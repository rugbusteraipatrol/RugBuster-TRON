#!/usr/bin/env python3
"""Pick the process this service should run, from a plain environment variable.

Two Railway services deploy this repo: a collector that crawls the chain, and
`tron-api`, which serves /api/tron/score on demand. They differ only in start
command.

Selecting that with Railway's own mechanisms did not hold. `RAILWAY_CONFIG_PATH`
pointing at railway.api.json is set on tron-api and is ignored there -- a fresh
build with the variable active still ran the collector -- and a `web:` entry in
the Procfile loses to railway.json's explicit startCommand. Every one of those
attempts reported a SUCCESS deployment while serving nothing, with a 502 as the
only outward sign.

Ordinary environment variables are read reliably, so the choice is made here
instead, where it is in git, testable, and visible in the log line below.

The default is the collector, so a service that sets nothing behaves exactly as
it did before this file existed.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys

ROLE_ENV_VAR = "RUGBUSTER_ROLE"
DEFAULT_ROLE = "collector"

COMMANDS = {
    "api": ["gunicorn", "api.tron_api:app", "--bind", "0.0.0.0:{port}"],
    "collector": [sys.executable, "chains/tron/tron_worker.py"],
}


def resolve_role(environ: dict | None = None) -> str:
    """Normalise the requested role, falling back to the collector.

    An unrecognised value is a misconfiguration, not a reason to guess: it is
    reported loudly and treated as the default rather than silently starting
    something the operator did not ask for.
    """
    environ = os.environ if environ is None else environ
    raw = (environ.get(ROLE_ENV_VAR) or "").strip().lower()
    if not raw:
        return DEFAULT_ROLE
    if raw not in COMMANDS:
        print(
            f"[start] {ROLE_ENV_VAR}={raw!r} is not one of {sorted(COMMANDS)}; "
            f"falling back to {DEFAULT_ROLE}",
            file=sys.stderr,
            flush=True,
        )
        return DEFAULT_ROLE
    return raw


def build_command(role: str, environ: dict | None = None) -> list[str]:
    environ = os.environ if environ is None else environ
    port = environ.get("PORT", "8080")
    return [part.format(port=port) for part in COMMANDS[role]]


def main() -> int:
    role = resolve_role()
    command = build_command(role)
    # Printed so the runtime log says which process started. Reading the
    # deployment status is not enough -- a service running the wrong process
    # still reports SUCCESS.
    print(f"[start] {ROLE_ENV_VAR}={role} -> {shlex.join(command)}", flush=True)
    return subprocess.call(command)


if __name__ == "__main__":
    sys.exit(main())
