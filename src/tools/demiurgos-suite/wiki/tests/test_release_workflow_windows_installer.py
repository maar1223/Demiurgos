# -*- coding: utf-8 -*-
"""Windows installer end-to-end job — seeds + graph wiring (AUD-17).

The release workflow's ``windows-installer-seeds-and-graph`` job runs the REAL
Windows installer core (``scripts/install-demiurgos.ps1``) against a hermetic
``file://`` channel built from the packaged Windows payload. It proves:

- a fresh install copies the foundational methodology seeds into the data root;
- the assistant profile gets the corrected ``demiurgos-graph`` entry and loses
  the legacy ``engram`` server;
- a same-version re-run restores a deleted seed tree.

These are text/YAML scans of a CODE artifact of the checkout: no network, no
GitHub, no Actions runtime. The real end-to-end proof is the job itself on a
master dry run or a tag; it cannot run locally and is not claimed here.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
JOB = "windows-installer-seeds-and-graph"


def _job() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert JOB in data["jobs"], f"missing workflow job: {JOB}"
    return data["jobs"][JOB]


def _runs(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_job_runs_after_packaging_on_windows():
    job = _job()
    assert job["needs"] == "package"
    assert job["runs-on"] == "windows-latest"
    assert job["timeout-minutes"] <= 30


def test_job_builds_a_hermetic_channel_and_a_test_signing_key():
    text = _runs(_job())
    assert "file://" in text
    assert "uv-shas.env" in text
    assert "UV_SHA_X86_64_WINDOWS_MSVC" in text
    assert "minisign.exe" in text
    assert "-G -W" in text
    assert "MINISIGN_PUBKEY" in text
    assert "SHA256SUMS" in text
    assert "-Sm" in text


def test_job_runs_the_real_installer_and_validates_seeds_and_graph():
    text = _runs(_job())
    # The real installer core runs twice: fresh install + same-version repair.
    assert text.count("-File $installer") == 2
    assert "DEMIURGOS_HERMES_SKIP" in text
    assert "data\\methodology\\seeds" in text
    assert "expected 19 seed files" in text
    assert "expected 19 restored seed files" in text
    assert "demiurgos-graph" in text
    assert "engram" in text
    assert "mcp_launcher.py" in text


def test_job_never_publishes():
    text = _runs(_job())
    assert "gh release" not in text
    assert "git push" not in text
