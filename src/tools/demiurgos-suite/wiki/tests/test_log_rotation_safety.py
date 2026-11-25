# -*- coding: utf-8 -*-
"""Durable regression probes for launcher log rotation (S5, T1.1).

Pins the safety properties a refactor could silently break: an O_APPEND writer
survives copy+truncate; rotation is inert on filesystem failure; the archive
count is bounded; kill-switch/garbage env resolves as documented. Supplied by
the independent verifier and kept as part of the unit.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import log_rotation  # noqa: E402
from log_rotation import (  # noqa: E402
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_MAX_BYTES,
    rotate_if_needed,
    rotation_settings,
)


def _write(path: Path, size: int, filler: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(filler * size)
    return path


def test_append_writer_keeps_writing_to_the_live_path_after_rotation(tmp_path):
    # S5/T1.1: the launcher opens the log with ``>>`` (O_APPEND); the writer's
    # file description must survive copy+truncate with no sparse hole.
    log = tmp_path / "demiurgos-api.log"
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, b"A" * 100)
        created = rotate_if_needed(log, max_bytes=100, keep=1)
        os.write(fd, b"B" * 30)
    finally:
        os.close(fd)

    assert created == ["demiurgos-api.log.1"]
    assert (tmp_path / "demiurgos-api.log.1").read_bytes() == b"A" * 100
    live = log.read_bytes()
    assert live == b"B" * 30
    assert b"\x00" not in live


@pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt", reason="needs POSIX shell fd"
)
def test_shell_append_redirection_survives_rotation(tmp_path):
    # S5/T1.1: same property through a real shell ``>>`` fd in another process.
    # The child cannot write the second block until the sentinel exists, so the
    # rotation is deterministically inside the window between the two writes.
    log = tmp_path / "demiurgos-gateway.log"
    release = tmp_path / "release"
    script = (
        r'''exec 3>>"$1"; printf '%0.sA' {1..100} >&3; '''
        r'''while [ ! -f "$2" ]; do sleep 0.02; done; '''
        r'''printf '%0.sB' {1..30} >&3'''
    )
    child = subprocess.Popen(["bash", "-c", script, "_", str(log), str(release)])
    try:
        for _ in range(500):
            if log.exists() and log.stat().st_size >= 100:
                break
            time.sleep(0.01)
        created = rotate_if_needed(log, max_bytes=100, keep=1)
        release.write_text("go", encoding="utf-8")
        child.wait(timeout=15)
    finally:
        if child.poll() is None:
            child.kill()
    assert created == ["demiurgos-gateway.log.1"]
    assert (tmp_path / "demiurgos-gateway.log.1").read_bytes() == b"A" * 100
    assert log.read_bytes() == b"B" * 30


def test_rotation_is_inert_when_the_archive_slot_is_a_directory(tmp_path):
    # S5/T1.1: a filesystem failure must leave the live log byte-identical.
    log = _write(tmp_path / "demiurgos-api.log", 100)
    (tmp_path / "demiurgos-api.log.1").mkdir()

    assert rotate_if_needed(log, max_bytes=100, keep=1) == []
    assert log.read_bytes() == b"x" * 100
    assert (tmp_path / "demiurgos-api.log.1").is_dir()


def test_rotation_is_inert_when_the_oldest_archive_is_a_directory(tmp_path):
    # S5/T1.1: same, on the unlink leg of the shift.
    log = _write(tmp_path / "demiurgos-gateway.log", 100)
    (tmp_path / "demiurgos-gateway.log.2").mkdir()

    assert rotate_if_needed(log, max_bytes=100, keep=2) == []
    assert log.read_bytes() == b"x" * 100


def test_archive_count_is_bounded_even_when_the_live_file_overshoots(tmp_path):
    # S5/T1.1: ``keep`` is a hard bound on the number of archives. A live file
    # that grew past ``max_bytes`` between checks is archived whole (the
    # docstring's ``(keep + 1) * max_bytes`` is a target, not a hard ceiling);
    # count and data preservation are what matter.
    log = _write(tmp_path / "launcher.log", 1000)
    rotate_if_needed(log, max_bytes=100, keep=2)

    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "launcher.log",
        "launcher.log.1",
    ]
    assert (tmp_path / "launcher.log.1").read_bytes() == b"x" * 1000
    assert log.read_bytes() == b""


def test_the_archive_keeps_the_live_file_permissions(tmp_path):
    # S5/T1.1: a hardened log must not become world-readable through rotation.
    log = _write(tmp_path / "demiurgos-api.log", 128)
    log.chmod(0o600)

    rotate_if_needed(log, max_bytes=128, keep=1)

    assert (tmp_path / "demiurgos-api.log.1").stat().st_mode & 0o777 == 0o600


def test_a_failed_copy_never_evicts_or_shifts_existing_archives(tmp_path):
    # S5/T1.1 (review R4-shift-before-copy): copying first and evicting later
    # means a full disk cannot destroy history on every retry.
    log = _write(tmp_path / "demiurgos-api.log", 256)
    (tmp_path / "demiurgos-api.log.1").write_bytes(b"a" * 64)
    (tmp_path / "demiurgos-api.log.2").write_bytes(b"b" * 64)
    (tmp_path / "demiurgos-api.log.rotating").mkdir()

    assert rotate_if_needed(log, max_bytes=256, keep=2) == []
    assert log.read_bytes() == b"x" * 256
    assert (tmp_path / "demiurgos-api.log.1").read_bytes() == b"a" * 64
    assert (tmp_path / "demiurgos-api.log.2").read_bytes() == b"b" * 64


def test_a_failed_rotation_is_logged(tmp_path, caplog):
    # S5/T1.1 (review R4-silent-rotation-failure): a dead rotation must not hide
    # behind an unbounded live log with no operator-visible signal.
    log = _write(tmp_path / "demiurgos-api.log", 256)
    (tmp_path / "demiurgos-api.log.rotating").mkdir()

    with caplog.at_level(logging.WARNING, logger="log_rotation"):
        rotate_if_needed(log, max_bytes=256, keep=1)

    assert any("log rotation copy failed" in record.getMessage() for record in caplog.records)


def test_the_archive_is_staged_privately_before_any_eviction(tmp_path, monkeypatch):
    # S5/T1.1 (review R1-toc-mode): the staged copy is created with a private
    # mode, so a hardened log is never briefly world-readable mid-rotation.
    log = _write(tmp_path / "demiurgos-api.log", 128)
    log.chmod(0o600)
    seen = {}

    real_stage = log_rotation._stage_copy

    def spy(source, staged):
        real_stage(source, staged)
        seen["mode"] = staged.stat().st_mode & 0o777
        seen["exists"] = staged.exists()

    monkeypatch.setattr(log_rotation, "_stage_copy", spy)

    rotate_if_needed(log, max_bytes=128, keep=1)

    assert seen == {"mode": 0o600, "exists": True}


def test_garbage_kill_switch_value_keeps_rotation_enabled():
    # S5/T1.1: only the documented off values disable; anything else is on.
    assert rotation_settings({"DEMIURGOS_LOG_ROTATION": "banana"}).enabled is True
    assert rotation_settings({"DEMIURGOS_LOG_ROTATION": "  OFF  "}).enabled is False


def test_zero_keep_and_garbage_caps_fall_back_to_safe_values():
    # S5/T1.1: keep=0 would silently store nothing; it clamps to one archive.
    settings = rotation_settings(
        {
            "DEMIURGOS_LOG_KEEP": "0",
            "DEMIURGOS_LOG_MAX_BYTES": "not-a-number",
            "DEMIURGOS_LOG_ROTATE_INTERVAL_SECONDS": "-5",
        }
    )
    assert settings.keep == 1
    assert settings.max_bytes == DEFAULT_MAX_BYTES
    assert settings.interval == DEFAULT_INTERVAL_SECONDS
