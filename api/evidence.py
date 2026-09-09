"""What the scanner claims, split into things that can each be checked.

Written for TRON; not shared with the other services. The dimension names are
the same because the questions are the same. What fills them is not, and
copying field names between services is how `withhold_verdict` came to blank a
label on Avalanche while leaving every numeric verdict field populated.

One rule throughout: a dimension we did not read reports UNKNOWN, and UNKNOWN
is neither clean nor guilty. This service already records a per-module status
-- each CIA module reports "ok" or an error -- so a module that failed is
visible here instead of being folded into a score and forgotten.
"""

from __future__ import annotations

from typing import Any

OK = "OK"
UNKNOWN = "UNKNOWN"
NOT_COLLECTED = "NOT_COLLECTED"

CONTROLLER_POWER_FIELDS = (
    "has_blacklist",
    "has_pause_function",
    "has_mint_function",
    "has_drain_function",
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _module(flags: dict[str, Any], name: str) -> dict[str, Any]:
    return _dict(flags.get(name))


def _module_read(block: dict[str, Any]) -> bool:
    """A module that reported an error read nothing, whatever else it returned."""
    if not block:
        return False
    status = str(block.get("status") or "").lower()
    return status in {"ok", ""} and not block.get("error")


def technical_controls(record: dict[str, Any], flags: dict[str, Any]) -> dict[str, Any]:
    """What the contract's controller can do, independent of who they are."""
    backdoor = _module(flags, "contract_backdoor")
    if not _module_read(backdoor):
        return {
            "status": UNKNOWN,
            "admin_functions": [],
            "contract_functions_matched": [],
            "powers": [],
            "has_backdoor": None,
            "reason": backdoor.get("error") or "not read",
            "note": (
                "The contract's functions were not read. Not read is not the "
                "same as none found."
            ),
        }
    return {
        "status": OK,
        "admin_functions": list(backdoor.get("admin_functions") or []),
        "contract_functions_matched": list(backdoor.get("backdoor_functions") or []),
        "powers": sorted(
            name for name in CONTROLLER_POWER_FIELDS if backdoor.get(name) is True
        ),
        "has_backdoor": backdoor.get("has_backdoor"),
        "note": (
            "Functions matched by name, not by reading what they do. A name "
            "match is a reason to look, not a finding about behaviour."
        ),
    }


def market(record: dict[str, Any]) -> dict[str, Any]:
    """Holders and depth, where the collector recorded them."""
    holders = record.get("holders_count")
    liquidity = record.get("liquidity_usd")
    if holders is None and liquidity is None:
        return {
            "status": UNKNOWN,
            "holders_count": None,
            "liquidity_usd": None,
            "note": (
                "No market reading was recorded. An absence of evidence about "
                "the market, not evidence of a bad market."
            ),
        }
    return {
        "status": OK,
        "holders_count": holders,
        "liquidity_usd": liquidity,
        "note": (
            "As recorded at scan time by the collector, not verified here, and "
            "not a claim about the deployer."
        ),
    }


def issuer_identity(record: dict[str, Any]) -> dict[str, Any]:
    """Whether we recognise who issued this, by curation and nothing else.

    Never by size: a token can be large, widely held and still controlled by
    someone nobody has identified.
    """
    if record.get("is_known_chain_asset") is True or record.get("is_known_tron_asset") is True:
        return {
            "status": OK,
            "recognised": True,
            "basis": "curated_list",
            "note": "On the curated list of canonical TRON assets.",
        }
    return {
        "status": UNKNOWN,
        "recognised": False,
        "basis": "curated_list",
        "note": (
            "Not recognised. This service keeps no curated list yet, so every "
            "issuer here is unestablished -- a gap in our coverage, not an "
            "accusation about any token."
        ),
    }


def creator_history(record: dict[str, Any], flags: dict[str, Any]) -> dict[str, Any]:
    """What this deployer's previous tokens were labelled by us.

    Nothing yet, and the field says so rather than reporting zero. Counting our
    own earlier verdicts as confirmed events would let one mistake harden into
    a record and then justify the next.
    """
    deployer = record.get("deployer") or record.get("creator") or ""
    funding = _module(flags, "funding_origin")

    return {
        "status": OK if deployer else UNKNOWN,
        "deployer": deployer or None,
        "prior_tokens_scanned_by_us": None,
        "prior_danger_rate_pct": None,
        "funding_read": _module_read(funding),
        "confirmed_incidents": {
            "count": None,
            "status": NOT_COLLECTED,
            "note": (
                "Sourced, dated incidents belong here. No such store exists "
                "yet, so this is not zero -- it is uncollected."
            ),
        },
        "note": (
            "A deployer is resolved here, but no history is looked up for it. "
            "Absent coverage, not an absence of history."
        ),
    }


def coverage(record: dict[str, Any], flags: dict[str, Any]) -> dict[str, Any]:
    """Which modules read something, and which did not."""
    modules = sorted(flags) if isinstance(flags, dict) else []
    read = [name for name in modules if _module_read(_module(flags, name))]
    not_read = {
        name: (
            _module(flags, name).get("error")
            or _module(flags, name).get("status")
            or "not read"
        )
        for name in modules if name not in read
    }
    confidence = _dict(record.get("confidence"))

    return {
        "status": OK,
        "modules_read": read,
        "modules_not_read": not_read,
        "completeness_pct": round(100 * len(read) / len(modules)) if modules else 0,
        "confidence_level": confidence.get("level"),
        "metadata_status": record.get("metadata_status"),
        "metadata_error": record.get("metadata_error") or "",
        "note": (
            "Governs how far the other dimensions can be trusted. A module "
            "under modules_not_read was not read -- it was not read as clean."
        ),
    }


def build_evidence(record: dict[str, Any], flags: dict[str, Any] | None = None) -> dict[str, Any]:
    """Additive. Reads the record; writes no verdict field."""
    record = _dict(record)
    flags = _dict(flags)
    return {
        "technical_controls": technical_controls(record, flags),
        "market": market(record),
        "issuer_identity": issuer_identity(record),
        "creator_history": creator_history(record, flags),
        "coverage": coverage(record, flags),
    }
