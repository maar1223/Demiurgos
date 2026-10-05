# -*- coding: utf-8 -*-
"""skill-materializer-reconciliation (WU 1.2a) — desired set + atomic writes.

Part 1 of the reconciling materializer. It resolves the desired set of native
Hermes skills for a world from the library's single source of truth and writes
that set into an unregistered staging tree with per-file atomic writes.

Orphan GC, the deterministic revision marker, and the fail-safe abort land in
WU 1.2b. This slice never deletes anything and never advances the marker, so it
is independently revertable and has no visible effect: staging is unregistered
and the registered live folder is never touched.

Invariant: every write lands under the staging root; the registered live folder
``data/methodology/skills/`` is never created or modified here.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from convergence_injection import carrier_root_for
from methodology_library import (
    DEFAULT_FLOW_TYPE,
    PublishedVersion,
    _version_key,
)
from methodology_trust import FOUNDATIONAL
from skill_renderer import (
    TRANSVERSAL_SCOPE,
    RenderIssue,
    RenderedSkill,
    render_skill,
)

#: Staging tree, a sibling of ``library.json``/``seeds/`` beside the source of
#: truth. Distinct from the registered live folder and NOT in ``external_dirs``.
STAGING_DIR_REL = Path("data") / "methodology" / "skills-staging"
#: The materialization revision marker (advanced only in WU 1.2b).
REVISION_MARKER_NAME = ".demiurgos-revision"
#: Paths GC must never delete (enforced in WU 1.2b).
SENTINEL_NAMES = (".gitkeep", REVISION_MARKER_NAME)
#: Layout subtrees (design D2).
TRANSVERSAL_SUBDIR = "transversal"
WORLD_SUBDIR = "world"


def resolve_staging_root(project_root: Path) -> Path:
    """Resolve the unregistered staging root under a checkout root."""
    return (Path(project_root).expanduser() / STAGING_DIR_REL).resolve()


def revision_marker_path(project_root: Path) -> Path:
    """Resolve the materialization revision marker under the staging root."""
    return resolve_staging_root(project_root) / REVISION_MARKER_NAME


@dataclass(frozen=True)
class DesiredSkill:
    """One skill the materializer wants present, already rendered."""

    skill_id: str
    version: str
    scope: str
    relative_dir: str
    rendered: RenderedSkill


@dataclass(frozen=True)
class MaterializationReport:
    """Outcome of one materialization pass.

    ``revision``/``deleted`` are always ``None``/``0`` in WU 1.2a: GC and the
    revision marker are added in WU 1.2b.
    """

    ok: bool
    aborted: bool
    revision: str | None
    written: int
    deleted: int
    issues: tuple[RenderIssue, ...]


def _atomic_write(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (temp sibling + ``os.replace``).

    A failure leaves the target's previous complete bytes in place and removes
    the temporary artifact; a success leaves no temporary artifact behind.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class SkillMaterializer:
    """Reconciles the library's desired skills into the staging tree."""

    def __init__(self, library, *, project_root: Path) -> None:
        self._library = library
        self._project_root = Path(project_root)
        self._staging_root = resolve_staging_root(self._project_root)

    # -- desired set ---------------------------------------------------- #

    def _transversals(self) -> list[PublishedVersion]:
        """Greatest non-deleted foundational version per ``skill_id``."""
        greatest: dict[str, PublishedVersion] = {}
        for published in self._library.list_published():
            if FOUNDATIONAL not in published.trust_attributes:
                continue
            current = greatest.get(published.skill_id)
            if current is None or _version_key(published.version) > _version_key(
                current.version
            ):
                greatest[published.skill_id] = published
        return [greatest[key] for key in sorted(greatest)]

    def _world_skills(self, world: str) -> list[PublishedVersion]:
        """The activated guided-flow skill plus every companion, resolved."""
        pairs: list[tuple[str, str]] = []
        activation = self._library.active_for(world, DEFAULT_FLOW_TYPE)
        if activation is not None:
            pairs.append((activation.skill_id, activation.version))
        for companion in self._library.list_companions(world):
            pairs.append((companion.skill_id, companion.version))
        resolved: list[PublishedVersion] = []
        for skill_id, version in pairs:
            published = self._library.get_published(skill_id, version)
            if published is not None:
                resolved.append(published)
        return resolved

    def _entry(
        self,
        published: PublishedVersion,
        *,
        scope: str,
        subdir: str,
        world_token: str | None,
    ) -> DesiredSkill:
        carrier_root = carrier_root_for(
            published.skill_id, project_root=self._project_root
        )
        rendered = render_skill(
            published,
            scope=scope,
            world_token=world_token,
            carrier_root=carrier_root,
        )
        return DesiredSkill(
            skill_id=published.skill_id,
            version=published.version,
            scope=scope,
            relative_dir=f"{subdir}/{rendered.directory_name}",
            rendered=rendered,
        )

    def desired_set(self, world: str | None) -> tuple[DesiredSkill, ...]:
        """Compute the desired skills: transversals plus the active world's.

        The set is derived solely from the library records (published,
        activation, companions). A ``world`` that is ``None`` or blank yields
        the transversals only. The result is sorted by ``relative_dir``; a
        skill reached twice (activated and companion) is deduplicated, and two
        distinct skills mapping to the same path raise ``ValueError``.
        """
        entries: list[DesiredSkill] = [
            self._entry(
                published,
                scope=TRANSVERSAL_SCOPE,
                subdir=TRANSVERSAL_SUBDIR,
                world_token=None,
            )
            for published in self._transversals()
        ]
        world_name = (world or "").strip()
        if world_name:
            entries.extend(
                self._entry(
                    published,
                    scope=world_name,
                    subdir=WORLD_SUBDIR,
                    world_token=None,
                )
                for published in self._world_skills(world_name)
            )
        by_path: dict[str, DesiredSkill] = {}
        for entry in entries:
            existing = by_path.get(entry.relative_dir)
            if existing is None:
                by_path[entry.relative_dir] = entry
            elif (existing.skill_id, existing.version, existing.scope) == (
                entry.skill_id,
                entry.version,
                entry.scope,
            ):
                continue  # same skill reached twice (activated + companion)
            else:
                raise ValueError(
                    f"desired skills collide on path {entry.relative_dir!r}: "
                    f"{existing.skill_id}@{existing.version} vs "
                    f"{entry.skill_id}@{entry.version}"
                )
        return tuple(sorted(by_path.values(), key=lambda skill: skill.relative_dir))

    # -- write pass ----------------------------------------------------- #

    def materialize(self, world: str | None) -> MaterializationReport:
        """Write the desired set atomically under staging (no GC, no marker)."""
        desired = self.desired_set(world)
        issues: list[RenderIssue] = []
        written = 0
        for skill in desired:
            base = self._staging_root / skill.relative_dir
            files: dict[str, bytes] = {"SKILL.md": skill.rendered.skill_md}
            for attachment in skill.rendered.attachments:
                files[attachment.path] = attachment.bytes
            for relative_path, data in files.items():
                target = base / relative_path
                if target.is_file() and target.read_bytes() == data:
                    continue
                _atomic_write(target, data)
                written += 1
            issues.extend(skill.rendered.issues)
        return MaterializationReport(
            ok=True,
            aborted=False,
            revision=None,
            written=written,
            deleted=0,
            issues=tuple(issues),
        )
