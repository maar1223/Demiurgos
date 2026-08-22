# -*- coding: utf-8 -*-
"""World importer — byte-budget chunking invariant tests.

PURPOSE (issue: fichas en ``fallback``/``respaldo`` en el importador
auto-frontmatter): el funnel trocea por CANTIDAD (``_FUNNEL_CHUNK_SIZE = 12``),
no por tamaño. Un chunk de 12 fichas grandes (ej. 72,136 chars) desborda el
presupuesto de salida de Hermes, que trunca la respuesta y deja a las últimas
fichas del lote sin resumen -> ``fallback`` (el 9no Stal – Mediador, siendo
estructuralmente idéntico al 8vo, cae porque es el ÚLTIMO del chunk).

La mitigación propuesta trocea por PRESUPUESTO DE BYTES: acumular fichas
COMPLETAS hasta un tope (~20k chars). Estos tests demuestran la INVARIANTE
central de ese diseño, SIN tocar todavía el funnel de producción:

    INVARIANTE: el body de una ficha NUNCA se divide entre dos lotes.
    - cada ficha aparece en exactamente UN lote, con su ``content_preview``
      íntegro (idéntico al original, byte a byte);
    - ninguna ficha se pierde ni se duplica;
    - un lote no excede el tope, SALVO cuando una sola ficha lo supera
      (esa ficha va sola en su lote, completa, nunca cortada).

Nota: el ``content_preview`` es preservation-first (el body NUNCA se recorta).
Estos tests NO recortan contenido; solo agrupan fichas ya completas.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_TOOLS = _HERE.parents[2]
for _p in (str(_WIKI), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_models import Candidate, Provenance  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


def _ficha(
    identity: str,
    *,
    body_length: int = 120,
    canonical_id: str | None = None,
) -> Candidate:
    """Build one complete-ficha candidate with a body of exactly ``body_length``.

    The body is deterministic and includes the identity so we can assert it is
    never split, reordered, or dropped.
    """
    cid = canonical_id or identity
    body = (f"# {identity}\n" + (f"{identity}: " * max(1, body_length // (len(identity) + 2))))[:body_length]
    # Force exact length so byte-budget math is deterministic.
    body = (body + ("x" * body_length))[:body_length]
    return Candidate(
        candidate_id=uuid.uuid4().hex,
        job_id="job-bytes",
        world="world1",
        normalized_identity=cid,
        canonical_id=cid,
        display_title=identity,
        source_hash=f"sha256:{cid}",
        provenance=Provenance(
            source_path=f"lore/{identity}.md",
            source_kind="loose",
            source_hash=f"sha256:{cid}",
        ),
        content_preview=body,
        size_bytes=body_length,
    )


def _byte_chunk_by_budget(
    candidates: list[Candidate],
    budget_chars: int = 20000,
) -> list[list[Candidate]]:
    """Proposed byte-budget chunking: accumulate COMPLETE fichas up to ``budget``.

    A single ficha that alone exceeds the budget still goes in its own chunk
    COMPLETE (never truncated). This mirrors the intended production helper.
    """
    chunks: list[list[Candidate]] = []
    current: list[Candidate] = []
    current_chars = 0
    for cand in candidates:
        chunk_chars = len(cand.content_preview or "")
        if current and current_chars + chunk_chars > budget_chars:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(cand)
        current_chars += chunk_chars
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# INVARIANT: fichas completas nunca se dividen entre lotes
# ---------------------------------------------------------------------------


def test_byte_chunking_never_splits_a_ficha_body():
    """A ficha's ``content_preview`` must appear byte-identical in exactly one chunk."""
    fichas = [_ficha(f"Ficha {i}", body_length=500) for i in range(8)]
    chunks = _byte_chunk_by_budget(fichas, budget_chars=2500)

    seen_ids: set[str] = set()
    for chunk in chunks:
        for cand in chunk:
            assert cand.candidate_id not in seen_ids, "duplicated across chunks"
            seen_ids.add(cand.candidate_id)
            # The body is intact — identical to the original candidate.
            original = next(f for f in fichas if f.candidate_id == cand.candidate_id)
            assert cand.content_preview == original.content_preview, "body was altered/split"
            assert len(cand.content_preview) == original.size_bytes
    assert seen_ids == {f.candidate_id for f in fichas}, "a ficha was dropped"


def test_byte_chunking_respects_budget_except_oversized_single_ficha():
    """No chunk exceeds the budget unless one ficha alone already exceeds it.

    When an oversized ficha exceeds the budget, it goes COMPLETE and alone.
    """
    big = _ficha("Ficha Gigante", body_length=30000)          # > budget
    small = [_ficha(f"Ficha {i}", body_length=800) for i in range(6)]
    fichas = [big, *small]
    chunks = _byte_chunk_by_budget(fichas, budget_chars=20000)

    # The oversized ficha is never split across chunks and never truncated.
    big_chunk = next(ch for ch in chunks if any(
        c.canonical_id == "Ficha Gigante" for c in ch))
    assert len(big_chunk) == 1, "oversized ficha should be alone"
    assert big_chunk[0].content_preview == big.content_preview, "oversized body truncated"

    # The remaining small fichas fit within budget in their own chunks (or one).
    for chunk in chunks:
        if any(c.canonical_id == "Ficha Gigante" for c in chunk):
            continue
        total = sum(len(c.content_preview or "") for c in chunk)
        assert total <= 20000, f"chunk exceeded budget: {total}"


def test_byte_chunking_preserves_order_and_completeness():
    """Chunks + fichas keep source order; the union is the full input set."""
    fichas = [_ficha(f"Ficha {i}", body_length=450) for i in range(20)]
    chunks = _byte_chunk_by_budget(fichas, budget_chars=2000)

    flat = [c for chunk in chunks for c in chunk]
    assert [c.canonical_id for c in flat] == [f.canonical_id for f in fichas], "order changed"
    assert len(flat) == len(fichas), "fichas lost"


def test_byte_chunking_empty_input_returns_no_chunks():
    """An empty candidate list yields no chunks (no crash, no phantom batch)."""
    assert _byte_chunk_by_budget([], budget_chars=20000) == []


def test_current_count_chunking_does_NOT_bound_bytes():
    """REGRESSION GUARD — proves the current design is why fichas fall back.

    The current funnel chunks by fixed COUNT (``_FUNNEL_CHUNK_SIZE = 12``). An
    import with 52 fichas of ~1.5-3.5k chars each produces a first chunk that is
    BOTH many fichas AND tens of thousands of chars — which is what makes Hermes
    truncate the tail of the batch. This documents the bug; it is not the fix.
    """
    # Simulate the real import shape: 52 fichas, some large.
    fichas = [
        _ficha(f"Ficha {i}", body_length=(2000 if i % 3 != 0 else 9000))
        for i in range(52)
    ]
    # Current behavior: fixed 12-count chunks.
    current_chunks = [fichas[i:i + 12] for i in range(0, len(fichas), 12)]
    first_chunk_chars = sum(len(c.content_preview or "") for c in current_chunks[0])
    # ~12 fichas, many 9k chars -> the first chunk is huge (way over 20k).
    assert first_chunk_chars > 20000, (
        "expected the current count-based first chunk to exceed a sane "
        "byte budget (this is precisely the truncation trigger)")
