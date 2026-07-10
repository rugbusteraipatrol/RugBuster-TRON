"""
multichain_worker.py - single Railway worker for RugBuster collectors.

Runs AVAX, BNB, Base, and TRON collectors inside one long-lived Python process.
Each chain gets a short turn: refill its queue from low-cost token feeds, then
process at most one queued token when that chain's scan delay has elapsed.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


RUN_UNTIL_DATE = os.getenv("RUN_UNTIL_DATE", "2099-12-31")
CHAIN_TURN_SLEEP_SECONDS = int(os.getenv("CONSOLIDATED_CHAIN_TURN_SLEEP_SECONDS", "5"))
REFILL_LOW_WATERMARK = int(os.getenv("CONSOLIDATED_QUEUE_LOW_WATERMARK", os.getenv("GECKOTERMINAL_QUEUE_LOW_WATERMARK", "10")))
MAX_QUEUE_PER_CHAIN = int(os.getenv("CONSOLIDATED_MAX_QUEUE_PER_CHAIN", os.getenv("MAX_PENDING_QUEUE", "250")))
NEW_POOLS_COOLDOWN_SECONDS = int(os.getenv("CONSOLIDATED_NEW_POOLS_COOLDOWN_SECONDS", os.getenv("GECKOTERMINAL_NEW_POOLS_COOLDOWN_SECONDS", "300")))
TOP_POOLS_COOLDOWN_SECONDS = int(os.getenv("CONSOLIDATED_TOP_POOLS_COOLDOWN_SECONDS", os.getenv("GECKOTERMINAL_TOP_POOLS_COOLDOWN_SECONDS", "900")))
DEX_SCAN_ENABLED = env_bool("CONSOLIDATED_DEX_SCAN_ENABLED", "false")
FALLBACK_SCAN_ENABLED = env_bool("CONSOLIDATED_FALLBACK_SCAN_ENABLED", "false")
RESCAN_COOLDOWN_SECONDS = int(os.getenv("RESCAN_COOLDOWN_SECONDS", "2700"))

os.environ.setdefault("RUN_UNTIL_DATE", RUN_UNTIL_DATE)
os.environ.setdefault("ONCHAIN_LOG_ENABLED", "false")
os.environ.setdefault("BOT_PUBLISH_TO_REGISTRY", "false")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MULTICHAIN] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass
class ChainConfig:
    name: str
    module_path: str
    process_func: str
    output_file: str
    gecko_network: str
    onchain_env_prefix: str


@dataclass
class ChainRuntime:
    config: ChainConfig
    module: Any
    process: Callable[[dict[str, Any], Path], dict[str, Any] | None]
    output_path: Path
    pending: list[dict[str, Any]] = field(default_factory=list)
    queued: set[str] = field(default_factory=set)
    seen_at: dict[str, float] = field(default_factory=dict)
    current_block: int = 0
    next_scan_at: float = 0.0
    last_new_pool_refill_at: float = 0.0
    last_top_pool_refill_at: float = 0.0
    last_dex_refill_at: float = 0.0
    last_fallback_refill_at: float = 0.0
    seeded: bool = False

    def label(self) -> str:
        return self.config.name.upper()

    def normalize_address(self, address: str) -> str:
        normalizer = getattr(self.module, "normalize_tron_address", None)
        if callable(normalizer):
            return normalizer(address)
        return str(address or "").lower()

    def enqueue(self, token_data: dict[str, Any]) -> None:
        address = self.normalize_address(token_data.get("address", ""))
        if not address or address in self.queued:
            return
        if time.time() - float(self.seen_at.get(address, 0.0)) < RESCAN_COOLDOWN_SECONDS:
            return
        if len(self.pending) >= MAX_QUEUE_PER_CHAIN:
            log.info("%s queue full; dropping %s from %s", self.label(), address[:12], token_data.get("source", "unknown"))
            return
        token_data["address"] = address
        self.pending.append(token_data)
        self.queued.add(address)

    def init(self) -> None:
        self.module.init_database()
        try:
            self.current_block = int(self.module.get_latest_block() or 0)
        except Exception as exc:
            log.warning("%s initial block fetch failed: %s", self.label(), exc)
        log.info("%s ready: table=%s start_block=%s output=%s", self.label(), getattr(self.module, "DB_TABLE", "?"), self.current_block, self.output_path)
        self.enqueue_seed_tokens()

    def enqueue_seed_tokens(self) -> None:
        if self.seeded:
            return
        self.seeded = True
        raw = os.getenv(f"{self.config.onchain_env_prefix}_SEED_TOKENS", "")
        for address in [item.strip() for item in raw.split(",") if item.strip()]:
            self.enqueue({
                "address": address,
                "name": "Unknown",
                "symbol": "",
                "deployer": "",
                "block": self.current_block,
                "timestamp": int(time.time()),
                "source": "consolidated_seed",
            })
        if raw:
            log.info("%s seeded queue=%d from %s_SEED_TOKENS", self.label(), len(self.pending), self.config.onchain_env_prefix)

    def refill_from_gecko(self) -> None:
        now = time.time()
        if len(self.pending) >= REFILL_LOW_WATERMARK:
            return
        if now - self.last_new_pool_refill_at >= NEW_POOLS_COOLDOWN_SECONDS:
            try:
                tokens = self.module.get_geckoterminal_new_pool_tokens()
                self.last_new_pool_refill_at = now
                for token in tokens:
                    self.enqueue(token)
                log.info("%s new_pools queued=%d found=%d", self.label(), len(self.pending), len(tokens))
            except Exception as exc:
                log.warning("%s new_pools failed: %s", self.label(), exc)
        if len(self.pending) < REFILL_LOW_WATERMARK and now - self.last_top_pool_refill_at >= TOP_POOLS_COOLDOWN_SECONDS:
            try:
                tokens = self.module.get_geckoterminal_top_pool_tokens()
                self.last_top_pool_refill_at = now
                for token in tokens:
                    self.enqueue(token)
                log.info("%s top_pools queued=%d found=%d", self.label(), len(self.pending), len(tokens))
            except Exception as exc:
                log.warning("%s top_pools failed: %s", self.label(), exc)

    def refill_from_chain(self) -> None:
        if len(self.pending) >= REFILL_LOW_WATERMARK:
            return
        now = time.time()
        try:
            new_block = int(self.module.get_latest_block() or 0)
        except Exception as exc:
            log.warning("%s block fetch failed: %s", self.label(), exc)
            return
        if not new_block or not self.current_block or new_block <= self.current_block:
            self.current_block = max(self.current_block, new_block)
            return

        dex_enabled = DEX_SCAN_ENABLED or (self.config.name == "tron" and env_bool("TRON_DEX_EVENT_SCAN_ENABLED", "true"))
        dex_cooldown = int(getattr(self.module, "DEX_EVENT_SCAN_COOLDOWN_SECONDS", 300))
        if dex_enabled and now - self.last_dex_refill_at >= dex_cooldown and hasattr(self.module, "get_new_dex_pair_tokens"):
            try:
                dex_fn = self.module.get_new_dex_pair_tokens
                if len(inspect.signature(dex_fn).parameters) == 0:
                    tokens = dex_fn()
                else:
                    tokens = dex_fn(self.current_block, new_block)
                for token in tokens:
                    self.enqueue(token)
                self.last_dex_refill_at = now
                log.info("%s dex queued=%d found=%d", self.label(), len(self.pending), len(tokens))
            except Exception as exc:
                log.warning("%s dex scan failed: %s", self.label(), exc)

        fallback_enabled = FALLBACK_SCAN_ENABLED or (self.config.name == "tron" and env_bool("TRON_FALLBACK_SCAN_ENABLED", "true"))
        fallback_cooldown = int(getattr(self.module, "FALLBACK_CONTRACT_SCAN_COOLDOWN_SECONDS", 300))
        if fallback_enabled and now - self.last_fallback_refill_at >= fallback_cooldown and hasattr(self.module, "get_new_token_deployments") and len(self.pending) < REFILL_LOW_WATERMARK:
            try:
                tokens = self.module.get_new_token_deployments(self.current_block, new_block)
                for token in tokens:
                    self.enqueue(token)
                self.last_fallback_refill_at = now
                log.info("%s fallback queued=%d found=%d blocks=%d-%d", self.label(), len(self.pending), len(tokens), self.current_block, new_block)
            except Exception as exc:
                log.warning("%s fallback scan failed: %s", self.label(), exc)

        self.current_block = new_block

    def daily_open(self) -> bool:
        try:
            state = self.module.load_daily_state()
            return bool(self.module.daily_limits_open(state))
        except Exception as exc:
            log.warning("%s daily state failed: %s", self.label(), exc)
            return True

    def increment_daily(self) -> None:
        try:
            state = self.module.load_daily_state()
            state["tokens"] = int(state.get("tokens", 0)) + 1
            self.module.save_daily_state(state)
        except Exception as exc:
            log.warning("%s daily increment failed: %s", self.label(), exc)

    def publish_onchain_if_supported(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        if not (
            hasattr(self.module, "module_payloads")
            and hasattr(self.module, "publish_module_payloads_onchain")
        ):
            return []
        try:
            state = self.module.load_daily_state() if hasattr(self.module, "load_daily_state") else {}
            payloads = self.module.module_payloads(record)
            txs = self.module.publish_module_payloads_onchain(payloads, state)
            if txs:
                log.info("%s on-chain writes confirmed: %d txs", self.label(), len(txs))
            return txs or []
        except Exception as exc:
            log.error("%s on-chain writes failed: %s", self.label(), exc)
            return []

    def emit_post_scan_outputs_if_supported(self, record: dict[str, Any], txs: list[dict[str, Any]]) -> None:
        append_fn = getattr(self.module, "append_markdown_scan_log", None)
        if callable(append_fn):
            try:
                if len(inspect.signature(append_fn).parameters) == 2:
                    append_fn(record, txs)
            except Exception as exc:
                log.warning("%s markdown scan log failed: %s", self.label(), exc)

        telegram_fn = getattr(self.module, f"send_telegram_alert_{self.config.name}", None)
        if not callable(telegram_fn) and self.config.name == "base":
            telegram_fn = getattr(self.module, "send_telegram_alert_BASE", None)
        if not callable(telegram_fn) and self.config.name == "bnb":
            telegram_fn = getattr(self.module, "send_telegram_alert_BNB", None)
        if callable(telegram_fn):
            try:
                telegram_fn(record, txs)
            except Exception as exc:
                log.warning("%s telegram alert failed: %s", self.label(), exc)

    def process_one_if_due(self) -> None:
        if not self.pending or time.time() < self.next_scan_at:
            return
        if not self.daily_open():
            log.info("%s daily limit reached; queue=%d", self.label(), len(self.pending))
            return

        token_data = self.pending.pop(0)
        address = self.normalize_address(token_data.get("address", ""))
        self.queued.discard(address)
        try:
            record = self.process(token_data, self.output_path)
            self.seen_at[address] = time.time()
            if record:
                txs = self.publish_onchain_if_supported(record)
                self.emit_post_scan_outputs_if_supported(record, txs)
                self.increment_daily()
                delay_min = random.randint(
                    int(os.getenv("MIN_SCAN_DELAY_MINUTES", "2")),
                    int(os.getenv("MAX_SCAN_DELAY_MINUTES", "3")),
                )
                self.next_scan_at = time.time() + delay_min * 60
                log.info("%s scanned %s label=%s risk=%s queue=%d next=%dm", self.label(), address, record.get("label"), record.get("risk_percent", "?"), len(self.pending), delay_min)
            else:
                self.next_scan_at = time.time()
                log.info("%s skipped %s queue=%d", self.label(), address, len(self.pending))
        except Exception as exc:
            self.seen_at[address] = time.time()
            self.next_scan_at = time.time() + 30
            log.error("%s process failed for %s: %s", self.label(), address, exc)

    def turn(self) -> None:
        self.refill_from_gecko()
        self.refill_from_chain()
        self.process_one_if_due()


CHAINS = [
    ChainConfig("avax", "chains.avalanche.avax_collector_v6", "process_token_avax", "syndicate_train_avax_v6.jsonl", "avax", "CONSOLIDATED_AVAX"),
    ChainConfig("bnb", "chains.bnb.bnb_collector_v1", "process_token_BNB", "syndicate_train_bnb_v1.jsonl", "bsc", "CONSOLIDATED_BNB"),
    ChainConfig("base", "chains.base.base_collector_v1", "process_token_BASE", "syndicate_train_base_v1.jsonl", "base", "CONSOLIDATED_BASE"),
    ChainConfig("tron", "chains.tron.tron_collector_v1", "process_token", "syndicate_train_tron_v1.jsonl", "tron", "CONSOLIDATED_TRON"),
]


def apply_chain_onchain_env(config: ChainConfig) -> None:
    enabled = os.getenv(f"{config.onchain_env_prefix}_ONCHAIN_LOG_ENABLED", "false")
    publish = os.getenv(f"{config.onchain_env_prefix}_BOT_PUBLISH_TO_REGISTRY", enabled)
    os.environ["ONCHAIN_LOG_ENABLED"] = enabled
    os.environ["BOT_PUBLISH_TO_REGISTRY"] = publish
    os.environ["PUBLISH_MODULES_TO_REGISTRY"] = publish


def build_runtimes() -> list[ChainRuntime]:
    runtimes = []
    for config in CHAINS:
        apply_chain_onchain_env(config)
        module = importlib.import_module(config.module_path)
        if hasattr(module, "GECKOTERMINAL_NEW_POOLS_URL"):
            module.GECKOTERMINAL_NEW_POOLS_URL = (
                f"https://api.geckoterminal.com/api/v2/networks/{config.gecko_network}/new_pools"
                "?include=base_token,quote_token"
            )
        if config.name == "tron":
            module.GECKOTERMINAL_TOP_POOLS_ENABLED = env_bool("TRON_TOP_POOLS_ENABLED", "true")
            module.GECKOTERMINAL_POOL_PAGES = min(int(getattr(module, "GECKOTERMINAL_POOL_PAGES", 3)), 2)
            module.DEX_EVENT_SCAN_ENABLED = env_bool("TRON_DEX_EVENT_SCAN_ENABLED", "true")
            module.FALLBACK_CONTRACT_SCAN_ENABLED = env_bool("TRON_FALLBACK_SCAN_ENABLED", "true")
        process = getattr(module, config.process_func)
        runtime = ChainRuntime(config=config, module=module, process=process, output_path=Path(config.output_file))
        runtime.init()
        runtimes.append(runtime)
    return runtimes


def main() -> None:
    log.info("Starting consolidated RugBuster worker: chains=%s RUN_UNTIL_DATE=%s", ",".join(c.name for c in CHAINS), RUN_UNTIL_DATE)
    log.info("Cost mode: one Railway service, one Python process, per-chain queues.")
    runtimes = build_runtimes()
    while True:
        for runtime in runtimes:
            runtime.turn()
            time.sleep(CHAIN_TURN_SLEEP_SECONDS)


if __name__ == "__main__":
    main()
