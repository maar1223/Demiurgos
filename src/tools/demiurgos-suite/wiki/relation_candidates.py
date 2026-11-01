"""Deterministic candidate detection for the on-demand relation sweep (P3).

The badge must measure reviewable work without calling a model and without
decaying to a permanent zero. A ficha is a candidate when:

* its body mentions at least one other world entity (textual evidence, not the
  folder index), and
* its body digest differs from the one recorded at its last sweep (or it was
  never swept), and
* the Author has not muted it and the pair is not rejected.

Editing the body changes the digest, so the ficha becomes reviewable again.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from import_relations import (
    build_relation_targets,
    grounded_relations,
    relaciones_entry_key,
)
from relation_rejections import load_rejected
from relation_state import SweepState, load_state


@dataclass(frozen=True)
class RelationCandidate:
    """One ficha the sweep may review."""

    path: str
    source_key: str
    title: str
    digest: str
    mentions: tuple[str, ...]
    missing: tuple[str, ...]


def body_digest(body: str) -> str:
    """Stable digest of a ficha body; drives the "reviewable again" rule."""
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


def scan_candidates(
    *,
    mundo: str,
    mundos_dir: Path,
    index: Any,
    rejected: set[tuple[str, str]] | None = None,
    state: SweepState | None = None,
) -> list[RelationCandidate]:
    """Return the world's sweep candidates, deterministically ordered."""
    world_dir = Path(mundos_dir) / mundo
    if rejected is None:
        rejected = load_rejected(world_dir)
    if state is None:
        state = load_state(world_dir)

    entities = index.entities() if index is not None else []
    if not entities:
        return []
    targets = build_relation_targets(entities)

    candidates: list[RelationCandidate] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        path = str(entity.get("path") or "")
        if not path or path in state.muted:
            continue
        body = str(entity.get("content") or "")
        digest = body_digest(body)
        if state.swept.get(path) == digest:
            continue
        source_id = str(entity.get("id") or "")
        source_key = source_id or path
        grounded = grounded_relations(
            body=body,
            source_id=source_id,
            source_path=path,
            targets=targets,
            structural_uncapped=True,
        )
        mentions = tuple(
            relation.canonical_id
            for relation in grounded
            # Folder membership is not a narrative mention: the sweep is about
            # what the text says, and structural edges are P1's job.
            if relation.evidence != "folder-index"
            and (source_key, relation.canonical_id) not in rejected
        )
        if not mentions:
            continue
        declared = {
            relaciones_entry_key(entry)
            for entry in (entity.get("relaciones") or [])
            if isinstance(entry, str)
        }
        candidates.append(
            RelationCandidate(
                path=path,
                source_key=source_key,
                title=str(entity.get("name") or entity.get("title") or path),
                digest=digest,
                mentions=mentions,
                missing=tuple(
                    target for target in mentions if target not in declared
                ),
            )
        )

    # Value first: a ficha that mentions many entities carries more reviewable
    # work than one that mentions a single neighbour. Path is the deterministic
    # tie-breaker, so the order never depends on index traversal or dict order.
    # Ordering by value also keeps one batch from being N near-identical
    # siblings: the richest fichas are reviewed before path-adjacent ones.
    candidates.sort(key=lambda candidate: (-len(candidate.mentions), candidate.path))
    return candidates
