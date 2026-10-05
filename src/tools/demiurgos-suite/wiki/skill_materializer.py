# -*- coding: utf-8 -*-
"""skill-materializer-reconciliation — desired set, atomic writes, GC, revision.

The reconciling materializer resolves the desired set of native Hermes skills
for a world from the library's single source of truth, writes that set into an
unregistered staging tree with per-file atomic writes, garbage-collects every
staging path no longer desired, and emits a deterministic materialization
revision (advancing the revision marker only after a successful write+GC).

It is correct by construction: after a successful run the staging tree equals
exactly the desired set plus the protected sentinels, and an unreadable or
malformed library aborts the whole run without deleting anything or advancing
the marker (fail-safe, never destructive).

Invariant: every write lands under the staging root; the registered live folder
``data/methodology/skills/`` is never created or modified here.
"""

from __future__ import annotations

import hashlib
import json
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
#: The materialization revision marker (written last, after a successful pass).
REVISION_MARKER_NAME = ".demiurgos-revision"
#: Root-level paths GC must never delete (exact-path match).
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

    On a fail-safe abort ``ok``/``aborted`` are ``False``/``True`` and
    ``revision`` is ``None`` with ``written``/``deleted`` both ``0``: nothing was
    written, nothing was deleted, and the marker was not advanced. On success
    ``revision`` is the deterministic desired-tree digest, ``deleted`` the number
    of files/symlinks removed by orphan GC, and ``issues`` carries every render
    and GC issue surfaced during the pass.
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


def _revision_digest(desired: tuple[DesiredSkill, ...]) -> str:
    """Deterministic materialization revision over the desired tree.

    The canonical form is the desired list sorted by ``relative_dir``, each
    entry ``{relative_dir, skill_id, version, scope, name, skill_md_sha256,
    attachments: sorted([{path, bytes, sha256}])}``. It is serialized as
    ``json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))``
    and SHA-256 digested. It depends only on content — never on write order,
    timestamps, or filesystem state — so an unchanged desired tree yields an
    identical revision and any add/remove/version/layout/attachment change
    yields a different one.
    """
    canonical: list[dict] = []
    for skill in sorted(desired, key=lambda entry: entry.relative_dir):
        rendered = skill.rendered
        attachments = sorted(
            (
                {
                    "path": attachment.path,
                    "bytes": len(attachment.bytes),
                    "sha256": hashlib.sha256(attachment.bytes).hexdigest(),
                }
                for attachment in rendered.attachments
            ),
            key=lambda item: (item["path"], item["sha256"]),
        )
        canonical.append(
            {
                "relative_dir": skill.relative_dir,
                "skill_id": skill.skill_id,
                "version": skill.version,
                "scope": skill.scope,
                "name": rendered.skill_name,
                "skill_md_sha256": rendered.skill_md_sha256,
                "attachments": attachments,
            }
        )
    payload = json.dumps(
        canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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

    # -- write + GC + revision ------------------------------------------ #

    @staticmethod
    def _contained(candidate: Path, root: Path) -> bool:
        """True when ``candidate`` resolves inside the resolved staging root."""
        try:
            resolved = candidate.resolve()
        except (OSError, ValueError):
            return False
        return resolved == root or root in resolved.parents

    def _gc(self, desired_paths: set[str]) -> tuple[int, tuple[RenderIssue, ...]]:
        """Delete every staging path outside ``desired_paths`` (spec D3).

        Walks the staging tree bottom-up, removing every file/symlink that is
        not a desired relative path and not an exact root-level sentinel
        (``.gitkeep`` / the revision marker), then prunes emptied directories.
        Every candidate is resolved and asserted inside the resolved staging
        root before it is touched: a symlink or ``..`` that escapes staging is
        left untouched and surfaced as a ``containment-violation`` issue, so GC
        can never delete outside its own tree. The staging root itself is never
        removed. Returns ``(deleted_file_count, issues)``.
        """
        staging = self._staging_root
        if not staging.is_dir():
            return 0, ()
        root = staging.resolve()
        deleted = 0
        issues: list[RenderIssue] = []
        for dirpath, dirnames, filenames in os.walk(
            staging, topdown=False, followlinks=False
        ):
            current = Path(dirpath)
            # Symlinked directories are listed in ``dirnames`` but never
            # descended; treat them as removable candidates too.
            candidates = list(filenames) + [
                name for name in dirnames if (current / name).is_symlink()
            ]
            for name in candidates:
                candidate = current / name
                if not self._contained(candidate, root):
                    issues.append(
                        RenderIssue(
                            code="containment-violation",
                            message=(
                                f"Staging candidate {candidate} escapes the "
                                "staging root; it was left untouched."
                            ),
                            field="staging",
                        )
                    )
                    continue
                relative = candidate.relative_to(staging).as_posix()
                if relative in SENTINEL_NAMES:
                    continue
                if relative in desired_paths:
                    continue
                try:
                    candidate.unlink()
                except OSError:
                    continue
                deleted += 1
            if current != staging:
                try:
                    current.rmdir()
                except OSError:
                    pass
        return deleted, tuple(issues)

    def materialize(self, world: str | None) -> MaterializationReport:
        """Reconcile the desired set into staging, emit + mark the revision.

        Fail-safe: any exception while reading the library or rendering the
        desired set aborts the whole pass — nothing is written, nothing is
        deleted, and the marker is not advanced — and surfaces an observable
        ``library-unreadable`` issue (never a silent success). On success the
        changed files are written atomically, orphan GC reconciles the tree,
        the deterministic revision is computed, and the marker is advanced last.
        """
        try:
            desired = self.desired_set(world)
        except Exception as exc:  # noqa: BLE001 - fail-safe abort boundary
            return MaterializationReport(
                ok=False,
                aborted=True,
                revision=None,
                written=0,
                deleted=0,
                issues=(
                    RenderIssue(
                        code="library-unreadable",
                        message=(
                            "Materialization aborted: the methodology library "
                            f"could not be read ({type(exc).__name__}: {exc}). "
                            "No staging path was modified and the revision "
                            "marker was not advanced."
                        ),
                        field="library",
                    ),
                ),
            )

        issues: list[RenderIssue] = []
        written = 0
        desired_paths: set[str] = set()
        for skill in desired:
            base = self._staging_root / skill.relative_dir
            files: dict[str, bytes] = {"SKILL.md": skill.rendered.skill_md}
            for attachment in skill.rendered.attachments:
                files[attachment.path] = attachment.bytes
            for relative_path, data in files.items():
                desired_paths.add(
                    (Path(skill.relative_dir) / relative_path).as_posix()
                )
                target = base / relative_path
                if target.is_file() and target.read_bytes() == data:
                    continue
                _atomic_write(target, data)
                written += 1
            issues.extend(skill.rendered.issues)

        deleted, gc_issues = self._gc(desired_paths)
        issues.extend(gc_issues)

        revision = _revision_digest(desired)
        _atomic_write(
            revision_marker_path(self._project_root),
            (revision + "\n").encode("utf-8"),
        )
        return MaterializationReport(
            ok=True,
            aborted=False,
            revision=revision,
            written=written,
            deleted=deleted,
            issues=tuple(issues),
        )
