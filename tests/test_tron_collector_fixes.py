from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chains.tron import tron_collector_v1 as tron


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, retry_after: str | None = None):
        self.status_code = status_code
        self.payload = payload or {}
        self.headers = {"Retry-After": retry_after} if retry_after else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class TronCollectorFixTests(unittest.TestCase):
    def test_remote_scoring_response_is_used_when_feature_flag_is_enabled(self):
        cia = {"funding": {"status": "ok"}, "latency": {"status": "ok"}, "entropy": {"status": "ok"}, "wash": {"status": "ok"}, "cluster": {"status": "ok"}}
        remote = FakeResponse(200, {"risk_score": 77, "verdict": "DANGER", "confidence": {"level": "NORMAL"}, "risk_factors": [{"detail": "remote factor"}]})
        with patch.object(tron, "USE_REMOTE_SCORING_ENGINE", True), patch.object(tron, "SCORING_ENGINE_URL", "http://scoring.test"), patch.object(tron, "SCORING_ENGINE_HMAC_SECRET", "test-secret"), patch.object(tron, "calculate_risk", return_value=(23, ["local factor"])), patch.object(tron.requests, "post", return_value=remote) as post:
            risk, reasons, confidence, used_remote = tron.score_with_optional_remote_engine({"name": "T", "symbol": "T"}, cia, {}, {"backdoor": {"status": "ok"}}, 10)
        self.assertEqual((risk, reasons, confidence, used_remote), (77, ["remote factor"], {"level": "NORMAL"}, True))
        self.assertEqual(post.call_args.kwargs["headers"]["Content-Type"], "application/json")
        self.assertIn("X-RugBuster-Signature", post.call_args.kwargs["headers"])

    def test_remote_scoring_failure_falls_back_to_local_result(self):
        cia = {"funding": {"status": "ok"}, "latency": {"status": "ok"}, "entropy": {"status": "ok"}, "wash": {"status": "ok"}, "cluster": {"status": "ok"}}
        with patch.object(tron, "USE_REMOTE_SCORING_ENGINE", True), patch.object(tron, "SCORING_ENGINE_URL", "http://scoring.test"), patch.object(tron, "SCORING_ENGINE_HMAC_SECRET", "test-secret"), patch.object(tron, "calculate_risk", return_value=(23, ["local factor"])), patch.object(tron.requests, "post", side_effect=tron.requests.Timeout):
            risk, reasons, confidence, used_remote = tron.score_with_optional_remote_engine({"name": "T", "symbol": "T"}, cia, {}, {"backdoor": {"status": "ok"}}, 10)
        self.assertEqual((risk, reasons, used_remote), (23, ["local factor"], False))
        self.assertEqual(confidence["level"], "NORMAL")

    def test_trongrid_retries_429_with_backoff(self):
        responses = [FakeResponse(429), FakeResponse(429), FakeResponse(200, {"data": []})]
        with patch.object(tron, "throttle"), patch.object(tron.requests, "get", side_effect=responses) as get, patch.object(tron.time, "sleep") as sleep:
            self.assertEqual(tron.trongrid_get("/v1/test"), {"data": []})
        self.assertEqual(get.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.75, 1.5])

    def test_cia_uses_one_shared_token_transfer_fetch(self):
        transfers = [{"value": "100", "token_info": {"decimals": 0}, "from": "", "to": "", "block_timestamp": 1000}]
        with patch.object(tron, "get_token_transfers_checked", return_value=(transfers, "ok", "")) as fetch, patch.object(tron, "get_account_transactions_checked", return_value=([], "ok", "")):
            cia = tron.run_cia_analysis("TToken", "", 0)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(cia["entropy"]["status"], "ok")
        self.assertEqual(cia["wash"]["status"], "ok")
        self.assertEqual(cia["cluster"]["status"], "ok")

    def test_low_confidence_is_not_presented_as_a_good_verdict(self):
        cia = {
            "funding": {"status": "unavailable", "error": "missing_deployer"},
            "latency": {"status": "unavailable", "error": "missing_deployment_timestamp"},
            "entropy": {"status": "ok", "tx_count": 1, "unique_wallets": 2},
            "wash": {"status": "error", "error": "429"},
            "cluster": {"status": "error", "error": "429"},
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(tron, "get_trc20_metadata", return_value={"name": "BLUC", "symbol": "BLUC", "decimals": 6, "total_supply": 1}), patch.object(tron, "get_creator_stats", return_value={"rug_rate": 0}), patch.object(tron, "run_cia_analysis", return_value=cia), patch.object(tron, "run_v5_analysis", return_value={}), patch.object(tron, "run_v6_analysis", return_value={"backdoor": {"status": "ok"}}), patch.object(tron, "calculate_risk", return_value=(23, ["thin TRON activity: 1 tx / 2 wallets"])), patch.object(tron, "previous_record", return_value=None), patch.object(tron, "save_to_postgres"), patch.object(tron, "append_markdown_scan_log"), patch.object(tron, "publish_recent_scan"), patch.object(tron, "update_creator_history"):
            record = tron.process_token({"address": "TNssvWyu48fuCRQkqfs9T4qX5T9PkBAxNN", "source": "test"}, Path(temp_dir) / "out.jsonl")
        self.assertEqual(record["label"], "WARN")
        self.assertEqual(record["base_label"], "GOOD")
        self.assertEqual(record["risk_percent"], 23)
        self.assertEqual(record["confidence"]["reading_status"], "degraded")
        self.assertIn("degraded reading: insufficient TRON data", record["risk_reasons"])

    def test_confidence_only_change_suppresses_telegram_alert(self):
        tron.last_alert_signatures.clear()
        previous = {
            "label": "GOOD",
            "risk_percent": 23,
            "risk_reasons": ["thin TRON activity: 1 tx / 2 wallets"],
        }
        current = {
            "contract_address": "TNssvWyu48fuCRQkqfs9T4qX5T9PkBAxNN",
            "label": "GOOD",
            "risk_percent": 23,
            "base_label": "GOOD",
            "base_risk_percent": 23,
            "risk_signal_reasons": ["thin TRON activity: 1 tx / 2 wallets"],
            "risk_reasons": ["thin TRON activity: 1 tx / 2 wallets", "degraded reading: insufficient TRON data"],
        }
        self.assertFalse(tron.should_send_telegram_alert(current, previous))

    def test_fallback_requires_trc20_core_abi(self):
        value = {"new_contract": {"abi": {"entrys": [
            {"type": "Function", "name": name}
            for name in ("name", "symbol", "decimals", "totalSupply")
        ]}}}
        self.assertTrue(tron.is_trc20_deployment(value))
        self.assertFalse(tron.is_trc20_deployment({"new_contract": {"abi": {"entrys": []}}}))


if __name__ == "__main__":
    unittest.main()
