# -*- coding: utf-8 -*-
"""World importer — GLOBAL relationship catalog (cross-chunk) design test.

PROBLEM (relaciones por lote): el Paso 3 actual ejecuta
``validate_relationship_batch`` SOLO contra las fichas ``summarized`` del
chunk. ``validate_suggestions`` valida source y target contra
``valid_candidate_ids`` = las fichas de ESE lote, así que una relación real que
cruza dos lotes (p. ej. ``Sistema Stal::9no Stal`` ->
``Áyagars::…::Áyagar del 9no Stal``) se descarta como "ungrounded". Un paso
extra que de nuevo trocee por lotes reintroduce el mismo problema: seguiría
anclando por-lote.

SOLUTION PROPUESTA: las relaciones se resuelven UNA vez, contra el CATÁLOGO
global del documento (ids + display_title, ~1.1k tokens para 52 fichas), no
contra el set resumido del lote. El catálogo es el universo de validación:
cualquier ficha del documento puede ser destino, sin importar en qué lote se
resumió. La única restricción real es que la FUENTE debe tener resumen (para
poder razonar la relación); el destino solo necesita existir en el catálogo.

INVARIANTE de este test:
  * una relación cuyo destino vive en OTRO lote se conserva (se valida contra
    el catálogo completo, no contra el lote);
  * una ficha sin resumen (fallback) sigue siendo destino VÁLIDO: el catálogo
    la enumera, así el grafo no se rompe alrededor de fallbacks;
  * la FUENTE sigue limitada al set resumido (necesita summary para razonar).

Este test NO toca el funnel de producción: implementa la validación global
como helper limpio y verifica la invariante ANTES de migrar. Las reglas de
seguridad (vocabulario, confianza, self-link) se reutilizan desde
``validate_suggestions``.
"""

from __future__ import annotations

import sys
import uuid
from importlib import import_module
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_TOOLS = _HERE.parents[2]
for _p in (str(_WIKI), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_models import Candidate, Provenance  # noqa: E402


_enrichment = import_module("import_enrichment")


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _ficha(identity: str, *, canonical_id: str | None = None) -> Candidate:
    cid = canonical_id or identity
    return Candidate(
        candidate_id=uuid.uuid4().hex,
        job_id="job-catalog",
        world="world1",
        normalized_identity=cid,
        canonical_id=cid,
        display_title=identity.split("::")[-1],
        source_hash=f"sha256:{cid}",
        provenance=Provenance(
            source_path=f"lore/{identity}.md",
            source_kind="loose",
            source_hash=f"sha256:{cid}",
        ),
        content_preview=f"Cuerpo denso de {identity}.",
        size_bytes=len(f"Cuerpo denso de {identity}."),
    )


def _with_summary(candidate: Candidate, summary: str) -> Candidate:
    data = candidate.model_dump()
    data["summary"] = summary
    return Candidate(**data)


def _canonical_key(candidate: Candidate) -> str:
    return candidate.canonical_id or candidate.normalized_identity


# ---------------------------------------------------------------------------
# PROPOSED helper: global relationship validation against a document catalog
# ---------------------------------------------------------------------------


def _validate_global_relationships(
    parsed: dict,
    catalog_fichas: list[Candidate],
    summarized: list[Candidate],
    rel_vocab=None,
):
    """Validate relationships against the DOCUMENT-WIDE ``catalog_fichas``.

    ``catalog_fichas`` is the universe of valid sources AND targets: every ficha
    of the document, including fallback ones. ``summarized`` is used ONLY to
    gate which fichas may act as SOURCE (they need a summary to reason over).
    A target grounds if it exists in the catalog, even when it is fallback or
    lives in a different chunk. Reuses ``validate_suggestions`` for the safety
    rules by feeding it the catalog as the validation universe.
    """
    # Map identity -> candidate id over the FULL catalog (not the chunk).
    catalog_by_identity = {_canonical_key(c): c.candidate_id for c in catalog_fichas}
    catalog_by_id = {c.candidate_id: c.candidate_id for c in catalog_fichas}
    summarized_ids = {c.candidate_id for c in summarized}

    rel_list = parsed.get("relationships", []) if isinstance(parsed, dict) else []
    remapped: list[dict] = []
    for entry in rel_list:
        if not isinstance(entry, dict):
            continue
        src = entry.get("source_candidate_id") or entry.get("source_canonical_id")
        tgt = (entry.get("target_candidate_id")
               or entry.get("target_canonical_id")
               or entry.get("target_name"))
        if not isinstance(src, str) or not isinstance(tgt, str):
            continue
        # Source must be a summarized ficha (has a summary to reason over).
        src_id = catalog_by_identity.get(src) or catalog_by_id.get(src)
        if src_id is None or src_id not in summarized_ids:
            continue
        # Target grounds against the FULL catalog, not the chunk.
        tgt_id = catalog_by_identity.get(tgt) or catalog_by_id.get(tgt)
        if tgt_id is None:
            continue
        if src_id == tgt_id:
            continue  # self-link
        remapped.append({
            "id": entry.get("id"),
            "source_candidate_id": src_id,
            "target_candidate_id": tgt_id,
            "relationship_type": entry.get("relationship_type"),
            "confidence": entry.get("confidence"),
            "evidence": entry.get("evidence"),
        })
    _, relationships = _enrichment.validate_suggestions(
        {"classifications": [], "relationships": remapped},
        catalog_fichas,
        rel_vocab=rel_vocab,
    )
    return relationships


# ---------------------------------------------------------------------------
# INVARIANT: cross-chunk relationships are preserved via the global catalog
# ---------------------------------------------------------------------------


def test_cross_chunk_relationship_is_grounded_by_global_catalog():
    """A real relationship spanning two chunks is NOT lost.

    ``source`` lives in chunk 0 (summarized), ``target`` in chunk 1. Per-chunk
    validation drops it; the global catalog grounds it.
    """
    chunk0 = [_ficha(f"A{i}", canonical_id=f"Chunk0::{i}") for i in range(6)]
    chunk1 = [_ficha(f"G{i}", canonical_id=f"Chunk1::{i}") for i in range(6)]
    catalog_fichas = chunk0 + chunk1

    source = chunk0[0]
    target = chunk1[4]
    # Only the source chunk is summarized.
    summarized = [_with_summary(c, "resumen denso") for c in chunk0]

    parsed = {"relationships": [{
        "id": "r1",
        "source_candidate_id": source.candidate_id,
        "target_canonical_id": target.canonical_id,
        "relationship_type": "relacionado-con",
        "confidence": 0.9,
        "evidence": "mencionado en el resumen",
    }]}

    rels = _validate_global_relationships(parsed, catalog_fichas, summarized)
    assert len(rels) == 1, (
        "cross-chunk relationship must ground via the global catalog, "
        "not be rejected as ungrounded")


def test_target_in_other_chunk_need_not_be_summarized():
    """A cross-chunk target is valid even when that ficha is fallback.

    Reality check: ``9no Stal`` (chunk 0) relates to ``Áyagar del 9no Stal``
    (chunk 1), which may itself be fallback. The catalog enumerates it, so the
    link survives instead of breaking the graph.
    """
    source = _ficha("Sistema Stal::9no Stal – Mediador",
                    canonical_id="Sistema Stal::9no Stal – Mediador")
    target = _ficha("Áyagars::Impacto::Áyagar del 9no Stal – Mediador",
                    canonical_id="Áyagars::Impacto::Áyagar del 9no Stal – Mediador")
    catalog_fichas = [source, target]

    # Only the source is summarized; target is fallback.
    summarized = [_with_summary(source, "resumen del 9no Stal")]

    parsed = {"relationships": [{
        "id": "r2",
        "source_candidate_id": source.candidate_id,
        "target_canonical_id": target.canonical_id,
        "relationship_type": "miembro-de",
        "confidence": 0.9,
        "evidence": "el 9no Stal mediador tiene su áyagar",
    }]}

    rels = _validate_global_relationships(parsed, catalog_fichas, summarized)
    assert len(rels) == 1, (
        "a fallback target must remain a valid relationship destination via "
        "the global catalog")


def test_source_is_limited_to_summarized_set():
    """Only summarized fichas may be a relationship SOURCE (need a summary)."""
    source_ok = _ficha("A", canonical_id="Mundo::A")
    source_no_summary = _ficha("B", canonical_id="Mundo::B")
    target = _ficha("C", canonical_id="Mundo::C")
    catalog_fichas = [source_ok, source_no_summary, target]

    summarized = [_with_summary(source_ok, "resumen"), _with_summary(target, "resumen")]
    parsed = {"relationships": [
        {"id": "r1", "source_candidate_id": source_ok.candidate_id,
         "target_canonical_id": "Mundo::C", "relationship_type": "relacionado-con",
         "confidence": 0.9, "evidence": "e"},
        {"id": "r2", "source_candidate_id": source_no_summary.candidate_id,
         "target_canonical_id": "Mundo::C", "relationship_type": "relacionado-con",
         "confidence": 0.9, "evidence": "e"},
    ]}
    rels = _validate_global_relationships(parsed, catalog_fichas, summarized)
    src_ids = {r.source_candidate_id for r in rels}
    assert source_ok.candidate_id in src_ids, "summarized source should be allowed"
    assert source_no_summary.candidate_id not in src_ids, (
        "a fallback ficha cannot be a relationship source (no summary to reason over)")


def test_catalog_is_document_wide_not_lot_scoped():
    """The catalog includes every ficha of the document, across all chunks."""
    chunk0 = [_ficha(f"A{i}", canonical_id=f"Chunk0::{i}") for i in range(3)]
    chunk1 = [_ficha(f"G{i}", canonical_id=f"Chunk1::{i}") for i in range(3)]
    chunk2 = [_ficha(f"Z{i}", canonical_id=f"Chunk2::{i}") for i in range(3)]
    all_fichas = chunk0 + chunk1 + chunk2
    catalog_keys = {_canonical_key(c) for c in all_fichas}
    assert len(catalog_keys) == 9, "catalog must cover the whole document"


def test_global_catalog_is_small_enough_for_a_single_call():
    """Guards the feasibility premise: ids+display catalog is tiny (≈1.1k tok @ 3.5 chars/tok)."""
    fichas = [_ficha(f"F{i}", canonical_id=f"Doc::Seccion::Ficha {i}") for i in range(200)]
    catalog_txt = "\n".join(f"{c.canonical_id}|{c.display_title}" for c in fichas)
    tokens = len(catalog_txt) / 3.5
    assert tokens < 3000, f"catalog too big ({int(tokens)} tok) for a single call"
