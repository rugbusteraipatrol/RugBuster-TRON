"""A lookup must answer, and must not announce itself.

Before this, /score returned 404 `not_found` for any address outside the
collector's table -- including USDT and WTRX, the two largest tokens on TRON.
Measured 2026-09-07: the chain answered for 2 of its 4 canonical tokens.

The obvious fix, calling process_token, would have been worse than the bug:
it appends a JSONL record, writes Postgres, appends the markdown scan log,
sends a Telegram alert and publishes to the public recent-scans feed. Every
user checking an address would have pinged the alert channel and appeared on
a public feed. These tests pin that separation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chains.tron import tron_collector_v1 as tron  # noqa: E402


def _fake_meta():
    return {
        "name": "Tether USD",
        "symbol": "USDT",
        "decimals": 6,
        "total_supply": 10**15,
        "metadata_source": "trongrid",
        "metadata_status": "ok",
    }


@pytest.fixture()
def stubbed(monkeypatch):
    """Stub every network read so the record is built from known values."""
    monkeypatch.setattr(tron, "get_trc20_metadata", lambda address: _fake_meta())
    monkeypatch.setattr(tron, "get_trx_balance", lambda address: 12.5)
    monkeypatch.setattr(tron, "get_creator_stats", lambda deployer: {"rug_rate": 0.0, "total": 0})
    monkeypatch.setattr(tron, "run_cia_analysis", lambda *a, **k: {
        "entropy": {"dominant_amount": 1.0}, "cluster": {"total_checked": 5},
    })
    monkeypatch.setattr(tron, "run_v5_analysis", lambda *a, **k: {})
    monkeypatch.setattr(tron, "run_v6_analysis", lambda address: {})
    monkeypatch.setattr(tron, "score_with_optional_remote_engine",
                        lambda *a, **k: (12, ["clean read"], {"level": "NORMAL"}, False))
    return tron


def test_build_token_record_returns_a_scored_record(stubbed):
    record = tron.build_token_record({"address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"})
    assert record is not None
    assert record["contract_address"]
    assert record["label"]
    assert record["risk_percent"] == 12


def test_build_token_record_writes_nothing_anywhere(stubbed):
    """The whole point of the split. If any of these fire on a lookup, a user
    searching an address has pinged the alert channel or published a token."""
    with mock.patch.object(tron, "append_jsonl") as jsonl, \
         mock.patch.object(tron, "save_to_postgres") as postgres, \
         mock.patch.object(tron, "append_markdown_scan_log") as markdown, \
         mock.patch.object(tron, "send_telegram_alert") as telegram, \
         mock.patch.object(tron, "publish_recent_scan") as feed:
        tron.build_token_record({"address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"})
    jsonl.assert_not_called()
    postgres.assert_not_called()
    markdown.assert_not_called()
    telegram.assert_not_called()
    feed.assert_not_called()


def test_process_token_still_writes_and_announces(stubbed, tmp_path):
    """The collector's behaviour must be unchanged by the split."""
    with mock.patch.object(tron, "append_jsonl") as jsonl, \
         mock.patch.object(tron, "save_to_postgres") as postgres, \
         mock.patch.object(tron, "append_markdown_scan_log"), \
         mock.patch.object(tron, "send_telegram_alert") as telegram, \
         mock.patch.object(tron, "publish_recent_scan") as feed, \
         mock.patch.object(tron, "previous_record", return_value=None), \
         mock.patch.object(tron, "update_creator_history"):
        record = tron.process_token(
            {"address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"}, tmp_path / "out.jsonl"
        )
    assert record is not None
    jsonl.assert_called_once()
    postgres.assert_called_once()
    telegram.assert_called_once()
    feed.assert_called_once()


def test_holder_sample_size_is_passed_through(stubbed):
    seen = {}

    def capture(token, deployer, deploy_ts, *, holder_sample_size=25):
        seen["size"] = holder_sample_size
        return {"entropy": {}, "cluster": {}}

    with mock.patch.object(tron, "run_cia_analysis", side_effect=capture):
        tron.build_token_record({"address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"},
                                holder_sample_size=8)
    assert seen["size"] == 8


def test_an_unreadable_token_yields_no_record(monkeypatch, stubbed):
    """Missing metadata must produce nothing, never a default-scored record."""
    monkeypatch.setattr(tron, "REQUIRE_TRC20_METADATA", True)
    monkeypatch.setattr(tron, "get_trc20_metadata", lambda address: {"name": "", "symbol": ""})
    assert tron.build_token_record({"address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"}) is None


def test_invalid_address_yields_no_record(stubbed):
    assert tron.build_token_record({"address": "not-a-tron-address"}) is None
