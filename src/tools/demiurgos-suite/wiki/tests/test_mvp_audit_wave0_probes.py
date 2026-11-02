# -*- coding: utf-8 -*-
"""Independent regression probes for MVP audit wave 0 (S1-S6).

These probes came out of the independent verification pass on the wave-0
branch. They are deliberately redundant with the focused tests: they assert the
cross-cutting invariants (the manifest is cross-platform, the gate is red on
every stale shape, the CI topology, the single launcher location) rather than
re-testing one function. Every probe fails on the pre-fix baseline.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[4]
_DERIVE = _REPO_ROOT / "scripts" / "derive_payload_manifest.py"
_MANIFEST = _REPO_ROOT / "payload_manifest.json"
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_RELEASE = _REPO_ROOT / ".github" / "workflows" / "release.yml"

_CONFLICT_MODULES = {
    "src/tools/demiurgos-suite/wiki/conflict_decisions.py",
    "src/tools/demiurgos-suite/wiki/conflict_detector.py",
    "src/tools/demiurgos-suite/wiki/conflict_proposing.py",
    "src/tools/demiurgos-suite/wiki/conflict_sweep.py",
}


def _check(manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_DERIVE), "--check", "--output", str(manifest)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _stale_copy(tmp_path: Path, mutate) -> Path:
    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    mutate(data)
    target = tmp_path / "payload_manifest.json"
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return target


def test_s1_s2_conflict_modules_ship_and_paths_are_posix() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))["payload"]
    assert _CONFLICT_MODULES <= set(payload)
    assert not [path for path in payload if "\\" in path], "manifest must be cross-platform"


def test_s1_s2_gate_is_green_on_the_committed_manifest() -> None:
    result = _check(_MANIFEST)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "is fresh" in result.stdout


def test_s1_s2_gate_rejects_a_dropped_module_and_never_rewrites_the_manifest(
    tmp_path: Path,
) -> None:
    before = _MANIFEST.read_bytes()
    dropped = _stale_copy(
        tmp_path,
        lambda data: data.__setitem__(
            "payload", [p for p in data["payload"] if p not in _CONFLICT_MODULES]
        ),
    )
    result = _check(dropped)
    assert result.returncode == 1
    assert "stale" in result.stderr and "conflict_" in result.stderr
    assert _MANIFEST.read_bytes() == before


def test_s1_s2_gate_rejects_an_extra_non_derived_path(tmp_path: Path) -> None:
    extra = _stale_copy(
        tmp_path,
        lambda data: data["payload"].append(
            "src/tools/demiurgos-suite/wiki/ghost_module.py"
        ),
    )
    result = _check(extra)
    assert result.returncode == 1 and "ghost_module.py" in result.stderr


def test_s1_s2_gate_ignores_only_the_source_commit(tmp_path: Path) -> None:
    rotated = _stale_copy(
        tmp_path, lambda data: data.__setitem__("source_commit", "0" * 7)
    )
    assert _check(rotated).returncode == 0


def test_s3_backend_jobs_never_depend_on_the_frontend_test_matrix() -> None:
    jobs = yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]
    for name in ("backend", "launcher", "static-serving", "ps51"):
        assert jobs[name]["needs"] == "frontend-build", name
    build = " ".join(str(step) for step in jobs["frontend-build"]["steps"]).lower()
    assert "npm test" not in build and "typecheck" not in build
    gate = " ".join(str(step) for step in jobs["payload-manifest"]["steps"])
    assert "derive_payload_manifest.py --check" in gate
    backend = " ".join(str(step) for step in jobs["backend"]["steps"])
    assert "src/tools/demiurgos-suite/wiki/tests/" in backend
    assert "test_payload_boot.py" not in backend  # never excluded from the suite


def test_s4_s5_release_packages_the_windows_launcher_under_scripts_only() -> None:
    text = _RELEASE.read_text(encoding="utf-8")
    assert 'cp start-demiurgos.ps1 "$stage/scripts/start-demiurgos.ps1"' in text
    assert "Join-Path $stage 'scripts/start-demiurgos.ps1'" in text
    root_entries = [
        line.strip()
        for line in text.splitlines()
        if re.fullmatch(r"'?start-demiurgos\.ps1'?,?", line.strip())
    ]
    assert root_entries == [], f"root launcher still allow-listed/shipped: {root_entries}"


def test_s4_s5_installer_and_shortcut_agree_on_the_contract_path() -> None:
    installer = (_REPO_ROOT / "scripts" / "install-demiurgos.ps1").read_text(
        encoding="utf-8"
    )
    assert r"current\scripts\start-demiurgos.ps1 start" in installer
    helper = (_REPO_ROOT / "scripts" / "lib" / "desktop-shortcut.ps1").read_bytes()
    text = helper.decode("ascii")  # shipped .ps1 files are ASCII-only (PS 5.1)
    assert text.index("scripts\\start-demiurgos.ps1") < text.index(
        '"start-demiurgos.ps1")'
    )
