# -*- coding: utf-8 -*-
"""The local install vehicle stays a plan-first, fail-closed dev tool.

`scripts/install-local.sh` builds this checkout and installs it as a real
app/<version>, bypassing the release channel. These tests pin the parts that
must never drift: the SemVer build-metadata label (so the updater never nags),
the dry run writing nothing, and the fail-fast guards.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]
SCRIPT = REPO_ROOT / "scripts" / "install-local.sh"

VERSION_RE = re.compile(r"(\d+\.\d+\.\d+\+local\.[0-9a-f]+(?:\.dirty)?)")


def _fake_install_root(tmp_path: Path) -> Path:
    install_root = tmp_path / "install"
    (install_root / "app").mkdir(parents=True)
    uv = install_root / "bin" / "uv"
    uv.parent.mkdir()
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    (tmp_path / "home").mkdir()
    return install_root


def _run(install_root: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DEMIURGOS_HOME": str(install_root),
        "HOME": str(tmp_path / "home"),
        # The checkout may be owned by another account in CI/containers; the
        # child git only needs this repository declared safe, without mutating
        # the real user's global config.
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": str(REPO_ROOT),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
    )


def test_dry_run_prints_the_plan_and_writes_nothing(tmp_path: Path) -> None:
    install_root = _fake_install_root(tmp_path)

    result = _run(install_root, tmp_path, "--dry-run")

    assert result.returncode == 0, result.stderr
    match = VERSION_RE.search(result.stdout)
    assert match, result.stdout
    version = match.group(1)
    assert str(install_root) in result.stdout
    assert str(install_root / "app" / version) in result.stdout
    # Nothing was written: no staging dir and no app version appeared.
    assert not (install_root / ".staging").exists()
    assert list((install_root / "app").iterdir()) == []


def test_unknown_argument_fails_with_usage(tmp_path: Path) -> None:
    install_root = _fake_install_root(tmp_path)

    result = _run(install_root, tmp_path, "--nope")

    assert result.returncode == 2
    assert "unknown argument" in result.stderr


def test_missing_install_layout_fails_closed(tmp_path: Path) -> None:
    install_root = tmp_path / "install"
    install_root.mkdir()
    (tmp_path / "home").mkdir()

    result = _run(install_root, tmp_path, "--dry-run")

    assert result.returncode == 1
    assert "install Demiurgos normally once" in result.stderr


def test_version_override_must_stay_semver_build_metadata(tmp_path: Path) -> None:
    install_root = _fake_install_root(tmp_path)

    result = _run(install_root, tmp_path, "--dry-run", "--version", "9.9.9")

    assert result.returncode == 1
    assert "not <X.Y.Z>+local.<sha>" in result.stderr
