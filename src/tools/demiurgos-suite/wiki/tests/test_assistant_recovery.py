# -*- coding: utf-8 -*-
"""Assistant recovery read model: launcher state dir, status file, cause mapping."""

from __future__ import annotations

import json
from pathlib import Path
import sys

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from assistant_recovery import (  # noqa: E402
    LAUNCHER_STATE_DIRNAME,
    STATUS_SCHEMA,
    launcher_state_dir,
    normalize_status,
    read_supervisor_status,
    recovery_view,
    supervisor_status_path,
    write_supervisor_status,
)


# --- launcher state dir mirrors the shell chain ----------------------------


def test_state_dir_prefers_xdg_runtime_dir():
    environ = {
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "TMPDIR": "/tmp",
        "XDG_CACHE_HOME": "/cache",
        "HOME": "/home/author",
    }
    assert launcher_state_dir(environ) == Path("/run/user/1000") / LAUNCHER_STATE_DIRNAME


def test_state_dir_uses_tmpdir_without_the_runtime_suffix():
    # Shell: ${TMPDIR:-...} replaces the whole base, so no /demiurgos/runtime.
    environ = {"TMPDIR": "/tmp", "HOME": "/home/author"}
    assert launcher_state_dir(environ) == Path("/tmp") / LAUNCHER_STATE_DIRNAME


def test_state_dir_uses_xdg_cache_home_under_demiurgos_runtime():
    environ = {"XDG_CACHE_HOME": "/cache", "HOME": "/home/author"}
    assert (
        launcher_state_dir(environ)
        == Path("/cache") / "demiurgos" / "runtime" / LAUNCHER_STATE_DIRNAME
    )


def test_state_dir_falls_back_to_home_cache():
    environ = {"HOME": "/home/author"}
    assert (
        launcher_state_dir(environ)
        == Path("/home/author") / ".cache" / "demiurgos" / "runtime" / LAUNCHER_STATE_DIRNAME
    )


def test_empty_values_behave_like_unset():
    environ = {"XDG_RUNTIME_DIR": "", "TMPDIR": "", "HOME": "/home/author"}
    assert launcher_state_dir(environ) == supervisor_status_path(environ).parent


def test_status_path_is_inside_the_state_dir():
    path = supervisor_status_path({"HOME": "/home/author"})
    assert path.name == "gateway-supervisor.json"
    assert path.parent.name == LAUNCHER_STATE_DIRNAME


# --- status file validation ------------------------------------------------


def _valid_payload(**overrides):
    payload = {
        "schema": STATUS_SCHEMA,
        "state": "running",
        "cause": None,
        "attempts": 0,
        "max_attempts": 3,
        "last_exit_code": None,
        "last_restart_at": None,
        "updated_at": "2026-11-23T20:00:00Z",
        "supervisor_pid": 111,
        "gateway_pid": 222,
    }
    payload.update(overrides)
    return payload


def test_write_then_read_roundtrip(tmp_path):
    path = write_supervisor_status(_valid_payload(), tmp_path / "status.json")
    status = read_supervisor_status(path)
    assert status is not None
    assert status["state"] == "running"
    assert status["gateway_pid"] == 222
    assert not list(tmp_path.glob("*.tmp"))


def test_missing_file_is_none(tmp_path):
    assert read_supervisor_status(tmp_path / "absent.json") is None


def test_corrupt_file_is_none(tmp_path):
    path = tmp_path / "status.json"
    path.write_text("{not json", encoding="utf-8")
    assert read_supervisor_status(path) is None


def test_wrong_schema_is_none():
    assert normalize_status(_valid_payload(schema="other/v9")) is None


def test_unknown_state_is_none():
    assert normalize_status(_valid_payload(state="exploded")) is None


def test_unknown_cause_is_none():
    assert normalize_status(_valid_payload(cause="provider_rejected")) is None


def test_negative_attempts_is_none():
    assert normalize_status(_valid_payload(attempts=-1)) is None


def test_non_object_is_none():
    assert normalize_status(["running"]) is None


# --- recovery view (closed vocabulary, no raw text) ------------------------


def _view(gateway_running, status=None):
    return recovery_view(gateway_running, status)


def test_running_gateway_needs_no_action():
    view = _view(True, normalize_status(_valid_payload()))
    assert view["gateway_running"] is True
    assert view["state"] == "running"
    assert view["cause"] is None
    assert view["can_restart"] is False


def test_no_status_reports_not_started_and_offers_restart():
    view = _view(False, None)
    assert view["state"] == "stopped"
    assert view["cause"] == "not_started"
    assert view["can_restart"] is True


def test_failed_config_invalid_never_offers_restart():
    status = normalize_status(
        _valid_payload(state="failed", cause="config_invalid", attempts=1)
    )
    view = _view(False, status)
    assert view["cause"] == "config_invalid"
    assert view["can_restart"] is False


def test_failed_not_started_never_offers_restart():
    status = normalize_status(_valid_payload(state="failed", cause="not_started"))
    view = _view(False, status)
    assert view["cause"] == "not_started"
    assert view["can_restart"] is False


def test_failed_exited_offers_restart_and_reports_attempts():
    status = normalize_status(
        _valid_payload(state="failed", cause="exited", attempts=3, max_attempts=3)
    )
    view = _view(False, status)
    assert view["cause"] == "exited"
    assert view["attempts"] == 3
    assert view["can_restart"] is True


def test_restarting_reports_exited_and_offers_restart():
    status = normalize_status(
        _valid_payload(state="restarting", cause="exited", attempts=1)
    )
    view = _view(False, status)
    assert view["state"] == "restarting"
    assert view["cause"] == "exited"
    assert view["can_restart"] is True


def test_stale_running_snapshot_reports_exited():
    # The file says running but the process probe says down: the child died
    # before the supervisor wrote its next transition.
    view = _view(False, normalize_status(_valid_payload(state="running")))
    assert view["state"] == "running"
    assert view["cause"] == "exited"
    assert view["can_restart"] is True


def test_view_carries_only_the_contract_fields():
    view = _view(False, None)
    assert set(view) == {
        "gateway_running",
        "state",
        "cause",
        "attempts",
        "can_restart",
        "updated_at",
    }


def test_view_never_leaks_raw_text_fields():
    status = normalize_status(
        _valid_payload(state="failed", cause="exited", last_exit_code=1)
    )
    serialized = json.dumps(_view(False, status))
    assert "Traceback" not in serialized
    assert "last_exit_code" not in serialized
