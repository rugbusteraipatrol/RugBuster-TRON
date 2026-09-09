"""TRON: what was found, what each module read, and what was not established.

The verdict field here is `verdict`, not `label`. That difference has already
cost this project once: a probe read `label`, found nothing, and reported the
endpoint as broken when it was answering correctly. So the sentence layer reads
`verdict`, and a test says so.

This service has more to disclose than the others. It keeps no curated list of
TRON assets, so every issuer is unestablished. It resolves a deployer and looks
up no history for it. Its CIA modules each report their own status, so a module
that failed is a fact the response can carry rather than something averaged
into a score and forgotten.

USDT on TRON is the worked example. It scores GOOD, and its controller can
pause transfers. Both are true, and until now only the first was said.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.evidence import build_evidence  # noqa: E402
from api.plain_language import FINDING, GAP, REFUSAL, describe, not_established  # noqa: E402

REASSURANCE = "not evidence against the token"

USDT_FLAGS = {
    "contract_backdoor": {
        "admin_functions": ["owner()", "transferOwnership(address)"],
        "backdoor_functions": ["pause()"],
        "has_backdoor": True, "has_pause_function": True,
        "has_blacklist": False, "has_mint_function": False,
        "has_drain_function": False, "status": "ok", "error": "",
    },
    "funding_origin": {"status": "ok", "error": "", "hop_count": 1},
    "deployment_latency": {"status": "ok", "error": "", "is_sniped": False},
}


def _described(verdict="GOOD", record=None, flags=None):
    record = record if record is not None else {"deployer": "TXFBqBbqJommqZf7BV8NNYzePh97UmJodJ"}
    payload = {"verdict": verdict,
               "evidence": build_evidence(record, USDT_FLAGS if flags is None else flags)}
    payload.update(describe(payload))
    return payload


# --- the field this service actually uses ----------------------------------

def test_the_verdict_field_is_read_not_the_label_field():
    """A probe that assumed `label` reported this endpoint as broken while it
    was answering correctly."""
    by_verdict = describe({"verdict": "GOOD", "evidence": {}})
    by_label = describe({"label": "GOOD", "evidence": {}})
    assert by_verdict["verdict_basis"] == FINDING
    assert by_label["verdict_basis"] == REFUSAL


# --- a clean verdict that still discloses a real power ---------------------

def test_a_good_token_still_says_its_controller_can_pause():
    result = _described()
    assert "pause transfers" in result["verdict_summary"]
    assert "pause()" in result["verdict_summary"]


def test_the_power_is_reported_as_matched_by_name():
    """The matcher works on function names. Saying more than that would claim
    a reading of the code that never happened."""
    result = _described()
    assert "matched by name, not by reading what they do" in result["verdict_summary"]


def test_who_holds_the_power_is_listed_as_unestablished():
    assert "who can call them" in _described()["not_established"]


# --- absent is not clean ---------------------------------------------------

def test_a_module_that_errored_did_not_read_anything():
    flags = {"contract_backdoor": {"status": "error", "error": "abi_fetch_failed",
                                   "has_backdoor": False}}
    evidence = build_evidence({"deployer": "TX"}, flags)
    assert evidence["technical_controls"]["status"] == "UNKNOWN"
    assert evidence["technical_controls"]["has_backdoor"] is None
    assert "what functions this contract exposes" in not_established({"evidence": evidence})


def test_a_failed_module_is_named_with_its_reason():
    flags = {"contract_backdoor": {"status": "error", "error": "abi_fetch_failed"}}
    result = _described(flags=flags)
    assert any("abi fetch failed" in gap or "abi_fetch_failed" in gap
               for gap in result["not_established"])


def test_an_unresolved_deployer_is_stated():
    result = _described(record={"deployer": ""})
    assert "who deployed this token" in result["not_established"]


def test_a_resolved_deployer_still_has_no_history():
    result = _described()
    assert "what this deployer's previous tokens did" in result["not_established"]
    evidence = result["evidence"]
    assert evidence["creator_history"]["prior_tokens_scanned_by_us"] is None


def test_confirmed_incidents_are_uncollected_not_zero():
    incidents = _described()["evidence"]["creator_history"]["confirmed_incidents"]
    assert incidents["status"] == "NOT_COLLECTED"
    assert incidents["count"] is None


def test_no_market_reading_is_not_a_bad_market():
    evidence = build_evidence({"deployer": "TX"}, USDT_FLAGS)
    assert evidence["market"]["status"] == "UNKNOWN"


def test_every_issuer_is_unrecognised_because_there_is_no_list():
    """Stated as our gap, not as a fact about the token."""
    identity = _described()["evidence"]["issuer_identity"]
    assert identity["recognised"] is False
    assert "not an accusation" in identity["note"]


# --- coverage is part of the answer ----------------------------------------

def test_the_summary_states_how_many_modules_read_something():
    flags = dict(USDT_FLAGS)
    flags["deployment_latency"] = {"status": "error", "error": "timeout"}
    result = _described(flags=flags)
    assert "% of the modules read something" in result["verdict_summary"]
    assert "deployment latency" in result["verdict_summary"]


def test_full_coverage_adds_no_clause():
    assert "modules read something" not in _described()["verdict_summary"]


# --- the sentence that must not appear where it does not belong ------------

def test_an_unknown_verdict_is_a_refusal_and_is_never_softened():
    result = _described(verdict="UNKNOWN", flags={})
    assert result["verdict_basis"] == REFUSAL
    assert REASSURANCE not in result["verdict_summary"]
    assert "not a clean bill of health" in result["verdict_summary"]


def test_describing_a_verdict_cannot_change_it():
    payload = {"verdict": "GOOD", "evidence": build_evidence({"deployer": "TX"}, USDT_FLAGS)}
    before = dict(payload)
    result = describe(payload)
    assert payload == before
    assert set(result) == {"verdict_summary", "verdict_basis", "not_established"}
