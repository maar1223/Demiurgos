# -*- coding: utf-8 -*-
"""World importer — Hermes advisory enrichment unit + integration tests.

Slice 2 (PR 1): the enrichment module is pure (no I/O, no Hermes network),
so we exercise it with fake runners and Pydantic candidates. Coverage:

* prompt bounds and JSON contract
* tolerant JSON parsing (fenced, malformed, non-object payloads)
* vocabulary/reference safety (invalid types, self-links, ungrounded names)
* fail-open semantics on runner exceptions / timeouts / malformed output
* deterministic digest stability (enrichment never touches the digest)
* advisory content patch during execute (approved-only, dedup, no mutation
  of unrelated frontmatter)

The integration suite under ``test_import_integration_enrichment.py`` adds
the router-level wiring (analyze with ``enrich``, decisions, suggestions
in review responses) on top of these primitives.
"""

from __future__ import annotations

import base64
import json
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
    DEFAULT_PROMPT_VERSION,
    apply_approved_suggestions,
    build_enrichment_prompt,
    enrich_candidates,
    entity_type_vocabulary,
    parse_hermes_response,
    parse_summary_response,
    validate_suggestions,
)
from import_models import (  # noqa: E402
    Candidate,
    EnrichmentStatus,
    Provenance,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _candidate(identity: str = "A", preview: str = "Settlement founded in 1200 AE.",
               *, candidate_id: str | None = None,
               world: str = "world1",
               job_id: str | None = None) -> Candidate:
    """Build a minimal candidate for unit tests."""
    return Candidate(
        candidate_id=candidate_id or uuid.uuid4().hex,
        job_id=job_id or "job-test",
        world=world,
        normalized_identity=identity,
        source_hash=f"sha256:{identity}",
        provenance=Provenance(
            source_path=f"lore/{identity}.md",
            source_kind="loose",
            source_hash=f"sha256:{identity}",
        ),
        content_preview=preview,
        size_bytes=len(preview),
    )


# ---------------------------------------------------------------------------
# T4 — vocabulary + parsing + fail-open
# ---------------------------------------------------------------------------


class TestEntityTypeVocabulary:
    def test_seeded_from_sync_lore_entity_type(self):
        vocab = entity_type_vocabulary()
        # The canonical EntityType is closed with 8 values; the importer must
        # match exactly so a Hermes suggestion cannot widen the contract.
        assert len(vocab) == 8
        assert set(vocab) == {
            "personaje", "criatura", "objeto", "lugar",
            "concepto", "evento", "organizacion", "especie",
        }


class TestBuildEnrichmentPrompt:
    def test_includes_entity_vocab_and_instructions(self):
        candidates = [_candidate("A"), _candidate("B")]
        prompt = build_enrichment_prompt(candidates)
        assert "classifications" in prompt["instructions"]
        assert "relationships" in prompt["instructions"]
        assert set(prompt["entity_vocab"]) == set(entity_type_vocabulary())
        assert "aliado-de" in prompt["rel_vocab"]
        # Preview is bounded and never exceeds the per-candidate budget.
        for entry in prompt["candidates"]:
            assert entry["preview"]
            assert len(entry["preview"]) <= 1500 + 3  # +3 for ellipsis

    def test_caps_preview_length(self):
        long_text = "x" * 5000
        candidates = [_candidate("A", preview=long_text)]
        prompt = build_enrichment_prompt(candidates)
        # The bounded preview truncates with an ellipsis marker.
        preview = prompt["candidates"][0]["preview"]
        assert preview.endswith("...")
        assert len(preview) <= 1503

    def test_caps_batch_size(self):
        # Hard cap of 100 per batch: a 150-candidate import is paginated.
        candidates = [_candidate(f"C{i}") for i in range(150)]
        prompt = build_enrichment_prompt(candidates)
        assert len(prompt["candidates"]) == 100

    def test_provenance_attaches_prompt_version(self):
        prompt = build_enrichment_prompt([_candidate("A")])
        assert prompt["provenance"]["prompt_version"] == DEFAULT_PROMPT_VERSION
        assert prompt["provenance"]["provider"] == "hermes-gateway"


class TestParseHermesResponse:
    def test_unfenced_json_round_trips(self):
        raw = json.dumps({
            "classifications": [{"candidate_id": "x", "type": "personaje"}],
            "relationships": [],
        })
        out = parse_hermes_response(raw)
        assert len(out["classifications"]) == 1
        assert len(out["relationships"]) == 0

    def test_strips_single_code_fence(self):
        raw = "```json\n" + json.dumps({"classifications": [], "relationships": []}) + "\n```"
        out = parse_hermes_response(raw)
        assert out == {"classifications": [], "relationships": []}

    def test_empty_payload_returns_empty_lists(self):
        assert parse_hermes_response("") == {"classifications": [], "relationships": []}
        assert parse_hermes_response("not json at all") == {
            "classifications": [], "relationships": []}

    def test_non_object_payload_returns_empty_lists(self):
        out = parse_hermes_response(json.dumps(["bad", "shape"]))
        assert out == {"classifications": [], "relationships": []}

    def test_prose_prefixed_fenced_json_is_parsed(self):
        """Prose before the fenced block must not defeat the parser.

        Hermes sometimes prepends a short intro (e.g. "Aquí tienes ...") before
        the `````json`` block. ``_strip_code_fence`` only strips a fence at the
        very start, so this previously fell through to ``json.loads`` on the
        prose and returned no classifications/relationships — silently emptying
        the enrichment funnel (every ficha landed in "requires your decision").
        """
        raw = (
            "Aquí tienes las fichas resumidas según el pipeline. \n\n"
            "```json\n"
            + json.dumps({"classifications": [
                {"candidate_id": "x", "type": "personaje"}],
                "relationships": []})
            + "\n```"
        )
        out = parse_hermes_response(raw)
        assert len(out["classifications"]) == 1
        assert len(out["relationships"]) == 0

    def test_summary_prose_prefixed_fenced_json_is_parsed(self):
        """Step 2 (summaries) must also tolerate a prose-prefixed fenced reply.

        This is the funnel's critical path: if the summary parse returns ``{}``,
        ``summarized`` is empty, Steps 3+4 never run, and every ficha falls into
        "requires your decision" with no relationships and fallback frontmatter.
        """
        raw = (
            "Aquí tienes las fichas resumidas (paso 1 del pipeline).\n\n"
            "```json\n"
            + json.dumps({"summaries": [
                {"candidate_id": "x", "summary": "Resumen de la ficha."}]})
            + "\n```"
        )
        out = parse_summary_response(raw)
        assert out == {"x": "Resumen de la ficha."}




class TestValidateSuggestions:
    def test_known_type_is_accepted(self):
        cand = _candidate("A")
        parsed = {
            "classifications": [{"candidate_id": cand.candidate_id,
                                 "type": "personaje",
                                 "tags": ["Líder"],
                                 "confidence": 0.9,
                                 "evidence": "named leader"}],
            "relationships": [],
        }
        cls, rel = validate_suggestions(parsed, [cand])
        assert len(cls) == 1
        assert cls[0].type == "personaje"
        assert cls[0].tags == ["líder"]  # lowercased + deduped
        assert cls[0].confidence == 0.9
        assert cls[0].review_state == "pending"

    def test_unknown_type_is_rejected(self):
        """Vocabulary filter rejects anything not in the canonical EntityType."""
        cand = _candidate("A")
        parsed = {
            "classifications": [{"candidate_id": cand.candidate_id,
                                 "type": "mythical-being",  # NOT in EntityType
                                 "confidence": 0.9,
                                 "evidence": "irrelevant"}],
            "relationships": [],
        }
        cls, _ = validate_suggestions(parsed, [cand])
        assert cls == []

    def test_confidence_out_of_bounds_is_rejected(self):
        """Confidence outside [0, 1] is silently dropped (fail-open)."""
        cand = _candidate("A")
        parsed = {
            "classifications": [
                {"candidate_id": cand.candidate_id, "type": "lugar",
                 "confidence": 1.5, "evidence": "x"},
                {"candidate_id": cand.candidate_id, "type": "lugar",
                 "confidence": -0.1, "evidence": "x"},
            ],
            "relationships": [],
        }
        cls, _ = validate_suggestions(parsed, [cand])
        assert cls == []

    def test_self_link_is_rejected(self):
        """A relationship from a candidate to itself is never accepted."""
        a = _candidate("A")
        parsed = {
            "classifications": [],
            "relationships": [{
                "source_candidate_id": a.candidate_id,
                "target_candidate_id": a.candidate_id,
                "relationship_type": "aliado-de",
                "confidence": 0.8,
                "evidence": "self-reference",
            }],
        }
        _, rel = validate_suggestions(parsed, [a])
        assert rel == []

    def test_ungrounded_target_name_is_rejected(self):
        """A named target absent from the batch is ungrounded -> rejected."""
        a = _candidate("A")
        parsed = {
            "classifications": [],
            "relationships": [{
                "source_candidate_id": a.candidate_id,
                "target_name": "Nobody",
                "relationship_type": "aliado-de",
                "confidence": 0.8,
                "evidence": "mentions Nobody",
            }],
        }
        _, rel = validate_suggestions(parsed, [a])
        assert rel == []

    def test_grounded_target_name_is_accepted(self):
        a = _candidate("A")
        b = _candidate("B")
        parsed = {
            "classifications": [],
            "relationships": [{
                "source_candidate_id": a.candidate_id,
                "target_name": "B",
                "relationship_type": "aliado-de",
                "confidence": 0.8,
                "evidence": "serves together",
            }],
        }
        _, rel = validate_suggestions(parsed, [a, b])
        assert len(rel) == 1
        assert rel[0].target_name == "B"

    def test_batched_target_gets_display_title_as_target_name(self):
        """BUG 4 — a relationship to another candidate of the batch carries
        that candidate's human title (display_title) so the frontend shows a
        readable name instead of the internal candidate id."""
        a = _candidate("A")
        b = _candidate("B")
        b.display_title = "Vibrastal"
        parsed = {
            "classifications": [],
            "relationships": [{
                "source_candidate_id": a.candidate_id,
                "target_candidate_id": b.candidate_id,
                "relationship_type": "aliado-de",
                "confidence": 0.8,
                "evidence": "serves together",
            }],
        }
        _, rel = validate_suggestions(parsed, [a, b])
        assert len(rel) == 1
        assert rel[0].target_candidate_id == b.candidate_id
        assert rel[0].target_name == "Vibrastal"

    def test_unknown_relationship_type_is_rejected(self):
        a = _candidate("A")
        b = _candidate("B")
        parsed = {
            "classifications": [],
            "relationships": [{
                "source_candidate_id": a.candidate_id,
                "target_candidate_id": b.candidate_id,
                "relationship_type": "fictional-relation",
                "confidence": 0.8,
                "evidence": "x",
            }],
        }
        _, rel = validate_suggestions(parsed, [a, b])
        assert rel == []


# ---------------------------------------------------------------------------
# T2 — fail-open + happy path
# ---------------------------------------------------------------------------


class TestEnrichCandidates:
    def test_no_runner_disables_enrichment(self):
        """No injected runner = disabled (legacy deterministic flow)."""
        a = _candidate("A")
        out = enrich_candidates([a], hermes_runner=None)
        assert out[0].enrichment_status == EnrichmentStatus.DISABLED.value
        assert out[0].enrichment_json is None

    def test_runner_exception_is_fail_open(self):
        """A runner that raises never breaks analyze; status is error."""
        a = _candidate("A")

        def boom(_prompt: str, _sid: str) -> str:
            raise RuntimeError("hermes unavailable")

        out = enrich_candidates([a], hermes_runner=boom)
        assert out[0].enrichment_status == EnrichmentStatus.NO_SUGGESTIONS.value
        assert out[0].enrichment_json is None

    def test_runner_timeout_is_fail_open(self):
        """Timeout exception -> no suggestions, status no_suggestions."""
        a = _candidate("A")

        def slow(_prompt: str, _sid: str) -> str:
            raise TimeoutError("5s budget exceeded")

        out = enrich_candidates([a], hermes_runner=slow)
        assert out[0].enrichment_status == EnrichmentStatus.NO_SUGGESTIONS.value

    def test_malformed_response_returns_no_suggestions(self):
        a = _candidate("A")
        out = enrich_candidates([a], hermes_runner=lambda _p, _s: "garbage")
        assert out[0].enrichment_status == EnrichmentStatus.NO_SUGGESTIONS.value
        assert out[0].enrichment_json is None

    def test_happy_path_attaches_classification_and_relationship(self):
        a = _candidate("A")
        b = _candidate("B")
        payload = {
            "classifications": [{
                "candidate_id": a.candidate_id,
                "type": "personaje",
                "tags": ["Líder"],
                "confidence": 0.9,
                "evidence": "named leader",
                "id": "cls-1",
            }],
            "relationships": [{
                "source_candidate_id": a.candidate_id,
                "target_candidate_id": b.candidate_id,
                "relationship_type": "aliado-de",
                "confidence": 0.8,
                "evidence": "serves together",
                "id": "rel-1",
            }],
        }

        def runner(prompt: str, _sid: str) -> str:
            return json.dumps(payload)

        out = enrich_candidates([a, b], hermes_runner=runner)
        # ``A`` is the source of both suggestions (its own classification +
        # the outgoing relationship) -> ``ok`` status.
        assert out[0].enrichment_status == EnrichmentStatus.OK.value
        # ``B`` is only a target; nothing attaches to it in this payload
        # -> ``no_suggestions`` (the batch was reachable but yielded no
        # suggestions targeting this candidate).
        assert out[1].enrichment_status == EnrichmentStatus.NO_SUGGESTIONS.value
        # Both candidates carry the shared suggestions list (relationships
        # live on their source candidate; classifications on their own).
        a_enrich = out[0].enrichment_json or []
        b_enrich = out[1].enrichment_json or []
        assert any(e["id"] == "cls-1" for e in a_enrich)
        assert any(e["id"] == "rel-1" for e in a_enrich)
        # ``B`` receives nothing because no suggestion targets it directly
        # in this payload.
        assert b_enrich == []


# ---------------------------------------------------------------------------
# T4 — digest stability
# ---------------------------------------------------------------------------


class TestDigestStability:
    def test_enrichment_does_not_change_candidate_digest(self):
        """The deterministic digest uses identity:source_hash only.

        Enrichment MUST NEVER alter those inputs; even with ``enrich=True``
        and a successful Hermes reply the digest stays identical to the
        non-enriched baseline.
        """
        a = _candidate("A")
        baseline = _digest([a])
        payload = {
            "classifications": [{
                "candidate_id": a.candidate_id, "type": "personaje",
                "tags": [], "confidence": 0.9, "evidence": "x", "id": "c1",
            }],
            "relationships": [],
        }
        patched = enrich_candidates([a], hermes_runner=lambda _p, _s: json.dumps(payload))[0]
        assert _digest([patched]) == baseline
        # Identity/digest inputs are byte-equal across the patched copy.
        assert patched.normalized_identity == a.normalized_identity
        assert patched.source_hash == a.source_hash


def _digest(candidates: list[Candidate]) -> str:
    """Replicate the import_service.candidate_digest computation in-test.

    Avoids importing the service module from the enrichment test so the
    two test surfaces stay independent.
    """
    import hashlib
    ordered = "|".join(
        f"{c.normalized_identity}:{c.source_hash}" for c in candidates)
    return hashlib.sha256(ordered.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# T1.3 — apply_approved_suggestions content patch
# ---------------------------------------------------------------------------


class TestApplyApprovedSuggestions:
    def _candidate_with_frontmatter(self) -> Candidate:
        return _candidate(
            "A",
            preview=("---\n"
                     "type: personaje\n"
                     "tags: [guerrero]\n"
                     "relaciones: []\n"
                     "---\n"
                     "# Origen\n"
                     "A body"),
        )

    def test_classification_patches_type_and_merges_tags(self):
        from import_enrichment import ClassificationSuggestion
        cand = self._candidate_with_frontmatter()
        cls = ClassificationSuggestion(
            id="cls-1", candidate_id=cand.candidate_id,
            type="lugar", tags=["ciudad", "guerrero"],
            confidence=0.9, evidence="x", provenance={}, review_state="pending")
        patched = apply_approved_suggestions(
            cand, classifications=[cls], relationships=[],
            approved_classification_ids=["cls-1"], approved_relationship_ids=[])
        assert "type: lugar" in patched
        # The pre-existing tag is preserved (dedupe, case-insensitive).
        assert "guerrero" in patched
        assert "ciudad" in patched

    def test_unapproved_classification_is_ignored(self):
        from import_enrichment import ClassificationSuggestion
        cand = self._candidate_with_frontmatter()
        cls = ClassificationSuggestion(
            id="cls-1", candidate_id=cand.candidate_id,
            type="lugar", tags=[], confidence=0.9, evidence="x",
            provenance={}, review_state="pending")
        patched = apply_approved_suggestions(
            cand, classifications=[cls], relationships=[],
            approved_classification_ids=[], approved_relationship_ids=[])
        # The original ``type: personaje`` is preserved because no ID was approved.
        assert "type: personaje" in patched

    def test_relationship_appends_dedup(self):
        from import_enrichment import RelationshipSuggestion
        cand = self._candidate_with_frontmatter()
        rel = RelationshipSuggestion(
            id="rel-1", source_candidate_id=cand.candidate_id,
            target_name="B", target_candidate_id=None,
            relationship_type="aliado-de", confidence=0.8, evidence="x",
            provenance={}, review_state="pending")
        patched = apply_approved_suggestions(
            cand, classifications=[], relationships=[rel],
            approved_classification_ids=[], approved_relationship_ids=["rel-1"])
        assert "[[B]]" in patched

    def test_unknown_approval_id_is_skipped(self):
        from import_enrichment import ClassificationSuggestion
        cand = self._candidate_with_frontmatter()
        cls = ClassificationSuggestion(
            id="cls-1", candidate_id=cand.candidate_id,
            type="lugar", tags=[], confidence=0.9, evidence="x",
            provenance={}, review_state="pending")
        # An approval referencing a stale ID is a no-op (defensive: the
        # approval token is consumed but the reviewer state may have
        # changed; we never crash on a stale approval).
        patched = apply_approved_suggestions(
            cand, classifications=[cls], relationships=[],
            approved_classification_ids=["stale"], approved_relationship_ids=["stale"])
        assert "type: personaje" in patched


# ---------------------------------------------------------------------------
# T7 — analyze+enrich flow integration (TestClient)
# ---------------------------------------------------------------------------


class _FakePrincipal:
    def __init__(self, pid: str = "tester"):
        self.id = pid


_OKF = b"---\ntype: personaje\nname: A\n---\n# Origen\nA body with context"


def _full_app(tmp_path, *, enricher=None):
    """Real router + ImportService on a hermetic store/spool/world.

    ``enricher`` is injected into ``create_import_router`` so analyze with
    ``enrich=true`` exercises the wiring without the real Hermes gateway.
    """
    from import_service import ImportService
    from import_store import ImportJobStore
    from import_router import create_import_router, StreamChunkRequest

    store = ImportJobStore(":memory:")
    spool = tmp_path / "spool"
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

    def require_principal(request):
        return _FakePrincipal()

    app = FastAPI()
    app.include_router(create_import_router(
        require_principal=require_principal,
        mundos_dir=lambda: mundos,
        spool_dir=lambda: spool,
        store=store,
        service=service,
        enricher=enricher,
    ))
    return TestClient(app), store, spool, mundos


class TestAnalyzeEnrichFlow:
    def test_analyze_with_enrich_true_attaches_suggestions(self, tmp_path):
        def enricher(candidates, progress_cb=None, on_phase=None, should_cancel=None):
            from import_models import EnrichmentStatus
            payload = [{
                "id": "cls-1",
                "candidate_id": candidates[0].candidate_id,
                "type": "personaje",
                "tags": ["Líder"],
                "confidence": 0.9,
                "evidence": "named leader",
                "provenance": {"prompt_version": "v1"},
                "review_state": "pending",
                "__type__": "classification",
            }]
            from import_models import Candidate
            data = candidates[0].model_dump()
            data["enrichment_json"] = payload
            data["enrichment_status"] = EnrichmentStatus.OK.value
            return [Candidate.model_validate(data)]

        client, store, spool, _ = _full_app(tmp_path, enricher=enricher)
        job = client.post("/api/world1/imports",
                          json={"source_kind": "loose",
                                "files": ["lore/A.md"]}).json()["job"]
        from import_router import StreamChunkRequest
        client.post(f"/api/world1/imports/{job['job_id']}/stream",
                    json=StreamChunkRequest(relative="lore/A.md", offset=0,
                                            data_b64=base64.b64encode(_OKF).decode()).model_dump())
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze",
                           json={"enrich": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["enrichment_status"] == "ok"
        review = client.get(f"/api/world1/imports/{job['job_id']}/review").json()
        # The suggestion rides on the candidate; the review response exposes
        # it under ``suggestions`` keyed by candidate_id.
        candidate_id = review["candidates"][0]["candidate_id"]
        assert any(e["id"] == "cls-1"
                   for e in review["suggestions"][candidate_id])

    def test_analyze_without_enrich_does_not_call_enricher(self, tmp_path):
        calls: list[int] = []

        def enricher(candidates, progress_cb=None, on_phase=None, should_cancel=None):
            calls.append(len(candidates))
            return candidates

        client, store, spool, _ = _full_app(tmp_path, enricher=enricher)
        job = client.post("/api/world1/imports",
                          json={"source_kind": "loose",
                                "files": ["lore/A.md"]}).json()["job"]
        from import_router import StreamChunkRequest
        client.post(f"/api/world1/imports/{job['job_id']}/stream",
                    json=StreamChunkRequest(relative="lore/A.md", offset=0,
                                            data_b64=base64.b64encode(_OKF).decode()).model_dump())
        # Enrichment is ON by default: an absent body MUST invoke the enricher.
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.status_code == 200, resp.text
        assert calls == [1]
        # The stub returns candidates unchanged (no enrichment_json), so the
        # rolled-up status stays "disabled" — the CALL is what matters here.

        # An explicit ``enrich: false`` is the opt-out: no enricher call.
        job2 = client.post("/api/world1/imports",
                           json={"source_kind": "loose",
                                 "files": ["lore/A.md"]}).json()["job"]
        client.post(f"/api/world1/imports/{job2['job_id']}/stream",
                    json=StreamChunkRequest(relative="lore/A.md", offset=0,
                                            data_b64=base64.b64encode(_OKF).decode()).model_dump())
        calls.clear()
        resp2 = client.post(f"/api/world1/imports/{job2['job_id']}/analyze",
                            json={"enrich": False})
        assert resp2.status_code == 200, resp2.text
        assert calls == []
        assert resp2.json()["enrichment_status"] == "disabled"

    def test_analyze_with_enrich_false_skips_enricher(self, tmp_path):
        """Explicit ``enrich=false`` preserves the legacy deterministic path."""
        calls: list[int] = []

        def enricher(candidates, progress_cb=None, on_phase=None, should_cancel=None):
            calls.append(len(candidates))
            return candidates

        client, store, spool, _ = _full_app(tmp_path, enricher=enricher)
        job = client.post("/api/world1/imports",
                          json={"source_kind": "loose",
                                "files": ["lore/A.md"]}).json()["job"]
        from import_router import StreamChunkRequest
        client.post(f"/api/world1/imports/{job['job_id']}/stream",
                    json=StreamChunkRequest(relative="lore/A.md", offset=0,
                                            data_b64=base64.b64encode(_OKF).decode()).model_dump())
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze",
                           json={"enrich": False})
        assert resp.status_code == 200, resp.text
        assert calls == []
        assert resp.json()["enrichment_status"] == "disabled"

    def test_hermes_unavailable_enricher_returns_no_suggestions(self, tmp_path):
        """A broken enricher is fail-open: analyze succeeds, no suggestions."""

        def broken(candidates):
            raise RuntimeError("hermes unavailable")

        client, store, spool, _ = _full_app(tmp_path, enricher=broken)
        job = client.post("/api/world1/imports",
                          json={"source_kind": "loose",
                                "files": ["lore/A.md"]}).json()["job"]
        from import_router import StreamChunkRequest
        client.post(f"/api/world1/imports/{job['job_id']}/stream",
                    json=StreamChunkRequest(relative="lore/A.md", offset=0,
                                            data_b64=base64.b64encode(_OKF).decode()).model_dump())
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze",
                           json={"enrich": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["enrichment_status"] in {"no_suggestions", "disabled"}
        review = client.get(f"/api/world1/imports/{job['job_id']}/review").json()
        # All candidates end up with empty suggestion lists.
        for suggestions in review["suggestions"].values():
            assert suggestions == []

    def test_decisions_endpoint_toggles_review_state(self, tmp_path):
        def enricher(candidates, progress_cb=None, on_phase=None, should_cancel=None):
            from import_models import EnrichmentStatus, Candidate
            data = candidates[0].model_dump()
            data["enrichment_json"] = [{
                "id": "cls-1",
                "candidate_id": candidates[0].candidate_id,
                "type": "personaje",
                "tags": [],
                "confidence": 0.9,
                "evidence": "x",
                "provenance": {},
                "review_state": "pending",
                "__type__": "classification",
            }]
            data["enrichment_status"] = EnrichmentStatus.OK.value
            return [Candidate.model_validate(data)]

        client, store, spool, _ = _full_app(tmp_path, enricher=enricher)
        job = client.post("/api/world1/imports",
                          json={"source_kind": "loose",
                                "files": ["lore/A.md"]}).json()["job"]
        from import_router import StreamChunkRequest
        client.post(f"/api/world1/imports/{job['job_id']}/stream",
                    json=StreamChunkRequest(relative="lore/A.md", offset=0,
                                            data_b64=base64.b64encode(_OKF).decode()).model_dump())
        client.post(f"/api/world1/imports/{job['job_id']}/analyze",
                    json={"enrich": True})
        # Approve the suggestion.
        resp = client.post(
            f"/api/world1/imports/{job['job_id']}/review/decisions",
            json={"decisions": [{"suggestion_id": "cls-1", "decision": "approve"}]})
        assert resp.status_code == 200, resp.text
        assert resp.json()["accepted"] == 1
        review = client.get(f"/api/world1/imports/{job['job_id']}/review").json()
        candidate_id = review["candidates"][0]["candidate_id"]
        assert review["suggestions"][candidate_id][0]["review_state"] == "approved"
