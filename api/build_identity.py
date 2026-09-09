"""Which code produced this answer.

An independent review of 2026-09-08 could confirm a finding in the repository
but not that the finding described what production was serving: "Open status
does not prove the branch is not deployed. Production deployment provenance was
NOT checked." A green `/health` shows a process is answering; it says nothing
about which commit is answering.

This service is the reason the rule exists. `tron-api` served July code for
two months behind a green /health -- it tracked a stale branch, later it ran
the collector instead of the API, and in both cases the deployment reported
SUCCESS while no response said which commit was answering.

So every response carries the commit it came from and the version of the rules
that produced it.
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache

UNKNOWN = "unknown"

# Platforms that inject the deployed commit. Railway sets the first.
COMMIT_ENV_VARS = (
    "RAILWAY_GIT_COMMIT_SHA",
    "SOURCE_COMMIT",
    "GIT_COMMIT",
    "HEROKU_SLUG_COMMIT",
    "VERCEL_GIT_COMMIT_SHA",
)


@lru_cache(maxsize=1)
def build_commit() -> str:
    """The commit this process is running, or "unknown".

    Reported rather than guessed: a wrong commit is worse than none, because
    the whole point is to be able to trust what a measurement was measuring.
    """
    for name in COMMIT_ENV_VARS:
        value = (os.getenv(name) or "").strip()
        if value:
            return value[:40]

    # Local runs and any deploy that ships the .git directory.
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    if result.returncode != 0:
        return UNKNOWN
    return (result.stdout or "").strip()[:40] or UNKNOWN


def build_identity(**versions: str) -> dict[str, str]:
    """The identity block attached to every response."""
    identity: dict[str, str] = {"build_commit": build_commit()}
    identity.update({name: value for name, value in versions.items() if value})
    return identity
