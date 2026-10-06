# -*- coding: utf-8 -*-
"""skill-materializer-reconciliation — desired set, writes, GC, revision, abort.

Part 1 covers computing the desired set from the library and writing it
atomically into the unregistered staging tree. Part 2 (WU 1.2b) covers orphan
GC, the deterministic revision + marker, and the fail-safe abort. Covered
scenarios (spec ``skill-materializer-reconciliation``):

- Desired set is transversal plus active world (all three scenarios).
- Desired tree layout maps each skill to a deterministic, distinct path.
- Staging root is distinct and unregistered (not in ``external_dirs``).
- Live skills folder stays empty (only its tracked ``.gitkeep``).
- Writes are atomic per file (complete replace; failed replace preserves bytes).
- Orphan GC removes every undesired path (file + folder, deactivated skill).
- Sentinel paths are never deleted (``.gitkeep`` + revision marker survive GC).
- Deterministic materialization revision (unchanged tree identical; add/remove/
  version bump/attachment byte change all differ).
- Fail-safe abort when the library is unreadable/malformed (no deletion, no
  marker advance, observable failure).
- GC containment (a ``..``/symlink candidate never escapes the staging root).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
import yaml

from methodology_compiler import AttachmentEntry
from methodology_library import DEFAULT_FLOW_TYPE, Activation, PublishedVersion
from methodology_trust import FOUNDATIONAL
import skill_materializer as materializer_module
from skill_materializer import (
    REVISION_MARKER_NAME,
    SENTINEL_NAMES,
    STAGING_DIR_REL,
    TRANSVERSAL_SUBDIR,
    WORLD_SUBDIR,
    PromoteReport,
    SkillMaterializer,
    SkillPromoter,
    _atomic_write,
    _gc_tree,
    _revision_digest,
    resolve_staging_root,
    revision_marker_path,
)
from hermes_profile_config import resolve_skills_dir

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo
LIVE_SKILLS_DIR = REPO_ROOT / "data" / "methodology" / "skills"


class _StubLibrary:
    """Minimal in-memory library seam for the materializer."""

    def __init__(self, *, published=(), activations=None, companions=None,
                 native_channels=None):
        self._published = {(p.skill_id, p.version): p for p in published}
        self._activations = dict(activations or {})
        self._companions = dict(companions or {})
        self._native_channels = dict(native_channels or {})

    def list_published(self):
        return list(self._published.values())

    def get_published(self, skill_id, version):
        return self._published.get((skill_id, version))

    def active_for(self, world, flow_type=DEFAULT_FLOW_TYPE):
        return self._activations.get(world)

    def list_companions(self, world):
        return list(self._companions.get(world, ()))

    def native_channel_enabled(self, world):
        return self._native_channels.get(str(world), False)


def _published(
    skill_id="alpha",
    version="1.0.0",
    *,
    foundational=True,
    description="A skill trigger",
    source="# Body\n",
    adjuntos=(),
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
        adjuntos=adjuntos,
    )


def _attachment(tmp_path, skill_id, content, *, path="exemplar.md", nivel="1º"):
    """Write a carrier file under ``seeds/<skill_id>`` and return its pin."""
    seed_dir = tmp_path / "data" / "methodology" / "seeds" / skill_id
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / path).write_bytes(content)
    return AttachmentEntry(
        path=path,
        sha256=hashlib.sha256(content).hexdigest(),
        bytes=len(content),
        nivel=nivel,
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
    assert second.revision == first.revision
    assert second.revision is not None
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


# -- Deterministic revision ---------------------------------------------------


def test_revision_identical_for_unchanged_tree(tmp_path):
    """Spec 'Unchanged desired tree yields an identical revision'."""
    library = _StubLibrary(published=[_published("alpha")])
    materializer = SkillMaterializer(library, project_root=tmp_path)
    first = materializer.materialize(None)
    second = materializer.materialize(None)
    assert first.revision is not None
    assert first.revision == second.revision
    # The digest depends only on content, not on the staging path.
    other = SkillMaterializer(library, project_root=tmp_path / "elsewhere")
    assert other.materialize(None).revision == first.revision


def test_revision_changes_on_add(tmp_path):
    """Spec 'Any desired change changes the revision': a skill is added."""
    only_alpha = SkillMaterializer(
        _StubLibrary(published=[_published("alpha")]), project_root=tmp_path
    ).materialize(None)
    with_beta = SkillMaterializer(
        _StubLibrary(published=[_published("alpha"), _published("beta")]),
        project_root=tmp_path,
    ).materialize(None)
    assert only_alpha.revision != with_beta.revision


def test_revision_changes_on_remove(tmp_path):
    """Spec 'Any desired change changes the revision': a skill is removed."""
    with_beta = SkillMaterializer(
        _StubLibrary(published=[_published("alpha"), _published("beta")]),
        project_root=tmp_path,
    ).materialize(None)
    without_beta = SkillMaterializer(
        _StubLibrary(published=[_published("alpha")]), project_root=tmp_path
    ).materialize(None)
    assert with_beta.revision != without_beta.revision


def test_revision_changes_on_version_bump(tmp_path):
    """Spec 'Any desired change changes the revision': version bumped."""
    v1 = SkillMaterializer(
        _StubLibrary(published=[_published("alpha", "1.0.0")]), project_root=tmp_path
    ).materialize(None)
    v2 = SkillMaterializer(
        _StubLibrary(published=[_published("alpha", "1.1.0")]), project_root=tmp_path
    ).materialize(None)
    assert v1.revision != v2.revision


def test_revision_changes_on_attachment_bytes(tmp_path):
    """Spec 'Any desired change changes the revision': attachment bytes change."""
    root_a = tmp_path / "a"
    pin_a = _attachment(root_a, "alpha", b"first exemplar\n")
    first = SkillMaterializer(
        _StubLibrary(published=[_published("alpha", adjuntos=(pin_a,))]),
        project_root=root_a,
    ).materialize(None)
    root_b = tmp_path / "b"
    pin_b = _attachment(root_b, "alpha", b"second exemplar\n")
    second = SkillMaterializer(
        _StubLibrary(published=[_published("alpha", adjuntos=(pin_b,))]),
        project_root=root_b,
    ).materialize(None)
    assert first.revision != second.revision


def test_revision_marker_content_equals_revision(tmp_path):
    """The marker holds exactly the revision + a trailing newline."""
    library = _StubLibrary(published=[_published("alpha")])
    report = SkillMaterializer(library, project_root=tmp_path).materialize(None)
    marker = revision_marker_path(tmp_path)
    assert marker.read_bytes() == (report.revision + "\n").encode("utf-8")


# -- Orphan GC ----------------------------------------------------------------


def test_gc_removes_undesired_file_and_folder(tmp_path):
    """Spec 'Undesired paths are removed'."""
    library = _StubLibrary(published=[_published("alpha")])
    materializer = SkillMaterializer(library, project_root=tmp_path)
    materializer.materialize(None)
    staging = resolve_staging_root(tmp_path)

    stray_file = staging / "world" / "demiurgos-W-ghost@1.0.0" / "SKILL.md"
    stray_file.parent.mkdir(parents=True)
    stray_file.write_bytes(b"orphan")
    stray_nested = staging / "orphan" / "nested"
    stray_nested.mkdir(parents=True)
    (stray_nested / "leaf.txt").write_bytes(b"leaf")

    report = materializer.materialize(None)
    assert report.ok is True
    assert not (staging / "world").exists()
    assert not (staging / "orphan").exists()
    assert report.deleted == 2
    assert (
        staging / TRANSVERSAL_SUBDIR / "demiurgos-alpha@1.0.0" / "SKILL.md"
    ).is_file()


def test_gc_collects_deactivated_world_skill(tmp_path):
    """Spec 'A deactivated world-specific skill is collected'."""
    published = [
        _published("alpha"),
        _published("worldskill", foundational=False),
    ]
    active = _StubLibrary(
        published=published,
        activations={"W": _activation("W", "worldskill", "1.0.0")},
    )
    materializer = SkillMaterializer(active, project_root=tmp_path)
    first = materializer.materialize("W")
    staging = resolve_staging_root(tmp_path)
    world_dir = staging / WORLD_SUBDIR / "demiurgos-W-worldskill@1.0.0"
    assert (world_dir / "SKILL.md").is_file()

    deactivated = _StubLibrary(published=published, activations={})
    report = SkillMaterializer(deactivated, project_root=tmp_path).materialize("W")
    assert report.ok is True
    assert not world_dir.exists()
    assert (
        staging / TRANSVERSAL_SUBDIR / "demiurgos-alpha@1.0.0" / "SKILL.md"
    ).is_file()
    assert report.revision != first.revision


def test_gc_preserves_sentinels(tmp_path):
    """Spec 'Sentinels survive GC': `.gitkeep` and the marker both survive."""
    staging = resolve_staging_root(tmp_path)
    staging.mkdir(parents=True, exist_ok=True)
    (staging / ".gitkeep").write_bytes(b"")
    library = _StubLibrary(published=[_published("alpha")])
    materializer = SkillMaterializer(library, project_root=tmp_path)
    materializer.materialize(None)
    materializer.materialize(None)
    assert (staging / ".gitkeep").exists()
    assert (staging / REVISION_MARKER_NAME).exists()


def test_gc_containment_skips_escaping_symlink(tmp_path):
    """A `..`/symlink candidate never escapes the staging root."""
    library = _StubLibrary(published=[_published("alpha")])
    materializer = SkillMaterializer(library, project_root=tmp_path)
    materializer.materialize(None)
    staging = resolve_staging_root(tmp_path)

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret = outside_dir / "secret.txt"
    secret.write_bytes(b"secret bytes")

    absolute_link = staging / "evil_absolute"
    relative_link = staging / "evil_relative"
    try:
        absolute_link.symlink_to(outside_dir, target_is_directory=True)
        relative_link.symlink_to(
            os.path.relpath(outside_dir, staging), target_is_directory=True
        )
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")

    report = materializer.materialize(None)
    assert secret.read_bytes() == b"secret bytes"
    assert sorted(p.name for p in outside_dir.iterdir()) == ["secret.txt"]
    assert any(issue.code == "containment-violation" for issue in report.issues)
    assert (
        staging / TRANSVERSAL_SUBDIR / "demiurgos-alpha@1.0.0" / "SKILL.md"
    ).is_file()


# -- Fail-safe abort ----------------------------------------------------------


class _RaisingLibrary(_StubLibrary):
    """A library whose read seam raises, simulating an unreadable source."""

    def __init__(self, exc, *, native_channels=None):
        super().__init__(native_channels=native_channels)
        self._exc = exc

    def list_published(self):
        raise self._exc


@pytest.mark.parametrize(
    "exc",
    [OSError("library is unreadable"), ValueError("library is malformed")],
)
def test_abort_on_unreadable_library(tmp_path, exc):
    """Spec 'Unreadable library aborts without deleting' + 'does not report
    success': no writes, no GC, no marker advance, observable failure."""
    staging = resolve_staging_root(tmp_path)
    pre_existing = staging / TRANSVERSAL_SUBDIR / "demiurgos-old@1.0.0" / "SKILL.md"
    pre_existing.parent.mkdir(parents=True)
    pre_existing.write_bytes(b"pre-existing derived bytes")
    (staging / ".gitkeep").write_bytes(b"")
    marker = revision_marker_path(tmp_path)
    marker.write_bytes(b"deadbeef\n")

    report = SkillMaterializer(
        _RaisingLibrary(exc), project_root=tmp_path
    ).materialize(None)

    assert report.ok is False
    assert report.aborted is True
    assert report.revision is None
    assert report.written == 0
    assert report.deleted == 0
    assert report.issues and report.issues[0].code == "library-unreadable"
    assert pre_existing.read_bytes() == b"pre-existing derived bytes"
    assert (staging / ".gitkeep").read_bytes() == b""
    assert marker.read_bytes() == b"deadbeef\n"


# -- Promotion staging -> live (WU-3.1, REQ-LP-1..7 / REQ-MM-3) ---------------


def _live_files(live: Path) -> frozenset[str]:
    """Relative posix path of every file under the live folder (empty when the
    folder does not exist)."""
    if not live.is_dir():
        return frozenset()
    return frozenset(
        path.relative_to(live).as_posix() for path in live.rglob("*") if path.is_file()
    )


def _promoted_marker(live: Path) -> bytes:
    return (live / REVISION_MARKER_NAME).read_bytes()


def test_promote_flag_off_leaves_live_untouched(tmp_path):
    """Spec 'Flag OFF — live folder untouched' (REQ-LP-2): with the native
    channel OFF for the world, promotion is a no-op and never creates the
    registered live folder."""
    library = _StubLibrary(published=[_published("alpha")])  # default OFF
    report = SkillPromoter(library, project_root=tmp_path).promote("W")
    assert isinstance(report, PromoteReport)
    assert report.ok is True
    assert report.promoted is False
    assert report.revision is None
    assert not resolve_skills_dir(tmp_path).exists()


def test_promote_writes_complete_desired_set_into_live(tmp_path):
    """Spec 'Successful atomic promotion' (REQ-LP-1 scenario 1): the live
    folder reflects the complete desired set plus the preserved sentinels, and
    no generation/left-aside tree is left behind."""
    library = _StubLibrary(
        published=[
            _published("alpha"),
            _published("worldskill", foundational=False),
        ],
        activations={"W": _activation("W", "worldskill", "1.0.0")},
        native_channels={"W": True},
    )
    report = SkillPromoter(library, project_root=tmp_path).promote("W")
    assert report.ok is True
    assert report.promoted is True
    assert report.revision is not None
    assert report.written >= 2  # both desired SKILL.md files
    live = resolve_skills_dir(tmp_path)
    assert _live_files(live) == frozenset(
        {
            f"{TRANSVERSAL_SUBDIR}/demiurgos-alpha@1.0.0/SKILL.md",
            f"{WORLD_SUBDIR}/demiurgos-W-worldskill@1.0.0/SKILL.md",
            ".gitkeep",
            REVISION_MARKER_NAME,
        }
    )
    assert _promoted_marker(live).decode("utf-8").strip() == report.revision
    assert not list(live.parent.glob(".skills-live-next-*"))
    assert not list(live.parent.glob(".skills-live-prev-*"))


def test_promote_swap_never_exposes_partial_tree(tmp_path, monkeypatch):
    """Spec 'A concurrent reader never observes a partial tree' (REQ-LP-1): at
    every observable point during the guarded two-rename swap the live folder
    holds the old complete tree, is briefly absent, or holds the new complete
    tree — never a partial or mixed-revision tree."""
    published = [
        _published("alpha"),
        _published("worldskill", foundational=False),
    ]
    active = _StubLibrary(
        published=published,
        activations={"W": _activation("W", "worldskill", "1.0.0")},
        native_channels={"W": True},
    )
    live = resolve_skills_dir(tmp_path)
    SkillPromoter(active, project_root=tmp_path).promote("W")
    old_set = _live_files(live)

    reverted = _StubLibrary(
        published=published, activations={}, native_channels={"W": True}
    )
    observed: list[frozenset[str]] = []
    real_replace = materializer_module.os.replace

    def spy(source, destination):
        observed.append(_live_files(live))
        real_replace(source, destination)
        observed.append(_live_files(live))

    monkeypatch.setattr(materializer_module.os, "replace", spy)
    SkillPromoter(reverted, project_root=tmp_path).promote("W")

    new_set = _live_files(live)
    empty: frozenset[str] = frozenset()
    for snapshot in observed:
        assert snapshot in (old_set, new_set, empty), f"partial tree observed: {snapshot}"
    assert new_set == frozenset(
        {
            f"{TRANSVERSAL_SUBDIR}/demiurgos-alpha@1.0.0/SKILL.md",
            ".gitkeep",
            REVISION_MARKER_NAME,
        }
    )


def test_promote_interruption_rolls_back_prior_state(tmp_path, monkeypatch):
    """Spec 'Interruption leaves a consistent prior state' (REQ-LP-1 scenario 2):
    a swap failure restores the prior consistent revision in the live folder and
    a retry is available."""
    published = [
        _published("alpha"),
        _published("worldskill", foundational=False),
    ]
    promoter = SkillPromoter(
        _StubLibrary(published=[_published("alpha")], native_channels={"W": True}),
        project_root=tmp_path,
    )
    first = promoter.promote("W")
    assert first.promoted is True
    live = resolve_skills_dir(tmp_path)
    prior_marker = _promoted_marker(live)
    prior_set = _live_files(live)

    real_replace = materializer_module.os.replace
    failed = False

    def flaky(source, destination):
        nonlocal failed
        # Fail the generation-tree move-in exactly once (the rollback rename
        # back to ``live`` must still succeed to restore the prior state).
        if Path(destination) == live and not failed:
            failed = True
            raise OSError("simulated interrupted swap")
        return real_replace(source, destination)

    monkeypatch.setattr(materializer_module.os, "replace", flaky)
    extended = SkillPromoter(
        _StubLibrary(
            published=published,
            activations={"W": _activation("W", "worldskill", "1.0.0")},
            native_channels={"W": True},
        ),
        project_root=tmp_path,
    )
    with pytest.raises(OSError):
        extended.promote("W")

    # The prior consistent tree is restored: same revision, complete content.
    assert _promoted_marker(live) == prior_marker
    assert _live_files(live) == prior_set
    assert not list(live.parent.glob(".skills-live-next-*"))
    assert not list(live.parent.glob(".skills-live-prev-*"))

    # Retry is available and lands the new revision.
    monkeypatch.undo()
    retry = extended.promote("W")
    assert retry.ok is True and retry.promoted is True
    assert _promoted_marker(live).decode("utf-8").strip() == retry.revision
    assert (live / WORLD_SUBDIR / "demiurgos-W-worldskill@1.0.0" / "SKILL.md").is_file()


def test_promote_abort_on_render_library_error(tmp_path):
    """Spec 'Aborted materialization does not promote' (REQ-LP-1 / REQ-MM-1
    scenario 3): a render/library failure aborts with the live tree
    byte-unchanged and the prior revision preserved."""
    library = _StubLibrary(
        published=[_published("alpha")], native_channels={"W": True}
    )
    promoter = SkillPromoter(library, project_root=tmp_path)
    first = promoter.promote("W")
    live = resolve_skills_dir(tmp_path)
    prior_marker = _promoted_marker(live)
    prior_set = _live_files(live)

    report = SkillPromoter(
        _RaisingLibrary(ValueError("render failure"), native_channels={"W": True}),
        project_root=tmp_path,
    ).promote("W")

    assert report.ok is False
    assert report.promoted is False
    assert report.revision is None
    assert report.written == 0 and report.deleted == 0
    assert _promoted_marker(live) == prior_marker
    assert _live_files(live) == prior_set
    assert first.revision is not None
    assert not list(live.parent.glob(".skills-live-next-*"))


def test_revision_digest_changes_on_layout_change(tmp_path):
    """Spec 'Any desired change changes the revision' (REQ-LP-3): a scope/
    layout change — the same skills under a different world — changes the
    digest, because layout is part of the canonical form."""
    published = [
        _published("alpha"),
        _published("w1", foundational=False),
        _published("w2", foundational=False),
    ]
    m1 = SkillMaterializer(
        _StubLibrary(
            published=published,
            activations={"W1": _activation("W1", "w1", "1.0.0")},
        ),
        project_root=tmp_path,
    )
    m2 = SkillMaterializer(
        _StubLibrary(
            published=published,
            activations={"W2": _activation("W2", "w2", "1.0.0")},
        ),
        project_root=tmp_path,
    )
    assert m1.desired_set("W1") != m2.desired_set("W2")
    assert _revision_digest(m1.desired_set("W1")) != _revision_digest(
        m2.desired_set("W2")
    )


def test_promote_idempotent_rerun_no_churn(tmp_path):
    """Spec 'Idempotent re-promotion' (REQ-LP-7 scenario 1): re-running with an
    unchanged desired set produces no duplicate files, an unchanged revision,
    and no new marker write."""
    library = _StubLibrary(
        published=[_published("alpha")], native_channels={"W": True}
    )
    promoter = SkillPromoter(library, project_root=tmp_path)
    first = promoter.promote("W")
    live = resolve_skills_dir(tmp_path)
    marker_before = _promoted_marker(live)
    files_before = _live_files(live)

    second = promoter.promote("W")

    assert first.promoted is True and first.ok is True
    assert second.ok is True
    assert second.promoted is False
    assert second.revision == first.revision
    assert _promoted_marker(live) == marker_before
    assert _live_files(live) == files_before
    assert not list(live.parent.glob(".skills-live-next-*"))
    assert not list(live.parent.glob(".skills-live-prev-*"))


def test_promote_rollback_by_repromotion(tmp_path):
    """Spec 'Rollback by repromotion' (REQ-LP-7 scenario 2): reverting to the
    prior desired set and repromoting returns the live folder to the prior
    consistent state and the revision reflects the reverted set."""
    published = [
        _published("alpha"),
        _published("worldskill", foundational=False),
    ]
    active = _StubLibrary(
        published=published,
        activations={"W": _activation("W", "worldskill", "1.0.0")},
        native_channels={"W": True},
    )
    live = resolve_skills_dir(tmp_path)
    with_skill = SkillPromoter(active, project_root=tmp_path).promote("W")
    assert (live / WORLD_SUBDIR / "demiurgos-W-worldskill@1.0.0" / "SKILL.md").is_file()

    reverted = _StubLibrary(
        published=published, activations={}, native_channels={"W": True}
    )
    without = SkillPromoter(reverted, project_root=tmp_path).promote("W")
    assert without.promoted is True
    assert without.revision != with_skill.revision
    assert not (live / WORLD_SUBDIR).exists()
    assert (live / TRANSVERSAL_SUBDIR / "demiurgos-alpha@1.0.0" / "SKILL.md").is_file()

    # Repromoting the original desired set restores it, revision included.
    restored = SkillPromoter(active, project_root=tmp_path).promote("W")
    assert restored.promoted is True
    assert restored.revision == with_skill.revision
    assert (live / WORLD_SUBDIR / "demiurgos-W-worldskill@1.0.0" / "SKILL.md").is_file()


def test_promote_collects_deactivated_skill_preserves_sentinels(tmp_path):
    """Spec 'Deactivated skill is collected' + 'Sentinels preserved' (REQ-LP-4):
    a skill dropped from the desired set disappears from the reconciled live
    set, while `.gitkeep` and `.demiurgos-revision` survive."""
    published = [
        _published("alpha"),
        _published("worldskill", foundational=False),
    ]
    active = _StubLibrary(
        published=published,
        activations={"W": _activation("W", "worldskill", "1.0.0")},
        native_channels={"W": True},
    )
    live = resolve_skills_dir(tmp_path)
    SkillPromoter(active, project_root=tmp_path).promote("W")
    world_dir = live / WORLD_SUBDIR / "demiurgos-W-worldskill@1.0.0"
    assert world_dir.is_dir()
    assert (live / ".gitkeep").exists()
    assert (live / REVISION_MARKER_NAME).exists()
    assert not list(live.parent.glob(".skills-live-next-*"))

    deactivated = _StubLibrary(
        published=published, activations={}, native_channels={"W": True}
    )
    report = SkillPromoter(deactivated, project_root=tmp_path).promote("W")
    assert report.ok is True and report.promoted is True
    assert not world_dir.exists()
    assert (live / ".gitkeep").exists()
    assert (live / REVISION_MARKER_NAME).exists()
    assert (live / TRANSVERSAL_SUBDIR / "demiurgos-alpha@1.0.0" / "SKILL.md").is_file()


def test_promote_gc_containment_surfaces_violation(tmp_path):
    """Spec 'Containment violation is surfaced' (REQ-LP-4 / REQ-MM-3): the
    promoted-side GC is the same containment-checked walk — an escaping
    candidate is reported, never deleted."""
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_bytes(b"secret bytes")
    next_root = resolve_skills_dir(tmp_path).parent / ".skills-live-next-test"
    legal = next_root / TRANSVERSAL_SUBDIR / "demiurgos-alpha@1.0.0"
    legal.mkdir(parents=True)
    (legal / "SKILL.md").write_bytes(b"# Body\n")
    try:
        (next_root / "evil").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")

    deleted, issues = _gc_tree(
        next_root, {f"{TRANSVERSAL_SUBDIR}/demiurgos-alpha@1.0.0/SKILL.md"}
    )

    assert secret.read_bytes() == b"secret bytes"
    assert deleted == 0
    assert any(issue.code == "containment-violation" for issue in issues)


def test_materialize_skips_unchanged_marker_write(tmp_path):
    """Spec 'Unchanged marker is a no-op' (REQ-LP-5): ``materialize()`` does not
    rewrite the staging ``.demiurgos-revision`` when its bytes are unchanged, so
    the gateway guard watching the marker stays a no-op on idempotent reruns."""
    library = _StubLibrary(published=[_published("alpha")])
    materializer = SkillMaterializer(library, project_root=tmp_path)
    materializer.materialize(None)
    marker = revision_marker_path(tmp_path)
    mtime_before = marker.stat().st_mtime_ns

    second = materializer.materialize(None)

    assert second.ok is True and second.written == 0
    assert marker.stat().st_mtime_ns == mtime_before  # not rewritten
    assert list(resolve_staging_root(tmp_path).glob(".tmp-*")) == []

    # A content change still rewrites the marker with the new revision.
    changed = SkillMaterializer(
        _StubLibrary(published=[_published("alpha"), _published("beta")]),
        project_root=tmp_path,
    ).materialize(None)
    assert marker.read_bytes().decode("utf-8").strip() == changed.revision
    assert changed.revision != second.revision
