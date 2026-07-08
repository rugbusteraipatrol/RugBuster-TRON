"""
tron_collector_v1.py - RugBuster TRON mainnet collector

TRON port of the RugBuster EVM collectors. Uses TronGrid/public full-node
HTTP APIs for TRC-20 metadata, deployments, account activity, and DEX events.

Run:
  python chains/tron/tron_collector_v1.py
  python chains/tron/tron_collector_v1.py <TRC20_CONTRACT_ADDRESS>
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg2
from psycopg2.extras import Json
import requests


def load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def clean_env_value(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip().strip('"').strip("'")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TRONGRID_API = clean_env_value("TRONGRID_API", "https://api.trongrid.io")
TRON_FULL_NODE = clean_env_value("TRON_FULL_NODE", TRONGRID_API)
TRONGRID_API_KEY = clean_env_value("TRONGRID_API_KEY")

OUTPUT_FILE = "syndicate_train_tron_v1.jsonl"
DATABASE_URL = os.getenv("DATABASE_URL")
DB_TABLE = "tron_scans"
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "20"))
RPC_TIMEOUT = int(os.getenv("RPC_TIMEOUT", "20"))
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "0.35"))
MIN_SCAN_DELAY_MINUTES = int(os.getenv("MIN_SCAN_DELAY_MINUTES", "2"))
MAX_SCAN_DELAY_MINUTES = int(os.getenv("MAX_SCAN_DELAY_MINUTES", "3"))
MAX_TOKENS_PER_DAY = int(os.getenv("MAX_TOKENS_PER_DAY", "120"))
RUN_UNTIL_DATE = os.getenv("RUN_UNTIL_DATE", "2099-12-31")
REQUIRE_TRC20_METADATA = os.getenv("REQUIRE_TRC20_METADATA", "true").strip().lower() in {"1", "true", "yes", "on"}
TRON_SCAN_LOG = Path(clean_env_value("TRON_SCAN_LOG", "tron_scan_log.md"))
TRON_STATE_FILE = Path(clean_env_value("TRON_STATE_FILE", "tron_collector_state.json"))
TRON_TELEGRAM_CHAT_ID = clean_env_value("TRON_TELEGRAM_CHAT_ID") or clean_env_value("TELEGRAM_CHAT_ID") or "@RugBusterTron"
TELEGRAM_BOT_TOKEN = clean_env_value("TRON_TELEGRAM_BOT_TOKEN") or clean_env_value("TELEGRAM_BOT_TOKEN")
RECENT_SCAN_FEED_URL = clean_env_value("RECENT_SCAN_FEED_URL", "https://web-production-376bf.up.railway.app/api/recent-scans")
RECENT_SCAN_INGEST_TOKEN = clean_env_value("RECENT_SCAN_INGEST_TOKEN")
GECKOTERMINAL_ENABLED = os.getenv("GECKOTERMINAL_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
GECKOTERMINAL_NEW_POOLS_URL = clean_env_value(
    "GECKOTERMINAL_NEW_POOLS_URL",
    "https://api.geckoterminal.com/api/v2/networks/tron/new_pools?include=base_token,quote_token",
)
GECKOTERMINAL_TOP_POOLS_ENABLED = os.getenv("GECKOTERMINAL_TOP_POOLS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
GECKOTERMINAL_POOL_PAGES = int(os.getenv("GECKOTERMINAL_POOL_PAGES", "3"))
GECKOTERMINAL_QUEUE_LOW_WATERMARK = int(os.getenv("GECKOTERMINAL_QUEUE_LOW_WATERMARK", "10"))
GECKOTERMINAL_NEW_POOLS_COOLDOWN_SECONDS = int(os.getenv("GECKOTERMINAL_NEW_POOLS_COOLDOWN_SECONDS", "300"))
GECKOTERMINAL_TOP_POOLS_COOLDOWN_SECONDS = int(os.getenv("GECKOTERMINAL_TOP_POOLS_COOLDOWN_SECONDS", "900"))
RESCAN_COOLDOWN_SECONDS = int(os.getenv("RESCAN_COOLDOWN_SECONDS", "2700"))
MAX_PENDING_QUEUE = int(os.getenv("MAX_PENDING_QUEUE", "250"))
FALLBACK_CONTRACT_SCAN_ENABLED = os.getenv("FALLBACK_CONTRACT_SCAN_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
DEX_EVENT_SCAN_ENABLED = os.getenv("DEX_EVENT_SCAN_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
DEX_FACTORY_ADDRESSES = [
    item.strip()
    for item in clean_env_value("TRON_DEX_FACTORY_ADDRESSES").split(",")
    if item.strip()
]
BASE_TOKEN_ADDRESSES = {
    "TNUC9Qb1rRpS5CbWLmNMxXBjyFoydXjWFR",  # WTRX
    "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",  # USDT
    "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8",  # USDC legacy
    "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7",  # WIN
}

TRONSCAN_ACCOUNT_URL = "https://tronscan.org/#/address/{address}"
TRONSCAN_TX_URL = "https://tronscan.org/#/transaction/{txid}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TRON-V1] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

creator_history = defaultdict(lambda: {"total": 0, "danger": 0, "warn": 0, "good": 0})
seen_contracts: dict[str, float] = {}
seen_token_names: list[str] = []
cross_chain_patterns: dict[str, dict[str, Any]] = {}
_last_api_call = [0.0]

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


# ---------------------------------------------------------------------------
# Address and ABI helpers
# ---------------------------------------------------------------------------
def b58encode(raw: bytes) -> str:
    num = int.from_bytes(raw, "big")
    encoded = ""
    while num:
        num, rem = divmod(num, 58)
        encoded = BASE58_ALPHABET[rem] + encoded
    pad = 0
    for byte in raw:
        if byte == 0:
            pad += 1
        else:
            break
    return "1" * pad + (encoded or "1")


def b58decode(value: str) -> bytes:
    num = 0
    for char in value:
        num = num * 58 + BASE58_ALPHABET.index(char)
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big")
    pad = len(value) - len(value.lstrip("1"))
    return b"\x00" * pad + raw


def tron_hex_to_base58(hex_addr: str) -> str:
    value = str(hex_addr or "").removeprefix("0x")
    if len(value) == 40:
        value = "41" + value
    if len(value) != 42:
        return ""
    payload = bytes.fromhex(value)
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return b58encode(payload + checksum)


def tron_base58_to_hex(address: str) -> str:
    try:
        raw = b58decode(address)
        if len(raw) != 25:
            return ""
        payload, checksum = raw[:-4], raw[-4:]
        expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        if checksum != expected or payload[0] != 0x41:
            return ""
        return payload.hex()
    except Exception:
        return ""


def normalize_tron_address(address: str) -> str:
    address = str(address or "").strip()
    if address.startswith("T") and tron_base58_to_hex(address):
        return address
    if address.startswith("41") or address.startswith("0x"):
        return tron_hex_to_base58(address)
    return address


def tron_address_from_abi_word(word: str) -> str:
    word = str(word or "").removeprefix("0x")
    if len(word) < 40:
        return ""
    return tron_hex_to_base58("41" + word[-40:])


def decode_abi_string(hex_value: str) -> str:
    data = str(hex_value or "").removeprefix("0x")
    if not data:
        return ""
    try:
        if len(data) == 64:
            return bytes.fromhex(data).rstrip(b"\x00").decode("utf-8", errors="ignore")
        offset = int(data[:64], 16) * 2
        length = int(data[offset:offset + 64], 16) * 2
        return bytes.fromhex(data[offset + 64:offset + 64 + length]).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def decode_abi_uint(hex_value: str) -> int:
    try:
        return int(str(hex_value or "0").removeprefix("0x")[:64] or "0", 16)
    except Exception:
        return 0


def normalize_timestamp_ms(value: Any) -> int:
    try:
        ts = int(float(value or 0))
    except (TypeError, ValueError):
        return 0
    if ts <= 0:
        return 0
    if ts > 10_000_000_000:
        return ts
    if ts > 1_000_000_000:
        return ts * 1000
    return 0


def timestamp_sec(value: Any) -> int:
    ts_ms = normalize_timestamp_ms(value)
    return int(ts_ms / 1000) if ts_ms else 0


def has_deployment_timestamp(token_data: dict[str, Any]) -> bool:
    source = str(token_data.get("source") or "")
    return bool(token_data.get("timestamp") and source == "contract_deploy")


def printable_token_text(value: str, max_len: int = 80) -> str:
    text = "".join(ch for ch in str(value or "").strip() if ch.isprintable())
    if not text or len(text) > max_len:
        return ""
    return text


def module_status(result: dict[str, Any]) -> str:
    return str(result.get("status") or "ok")


# ---------------------------------------------------------------------------
# HTTP / TronGrid helpers
# ---------------------------------------------------------------------------
def throttle() -> None:
    elapsed = time.time() - _last_api_call[0]
    if elapsed < RATE_LIMIT_DELAY:
        time.sleep(RATE_LIMIT_DELAY - elapsed)
    _last_api_call[0] = time.time()


def headers() -> dict[str, str]:
    result = {"Accept": "application/json"}
    if TRONGRID_API_KEY:
        result["TRON-PRO-API-KEY"] = TRONGRID_API_KEY
    return result


def full_node_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    throttle()
    resp = requests.post(
        f"{TRON_FULL_NODE.rstrip('/')}{path}",
        json=payload,
        headers=headers(),
        timeout=RPC_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def trongrid_get(path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    throttle()
    resp = requests.get(
        f"{TRONGRID_API.rstrip('/')}{path}",
        params=params or {},
        headers=headers(),
        timeout=API_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_latest_block() -> int:
    try:
        block = full_node_post("/wallet/getnowblock", {"visible": True})
        return int(block.get("block_header", {}).get("raw_data", {}).get("number", 0))
    except Exception as exc:
        log.warning("Latest block fetch failed: %s", exc)
        return 0


def get_block_by_num(block_num: int) -> dict[str, Any]:
    try:
        return full_node_post("/wallet/getblockbynum", {"num": block_num, "visible": True})
    except Exception as exc:
        log.warning("Block %s fetch failed: %s", block_num, exc)
        return {}


def get_transaction_info(txid: str) -> dict[str, Any]:
    try:
        return full_node_post("/wallet/gettransactioninfobyid", {"value": txid})
    except Exception:
        return {}


def trigger_constant_contract(contract: str, selector: str) -> str:
    owner = clean_env_value("TRON_CALLER_ADDRESS", "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE")
    payload = {
        "owner_address": owner,
        "contract_address": normalize_tron_address(contract),
        "function_selector": selector,
        "parameter": "",
        "visible": True,
    }
    result = full_node_post("/wallet/triggerconstantcontract", payload)
    values = result.get("constant_result") or []
    return values[0] if values else ""


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def _db_connect():
    if not DATABASE_URL:
        return None
    return psycopg2.connect(DATABASE_URL)


def init_database() -> None:
    conn = _db_connect()
    if conn is None:
        log.info("DATABASE_URL is not set; PostgreSQL writes disabled.")
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {DB_TABLE} (
                        id BIGSERIAL PRIMARY KEY,
                        contract_address TEXT NOT NULL UNIQUE,
                        chain TEXT,
                        label TEXT,
                        full_record JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
        log.info("PostgreSQL table ready: %s", DB_TABLE)
    finally:
        conn.close()


def save_to_postgres(record: dict[str, Any]) -> None:
    contract_address = record.get("contract_address")
    if not contract_address:
        return
    conn = _db_connect()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {DB_TABLE} (contract_address, chain, label, full_record)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (contract_address) DO UPDATE SET
                        chain = EXCLUDED.chain,
                        label = EXCLUDED.label,
                        full_record = EXCLUDED.full_record,
                        created_at = NOW()
                    """,
                    (contract_address, record.get("chain"), record.get("label"), Json(record)),
                )
        log.info("PostgreSQL upsert [%s]: %s", DB_TABLE, contract_address)
    except Exception as exc:
        log.error("PostgreSQL write failed: %s", exc)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Token data feeds
# ---------------------------------------------------------------------------
def get_trc20_metadata(contract: str) -> dict[str, Any]:
    contract = normalize_tron_address(contract)
    info = {
        "address": contract,
        "name": "",
        "symbol": "",
        "decimals": 0,
        "total_supply": 0,
        "metadata_source": "tron_constant_contract",
        "metadata_status": "unavailable",
        "metadata_error": "",
    }
    try:
        info["name"] = printable_token_text(decode_abi_string(trigger_constant_contract(contract, "name()")))
        info["symbol"] = printable_token_text(decode_abi_string(trigger_constant_contract(contract, "symbol()")), max_len=24)
        info["decimals"] = decode_abi_uint(trigger_constant_contract(contract, "decimals()"))
        info["total_supply"] = decode_abi_uint(trigger_constant_contract(contract, "totalSupply()"))
        info["metadata_status"] = "ok" if info["name"] and info["symbol"] else "incomplete"
    except Exception as exc:
        info["metadata_error"] = str(exc)
        log.debug("TRC-20 metadata failed for %s: %s", contract, exc)
    return info


def get_account_transactions_checked(address: str, limit: int = 50) -> tuple[list[dict[str, Any]], str, str]:
    try:
        data = trongrid_get(
            f"/v1/accounts/{normalize_tron_address(address)}/transactions",
            {"limit": limit, "only_confirmed": "true", "order_by": "block_timestamp,asc"},
        )
        rows = data.get("data", []) if isinstance(data.get("data"), list) else []
        return rows, "ok", ""
    except Exception as exc:
        return [], "error", str(exc)


def get_token_transfers_checked(address: str, limit: int = 200) -> tuple[list[dict[str, Any]], str, str]:
    try:
        data = trongrid_get(
            f"/v1/accounts/{normalize_tron_address(address)}/transactions/trc20",
            {"limit": limit, "only_confirmed": "true", "order_by": "block_timestamp,asc"},
        )
        rows = data.get("data", []) if isinstance(data.get("data"), list) else []
        return rows, "ok", ""
    except Exception as exc:
        return [], "error", str(exc)


def get_account_transactions(address: str, limit: int = 50) -> list[dict[str, Any]]:
    txs, _, _ = get_account_transactions_checked(address, limit)
    return txs


def get_token_transfers(address: str, limit: int = 200) -> list[dict[str, Any]]:
    transfers, _, _ = get_token_transfers_checked(address, limit)
    return transfers


def get_contract_events(contract: str, event_name: str, limit: int = 50) -> list[dict[str, Any]]:
    try:
        data = trongrid_get(
            f"/v1/contracts/{normalize_tron_address(contract)}/events",
            {"event_name": event_name, "limit": limit, "only_confirmed": "true", "order_by": "block_timestamp,desc"},
        )
        return data.get("data", []) if isinstance(data.get("data"), list) else []
    except Exception as exc:
        log.debug("Event fetch failed for %s %s: %s", contract, event_name, exc)
        return []


def get_trx_balance(address: str) -> float:
    try:
        account = full_node_post("/wallet/getaccount", {"address": normalize_tron_address(address), "visible": True})
        return int(account.get("balance", 0)) / 1_000_000
    except Exception:
        return 0.0


def get_contract_bytecode(contract: str) -> str:
    try:
        result = full_node_post("/wallet/getcontract", {"value": normalize_tron_address(contract), "visible": True})
        return str(result.get("bytecode") or "")
    except Exception:
        return ""


def get_new_token_deployments(from_block: int, to_block: int) -> list[dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for block_num in range(from_block, to_block + 1):
        block = get_block_by_num(block_num)
        ts = int(block.get("block_header", {}).get("raw_data", {}).get("timestamp", 0) / 1000)
        for tx in block.get("transactions", []) or []:
            txid = tx.get("txID", "")
            for item in tx.get("raw_data", {}).get("contract", []) or []:
                if item.get("type") != "CreateSmartContract":
                    continue
                value = item.get("parameter", {}).get("value", {})
                deployer = normalize_tron_address(value.get("owner_address", ""))
                contract_addr = normalize_tron_address(value.get("contract_address", ""))
                if not contract_addr:
                    receipt = get_transaction_info(txid)
                    contract_addr = normalize_tron_address(receipt.get("contract_address", ""))
                if contract_addr and contract_addr not in contracts:
                    contracts[contract_addr] = {
                        "address": contract_addr,
                        "name": "Unknown",
                        "symbol": "",
                        "deployer": deployer,
                        "block": block_num,
                        "timestamp": ts or int(time.time()),
                        "txid": txid,
                        "source": "contract_deploy",
                    }
                    log.info("New TRON contract: %s from %s", contract_addr, deployer)
        time.sleep(0.05)
    return list(contracts.values())


def token_id_to_address(token_id: str) -> str:
    raw = str(token_id or "").split("_")[-1]
    return normalize_tron_address(raw)


def choose_pair_token(token0: str, token1: str) -> str:
    token0 = normalize_tron_address(token0)
    token1 = normalize_tron_address(token1)
    if token0 and token0 not in BASE_TOKEN_ADDRESSES:
        return token0
    if token1 and token1 not in BASE_TOKEN_ADDRESSES:
        return token1
    return ""


def parse_geckoterminal_pool_tokens(payload: dict[str, Any], source: str) -> list[dict[str, Any]]:
    included = {item.get("id"): item for item in payload.get("included", []) if item.get("type") == "token"}
    tokens: dict[str, dict[str, Any]] = {}
    pools = payload.get("data", [])
    if not isinstance(pools, list):
        return []
    for pool in pools:
        rel = pool.get("relationships", {})
        base_id = rel.get("base_token", {}).get("data", {}).get("id", "")
        quote_id = rel.get("quote_token", {}).get("data", {}).get("id", "")
        base_addr = token_id_to_address(base_id)
        quote_addr = token_id_to_address(quote_id)
        token_addr = choose_pair_token(base_addr, quote_addr)
        if not token_addr or token_addr in tokens:
            continue
        token_item = included.get(base_id) or included.get(quote_id) or {}
        attrs = token_item.get("attributes", {})
        pool_attrs = pool.get("attributes", {})
        tokens[token_addr] = {
            "address": token_addr,
            "name": attrs.get("name") or pool_attrs.get("name", "Unknown").split("/", 1)[0].strip(),
            "symbol": attrs.get("symbol", ""),
            "deployer": "",
            "block": 0,
            "timestamp": int(time.time()),
            "pair": pool_attrs.get("address", ""),
            "source": source,
        }
    return list(tokens.values())


def get_geckoterminal_new_pool_tokens() -> list[dict[str, Any]]:
    if not GECKOTERMINAL_ENABLED:
        return []
    try:
        resp = requests.get(GECKOTERMINAL_NEW_POOLS_URL, timeout=API_TIMEOUT)
        if resp.status_code == 429:
            log.warning("GeckoTerminal new_pools rate limited.")
            return []
        resp.raise_for_status()
        return parse_geckoterminal_pool_tokens(resp.json(), "geckoterminal_new_pools")
    except Exception as exc:
        log.warning("GeckoTerminal new_pools failed: %s", exc)
        return []


def get_geckoterminal_top_pool_tokens() -> list[dict[str, Any]]:
    if not (GECKOTERMINAL_ENABLED and GECKOTERMINAL_TOP_POOLS_ENABLED):
        return []
    tokens: dict[str, dict[str, Any]] = {}
    for page in range(1, max(1, min(GECKOTERMINAL_POOL_PAGES, 5)) + 1):
        try:
            url = f"https://api.geckoterminal.com/api/v2/networks/tron/pools?include=base_token,quote_token&page={page}"
            resp = requests.get(url, timeout=API_TIMEOUT)
            if resp.status_code == 429:
                break
            resp.raise_for_status()
            for token in parse_geckoterminal_pool_tokens(resp.json(), f"geckoterminal_top_p{page}"):
                tokens.setdefault(token["address"], token)
            time.sleep(0.8)
        except Exception as exc:
            log.warning("GeckoTerminal pools page=%d failed: %s", page, exc)
            break
    return list(tokens.values())


def get_new_dex_pair_tokens() -> list[dict[str, Any]]:
    if not (DEX_EVENT_SCAN_ENABLED and DEX_FACTORY_ADDRESSES):
        return []
    tokens: dict[str, dict[str, Any]] = {}
    for factory in DEX_FACTORY_ADDRESSES:
        for event in get_contract_events(factory, "PairCreated", limit=100):
            result = event.get("result", {})
            token0 = normalize_tron_address(result.get("token0", ""))
            token1 = normalize_tron_address(result.get("token1", ""))
            token_addr = choose_pair_token(token0, token1)
            if not token_addr or token_addr in tokens:
                continue
            meta = get_trc20_metadata(token_addr)
            tokens[token_addr] = {
                "address": token_addr,
                "name": meta.get("name") or "Unknown",
                "symbol": meta.get("symbol") or "",
                "deployer": "",
                "block": int(event.get("block_number", 0)),
                "timestamp": int(event.get("block_timestamp", int(time.time() * 1000)) / 1000),
                "pair": normalize_tron_address(result.get("pair", "")),
                "source": "tron_dex_pair_event",
            }
    return list(tokens.values())


# ---------------------------------------------------------------------------
# CIA / V5 / V6 modules
# ---------------------------------------------------------------------------
def update_creator_history(creator: str, label: str) -> None:
    if not creator:
        return
    creator_history[creator]["total"] += 1
    if label in {"DANGER", "WARN", "GOOD"}:
        creator_history[creator][label.lower()] += 1


def get_creator_stats(creator: str) -> dict[str, Any]:
    if not creator or creator not in creator_history:
        return {"total": 0, "danger": 0, "rug_rate": 0.0}
    stats = creator_history[creator]
    total = stats["total"]
    danger = stats["danger"]
    return {"total": total, "danger": danger, "rug_rate": round((danger / total * 100) if total else 0.0, 1)}


def compute_wallet_pattern_hash(deploy_ts: int, tx_amounts: list[float], holder_count: int) -> str:
    hour_bucket = (deploy_ts // 3600 // 4) % 6
    amount_sig = round(sum(tx_amounts[:5]) / max(len(tx_amounts[:5]), 1), 1) if tx_amounts else 0
    holder_bucket = "low" if holder_count < 10 else "mid" if holder_count < 100 else "high"
    return hashlib.md5(f"{hour_bucket}_{amount_sig}_{holder_bucket}".encode()).hexdigest()[:12]


def detect_cross_chain_match(deploy_ts: int, tx_amounts: list[float], holder_count: int, chain: str = "TRON") -> dict[str, Any]:
    pattern = compute_wallet_pattern_hash(deploy_ts, tx_amounts, holder_count)
    entry = cross_chain_patterns.setdefault(pattern, {"chains": [chain], "count": 0, "first_seen": deploy_ts})
    cross_chain = chain not in entry["chains"] or len(entry["chains"]) > 1
    if chain not in entry["chains"]:
        entry["chains"].append(chain)
    entry["count"] += 1
    return {"pattern_hash": pattern, "cross_chain_match": cross_chain, "match_chains": entry["chains"], "match_count": entry["count"]}


SCAM_NAME_PATTERNS = [
    "killer", "2.0", "reborn", "moon", "elon", "musk", "trump", "inu", "doge",
    "pepe", "shiba", "wojak", "chad", "ai", "gpt", "agent", "100x", "1000x",
    "official", "real", "v2", "v3", "sun", "just", "trx", "tron",
]

KNOWN_BRAND_TOKENS = {
    ("bitcoin", "btc"),
    ("ethereum", "eth"),
    ("litecoin", "ltc"),
    ("dogecoin", "doge"),
    ("cardano", "ada"),
    ("ripple", "xrp"),
    ("solana", "sol"),
    ("binance coin", "bnb"),
    ("avalanche", "avax"),
    ("chainlink", "link"),
    ("polygon", "matic"),
    ("polkadot", "dot"),
}


def analyze_name_stylometry(token_name: str, ticker: str) -> dict[str, Any]:
    name_lower = (token_name or "").lower()
    ticker_lower = (ticker or "").lower()
    matched = [p for p in SCAM_NAME_PATTERNS if p in name_lower or p in ticker_lower]
    brand_match = next(
        (
            {"name": brand_name, "symbol": brand_symbol.upper()}
            for brand_name, brand_symbol in KNOWN_BRAND_TOKENS
            if name_lower == brand_name or ticker_lower == brand_symbol
        ),
        None,
    )
    result = {
        "name_scam_score": min(len(matched) * 25 + (75 if brand_match else 0), 100),
        "matched_patterns": matched,
        "brand_impersonation": bool(brand_match),
        "impersonated_brand": brand_match or {},
        "similar_to_previous": False,
        "most_similar_name": "",
        "similarity_score": 0.0,
    }
    max_sim, most_sim = 0.0, ""
    for previous in seen_token_names[-200:]:
        a, b = set(name_lower), set(previous.lower())
        sim = len(a & b) / len(a | b) if a and b else 0.0
        if sim > max_sim:
            max_sim, most_sim = sim, previous
    if max_sim > 0.8:
        result.update({"similar_to_previous": True, "most_similar_name": most_sim, "similarity_score": round(max_sim, 2)})
    if token_name:
        seen_token_names.append(token_name)
    return result


def detect_funding_origin(deployer: str, deploy_ts: int) -> dict[str, Any]:
    if not deployer:
        return {
            "status": "unavailable",
            "error": "missing_deployer",
            "funding_tx_count": None,
            "first_funding_age_sec": None,
            "fresh_wallet": False,
            "all_fresh": False,
            "hop_count": 0,
            "funders": [],
        }
    if not deploy_ts:
        return {
            "status": "unavailable",
            "error": "missing_deployment_timestamp",
            "funding_tx_count": None,
            "first_funding_age_sec": None,
            "fresh_wallet": False,
            "all_fresh": False,
            "hop_count": 0,
            "funders": [],
        }
    txs, status, error = get_account_transactions_checked(deployer, limit=50)
    if status != "ok":
        return {
            "status": "error",
            "error": error,
            "funding_tx_count": None,
            "first_funding_age_sec": None,
            "fresh_wallet": False,
            "all_fresh": False,
            "hop_count": 0,
            "funders": [],
        }
    incoming = []
    for tx in txs:
        raw = tx.get("raw_data", {}).get("contract", [{}])[0].get("parameter", {}).get("value", {})
        to_addr = normalize_tron_address(raw.get("to_address", ""))
        amount = int(raw.get("amount", 0)) / 1_000_000
        ts = timestamp_sec(tx.get("block_timestamp"))
        if to_addr == deployer and ts <= deploy_ts:
            incoming.append({"from": normalize_tron_address(raw.get("owner_address", "")), "amount": amount, "timestamp": ts})
    first_funding_age = deploy_ts - incoming[-1]["timestamp"] if incoming else -1
    return {
        "status": "ok",
        "error": "",
        "funding_tx_count": len(incoming),
        "first_funding_age_sec": first_funding_age,
        "fresh_wallet": 0 <= first_funding_age < 3600,
        "all_fresh": bool(incoming) and first_funding_age < 3600,
        "hop_count": min(len(incoming), 5),
        "funders": incoming[-5:],
    }


def detect_deployment_latency(token: str, deploy_ts: int) -> dict[str, Any]:
    if not deploy_ts:
        return {
            "status": "unavailable",
            "error": "missing_deployment_timestamp",
            "first_transfer_ts": None,
            "latency_ms": None,
            "is_sniped": False,
        }
    transfers, status, error = get_token_transfers_checked(token, limit=50)
    if status != "ok":
        return {
            "status": "error",
            "error": error,
            "first_transfer_ts": None,
            "latency_ms": None,
            "is_sniped": False,
        }
    first_ts = 0
    for transfer in transfers:
        ts = timestamp_sec(transfer.get("block_timestamp"))
        if ts and (not first_ts or ts < first_ts):
            first_ts = ts
    if not first_ts:
        return {
            "status": "no_transfers",
            "error": "",
            "first_transfer_ts": None,
            "latency_ms": None,
            "is_sniped": False,
        }
    latency_ms = (first_ts - deploy_ts) * 1000
    if latency_ms < 0:
        return {
            "status": "invalid",
            "error": "first_transfer_before_deployment_timestamp",
            "first_transfer_ts": first_ts,
            "latency_ms": None,
            "is_sniped": False,
        }
    return {"status": "ok", "error": "", "first_transfer_ts": first_ts, "latency_ms": latency_ms, "is_sniped": latency_ms <= 30_000}


def detect_tx_entropy(token: str) -> dict[str, Any]:
    transfers, status, error = get_token_transfers_checked(token, limit=200)
    if status != "ok":
        return {
            "status": "error",
            "error": error,
            "tx_count": None,
            "unique_wallets": None,
            "dominant_amount": None,
            "dominant_amount_ratio": None,
            "is_bot_pattern": False,
        }
    amounts = []
    wallets = []
    for transfer in transfers:
        value = transfer.get("value")
        decimals = int(transfer.get("token_info", {}).get("decimals") or 0)
        try:
            amounts.append(int(value) / (10 ** decimals if decimals else 1))
        except Exception:
            pass
        wallets.extend([transfer.get("from"), transfer.get("to")])
    rounded = [round(amount, 4) for amount in amounts if amount > 0]
    dominant_amount, dominant_count = (0, 0)
    if rounded:
        dominant_amount, dominant_count = Counter(rounded).most_common(1)[0]
    unique_wallets = len({normalize_tron_address(w) for w in wallets if w})
    repeated_ratio = dominant_count / max(len(rounded), 1)
    return {
        "status": "ok",
        "error": "",
        "tx_count": len(transfers),
        "unique_wallets": unique_wallets,
        "dominant_amount": dominant_amount,
        "dominant_amount_ratio": round(repeated_ratio, 3),
        "is_bot_pattern": len(rounded) >= 10 and repeated_ratio >= 0.35,
    }


def detect_wash_pattern(token: str) -> dict[str, Any]:
    transfers, status, error = get_token_transfers_checked(token, limit=200)
    if status != "ok":
        return {
            "status": "error",
            "error": error,
            "wash_detected": False,
            "reciprocal_edges": None,
            "edge_count": None,
        }
    edges = Counter()
    for transfer in transfers:
        src = normalize_tron_address(transfer.get("from", ""))
        dst = normalize_tron_address(transfer.get("to", ""))
        if src and dst:
            edges[(src, dst)] += 1
    reciprocal = 0
    for (src, dst), count in edges.items():
        if edges.get((dst, src), 0):
            reciprocal += min(count, edges[(dst, src)])
    return {"status": "ok", "error": "", "wash_detected": reciprocal >= 4, "reciprocal_edges": reciprocal, "edge_count": len(edges)}


def detect_holder_cluster_age(token: str) -> dict[str, Any]:
    transfers, status, error = get_token_transfers_checked(token, limit=200)
    if status != "ok":
        return {
            "status": "error",
            "error": error,
            "total_checked": None,
            "wallets_with_age": None,
            "fresh_wallet_count": None,
            "fresh_wallet_ratio": None,
            "median_age_sec": None,
            "is_bot_farm": False,
        }
    wallets = []
    for transfer in transfers:
        wallets.extend([normalize_tron_address(transfer.get("from", "")), normalize_tron_address(transfer.get("to", ""))])
    unique_wallets = [w for w in dict.fromkeys(wallets) if w and w not in BASE_TOKEN_ADDRESSES][:25]
    fresh = 0
    ages = []
    now = int(time.time())
    for wallet in unique_wallets:
        txs, wallet_status, _ = get_account_transactions_checked(wallet, limit=10)
        if wallet_status != "ok":
            continue
        first = min([timestamp_sec(tx.get("block_timestamp")) for tx in txs if tx.get("block_timestamp")] or [0])
        if first:
            age = now - first
            ages.append(age)
            if age < 86_400:
                fresh += 1
    fresh_ratio = fresh / max(len(ages), 1)
    return {
        "status": "ok",
        "error": "",
        "total_checked": len(unique_wallets),
        "wallets_with_age": len(ages),
        "fresh_wallet_count": fresh,
        "fresh_wallet_ratio": round(fresh_ratio, 3),
        "median_age_sec": int(statistics.median(ages)) if ages else -1,
        "is_bot_farm": len(ages) >= 5 and fresh_ratio >= 0.6,
    }


BACKDOOR_SIGNATURES = {
    "8da5cb5b": "owner()",
    "f2fde38b": "transferOwnership(address)",
    "715018a6": "renounceOwnership()",
    "42966c68": "burn(uint256)",
    "40c10f19": "mint(address,uint256)",
    "3ccfd60b": "withdraw()",
    "2e1a7d4d": "withdraw(uint256)",
    "51cff8d9": "withdrawToken(address)",
    "3659cfe6": "upgradeTo(address)",
    "8456cb59": "pause()",
    "3f4ba83a": "unpause()",
    "044df020": "blacklist(address)",
}


def detect_contract_backdoor(token: str) -> dict[str, Any]:
    bytecode = get_contract_bytecode(token).lower()
    if not bytecode:
        return {
            "status": "unavailable",
            "error": "bytecode_unavailable",
            "has_backdoor": False,
            "backdoor_functions": [],
            "has_mint_function": False,
            "has_pause_function": False,
            "has_blacklist": False,
            "has_drain_function": False,
            "backdoor_risk_score": 0,
        }
    found = [name for sig, name in BACKDOOR_SIGNATURES.items() if sig in bytecode]
    return {
        "status": "ok",
        "error": "",
        "has_backdoor": bool(found),
        "backdoor_functions": found,
        "has_mint_function": any("mint" in name for name in found),
        "has_pause_function": any("pause" in name for name in found),
        "has_blacklist": any("blacklist" in name.lower() for name in found),
        "has_drain_function": any("withdraw" in name for name in found),
        "backdoor_risk_score": min(len(found) * 15, 100),
    }


def predict_lifecycle(cia: dict[str, Any], creator_rug_rate: float) -> dict[str, Any]:
    signals = sum([
        cia.get("latency", {}).get("is_sniped", False),
        cia.get("entropy", {}).get("is_bot_pattern", False),
        cia.get("wash", {}).get("wash_detected", False),
        cia.get("cluster", {}).get("is_bot_farm", False),
        cia.get("funding", {}).get("all_fresh", False),
    ])
    if signals >= 4:
        return {"estimated_rug_minutes": 15, "confidence": 0.87, "prediction_text": "Rug expected within 15 minutes"}
    if signals >= 3 and creator_rug_rate > 50:
        return {"estimated_rug_minutes": 45, "confidence": 0.72, "prediction_text": "Rug expected within 45 minutes"}
    if signals >= 3:
        return {"estimated_rug_minutes": 120, "confidence": 0.61, "prediction_text": "Rug expected within 2 hours"}
    if signals >= 2:
        return {"estimated_rug_minutes": 360, "confidence": 0.45, "prediction_text": "Possible rug within 6 hours"}
    return {"estimated_rug_minutes": -1, "confidence": 0.0, "prediction_text": "No imminent rug signals"}


def calculate_risk(meta: dict[str, Any], cia: dict[str, Any], v5: dict[str, Any], v6: dict[str, Any], deployer_balance: Optional[float]) -> tuple[int, list[str]]:
    risk = 15
    reasons = []
    style = v5.get("name_style", {})
    backdoor = v6.get("backdoor", {})
    entropy = cia.get("entropy", {})
    wash = cia.get("wash", {})
    backdoor_score = int(backdoor.get("backdoor_risk_score", 0) or 0)
    checks = [
        (cia.get("funding", {}).get("all_fresh"), 16, "fresh deployer funding"),
        (cia.get("latency", {}).get("is_sniped"), 12, "sniped first transfer"),
        (entropy.get("is_bot_pattern"), 14, "bot-like transfer entropy"),
        (wash.get("wash_detected"), 18, "wash transfer pattern"),
        (cia.get("cluster", {}).get("is_bot_farm"), 16, "fresh holder cluster"),
        (style.get("name_scam_score", 0) >= 50, 10, "scam-name stylometry"),
        (style.get("brand_impersonation"), 22, f"brand impersonation: {style.get('impersonated_brand', {}).get('name', 'known asset')}"),
        (isinstance(deployer_balance, (int, float)) and deployer_balance < 25, 6, "low deployer TRX balance"),
        (not meta.get("name") or not meta.get("symbol"), 10, "missing TRC-20 metadata"),
    ]
    for active, points, reason in checks:
        if active:
            risk += points
            reasons.append(reason)
    if backdoor.get("has_backdoor") or backdoor_score >= 40:
        risk += min(35, max(18, backdoor_score // 2))
        reasons.append(f"bytecode backdoor risk {backdoor_score}/100")
    tx_count = entropy.get("tx_count")
    unique_wallets = entropy.get("unique_wallets")
    if isinstance(tx_count, int) and isinstance(unique_wallets, int) and 0 < tx_count <= 25 and unique_wallets <= 25:
        risk += 8
        reasons.append(f"thin TRON activity: {tx_count} tx / {unique_wallets} wallets")
    edge_count = wash.get("edge_count")
    if isinstance(edge_count, int) and edge_count >= 15 and not wash.get("wash_detected"):
        risk += 6
        reasons.append(f"thin transfer graph edges: {edge_count}")
    unavailable = {
        module_status(cia.get("funding", {})),
        module_status(cia.get("latency", {})),
    }
    if (style.get("brand_impersonation") or backdoor_score >= 40) and unavailable & {"error", "unavailable", "invalid"}:
        risk += 8
        reasons.append("missing provenance on elevated-risk token")
    return min(risk, 100), reasons


def risk_status_from_percent(risk: int) -> str:
    if risk >= 70:
        return "DANGER"
    if risk >= 40:
        return "WARN"
    return "GOOD"


def run_cia_analysis(token: str, deployer: str, deploy_ts: int) -> dict[str, Any]:
    return {
        "funding": detect_funding_origin(deployer, deploy_ts),
        "latency": detect_deployment_latency(token, deploy_ts),
        "entropy": detect_tx_entropy(token),
        "wash": detect_wash_pattern(token),
        "cluster": detect_holder_cluster_age(token),
    }


def run_v5_analysis(token_name: str, symbol: str, deploy_ts: int, tx_amounts: list[float], holder_count: int, cia: dict[str, Any], creator_rug_rate: float) -> dict[str, Any]:
    return {
        "cross_chain": detect_cross_chain_match(deploy_ts, tx_amounts, holder_count, "TRON"),
        "lifecycle": predict_lifecycle(cia, creator_rug_rate),
        "name_style": analyze_name_stylometry(token_name, symbol),
    }


def run_v6_analysis(token: str) -> dict[str, Any]:
    return {"backdoor": detect_contract_backdoor(token)}


def confidence_from_modules(cia: dict[str, Any], v6: dict[str, Any]) -> dict[str, Any]:
    modules = {
        "funding_origin": cia.get("funding", {}),
        "deployment_latency": cia.get("latency", {}),
        "tx_entropy": cia.get("entropy", {}),
        "wash_pattern": cia.get("wash", {}),
        "holder_cluster_age": cia.get("cluster", {}),
        "contract_backdoor": v6.get("backdoor", {}),
    }
    missing = [
        name
        for name, result in modules.items()
        if module_status(result) in {"error", "unavailable", "invalid"}
    ]
    return {
        "level": "LOW" if len(missing) >= 3 else "NORMAL",
        "missing_module_count": len(missing),
        "missing_modules": missing,
    }


# ---------------------------------------------------------------------------
# Output integrations
# ---------------------------------------------------------------------------
def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def append_markdown_scan_log(record: dict[str, Any]) -> None:
    line = (
        f"- {datetime.now(timezone.utc).isoformat()} | {record['label']} | "
        f"{record['risk_percent']}% | {record.get('token_name')} ({record.get('symbol')}) | "
        f"{TRONSCAN_ACCOUNT_URL.format(address=record['contract_address'])}\n"
    )
    with TRON_SCAN_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line)


def send_telegram_alert(record: dict[str, Any]) -> None:
    if not TELEGRAM_BOT_TOKEN:
        return
    flags = ", ".join(record.get("risk_reasons", [])[:5]) or "No major flags"
    text = (
        f"RugBuster TRON Scan\n"
        f"{record['label']} | Risk {record['risk_percent']}%\n"
        f"{record.get('token_name')} ({record.get('symbol')})\n"
        f"Token: {record['contract_address']}\n"
        f"Flags: {flags}\n"
        f"Tronscan: {TRONSCAN_ACCOUNT_URL.format(address=record['contract_address'])}"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TRON_TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True},
            timeout=API_TIMEOUT,
        ).raise_for_status()
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", "unknown")
        log.warning("Telegram alert failed with status=%s for chat=%s", status, TRON_TELEGRAM_CHAT_ID)


def publish_recent_scan(record: dict[str, Any]) -> None:
    if not (RECENT_SCAN_FEED_URL and RECENT_SCAN_INGEST_TOKEN):
        return
    try:
        requests.post(
            RECENT_SCAN_FEED_URL,
            json=record,
            headers={"Authorization": f"Bearer {RECENT_SCAN_INGEST_TOKEN}"},
            timeout=API_TIMEOUT,
        )
    except Exception as exc:
        log.debug("Recent scan feed failed: %s", exc)


def load_daily_state() -> dict[str, Any]:
    if not TRON_STATE_FILE.exists():
        return {"date": datetime.now(timezone.utc).date().isoformat(), "tokens": 0}
    try:
        return json.loads(TRON_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"date": datetime.now(timezone.utc).date().isoformat(), "tokens": 0}


def save_daily_state(state: dict[str, Any]) -> None:
    TRON_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def daily_limits_open(state: dict[str, Any]) -> bool:
    today = datetime.now(timezone.utc).date().isoformat()
    if state.get("date") != today:
        state.clear()
        state.update({"date": today, "tokens": 0})
        save_daily_state(state)
    return int(state.get("tokens", 0)) < MAX_TOKENS_PER_DAY


def run_until_reached() -> bool:
    try:
        return datetime.now(timezone.utc).date() > datetime.fromisoformat(RUN_UNTIL_DATE).date()
    except Exception:
        return False


def process_token(token_data: dict[str, Any], output_path: Path) -> Optional[dict[str, Any]]:
    address = normalize_tron_address(token_data.get("address", ""))
    if not address:
        return None
    meta = get_trc20_metadata(address)
    if token_data.get("name") and not meta.get("name"):
        meta["name"] = printable_token_text(token_data.get("name"))
        meta["metadata_source"] = "feed_fallback"
        meta["metadata_status"] = "fallback"
    if token_data.get("symbol") and not meta.get("symbol"):
        meta["symbol"] = printable_token_text(token_data.get("symbol"), max_len=24)
        meta["metadata_source"] = "feed_fallback"
        meta["metadata_status"] = "fallback"
    if REQUIRE_TRC20_METADATA and (not meta.get("name") or not meta.get("symbol")):
        log.info("Skipping %s without valid TRC-20 metadata.", address)
        return None

    deployer = normalize_tron_address(token_data.get("deployer", ""))
    deploy_ts = timestamp_sec(token_data.get("timestamp")) if has_deployment_timestamp(token_data) else 0
    deployer_balance = get_trx_balance(deployer) if deployer else None
    creator_stats = get_creator_stats(deployer)
    cia = run_cia_analysis(address, deployer, deploy_ts)
    dominant_amount = cia.get("entropy", {}).get("dominant_amount")
    tx_amounts = [dominant_amount] if isinstance(dominant_amount, (int, float)) else []
    holder_count = cia.get("cluster", {}).get("total_checked")
    holder_count = holder_count if isinstance(holder_count, int) else 0
    v5 = run_v5_analysis(meta.get("name", ""), meta.get("symbol", ""), deploy_ts, tx_amounts, holder_count, cia, creator_stats["rug_rate"])
    v6 = run_v6_analysis(address)
    risk_percent, risk_reasons = calculate_risk(meta, cia, v5, v6, deployer_balance)
    label = risk_status_from_percent(risk_percent)
    confidence = confidence_from_modules(cia, v6)
    if confidence["level"] == "LOW":
        risk_reasons.append("low confidence: insufficient TRON data")
        if label == "GOOD":
            label = "WARN"
        risk_percent = max(risk_percent, 40)

    record = {
        "chain": "TRON",
        "collector": "tron_collector_v1",
        "contract_address": address,
        "token_name": meta.get("name") or "Unknown",
        "symbol": meta.get("symbol") or "",
        "decimals": meta.get("decimals", 0),
        "total_supply": str(meta.get("total_supply", 0)),
        "deployer": deployer,
        "deployer_balance_trx": deployer_balance,
        "deploy_timestamp": deploy_ts or None,
        "metadata_source": meta.get("metadata_source"),
        "metadata_status": meta.get("metadata_status"),
        "metadata_error": meta.get("metadata_error", ""),
        "source": token_data.get("source", "unknown"),
        "pair": token_data.get("pair", ""),
        "label": label,
        "risk_percent": risk_percent,
        "risk_reasons": risk_reasons,
        "creator_stats": creator_stats,
        "confidence": confidence,
        "cia": cia,
        "v5": v5,
        "v6": v6,
        "scan_timestamp": int(time.time()),
    }
    append_jsonl(output_path, record)
    save_to_postgres(record)
    append_markdown_scan_log(record)
    send_telegram_alert(record)
    publish_recent_scan(record)
    update_creator_history(deployer, label)
    seen_contracts[address] = time.time()
    log.info("Scanned %s (%s): %s risk=%d%%", record["token_name"], record["symbol"], label, risk_percent)
    return record


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------
def poll_loop(output_path: Path) -> None:
    log.info("=" * 60)
    log.info("  RugBuster TRON Collector V1 - CIA/V5/V6 Intel")
    log.info("  TronGrid    : %s", TRONGRID_API)
    log.info("  DB table    : %s", DB_TABLE)
    log.info("  Telegram    : %s", TRON_TELEGRAM_CHAT_ID)
    log.info("  Campaign    : until %s, %d tokens/day", RUN_UNTIL_DATE, MAX_TOKENS_PER_DAY)
    log.info("  Output      : %s (%d existing)", output_path.absolute(), count_lines(output_path))
    log.info("=" * 60)

    current_block = get_latest_block()
    if not current_block:
        log.error("Could not fetch current TRON block.")
        return
    pending_tokens: list[dict[str, Any]] = []
    queued_contracts: set[str] = set()
    last_new_pool_refill_at = 0.0
    last_top_pool_refill_at = 0.0
    next_scan_at = 0.0

    def enqueue(token_data: dict[str, Any]) -> None:
        address = normalize_tron_address(token_data.get("address", ""))
        if not address or address in queued_contracts:
            return
        if time.time() - float(seen_contracts.get(address, 0.0)) < RESCAN_COOLDOWN_SECONDS:
            return
        if len(pending_tokens) >= MAX_PENDING_QUEUE:
            log.info("Queue limit reached; dropping %s from %s.", address, token_data.get("source", "unknown"))
            return
        token_data["address"] = address
        pending_tokens.append(token_data)
        queued_contracts.add(address)

    while True:
        try:
            state = load_daily_state()
            if not daily_limits_open(state):
                if run_until_reached():
                    log.warning("Campaign end reached (%s). Collector stopped.", RUN_UNTIL_DATE)
                    return
                time.sleep(POLL_INTERVAL)
                continue

            new_block = get_latest_block()
            if not new_block or new_block <= current_block:
                time.sleep(POLL_INTERVAL)
                continue

            if len(pending_tokens) < GECKOTERMINAL_QUEUE_LOW_WATERMARK and time.time() - last_new_pool_refill_at >= GECKOTERMINAL_NEW_POOLS_COOLDOWN_SECONDS:
                gecko_tokens = get_geckoterminal_new_pool_tokens()
                last_new_pool_refill_at = time.time()
                log.info("Found %d GeckoTerminal TRON new-pool tokens.", len(gecko_tokens))
                for token in gecko_tokens:
                    enqueue(token)

            if len(pending_tokens) < GECKOTERMINAL_QUEUE_LOW_WATERMARK and time.time() - last_top_pool_refill_at >= GECKOTERMINAL_TOP_POOLS_COOLDOWN_SECONDS:
                top_tokens = get_geckoterminal_top_pool_tokens()
                last_top_pool_refill_at = time.time()
                log.info("Found %d GeckoTerminal TRON top-pool refill tokens.", len(top_tokens))
                for token in top_tokens:
                    enqueue(token)

            for token in get_new_dex_pair_tokens():
                enqueue(token)

            if FALLBACK_CONTRACT_SCAN_ENABLED and len(pending_tokens) < GECKOTERMINAL_QUEUE_LOW_WATERMARK:
                deployments = get_new_token_deployments(current_block, new_block)
                log.info("Found %d fallback contract deployments in blocks %d-%d.", len(deployments), current_block, new_block)
                for token in deployments:
                    enqueue(token)

            now = time.time()
            if pending_tokens and now >= next_scan_at:
                token_data = pending_tokens.pop(0)
                queued_contracts.discard(token_data.get("address", ""))
                record = process_token(token_data, output_path)
                if record:
                    state = load_daily_state()
                    state["tokens"] = int(state.get("tokens", 0)) + 1
                    save_daily_state(state)
                    delay_minutes = random.randint(MIN_SCAN_DELAY_MINUTES, MAX_SCAN_DELAY_MINUTES)
                    next_scan_at = time.time() + delay_minutes * 60
                    log.info("Next scan in %d min. Queue=%d daily=%s/%s.", delay_minutes, len(pending_tokens), state.get("tokens", 0), MAX_TOKENS_PER_DAY)
                else:
                    next_scan_at = time.time()

            current_block = new_block
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log.error("Poll loop failed: %s. Continuing in 30s.", exc)
            time.sleep(30)


def scan_single(address: str) -> None:
    token = {"address": normalize_tron_address(address), "timestamp": int(time.time()), "source": "cli"}
    record = process_token(token, Path(OUTPUT_FILE))
    if record:
        print(json.dumps(record, indent=2, default=str))


def main() -> None:
    import sys

    init_database()
    if len(sys.argv) > 1:
        scan_single(sys.argv[1])
        return
    poll_loop(Path(OUTPUT_FILE))


if __name__ == "__main__":
    main()
