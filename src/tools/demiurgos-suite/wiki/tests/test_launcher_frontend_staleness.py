# -*- coding: utf-8 -*-
"""Stale frontend bundle guard (plan B, ``ui/build-stamp-and-stale-dist-guard``).

The API serves the prebuilt, gitignored ``frontend/dist``. ``vitest`` and
``tsc`` can be green while the served bundle lags behind ``frontend/src``, so
every "look at the UI" check may silently target an older build. The launcher
must warn before booting when the source is newer than the bundle, and must be
able to rebuild on request (``--build-if-stale``).

These are hermetic probes: they source the launcher (which never runs ``main``
when sourced) and call its predicate against temporary trees.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

LAUNCHER = REPO_ROOT / "scripts" / "start-demiurgos.sh"
BASH = shutil.which("bash") or "/bin/bash"

_PROBE = '. "$1" || exit 9; shift; '


def _source(script: str, *args: str) -> subprocess.CompletedProcess:
    """Source the launcher, then run ``script`` with ``args`` as ``$1..$n``."""
    return subprocess.run(
        [BASH, "-c", _PROBE + script, "_", str(LAUNCHER), *args],
        capture_output=True,
        text=True,
    )


def _tree(root: Path, *, dist_mtime: float, src_mtime: float) -> Path:
    src = root / "frontend" / "src"
    dist = root / "frontend" / "dist"
    src.mkdir(parents=True)
    dist.mkdir(parents=True)
    (src / "App.tsx").write_text("export const App = () => null;\n", encoding="utf-8")
    (dist / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    os.utime(src / "App.tsx", (src_mtime, src_mtime))
    os.utime(dist / "index.html", (dist_mtime, dist_mtime))
    return root


_STALE_OR_FRESH = 'if frontend_dist_is_stale "$1"; then echo STALE; else echo FRESH; fi'


@pytest.mark.skipif(not LAUNCHER.is_file(), reason="launcher missing")
class TestFrontendDistStaleness:
    def test_source_newer_than_bundle_is_stale(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, dist_mtime=1_000.0, src_mtime=2_000.0)
        result = _source(_STALE_OR_FRESH, str(root))
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "STALE"

    def test_bundle_newer_than_source_is_fresh(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, dist_mtime=3_000.0, src_mtime=2_000.0)
        result = _source(_STALE_OR_FRESH, str(root))
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "FRESH"

    def test_missing_bundle_is_not_reported_as_stale(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, dist_mtime=1_000.0, src_mtime=2_000.0)
        (root / "frontend" / "dist" / "index.html").unlink()
        result = _source(_STALE_OR_FRESH, str(root))
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "FRESH"

    def test_warning_names_the_rebuild_command(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, dist_mtime=1_000.0, src_mtime=2_000.0)
        result = _source('APP_ROOT="$1"; warn_if_frontend_dist_stale', str(root))
        assert result.returncode == 0, result.stderr
        assert "npm run build" in result.stderr
        assert "--build-if-stale" in result.stderr

    def test_fresh_bundle_produces_no_warning(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, dist_mtime=3_000.0, src_mtime=2_000.0)
        result = _source('APP_ROOT="$1"; warn_if_frontend_dist_stale', str(root))
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""


@pytest.mark.skipif(not LAUNCHER.is_file(), reason="launcher missing")
def test_usage_documents_the_flag() -> None:
    usage = _source("usage")
    assert "--build-if-stale" in usage.stdout
