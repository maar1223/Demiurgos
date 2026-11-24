# -*- coding: utf-8 -*-
"""Launcher log rotation (Phase 1, S5).

The launcher opens three logs with ``>>`` (``demiurgos-api.log``,
``demiurgos-gateway.log``, ``launcher.log``) and nothing bounds them, so a
report sent after weeks of use arrives with a single gigantic file. Rotation is
size-based, keeps a bounded number of archives, and never renames a file a live
process holds open (copy + truncate is safe for ``O_APPEND`` writers on every
platform the product supports).
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from log_rotation import (  # noqa: E402
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_KEEP,
    DEFAULT_MAX_BYTES,
    resolve_log_dir,
    rotate_if_needed,
    rotate_log_dir,
    rotation_settings,
    run_rotation_loop,
    start_rotation,
)


def _write(path: Path, size: int, filler: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(filler * size)
    return path


# --- per-file rotation -----------------------------------------------------


def test_small_file_is_left_alone(tmp_path):
    log = _write(tmp_path / "demiurgos-api.log", 10)

    created = rotate_if_needed(log, max_bytes=1024, keep=3)

    assert created == []
    assert log.read_bytes() == b"x" * 10
    assert not (tmp_path / "demiurgos-api.log.1").exists()


def test_file_at_the_cap_moves_to_the_first_archive_and_the_live_file_empties(tmp_path):
    log = _write(tmp_path / "demiurgos-api.log", 2048)

    created = rotate_if_needed(log, max_bytes=2048, keep=3)

    assert created == ["demiurgos-api.log.1"]
    # The live file still exists (an open ``>>`` handle keeps writing to it).
    assert log.exists()
    assert log.stat().st_size == 0
    assert (tmp_path / "demiurgos-api.log.1").read_bytes() == b"x" * 2048


def test_archives_shift_and_stay_bounded_by_keep(tmp_path):
    log = tmp_path / "demiurgos-gateway.log"
    for letter in (b"a", b"b", b"c", b"d"):
        _write(log, 100, filler=letter)
        rotate_if_needed(log, max_bytes=100, keep=2)

    assert (tmp_path / "demiurgos-gateway.log.1").read_bytes() == b"d" * 100
    assert (tmp_path / "demiurgos-gateway.log.2").read_bytes() == b"c" * 100
    # keep=2 is a hard bound: the third generation is dropped, never written.
    assert not (tmp_path / "demiurgos-gateway.log.3").exists()


def test_missing_file_is_not_an_error(tmp_path):
    assert rotate_if_needed(tmp_path / "absent.log", max_bytes=1, keep=1) == []


def test_archive_names_never_match_the_bug_report_glob(tmp_path):
    # ``bug_report._default_log_source`` reads ``*.log``. An archive must not
    # be picked up as a second copy of the same bytes.
    _write(tmp_path / "launcher.log", 64)

    rotate_if_needed(tmp_path / "launcher.log", max_bytes=64, keep=3)

    assert sorted(p.name for p in tmp_path.glob("*.log")) == ["launcher.log"]


# --- directory rotation ----------------------------------------------------


def test_rotate_log_dir_rotates_every_launcher_log(tmp_path):
    for name in ("demiurgos-api.log", "demiurgos-gateway.log", "launcher.log"):
        _write(tmp_path / name, 2048)

    rotated = rotate_log_dir(tmp_path, max_bytes=1024, keep=3)

    assert set(rotated) == {"demiurgos-api.log", "demiurgos-gateway.log", "launcher.log"}
    for name in rotated:
        assert (tmp_path / f"{name}.1").stat().st_size == 2048
        assert (tmp_path / name).stat().st_size == 0


def test_rotate_log_dir_ignores_everything_but_plain_logs(tmp_path):
    archive = _write(tmp_path / "demiurgos-api.log.1", 4096)
    state = _write(tmp_path / "state.json", 4096)

    rotated = rotate_log_dir(tmp_path, max_bytes=1024, keep=2)

    assert rotated == {}
    assert archive.stat().st_size == 4096
    assert state.stat().st_size == 4096


def test_rotate_log_dir_on_a_missing_directory_is_not_an_error(tmp_path):
    assert rotate_log_dir(tmp_path / "absent", max_bytes=1, keep=1) == {}


def test_symlinked_logs_are_skipped(tmp_path):
    target = _write(tmp_path / "real.txt", 4096)
    (tmp_path / "linked.log").symlink_to(target)

    rotated = rotate_log_dir(tmp_path, max_bytes=1024, keep=1)

    assert "linked.log" not in rotated
    assert target.stat().st_size == 4096


# --- settings --------------------------------------------------------------


def test_settings_defaults():
    settings = rotation_settings({})

    assert settings.enabled is True
    assert settings.max_bytes == DEFAULT_MAX_BYTES
    assert settings.keep == DEFAULT_KEEP
    assert settings.interval == DEFAULT_INTERVAL_SECONDS


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "FALSE"])
def test_settings_kill_switch(value):
    assert rotation_settings({"DEMIURGOS_LOG_ROTATION": value}).enabled is False


def test_settings_read_overrides():
    settings = rotation_settings(
        {
            "DEMIURGOS_LOG_MAX_BYTES": "2048",
            "DEMIURGOS_LOG_KEEP": "5",
            "DEMIURGOS_LOG_ROTATE_INTERVAL_SECONDS": "7.5",
        }
    )

    assert (settings.max_bytes, settings.keep, settings.interval) == (2048, 5, 7.5)


def test_settings_fall_back_on_garbage_and_never_allow_zero_archives():
    settings = rotation_settings(
        {
            "DEMIURGOS_LOG_MAX_BYTES": "nope",
            "DEMIURGOS_LOG_KEEP": "0",
            "DEMIURGOS_LOG_ROTATE_INTERVAL_SECONDS": "-3",
        }
    )

    assert settings.max_bytes == DEFAULT_MAX_BYTES
    assert settings.keep == 1
    assert settings.interval == DEFAULT_INTERVAL_SECONDS


# --- loop and wiring ------------------------------------------------------


def test_loop_rotates_once_then_honours_an_already_set_stop_event(tmp_path):
    _write(tmp_path / "demiurgos-api.log", 512)
    stop = threading.Event()
    stop.set()

    run_rotation_loop(tmp_path, max_bytes=256, keep=2, interval=3600.0, stop_event=stop)

    assert (tmp_path / "demiurgos-api.log.1").stat().st_size == 512


def test_resolve_log_dir_prefers_the_launcher_export(tmp_path):
    assert resolve_log_dir(install_root=tmp_path / "install", environ={"DEMIURGOS_LOG_DIR": str(tmp_path)}) == tmp_path


def test_resolve_log_dir_uses_the_install_root(tmp_path):
    assert resolve_log_dir(install_root=tmp_path, environ={}) == tmp_path / "logs"


def test_resolve_log_dir_uses_the_dev_checkout_root(tmp_path):
    assert resolve_log_dir(install_root=None, code_root=tmp_path, environ={}) == tmp_path / "logs"


def test_resolve_log_dir_falls_back_to_the_checkout_root_it_lives_in(tmp_path, monkeypatch):
    import log_rotation

    fake_module = tmp_path / "src" / "tools" / "demiurgos-suite" / "wiki" / "log_rotation.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("", encoding="utf-8")
    monkeypatch.setattr(log_rotation, "__file__", str(fake_module))

    assert log_rotation.resolve_log_dir(environ={}) == tmp_path / "logs"


def test_start_rotation_is_off_under_the_kill_switch(tmp_path):
    assert start_rotation(environ={"DEMIURGOS_LOG_ROTATION": "0", "DEMIURGOS_LOG_DIR": str(tmp_path)}) is None


def test_start_rotation_skips_a_missing_log_dir(tmp_path):
    environ = {"DEMIURGOS_LOG_DIR": str(tmp_path / "absent")}

    assert start_rotation(environ=environ) is None


def test_start_rotation_runs_one_pass_and_returns_the_thread(tmp_path):
    _write(tmp_path / "launcher.log", 512)
    environ = {
        "DEMIURGOS_LOG_DIR": str(tmp_path),
        "DEMIURGOS_LOG_MAX_BYTES": "256",
        "DEMIURGOS_LOG_ROTATE_INTERVAL_SECONDS": "0.01",
    }
    stop = threading.Event()

    thread = start_rotation(environ=environ, stop_event=stop)

    assert thread is not None
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert (tmp_path / "launcher.log.1").stat().st_size == 512


def test_api_lifespan_wiring_calls_start_rotation(monkeypatch):
    # The wiring is three guarded lines in ``_lifespan``; this pins it so a
    # silent deletion cannot pass the suite.
    import api_server
    import log_rotation

    calls = []
    monkeypatch.setattr(
        log_rotation,
        "start_rotation",
        lambda **kwargs: calls.append(kwargs) or None,
    )

    api_server._start_log_rotation()

    assert len(calls) == 1
    assert "install_root" in calls[0]
    assert "code_root" in calls[0]


def test_api_lifespan_actually_invokes_the_wiring():
    # Booting the whole app to observe one startup thread would drag every store
    # into the test; asserting the call site is the cheap guard that catches the
    # regression that matters (someone dropping the hook).
    import inspect

    import api_server

    assert "_start_log_rotation()" in inspect.getsource(api_server._lifespan)
