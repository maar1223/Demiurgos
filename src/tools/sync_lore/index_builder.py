"""
index_builder.py — Builds the LoreIndex from chunk and image results.

Handles entity merging, deduplication, contradiction detection,
and relationship resolution.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal

from .schemas import (
    ApprovedCharacterWrite,
    ContradictionEntry,
    LoreEntity,
    LoreIndex,
    LoreIndexMeta,
    StalTier,
)

if TYPE_CHECKING:
    from .providers.base import ChunkResult
    from .schemas import Chunk, ImageEntry


# ---------------------------------------------------------------------------
# Entity type normalization
# ---------------------------------------------------------------------------

_VALID_TYPES = frozenset({
    "personaje", "criatura", "objeto", "lugar",
    "concepto", "evento", "organizacion", "especie",
})


def _normalize_type(raw_type: str) -> str:
    """Map LLM-returned types to valid EntityType values."""
    t = raw_type.strip().lower()
    if t in _VALID_TYPES:
        return t
    # Fuzzy mappings
    fuzzy = {
        "character": "personaje",
        "creature": "criatura",
        "object": "objeto",
        "place": "lugar",
        "location": "lugar",
        "concept": "concepto",
        "event": "evento",
        "organization": "organizacion",
        "organisation": "organizacion",
        "species": "especie",
    }
    return fuzzy.get(t, "concepto")  # default fallback


# ---------------------------------------------------------------------------
# Dedup key
# ---------------------------------------------------------------------------

def _dedup_key(entity: dict) -> tuple[str, str, str]:
    """Dedup key: (name lowercase, type, world or '')."""
    return (
        entity.get("name", "").strip().lower(),
        entity.get("type", "concepto").strip().lower(),
        (entity.get("world") or "").strip().lower(),
    )


# ---------------------------------------------------------------------------
# Index builder
# ---------------------------------------------------------------------------

def build_index(
    chunk_results: list[tuple["Chunk", "ChunkResult"]],
    image_entries: list["ImageEntry"] | None = None,
    world: str | None = None,
    mode: str = "text",
    stal_tiers: dict[str, str] | None = None,
) -> LoreIndex:
    """
    Build a complete LoreIndex from chunk results and image entries.

    Steps:
    1. Collect all entities from chunk results
    2. Dedup by (name, type, world): merge relations, dedup quotes
    3. Detect cross-chunk contradictions
    4. Build terms index
    5. Assemble final LoreIndex

    Args:
        chunk_results: List of (Chunk, ChunkResult) from text processing.
        image_entries: Optional list of processed ImageEntry.
        world: Active world name or None.
        mode: Processing mode (text/images/both).
        stal_tiers: Optional dict mapping entity name -> StalTier value.

    Returns:
        Complete LoreIndex ready for persistence.
    """
    if stal_tiers is None:
        stal_tiers = {}

    if image_entries is None:
        image_entries = []

    # === Step 1: Collect raw entities ===
    raw_entities: list[dict] = []
    raw_terms: list[dict] = []
    chunk_claims: list[dict] = []  # [(chunk_ref, entity_name, claim), ...]

    for chunk, cr in chunk_results:
        source_file = chunk.source_file
        chunk_ref = chunk.heading_path

        for ent in cr.entities:
            ent["_source_file"] = source_file
            ent["_chunk_ref"] = chunk_ref
            ent["_world"] = world
            raw_entities.append(ent)

            # Track claims for contradiction detection
            if ent.get("description"):
                chunk_claims.append({
                    "chunk_ref": chunk_ref,
                    "entity_name": ent.get("name", ""),
                    "claim": ent.get("description", ""),
                    "source_file": source_file,
                })

        for term in cr.terms:
            term["_source_file"] = source_file
            term["_chunk_ref"] = chunk_ref
            raw_terms.append(term)

    # === Step 2: Dedup entities ===
    deduped: dict[tuple, dict] = {}

    for ent in raw_entities:
        key = _dedup_key(ent)
        name = ent.get("name", "").strip()
        ent_type = _normalize_type(ent.get("type", "concepto"))

        if key not in deduped:
            deduped[key] = {
                "name": name,
                "type": ent_type,
                "world": world,
                "source_file": ent.get("_source_file", ""),
                "chunk_ref": ent.get("_chunk_ref", ""),
                "description": ent.get("description", ""),
                "relations": ent.get("relations", []),
                "terms": ent.get("terms", []),
                "stal_tier": stal_tiers.get(name.lower()),
                "quotes": ent.get("quotes", []),
                "sources": [ent.get("_source_file", "")],
                "chunk_refs": [ent.get("_chunk_ref", "")],
            }
        else:
            existing = deduped[key]
            # Merge description: keep longest
            new_desc = ent.get("description", "")
            if len(new_desc) > len(existing["description"]):
                existing["description"] = new_desc

            # Merge relations: same target+type = keep highest strength
            existing_rels: dict[tuple, dict] = {}
            for rel in existing["relations"]:
                rkey = (rel.get("target", "").lower(), rel.get("type", "").lower())
                existing_rels[rkey] = rel
            for rel in ent.get("relations", []):
                rkey = (rel.get("target", "").lower(), rel.get("type", "").lower())
                if rkey not in existing_rels:
                    existing_rels[rkey] = rel
                else:
                    new_str = rel.get("strength", 1.0)
                    old_str = existing_rels[rkey].get("strength", 1.0)
                    if new_str > old_str:
                        existing_rels[rkey] = rel
            existing["relations"] = list(existing_rels.values())

            # Dedup quotes
            existing_quotes_set = set(existing["quotes"])
            for q in ent.get("quotes", []):
                if q not in existing_quotes_set:
                    existing["quotes"].append(q)
                    existing_quotes_set.add(q)

            # Track all sources
            src = ent.get("_source_file", "")
            if src and src not in existing["sources"]:
                existing["sources"].append(src)
            cr_ref = ent.get("_chunk_ref", "")
            if cr_ref and cr_ref not in existing["chunk_refs"]:
                existing["chunk_refs"].append(cr_ref)

    # Build LoreEntity list
    entities: list[LoreEntity] = []
    entity_id_map: dict[str, str] = {}  # name.lower() -> uuid
    for key, edata in deduped.items():
        eid = str(uuid.uuid4())
        e = LoreEntity(
            id=eid,
            name=edata["name"],
            type=edata["type"],
            world=edata["world"],
            source_file=edata["source_file"],
            chunk_ref=edata["chunk_ref"],
            description=edata["description"],
            relations=edata["relations"],
            terms=edata["terms"],
            stal_tier=edata["stal_tier"],
            quotes=edata["quotes"],
        )
        entities.append(e)
        entity_id_map[edata["name"].lower()] = eid

    # Resolve relation targets: string name -> uuid
    for e in entities:
        for rel in e.relations:
            target_name = rel.get("target", "")
            target_id = entity_id_map.get(target_name.lower())
            if target_id:
                rel["target_id"] = target_id

    # === Step 3: Contradiction detection ===
    contradictions: list[ContradictionEntry] = []
    # Group claims by entity name
    claims_by_entity: dict[str, list[dict]] = {}
    for claim in chunk_claims:
        ename = claim["entity_name"].strip().lower()
        if ename not in claims_by_entity:
            claims_by_entity[ename] = []
        claims_by_entity[ename].append(claim)

    # Compare claims pairwise within each entity
    for ename, claims in claims_by_entity.items():
        if len(claims) < 2:
            continue
        for i in range(len(claims)):
            for j in range(i + 1, len(claims)):
                a = claims[i]
                b = claims[j]
                # Simple heuristic: if both have non-empty claims and they
                # come from different chunks, flag as potential contradiction
                if (
                    a["claim"]
                    and b["claim"]
                    and a["chunk_ref"] != b["chunk_ref"]
                    and a["claim"].lower() != b["claim"].lower()
                ):
                    # Skip if both claims are identical or very similar
                    if _claims_different(a["claim"], b["claim"]):
                        eid = entity_id_map.get(ename, "")
                        is_stal_t1 = stal_tiers.get(ename, "") == StalTier.T1
                        contradictions.append(
                            ContradictionEntry(
                                id=str(uuid.uuid4()),
                                entity=a["entity_name"],
                                entity_id=eid,
                                chunk_a={
                                    "file": a["source_file"],
                                    "heading": a["chunk_ref"],
                                    "claim": a["claim"],
                                },
                                chunk_b={
                                    "file": b["source_file"],
                                    "heading": b["chunk_ref"],
                                    "claim": b["claim"],
                                },
                                reason=f"Contradictory claims about {a['entity_name']} "
                                       f"in {a['chunk_ref']} vs {b['chunk_ref']}",
                                stal_conflict=is_stal_t1,
                            )
                        )

    # === Step 4: Build terms index ===
    terms_index: dict[str, dict] = {}
    for t in raw_terms:
        term_name = t.get("term", "").strip().lower()
        if not term_name:
            continue
        if term_name not in terms_index:
            terms_index[term_name] = {
                "term": t.get("term", "").strip(),
                "definition": t.get("definition", ""),
                "sources": [t.get("_chunk_ref", "")],
            }
        else:
            src = t.get("_chunk_ref", "")
            if src and src not in terms_index[term_name]["sources"]:
                terms_index[term_name]["sources"].append(src)
            # Keep longest definition
            new_def = t.get("definition", "")
            if len(new_def) > len(terms_index[term_name]["definition"]):
                terms_index[term_name]["definition"] = new_def

    # === Step 5: Assemble LoreIndex ===
    meta = LoreIndexMeta(
        tool="sync-lore",
        version="0.1.0",
        generated_at=datetime.now(timezone.utc).isoformat(),
        world=world,
        mode=mode,
        chunks_processed=len(chunk_results),
        entities_extracted=len(entities),
        contradictions_found=len(contradictions),
    )

    # Convert image entries for JSON (strip image_bytes)
    serializable_images: list[dict] = []
    for img in image_entries:
        analysis_dict = None
        if img.analysis:
            analysis_dict = {
                "descripcion": img.analysis.descripcion,
                "veredicto": img.analysis.veredicto,
                "analisis": img.analysis.analisis,
                "tags": img.analysis.tags,
            }
        serializable_images.append({
            "id": img.id,
            "source_file": img.source_file,
            "page": img.page,
            "chunk_ref": img.chunk_ref,
            "context_text": img.context_text,
            "filename": img.filename,
            "analysis": analysis_dict,
        })

    return LoreIndex(
        meta=meta,
        entities=entities,
        terms=list(terms_index.values()),
        images=serializable_images,
        contradictions=contradictions,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _claims_different(a: str, b: str) -> bool:
    """Check if two claims are substantially different (not just whitespace)."""
    a_norm = " ".join(a.lower().split())
    b_norm = " ".join(b.lower().split())
    if a_norm == b_norm:
        return False
    # Check if one contains the other (substring match)
    if len(a_norm) > 10 and len(b_norm) > 10:
        if a_norm in b_norm or b_norm in a_norm:
            return False
    return True


# ---------------------------------------------------------------------------
# Approved character graph reconciliation (idempotent, approval-gated)
# ---------------------------------------------------------------------------


ReconcileStatus = Literal["indexed", "pending", "failed", "dirty"]


@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of reconciling one approved character write with the graph."""

    target: str
    content_digest: str
    index_status: ReconcileStatus
    retryable: bool
    message: str


class ApprovedCharacterReconciler:
    """Idempotently reconcile an approved character write with a graph index.

    Sync-lore-owned counterpart of the wiki ``ReindexCoordinator``: it never
    repeats durable file creation and never writes canon.  Results are
    memoized by ``(target, content_digest)`` so a repeated reconcile for the
    same approved write is a no-op that does not re-run the graph build.
    Fail-closed: a missing file or a content digest mismatch never yields an
    ``indexed`` result.
    """

    def __init__(
        self,
        mundos_root: Path,
        index_factory: Callable[[str], Any],
    ) -> None:
        self._mundos_root = mundos_root
        self._index_factory = index_factory
        self._results: dict[tuple[str, str], ReconcileResult] = {}

    def reconcile(self, approved: ApprovedCharacterWrite) -> ReconcileResult:
        key = (approved.target, approved.content_digest)
        previous = self._results.get(key)
        if previous is not None and previous.index_status == "indexed":
            return previous

        full = (self._mundos_root / approved.world / approved.target).resolve()
        world_root = (self._mundos_root / approved.world).resolve()
        if world_root not in full.parents or not full.is_file():
            return self._remember(
                key,
                ReconcileResult(
                    approved.target, approved.content_digest, "failed", False,
                    "Character was not persisted; graph reconciliation was not attempted.",
                ),
            )
        actual_digest = hashlib.sha256(full.read_bytes()).hexdigest()
        if actual_digest != approved.content_digest:
            return self._remember(
                key,
                ReconcileResult(
                    approved.target, approved.content_digest, "failed", False,
                    "Character content changed; graph reconciliation requires re-review.",
                ),
            )

        try:
            index = self._index_factory(approved.world)
            index.build(approved.world)
            if index.dirty:
                return self._remember(
                    key,
                    ReconcileResult(
                        approved.target, approved.content_digest, "dirty", True,
                        "Character created; graph indexing is still dirty. Retry shortly.",
                    ),
                )
            if index.get_entity(approved.target) is None:
                return self._remember(
                    key,
                    ReconcileResult(
                        approved.target, approved.content_digest, "pending", True,
                        "Character created; graph indexing is pending. Retry or reload.",
                    ),
                )
            return self._remember(
                key,
                ReconcileResult(
                    approved.target, approved.content_digest, "indexed", False,
                    "Character created and is visible in the graph.",
                ),
            )
        except Exception:
            return self._remember(
                key,
                ReconcileResult(
                    approved.target, approved.content_digest, "failed", True,
                    "Character created; graph indexing is unavailable. Retry later.",
                ),
            )

    def _remember(self, key: tuple[str, str], result: ReconcileResult) -> ReconcileResult:
        self._results[key] = result
        return result
