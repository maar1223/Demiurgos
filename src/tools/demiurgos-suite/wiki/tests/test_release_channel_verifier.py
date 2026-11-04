# -*- coding: utf-8 -*-
"""Regression probes for release-channel-installability (S2, S8).

Committed from the independent verifier's probes: every package cell published
by the release matrix must be reachable by the installer's own cell derivation,
and the pointer contract must keep a default install resolvable.

These are text/shell probes of checkout artifacts — no network, no GitHub, no
Actions runtime, and no live release is claimed.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[4]
INSTALLER = _REPO_ROOT / "scripts" / "install-demiurgos.sh"
WINDOWS_CORE = _REPO_ROOT / "scripts" / "install-demiurgos.ps1"
WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "release.yml"

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="sources the POSIX core; Windows cells are text-checked"
)


def _function_source(name: str) -> str:
    """Extract one shell function from the core, for a portable bash probe.

    Python extraction (not a sed range) keeps the probe identical on GNU and
    BSD userlands: a BSD ``sed`` range produced an empty script on the macOS CI
    runner, turning the probe into an unknown command (exit 127).
    """
    text = INSTALLER.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{.*?^\}}", text, re.MULTILINE | re.DOTALL
    )
    assert match, f"{name}() not found in {INSTALLER.name}"
    return match.group(0)


def _payload_cell(os_name: str, arch: str) -> str:
    """Run the core's own ``payload_cell`` with a simulated host."""
    script = "\n".join(
        [
            _function_source("uv_arch"),
            _function_source("payload_cell"),
            f'OS="{os_name}"; ARCH="{arch}"; payload_cell',
        ]
    )
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _matrix_cells() -> set[str]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return {
        item["cell"]
        for item in data["jobs"]["package"]["strategy"]["matrix"]["include"]
    }


def _job_runs(job: str) -> str:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return "\n".join(step.get("run", "") for step in data["jobs"][job]["steps"])


def test_every_release_matrix_cell_is_reachable_by_the_installer():
    """S8: the core derives exactly the cells the release matrix publishes."""
    cells = _matrix_cells()
    assert cells == {
        "linux-x86_64", "linux-aarch64", "macos-arm64", "windows-amd64",
    }
    assert _payload_cell("Linux", "x86_64") == "linux-x86_64"
    assert _payload_cell("Linux", "aarch64") == "linux-aarch64"
    # The uv triple says aarch64, the channel publishes macos-arm64.
    assert _payload_cell("Darwin", "arm64") == "macos-arm64"


def test_windows_core_selects_the_windows_amd64_cell():
    """S8: the Windows core requests the published windows-amd64 artifact."""
    text = WINDOWS_CORE.read_text(encoding="utf-8")
    assert "demiurgos-app-$version-windows-amd64.zip" in text


def test_pointer_job_writes_only_the_computed_pointer():
    """S7: only the classified pointer is written; the other stays intact."""
    text = _job_runs("pointer")
    assert '> "$pointer"' in text
    assert "> latest" not in text
    assert "> latest-beta" not in text


def test_default_install_resolves_a_beta_first_channel():
    """S2: a channel with no stable pointer yet still installs by default."""
    assert "latest-beta" in INSTALLER.read_text(encoding="utf-8")
    assert "latest-beta" in WINDOWS_CORE.read_text(encoding="utf-8")
