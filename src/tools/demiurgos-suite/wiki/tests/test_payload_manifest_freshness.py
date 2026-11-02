# -*- coding: utf-8 -*-
"""The payload manifest must stay fresh (AUD-01).

``payload_manifest.json`` is the release allow-list: the packaging ships exactly
the files it names. A runtime import that never reaches the manifest produces an
artifact that installs and then cannot boot, and the failure only surfaces at the
release smoke (or, worse, for the author). AUD-01 was exactly that: four
``conflict_*.py`` modules imported at ``api_server`` top level were absent.

``scripts/derive_payload_manifest.py --check`` is the CI freshness gate: it
derives the manifest in memory and compares it field by field against the
committed file, ignoring ``source_commit`` — a commit cannot contain its own sha,
so that provenance field can never match after the manifest is committed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[4]
_MANIFEST = _REPO_ROOT / "payload_manifest.json"
_DERIVE = _REPO_ROOT / "scripts" / "derive_payload_manifest.py"


def _run_check(manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_DERIVE), "--check", "--output", str(manifest)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _load(manifest: Path) -> dict:
    return json.loads(manifest.read_text(encoding="utf-8"))


def _write(manifest: Path, data: dict) -> None:
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class TestPayloadManifestFreshness:
    def test_the_committed_manifest_is_fresh(self) -> None:
        result = _run_check(_MANIFEST)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "is fresh" in result.stdout

    def test_a_missing_payload_entry_fails_the_gate(self, tmp_path: Path) -> None:
        stale = tmp_path / "payload_manifest.json"
        data = _load(_MANIFEST)
        data["payload"] = [
            path
            for path in data["payload"]
            if not path.endswith("wiki/conflict_decisions.py")
        ]
        _write(stale, data)

        result = _run_check(stale)

        assert result.returncode == 1
        assert "stale" in result.stderr
        assert "conflict_decisions.py" in result.stderr

    def test_source_commit_alone_does_not_fail_the_gate(self, tmp_path: Path) -> None:
        rotated = tmp_path / "payload_manifest.json"
        data = _load(_MANIFEST)
        data["source_commit"] = "0000000"
        _write(rotated, data)

        result = _run_check(rotated)

        assert result.returncode == 0, result.stdout + result.stderr

    def test_an_unreadable_manifest_fails_the_gate(self, tmp_path: Path) -> None:
        result = _run_check(tmp_path / "missing.json")

        assert result.returncode == 1
        assert "cannot read" in result.stderr
