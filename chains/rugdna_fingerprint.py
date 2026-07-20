"""Read-only evidence normalization for future RugDNA matching.

This module only shapes data that collectors have already fetched. It does not
perform RPC calls, write transactions, or alter collector/scoring behaviour.
"""

from __future__ import annotations

from typing import Any


def _status(value: str, default: str = "unavailable") -> str:
    return value if value in {"ok", "partial", "unavailable", "error"} else default


def build_fingerprint(
    creator: str | None,
    deployment_timestamp: int | None,
    funding: dict[str, Any] | None,
    holder_snapshot: dict[str, Any] | None,
    creator_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a versioned, fail-open raw-evidence envelope for ``full_record``."""
    funding = funding or {}
    holder_snapshot = holder_snapshot or {}
    creator_evidence = creator_evidence or {}
    first_hop = funding.get("first_hop") if isinstance(funding.get("first_hop"), dict) else {}

    return {
        "schema_version": 1,
        "creator": {
            "status": _status(str(creator_evidence.get("status") or ""), "ok" if creator else "unavailable"),
            "address": creator_evidence.get("address") or creator or None,
            "deployment_timestamp": creator_evidence.get("deployment_timestamp") or deployment_timestamp or None,
            "error": creator_evidence.get("error") or "",
        },
        "first_hop_funding": {
            "status": _status(str(first_hop.get("status") or "")),
            "address": first_hop.get("address") or None,
            "amount": first_hop.get("amount"),
            "timestamp": first_hop.get("timestamp"),
            "asset": first_hop.get("asset") or None,
            "error": first_hop.get("error") or "",
        },
        "top_holders": {
            "status": _status(str(holder_snapshot.get("status") or "")),
            "holders": holder_snapshot.get("holders") if isinstance(holder_snapshot.get("holders"), list) else [],
            "error": holder_snapshot.get("error") or "",
        },
    }
