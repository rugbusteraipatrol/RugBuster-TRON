#!/usr/bin/env python3
"""Read-only RugBuster agreement benchmark.

The script only performs HTTP GET requests. It never calls a RugBuster POST /scan
endpoint and never opens a production database connection.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parent
DEFAULT_REPORT_DIR = ROOT / "reports"
DEXSCREENER = "https://api.dexscreener.com"
GOPLUS = "https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/{address}/report"

CHAIN_CONFIG = {
    "bnb": {
        "dex": "bsc",
        "goplus_chain": "56",
        "rugbuster_url": "",
        "control_searches": ["WBNB", "USDT", "USDC", "BTCB", "CAKE"],
        "discovery_searches": ["pepe", "inu", "moon", "ai", "doge"],
        "controls": [
            ("WBNB", "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"),
            ("USDT", "0x55d398326f99059fF775485246999027B3197955"),
            ("USDC", "0x8AC76a51cc950d9822d68b83fE1Ad97B32Cd580d"),
            ("BTCB", "0x7130d2a12B9BCbfae4f2634d864A1Ee1Ce3Ead9c"),
            ("ETH", "0x2170Ed0880ac9A755fd29B2688956BD959F933F8"),
            ("CAKE", "0x0E09fABB73Bd3Ade0a17ECC321fD13a19e81cE82"),
        ],
    },
    "base": {
        "dex": "base",
        "goplus_chain": "8453",
        "rugbuster_url": "https://base-api-production-6887.up.railway.app/score?address={address}",
        "control_searches": ["WETH", "USDC", "cbBTC", "AERO", "DAI"],
        "discovery_searches": ["pepe", "inu", "moon", "ai", "doge"],
        "controls": [
            ("WETH", "0x4200000000000000000000000000000000000006"),
            ("USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
            ("cbBTC", "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf"),
            ("AERO", "0x940181a94A35A4569E4529A3CDfB74e38FD98631"),
            ("cbETH", "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0dec22"),
            ("DAI", "0x50c5725949A6F0c72E6C4A641F24049A917DB0Cb"),
        ],
    },
    "solana": {
        "dex": "solana",
        "goplus_chain": None,
        "rugbuster_url": "",
        "control_searches": ["SOL", "USDC", "JUP", "BONK", "RAY"],
        "discovery_searches": ["pepe", "inu", "moon", "ai", "doge"],
        "controls": [
            ("SOL", "So11111111111111111111111111111111111111112"),
            ("USDC", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
            ("USDT", "Es9vMFrzaCERmJfrF4H2FYDgG9hZZfZGYy7nY9j7bZ2"),
            ("JUP", "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"),
            ("BONK", "DezXAZ8z7PnrnRJjz3wXBoRgixCa6K2B5D2YBGz7hE4H"),
        ],
    },
}

SERIOUS_GOPLUS_FLAGS = {
    "is_honeypot",
    "is_blacklisted",
    "hidden_owner",
    "cannot_sell_all",
    "owner_change_balance",
    "transfer_pausable",
}
MINOR_GOPLUS_FLAGS = {
    "is_open_source",
    "is_proxy",
    "is_mintable",
    "is_anti_whale",
    "slippage_modifiable",
    "personal_slippage_modifiable",
    "trading_cooldown",
}


@dataclass
class Candidate:
    chain: str
    address: str
    bucket: str
    symbol: str = ""
    name: str = ""
    provenance: str = ""
    pair_created_at: int | None = None
    liquidity_usd: float | None = None
    price_change_h24: float | None = None


@dataclass
class SourceResult:
    normalized: str = "FETCH_FAILED"
    error: str | None = None
    raw: Any = None
    flags: list[str] = field(default_factory=list)
    label: str | None = None


class HttpClient:
    def __init__(self, delay_seconds: float, timeout_seconds: int):
        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": "RugBusterAgreementBenchmark/1.0"})
        self._last_request_at = 0.0

    def get_json(self, url: str, *, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> Any:
        wait_for = self.delay_seconds - (time.monotonic() - self._last_request_at)
        if wait_for > 0:
            time.sleep(wait_for)
        response = self.session.get(url, params=params, headers=headers, timeout=self.timeout_seconds)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response.json()


def as_bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes"}


def as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def pair_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    pairs = row.get("pairs") if isinstance(row, dict) else row
    if not isinstance(pairs, list):
        return None
    return max(pairs, key=lambda pair: as_float((pair.get("liquidity") or {}).get("usd")) or 0, default=None)


def candidate_from_pair(
    chain: str,
    pair: dict[str, Any],
    bucket: str,
    provenance: str,
    token_address: str | None = None,
) -> Candidate | None:
    base = pair.get("baseToken") or {}
    quote = pair.get("quoteToken") or {}
    token = base
    if token_address and str(base.get("address") or "").lower() != token_address.lower():
        token = quote
    address = str(token.get("address") or "").strip()
    if not address:
        return None
    return Candidate(
        chain=chain,
        address=address,
        bucket=bucket,
        symbol=clean_text(token.get("symbol")),
        name=clean_text(token.get("name")),
        provenance=provenance,
        pair_created_at=int(pair["pairCreatedAt"]) if str(pair.get("pairCreatedAt") or "").isdigit() else None,
        liquidity_usd=as_float((pair.get("liquidity") or {}).get("usd")),
        price_change_h24=as_float((pair.get("priceChange") or {}).get("h24")),
    )


def dex_search(client: HttpClient, query: str) -> list[dict[str, Any]]:
    data = client.get_json(f"{DEXSCREENER}/latest/dex/search", params={"q": query})
    return data.get("pairs") or []


def dex_token_pairs(client: HttpClient, chain: str, address: str) -> list[dict[str, Any]]:
    data = client.get_json(f"{DEXSCREENER}/token-pairs/v1/{CHAIN_CONFIG[chain]['dex']}/{address}")
    return data if isinstance(data, list) else []


def top_pair_for_token(client: HttpClient, chain: str, address: str) -> dict[str, Any] | None:
    return max(dex_token_pairs(client, chain, address), key=lambda item: as_float((item.get("liquidity") or {}).get("usd")) or 0, default=None)


def collect_controls(client: HttpClient, chain: str, target: int) -> list[Candidate]:
    config = CHAIN_CONFIG[chain]
    controls: list[Candidate] = []
    seen: set[str] = set()
    one_year_ago = int((datetime.now(UTC) - timedelta(days=365)).timestamp() * 1000)

    for symbol, address in config["controls"]:
        pair = top_pair_for_token(client, chain, address)
        candidate = candidate_from_pair(chain, pair, "control", "hardcoded_control", address) if pair else None
        if candidate is None:
            candidate = Candidate(chain=chain, address=address, bucket="control", symbol=symbol, provenance="hardcoded_control_no_dex_pair")
        key = candidate.address.lower()
        if key not in seen:
            seen.add(key)
            controls.append(candidate)

    # Fill the control set only with mature, liquid pairs returned by DexScreener.
    for query in config["control_searches"]:
        if len(controls) >= target:
            break
        for pair in dex_search(client, query):
            if pair.get("chainId") != config["dex"]:
                continue
            if int(pair.get("pairCreatedAt") or 0) > one_year_ago:
                continue
            if (as_float((pair.get("liquidity") or {}).get("usd")) or 0) < 100_000:
                continue
            candidate = candidate_from_pair(chain, pair, "control", f"dex_search:{query}")
            if candidate and candidate.address.lower() not in seen:
                seen.add(candidate.address.lower())
                controls.append(candidate)
                if len(controls) >= target:
                    break
    return controls[:target]


def discover_dex_candidates(client: HttpClient, chain: str) -> list[Candidate]:
    config = CHAIN_CONFIG[chain]
    rows: list[dict[str, Any]] = []
    for endpoint in ("token-profiles/latest/v1", "token-boosts/latest/v1", "token-boosts/top/v1"):
        try:
            value = client.get_json(f"{DEXSCREENER}/{endpoint}")
            rows.extend(item for item in value if isinstance(item, dict) and item.get("chainId") == config["dex"])
        except Exception:
            continue
    for query in config["discovery_searches"]:
        try:
            for pair in dex_search(client, query):
                if pair.get("chainId") != config["dex"]:
                    continue
                base = pair.get("baseToken") or {}
                rows.append({"tokenAddress": base.get("address"), "chainId": config["dex"]})
        except Exception:
            continue

    discovered: dict[str, Candidate] = {}
    for row in rows:
        address = str(row.get("tokenAddress") or "").strip()
        if not address or address.lower() in discovered:
            continue
        try:
            pair = top_pair_for_token(client, chain, address)
        except Exception:
            continue
        if not pair:
            continue
        candidate = candidate_from_pair(chain, pair, "candidate", "dexscreener_profiles_or_boosts", address)
        if candidate:
            discovered[candidate.address.lower()] = candidate
    return list(discovered.values())


def collect_buckets(client: HttpClient, chain: str, controls: int, fresh: int, bad: int, seed: int) -> list[Candidate]:
    selected = collect_controls(client, chain, controls)
    existing = {item.address.lower() for item in selected}
    now_ms = int(time.time() * 1000)
    recent_ms = now_ms - 7 * 24 * 60 * 60 * 1000
    market = [item for item in discover_dex_candidates(client, chain) if item.address.lower() not in existing]

    fresh_pool = [item for item in market if item.pair_created_at and item.pair_created_at >= recent_ms]
    bad_pool = [item for item in market if (item.price_change_h24 or 0) <= -90]
    random.Random(seed).shuffle(fresh_pool)
    random.Random(seed + 1).shuffle(bad_pool)

    for item in fresh_pool[:fresh]:
        item.bucket = "fresh_unknown"
        selected.append(item)
        existing.add(item.address.lower())
    for item in bad_pool:
        if len([token for token in selected if token.bucket == "likely_bad"]) >= bad:
            break
        if item.address.lower() in existing:
            continue
        item.bucket = "likely_bad"
        selected.append(item)
        existing.add(item.address.lower())
    return selected


def normalize_rugbuster(payload: Any) -> SourceResult:
    if not isinstance(payload, dict) or payload.get("ok") is False:
        return SourceResult(error="RugBuster returned no usable cached/read-only score", raw=payload)
    label = str(payload.get("label") or payload.get("verdict") or "").upper()
    mapping = {"GOOD": "SAFE", "SAFE": "SAFE", "WARN": "CAUTION", "ELEVATED": "CAUTION", "DANGER": "DANGER"}
    verdict = mapping.get(label)
    if verdict is None:
        score = as_float(payload.get("rug_score") if payload.get("rug_score") is not None else payload.get("risk_score"))
        if score is not None:
            verdict = "DANGER" if score >= 75 else "CAUTION" if score >= 45 else "SAFE"
            label = f"RISK_{score:g}"
    if verdict is None:
        return SourceResult(error=f"unrecognized RugBuster label: {label or 'empty'}", raw=payload, label=label)
    return SourceResult(normalized=verdict, raw=payload, label=label, flags=[str(item) for item in payload.get("risk_flags", []) if item])


def normalize_goplus(payload: Any, address: str) -> SourceResult:
    if not isinstance(payload, dict) or str(payload.get("code")) not in {"1", "2"}:
        return SourceResult(error=f"GoPlus API result code: {payload.get('code') if isinstance(payload, dict) else 'invalid'}", raw=payload)
    result = payload.get("result") or {}
    data = result.get(address.lower()) or result.get(address) or {}
    if not isinstance(data, dict) or not data:
        return SourceResult(error="GoPlus returned no token data", raw=payload)
    serious = [key for key in SERIOUS_GOPLUS_FLAGS if as_bool(data.get(key))]
    minor = [key for key in MINOR_GOPLUS_FLAGS - {"is_open_source"} if as_bool(data.get(key))]
    sell_tax = as_float(data.get("sell_tax")) or 0
    buy_tax = as_float(data.get("buy_tax")) or 0
    if sell_tax >= 0.5 or buy_tax >= 0.5:
        serious.append("extreme_tax")
    elif sell_tax >= 0.1 or buy_tax >= 0.1:
        minor.append("high_tax")
    # GoPlus cannot inspect many fields when source is not open; this is CAUTION, not DANGER.
    if str(data.get("is_open_source", "1")) == "0":
        minor.append("unverified_source")
    verdict = "DANGER" if serious else "CAUTION" if minor else "SAFE"
    return SourceResult(normalized=verdict, raw=payload, flags=sorted(set(serious + minor)))


def normalize_rugcheck(payload: Any) -> SourceResult:
    if not isinstance(payload, dict):
        return SourceResult(error="invalid RugCheck response", raw=payload)
    score = as_float(payload.get("score"))
    if score is None:
        return SourceResult(error="RugCheck score missing", raw=payload)
    risks = payload.get("risks") if isinstance(payload.get("risks"), list) else []
    risk_text = " ".join(json.dumps(item).lower() for item in risks)
    serious_terms = ("danger", "critical", "honeypot", "freeze", "cannot sell", "blacklist")
    if any(term in risk_text for term in serious_terms) or score >= 5000:
        verdict = "DANGER"
    elif score >= 100:
        verdict = "CAUTION"
    else:
        verdict = "SAFE"
    flags = [clean_text(item.get("name") or item.get("description") or item.get("level")) for item in risks if isinstance(item, dict)]
    return SourceResult(normalized=verdict, raw=payload, flags=[item for item in flags if item])


def fetch_rugbuster(client: HttpClient, candidate: Candidate) -> SourceResult:
    env_name = f"RUGBUSTER_{candidate.chain.upper()}_SCORE_URL"
    url = os.getenv(env_name, CHAIN_CONFIG[candidate.chain]["rugbuster_url"]).format(address=candidate.address)
    if url:
        try:
            return normalize_rugbuster(client.get_json(url))
        except Exception as exc:
            remote_error = f"{type(exc).__name__}: {exc}"
    else:
        remote_error = "no public read-only RugBuster score endpoint configured"
    if candidate.chain in {"bnb", "base"}:
        try:
            payload = local_evm_score(candidate.chain, candidate.address)
            result = normalize_rugbuster(payload)
            result.raw = {"mode": "local_read_only_scan", "response": payload}
            return result
        except Exception as exc:
            return SourceResult(error=f"remote={remote_error}; local={type(exc).__name__}: {exc}")
    return SourceResult(error=f"{remote_error}; set {env_name} to a read-only Solana score endpoint")


def local_evm_score(chain: str, address: str) -> dict[str, Any]:
    command = [sys.executable, str(Path(__file__).resolve()), "--internal-local-score", chain, address]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    if completed.returncode:
        raise RuntimeError(clean_text(completed.stderr or completed.stdout or "local scanner failed"))
    try:
        return json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"local scanner emitted invalid JSON: {completed.stdout[-400:]}") from exc


def run_internal_local_score(chain: str, address: str) -> int:
    workspace = ROOT.parents[1]
    source = {
        "bnb": workspace / "RugBuster-BNB" / "api" / "server.py",
        "base": workspace / "RugBuster-Base" / "api" / "server.py",
    }.get(chain)
    if source is None:
        raise SystemExit(f"local read-only scorer unavailable for {chain}")
    spec = importlib.util.spec_from_file_location(f"agreement_benchmark_{chain}", source)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print(json.dumps(module.scan_token(address), ensure_ascii=True))
    return 0


def fetch_goplus(client: HttpClient, candidate: Candidate) -> SourceResult:
    chain_id = CHAIN_CONFIG[candidate.chain]["goplus_chain"]
    if not chain_id:
        return SourceResult(error="not applicable to Solana in this benchmark")
    headers: dict[str, str] = {}
    token = os.getenv("GOPLUS_ACCESS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        payload = client.get_json(GOPLUS.format(chain_id=chain_id), params={"contract_addresses": candidate.address}, headers=headers)
        return normalize_goplus(payload, candidate.address)
    except Exception as exc:
        return SourceResult(error=f"{type(exc).__name__}: {exc}")


def fetch_rugcheck(client: HttpClient, candidate: Candidate) -> SourceResult:
    if candidate.chain != "solana":
        return SourceResult(error="not applicable to this chain")
    try:
        return normalize_rugcheck(client.get_json(RUGCHECK.format(address=candidate.address)))
    except Exception as exc:
        return SourceResult(error=f"{type(exc).__name__}: {exc}")


def markdown_escape(value: Any) -> str:
    return clean_text(value).replace("|", "\\|")


def write_report(path: Path, rows: list[dict[str, Any]], run_meta: dict[str, Any]) -> None:
    critical = [row for row in rows if row["critical"]]
    reverse = [row for row in rows if row["reverse"]]
    controls_flagged = [row for row in rows if row["bucket"] == "control" and row["rugbuster"] == "DANGER"]
    controls_not_safe = [row for row in rows if row["bucket"] == "control" and row["rugbuster"] not in {"SAFE", "FETCH_FAILED"}]
    lines = [
        "# RugBuster Agreement Benchmark",
        "",
        f"Generated: `{run_meta['generated_at']}`  ",
        "Mode: read-only HTTP GET only. No RugBuster scan endpoint or production database write was called.",
        "",
        "## Critical Disagreements",
        "",
    ]
    if critical:
        for row in critical:
            other = "GoPlus" if row["goplus"] == "DANGER" else "RugCheck"
            hypothesis = "missing contract-level signal or a stale/incomplete RugBuster cache record"
            lines.append(f"- `{row['chain']}` `{row['address']}`: RugBuster SAFE vs {other} DANGER. Hypothesis: {hypothesis}.")
    else:
        lines.append("- None in evaluated rows.")
    lines += [
        "",
        "## Mapping",
        "",
        "- RugBuster: GOOD/SAFE -> SAFE; WARN/ELEVATED -> CAUTION; DANGER -> DANGER.",
        "- GoPlus: honeypot, blacklist, hidden owner, cannot sell, balance-changing owner, transfer pause, or >=50% tax -> DANGER; unverified source/proxy/mintability/modifiable tax/cooldown or >=10% tax -> CAUTION; otherwise SAFE.",
        "- RugCheck (operational band, documented for this benchmark): score <100 -> SAFE; 100-4,999 -> CAUTION; >=5,000 or a serious risk item -> DANGER.",
        "- FETCH_FAILED means no verdict was inferred and the row is excluded from agreement statistics.",
        "",
        "## Results",
        "",
        "| Address | Chain | Bucket | RugBuster | GoPlus | RugCheck | Agree? |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['address']}` | {row['chain']} | {row['bucket']} | {row['rugbuster']} | {row['goplus']} | {row['rugcheck']} | {row['agreement']} |"
        )

    lines += ["", "## Summary", ""]
    for chain in run_meta["chains"]:
        chain_rows = [row for row in rows if row["chain"] == chain]
        evaluable = [row for row in chain_rows if row["agreement"] in {"AGREE", "DISAGREE"}]
        agreements = sum(row["agreement"] == "AGREE" for row in evaluable)
        lines.append(f"### {chain.upper()}")
        bucket_counts = Counter(row["bucket"] for row in chain_rows)
        lines.append(f"- Collected: {len(chain_rows)}; evaluated: {len(evaluable)}; fetch failures/not-applicable: {len(chain_rows) - len(evaluable)}.")
        lines.append(f"- Bucket coverage: controls={bucket_counts['control']}, fresh={bucket_counts['fresh_unknown']}, likely_bad={bucket_counts['likely_bad']}.")
        lines.append(f"- Agreement: {agreements}/{len(evaluable)} ({(agreements / len(evaluable) * 100) if evaluable else 0:.1f}%).")
        for bucket in ("control", "fresh_unknown", "likely_bad"):
            bucket_rows = [row for row in evaluable if row["bucket"] == bucket]
            bucket_agree = sum(row["agreement"] == "AGREE" for row in bucket_rows)
            lines.append(f"- {bucket}: {bucket_agree}/{len(bucket_rows)} agreement.")
        lines.append("")

    lines += ["## Review Queue", ""]
    lines.append(f"- Critical SAFE-vs-DANGER disagreements: {len(critical)}.")
    lines.append(f"- Reverse DANGER-vs-SAFE disagreements: {len(reverse)}.")
    lines.append(f"- Legit controls marked RugBuster DANGER: {len(controls_flagged)}.")
    lines.append(f"- Legit controls not marked RugBuster SAFE: {len(controls_not_safe)} (review before external use).")
    if reverse:
        lines.append("- Reverse cases: " + ", ".join(f"`{item['chain']}:{item['address']}`" for item in reverse))
    if controls_flagged:
        lines.append("- Control failures: " + ", ".join(f"`{item['chain']}:{item['address']}`" for item in controls_flagged))
    if controls_not_safe:
        lines.append("- Control warnings: " + ", ".join(f"`{item['chain']}:{item['address']}={item['rugbuster']}`" for item in controls_not_safe))
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    chains = [item.strip() for item in args.chains.split(",") if item.strip()]
    unknown = set(chains) - set(CHAIN_CONFIG)
    if unknown:
        raise SystemExit(f"Unsupported chains: {', '.join(sorted(unknown))}")
    client = HttpClient(args.request_delay, args.timeout)
    all_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []

    for index, chain in enumerate(chains):
        tokens = collect_buckets(client, chain, args.controls, args.fresh, args.bad, args.seed + index)
        print(f"{chain}: collected {len(tokens)} tokens", file=sys.stderr)
        for candidate in tokens:
            rugbuster = fetch_rugbuster(client, candidate)
            goplus = fetch_goplus(client, candidate)
            rugcheck = fetch_rugcheck(client, candidate)
            comparators = [item.normalized for item in (goplus, rugcheck) if item.normalized != "FETCH_FAILED"]
            agreement = "FETCH_FAILED"
            if rugbuster.normalized != "FETCH_FAILED" and comparators:
                agreement = "AGREE" if rugbuster.normalized in comparators else "DISAGREE"
            critical = rugbuster.normalized == "SAFE" and "DANGER" in comparators
            reverse = rugbuster.normalized == "DANGER" and "SAFE" in comparators
            row = {
                **asdict(candidate),
                "rugbuster": rugbuster.normalized,
                "goplus": goplus.normalized,
                "rugcheck": rugcheck.normalized,
                "agreement": agreement,
                "critical": critical,
                "reverse": reverse,
            }
            all_rows.append(row)
            raw_rows.append({
                "candidate": asdict(candidate),
                "rugbuster": asdict(rugbuster),
                "goplus": asdict(goplus),
                "rugcheck": asdict(rugcheck),
            })

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"agreement_report_{timestamp}.md"
    raw_path = output_dir / f"agreement_raw_{timestamp}.json"
    run_meta = {"generated_at": datetime.now(UTC).isoformat(), "chains": chains, "args": vars(args)}
    write_report(report_path, all_rows, run_meta)
    raw_path.write_text(json.dumps({"meta": run_meta, "rows": raw_rows}, indent=2, ensure_ascii=True), encoding="utf-8")
    print(report_path)
    print(raw_path)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only RugBuster agreement benchmark")
    parser.add_argument("--chains", default="bnb,base,solana")
    parser.add_argument("--controls", type=int, default=15)
    parser.add_argument("--fresh", type=int, default=20)
    parser.add_argument("--bad", type=int, default=15)
    parser.add_argument("--request-delay", type=float, default=0.35, help="Minimum delay between all external GET requests")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--seed", type=int, default=9000)
    parser.add_argument("--output-dir", default=str(DEFAULT_REPORT_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--internal-local-score":
        raise SystemExit(run_internal_local_score(sys.argv[2], sys.argv[3]))
    raise SystemExit(run(parse_args()))
