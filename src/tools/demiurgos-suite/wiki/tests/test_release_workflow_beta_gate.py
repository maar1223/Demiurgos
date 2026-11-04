# -*- coding: utf-8 -*-
"""Slice 0 (in-app-updater) — the Beta gate contract for the release pipeline.

The pushed tag is the single authority for the stable/beta split: a tag whose
version core carries a ``-`` prerelease suffix (``v0.x.y-beta.N``) is a
prerelease that publishes a GitHub prerelease and advances ONLY the
``latest-beta`` pointer; a plain ``v0.x.y`` tag is stable, publishes a normal
release, and advances ONLY ``latest``. The classification is recomputed inline
per job (no cross-job outputs), and the anonymous post-publish smoke asserts
the gate so a mis-move fails the workflow.

These are text/YAML scans of the release workflow — a CODE artifact of the
checkout, located from this file, matching the launcher-contract tests: no
network, no GitHub, no Actions runtime. The real end-to-end proof of this slice
is the post-publish smoke job on a live tag against the public channel repo;
that cannot run locally and is not claimed here.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job_runs(workflow: dict, job: str) -> str:
    """Every ``run:`` script of a job, newline-joined in step order."""
    return "\n".join(s.get("run", "") for s in workflow["jobs"][job]["steps"])


def _all_runs(workflow: dict) -> str:
    return "\n".join(
        s.get("run", "")
        for job in workflow["jobs"].values()
        for s in job["steps"]
    )


def _join_continuations(text: str) -> str:
    """Fold backslash line-continuations so a multi-line shell call is one line."""
    return re.sub(r"\\\n[ \t]*", " ", text)


def test_workflow_parses_as_yaml():
    workflow = _load()
    assert "publish" in workflow["jobs"]
    assert "smoke" in workflow["jobs"]
    assert "pointer" in workflow["jobs"]


def test_classifier_present_in_publish_and_smoke():
    """(a) The inline prerelease classifier is recomputed per job."""
    workflow = _load()
    for job in ("publish", "smoke", "pointer"):
        text = _job_runs(workflow, job)
        assert 'core="${tag#v}"' in text, f"{job}: missing classifier core"
        assert "grep -q '-'" in text, f"{job}: missing prerelease test"
        assert "is_prerelease=1" in text, f"{job}: missing prerelease branch"
        assert "is_prerelease=0" in text, f"{job}: missing stable branch"


def test_prerelease_flag_is_conditional_and_passed():
    """(b) ``gh release create`` gets ``--prerelease`` only for prereleases."""
    text = _job_runs(_load(), "publish")
    assert "prerelease_flag=" in text
    assert '[ "$is_prerelease" = "1" ] && prerelease_flag="--prerelease"' in text
    assert "$prerelease_flag" in text, "the flag is not passed to gh release create"


def test_pointer_split_stable_latest_beta_latest_beta():
    """(c) The pointer defaults to ``latest`` and switches to ``latest-beta``."""
    text = _job_runs(_load(), "pointer")
    assert "[ \"$is_prerelease\" = \"1\" ] && pointer=\"latest-beta\"" in text, (
        "the pointer does not switch to latest-beta for prereleases"
    )
    assert re.search(r'pointer="latest";\s*\[ "\$is_prerelease" = "1" \]', text), (
        "the pointer does not default to latest"
    )
    # the moved pointer is the computed variable, written on the channel branch
    assert '> "$pointer"' in text
    assert "git push origin HEAD:main" in text


def test_every_gh_release_call_carries_explicit_repo():
    """(d) Threat coverage: every publish/upload selects the repo explicitly."""
    joined = _join_continuations(_all_runs(_load()))
    calls = [ln for ln in joined.splitlines() if re.search(r"\bgh release (create|upload)\b", ln)]
    assert calls, "no gh release create/upload call found"
    for line in calls:
        assert "--repo" in line, f"gh release call without an explicit --repo: {line!r}"


def test_smoke_asserts_pointer_gating():
    """(e) The pointer job asserts the gating and fails on a mismatch."""
    text = _job_runs(_load(), "pointer")
    # the created release's own prerelease flag is checked against the tag
    assert "--json isPrerelease" in text
    # the authoritative pointers are the files on the public raw branch
    assert "raw.githubusercontent.com/${public_repo}/main" in text
    assert "${base}/latest?run=" in text
    assert 'wait_pointer latest-beta "$version"' in text
    assert 'wait_pointer latest "$version"' in text
    # any mismatch exits non-zero
    assert "exit 1" in text


def test_a_prerelease_never_writes_the_literal_latest_pointer():
    """A prerelease must not mutate ``latest``: the write uses the variable."""
    text = _job_runs(_load(), "pointer")
    # the only pointer write target is the computed variable, never the literal
    assert '> latest' not in text
    assert not re.search(r"gh release upload[^\n]*\blatest\b(?!-beta)", _join_continuations(text))


def test_channel_tree_is_the_documented_flat_branch():
    """S2/S5: the publish job assembles the flat raw-branch channel tree."""
    text = _job_runs(_load(), "publish")
    for needle in (
        "channel/scripts/lib",
        "channel/uv",
        "uv-shas.env",
        "UV_SHA_",
        "channel/version.json",
        "find . -path ./.git -prune -o -type f",
        "! -name SHA256SUMS ! -name SHA256SUMS.minisig",
        "git push origin HEAD:main",
    ):
        assert needle in text, f"publish does not assemble {needle!r}"
    # the manifest is regenerated over the whole tree, never only this run's
    assert "cat SHA256SUMS.*" not in text


def test_smoke_installs_from_the_real_raw_channel():
    """S6: no fabricated file:// fixture and no uv-SHA override."""
    text = _job_runs(_load(), "smoke")
    assert 'base="https://raw.githubusercontent.com/${public_repo}/main"' in text
    assert 'DEMIURGOS_URL_BASE="$base"' in text
    assert 'DEMIURGOS_URL_BASE="file://' not in text
    assert "export DEMIURGOS_UV_SHA256" not in text
    assert "bash install.sh" in text
    assert "/health" in text
