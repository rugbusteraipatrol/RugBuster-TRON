from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep API-triggered scans quiet unless explicitly enabled.
os.environ.setdefault("TRON_TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")

from chains.tron import tron_collector_v1 as tron  # noqa: E402

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")
API_VERSION = "rugbuster-tron-api-v1"


def db_connect():
    if not DATABASE_URL or psycopg2 is None:
        return None
    return psycopg2.connect(DATABASE_URL)


def load_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def normalize_address(address: str) -> str:
    return tron.normalize_tron_address(address.strip())


def valid_tron_address(address: str) -> bool:
    return bool(address and address.startswith("T") and tron.tron_base58_to_hex(address))


def reason_from_record(record: dict[str, Any]) -> str:
    reasons = record.get("risk_reasons") or []
    if isinstance(reasons, list) and reasons:
        return "; ".join(str(reason) for reason in reasons[:4])
    return "No major CIA Engine risk flags detected"


def cia_flags(record: dict[str, Any]) -> dict[str, Any]:
    cia = record.get("cia") or {}
    v5 = record.get("v5") or {}
    v6 = record.get("v6") or {}
    return {
        "funding_origin": cia.get("funding", {}),
        "deployment_latency": cia.get("latency", {}),
        "tx_entropy": cia.get("entropy", {}),
        "wash_pattern": cia.get("wash", {}),
        "holder_cluster_age": cia.get("cluster", {}),
        "name_stylometry": v5.get("name_style", {}),
        "contract_backdoor": v6.get("backdoor", {}),
    }


def api_record(record: dict[str, Any], source: str) -> dict[str, Any]:
    address = record.get("contract_address") or record.get("address") or ""
    return {
        "ok": True,
        "chain": "tron",
        "address": address,
        "verdict": record.get("label") or "UNKNOWN",
        "reason": reason_from_record(record),
        "risk_score": record.get("risk_percent"),
        "token_name": record.get("token_name"),
        "token_symbol": record.get("symbol") or record.get("token_symbol"),
        "cia_flags": cia_flags(record),
        "source": source,
        "scanner": record.get("collector") or "tron_collector_v1",
    }


def scan_feed_item(row: dict[str, Any]) -> dict[str, Any]:
    record = load_record(row.get("full_record"))
    created_at = row.get("created_at")
    risk_score = record.get("risk_percent")
    return {
        "address": row.get("contract_address") or record.get("contract_address") or record.get("address"),
        "verdict": row.get("label") or record.get("label") or "UNKNOWN",
        "risk_score": risk_score,
        "reason": reason_from_record(record),
        "token_name": record.get("token_name"),
        "token_symbol": record.get("symbol") or record.get("token_symbol"),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
    }


def latest_record(address: str) -> dict[str, Any] | None:
    conn = db_connect()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT full_record
                    FROM tron_scans
                    WHERE contract_address = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (address,),
                )
                row = cur.fetchone()
        return load_record(row["full_record"]) if row else None
    finally:
        conn.close()


def scan_live(address: str) -> dict[str, Any]:
    token_data = {
        "address": address,
        "timestamp": int(time.time()),
        "source": "tron_api",
    }
    record = tron.process_token(token_data, Path("api_tron_scans.jsonl"))
    if not record:
        raise RuntimeError("TRC-20 metadata unavailable or token scan returned no record")
    return record


@app.after_request
def add_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "version": API_VERSION, "database_configured": bool(DATABASE_URL)})


@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "ok": True,
        "name": "RugBuster TRON API",
        "version": API_VERSION,
        "stats_endpoint": "/api/tron/stats",
        "recent_endpoint": "/api/tron/recent?limit=10",
        "scan_endpoint": "/api/tron/scan",
        "score_endpoint": "/api/tron/score?address=T...",
    })


@app.route("/api/tron/stats", methods=["GET"])
def tron_stats():
    count = 0
    latest = None
    conn = db_connect()
    if conn is None:
        return jsonify({"ok": False, "error": "database_not_configured", "scan_count": count}), 503
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT COUNT(*) AS count FROM tron_scans")
                count = int(cur.fetchone()["count"] or 0)
                cur.execute(
                    """
                    SELECT contract_address, label, created_at, full_record
                    FROM tron_scans
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row:
                    record = load_record(row["full_record"])
                    latest = {
                        "address": row["contract_address"],
                        "verdict": row["label"],
                        "token_name": record.get("token_name"),
                        "token_symbol": record.get("symbol"),
                        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                    }
        return jsonify({"ok": True, "chain": "tron", "scan_count": count, "latest": latest})
    finally:
        conn.close()


@app.route("/api/tron/recent", methods=["GET"])
def tron_recent():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 25))

    conn = db_connect()
    if conn is None:
        return jsonify({"ok": False, "error": "database_not_configured", "chain": "tron", "items": []}), 503
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT contract_address, label, created_at, full_record
                    FROM tron_scans
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall() or []
        return jsonify({
            "ok": True,
            "chain": "tron",
            "limit": limit,
            "items": [scan_feed_item(row) for row in rows],
        })
    finally:
        conn.close()


@app.route("/api/tron/score", methods=["GET"])
def tron_score():
    address = normalize_address(str(request.args.get("address") or ""))
    if not valid_tron_address(address):
        return jsonify({"ok": False, "error": "invalid_tron_address"}), 400
    record = latest_record(address)
    if not record:
        return jsonify({"ok": False, "error": "not_found", "chain": "tron", "address": address}), 404
    return jsonify(api_record(record, "postgres_cache"))


@app.route("/api/tron/scan", methods=["POST", "OPTIONS"])
def tron_scan():
    if request.method == "OPTIONS":
        return ("", 204)
    payload = request.get_json(silent=True) or {}
    address = normalize_address(str(payload.get("address") or ""))
    use_cached = bool(payload.get("use_cached", True))
    if not valid_tron_address(address):
        return jsonify({"ok": False, "error": "invalid_tron_address"}), 400
    record = latest_record(address) if use_cached else None
    source = "postgres_cache"
    if record is None:
        try:
            record = scan_live(address)
            source = "live_scan"
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc), "chain": "tron", "address": address}), 400
    return jsonify(api_record(record, source))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8787")), debug=False)
