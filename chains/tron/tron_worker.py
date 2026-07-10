"""Dedicated TRON worker entrypoint for the Railway TRON service."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chains.tron import tron_collector_v1 as tron


def env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def configure_discovery() -> None:
    tron.GECKOTERMINAL_TOP_POOLS_ENABLED = env_bool("TRON_TOP_POOLS_ENABLED", "true")
    tron.GECKOTERMINAL_POOL_PAGES = min(tron.GECKOTERMINAL_POOL_PAGES, 2)
    tron.DEX_EVENT_SCAN_ENABLED = env_bool("TRON_DEX_EVENT_SCAN_ENABLED", "true")
    tron.FALLBACK_CONTRACT_SCAN_ENABLED = env_bool("TRON_FALLBACK_SCAN_ENABLED", "true")


def main() -> None:
    configure_discovery()
    tron.init_database()
    tron.poll_loop(Path(tron.OUTPUT_FILE))


if __name__ == "__main__":
    main()
