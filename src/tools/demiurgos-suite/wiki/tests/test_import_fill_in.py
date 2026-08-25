# -*- coding: utf-8 -*-
"""World importer — enrichment funnel: summary fill-in + relationship reach.

ISSUE (fichas en ``fallback``/``respaldo``): el funnel trocea por CANTIDAD
(``_FUNNEL_CHUNK_SIZE = 12``), y cuando Hermes corta la respuesta del Paso 2
(resúmenes), las fichas al final del lote quedan SIN resumen. Por diseño del
funnel, una ficha sin resumen:

  * NO entra a ``summarized``;
  * por tanto NO participa del Paso 3 (relaciones);
  * por tanto NO participa del Paso 4 (frontmatter) -> ``fallback``.

CONSECUENCIA PARA LAS RELACIONES (lo que no se había visto): ``validate_relationship_batch``
construye ``by_canonical``/``by_candidate`` SOLO con las fichas ``summarized``
del chunk. Si una ficha queda en ``fallback``:
  - no puede ser FUENTE de una relación (no está en el lote del Paso 3);
  - las relaciones que APUNTAN a ella como destino se rechazan ("ungrounded")
    porque su canonical_id no está en el set de validación.

Esto significa que el fallback no solo pierde el frontmatter: ROMPE el grafo
de relaciones alrededor de esa ficha. Un ficha "incompleta" arrastra a sus
vecinas (no puede ser referenciada).

Estos tests validan la propuesta de RELLENO (fill-in de resúmenes): tras
rellenar, todas las fichas del chunk tienen resumen, participan del Paso 3, y
las relaciones del chunk se capturan igual que antes. Los tests NO tocan el
funnel de producción: implementan el relleno como helper y verifican la
INVARIANTE que queremos garantizar antes de migrar.
"""

from __future__ import annotations

import inspect
import json
import sys
import uuid
from importlib import import_module
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_TOOLS = _HERE.parents[2]
for _p in (str(_WIKI), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_models import Candidate, Provenance  # noqa: E402


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _ficha(
    identity: str,
    *,
    body: str | None = None,
    canonical_id: str | None = None,
) -> Candidate:
    cid = canonical_id or identity
    text = body or f"Cuerpo denso de {identity} con contexto suficiente para resumir."
    return Candidate(
        candidate_id=uuid.uuid4().hex,
        job_id="job-fill",
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
        content_preview=text,
        size_bytes=len(text),
    )


# ---------------------------------------------------------------------------
# Reused production helpers (read-only; import, don't reimplement)
# ---------------------------------------------------------------------------

_enrichment = import_module("import_enrichment")
build_summary_prompt = _enrichment.build_summary_prompt
build_relationship_batch_prompt = _enrichment.build_relationship_batch_prompt
validate_relationship_batch = _enrichment.validate_relationship_batch
_summary_budget_for_step2 = getattr(_enrichment, "_FUNNEL_CHUNK_SIZE", 12)


def _copy_candidate(candidate: Candidate, **overrides: Any) -> Candidate:
    """Copy a Candidate applying overrides (mirror of ``_copy_candidate``)."""
    data = candidate.model_dump()
    data.update(overrides)
    return Candidate(**data)


# ---------------------------------------------------------------------------
# Proposed helper: fill-in of missing summaries within one chunk
# ---------------------------------------------------------------------------


def _fill_missing_summaries(
    candidates: list[Candidate],
    hermes_runner: Callable[[str, str], str],
    session_id: str,
    fill_group_size: int = 4,
) -> dict[str, str]:
    """Run Step 2 and fill any candidate the runner omitted.

    Strategy (fail-open): first ask for the whole chunk's summaries, then for
    every candidate that came back WITHOUT a summary, re-ask in small groups
    (``fill_group_size``) so a single truncated/large response cannot drop a
    ficha again. Returns ``{candidate_id: summary}`` for every candidate that
    eventually produced one. Never raises: a candidate the model genuinely
    cannot summarize stays missing (that candidate falls back, but the rest
    keep their relationships — see the relationship-reach tests).
    """
    summaries: dict[str, str] = {}

    def _ask(group: list[Candidate]) -> dict[str, str]:
        raw = hermes_runner(
            json.dumps(build_summary_prompt(group), ensure_ascii=False),
            session_id,
        )
        return _enrichment.parse_summary_response(raw or "")

    # First pass: whole chunk.
    summaries.update(_ask(candidates))
    missing = [c for c in candidates
               if not summaries.get(c.candidate_id)]
    # Fill-in passes: small groups, up to a bounded number of rounds. A round
    # that recovers ZERO new summaries stops the loop early — a runner that
    # keeps returning the same non-productive response (the observed "same
    # candidates, identical JSON" loop) would otherwise burn every round.
    rounds = 0
    while missing and rounds < 5:
        rounds += 1
        before = len(summaries)
        for start in range(0, len(missing), fill_group_size):
            group = missing[start:start + fill_group_size]
            summaries.update(_ask(group))
        if len(summaries) == before:
            break
        missing = [c for c in candidates
                   if not summaries.get(c.candidate_id)]
    return summaries


# ---------------------------------------------------------------------------
# INVARIANT: fill-in restores every ficha that would otherwise be fallback
# ---------------------------------------------------------------------------


def _truncating_runner(cut_off: int) -> Callable[[str, str], str]:
    """A runner that only summarizes the first ``cut_off`` candidates per call.

    On the SECOND call (fill-in, small group) it summarizes fully — modelling
    a Hermes that truncates large batches but succeeds on small ones.
    """
    calls = {"n": 0}

    def runner(prompt: str, _session: str) -> str:
        data = json.loads(prompt)
        cands = data["candidates"]
        calls["n"] += 1
        if calls["n"] == 1 and len(cands) > cut_off:
            cands = cands[:cut_off]
        return json.dumps({"summaries": [
            {"candidate_id": c["candidate_id"],
             "summary": f"Resumen denso de {c['display_title']}."}
            for c in cands]})

    return runner


def test_fill_in_recovers_every_ficha_a_truncating_batch_dropped():
    """A truncated Step 2 that drops the tail fichas is healed by fill-in."""
    fichas = [_ficha(f"Ficha {i}", body=f"Contenido determinista de {i}.") for i in range(12)]
    runner = _truncating_runner(cut_off=9)  # drops the last 3 on the big call
    session = "job-fill"
    summaries = _fill_missing_summaries(fichas, runner, session)

    # Every ficha, including the 3 the big call dropped, has a summary now.
    for c in fichas:
        assert summaries.get(c.candidate_id), f"ficha {c.display_title} still missing"


def test_fill_in_only_asks_group_for_candidates_without_summary():
    """The fill-in round only re-asks the missing candidates (small group)."""
    seen_sizes: list[int] = []

    def runner(prompt: str, _session: str) -> str:
        data = json.loads(prompt)
        cands = data["candidates"]
        seen_sizes.append(len(cands))
        if len(cands) == 12:
            # Big call: summarize only the first 8.
            cands = cands[:8]
        return json.dumps({"summaries": [
            {"candidate_id": c["candidate_id"],
             "summary": f"Resumen de {c['display_title']}."}
            for c in cands]})

    fichas = [_ficha(f"Ficha {i}") for i in range(12)]
    _fill_missing_summaries(fichas, runner, "job")
    # First big call (12), then small fill-in groups of the 4 missing.
    assert seen_sizes[0] == 12
    assert all(s <= 4 for s in seen_sizes[1:]), f"fill group too big: {seen_sizes}"


# ---------------------------------------------------------------------------
# CONSEQUENCE: relationships need every ficha present in the Step 3 batch
# ---------------------------------------------------------------------------


def test_relationship_reach_is_broken_when_a_ficha_is_fallback():
    """A ficha left out of ``summarized`` cannot be a relationship target.

    This documents the bug: ``validate_relationship_batch`` grounds targets
    ONLY against the ``summarized`` set. If the target ficha is fallback, a
    relationship whose ``target_canonical_id`` points at it is rejected, so
    the surrounding ficha ALSO loses its link. Fill-in prevents this.
    """
    # Two fichas; one with a summary, one without (simulating fallback).
    a = _ficha("A", canonical_id="Mundo::A")
    b = _ficha("B", canonical_id="Mundo::B")

    # Sanity: with BOTH summarized, an A->B relationship grounds fine.
    both = [_copy_candidate(a, summary="sum a"), _copy_candidate(b, summary="sum b")]
    parsed = {"relationships": [{
        "id": "r1",
        "source_candidate_id": a.candidate_id,
        "target_canonical_id": "Mundo::B",
        "relationship_type": "relacionado-con",
        "confidence": 0.9,
        "evidence": "mencionado",
    }]}
    rels_ok = validate_relationship_batch(parsed, both)
    assert len(rels_ok) == 1, "expected A->B to ground when B is summarized"

    # Now drop B from the batch (B is fallback -> not summarized).
    only_a = [_copy_candidate(a, summary="sum a")]
    rels_dropped = validate_relationship_batch(parsed, only_a)
    assert rels_dropped == [], (
        "BUG: a relationship to a fallback ficha is silently dropped — "
        "fill-in must restore B so Step 3 sees it")


def test_fill_in_restores_relationship_reach_for_whole_chunk():
    """After fill-in, every chunk ficha is in the Step 3 batch and relationships ground.

    Simulates the real funnel: Step 2 truncates the tail, fill-in heals it,
    then Step 3 runs over the complete set and the A->B link survives.
    """
    fichas = [_ficha(f"Ficha {i}", canonical_id=f"Chunk::{i}") for i in range(6)]
    runner = _truncating_runner(cut_off=3)  # drops last 3 on big call
    session = "job-fill"
    summaries = _fill_missing_summaries(fichas, runner, session)

    # The full chunk is now summarizable -> all fichas enter Step 3.
    summarized = [_copy_candidate(c, summary=summaries[c.candidate_id])
                  for c in fichas if summaries.get(c.candidate_id)]
    assert len(summarized) == len(fichas), "fill-in left a ficha out of Step 3"

    # A relationship from the last (previously dropped) ficha to the first grounds.
    src = summarized[-1]
    tgt = summarized[0]
    parsed = {"relationships": [{
        "id": "r2",
        "source_candidate_id": src.candidate_id,
        "target_canonical_id": tgt.canonical_id,
        "relationship_type": "relacionado-con",
        "confidence": 0.9,
        "evidence": "mencionado",
    }]}
    rels = validate_relationship_batch(parsed, summarized)
    assert len(rels) == 1, (
        "after fill-in the previously-dropped ficha must be usable as a "
        "relationship source/target")


def test_no_fill_needed_when_runner_completes():
    """Happy path: no fill-in calls are made when Step 2 completes fully."""
    calls = {"big": 0, "small": 0}

    def runner(prompt: str, _session: str) -> str:
        data = json.loads(prompt)
        cands = data["candidates"]
        if len(cands) > 4:
            calls["big"] += 1
        else:
            calls["small"] += 1
        return json.dumps({"summaries": [
            {"candidate_id": c["candidate_id"],
             "summary": f"Resumen de {c['display_title']}."}
            for c in cands]})

    fichas = [_ficha(f"Ficha {i}") for i in range(6)]
    _fill_missing_summaries(fichas, runner, "job")
    assert calls["big"] == 1
    assert calls["small"] == 0, "fill-in should be no-op on the happy path"


def test_fill_in_stops_when_round_recovers_nothing_new():
    """A non-productive round (same repeated response) must not burn all rounds.

    Reproduces the observed prod loop: a runner that answers "same candidates,
    identical JSON" — i.e. keeps returning summaries already captured by a
    prior round and never fills the remaining fichas. The no-progress guard
    breaks out after the first dead round instead of re-asking up to 5 times.
    """
    calls = {"n": 0}
    fichas = [_ficha(f"Ficha {i}") for i in range(6)]
    # The one summary the runner "knows": the first ficha's id, already
    # captured by the initial pass. Every re-ask returns THIS same id — the
    # observed "identical JSON" refusal to fill the remaining fichas.
    known_id = fichas[0].candidate_id

    def runner(prompt: str, _session: str) -> str:
        calls["n"] += 1
        return json.dumps({"summaries": [
            {"candidate_id": known_id, "summary": f"Stub resumen de {known_id}."}]})

    summaries = _fill_missing_summaries(fichas, runner, "job")

    # The guard cut the loop after the first dead round: 1 initial pass + 2
    # fill-in calls (5 missing -> groups of 4 => 2 groups) that added nothing.
    # WITHOUT the guard this would burn one round per missing group up to 5
    # rounds (~10+ calls). Assert we stopped well short of that.
    assert calls["n"] <= 3, (
        f"non-productive fill-in burned {calls['n']} calls; expected <=3")
    # Only the one ficha the runner actually summarized is captured.
    assert len(summaries) == 1, f"expected only the single returned summary, got {len(summaries)}"
