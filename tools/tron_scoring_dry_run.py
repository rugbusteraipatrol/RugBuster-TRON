"""Read-only parity check for current TRON addresses.

Run through `railway run --service tron -- python tools/tron_scoring_dry_run.py <address> ...`.
It does not write Postgres rows, collector state, JSONL files, or Telegram alerts.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "rugbuster-scoring-engine"))

from chains.tron import tron_collector_v1 as tron  # noqa: E402
from rugbuster_scoring_engine.engine import score_payload  # noqa: E402


def main() -> int:
    addresses = [tron.normalize_tron_address(value) for value in sys.argv[1:]]
    addresses = [address for address in addresses if address]
    if not addresses:
        print("Provide one or more TRON contract addresses.")
        return 2

    mismatches = 0
    for address in addresses:
        # This dry run intentionally has no deployment feed record, so unavailable
        # provenance modules are represented identically on both scoring paths.
        deployer = ""
        deploy_ts = 0
        metadata = tron.get_trc20_metadata(address)
        creator_stats = tron.get_creator_stats(deployer or "")
        cia = tron.run_cia_analysis(address, deployer or "", deploy_ts)
        dominant = cia.get("entropy", {}).get("dominant_amount")
        amounts = [dominant] if isinstance(dominant, (int, float)) else []
        holders = int(cia.get("cluster", {}).get("total_checked") or 0)
        v5 = tron.run_v5_analysis(metadata.get("name", ""), metadata.get("symbol", ""), deploy_ts, amounts, holders, cia, creator_stats.get("rug_rate", 0))
        v6 = tron.run_v6_analysis(address)
        balance = tron.get_trx_balance(deployer) if deployer else None

        old_score, old_reasons = tron.calculate_risk(metadata, cia, v5, v6, balance)
        old_confidence = tron.confidence_from_modules(cia, v6)
        new = score_payload({
            "chain": "TRON", "token": metadata, "cia": cia, "v5": v5, "v6": v6,
            "deployer_balance": balance,
        })
        new_reasons = [item["detail"] for item in new["risk_factors"]]
        matched = (old_score, old_reasons, old_confidence) == (new["risk_score"], new_reasons, new["confidence"])
        mismatches += int(not matched)
        print(f"{address}: {'MATCH' if matched else 'MISMATCH'} old={old_score} new={new['risk_score']}")

    print(f"TRON parity: {len(addresses) - mismatches}/{len(addresses)} matched")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
