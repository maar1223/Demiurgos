# -*- coding: utf-8 -*-
"""Stable desktop entry point: the shortcut must survive a version flip.

The desktop file used to exec `<install_root>/current/scripts/start-demiurgos.sh`
directly, so a dangling or half-written `current` took the shortcut down with it
(2026-11-18). These tests pin the wrapper that resolves the active version and
repairs a broken link.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]
WRAPPER = REPO_ROOT / "scripts" / "demiurgos"
TEMPLATE = REPO_ROOT / "desktop" / "Demiurgos.desktop"


def _version(root: Path, name: str, marker: str, mtime: float | None = None) -> Path:
    version = root / "app" / name
    (version / "scripts").mkdir(parents=True)
    (version / ".venv" / "bin").mkdir(parents=True)
    launcher = version / "scripts" / "start-demiurgos.sh"
    launcher.write_text(f"#!/bin/sh\necho {marker}\n", encoding="utf-8")
    launcher.chmod(0o755)
    python = version / ".venv" / "bin" / "python"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)
    if mtime is not None:
        os.utime(version, (mtime, mtime))
    return version


def _entrypoint(root: Path) -> Path:
    (root / "bin").mkdir(parents=True, exist_ok=True)
    wrapper = root / "bin" / "demiurgos"
    shutil.copy2(WRAPPER, wrapper)
    wrapper.chmod(0o755)
    return wrapper


def _run(wrapper: Path, action: str = "start") -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(wrapper), action],
        capture_output=True,
        text=True,
        timeout=20,
        env={
            "HOME": str(wrapper.parents[2]),
            "PATH": "/usr/bin:/bin",
            "DEMIURGOS_NO_NOTIFY": "1",
        },
    )


def _log(root: Path) -> str:
    log = root / "logs" / "launcher.log"
    return log.read_text(encoding="utf-8") if log.exists() else ""


def test_template_exec_points_at_the_stable_entry_point() -> None:
    exec_lines = [
        line for line in TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line.startswith("Exec=")
    ]
    assert exec_lines == ["Exec=@LAUNCHER_ENTRY@ start"]
    assert "start-demiurgos.sh" not in exec_lines[0]


def test_entrypoint_runs_the_active_version(tmp_path) -> None:
    version = _version(tmp_path, "0.1.0", "active")
    (tmp_path / "current").symlink_to("app/0.1.0")

    done = _run(_entrypoint(tmp_path))

    assert done.returncode == 0
    assert done.stdout.strip() == "active"
    assert (tmp_path / "current").resolve() == version.resolve()


def test_entrypoint_repairs_a_dangling_current_to_the_newest_bootable(tmp_path) -> None:
    _version(tmp_path, "0.1.0", "old", mtime=1_700_000_000)
    _version(tmp_path, "0.2.0", "newest", mtime=1_800_000_000)
    (tmp_path / "current").symlink_to("app/gone")

    done = _run(_entrypoint(tmp_path))

    assert done.returncode == 0
    assert done.stdout.strip() == "newest"
    assert os.readlink(tmp_path / "current") == "app/0.2.0"
    assert "repairing current -> app/0.2.0" in _log(tmp_path)


def test_entrypoint_fails_loudly_when_nothing_is_bootable(tmp_path) -> None:
    (tmp_path / "app").mkdir()
    done = _run(_entrypoint(tmp_path))

    assert done.returncode == 1
    assert "no bootable Demiurgos version" in _log(tmp_path)


def test_entrypoint_falls_back_to_a_dev_checkout(tmp_path) -> None:
    """Run from a repo checkout: <root>/scripts + <root>/.venv is bootable."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    launcher = tmp_path / "scripts" / "start-demiurgos.sh"
    launcher.write_text("#!/bin/sh\necho dev\n", encoding="utf-8")
    launcher.chmod(0o755)
    python = tmp_path / ".venv" / "bin" / "python"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)

    done = _run(_entrypoint(tmp_path))

    assert done.returncode == 0
    assert done.stdout.strip() == "dev"
    assert "running the dev checkout" in _log(tmp_path)
