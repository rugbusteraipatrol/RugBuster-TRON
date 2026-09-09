"""Say, in a sentence, what was found and what could not be established.

Written for TRON; not shared with the other services. Same three fields, own
vocabulary. The verdict field here is `verdict`, not `label` -- a difference
that has already cost this project once, when a probe of this service read
`label`, found nothing, and reported the endpoint as broken.

Most of what keeps a token out of a clean answer on this service is not a
finding. There is no curated list of TRON assets, so every issuer is
unestablished; a deployer is resolved but no history is looked up for it. A
reader given `WARN` and nothing else will supply a reason we never gave them,
and the reason they supply will be worse than the truth.
"""

from __future__ import annotations

from typing import Any

FINDING, REFUSAL, GAP = "FINDING", "REFUSAL", "GAP"

UNREAD_STATUSES = {"", "UNKNOWN", "NOT_COLLECTED", "NOT_QUERIED", "FETCH_FAILED", "NOT_FOUND"}

# Plain words for the powers the contract module reports.
POWER_WORDS = {
    "has_blacklist": "freeze or blacklist an address",
    "has_pause_function": "pause transfers",
    "has_mint_function": "mint new supply",
    "has_drain_function": "call a withdraw function",
}


def _dimension(evidence: dict[str, Any], name: str) -> dict[str, Any]:
    value = (evidence or {}).get(name)
    return value if isinstance(value, dict) else {}


def _was_read(block: dict[str, Any]) -> bool:
    return str(block.get("status") or "").upper() not in UNREAD_STATUSES


def not_established(payload: dict[str, Any]) -> list[str]:
    """Plainly: the questions this answer does not settle."""
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    gaps: list[str] = []

    controls = _dimension(evidence, "technical_controls")
    identity = _dimension(evidence, "issuer_identity")
    issuer_known = identity.get("recognised") is True

    if not _was_read(controls):
        gaps.append("what functions this contract exposes")
    elif controls.get("contract_functions_matched") or controls.get("admin_functions"):
        gaps.append("what the matched contract functions actually do")
        if not issuer_known:
            gaps.append("who can call them")

    if not issuer_known:
        gaps.append("who issued this token")

    if not _was_read(_dimension(evidence, "market")):
        gaps.append("how many holders this token has and how deep its market is")

    creator = _dimension(evidence, "creator_history")
    if not _was_read(creator):
        gaps.append("who deployed this token")
    else:
        gaps.append("what this deployer's previous tokens did")
    incidents = creator.get("confirmed_incidents")
    if isinstance(incidents, dict) and not _was_read(incidents):
        gaps.append("whether this token or its deployer has a confirmed incident on record")

    for name, reason in (_dimension(evidence, "coverage").get("modules_not_read") or {}).items():
        gaps.append(f"the {str(name).replace('_', ' ')} reading, which returned {reason}")

    seen: set[str] = set()
    return [gap for gap in gaps if not (gap in seen or seen.add(gap))]


def _headline(payload: dict[str, Any]) -> tuple[str, str]:
    # `verdict`, not `label`. This service names it differently and a probe
    # that assumed otherwise once reported it as returning nothing.
    verdict = str(payload.get("verdict") or "").upper()
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    controls = _dimension(evidence, "technical_controls")
    identity = _dimension(evidence, "issuer_identity")

    if verdict in {"UNKNOWN", "INSUFFICIENT_DATA", ""}:
        return (
            "Too little was readable to judge this token. That is our answer, "
            "not a clean bill of health.",
            REFUSAL,
        )

    powers = list(controls.get("powers") or [])
    if powers:
        readable = ", ".join(POWER_WORDS.get(name, name) for name in powers)
        matched = ", ".join(controls.get("contract_functions_matched") or []) or "controller functions"
        if identity.get("recognised") is True:
            return (
                f"A recognised TRON asset. Its controller can {readable} "
                f"({matched}) -- expected for this kind of asset, reported "
                "rather than read as intent.",
                FINDING,
            )
        return (
            f"This contract's controller can {readable} ({matched}). The "
            "functions were matched by name, not by reading what they do, and "
            "who holds them has not been established.",
            FINDING,
        )

    if verdict == "DANGER":
        return "Findings against this contract or its deployer, listed below.", FINDING
    if verdict == "GOOD":
        return "Nothing found against this token in what was checked.", FINDING
    return "Nothing conclusive was found either way.", GAP


def _coverage_clause(payload: dict[str, Any]) -> str:
    """How much of the check actually ran.

    A clean answer built on half the modules is not the same as a clean answer,
    and "nothing found in what was checked" hides the size of what was checked.
    """
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    coverage = evidence.get("coverage") if isinstance(evidence.get("coverage"), dict) else {}
    pct = coverage.get("completeness_pct")
    not_read = coverage.get("modules_not_read") or {}
    if pct is None or pct >= 100 or not not_read:
        return ""
    names = ", ".join(str(name).replace("_", " ") for name in sorted(not_read))
    return f" {pct}% of the modules read something; these did not: {names}."


def describe(payload: dict[str, Any]) -> dict[str, Any]:
    """A sentence and a list, both restating fields computed elsewhere."""
    summary, basis = _headline(payload)
    summary += _coverage_clause(payload)
    gaps = not_established(payload)

    # Only a GAP earns the reassuring clause. A refusal to judge must never be
    # softened with it: on a token we could barely read, "not evidence against
    # the token" is the sentence a reader would most like to hear and the one
    # least supported by what we know.
    if basis == GAP and gaps:
        summary += (
            " What is missing is knowledge on our side, not evidence against "
            "the token: see not_established."
        )

    return {"verdict_summary": summary, "verdict_basis": basis, "not_established": gaps}
