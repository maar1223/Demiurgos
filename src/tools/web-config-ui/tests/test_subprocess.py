"""RED tests for the safe rclone subprocess boundary.

Covers the four guarantees the wizard requires when invoking an external
binary:
1. The external process receives only allowlisted arguments (command and
   flags) — anything else is rejected before any subprocess is spawned.
2. Local paths are validated against the project root — path traversal is
   rejected.
3. An unavailable rclone binary is reported as a non-blocking status.
4. A timed-out rclone is reported as a non-blocking status — Core stays
   usable and nothing raises.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_UI = Path(__file__).resolve().parents[1]
if str(_UI) not in sys.path:
    sys.path.insert(0, str(_UI))

from backup import (  # noqa: E402
    ALLOWED_COMMANDS,
    DisallowedArgumentError,
    RcloneRunner,
    TraversalError,
    build_rclone_argv,
    validate_local_path,
)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    return root


class TestArgumentAllowlist:
    def test_allowlisted_command_accepted(self, tmp_path: Path) -> None:
        argv = build_rclone_argv("sync", ["mundos", "gdrive:demiurgos/mundos"], _root(tmp_path))
        assert argv[0] == "sync"

    def test_disallowed_command_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DisallowedArgumentError):
            build_rclone_argv("delete", ["mundos"], _root(tmp_path))

    def test_disallowed_flag_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DisallowedArgumentError):
            build_rclone_argv("sync", ["mundos", "gdrive:x", "--dry-run"], _root(tmp_path))

    def test_allowlisted_flag_with_value_accepted(self, tmp_path: Path) -> None:
        argv = build_rclone_argv(
            "sync",
            ["mundos", "gdrive:demiurgos/mundos", "--transfers=4"],
            _root(tmp_path),
        )
        assert "--transfers=4" in argv

    def test_flag_value_must_be_simple(self, tmp_path: Path) -> None:
        with pytest.raises(DisallowedArgumentError):
            build_rclone_argv(
                "sync",
                ["mundos", "gdrive:x", "--transfers=4;rm -rf /"],
                _root(tmp_path),
            )

    def test_only_allowlisted_commands_exist(self) -> None:
        assert "sync" in ALLOWED_COMMANDS
        assert "copy" in ALLOWED_COMMANDS
        assert "delete" not in ALLOWED_COMMANDS
        assert "purge" not in ALLOWED_COMMANDS


class TestPathTraversal:
    def test_dotdot_escape_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(TraversalError):
            validate_local_path("../../etc/passwd", _root(tmp_path))

    def test_absolute_path_outside_root_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(TraversalError):
            validate_local_path(str(tmp_path / "elsewhere"), _root(tmp_path))

    def test_relative_inside_root_allowed(self, tmp_path: Path) -> None:
        resolved = validate_local_path("mundos", _root(tmp_path))
        assert resolved == (_root(tmp_path) / "mundos").resolve()

    def test_build_rejects_traversal_argument(self, tmp_path: Path) -> None:
        with pytest.raises(TraversalError):
            build_rclone_argv("sync", ["../escape", "gdrive:x"], _root(tmp_path))

    def test_remote_ref_with_traversal_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DisallowedArgumentError):
            build_rclone_argv("sync", ["mundos", "gdrive:../x"], _root(tmp_path))


class TestUnavailableNonBlocking:
    def test_missing_binary_reports_unavailable(self, tmp_path: Path) -> None:
        runner = RcloneRunner(binary=str(tmp_path / "no-such-rclone"), root=str(_root(tmp_path)))
        status = runner.run("version", [])
        assert status.state == "unavailable"
        assert not status.ok

    def test_missing_binary_does_not_raise(self, tmp_path: Path) -> None:
        runner = RcloneRunner(binary=str(tmp_path / "no-such-rclone"), root=str(_root(tmp_path)))
        assert runner.run("version", []).state == "unavailable"


class TestTimeoutNonBlocking:
    def test_timeout_reports_timeout_state(self, tmp_path: Path) -> None:
        fake = _fake_slow_rclone(tmp_path)
        runner = RcloneRunner(binary=str(fake), root=str(_root(tmp_path)), timeout=0.15)
        status = runner.run("version", [], timeout=0.05)
        assert status.state == "timeout"
        assert not status.ok

    def test_timeout_does_not_raise(self, tmp_path: Path) -> None:
        fake = _fake_slow_rclone(tmp_path)
        runner = RcloneRunner(binary=str(fake), root=str(_root(tmp_path)), timeout=0.15)
        assert runner.run("version", [], timeout=0.05).state == "timeout"


def _fake_slow_rclone(tmp_path: Path) -> Path:
    """Write a fake rclone executable that sleeps on every invocation."""
    script = tmp_path / "rclone-slow"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script
