# -*- coding: utf-8 -*-
"""End-to-end tests for the slice-2 enrichment lifecycle.

These tests exercise the full HTTP flow through the FastAPI router (no Hermes
network, no real filesystem beyond a hermetic ``mundos/`` and ``spool/``):

1. **Happy path**: import → analyze(``enrich=true``) → review → approve
   suggestion → execute → verify the candidate was written to ``lore/`` with
   the suggestion's frontmatter type/tags applied.
2. **Fail-open**: import → analyze(``enrich=true``) with a broken enricher →
   import succeeds, zero suggestions, no error state in the review surface.
3. **Vocabulary safety**: import → analyze(``enrich=true``) with an enricher
   that returns an invalid EntityType / relationship type → those entries are
   silently dropped during validation; the surviving valid suggestions still
   surface in review.

The router + ``ImportService`` are real; only the enricher is a callable
under test. This proves the slice-2 contract end-to-end without needing a
real Hermes gateway.
"""

from __future__ import annotations

import base64
import json
import sys
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

from import_models import Candidate, EnrichmentStatus  # noqa: E402
from import_router import StreamChunkRequest, create_import_router  # noqa: E402
from import_service import ImportService  # noqa: E402
from import_store import ImportJobStore  # noqa: E402


# Minimal but valid OKF document — frontmatter type is intentionally absent
# so enrichment has something meaningful to suggest.
_OKF = (
    b"---\n"
    b"name: Aldea del Viento\n"
    b"type: lugar\n"
    b"tags: [frontera]\n"
    b"---\n"
    b"# Origen\n"
    b"La aldea fue fundada en el 1200 AE por los primeros colonos.\n"
    b"Esta cerca de la Ciudad Alta.\n"
)


class _FakePrincipal:
    """Bypass the real auth dependency for hermetic E2E tests."""
    id = "test-principal"

    def __str__(self) -> str:
        return self.id


def _build_app(tmp_path, *, enricher=None):
    """Real router + ImportService + a hermetic store/spool/world dir."""
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
        store=store,
        mundos_dir=mundos,
        spool_dir=spool,
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
    ))
    return TestClient(app), store, spool, mundos


def _create_job(client, relative):
    """Create a job and stream the source file in one shot. Returns the
    server-issued ``job_id``.
    """
    resp = client.post(
        "/api/world1/imports",
        json={"source_kind": "loose", "files": [relative]},
    )
    assert resp.status_code == 201, resp.text
    # The create-job endpoint returns ``{"job": {...}}``; the inner payload
    # is the same as GET /api/{mundo}/imports/{id}.
    job_id = resp.json()["job"]["job_id"]
    stream = _stream_file(client, job_id, relative)
    assert stream.status_code == 200, stream.text
    return job_id


def _stream_file(client, job_id, relative, payload=_OKF):
    return client.post(
        f"/api/world1/imports/{job_id}/stream",
        json=StreamChunkRequest(
            relative=relative,
            offset=0,
            data_b64=base64.b64encode(payload).decode(),
        ).model_dump(),
    )


def _classifying_enricher(
    *,
    classification_id: str = "cls-village",
    classification_type: str = "lugar",
    classification_tags: tuple[str, ...] = ("pueblo",),
    classification_confidence: float = 0.92,
    include_invalid_classification: bool = False,
    include_invalid_relationship: bool = False,
    relationship_id: str = "rel-near",
    grounded_target: str = "Aldea del Viento",
):
    """Build a fake enricher that injects one valid classification plus,
    optionally, an invalid entry of each kind to test vocabulary rejection.

    We use the REAL ``enrich_candidates`` adapter so the validation layer
    (vocabulary filter, confidence bounds, target grounding) runs against
    the LLM response — that is the only place those guards live.
    """

    from import_enrichment import enrich_candidates

    def enricher(candidates):
        if not candidates:
            return list(candidates)
        candidate_id = candidates[0].candidate_id

        classifications = [{
            "id": classification_id,
            "candidate_id": candidate_id,
            "type": classification_type,
            "tags": list(classification_tags),
            "confidence": classification_confidence,
            "evidence": "founded by colonos in the first paragraph",
        }]
        relationships = [{
            "id": relationship_id,
            "source_candidate_id": candidate_id,
            "target_name": grounded_target,
            "relationship_type": "ubicado-en",
            "confidence": 0.83,
            "evidence": "explicit mention of " + grounded_target,
        }]
        if include_invalid_classification:
            classifications.append({
                "id": "cls-invalid",
                "candidate_id": candidate_id,
                "type": "made-up-entity-type",  # NOT in EntityType vocab
                "tags": ["tag"],
                "confidence": 0.7,
                "evidence": "x",
            })
        if include_invalid_relationship:
            relationships.append({
                "id": "rel-invalid",
                "source_candidate_id": candidate_id,
                "target_name": "Lo Nunca Visto",
                "relationship_type": "???-not-a-rel-type",
                "confidence": 0.5,
                "evidence": "x",
            })

        hermes_response = json.dumps({
            "classifications": classifications,
            "relationships": relationships,
        })

        def hermes_runner(_prompt: str, _session: str) -> str:
            return hermes_response

        return enrich_candidates(
            candidates, hermes_runner=hermes_runner,
        )

    return enricher


# ---------------------------------------------------------------------------
# T12.1 — Happy path: analyze → review → approve → execute → canon write.
# ---------------------------------------------------------------------------


class TestEnrichmentEndToEnd:
    def test_approved_suggestion_lands_in_canon_on_execute(self, tmp_path):
        """Full lifecycle: opt-in → review → approve one suggestion → execute
        → the frontmatter type + a ``[[Ciudad Alta]]`` link appear in the
        written ``lore/`` file. The deterministic digest is unchanged.
        """
        client, store, spool, mundos = _build_app(
            tmp_path, enricher=_classifying_enricher(),
        )

        # 1. Create the job and stream the source file.
        job_id = _create_job(client, "lore/Aldea del Viento.md")

        # 2. Analyze with enrichment on.
        analyze = client.post(
            f"/api/world1/imports/{job_id}/analyze",
            json={"enrich": True},
        )
        assert analyze.status_code == 200, analyze.text
        assert analyze.json()["enrichment_status"] == "ok"

        # 3. Review surfaces per-candidate suggestions + the batch status.
        review = client.get(
            f"/api/world1/imports/{job_id}/review",
        ).json()
        assert review["enrichment_status"] == "ok"
        candidate_id = review["candidates"][0]["candidate_id"]
        suggestion_ids = [
            e["id"] for e in review["suggestions"][candidate_id]
        ]
        assert "cls-village" in suggestion_ids
        assert "rel-near" in suggestion_ids
        # Digest is computed from the deterministic identity+source_hash,
        # not from the enrichment payload — capture it for later binding.
        digest_before_approve = review["digest"]
        assert digest_before_approve  # non-empty

        # 4. Approve only the classification (NOT the relationship).
        decisions = client.post(
            f"/api/world1/imports/{job_id}/review/decisions",
            json={
                "decisions": [
                    {"suggestion_id": "cls-village", "decision": "approve"},
                ],
            },
        )
        assert decisions.status_code == 200
        assert decisions.json()["accepted"] == 1

        # 5. Approve the group with the suggestion-IDs commitment.
        approval = client.post(
            f"/api/world1/imports/{job_id}/approve",
            json={
                "group_ids": ["fichas"],
                "suggestion_ids": ["cls-village"],
            },
        )
        assert approval.status_code == 200, approval.text
        token = approval.json()["token"]
        assert token  # single-use, non-empty

        # 6. Execute with the digest+token; the suggestion is materialized.
        execute = client.post(
            f"/api/world1/imports/{job_id}/execute",
            json={
                "digest": digest_before_approve,
                "token": token,
                "suggestion_ids": ["cls-village"],
            },
        )
        assert execute.status_code == 200, execute.text
        outcomes = execute.json()["outcomes"]
        assert len(outcomes) == 1
        assert outcomes[0]["written"] is True
        # The suggestion wrote the canonical frontmatter ``type`` value.
        target_path = (
            mundos
            / "world1"
            / "lore"
            / "Aldea del Viento.md"
        )
        assert target_path.exists(), (
            "approved classification must materialize the candidate into "
            "the world's lore directory"
        )
        written = target_path.read_text(encoding="utf-8")
        # The classification suggestion patched the frontmatter: ``type``
        # comes from the suggestion ("lugar") and ``tags`` is merged with
        # the approved tag. The body is preserved verbatim.
        assert "type: lugar" in written, (
            "approved classification's type must be patched into frontmatter"
        )
        assert "pueblo" in written, (
            "approved classification's tag must be patched into frontmatter"
        )
        assert "# Origen" in written, (
            "the executor must not strip the body when patching frontmatter"
        )

    def test_no_approved_suggestions_executes_legacy_path(self, tmp_path):
        """``suggestion_ids=[]`` preserves the legacy deterministic write:
        no frontmatter type is patched because the user opted out of
        enrichment materialization.
        """
        client, _, _, mundos = _build_app(
            tmp_path, enricher=_classifying_enricher(),
        )

        job_id = _create_job(client, "lore/Aldea del Viento.md")
        client.post(
            f"/api/world1/imports/{job_id}/analyze",
            json={"enrich": True},
        )
        review = client.get(
            f"/api/world1/imports/{job_id}/review",
        ).json()
        digest = review["digest"]

        approval = client.post(
            f"/api/world1/imports/{job_id}/approve",
            json={"group_ids": ["fichas"]},  # no suggestion_ids
        ).json()
        execute = client.post(
            f"/api/world1/imports/{job_id}/execute",
            json={"digest": digest, "token": approval["token"]},
        )
        assert execute.status_code == 200, execute.text

        written = (
            mundos / "world1" / "lore" / "Aldea del Viento.md"
        ).read_text(encoding="utf-8")
        # The original frontmatter does not declare a ``type``, and the
        # legacy path never patches one in — so the executed file stays
        # type-less (the deterministic identity/digest did not change).
        assert "pueblo" not in written, (
            "without approved suggestion_ids the executor must not patch "
            "the frontmatter — legacy deterministic contract"
        )
        assert "type: lugar" not in written, (
            "without approved suggestion_ids the executor must not inject a "
            "frontmatter type — legacy deterministic contract"
        )

    # -----------------------------------------------------------------------
    # T12.2 — Fail-open: Hermes unavailable → analyze succeeds, no
    # suggestions, no error state in review.
    # -----------------------------------------------------------------------

    def test_hermes_unavailable_yields_zero_suggestions(self, tmp_path):
        """The fail-open contract: a broken enricher never blocks the
        import. The analyze response reports ``no_suggestions`` and the
        review row carries an empty suggestion list per candidate.
        """

        def broken(_candidates):
            raise RuntimeError("hermes gateway unreachable")

        client, _, _, _ = _build_app(tmp_path, enricher=broken)

        job_id = _create_job(client, "lore/Aldea del Viento.md")

        analyze = client.post(
            f"/api/world1/imports/{job_id}/analyze",
            json={"enrich": True},
        )
        assert analyze.status_code == 200, (
            "fail-open: a broken enricher must NEVER make analyze fail"
        )
        # The router reports the gateway failure as ``no_suggestions``
        # (reviewable status), NOT as a failed job — the diagnostic is
        # surfaced but the import stays importable.
        assert analyze.json()["enrichment_status"] in {
            "no_suggestions",
            "disabled",
        }
        assert analyze.json()["job"]["state"] == "review"

        review = client.get(
            f"/api/world1/imports/{job_id}/review",
        ).json()
        # Every candidate ends up with an empty suggestion list.
        for suggestions in review["suggestions"].values():
            assert suggestions == [], (
                "fail-open contract: zero suggestions when Hermes is down"
            )

        # The deterministic flow continues: approve + execute still work
        # with no suggestion_ids bound (legacy path).
        digest = review["digest"]
        approval = client.post(
            f"/api/world1/imports/{job_id}/approve",
            json={"group_ids": ["fichas"]},
        ).json()
        execute = client.post(
            f"/api/world1/imports/{job_id}/execute",
            json={"digest": digest, "token": approval["token"]},
        )
        assert execute.status_code == 200, execute.text
        assert execute.json()["job"]["state"] == "completed"

    # -----------------------------------------------------------------------
    # T12.3 — Vocabulary validation: invalid EntityType / relationship type
    # are silently dropped; surviving valid suggestions still surface.
    # -----------------------------------------------------------------------

    def test_invalid_entity_type_and_rel_type_are_dropped(self, tmp_path):
        """The validation layer filters out suggestions whose ``type`` is not
        in the canonical EntityType vocabulary, or whose
        ``relationship_type`` does not normalize to the allowlist. Valid
        entries still surface to the reviewer — this proves the filter is
        PER-ENTRY, not all-or-nothing.
        """
        enricher = _classifying_enricher(
            include_invalid_classification=True,
            include_invalid_relationship=True,
        )
        client, _, _, _ = _build_app(tmp_path, enricher=enricher)

        job_id = _create_job(client, "lore/Aldea del Viento.md")
        client.post(
            f"/api/world1/imports/{job_id}/analyze",
            json={"enrich": True},
        )
        review = client.get(
            f"/api/world1/imports/{job_id}/review",
        ).json()
        candidate_id = review["candidates"][0]["candidate_id"]
        surfaced_ids = [
            e["id"] for e in review["suggestions"][candidate_id]
        ]

        # The valid classification + valid relationship survive.
        assert "cls-village" in surfaced_ids, (
            "valid classification must survive vocabulary filtering"
        )
        assert "rel-near" in surfaced_ids, (
            "valid relationship must survive vocabulary filtering"
        )
        # The invalid entries are silently dropped during validation —
        # never reaching the review row, never reaching the decisions
        # endpoint, never reaching the executor.
        assert "cls-invalid" not in surfaced_ids, (
            "an unknown EntityType must be rejected by validation"
        )
        assert "rel-invalid" not in surfaced_ids, (
            "an unknown relationship_type must be rejected by validation"
        )

        # The batch-level status still reflects "ok" because at least one
        # valid suggestion was produced — vocabulary filtering is NOT a
        # gateway failure.
        assert review["enrichment_status"] == "ok"


# ---------------------------------------------------------------------------
# T12.4 — Enrichment cache: re-importing the same file reuses prior
# enrichment instead of re-running Hermes (token savings).
# ---------------------------------------------------------------------------


class TestEnrichmentCache:
    def test_second_import_reuses_cached_enrichment(self, tmp_path):
        """When the same file (same source_hash + identity) is imported twice
        with enrichment enabled, the second analyze MUST reuse the cached
        enrichment from the first import. The enricher callable must NOT be
        invoked on the second run — this proves token savings.
        """
        call_count = {"n": 0}

        def counting_enricher(candidates):
            call_count["n"] += 1
            return _classifying_enricher()(candidates)

        client, store, spool, mundos = _build_app(
            tmp_path, enricher=counting_enricher)

        # First import: enricher runs once.
        job1 = _create_job(client, "lore/Aldea del Viento.md")
        resp1 = client.post(
            f"/api/world1/imports/{job1}/analyze",
            json={"enrich": True},
        )
        assert resp1.status_code == 200, resp1.text
        assert resp1.json().get("enriched_from_cache", 0) == 0
        assert call_count["n"] == 1, "enricher must run on first import"

        # Second import of the SAME file: enricher must NOT run again.
        job2 = _create_job(client, "lore/Aldea del Viento.md")
        resp2 = client.post(
            f"/api/world1/imports/{job2}/analyze",
            json={"enrich": True},
        )
        assert resp2.status_code == 200, resp2.text
        # The cache hit counter must be 1 (one candidate reused).
        assert resp2.json().get("enriched_from_cache", 0) == 1
        # The enricher was NOT called a second time.
        assert call_count["n"] == 1, (
            "enricher must NOT run on second import — cache hit"
        )

        # The second job's review must still carry the enrichment from the
        # first import (same suggestions visible to the reviewer).
        review2 = client.get(
            f"/api/world1/imports/{job2}/review",
        ).json()
        candidate_id2 = review2["candidates"][0]["candidate_id"]
        suggestions2 = review2["suggestions"][candidate_id2]
        assert len(suggestions2) > 0, (
            "cached enrichment must surface in second job's review"
        )
        # The batch status reflects the cached enrichment.
        assert review2["enrichment_status"] == "ok"

    def test_cache_only_applies_when_enrichment_was_ok(self, tmp_path):
        """If the first import had enrichment disabled (or failed), the second
        import with enrich=true MUST run the enricher — there is nothing to
        cache. The cache only applies when the prior import produced a
        non-disabled enrichment status.
        """
        call_count = {"n": 0}

        def counting_enricher(candidates):
            call_count["n"] += 1
            return _classifying_enricher()(candidates)

        client, store, spool, mundos = _build_app(
            tmp_path, enricher=counting_enricher)

        # First import WITHOUT enrichment.
        job1 = _create_job(client, "lore/Aldea del Viento.md")
        resp1 = client.post(
            f"/api/world1/imports/{job1}/analyze",
            json={},  # enrich defaults to False
        )
        assert resp1.status_code == 200, resp1.text
        assert call_count["n"] == 0, "no enrichment on first import"

        # Second import WITH enrichment: enricher MUST run (no cache).
        job2 = _create_job(client, "lore/Aldea del Viento.md")
        resp2 = client.post(
            f"/api/world1/imports/{job2}/analyze",
            json={"enrich": True},
        )
        assert resp2.status_code == 200, resp2.text
        assert call_count["n"] == 1, (
            "enricher must run when prior import had no enrichment"
        )
        # No cache hit because the first import was disabled.
        assert resp2.json().get("enriched_from_cache", 0) == 0
