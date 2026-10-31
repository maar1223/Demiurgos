"""On-demand semantic sweep: one candidate, one model call (P3).

The sweep proposes; it never writes. Each call:

1. scans the deterministic candidates and picks the first (path order);
2. builds the existing importer prompt over that ficha and a bounded catalog;
3. runs the production Hermes bridge;
4. parses and validates with the importer's own rules;
5. stores the surviving proposals and records the ficha as swept at its
   current body digest.

A provider that returns nothing usable does NOT mark the ficha swept, so an
outage cannot silently hide reviewable work.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from import_enrichment import (
    build_relationship_batch_prompt,
    parse_hermes_response,
    validate_relationship_batch,
)
from import_relations import relaciones_entry_key
from relation_candidates import RelationCandidate, scan_candidates
from relation_proposals import Proposal, add_proposals, load_proposals, proposal_id
from relation_rejections import load_rejected
from relation_state import mark_swept

logger = logging.getLogger(__name__)

#: Bounded catalog so a big world still fits in one prompt.
CATALOG_LIMIT = 60
#: Bounded body excerpt for the source ficha.
SOURCE_BODY_LIMIT = 4000

HermesRunner = Callable[[str, str], str]


@dataclass(frozen=True)
class _PromptEntity:
    candidate_id: str
    canonical_id: str
    normalized_identity: str
    display_title: str
    summary: str = ""


@dataclass(frozen=True)
class SweepResult:
    status: str  # swept | done | unavailable
    path: str = ""
    created: int = 0
    pending: int = 0
    message: str = ""


def sweep_next(
    *,
    mundo: str,
    mundos_dir: Path,
    index: Any,
    runner: HermesRunner,
    catalog_limit: int = CATALOG_LIMIT,
) -> SweepResult:
    """Sweep the next candidate. One call, one ficha, no writes to content."""
    world_dir = Path(mundos_dir) / mundo
    candidates = scan_candidates(mundo=mundo, mundos_dir=mundos_dir, index=index)
    if not candidates:
        return SweepResult(status="done", message="No hay fichas por revisar.")

    candidate = candidates[0]
    entities = index.entities() if index is not None else []
    source_entity = next(
        (entity for entity in entities if entity.get("path") == candidate.path),
        None,
    )
    if source_entity is None:
        return SweepResult(
            status="unavailable",
            path=candidate.path,
            message="La ficha ya no está en el índice; probá de nuevo.",
        )

    source = _project(source_entity, body_limit=SOURCE_BODY_LIMIT)
    catalog = _build_catalog(entities, candidate, catalog_limit)
    prompt = json.dumps(
        build_relationship_batch_prompt([source], catalog=catalog),
        ensure_ascii=False,
    )
    raw = runner(prompt, f"sweep-{mundo}-{uuid.uuid4().hex}")
    if not _looks_parsed(raw):
        return SweepResult(
            status="unavailable",
            path=candidate.path,
            message="El proveedor semántico no respondió; probá de nuevo.",
        )

    parsed = parse_hermes_response(raw)
    suggestions = validate_relationship_batch(parsed, [source], catalog=catalog)

    declared = {
        relaciones_entry_key(entry)
        for entry in (source_entity.get("relaciones") or [])
        if isinstance(entry, str)
    }
    rejected = load_rejected(world_dir)
    now = datetime.now(timezone.utc).isoformat()
    proposals: list[Proposal] = []
    for suggestion in suggestions:
        target_id = str(suggestion.target_candidate_id or "")
        if not target_id or target_id == candidate.source_key or target_id in declared:
            continue
        if (candidate.source_key, target_id) in rejected:
            continue
        relationship_type = str(suggestion.relationship_type or "")
        proposals.append(
            Proposal(
                id=proposal_id(candidate.source_key, target_id, relationship_type),
                source_path=candidate.path,
                source_key=candidate.source_key,
                target_id=target_id,
                relationship_type=relationship_type,
                confidence=float(suggestion.confidence or 0.0),
                evidence=str(suggestion.evidence or ""),
                created_at=now,
            )
        )

    try:
        added = add_proposals(world_dir, proposals)
        mark_swept(world_dir, candidate.path, candidate.digest, at=now)
    except OSError as exc:
        logger.warning("relations: cannot persist sweep result for %s: %s", mundo, exc)
        return SweepResult(
            status="unavailable",
            path=candidate.path,
            message="No se pudo guardar la cola de propuestas.",
        )

    return SweepResult(
        status="swept",
        path=candidate.path,
        created=len(added),
        pending=len(load_proposals(world_dir)),
    )


def _project(entity: dict, *, body_limit: int | None = None) -> _PromptEntity:
    canonical_id = str(entity.get("id") or "")
    title = str(entity.get("name") or entity.get("title") or canonical_id)
    body = str(entity.get("content") or "")
    if body_limit is not None:
        body = body[:body_limit]
    return _PromptEntity(
        candidate_id=canonical_id or str(entity.get("path") or ""),
        canonical_id=canonical_id,
        normalized_identity=canonical_id,
        display_title=title,
        summary=body,
    )


def _build_catalog(
    entities: Iterable[dict],
    candidate: RelationCandidate,
    limit: int,
) -> list[_PromptEntity]:
    """Mentioned entities first, then the same folder, then the rest."""
    mentioned = set(candidate.mentions)
    folder = candidate.path.rsplit("/", 1)[0] if "/" in candidate.path else ""

    def rank(entity: dict) -> tuple[int, str]:
        canonical_id = str(entity.get("id") or "")
        path = str(entity.get("path") or "")
        if canonical_id in mentioned:
            group = 0
        elif folder and path.startswith(f"{folder}/"):
            group = 1
        else:
            group = 2
        return (group, canonical_id or path)

    ordered = sorted(
        (
            entity
            for entity in entities
            if isinstance(entity, dict) and entity.get("id")
        ),
        key=rank,
    )
    # The validator grounds the SOURCE against the same universe, so the
    # source ficha must always be present even when the catalog is capped.
    source = [entity for entity in ordered if entity.get("path") == candidate.path]
    rest = [entity for entity in ordered if entity.get("path") != candidate.path]
    selected = (source + rest)[: max(1, limit)]
    return [_project(entity) for entity in selected]


def _looks_parsed(raw: str) -> bool:
    stripped = (raw or "").strip()
    return bool(stripped) and "{" in stripped
