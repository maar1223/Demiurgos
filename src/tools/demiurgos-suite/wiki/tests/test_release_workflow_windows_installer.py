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

import re
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
    # Upstream uv assets are versionless (version in the path); the channel copy
    # keeps the installer's versioned contract name. Pinning both sides stops
    # the 404 the reviewer found in the first draft.
    assert "uv-x86_64-pc-windows-msvc.zip" in text
    assert 'uv-x86_64-pc-windows-msvc-$uvVersion.zip' in text
    assert "minisign.exe" in text
    assert "-G -W" in text
    assert "MINISIGN_PUBKEY" in text
    assert "SHA256SUMS" in text
    assert "-Sm" in text


def test_uv_download_url_resolves_to_the_versionless_upstream_asset():
    text = _runs(_job())
    upstream = re.search(r"^\s*\$uvUpstream\s*=\s*'([^']+)'\s*$", text, re.M)
    local = re.search(r'^\s*\$uvLocal\s*=\s*"([^"]+)"\s*$', text, re.M)
    url = re.search(r'^\s*\$uvUrl\s*=\s*"([^"]+)"\s*$', text, re.M)
    assert upstream and local and url, "uv assignment block missing"
    upstream_name, _local_name, url_template = (
        upstream.group(1),
        local.group(1),
        url.group(1),
    )
    assert upstream_name == "uv-x86_64-pc-windows-msvc.zip", upstream_name
    # The URL interpolates the versionless upstream asset, never the local
    # versioned channel copy (that pairing 404s).
    assert "$uvUpstream" in url_template and "$uvLocal" not in url_template
    resolved = url_template.replace("$uvVersion", "0.5.24").replace(
        "$uvUpstream", upstream_name
    )
    assert resolved == (
        "https://github.com/astral-sh/uv/releases/download/0.5.24/"
        "uv-x86_64-pc-windows-msvc.zip"
    ), resolved


def test_minisign_binary_is_the_x86_64_build():
    text = _runs(_job())
    selection = text[text.index("$minisign = Get-ChildItem") :]
    selection = selection[: selection.index("if (-not $minisign)")]
    assert "x86_64" in selection, selection


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


def test_repair_run_deletes_the_seed_tree_before_reinstalling():
    text = _runs(_job())
    delete_at = text.index("Remove-Item -LiteralPath $seeds -Recurse -Force")
    assert delete_at < text.rindex("-File $installer")
    assert "DEMIURGOS_VERSION = $version" in text


def test_payload_manifest_ships_exactly_the_19_seed_files():
    import json

    manifest = json.loads(
        (REPO_ROOT / "payload_manifest.json").read_text(encoding="utf-8")
    )
    seeds = [
        path
        for path in manifest["payload"]
        if path.startswith("data/methodology/seeds/")
    ]
    assert len(seeds) == 19, len(seeds)


def test_job_never_publishes():
    job = _job()
    assert job.get("permissions") in (None, {"contents": "read"})
    text = _runs(job)
    assert "gh release" not in text
    assert "git push" not in text
    # Actions can publish without a run: no release/publish action may appear.
    uses = [str(step.get("uses", "")) for step in job["steps"]]
    assert not [
        action
        for action in uses
        if "release" in action.lower() or "publish" in action.lower()
    ], uses
