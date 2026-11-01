"""On-demand semantic sweep: a bounded batch of independent sources (P3).

The sweep proposes; it never writes content. One call:

1. scans the deterministic candidates and takes the first ``batch_size`` of
   them, ordered by value (most mentions first, path as tie-breaker);
2. builds one :class:`Source` per candidate with the FULL body as evidence and
   a bounded excerpt as the prompt body;
3. builds the catalog from EVERY indexed entity, so a target never needs to
   travel in the same batch;
4. runs the shared batch-safe primitive once;
5. converts the surviving quote-backed claims into proposals and records each
   source as swept at its current body digest.

Batch composition only affects recall, never truth: an outage (a provider that
never answered) does NOT mark any ficha swept, so it cannot silently hide
reviewable work.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from import_relations import relaciones_entry_key
from relation_candidates import scan_candidates
from relation_evidence import load_evidence
from relation_proposals import Proposal, add_proposals, load_proposals, proposal_id
from relation_proposing import (
    CatalogEntry,
    Claim,
    Source,
    pair_key,
    propose_relations_outcome,
)
from relation_rejections import load_rejected
from relation_state import mark_swept

logger = logging.getLogger(__name__)

#: Default number of fichas reviewed in one model call.
DEFAULT_BATCH_SIZE = 5
#: Hard bounds for the batch size; the UI and the endpoint both clamp here.
MIN_BATCH_SIZE = 1
MAX_BATCH_SIZE = 10
#: Safety valve for the target universe. It is deliberately far above the old
#: 60-entry cap: the catalog must be the whole world, not the batch. A world
#: larger than this loses recall (some targets are not offered), never
#: correctness (an offered claim still needs its own body quote).
CATALOG_LIMIT = 1000
#: Bounded body excerpt sent to the model. Verification always uses the full
#: body, so truncation costs recall only.
SOURCE_BODY_LIMIT = 4000

ModelRunner = Callable[[str, str], str]


@dataclass(frozen=True)
class SweepResult:
    """One batch result. ``paths`` is the deterministic batch order."""

    status: str  # swept | done | unavailable
    swept: int = 0
    created: int = 0
    pending: int = 0
    paths: list[str] = field(default_factory=list)
    message: str = ""


def clamp_batch_size(size: Any) -> int:
    """Coerce a caller-supplied batch size into ``[MIN..MAX]``.

    A missing, boolean or non-integer value falls back to the default instead
    of failing the request: the sweep is a review helper, not a strict API.
    """
    if isinstance(size, bool) or not isinstance(size, int):
        return DEFAULT_BATCH_SIZE
    return max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, size))


def sweep_batch(
    *,
    mundo: str,
    mundos_dir: Path,
    index: Any,
    runner: ModelRunner,
    batch_size: int = DEFAULT_BATCH_SIZE,
    catalog_limit: int = CATALOG_LIMIT,
) -> SweepResult:
    """Review a bounded batch of candidates in one independent model call."""
    world_dir = Path(mundos_dir) / mundo
    size = clamp_batch_size(batch_size)
    candidates = scan_candidates(mundo=mundo, mundos_dir=mundos_dir, index=index)
    if not candidates:
        return SweepResult(
            status="done",
            pending=len(load_proposals(world_dir)),
            message="No hay fichas por revisar.",
        )

    batch = candidates[:size]
    entities = index.entities() if index is not None else []
    by_path = {
        str(entity.get("path") or ""): entity
        for entity in entities
        if isinstance(entity, dict)
    }

    sources: list[Source] = []
    digests: dict[str, str] = {}
    declared: dict[str, tuple[str, ...]] = {}
    for candidate in batch:
        entity = by_path.get(candidate.path)
        if entity is None:
            # The index changed between the scan and this call. Skip the ficha
            # without marking it, so it stays reviewable.
            continue
        body = str(entity.get("content") or "")
        sources.append(
            Source(
                key=candidate.source_key,
                path=candidate.path,
                name=candidate.title,
                body=body,
                prompt_body=body[:SOURCE_BODY_LIMIT],
            )
        )
        digests[candidate.path] = candidate.digest
        declared[candidate.source_key] = tuple(
            relaciones_entry_key(entry)
            for entry in (entity.get("relaciones") or [])
            if isinstance(entry, str)
        )

    if not sources:
        return SweepResult(
            status="unavailable",
            pending=len(load_proposals(world_dir)),
            message="Las fichas ya no están en el índice; probá de nuevo.",
        )

    catalog = _build_catalog(entities, catalog_limit)
    known_pairs = _known_pairs(declared, world_dir)
    outcome = propose_relations_outcome(
        sources=sources,
        catalog=catalog,
        runner=runner,
        known_pairs=known_pairs,
        session_id=f"sweep-{mundo}-{uuid.uuid4().hex}",
    )
    if not outcome.provider_ok:
        return SweepResult(
            status="unavailable",
            pending=len(load_proposals(world_dir)),
            paths=[source.path for source in sources],
            message="El proveedor semántico no respondió; probá de nuevo.",
        )

    now = datetime.now(timezone.utc).isoformat()
    proposals = [_to_proposal(claim, now) for claim in outcome.claims]
    try:
        added = add_proposals(world_dir, proposals)
        for source in sources:
            mark_swept(world_dir, source.path, digests[source.path], at=now)
    except OSError as exc:
        logger.warning("relations: cannot persist sweep result for %s: %s", mundo, exc)
        return SweepResult(
            status="unavailable",
            pending=len(load_proposals(world_dir)),
            paths=[source.path for source in sources],
            message="No se pudo guardar la cola de propuestas.",
        )

    return SweepResult(
        status="swept",
        swept=len(sources),
        created=len(added),
        pending=len(load_proposals(world_dir)),
        paths=[source.path for source in sources],
    )


def _build_catalog(
    entities: Iterable[dict],
    limit: int,
) -> list[CatalogEntry]:
    """The world-wide target universe, deduped and deterministically ordered."""
    by_id: dict[str, CatalogEntry] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        canonical_id = str(entity.get("id") or "")
        if not canonical_id or canonical_id in by_id:
            continue
        title = str(entity.get("name") or entity.get("title") or canonical_id)
        by_id[canonical_id] = CatalogEntry(
            canonical_id=canonical_id,
            display_title=title,
        )
    ordered = [by_id[key] for key in sorted(by_id)]
    return ordered[: max(0, limit)]


def _known_pairs(
    declared: dict[str, tuple[str, ...]],
    world_dir: Path,
) -> set[tuple[str, str]]:
    """Every pair already declared, rejected or body-verified for this world.

    Nothing already known may be proposed again, and the set is independent of
    the batch: it comes from the world's stores, not from who travelled
    together. Both directions collapse through :func:`pair_key`.
    """
    known: set[tuple[str, str]] = set()
    for source_key, targets in declared.items():
        for target in targets:
            known.add(pair_key(source_key, target))
    for left, right in load_rejected(world_dir):
        known.add(pair_key(left, right))
    for pair in load_evidence(world_dir):
        known.add(pair)
    return known


def _to_proposal(claim: Claim, now: str) -> Proposal:
    return Proposal(
        id=proposal_id(claim.source_key, claim.target_id, claim.relationship_type),
        source_path=claim.source_path,
        source_key=claim.source_key,
        target_id=claim.target_id,
        relationship_type=claim.relationship_type,
        confidence=claim.confidence,
        evidence=claim.quote,
        created_at=now,
    )
