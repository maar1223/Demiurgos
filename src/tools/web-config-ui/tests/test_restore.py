"""RED tests for the atomic restore and 30-second post-edit sync boundary.

Covers the restore guarantees the wizard requires:
1. Restore is atomic: it stages into a sibling temp directory and only swaps
   into the target on success, leaving the target untouched on failure.
2. Restore reports explicit conflict or error states instead of silently
   overwriting or half-writing.
3. The 30-second post-edit sync is debounced: consecutive edits collapse
   into one sync fired 30s after the last edit.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_UI = Path(__file__).resolve().parents[1]
if str(_UI) not in sys.path:
    sys.path.insert(0, str(_UI))

from backup import (  # noqa: E402
    RestoreManager,
    SyncScheduler,
)


class _FakeRclone:
    """Test double standing in for the rclone binary.

    Writes a fake executable that copies a source file or directory into a
    staging directory, without ever touching the real filesystem beyond what
    the adapter asks it to. A missing source makes the process exit non-zero
    (the same way a real rclone copy failure would).
    """

    def __init__(self, tmp_path: Path) -> None:
        self.remote = tmp_path / "remote"
        self.remote.mkdir(exist_ok=True)
        self.script = tmp_path / "fake-rclone"
        self.script.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "import shutil\n"
            "import sys\n"
            "src = sys.argv[2]\n"
            "dst = sys.argv[3]\n"
            "if not os.path.exists(src):\n"
            "    print(f'ERROR: source not found: {src}', file=sys.stderr)\n"
            "    sys.exit(1)\n"
            "if os.path.isdir(src):\n"
            "    shutil.copytree(src, dst, dirs_exist_ok=True)\n"
            "else:\n"
            "    os.makedirs(dst, exist_ok=True)\n"
            "    shutil.copy2(src, os.path.join(dst, os.path.basename(src)))\n",
            encoding="utf-8",
        )
        self.script.chmod(0o755)


class TestAtomicRestore:
    def test_restore_stages_then_swaps(self, tmp_path: Path) -> None:
        fake = _FakeRclone(tmp_path)
        (fake.remote / "lore.md").write_text("remote content", encoding="utf-8")
        target = tmp_path / "worlds" / "vibrantes"
        target.mkdir(parents=True)

        manager = RestoreManager(
            binary=str(fake.script),
            root=str(tmp_path),
            remote=str(fake.remote),
            timeout=5.0,
        )
        status = manager.restore(source_relative="lore.md", target=target)

        assert status.state == "ok"
        assert (target / "lore.md").read_text(encoding="utf-8") == "remote content"

    def test_failed_restore_leaves_target_untouched(self, tmp_path: Path) -> None:
        fake = _FakeRclone(tmp_path)
        fake.fail = True
        target = tmp_path / "worlds" / "vibrantes"
        target.mkdir(parents=True)
        (target / "existing.md").write_text("keep me", encoding="utf-8")

        manager = RestoreManager(
            binary=str(fake.script),
            root=str(tmp_path),
            remote=str(fake.remote),
            timeout=5.0,
        )
        status = manager.restore(source_relative="lore.md", target=target)

        assert status.state in {"error", "unavailable", "timeout"}
        assert (target / "existing.md").read_text(encoding="utf-8") == "keep me"

    def test_atomic_swap_leaves_no_partial_state(self, tmp_path: Path) -> None:
        fake = _FakeRclone(tmp_path)
        (fake.remote / "a.md").write_text("a", encoding="utf-8")
        target = tmp_path / "worlds" / "vibrantes"
        target.mkdir(parents=True)

        manager = RestoreManager(
            binary=str(fake.script),
            root=str(tmp_path),
            remote=str(fake.remote),
            timeout=5.0,
        )
        status = manager.restore(source_relative="a.md", target=target)

        assert status.state == "ok"
        # No temp/staging leftovers next to the target.
        leftovers = [p for p in target.parent.iterdir() if "tmp" in p.name or ".tmp" in p.suffix]
        assert leftovers == []


class TestExplicitConflictError:
    def test_missing_source_reports_explicit_error(self, tmp_path: Path) -> None:
        fake = _FakeRclone(tmp_path)
        target = tmp_path / "worlds" / "vibrantes"
        target.mkdir(parents=True)

        manager = RestoreManager(
            binary=str(fake.script),
            root=str(tmp_path),
            remote=str(fake.remote / "does-not-exist"),
            timeout=5.0,
        )
        status = manager.restore(source_relative="missing.md", target=target)
        assert status.state in {"error", "unavailable"}
        assert status.detail  # never silently succeed

    def test_conflict_returns_explicit_conflict_state(self, tmp_path: Path) -> None:
        fake = _FakeRclone(tmp_path)
        (fake.remote / "lore.md").write_text("remote version", encoding="utf-8")
        target = tmp_path / "worlds" / "vibrantes"
        target.mkdir(parents=True)
        (target / "lore.md").write_text("local version", encoding="utf-8")

        manager = RestoreManager(
            binary=str(fake.script),
            root=str(tmp_path),
            remote=str(fake.remote),
            timeout=5.0,
        )
        status = manager.restore(source_relative="lore.md", target=target)
        assert status.state == "conflict"
        assert (target / "lore.md").read_text(encoding="utf-8") == "local version"


class TestThirtySecondPostEditSync:
    def test_edits_debounce_to_single_sync(self, tmp_path: Path) -> None:
        fired: list[str] = []
        scheduler = SyncScheduler(
            callback=lambda: fired.append("sync"),
            delay_seconds=0.05,
        )
        scheduler.notify_edit()
        scheduler.notify_edit()
        scheduler.notify_edit()
        deadline = time.time() + 1.0
        while time.time() < deadline and not fired:
            time.sleep(0.01)
        scheduler.stop()
        assert fired == ["sync"]

    def test_sync_fires_after_delay_not_immediately(self, tmp_path: Path) -> None:
        fired: list[str] = []
        scheduler = SyncScheduler(
            callback=lambda: fired.append("sync"),
            delay_seconds=0.2,
        )
        scheduler.notify_edit()
        time.sleep(0.05)  # well before the 30s-equivalent window
        assert fired == []
        deadline = time.time() + 1.0
        while time.time() < deadline and not fired:
            time.sleep(0.01)
        scheduler.stop()
        assert fired == ["sync"]

    def test_stop_cancels_pending_sync(self, tmp_path: Path) -> None:
        fired: list[str] = []
        scheduler = SyncScheduler(
            callback=lambda: fired.append("sync"),
            delay_seconds=0.05,
        )
        scheduler.notify_edit()
        scheduler.stop()
        time.sleep(0.15)
        assert fired == []
