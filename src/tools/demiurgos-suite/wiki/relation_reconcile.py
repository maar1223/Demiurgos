"""World-wide deterministic reconciliation plan (P4).

The plan is read-only. It says, for every graph entity, which relations the text
justifies and which declared entries no text backs:

* ``add`` — grounded relations the ficha does not declare;
* ``remove`` — declared entries that are not grounded, are dangling (the target
  no longer exists) or were rejected by the Author.

Curation wins: a rejected pair (P2) is never added and is removed if present, and
a muted ficha (P3 "leave as is") is skipped entirely.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from import_relations import (
    build_relation_targets,
    grounded_relations,
    normalize_mention,
    relaciones_entry_key,
)
from relation_rejections import load_rejected
from relation_state import SweepState, load_state

logger = logging.getLogger(__name__)

PREIMAGES_DIR = "preimages"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Removal:
    """One declared entry the reconciliation would remove."""

    key: str
    target_id: str
    reason: str  # ungrounded | unresolved | rejected


@dataclass(frozen=True)
class FilePlan:
    path: str
    source_key: str
    add: tuple[str, ...]
    remove: tuple[Removal, ...]


@dataclass(frozen=True)
class GlobalPlan:
    files: tuple[FilePlan, ...]

    @property
    def additions(self) -> int:
        return sum(len(file_plan.add) for file_plan in self.files)

    @property
    def removals(self) -> int:
        return sum(len(file_plan.remove) for file_plan in self.files)

    @property
    def unresolved(self) -> int:
        return sum(
            1
            for file_plan in self.files
            for removal in file_plan.remove
            if removal.reason == "unresolved"
        )

    def __bool__(self) -> bool:
        return bool(self.files)


def build_global_plan(
    *,
    mundo: str,
    mundos_dir: Path,
    index: Any,
    rejected: set[tuple[str, str]] | None = None,
    state: SweepState | None = None,
) -> GlobalPlan:
    """Compute the reconciliation plan for the whole world."""
    world_dir = Path(mundos_dir) / mundo
    if rejected is None:
        rejected = load_rejected(world_dir)
    if state is None:
        state = load_state(world_dir)

    entities = index.entities() if index is not None else []
    if not entities:
        return GlobalPlan(())

    resolver = _Resolver(entities)
    targets = build_relation_targets(entities)

    files: list[FilePlan] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        path = str(entity.get("path") or "")
        if not path or path in state.muted:
            continue
        source_id = str(entity.get("id") or "")
        source_key = source_id or path
        body = str(entity.get("content") or "")
        grounded = {
            relation.canonical_id
            for relation in grounded_relations(
                body=body,
                source_id=source_id,
                source_path=path,
                targets=targets,
                structural_uncapped=True,
            )
            if (source_key, relation.canonical_id) not in rejected
        }

        declared_entries = [
            entry for entry in (entity.get("relaciones") or []) if isinstance(entry, str)
        ]
        kept: set[str] = set()
        removals: list[Removal] = []
        for entry in declared_entries:
            key = relaciones_entry_key(entry)
            if not key:
                continue
            resolved = resolver.resolve(key)
            if resolved is None:
                removals.append(Removal(key=key, target_id="", reason="unresolved"))
            elif resolved not in grounded:
                reason = (
                    "rejected"
                    if (source_key, resolved) in rejected
                    else "ungrounded"
                )
                removals.append(Removal(key=key, target_id=resolved, reason=reason))
            else:
                kept.add(resolved)

        additions = tuple(sorted(grounded - kept))
        if additions or removals:
            files.append(
                FilePlan(
                    path=path,
                    source_key=source_key,
                    add=additions,
                    remove=tuple(removals),
                )
            )

    files.sort(key=lambda file_plan: file_plan.path)
    return GlobalPlan(tuple(files))


class _Resolver:
    """Resolve a declared ``relaciones`` entry to a canonical id."""

    def __init__(self, entities: Iterable[dict]) -> None:
        self._by_id: dict[str, str] = {}
        self._by_name: dict[str, set[str]] = {}
        self._by_stem: dict[str, set[str]] = {}
        self._by_path: dict[str, str] = {}
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            canonical_id = str(entity.get("id") or "")
            path = str(entity.get("path") or "")
            if not canonical_id:
                continue
            self._by_id[canonical_id] = canonical_id
            if path:
                self._by_path[path] = canonical_id
                stem = path.rsplit("/", 1)[-1]
                if stem.lower().endswith(".md"):
                    stem = stem[:-3]
                self._by_stem.setdefault(normalize_mention(stem), set()).add(canonical_id)
            name = str(entity.get("name") or entity.get("title") or "")
            if name:
                self._by_name.setdefault(normalize_mention(name), set()).add(canonical_id)

    def resolve(self, key: str) -> str | None:
        if key in self._by_id:
            return self._by_id[key]
        if key in self._by_path:
            return self._by_path[key]
        normalized = normalize_mention(key)
        for table in (self._by_name, self._by_stem):
            candidates = table.get(normalized)
            if candidates:
                return next(iter(candidates)) if len(candidates) == 1 else None
        return None


def create_preimage_backup(
    world_dir: Path,
    paths: Iterable[str],
    *,
    counts: dict[str, int] | None = None,
    moment: datetime | None = None,
) -> tuple[Path, tuple[str, ...]]:
    """Copy every affected file under ``.relations/preimages/<stamp>/``.

    Per-file fail-open: a file that cannot be copied is returned as skipped so
    the caller reports it instead of aborting the whole pass. Only a failure to
    write the manifest (the backup itself) raises.
    """
    stamp = (moment or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S%fZ")
    root = Path(world_dir) / ".relations" / PREIMAGES_DIR / stamp
    files_root = root / "files"
    copied: list[str] = []
    skipped: list[str] = []
    for relative in sorted(set(paths)):
        source = Path(world_dir) / relative
        if not source.is_file():
            skipped.append(relative)
            continue
        destination = files_root / relative
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as exc:
            logger.warning("relations: cannot back up %s: %s", relative, exc)
            skipped.append(relative)
            continue
        copied.append(relative)
    manifest = {
        "version": SCHEMA_VERSION,
        "created_at": (moment or datetime.now(timezone.utc)).isoformat(),
        "files": copied,
        "counts": dict(counts or {}),
    }
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f".manifest.{uuid.uuid4().hex}.tmp"
    try:
        tmp.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, root / "manifest.json")
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return root, tuple(skipped)
