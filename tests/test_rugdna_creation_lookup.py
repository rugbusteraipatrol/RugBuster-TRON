from unittest.mock import patch

from chains.base import base_collector_v1 as base
from chains.bnb import bnb_collector_v1 as bnb
from chains.tron import tron_collector_v1 as tron


def test_bnb_creation_evidence_uses_existing_explorer_transaction_shape():
    with patch.object(bnb, "get_contract_transactions", return_value=[{"from": "0xCreator", "timeStamp": "1700000000"}]):
        result = bnb.resolve_contract_creation_BNB("0xToken")
    assert result == {"status": "ok", "address": "0xcreator", "deployment_timestamp": 1700000000, "error": ""}


def test_base_creation_evidence_fails_open_when_explorer_has_no_row():
    with patch.object(base, "get_contract_transactions", return_value=[]):
        result = base.resolve_contract_creation_BASE("0xToken")
    assert result["status"] == "unavailable"
    assert result["address"] is None


def test_tron_contract_record_does_not_invent_a_creation_timestamp():
    with patch.object(tron, "full_node_post", return_value={"origin_address": "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE"}):
        result = tron.resolve_contract_creation_tron("TToken")
    assert result["status"] == "partial"
    assert result["deployment_timestamp"] is None
