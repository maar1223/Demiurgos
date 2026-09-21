# -*- coding: utf-8 -*-
"""Read-only Hermes gateway liveness probe tests."""

import json
import os
from pathlib import Path
import sys

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _path in (str(_WIKI), str(_SUITE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from hermes_runtime_probe import HermesGatewayProbe, _pid_alive  # noqa: E402


def _record(home: Path, state="running", pid=4242, recorded_home=None):
    return {
        "gateway_state": state,
        "pid": pid,
        "hermes_home": str(recorded_home if recorded_home is not None else home),
    }


def test_running_record_with_live_pid(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    probe = HermesGatewayProbe(
        home, record_reader=lambda path: _record(home), pid_probe=lambda pid: pid == 4242
    )
    assert probe.is_running() is True


def test_down_states_are_not_running(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    for state in ("stopped", "startup_failed", None):
        probe = HermesGatewayProbe(
            home,
            record_reader=lambda path, state=state: _record(home, state=state),
            pid_probe=lambda pid: True,
        )
        assert probe.is_running() is False, state


def test_dead_pid_is_not_running(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    probe = HermesGatewayProbe(
        home, record_reader=lambda path: _record(home), pid_probe=lambda pid: False
    )
    assert probe.is_running() is False


def test_missing_or_corrupt_record_is_not_running(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    assert HermesGatewayProbe(home).is_running() is False

    (home / "gateway_state.json").write_text("{ not json", encoding="utf-8")
    assert HermesGatewayProbe(home).is_running() is False

    (home / "gateway_state.json").write_text("[1, 2]", encoding="utf-8")
    assert HermesGatewayProbe(home).is_running() is False


def test_mismatched_home_is_not_running(tmp_path: Path):
    home = tmp_path / "hermes"
    other = tmp_path / "other"
    home.mkdir()
    other.mkdir()
    probe = HermesGatewayProbe(
        home,
        record_reader=lambda path: _record(home, recorded_home=other),
        pid_probe=lambda pid: True,
    )
    assert probe.is_running() is False


def test_reader_failure_fails_closed(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()

    def _boom(path):
        raise OSError("unreadable")

    probe = HermesGatewayProbe(home, record_reader=_boom, pid_probe=lambda pid: True)
    assert probe.is_running() is False


def test_real_record_for_current_process_is_running(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "gateway_state.json").write_text(
        json.dumps(_record(home, pid=os.getpid())), encoding="utf-8"
    )
    assert HermesGatewayProbe(home).is_running() is True


def test_real_record_for_dead_pid_is_not_running(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "gateway_state.json").write_text(
        json.dumps(_record(home, pid=2_000_000_000)), encoding="utf-8"
    )
    assert HermesGatewayProbe(home).is_running() is False


def test_pid_alive_rejects_non_positive():
    assert _pid_alive(0) is False
    assert _pid_alive(-1) is False
    assert _pid_alive(True) is False
