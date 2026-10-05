# -*- coding: utf-8 -*-
"""Cross-cutting invariant — Etapa 1 changes nothing assistant-visible.

Etapa 1 (renderer + materializer + sessions + T-FU-02 hook) is additive and
inert with respect to what the model sees. Covered scenarios (spec cross-cutting
'No visible product behavior change in Etapa 1'):

- The legacy server-side projection of an active world's methodology is
  byte-identical before and after Etapa 1 materialization + session plumbing
  (the library record is never mutated; the projection is a pure function).
- The ``skills`` toolset stays absent from ``platform_toolsets.api_server`` and
  the staging root is never registered in ``skills.external_dirs``.
- Materialization writes nothing under the live ``data/methodology/skills/``
  folder, which keeps holding only its tracked sentinel.
- The legacy channel modules (``skill_router.py`` / ``contract_projection.py``)
  are unchanged versus the merge base with ``master`` (skipped when git is
  unavailable).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from contract_projection import project_contract_markdown
from hermes_profile_config import merge_skills_external_dirs, resolve_skills_dir
from methodology_library import DEFAULT_FLOW_TYPE, Activation, PublishedVersion
from methodology_trust import FOUNDATIONAL
from skill_materializer import SkillMaterializer, resolve_staging_root
from skill_session_epochs import SessionEpochRegistry, resolve_session_store_path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

LIVE_SKILLS_DIR = REPO_ROOT / "data" / "methodology" / "skills"
INSTALL_SH = REPO_ROOT / "install.sh"

_ROUTER = "src/tools/demiurgos-suite/wiki/skill_router.py"
_PROJECTION = "src/tools/demiurgos-suite/wiki/contract_projection.py"

GIT_AVAILABLE = shutil.which("git") is not None


class _StubLibrary:
    """Minimal in-memory library seam (published + activations + companions)."""

    def __init__(self, *, published=(), activations=None, companions=None):
        self._published = {(p.skill_id, p.version): p for p in published}
        self._activations = dict(activations or {})
        self._companions = dict(companions or {})

    def list_published(self):
        return list(self._published.values())

    def get_published(self, skill_id, version):
        return self._published.get((skill_id, version))

    def active_for(self, world, flow_type=DEFAULT_FLOW_TYPE):
        return self._activations.get(world)

    def list_companions(self, world):
        return list(self._companions.get(world, ()))


def _published(skill_id, version="1.0.0", *, foundational, source="# Body\n"):
    return PublishedVersion(
        skill_id=skill_id,
        version=version,
        name=skill_id,
        description=f"{skill_id} trigger",
        phases=("discovery",),
        language=None,
        source=source,
        digest="0" * 64,
        published_at="2026-01-01T00:00:00+00:00",
        trust_attributes=(FOUNDATIONAL,) if foundational else (),
        adjuntos=(),
    )


def _activation(world, skill_id, version):
    return Activation(
        world=world,
        skill_id=skill_id,
        version=version,
        digest="0" * 64,
        activated_at="2026-01-01T00:00:00+00:00",
        flow_type=DEFAULT_FLOW_TYPE,
    )


def _library():
    transversal = _published("alpha", foundational=True)
    guided = _published("guia", foundational=False)
    return _StubLibrary(
        published=[transversal, guided],
        activations={"W": _activation("W", "guia", "1.0.0")},
    )


def _snapshot(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# -- Prompt + toolset byte-identical -----------------------------------------


def test_legacy_projection_byte_identical_after_materialization(tmp_path):
    """Scenario 'System prompt ... byte-identical to baseline': the legacy
    projection of the active world's method is unchanged by Etapa 1 render +
    materialization + session plumbing."""
    library = _library()
    guided = library.get_published("guia", "1.0.0")
    baseline = project_contract_markdown(guided).encode("utf-8")

    report = SkillMaterializer(library, project_root=tmp_path).materialize("W")
    assert report.ok is True
    assert report.revision

    SessionEpochRegistry(resolve_session_store_path(tmp_path)).observe(
        "W", report.revision
    )

    after = project_contract_markdown(guided).encode("utf-8")
    assert after == baseline


def test_skills_absent_and_staging_not_registered(tmp_path):
    """Scenario 'skills is still absent from platform_toolsets.api_server' and
    the staging root is not among ``skills.external_dirs``."""
    live = resolve_skills_dir(tmp_path)
    staging = resolve_staging_root(tmp_path)
    assert staging != live

    config = tmp_path / "config.yaml"
    config.write_text(
        "platform_toolsets:\n  api_server:\n    - file\n    - terminal\n",
        encoding="utf-8",
    )
    merge_skills_external_dirs(config, live)

    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert "skills" not in data["platform_toolsets"]["api_server"]
    assert data["platform_toolsets"]["api_server"] == ["file", "terminal"]
    assert str(live) in data["skills"]["external_dirs"]
    assert str(staging) not in data["skills"]["external_dirs"]


def test_materialization_writes_nothing_under_live_folder(tmp_path):
    """Scenario 'No materialized skill leaks into the live folder': a
    materialization pass touches no byte under the registered live folder, which
    keeps holding only its tracked sentinel."""
    before = _snapshot(LIVE_SKILLS_DIR)

    report = SkillMaterializer(_library(), project_root=tmp_path).materialize("W")
    assert report.ok is True

    after = _snapshot(LIVE_SKILLS_DIR)
    assert after == before
    assert [p.name for p in LIVE_SKILLS_DIR.iterdir()] == [".gitkeep"]
    assert list(LIVE_SKILLS_DIR.rglob("SKILL.md")) == []
    # the materializer writes only to its staging tree, never to a live folder
    assert not (tmp_path / "data" / "methodology" / "skills").exists()


def test_installer_never_enables_skills_toolset():
    """Sequencing guard: the installer-written product config never enables the
    ``skills`` toolset in ``platform_toolsets.api_server`` (Etapa 3 owns that)."""
    if not INSTALL_SH.is_file():
        pytest.skip("install.sh absent")
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "platform_toolsets" not in text


# -- Legacy channel modules unchanged ----------------------------------------


def test_legacy_channel_modules_unchanged_vs_merge_base():
    """Scenario 'Legacy methodology channel is untouched and still serving': the
    legacy channel modules are byte-unchanged versus the merge base with master."""
    if not GIT_AVAILABLE:
        pytest.skip("git unavailable")

    base = subprocess.run(
        ["git", "merge-base", "HEAD", "master"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if base.returncode != 0 or not base.stdout.strip():
        pytest.skip("merge-base with master unavailable")
    merge_base = base.stdout.strip()

    result = subprocess.run(
        ["git", "diff", "--quiet", merge_base, "--", _ROUTER, _PROJECTION],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"legacy channel modules changed vs merge-base {merge_base}: "
        f"{result.stdout}{result.stderr}"
    )
