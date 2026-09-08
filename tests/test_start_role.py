"""The entrypoint must never start a process nobody asked for.

Both Railway services deploy this repo through start.py. The collector is the
default, so the risk that matters is the reverse of the usual one: a typo or an
unset variable must not silently flip a service onto the other process.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import start  # noqa: E402


def test_unset_role_runs_the_collector():
    """The collector service sets nothing and must behave exactly as before."""
    assert start.resolve_role({}) == "collector"


def test_api_role_is_honoured():
    assert start.resolve_role({"RUGBUSTER_ROLE": "api"}) == "api"


@pytest.mark.parametrize("value", ["API", " api ", "Api"])
def test_role_is_case_and_whitespace_insensitive(value):
    """A stray space in a dashboard field must not cost another debugging round."""
    assert start.resolve_role({"RUGBUSTER_ROLE": value}) == "api"


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_role_falls_back_to_collector(value):
    assert start.resolve_role({"RUGBUSTER_ROLE": value}) == "collector"


def test_unknown_role_falls_back_to_collector_rather_than_guessing(capsys):
    assert start.resolve_role({"RUGBUSTER_ROLE": "webserver"}) == "collector"
    assert "not one of" in capsys.readouterr().err


def test_api_command_binds_the_port_railway_supplies():
    command = start.build_command("api", {"PORT": "9001"})
    assert command == ["gunicorn", "api.tron_api:app", "--bind", "0.0.0.0:9001"]


def test_api_command_has_a_port_default_so_it_never_binds_a_literal_brace():
    command = start.build_command("api", {})
    assert "0.0.0.0:8080" in command
    assert not any("{port}" in part for part in command)


def test_collector_command_points_at_the_worker():
    command = start.build_command("collector", {})
    assert command[1] == "chains/tron/tron_worker.py"


def test_every_role_builds_a_runnable_command():
    for role in start.COMMANDS:
        command = start.build_command(role, {"PORT": "1234"})
        assert command and all(isinstance(part, str) for part in command)
