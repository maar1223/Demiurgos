"""On-demand semantic conflict sweep (S3).

One model call reviews ONE ficha against a bounded list of related fichas
(declared relations, wikilinks, backlinks). The sweep proposes; it never writes
content and never decides canon.

Batch composition only affects how many calls you pay for, never truth: each
source is verified against its own body and against the target's body, so an
outage (a provider that never answered) marks nothing swept and cannot hide
reviewable work.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from conflict_decisions import (
    known_semantic_keys,
    load_records,
    record_proposal,
)
from conflict_proposing import SourceFicha, propose_conflicts_outcome
from import_relations import relaciones_entry_key
from relation_candidates import body_digest

logger = logging.getLogger(__name__)

#: Default number of fichas reviewed in one call.
DEFAULT_BATCH_SIZE = 3
#: Hard bounds for the batch size; the UI and the endpoint both clamp here.
MIN_BATCH_SIZE = 1
MAX_BATCH_SIZE = 5
#: Related fichas offered to the model per source.
TARGET_LIMIT = 8
#: Bounded body excerpt sent to the model. Verification always uses the full
#: body, so truncation costs recall only.
SOURCE_BODY_LIMIT = 4000
TARGET_BODY_LIMIT = 1500
STATE_DIR = ".conflicts"
STATE_NAME = "swept.json"
SCHEMA_VERSION = 1

ModelRunner = Callable[[str, str], str]

_LOCK = threading.Lock()

_RELATION_KEY_FIELDS = ("target_id", "target", "id", "name")


@dataclass(frozen=True)
class ConflictSweepResult:
    """One batch result. ``paths`` is the deterministic batch order."""

    status: str  # swept | done | unavailable
    swept: int = 0
    created: int = 0
    #: Claims the model produced with a quote that is not in the ficha.
    discarded: int = 0
    #: Semantic proposals waiting for the Author (not fichas left to review).
    proposals: int = 0
    paths: list[str] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True)
class ReviewProgress:
    """How much of the world has been reviewed at its current text."""

    total: int = 0
    reviewed: int = 0
    pending: int = 0


def review_progress(
    *,
    mundo: str,
    mundos_dir: Path,
    index: Any,
) -> ReviewProgress:
    """Coverage of the semantic review, by body digest.

    A ficha counts as reviewed only when its CURRENT text is the one the sweep
    saw: editing it puts it back in the queue, because the new text may
    contradict something else.
    """
    world_dir = Path(mundos_dir) / mundo
    entities = index.entities() if index is not None else []
    by_path = {
        str(entity.get("path") or ""): entity
        for entity in entities
        if isinstance(entity, dict)
    }
    if not by_path:
        return ReviewProgress()
    swept = _load_swept(world_dir)
    pending = sum(
        1
        for path, entity in by_path.items()
        if swept.get(path) != body_digest(str(entity.get("content") or ""))
    )
    return ReviewProgress(
        total=len(by_path),
        reviewed=len(by_path) - pending,
        pending=pending,
    )


def clamp_batch_size(size: Any) -> int:
    """Coerce a caller-supplied batch size into ``[MIN..MAX]``."""
    if isinstance(size, bool) or not isinstance(size, int):
        return DEFAULT_BATCH_SIZE
    return max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, size))


def state_path(world_dir: Path) -> Path:
    return Path(world_dir) / STATE_DIR / STATE_NAME


def _load_swept(world_dir: Path) -> dict[str, str]:
    try:
        raw = state_path(world_dir).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("conflicts: cannot read sweep state: %s", exc)
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    entries = data.get("swept") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {
        str(path): str(digest)
        for path, digest in entries.items()
        if isinstance(path, str) and isinstance(digest, str)
    }


def _mark_swept(world_dir: Path, path: str, digest: str) -> None:
    with _LOCK:
        entries = _load_swept(world_dir)
        entries[path] = digest
        target = state_path(world_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"version": SCHEMA_VERSION, "swept": dict(sorted(entries.items()))},
            ensure_ascii=False,
            indent=2,
        )
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(payload + "\n", encoding="utf-8")
        os.replace(tmp, target)


def _entity_key(entity: dict[str, Any]) -> str:
    return str(entity.get("id") or entity.get("path") or "")


def _relation_key(entry: Any) -> str:
    if isinstance(entry, dict):
        for field_name in _RELATION_KEY_FIELDS:
            value = entry.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    return relaciones_entry_key(str(entry))


def _related_paths(
    entity: dict[str, Any],
    by_path: dict[str, dict],
    resolve: Callable[[str], Iterable[str]],
) -> list[str]:
    """Bounded deterministic shortlist: relations, wikilinks and backlinks."""
    own = str(entity.get("path") or "")
    keys: list[str] = []
    for entry in entity.get("relaciones") or []:
        key = _relation_key(entry)
        if key:
            keys.append(key)
    keys.extend(str(link) for link in (entity.get("forward_links") or []))

    paths: list[str] = []
    for key in keys:
        for path in resolve(key) or ():
            if path != own and path in by_path and path not in paths:
                paths.append(path)
    for path in entity.get("backlinks") or []:
        if path != own and path in by_path and path not in paths:
            paths.append(path)
    return paths[:TARGET_LIMIT]


def _ficha(entity: dict[str, Any], *, limit: int) -> SourceFicha:
    body = str(entity.get("content") or "")
    return SourceFicha(
        key=_entity_key(entity),
        path=str(entity.get("path") or ""),
        name=str(entity.get("name") or entity.get("title") or ""),
        body=body,
        prompt_body=body[:limit],
    )


def _pending(world_dir: Path) -> int:
    return sum(
        1
        for record in load_records(world_dir).values()
        if record.state == "proposed"
    )


def sweep_conflicts_batch(
    *,
    mundo: str,
    mundos_dir: Path,
    index: Any,
    runner: ModelRunner,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ConflictSweepResult:
    """Review a bounded batch of fichas in one independent model call each."""
    world_dir = Path(mundos_dir) / mundo
    size = clamp_batch_size(batch_size)
    entities = index.entities() if index is not None else []
    by_path = {
        str(entity.get("path") or ""): entity
        for entity in entities
        if isinstance(entity, dict)
    }
    if not by_path:
        return ConflictSweepResult(status="done", message="El mundo no tiene fichas.")

    resolve = getattr(index, "_resolve_link_candidates", None)
    if resolve is None:
        return ConflictSweepResult(
            status="unavailable",
            message="El índice no puede resolver referencias.",
        )

    swept = _load_swept(world_dir)
    candidates: list[tuple[str, str, list[str]]] = []
    for path, entity in by_path.items():
        digest = body_digest(str(entity.get("content") or ""))
        if swept.get(path) == digest:
            continue
        candidates.append((path, digest, _related_paths(entity, by_path, resolve)))

    if not candidates:
        return ConflictSweepResult(
            status="done",
            proposals=_pending(world_dir),
            message="No hay fichas por revisar.",
        )

    candidates.sort(key=lambda item: (-len(item[2]), item[0]))
    batch = candidates[:size]
    known = known_semantic_keys(load_records(world_dir))

    reviewed = 0
    created = 0
    discarded = 0
    for path, digest, target_paths in batch:
        source = _ficha(by_path[path], limit=SOURCE_BODY_LIMIT)
        targets = [
            _ficha(by_path[target_path], limit=TARGET_BODY_LIMIT)
            for target_path in target_paths
            if target_path in by_path
        ]
        if not targets:
            # Nothing to compare: mark it so it is not picked again forever.
            _mark_swept(world_dir, path, digest)
            reviewed += 1
            continue

        outcome = propose_conflicts_outcome(
            source=source,
            targets=targets,
            runner=runner,
            known=known,
            session_id=f"conflicts-{mundo}-{uuid.uuid4().hex}",
        )
        discarded += outcome.discarded
        if not outcome.provider_ok:
            return ConflictSweepResult(
                status="unavailable",
                swept=reviewed,
                created=created,
                discarded=discarded,
                proposals=_pending(world_dir),
                paths=[item[0] for item in batch],
                message="El proveedor semántico no respondió; probá de nuevo.",
            )

        for claim in outcome.claims:
            record_proposal(
                world_dir,
                conflict_id=claim.conflict_id,
                source_a=claim.source_key,
                source_b=claim.target_key,
                path=claim.source_path,
                name=source.name,
                quote_a=claim.quote_a,
                quote_b=claim.quote_b,
                conflict_type=claim.conflict_type,
                confidence=claim.confidence,
                pair_left=claim.pair[0],
                pair_right=claim.pair[1],
            )
            known.add((claim.pair[0], claim.pair[1], claim.conflict_type))
            created += 1
        _mark_swept(world_dir, path, digest)
        reviewed += 1

    return ConflictSweepResult(
        status="swept",
        swept=reviewed,
        created=created,
        discarded=discarded,
        proposals=_pending(world_dir),
        paths=[item[0] for item in batch],
    )
