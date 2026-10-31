"""Deterministic relation reconciliation after a ficha is saved (P1).

The importer grounds relations from the ficha body, but a ficha created by the
Assistant, materialized from an idea, or edited by hand never grew relations.
This service closes that gap: after a successful write it computes the
deterministic relations the world's own text justifies, so the graph grows
inside the app instead of through an out-of-band repair script.

Four passes, per the Owner's design (``roadmap/relations-lifecycle``):

* forward — the changed ficha's body against the world catalog;
* reverse — existing fichas whose body names the changed ficha;
* folder index — the folder's index file and its members (derived from the
  path, inside :func:`import_relations.grounded_relations`);
* idempotency — the plan only lists grounded ids, and the applier adds just the
  ones a ficha does not carry yet.

The service is pure and read-only: it returns a :class:`RelationPlan` and the
API layer applies it with the same frontmatter helpers every other relation
write uses, so there is exactly one writer of ``relaciones:``.

Cost: the catalog and the unchanged bodies come from the already-parsed graph
index in memory; only the changed fichas are re-read from disk.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from import_relations import (
    RelationTarget,
    build_relation_targets,
    grounded_relations,
)

logger = logging.getLogger(__name__)

_FRONTMATTER = re.compile(r"^---\r?\n([\s\S]*?)^---[ \t]*(?=\r?\n|$)", re.MULTILINE)


@dataclass(frozen=True)
class RelationPlan:
    """Grounded relation ids per mundo-relative ficha path."""

    relations: dict[str, tuple[str, ...]]

    def __bool__(self) -> bool:
        return bool(self.relations)


@dataclass(frozen=True)
class _Ficha:
    path: str
    canonical_id: str
    name: str
    body: str


def build_relation_plan(
    *,
    mundo: str,
    changed_paths: Iterable[str],
    mundos_dir: Path,
    index: Any = None,
) -> RelationPlan:
    """Compute the grounded relations affected by ``changed_paths``.

    ``index`` is the world's ``EntityGraphIndex`` (duck-typed: it only needs
    ``entities()``). When it is ``None`` the changed fichas still get their
    forward pass, but the reverse pass cannot see the rest of the world.
    """

    changed = [path for path in dict.fromkeys(changed_paths) if path]
    if not changed:
        return RelationPlan({})

    world_root = Path(mundos_dir) / mundo
    fichas = _indexed_fichas(index)
    changed_fichas: list[_Ficha] = []
    for rel_path in changed:
        ficha = _read_ficha(world_root / rel_path, rel_path)
        if ficha is None:
            # The ficha stopped being an entity (``graph: false``, non-OKF,
            # or deleted): never propose relations for or through it.
            fichas.pop(rel_path, None)
            continue
        fichas[rel_path] = ficha
        changed_fichas.append(ficha)

    targets = _unique_targets(
        build_relation_targets(
            {
                "id": ficha.canonical_id,
                "name": ficha.name,
                "path": ficha.path,
            }
            for ficha in fichas.values()
        )
    )
    changed_ids = {ficha.canonical_id for ficha in changed_fichas if ficha.canonical_id}
    changed_targets = [
        target for target in targets if target.canonical_id in changed_ids
    ]

    changed_set = {ficha.path for ficha in changed_fichas}
    sources = list(changed_fichas)
    if changed_targets:
        for ficha in fichas.values():
            if ficha.path in changed_set or not ficha.body:
                continue
            # Reverse pass: only a ficha that actually names a changed entity
            # is worth recomputing, so the cost stays O(k) in the common case.
            if grounded_relations(
                body=ficha.body,
                source_id=ficha.canonical_id,
                source_path=ficha.path,
                targets=changed_targets,
            ):
                sources.append(ficha)

    plan: dict[str, tuple[str, ...]] = {}
    for source in sources:
        relations = grounded_relations(
            body=source.body,
            source_id=source.canonical_id,
            source_path=source.path,
            targets=targets,
        )
        if relations:
            plan[source.path] = tuple(
                relation.canonical_id for relation in relations
            )
    return RelationPlan(plan)


def _indexed_fichas(index: Any) -> dict[str, _Ficha]:
    if index is None:
        return {}
    try:
        entities = index.entities()
    except Exception as exc:  # noqa: BLE001 — a broken index must not break a save
        logger.warning("relations: graph index unavailable: %s", exc)
        return {}
    fichas: dict[str, _Ficha] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        path = str(entity.get("path") or "")
        name = str(entity.get("name") or entity.get("title") or "")
        if not path or not name:
            continue
        fichas[path] = _Ficha(
            path=path,
            canonical_id=str(entity.get("id") or ""),
            name=name,
            body=str(entity.get("content") or ""),
        )
    return fichas


def _read_ficha(full: Path, rel_path: str) -> _Ficha | None:
    """Parse one Okf ficha; ``None`` when it is not a relation-bearing entity."""

    try:
        content = full.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _FRONTMATTER.match(content)
    if match is None:
        return None
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(frontmatter, dict) or not frontmatter.get("type"):
        return None
    if frontmatter.get("graph") is False:
        return None
    canonical_id = frontmatter.get("id")
    # A ficha without a canonical id can still be a SOURCE (its body grows
    # relations); it simply cannot be a TARGET. ``build_relation_targets``
    # drops it from the catalog because it has no id.
    canonical_id = canonical_id.strip() if isinstance(canonical_id, str) else ""
    title = frontmatter.get("title")
    name = title if isinstance(title, str) and title.strip() else full.stem.replace("_", " ")
    return _Ficha(
        path=rel_path,
        canonical_id=canonical_id,
        name=name,
        body=content[match.end():],
    )


def _unique_targets(targets: Iterable[RelationTarget]) -> list[RelationTarget]:
    unique: list[RelationTarget] = []
    seen: set[str] = set()
    for target in targets:
        if target.canonical_id in seen:
            continue
        seen.add(target.canonical_id)
        unique.append(target)
    return unique
