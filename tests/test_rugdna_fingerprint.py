from chains.rugdna_fingerprint import build_fingerprint


def test_fingerprint_keeps_raw_evidence_and_statuses():
    fingerprint = build_fingerprint(
        "0xcreator",
        1_700_000_000,
        {
            "first_hop": {
                "status": "ok",
                "address": "0xfunder",
                "amount": 2.5,
                "timestamp": 1_699_999_000,
                "asset": "AVAX",
            }
        },
        {"status": "ok", "holders": [{"address": "0xholder", "ownership_pct": 12.5}]},
    )

    assert fingerprint["creator"]["address"] == "0xcreator"
    assert fingerprint["first_hop_funding"]["address"] == "0xfunder"
    assert fingerprint["top_holders"]["holders"][0]["ownership_pct"] == 12.5


def test_fingerprint_fails_open_when_evidence_is_missing():
    fingerprint = build_fingerprint(None, None, None, None)

    assert fingerprint["creator"]["status"] == "unavailable"
    assert fingerprint["first_hop_funding"]["status"] == "unavailable"
    assert fingerprint["top_holders"]["holders"] == []
