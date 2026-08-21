# -*- coding: utf-8 -*-
"""World importer — PR3 (sync-lore-in-importer) router vision seam tests.

Covers tasks 5.1-5.6 (Phase 5: the ``vision`` callable wiring, media-bundle
preservation through the router, ``file_path``/``spool_root`` propagation into
``analyze_source``, fail-open invocation before persistence) and task 7.4
(Phase 7: API composition of the vision callable from ``import_vision`` +
thumbnail + cache). Conversion and extraction seams are mocked — no
markitdown/python-docx/PyMuPDF required.
"""

from __future__ import annotations

import base64
import hashlib
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

from import_models import Candidate  # noqa: E402
from import_store import ImportJobStore  # noqa: E402
from import_service import ImportService  # noqa: E402
from import_router import (  # noqa: E402
    VisionMediaEntry,
    create_import_router,
)
from sync_lore.schemas import ImageEntry  # noqa: E402


class _FakePrincipal:
    def __init__(self, pid: str = "tester"):
        self.id = pid


def _entry(filename: str = "portada.png",
           data: bytes = b"PORTADA-BYTES") -> ImageEntry:
    return ImageEntry(
        id=str(uuid.uuid4()),
        source_file="Lore/Enciclopedia.docx",
        page=None, chunk_ref="", context_text="",
        filename=filename, image_bytes=data,
    )


def _make_app(tmp_path, *, vision=None, enricher=None, register_gallery=None):
    """Real router + ImportService on a hermetic store/spool/world."""
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
        register_gallery=register_gallery or (lambda world, src, rel: None),
    )
    app = FastAPI()
    app.include_router(
        create_import_router(
            require_principal=lambda request: _FakePrincipal(),
            mundos_dir=lambda: mundos,
            spool_dir=lambda: spool,
            store=store,
            service=service,
            enricher=enricher,
            vision=vision,
        )
    )
    return TestClient(app), store, spool, mundos


def _create_job(client: TestClient) -> dict:
    resp = client.post(
        "/api/world1/imports",
        json={"source_kind": "loose", "files": ["Lore/Enciclopedia.docx"]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["job"]


def _stream(client: TestClient, job_id: str, data: bytes) -> None:
    resp = client.post(
        f"/api/world1/imports/{job_id}/stream",
        json={"relative": "Lore/Enciclopedia.docx", "offset": 0,
              "data_b64": base64.b64encode(data).decode()},
    )
    assert resp.status_code == 200, resp.text


def _analyze(client: TestClient, job_id: str, enrich: bool = False) -> dict:
    body = {"enrich": True} if enrich else None
    resp = client.post(f"/api/world1/imports/{job_id}/analyze", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _events(store, job: dict) -> list[str]:
    """Events for a job; ``opaque_token`` is redacted from the API response,
    so read it from the store record."""
    stored = store.get_job(job["job_id"])
    obs = store.observability(stored.opaque_token)
    return [e["event"] for e in obs["events"]]


def _docx_seams(monkeypatch, entries):
    """Mock the lazy conversion + extraction seams for a .docx source."""
    monkeypatch.setattr(
        "sync_lore.utils.converter.convert_to_markdown",
        lambda _p: "# Enciclopedia\n\nBody text here",
    )
    monkeypatch.setattr(
        "import_analysis.extract_images_from_file", lambda _p: entries)


# ---------------------------------------------------------------------------
# Phase 5 — router vision seam (tasks 5.1-5.6)
# ---------------------------------------------------------------------------


class TestRouterVisionSeam:
    def test_vision_receives_candidates_and_preserved_media_bundle(
            self, tmp_path, monkeypatch):
        """Task 5.2/5.5 — the ImageEntry bundle survives analysis and reaches
        the vision seam tied to its owning candidate + spool path; media bytes
        are persisted in the job spool (PR1 wiring through the router)."""
        captured: dict = {}
        _docx_seams(monkeypatch, [_entry()])

        def fake_vision(candidates, media_entries):
            captured["candidates"] = list(candidates)
            captured["media_entries"] = list(media_entries)
            return candidates  # unchanged — visibility test only

        client, store, spool, _ = _make_app(tmp_path, vision=fake_vision)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        result = _analyze(client, job["job_id"])
        assert result["job"]["state"] == "review"
        assert captured["media_entries"]
        me = captured["media_entries"][0]
        assert isinstance(me, VisionMediaEntry)
        assert me.spool_relative_path == "media/Enciclopedia/portada.png"
        assert me.image.image_bytes == b"PORTADA-BYTES"
        assert me.candidate_id == captured["candidates"][0].candidate_id
        # PR1 spool persistence is wired: bytes exist where execution reads
        # them (spool_dir/job_id/media/<stem>/<filename>).
        stored = spool / job["job_id"] / "media" / "Enciclopedia" / "portada.png"
        assert stored.read_bytes() == b"PORTADA-BYTES"

    def test_vision_suggestions_persisted_and_visible_on_review(
            self, tmp_path, monkeypatch):
        """Task 5.3/5.5 — vision runs BEFORE persistence; the persisted review
        row carries the vision suggestions, even without the ``enrich`` flag
        (vision is its own seam)."""
        _docx_seams(monkeypatch, [_entry()])

        def fake_vision(candidates, media_entries):
            out = []
            for c in candidates:
                out.append(c.model_copy(update={
                    "enrichment_json": [{
                        "__type__": "vision", "id": "vision:abc",
                        "candidate_id": c.candidate_id,
                        "relative_media_path": "media/Enciclopedia/portada.png",
                        "description": "Retrato", "verdict": "confirma",
                        "analysis": "", "tags": [], "confidence": 0.0,
                        "provenance": {"provider": "vision"},
                        "evidence": "image:media/Enciclopedia/portada.png",
                        "review_state": "pending",
                    }],
                    "enrichment_status": "ok",
                }))
            return out

        client, store, spool, _ = _make_app(tmp_path, vision=fake_vision)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        result = _analyze(client, job["job_id"])  # enrich flag NOT set
        assert result["enrichment_status"] == "ok"
        review = client.get(f"/api/world1/imports/{job['job_id']}/review")
        body = review.json()
        cand = body["candidates"][0]
        assert cand["enrichment_status"] == "ok"
        assert any(e.get("__type__") == "vision" and e.get("id") == "vision:abc"
                   for e in (cand["enrichment_json"] or []))

    def test_vision_runs_after_text_enrichment(self, tmp_path, monkeypatch):
        """Task 5.3 — vision merges AFTER text enrichment so both suggestion
        families coexist in the persisted enrichment payload."""
        _docx_seams(monkeypatch, [_entry()])

        def fake_enricher(candidates):
            return [c.model_copy(update={
                "enrichment_json": [{
                    "__type__": "classification", "id": "cls:1",
                    "candidate_id": c.candidate_id, "type": "personaje",
                    "tags": [], "confidence": 0.9, "evidence": "texto",
                    "provenance": {"provider": "hermes"},
                    "review_state": "pending",
                }],
                "enrichment_status": "ok",
            }) for c in candidates]

        def fake_vision(candidates, media_entries):
            out = []
            for c in candidates:
                payload = list(c.enrichment_json or []) + [{
                    "__type__": "vision", "id": "vision:abc",
                    "candidate_id": c.candidate_id,
                    "relative_media_path": "media/Enciclopedia/portada.png",
                    "description": "Retrato", "verdict": "confirma",
                    "analysis": "", "tags": [], "confidence": 0.0,
                    "provenance": {"provider": "vision"},
                    "evidence": "", "review_state": "pending",
                }]
                out.append(c.model_copy(update={
                    "enrichment_json": payload, "enrichment_status": "ok",
                }))
            return out

        client, store, spool, _ = _make_app(
            tmp_path, vision=fake_vision, enricher=fake_enricher)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        result = _analyze(client, job["job_id"], enrich=True)
        assert result["enrichment_status"] == "ok"
        cand = store.candidates_for(job["job_id"])[0]
        kinds = {e.get("__type__") for e in (cand.enrichment_json or [])}
        assert {"classification", "vision"} <= kinds

    def test_router_without_vision_works_as_before(self, tmp_path, monkeypatch):
        """Task 5.6 — no vision callable: the deterministic flow is untouched
        (no enrichment, no vision events, candidates persisted)."""
        _docx_seams(monkeypatch, [_entry()])
        client, store, spool, _ = _make_app(tmp_path)  # vision=None
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        result = _analyze(client, job["job_id"])
        assert result["job"]["state"] == "review"
        cand = store.candidates_for(job["job_id"])[0]
        assert cand.enrichment_json is None
        assert not any(e.startswith("vision_error") for e in _events(store, job))

    def test_vision_exception_fail_open_candidates_persist(
            self, tmp_path, monkeypatch):
        """Task 5.4 — a vision exception records a diagnostic event and the
        candidates persist WITHOUT vision data (import never blocks)."""
        _docx_seams(monkeypatch, [_entry()])

        def boom(candidates, media_entries):
            raise RuntimeError("vision provider exploded")

        client, store, spool, _ = _make_app(tmp_path, vision=boom)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        result = _analyze(client, job["job_id"])
        assert result["job"]["state"] == "review"
        cand = store.candidates_for(job["job_id"])[0]
        assert cand.enrichment_json is None
        assert any(e.startswith("vision_error:") for e in _events(store, job))

    def test_vision_malformed_output_fail_open(self, tmp_path, monkeypatch):
        """Task 5.4 — a non-list vision output is treated as a failure too."""
        _docx_seams(monkeypatch, [_entry()])

        def bad_output(candidates, media_entries):
            return "not-a-list"

        client, store, spool, _ = _make_app(tmp_path, vision=bad_output)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        result = _analyze(client, job["job_id"])
        assert result["job"]["state"] == "review"
        assert store.candidates_for(job["job_id"])
        assert any(e.startswith("vision_error:") for e in _events(store, job))

    def test_reimport_persists_vision_enrichment_on_existing_candidate(
            self, tmp_path, monkeypatch):
        """Vision data must reach an existing candidate row on re-import (the
        router persists enrichment even when the candidate already exists)."""
        _docx_seams(monkeypatch, [_entry()])

        def fake_vision(candidates, media_entries):
            return [c.model_copy(update={
                "enrichment_json": [{
                    "__type__": "vision", "id": "vision:abc",
                    "candidate_id": c.candidate_id,
                    "relative_media_path": "media/Enciclopedia/portada.png",
                    "description": "Retrato", "verdict": "confirma",
                    "analysis": "", "tags": [], "confidence": 0.0,
                    "provenance": {"provider": "vision"},
                    "evidence": "", "review_state": "pending",
                }],
                "enrichment_status": "ok",
            }) for c in candidates]

        client, store, spool, _ = _make_app(tmp_path, vision=fake_vision)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        _analyze(client, job["job_id"])
        assert store.candidates_for(job["job_id"])[0].enrichment_json
        # Second import of the same bytes: candidate already exists; vision
        # enrichment must still be persisted on the existing row.
        _analyze(client, job["job_id"])
        cand = store.candidates_for(job["job_id"])[0]
        assert any(e.get("__type__") == "vision" for e in cand.enrichment_json)

    def test_media_derived_placements_attached_to_candidate(
            self, tmp_path, monkeypatch):
        """Task 6.1 (router side) — extracted media attaches to its parent
        candidate as placements even when the converted markdown has no image
        refs; the converted identity keeps the .md path (PR1 rule)."""
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown",
            lambda _p: "# Enciclopedia\n\nBody without image refs",
        )
        monkeypatch.setattr(
            "import_analysis.extract_images_from_file", lambda _p: [_entry()])
        client, store, spool, _ = _make_app(tmp_path)  # no vision
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        _analyze(client, job["job_id"])
        cand = store.candidates_for(job["job_id"])[0]
        assert cand.provenance.source_path == "Lore/Enciclopedia.md"
        assert any(p.relative_media_path == "media/Enciclopedia/portada.png"
                   for p in cand.images)

    def test_reimport_backfills_media_on_candidate_created_without_images(
            self, tmp_path, monkeypatch):
        """A candidate persisted while media extraction was unavailable (e.g.
        before python-docx was installed) carries empty images. A re-import of
        the same bytes now extracts media: the existing row must be
        backfilled so review/execute see the placements."""
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown",
            lambda _p: "# Enciclopedia\n\nBody without image refs",
        )
        # First analysis: no media extraction (unavailable dependency).
        monkeypatch.setattr(
            "import_analysis.extract_images_from_file", lambda _p: [])
        client, store, spool, _ = _make_app(tmp_path)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        _analyze(client, job["job_id"])
        first = store.candidates_for(job["job_id"])[0]
        assert first.images == []

        # Second analysis of the same bytes: media extraction now works.
        monkeypatch.setattr(
            "import_analysis.extract_images_from_file",
            lambda _p: [_entry(filename="portada.png")])
        _analyze(client, job["job_id"])
        cand = store.candidates_for(job["job_id"])[0]
        assert any(p.relative_media_path == "media/Enciclopedia/portada.png"
                   for p in cand.images)


# ---------------------------------------------------------------------------
# Phase 7 — API composition of the vision callable (task 7.4)
# ---------------------------------------------------------------------------


class TestApiVisionComposition:
    def _candidate(self) -> Candidate:
        return Candidate(
            candidate_id="cand-1", job_id="job1", world="world1",
            normalized_identity="Enciclopedia", source_hash="sha256:abc",
            provenance={"source_path": "Lore/Enciclopedia.md",
                        "source_kind": "loose", "source_hash": "sha256:abc"},
            content_preview="# Enciclopedia\n\nBody",
        )

    def _media(self) -> VisionMediaEntry:
        return VisionMediaEntry(
            candidate_id="cand-1",
            image=ImageEntry(id="e1", source_file="Lore/Enciclopedia.docx",
                             filename="portada.png", image_bytes=b"BYTES"),
            spool_relative_path="media/Enciclopedia/portada.png",
        )

    def test_text_only_assistant_yields_none(self, monkeypatch):
        """Task 7.3 — a text-only/unconfigured assistant produces ``None`` and
        the router then runs without vision."""
        import api_server
        monkeypatch.setattr(
            "import_vision.build_vision_callable", lambda **kw: None)
        assert api_server._make_vision_callable() is None

    def test_vision_adapter_builds_suggestions(self, monkeypatch):
        """Task 7.4 — the adapter wires thumbnail + cache into the PR2
        callable and converts VisionResult payloads into advisory vision
        suggestions on the owning candidate."""
        import api_server
        from import_vision import VisionResult

        def fake_build(**kw):
            assert kw["generate_thumbnail"] is api_server.generate_thumbnail
            assert callable(kw["vision_cache_lookup"])
            assert callable(kw["vision_cache_store"])

            def analyze_images(images, context):
                assert images[0].image_bytes == b"BYTES"
                return [VisionResult(
                    image_hash=hashlib.sha256(b"BYTES").hexdigest(),
                    description="Un retrato", verdict="confirma",
                    analysis="analisis", tags=["retrato"],
                )]
            return analyze_images

        monkeypatch.setattr("import_vision.build_vision_callable", fake_build)
        vision = api_server._make_vision_callable()
        assert vision is not None
        cand = self._candidate()
        out = vision([cand], [self._media()])
        assert len(out) == 1
        entry = out[0].enrichment_json[0]
        assert entry["__type__"] == "vision"
        assert entry["id"] == f"vision:{hashlib.sha256(b'BYTES').hexdigest()}"
        assert entry["candidate_id"] == "cand-1"
        assert entry["relative_media_path"] == "media/Enciclopedia/portada.png"
        assert entry["description"] == "Un retrato"
        assert entry["verdict"] == "confirma"
        assert entry["review_state"] == "pending"
        assert out[0].enrichment_status == "ok"

    def test_vision_adapter_fail_open_on_analyze_error(self, monkeypatch):
        """The seam adapter never raises: a provider error returns the
        candidates unchanged."""
        import api_server

        def fake_build(**kw):
            def analyze_images(images, context):
                raise RuntimeError("provider down")
            return analyze_images

        monkeypatch.setattr("import_vision.build_vision_callable", fake_build)
        vision = api_server._make_vision_callable()
        cand = self._candidate()
        out = vision([cand], [self._media()])
        assert out == [cand]
        assert cand.enrichment_json is None

    def test_vision_adapter_skips_unmatched_media(self, monkeypatch):
        """Media without a successful analysis yields no suggestion and the
        candidate's enrichment is left untouched."""
        import api_server

        def fake_build(**kw):
            def analyze_images(images, context):
                return []  # nothing analyzed
            return analyze_images

        monkeypatch.setattr("import_vision.build_vision_callable", fake_build)
        vision = api_server._make_vision_callable()
        cand = self._candidate()
        out = vision([cand], [self._media()])
        assert out == [cand]
        assert cand.enrichment_json is None

    def test_vision_adapter_no_media_noop(self, monkeypatch):
        """An empty media bundle short-circuits without calling the provider."""
        import api_server
        called = []

        def fake_build(**kw):
            def analyze_images(images, context):
                called.append(images)
                return []
            return analyze_images

        monkeypatch.setattr("import_vision.build_vision_callable", fake_build)
        vision = api_server._make_vision_callable()
        cand = self._candidate()
        out = vision([cand], [])
        assert out == [cand]
        assert called == []


# ---------------------------------------------------------------------------
# Opción A — manual DELETE endpoint for terminal jobs
# ---------------------------------------------------------------------------


class TestDeleteJobEndpoint:
    """DELETE /api/{mundo}/imports/{job_id} — owner-only, state-gated reaping."""

    def _make_job(self, store, *, state="completed", owner="tester",
                  job_id="jobX"):
        from import_models import (  # noqa: PLC0415
            ImportJob,
            ImportJobState,
            utcnow_iso,
        )
        job = ImportJob(
            job_id=job_id, world="world1", owner_principal=owner,
            state=ImportJobState(state), source_kind="loose",
            opaque_token="tok", created_at=utcnow_iso(), updated_at=utcnow_iso(),
        )
        store.create_job(job)
        return job

    def _delete(self, client, job_id="jobX"):
        return client.delete(f"/api/world1/imports/{job_id}")

    def test_delete_completed_job(self, tmp_path):
        client, store, _, _ = _make_app(tmp_path)
        self._make_job(store, state="completed")
        resp = self._delete(client)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True}
        assert store.get_job("jobX") is None

    def test_delete_failed_job(self, tmp_path):
        client, store, _, _ = _make_app(tmp_path)
        self._make_job(store, state="failed")
        resp = self._delete(client)
        assert resp.status_code == 200, resp.text
        assert store.get_job("jobX") is None

    def test_delete_rolled_back_job(self, tmp_path):
        client, store, _, _ = _make_app(tmp_path)
        self._make_job(store, state="rolled_back")
        resp = self._delete(client)
        assert resp.status_code == 200, resp.text
        assert store.get_job("jobX") is None

    def test_delete_review_with_candidates_forbidden(self, tmp_path):
        from import_models import Candidate, Provenance  # noqa: PLC0415
        client, store, _, _ = _make_app(tmp_path)
        self._make_job(store, state="review")
        store.add_candidate(Candidate(
            candidate_id="c1", job_id="jobX", world="world1",
            normalized_identity="A", source_hash="sha256:a",
            provenance=Provenance(source_path="lore/A.md", source_kind="loose",
                                  source_hash="sha256:a"),
            content_preview="body"))
        resp = self._delete(client)
        assert resp.status_code == 409, resp.text
        assert store.get_job("jobX") is not None

    def test_delete_empty_review_allowed(self, tmp_path):
        client, store, _, _ = _make_app(tmp_path)
        self._make_job(store, state="review")
        resp = self._delete(client)
        assert resp.status_code == 200, resp.text
        assert store.get_job("jobX") is None

    def test_delete_non_terminal_state_forbidden(self, tmp_path):
        client, store, _, _ = _make_app(tmp_path)
        self._make_job(store, state="executing")
        resp = self._delete(client)
        assert resp.status_code == 409, resp.text
        assert store.get_job("jobX") is not None

    def test_delete_not_owner_forbidden(self, tmp_path):
        client, store, _, _ = _make_app(tmp_path)
        self._make_job(store, state="completed", owner="bob")
        resp = self._delete(client)
        assert resp.status_code == 403, resp.text
        assert store.get_job("jobX") is not None

    def test_delete_unknown_job_404(self, tmp_path):
        client, _, _, _ = _make_app(tmp_path)
        resp = self._delete(client, job_id="nope")
        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Conversion-failure gate — empty content_preview must FAIL, not reach REVIEW
# ---------------------------------------------------------------------------


class TestConversionFailureGate:
    def test_conversion_failure_fails_job_instead_of_review(
            self, tmp_path, monkeypatch):
        """A convertible source (.docx) whose markitdown conversion returns
        None must send the job to FAILED with a clear message and a diagnostic
        event — never to REVIEW as a silent empty candidate."""
        # Conversion fails (markitdown returns None), media extraction is a
        # no-op so it cannot mask the missing conversion.
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", lambda _p: None)
        monkeypatch.setattr(
            "import_analysis.extract_images_from_file", lambda _p: [])

        client, store, spool, _ = _make_app(tmp_path)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        result = _analyze(client, job["job_id"])

        stored = store.get_job(job["job_id"])
        assert stored.state.value == "failed"
        # Conversion returned None => conversion_failed => "Conversion failed".
        assert "Conversion failed" in stored.error
        assert "not installed" not in stored.error
        # No candidate was persisted for a failed conversion.
        assert store.candidates_for(job["job_id"]) == []
        assert "failed:conversion" in _events(store, job)

    def test_successful_conversion_still_reaches_review(
            self, tmp_path, monkeypatch):
        """Regression guard: a healthy conversion keeps the legacy REVIEW
        behavior — the gate must not break the happy path."""
        _docx_seams(monkeypatch, [])
        client, store, _, _ = _make_app(tmp_path)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        result = _analyze(client, job["job_id"])
        assert result["job"]["state"] == "review"
        cands = store.candidates_for(job["job_id"])
        assert len(cands) == 1
        assert cands[0].content_preview
