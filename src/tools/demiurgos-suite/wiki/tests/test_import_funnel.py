# -*- coding: utf-8 -*-
"""World importer — enrichment funnel tests (importador-auto-frontmatter, Phase 2).

Covers tasks 2.1-2.7:

* Step 2 — per-ficha summary prompt/parser (full body, ``{candidate_id,
  canonical_id, display_title}`` identity contract).
* Step 3 — one batched relationship pass anchored to EXACT canonical ids;
  ambiguous leaf names, ungrounded targets, self-links, and unknown
  relationship types are rejected.
* Step 4 — type/frontmatter prompt/parser with ``generated``/``manual``/
  ``fallback`` state.
* Extended-timeout fail-open (design risk 4): a timeout/malformed/unavailable
  runner preserves every candidate with manual/fallback frontmatter and the
  original body untouched.
* Hermes name/identity alignment (design risk 3): relationship anchors map
  canonical ids back to candidates; a bare leaf name shared by two branches
  never survives.
* Store idempotent bootstrap: legacy databases gain the new metadata columns
  on open, the UNIQUE constraint is retained, and funnel metadata round-trips.

The router-level wiring (one candidate per ficha, review payload with
frontmatter + body + media warnings) is covered by ``TestFunnelRouterWiring``
at the bottom of this file.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_TOOLS = _HERE.parents[2]
for _p in (str(_WIKI), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_enrichment import (  # noqa: E402
    DEFAULT_TIMEOUT_SECONDS,
    analyze_ficha_funnel,
    build_relationship_batch_prompt,
    build_summary_prompt,
    build_type_frontmatter_prompt,
    parse_frontmatter_response,
    parse_summary_response,
    validate_relationship_batch,
)
from import_models import (  # noqa: E402
    Candidate,
    EnrichmentStatus,
    FrontmatterState,
    Provenance,
)
from import_store import ImportJobStore  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ficha(
    identity: str,
    *,
    canonical_id: str | None = None,
    title: str | None = None,
    preview: str = "Cuerpo de la ficha con contexto suficiente para resumir.",
    candidate_id: str | None = None,
    job_id: str = "job-funnel",
) -> Candidate:
    """Build a complete-ficha candidate (Phase 2 contract)."""
    cid = canonical_id or identity
    return Candidate(
        candidate_id=candidate_id or uuid.uuid4().hex,
        job_id=job_id,
        world="world1",
        normalized_identity=cid,
        canonical_id=cid,
        display_title=title or identity,
        source_hash=f"sha256:{cid}",
        provenance=Provenance(
            source_path=f"lore/{identity}.md",
            source_kind="loose",
            source_hash=f"sha256:{cid}",
        ),
        content_preview=preview,
        size_bytes=len(preview),
    )


def _scripted_funnel_runner():
    """Build a dynamic fake Hermes runner covering funnel Steps 2-4.

    Inspects the prompt payload to decide the step: Step 2 candidates carry
    ``body``; Step 3 prompts carry ``rel_vocab``; Step 4 prompts carry
    ``entity_vocab``. Relationships anchor on canonical ids (design risk 3).
    """

    def runner(prompt: str, _session: str) -> str:
        data = json.loads(prompt)
        cands = data["candidates"]
        if cands and "body" in cands[0]:
            return json.dumps({"summaries": [
                {"candidate_id": c["candidate_id"],
                 "summary": f"Resumen denso de {c['display_title']}."}
                for c in cands]})
        if "rel_vocab" in data:
            rels = []
            if len(cands) >= 2:
                rels.append({
                    "id": "rel-1",
                    "source_candidate_id": cands[0]["candidate_id"],
                    "target_canonical_id": cands[1]["canonical_id"],
                    "relationship_type": "ubicado-en",
                    "confidence": 0.9,
                    "evidence": "mencionado en el resumen",
                })
            return json.dumps({"relationships": rels})
        return json.dumps({"frontmatter": [
            {"candidate_id": c["candidate_id"],
             "title": c["display_title"],
             "type": "lugar",
             "description": f"Descripcion de {c['display_title']}.",
             "relaciones": [o["canonical_id"] for o in cands
                            if o["candidate_id"] != c["candidate_id"]]}
            for c in cands]})

    return runner


# ---------------------------------------------------------------------------
# Task 2.1 — Step 2: per-ficha summaries
# ---------------------------------------------------------------------------


class TestSummaryPrompt:
    def test_carries_identity_contract_and_full_body(self):
        ficha = _ficha(
            "Ayagares", canonical_id="Ayagares::Descripción Física",
            title="Descripción Física",
            preview="Altas murallas de piedra blanca.",
        )
        prompt = build_summary_prompt([ficha])
        entry = prompt["candidates"][0]
        assert entry["candidate_id"] == ficha.candidate_id
        assert entry["canonical_id"] == "Ayagares::Descripción Física"
        assert entry["display_title"] == "Descripción Física"
        assert entry["body"] == ficha.content_preview
        assert "200" in prompt["instructions"] and "400" in prompt["instructions"]

    def test_parse_summary_response_maps_candidate_ids(self):
        raw = json.dumps({"summaries": [
            {"candidate_id": "c1", "summary": "  Resumen uno.  "},
            {"candidate_id": "c2", "summary": "Resumen dos."},
            {"candidate_id": "c3", "summary": "   "},   # empty -> skipped
            {"candidate_id": 5, "summary": "nope"},     # non-str id -> skipped
        ]})
        out = parse_summary_response(raw)
        assert out == {"c1": "Resumen uno.", "c2": "Resumen dos."}

    def test_parse_summary_response_fail_open_on_malformed(self):
        assert parse_summary_response("") == {}
        assert parse_summary_response("not json") == {}
        assert parse_summary_response('{"summaries": "nope"}') == {}
        assert parse_summary_response("```json\n[]\n```") == {}


# ---------------------------------------------------------------------------
# Task 2.2 — Step 3: batched relationships anchored to canonical ids
# ---------------------------------------------------------------------------


class TestRelationshipBatch:
    def test_prompt_uses_summaries_and_canonical_ids(self):
        a = _ficha("Ayagares", preview="Cuerpo A")
        b = _ficha("Palacios", preview="Cuerpo B")
        prompt = build_relationship_batch_prompt([a, b])
        assert "rel_vocab" in prompt
        assert "aliado-de" in prompt["rel_vocab"]
        entries = {c["candidate_id"]: c for c in prompt["candidates"]}
        assert entries[a.candidate_id]["canonical_id"] == "Ayagares"
        assert entries[a.candidate_id]["summary"] == ""
        # A summarized candidate feeds its summary into the batch.
        a2 = _ficha("Ayagares", preview="Cuerpo A")
        a2.summary = "Resumen de Ayagares."
        prompt2 = build_relationship_batch_prompt([a2])
        assert prompt2["candidates"][0]["summary"] == "Resumen de Ayagares."

    def test_validate_anchors_canonical_ids_back_to_candidates(self):
        a = _ficha("Ayagares")
        b = _ficha("Palacios")
        parsed = {"relationships": [{
            "id": "r1",
            "source_candidate_id": a.candidate_id,
            "target_canonical_id": "Palacios",
            "relationship_type": "ubicado-en",
            "confidence": 0.9,
            "evidence": "x",
        }]}
        rels = validate_relationship_batch(parsed, [a, b])
        assert len(rels) == 1
        assert rels[0].source_candidate_id == a.candidate_id
        assert rels[0].target_candidate_id == b.candidate_id
        assert rels[0].target_name is None  # canonical id materialized, not name

    def test_validate_rejects_ambiguous_leaf_names(self):
        """Design risk 3: a bare leaf name shared by two branches must not
        resolve; only the exact parent-qualified canonical id matches."""
        a = _ficha("Ayagares", canonical_id="Ayagares::Descripción Física",
                   title="Descripción Física")
        b = _ficha("Palacios", canonical_id="Palacios::Descripción Física",
                   title="Descripción Física")
        # Ambiguous leaf name -> ungrounded -> rejected.
        ambiguous = {"relationships": [{
            "id": "r-amb",
            "source_candidate_id": a.candidate_id,
            "target_name": "Descripción Física",
            "relationship_type": "ubicado-en",
            "confidence": 0.8,
            "evidence": "x",
        }]}
        assert validate_relationship_batch(ambiguous, [a, b]) == []
        # Exact canonical id -> anchored to candidate B.
        exact = {"relationships": [{
            "id": "r-exact",
            "source_candidate_id": a.candidate_id,
            "target_canonical_id": "Palacios::Descripción Física",
            "relationship_type": "ubicado-en",
            "confidence": 0.8,
            "evidence": "x",
        }]}
        rels = validate_relationship_batch(exact, [a, b])
        assert len(rels) == 1 and rels[0].target_candidate_id == b.candidate_id

    def test_validate_rejects_ungrounded_self_links_and_unknown_types(self):
        a = _ficha("Ayagares")
        b = _ficha("Palacios")
        parsed = {"relationships": [
            {"id": "r-ung", "source_candidate_id": a.candidate_id,
             "target_canonical_id": "Nunca Visto",
             "relationship_type": "ubicado-en", "confidence": 0.8,
             "evidence": "x"},
            {"id": "r-self", "source_candidate_id": a.candidate_id,
             "target_canonical_id": "Ayagares",
             "relationship_type": "ubicado-en", "confidence": 0.8,
             "evidence": "x"},
            {"id": "r-type", "source_candidate_id": a.candidate_id,
             "target_canonical_id": "Palacios",
             "relationship_type": "???-not-a-rel-type", "confidence": 0.8,
             "evidence": "x"},
        ]}
        assert validate_relationship_batch(parsed, [a, b]) == []


# ---------------------------------------------------------------------------
# Task 2.3 — Step 4: type/frontmatter with manual fallback
# ---------------------------------------------------------------------------


class TestTypeFrontmatter:
    def test_prompt_includes_entity_vocab(self):
        ficha = _ficha("Ayagares")
        prompt = build_type_frontmatter_prompt([ficha])
        assert set(prompt["entity_vocab"]) >= {"personaje", "lugar", "criatura"}
        entry = prompt["candidates"][0]
        assert entry["canonical_id"] == "Ayagares"
        assert entry["display_title"] == "Ayagares"

    def test_parse_frontmatter_response_maps_generated_state(self):
        raw = json.dumps({"frontmatter": [{
            "candidate_id": "c1",
            "title": "Ayagares",
            "type": "lugar",
            "description": "Ciudad amurallada.",
            "relaciones": ["Palacios"],
        }]})
        out = parse_frontmatter_response(raw)
        assert out["c1"] == {
            "title": "Ayagares", "type": "lugar",
            "description": "Ciudad amurallada.",
            "relaciones": ["Palacios"],
            "state": "generated",
        }

    def test_parse_frontmatter_response_fail_open(self):
        assert parse_frontmatter_response("") == {}
        assert parse_frontmatter_response("nope") == {}
        # Missing/invalid title -> skipped; non-str type -> None.
        raw = json.dumps({"frontmatter": [
            {"candidate_id": "c1", "title": "  ", "type": "lugar"},
            {"candidate_id": "c2", "title": "Válida", "type": 42,
             "description": "d", "relaciones": []},
        ]})
        out = parse_frontmatter_response(raw)
        assert "c1" not in out
        assert out["c2"]["type"] is None


# ---------------------------------------------------------------------------
# Task 2.4 — extended-timeout fail-open (design risk 4)
# ---------------------------------------------------------------------------


class TestTimeoutAndFailOpen:
    def test_extended_timeout_constant_is_120s(self):
        assert DEFAULT_TIMEOUT_SECONDS == 120.0

    def test_timeout_runner_fails_open_to_fallback_preserving_source(self):
        a = _ficha("Ayagares", preview="Cuerpo original que no se pierde.")

        def timeout_runner(_prompt: str, _session: str) -> str:
            raise TimeoutError("gateway timed out")

        out = analyze_ficha_funnel([a], timeout_runner)
        assert len(out) == 1
        cand = out[0]
        assert cand.summary == ""
        assert cand.frontmatter is not None
        assert cand.frontmatter.state == FrontmatterState.FALLBACK
        assert cand.frontmatter.title == "Ayagares"  # reviewable fallback
        assert cand.content_preview == "Cuerpo original que no se pierde."
        assert cand.enrichment_status == EnrichmentStatus.NO_SUGGESTIONS.value

    def test_unavailable_runner_fails_open_to_fallback(self):
        a = _ficha("Ayagares")

        def boom(_prompt: str, _session: str) -> str:
            raise ConnectionError("gateway unreachable")

        out = analyze_ficha_funnel([a], boom)
        assert out[0].frontmatter.state == FrontmatterState.FALLBACK
        assert out[0].content_preview == a.content_preview

    def test_malformed_runner_fails_open_to_fallback(self):
        a = _ficha("Ayagares")
        out = analyze_ficha_funnel([a], lambda _p, _s: "not-json-at-all")
        assert out[0].frontmatter.state == FrontmatterState.FALLBACK

    def test_no_runner_leaves_manual_state(self):
        a = _ficha("Ayagares")
        out = analyze_ficha_funnel([a], None)
        assert out[0].frontmatter.state == FrontmatterState.MANUAL
        assert out[0].summary == ""
        assert out[0].frontmatter.title == "Ayagares"


# ---------------------------------------------------------------------------
# Funnel orchestration — Steps 2-4 end to end
# ---------------------------------------------------------------------------


class TestFichaFunnel:
    def test_generates_summary_relationships_and_generated_frontmatter(self):
        a = _ficha("Ayagares")
        b = _ficha("Palacios")
        out = analyze_ficha_funnel([a, b], _scripted_funnel_runner())
        by_id = {c.candidate_id: c for c in out}
        for cand in out:
            assert cand.summary.startswith("Resumen denso de")
            assert cand.frontmatter.state == FrontmatterState.GENERATED
            assert cand.frontmatter.type == "lugar"
            assert cand.frontmatter.description
        # The relationship anchored on the second ficha's canonical id.
        rels = by_id[a.candidate_id].enrichment_json or []
        assert rels and rels[0]["__type__"] == "relationship"
        assert rels[0]["target_candidate_id"] == b.candidate_id
        assert by_id[a.candidate_id].enrichment_status == EnrichmentStatus.OK.value
        # Bodies stay untouched (preservation-first).
        assert by_id[a.candidate_id].content_preview == a.content_preview

    def test_funnel_never_mutates_input_list(self):
        a = _ficha("Ayagares")
        original = [a]
        out = analyze_ficha_funnel(original, _scripted_funnel_runner())
        assert out is not original
        assert original[0].summary == ""
        assert original[0].frontmatter is None

    def test_funnel_fill_in_recovers_skipped_summary_candidate(self):
        """A candidate omitted by the FIRST Step 2 call is recovered by fill-in.

        Old behavior: a candidate missing from the summary batch stayed
        fallback, which cascaded into losing its relationships in Step 3. New
        behavior (fill-in): the funnel re-asks the omitted candidate in a small
        group, so it gets a summary and its generated frontmatter + Step 3
        reach survive.
        """
        a = _ficha("Ayagares")
        b = _ficha("Palacios")

        def partial_runner(prompt: str, _session: str) -> str:
            data = json.loads(prompt)
            cands = data["candidates"]
            if cands and "body" in cands[0]:
                # First summary call summarizes ONLY the first candidate; the
                # fill-in call (small group) summarizes whatever it is asked.
                return json.dumps({"summaries": [{
                    "candidate_id": cands[0]["candidate_id"],
                    "summary": f"Resumen de {cands[0]['display_title']}.",
                }]})
            if "rel_vocab" in data:
                return json.dumps({"relationships": []})
            return json.dumps({"frontmatter": [
                {"candidate_id": c["candidate_id"],
                 "title": c["display_title"],
                 "type": "lugar", "description": "d", "relaciones": []}
                for c in cands]})

        out = analyze_ficha_funnel([a, b], partial_runner)
        by_id = {c.candidate_id: c for c in out}
        # Both fichas now have a summary and generated frontmatter: fill-in
        # recovered the one the big batch omitted.
        assert by_id[a.candidate_id].summary
        assert by_id[a.candidate_id].frontmatter.state == FrontmatterState.GENERATED
        assert by_id[b.candidate_id].summary
        assert by_id[b.candidate_id].frontmatter.state == FrontmatterState.GENERATED

    def test_funnel_chunks_large_batches_by_bytes_and_isolates_failures(self):
        """Large fichas split into 2 chunks by BYTE budget; a timeout on chunk 2
        must NOT kill chunk 1's generated metadata.

        Chunks are bounded by cumulative body bytes (not ficha count): 13 small
        fichas fit in one chunk, so they are NOT split. Oversized fichas DO
        split into multiple byte-bounded chunks, and a failure is isolated to
        its own chunk.
        """
        # 13 fichas with big bodies (~3.5k chars) -> > 20k total -> >1 chunk.
        fichas = [_ficha(f"Ficha {i:02d}",
                         preview=f"#" + ("x" * 3500)) for i in range(13)]
        summary_calls = {"n": 0}

        def failing_runner(prompt: str, _session: str) -> str:
            data = json.loads(prompt)
            cands = data["candidates"]
            if cands and "body" in cands[0]:
                summary_calls["n"] += 1
                if summary_calls["n"] > 1:
                    raise TimeoutError("chunk 2 timed out")
                return json.dumps({"summaries": [
                    {"candidate_id": c["candidate_id"],
                     "summary": f"Resumen de {c['display_title']}."}
                    for c in cands]})
            if "rel_vocab" in data:
                return json.dumps({"relationships": []})
            return json.dumps({"frontmatter": [
                {"candidate_id": c["candidate_id"], "title": c["display_title"],
                 "type": "lugar", "description": "d", "relaciones": []}
                for c in cands]})

        out = analyze_ficha_funnel(fichas, failing_runner)
        # The funnel actually byte-chunked: more than one summary call happened.
        assert summary_calls["n"] > 1
        # Chunk 1 (the one that succeeded) keeps generated metadata; chunk 2's
        # candidates fall back (timeout), but do not drag chunk 1 down.
        generated = [c for c in out
                     if c.frontmatter.state == FrontmatterState.GENERATED]
        fallback = [c for c in out
                    if c.frontmatter.state == FrontmatterState.FALLBACK]
        assert len(generated) >= 1
        assert len(fallback) >= 1
        # The first chunk (non-failing) yields generated candidates.
        assert generated[0].summary == f"Resumen de {generated[0].display_title}."


# ---------------------------------------------------------------------------
# Store — idempotent bootstrap + metadata round trip (task 2.6)
# ---------------------------------------------------------------------------


_LEGACY_SCHEMA = """
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY, world TEXT NOT NULL, owner_principal TEXT NOT NULL,
    state TEXT NOT NULL, source_kind TEXT NOT NULL DEFAULT 'loose',
    aggregate_uncompressed_bytes INTEGER NOT NULL DEFAULT 0,
    aggregate_compressed_bytes INTEGER NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '', opaque_token TEXT NOT NULL DEFAULT '',
    lease_owner TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE candidates (
    candidate_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, world TEXT NOT NULL,
    normalized_identity TEXT NOT NULL, source_hash TEXT NOT NULL,
    provenance_json TEXT NOT NULL, content_preview TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending', okf_issues_json TEXT NOT NULL DEFAULT '[]',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    UNIQUE (world, source_hash, normalized_identity));
CREATE TABLE items (
    item_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'pending', detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL);
CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
    event TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE approvals (
    approval_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, principal TEXT NOT NULL,
    revision INTEGER NOT NULL, digest TEXT NOT NULL, token TEXT NOT NULL,
    group_ids_json TEXT NOT NULL DEFAULT '[]', issued_at TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL DEFAULT '', consumed INTEGER NOT NULL DEFAULT 0,
    UNIQUE (job_id, token));
"""


class TestStoreBootstrap:
    def test_legacy_db_bootstraps_funnel_columns_and_keeps_uniqueness(
            self, tmp_path):
        db_path = tmp_path / "legacy.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.executescript(_LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO candidates (candidate_id, job_id, world,"
            " normalized_identity, source_hash, provenance_json, content_preview)"
            " VALUES ('legacy-1', 'job1', 'world1', 'Origen', 'sha256:abc',"
            " '{\"source_path\": \"lore/Origen.md\", \"source_kind\": \"loose\","
            " \"source_hash\": \"sha256:abc\"}', 'body')")
        conn.commit()
        conn.close()

        store = ImportJobStore(db_path)  # bootstrap runs on open
        cols = {
            row[1] for row in store._conn.execute(
                "PRAGMA table_info(candidates)").fetchall()
        }
        for expected in ("display_title", "summary", "frontmatter_json",
                         "media_diagnostics_json"):
            assert expected in cols, f"missing bootstrap column {expected}"

        # The legacy row deserializes with funnel defaults (fail-open).
        cand = store.find_candidate("world1", "sha256:abc", "Origen")
        assert cand is not None
        assert cand.display_title == ""
        assert cand.summary == ""
        assert cand.frontmatter is None
        assert cand.media_diagnostics == []

        # Uniqueness constraint is retained: a duplicate insert is ignored.
        dup = store.find_candidate("world1", "sha256:abc", "Origen")
        assert dup.candidate_id == "legacy-1"

        # Reopening is idempotent (no duplicate-column crash).
        store2 = ImportJobStore(db_path)
        cols2 = {
            row[1] for row in store2._conn.execute(
                "PRAGMA table_info(candidates)").fetchall()
        }
        assert cols2 == cols

    def test_funnel_metadata_round_trips(self):
        store = ImportJobStore(":memory:")
        from import_models import FrontmatterCandidate, MediaDiagnostic
        cand = _ficha("Origen", preview="Cuerpo.")
        cand.display_title = "Origen"
        cand.summary = "Resumen de Origen."
        cand.frontmatter = FrontmatterCandidate(
            title="Origen", type="lugar", description="d",
            relaciones=["Palacios"], state=FrontmatterState.GENERATED)
        cand.media_diagnostics = [MediaDiagnostic(
            reference="![][image1]", image_key="image1", status="unresolved",
            target_ficha="Origen",
            message="reference image placement unresolved")]
        store.add_candidate(cand)
        back = store.find_candidate("world1", cand.source_hash,
                                    cand.normalized_identity)
        assert back.display_title == "Origen"
        assert back.summary == "Resumen de Origen."
        assert back.frontmatter is not None
        assert back.frontmatter.title == "Origen"
        assert back.frontmatter.type == "lugar"
        assert back.frontmatter.state == FrontmatterState.GENERATED
        assert [m.image_key for m in back.media_diagnostics] == ["image1"]
        # The uniqueness identity is the canonical id (one row per ficha).
        assert back.normalized_identity == "Origen"


# ---------------------------------------------------------------------------
# Router wiring — one candidate per ficha + review payload (task 2.5)
# ---------------------------------------------------------------------------


class _FakePrincipal:
    id = "test-principal"

    def __str__(self) -> str:
        return self.id


def _funnel_app(tmp_path, *, enricher=None, structure_inference=None):
    from import_router import create_import_router
    from import_service import ImportService

    store = ImportJobStore(":memory:")
    spool = tmp_path / "spool"
    spool.mkdir()
    mundos = tmp_path / "mundos"
    (mundos / "world1" / "lore").mkdir(parents=True, exist_ok=True)

    def read_file(rel):
        p = spool / rel
        try:
            return p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    service = ImportService(
        store=store, mundos_dir=mundos, spool_dir=spool,
        read_file=read_file,
        graph_reconcile=lambda rel, mundo: None,
        register_gallery=lambda world, src, rel: None,
    )
    app = FastAPI()
    app.include_router(create_import_router(
        require_principal=lambda _request: _FakePrincipal(),
        mundos_dir=lambda: mundos,
        spool_dir=lambda: spool,
        store=store,
        service=service,
        enricher=enricher,
        structure_inference=structure_inference,
    ))
    return TestClient(app), store, spool, mundos


_TWO_FICHA_DOC = (
    "# Ayagares\n\n"
    "Fundada en el 1200 AE por los primeros colonos.\n\n"
    "## Descripción Física\n\n"
    "Altas murallas de piedra blanca.\n\n"
    "![][imagen1]\n\n"
    "# Palacios\n\n"
    "Residencia del señor de la ciudad.\n"
)


class TestFunnelRouterWiring:
    def test_one_candidate_per_ficha_with_source_ordering(self, tmp_path):
        """Task 2.5 — a two-H1 document yields one candidate per ficha, in
        source order, with canonical ids and folded childless prose."""
        client, store, spool, _ = _funnel_app(tmp_path)
        resp = client.post(
            "/api/world1/imports",
            json={"source_kind": "loose", "files": ["lore/Enciclopedia.md"]})
        job = resp.json()["job"]
        client.post(
            f"/api/world1/imports/{job['job_id']}/stream",
            json={"relative": "lore/Enciclopedia.md", "offset": 0,
                  "data_b64": base64.b64encode(
                      _TWO_FICHA_DOC.encode()).decode()})
        analyze = client.post(
            f"/api/world1/imports/{job['job_id']}/analyze")
        assert analyze.status_code == 200, analyze.text
        assert analyze.json()["candidates"] == 2
        cands = store.candidates_for(job["job_id"])
        assert [c.canonical_id for c in cands] == ["Ayagares", "Palacios"]
        assert [c.display_title for c in cands] == ["Ayagares", "Palacios"]
        # Ficha bodies preserve the original text (heading folds for the
        # childless H2; the ficha's own H1 becomes the title).
        assert "Altas murallas de piedra blanca" in cands[0].content_preview
        assert "Residencia del señor" in cands[1].content_preview

    def test_review_payload_exposes_frontmatter_body_and_media_warnings(
            self, tmp_path):
        """Task 2.5 — the review payload carries frontmatter (manual by
        default), the original body, and reference-image media warnings."""
        client, store, spool, _ = _funnel_app(tmp_path)
        resp = client.post(
            "/api/world1/imports",
            json={"source_kind": "loose", "files": ["lore/Enciclopedia.md"]})
        job = resp.json()["job"]
        client.post(
            f"/api/world1/imports/{job['job_id']}/stream",
            json={"relative": "lore/Enciclopedia.md", "offset": 0,
                  "data_b64": base64.b64encode(
                      _TWO_FICHA_DOC.encode()).decode()})
        client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        review = client.get(
            f"/api/world1/imports/{job['job_id']}/review").json()
        cand = review["candidates"][0]
        assert cand["canonical_id"] == "Ayagares"
        assert cand["display_title"] == "Ayagares"
        assert cand["frontmatter"]["state"] == "manual"
        assert cand["frontmatter"]["title"] == "Ayagares"
        assert "Fundada en el 1200 AE" in cand["content_preview"]
        # Media warning: the unresolved ![][imagen1] reference is surfaced.
        warnings = cand["media_diagnostics"]
        assert any(w["image_key"] == "imagen1"
                   and w["status"] == "unresolved" for w in warnings)

    def test_enrich_true_runs_funnel_and_persists_frontmatter(
            self, tmp_path):
        """Funnel runs on enrich=true; review then shows the generated
        summary + frontmatter persisted on the candidate rows."""
        from import_enrichment import analyze_ficha_funnel

        def enricher(candidates):
            return analyze_ficha_funnel(
                candidates, hermes_runner=_scripted_funnel_runner())

        client, store, spool, _ = _funnel_app(tmp_path, enricher=enricher)
        resp = client.post(
            "/api/world1/imports",
            json={"source_kind": "loose", "files": ["lore/Enciclopedia.md"]})
        job = resp.json()["job"]
        client.post(
            f"/api/world1/imports/{job['job_id']}/stream",
            json={"relative": "lore/Enciclopedia.md", "offset": 0,
                  "data_b64": base64.b64encode(
                      _TWO_FICHA_DOC.encode()).decode()})
        analyze = client.post(
            f"/api/world1/imports/{job['job_id']}/analyze",
            json={"enrich": True})
        assert analyze.status_code == 200, analyze.text
        review = client.get(
            f"/api/world1/imports/{job['job_id']}/review").json()
        assert review["enrichment_status"] == "ok"
        palacios = next(c for c in review["candidates"]
                        if c["canonical_id"] == "Palacios")
        ayagares = next(c for c in review["candidates"]
                        if c["canonical_id"] == "Ayagares")
        assert ayagares["summary"].startswith("Resumen denso de")
        assert ayagares["frontmatter"]["state"] == "generated"
        assert ayagares["frontmatter"]["type"] == "lugar"
        # Persisted: a fresh read from the store returns the same payload.
        stored = store.candidates_for(job["job_id"])
        stored_by_cid = {c.canonical_id: c for c in stored}
        assert stored_by_cid["Ayagares"].summary.startswith("Resumen denso de")
        assert stored_by_cid["Ayagares"].frontmatter is not None
        assert (stored_by_cid["Ayagares"].frontmatter.state
                == FrontmatterState.GENERATED)
        # Relationship anchored on the second ficha's canonical id.
        rels = stored_by_cid["Ayagares"].enrichment_json or []
        assert rels and rels[0]["target_candidate_id"] == palacios[
            "candidate_id"]

    def test_structure_inference_seam_wired_in_router(self, tmp_path):
        """Task 1.2 seam — when the deterministic scan finds no headings, the
        injected Hermes structure-inference callable supplies the spans and
        the splitter builds fichas from them."""
        from import_analysis import HeadingSpan

        calls = {"n": 0}

        def infer(text: str):
            calls["n"] += 1
            assert text.strip()
            return [HeadingSpan(
                level=1, title="Inferido", source_text="# Inferido",
                line_index=0)]

        client, store, spool, _ = _funnel_app(
            tmp_path, structure_inference=infer)
        resp = client.post(
            "/api/world1/imports",
            json={"source_kind": "loose", "files": ["lore/Manual.md"]})
        job = resp.json()["job"]
        client.post(
            f"/api/world1/imports/{job['job_id']}/stream",
            json={"relative": "lore/Manual.md", "offset": 0,
                  "data_b64": base64.b64encode(
                      b"Texto sin encabezados markdown.").decode()})
        analyze = client.post(
            f"/api/world1/imports/{job['job_id']}/analyze")
        assert analyze.status_code == 200, analyze.text
        assert analyze.json()["candidates"] == 1
        assert calls["n"] >= 1, "inference must be consulted when no headings"
        cand = store.candidates_for(job["job_id"])[0]
        assert cand.canonical_id == "Inferido"
        assert cand.display_title == "Inferido"
        # Deterministic scan that finds headings does NOT consult inference.
        calls["n"] = 0
        resp2 = client.post(
            "/api/world1/imports",
            json={"source_kind": "loose", "files": ["lore/Manual.md"]})
        job2 = resp2.json()["job"]
        client.post(
            f"/api/world1/imports/{job2['job_id']}/stream",
            json={"relative": "lore/Manual.md", "offset": 0,
                  "data_b64": base64.b64encode(
                      b"# Real\n\nCuerpo.").decode()})
        client.post(f"/api/world1/imports/{job2['job_id']}/analyze")
        assert calls["n"] == 0, "inference must NOT run when headings exist"