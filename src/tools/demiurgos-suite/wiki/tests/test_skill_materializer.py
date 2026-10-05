# -*- coding: utf-8 -*-
"""skill-materializer-reconciliation (WU 1.2a) — desired set + atomic writes.

Part 1 of the materializer: compute the desired set from the library and write
it atomically into the unregistered staging tree. Orphan GC, the revision
marker, and the fail-safe abort are WU 1.2b and are deliberately NOT covered
here. Covered scenarios (spec ``skill-materializer-reconciliation``):

- Desired set is transversal plus active world (all three scenarios).
- Desired tree layout maps each skill to a deterministic, distinct path.
- Staging root is distinct and unregistered (not in ``external_dirs``).
- Live skills folder stays empty (only its tracked ``.gitkeep``).
- Writes are atomic per file (complete replace; failed replace preserves bytes).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from methodology_library import DEFAULT_FLOW_TYPE, Activation, PublishedVersion
from methodology_trust import FOUNDATIONAL
import skill_materializer as materializer_module
from skill_materializer import (
    REVISION_MARKER_NAME,
    SENTINEL_NAMES,
    STAGING_DIR_REL,
    TRANSVERSAL_SUBDIR,
    WORLD_SUBDIR,
    SkillMaterializer,
    _atomic_write,
    resolve_staging_root,
    revision_marker_path,
)

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo
LIVE_SKILLS_DIR = REPO_ROOT / "data" / "methodology" / "skills"


class _StubLibrary:
    """Minimal in-memory library seam for the materializer."""

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


def _published(
    skill_id="alpha",
    version="1.0.0",
    *,
    foundational=True,
    description="A skill trigger",
    source="# Body\n",
):
    return PublishedVersion(
        skill_id=skill_id,
        version=version,
        name=skill_id,
        description=description,
        phases=("discovery",),
        language=None,
        source=source,
        digest="0" * 64,
        published_at="2026-01-01T00:00:00+00:00",
        trust_attributes=(FOUNDATIONAL,) if foundational else (),
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


# -- Desired set --------------------------------------------------------------


def test_desired_set_transversal_only(tmp_path):
    """Spec 'Transversals are always materialized': no world → transversals."""
    library = _StubLibrary(
        published=[_published("alpha"), _published("worldskill", foundational=False)],
        activations={"W": _activation("W", "worldskill", "1.0.0")},
    )
    skills = SkillMaterializer(library, project_root=tmp_path).desired_set(None)
    assert [s.skill_id for s in skills] == ["alpha"]
    assert skills[0].scope == "transversal"
    assert skills[0].relative_dir == f"{TRANSVERSAL_SUBDIR}/demiurgos-alpha@1.0.0"


def test_desired_set_transversal_plus_world(tmp_path):
    """Spec 'Active world adds its activated and companion skills'."""
    library = _StubLibrary(
        published=[
            _published("alpha"),
            _published("worldskill", foundational=False),
            _published("companion", foundational=False),
        ],
        activations={"Aldoria": _activation("Aldoria", "worldskill", "1.0.0")},
        companions={"Aldoria": [_activation("Aldoria", "companion", "1.0.0")]},
    )
    skills = SkillMaterializer(library, project_root=tmp_path).desired_set("Aldoria")
    assert [s.relative_dir for s in skills] == [
        f"{TRANSVERSAL_SUBDIR}/demiurgos-alpha@1.0.0",
        f"{WORLD_SUBDIR}/demiurgos-Aldoria-companion@1.0.0",
        f"{WORLD_SUBDIR}/demiurgos-Aldoria-worldskill@1.0.0",
    ]
    assert {s.scope for s in skills} == {"transversal", "Aldoria"}


def test_desired_set_switching_world_changes_only_world_part(tmp_path):
    """Spec 'Switching the active world changes only the world-specific part'."""
    library = _StubLibrary(
        published=[
            _published("alpha"),
            _published("w1skill", foundational=False),
            _published("w2skill", foundational=False),
        ],
        activations={
            "W1": _activation("W1", "w1skill", "1.0.0"),
            "W2": _activation("W2", "w2skill", "1.0.0"),
        },
    )
    materializer = SkillMaterializer(library, project_root=tmp_path)
    first = materializer.desired_set("W1")
    second = materializer.desired_set("W2")
    transversals = [s for s in first if s.scope == "transversal"]
    assert transversals == [s for s in second if s.scope == "transversal"]
    assert [s.skill_id for s in first if s.scope == "W1"] == ["w1skill"]
    assert [s.skill_id for s in second if s.scope == "W2"] == ["w2skill"]
    assert "w1skill" not in [s.skill_id for s in second]
    assert "w2skill" not in [s.skill_id for s in first]


def test_desired_set_paths_deterministic_and_distinct(tmp_path):
    """Spec 'Each desired skill maps to a deterministic path'."""
    library = _StubLibrary(
        published=[_published("alpha"), _published("worldskill", foundational=False)],
        activations={"W": _activation("W", "worldskill", "1.0.0")},
    )
    materializer = SkillMaterializer(library, project_root=tmp_path)
    first = materializer.desired_set("W")
    second = materializer.desired_set("W")
    assert first == second
    dirs = [s.relative_dir for s in first]
    assert len(dirs) == len(set(dirs))


def test_desired_set_deduplicates_activated_companion(tmp_path):
    """A skill reached twice (activated and companion) appears once."""
    same = _activation("W", "worldskill", "1.0.0")
    library = _StubLibrary(
        published=[_published("worldskill", foundational=False)],
        activations={"W": same},
        companions={"W": [same]},
    )
    skills = SkillMaterializer(library, project_root=tmp_path).desired_set("W")
    assert [s.relative_dir for s in skills] == [
        f"{WORLD_SUBDIR}/demiurgos-W-worldskill@1.0.0"
    ]


# -- Staging root / live folder / registration --------------------------------


def test_live_folder_holds_only_gitkeep():
    """Spec 'No materialized skill leaks into the live folder'."""
    assert sorted(p.name for p in LIVE_SKILLS_DIR.iterdir()) == [".gitkeep"]
    assert list(LIVE_SKILLS_DIR.rglob("SKILL.md")) == []


def test_live_folder_staging_not_in_external_dirs(tmp_path):
    """Spec 'Staging root is not in external_dirs': it is distinct from the
    registered live folder and never registered."""
    from hermes_profile_config import merge_skills_external_dirs, resolve_skills_dir

    staging = resolve_staging_root(tmp_path)
    live = resolve_skills_dir(tmp_path)
    assert staging != live
    assert live not in staging.parents and staging not in live.parents
    assert staging == tmp_path / STAGING_DIR_REL
    assert revision_marker_path(tmp_path) == staging / REVISION_MARKER_NAME
    assert SENTINEL_NAMES == (".gitkeep", REVISION_MARKER_NAME)

    config_path = tmp_path / "config.yaml"
    merge_skills_external_dirs(config_path, live)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    external_dirs = data["skills"]["external_dirs"]
    assert str(live) in external_dirs
    assert str(staging) not in external_dirs


# -- Atomic writes ------------------------------------------------------------


def test_atomic_replace_completes_without_leftover_temp(tmp_path):
    """Spec 'Target is replaced completely, never partially'."""
    target = tmp_path / "world" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old bytes")
    _atomic_write(target, b"new bytes")
    assert target.read_bytes() == b"new bytes"
    assert [p.name for p in target.parent.iterdir()] == ["SKILL.md"]


def test_atomic_failed_replace_preserves_previous_bytes(tmp_path, monkeypatch):
    """Spec 'A failed replacement preserves the previous bytes'."""
    target = tmp_path / "SKILL.md"
    target.write_bytes(b"previous complete bytes")

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(materializer_module.os, "replace", boom)
    with pytest.raises(OSError):
        _atomic_write(target, b"new bytes")
    assert target.read_bytes() == b"previous complete bytes"
    assert [p.name for p in tmp_path.iterdir()] == ["SKILL.md"]


def test_atomic_materialize_skips_unchanged_files(tmp_path):
    """Only changed files are written; a no-op rerun writes nothing."""
    library = _StubLibrary(published=[_published("alpha")])
    materializer = SkillMaterializer(library, project_root=tmp_path)
    first = materializer.materialize(None)
    second = materializer.materialize(None)
    assert first.written == 1
    assert second.written == 0
    assert second.revision is None
    assert second.aborted is False
    assert second.deleted == 0
    assert second.ok is True


def test_live_folder_unchanged_after_materialize(tmp_path):
    """Spec 'Writes target staging, never the registered folder'."""
    library = _StubLibrary(published=[_published("alpha")])
    report = SkillMaterializer(library, project_root=tmp_path).materialize(None)
    assert report.ok is True
    staging = resolve_staging_root(tmp_path)
    written = list(staging.rglob("SKILL.md"))
    assert written
    assert all(path.is_relative_to(staging) for path in written)
    assert not (tmp_path / "data" / "methodology" / "skills").exists()
    assert sorted(p.name for p in LIVE_SKILLS_DIR.iterdir()) == [".gitkeep"]
