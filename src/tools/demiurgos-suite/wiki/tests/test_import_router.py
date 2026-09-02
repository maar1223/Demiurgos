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
import json
import sys
import uuid
import zipfile
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

import import_notion  # noqa: E402
from sync_lore.import_docx_parser import ExtractionResult  # noqa: E402
from import_models import (  # noqa: E402
    Candidate,
    FrontmatterCandidate,
    FrontmatterState,
    ImportJobState,
    Provenance,
)
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
           data: bytes = b"PORTADA-BYTES",
           *, page: int | None = None, document_order: int = 0,
           paragraph_index: int = 0, anchor_type: str = "",
           structural_path: str = "", heading_path: str = "",
           context_text: str = "") -> ImageEntry:
    return ImageEntry(
        id=str(uuid.uuid4()),
        source_file="Lore/Enciclopedia.docx",
        page=page, chunk_ref="", context_text=context_text,
        filename=filename, image_bytes=data,
        document_order=document_order, paragraph_index=paragraph_index,
        anchor_type=anchor_type, structural_path=structural_path,
        heading_path=heading_path,
    )


def _make_app(tmp_path, *, vision=None, enricher=None, register_gallery=None,
              graph_resolver=None, provider=None):
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
            provider=provider,
            graph_resolver=graph_resolver,
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
        "sync_lore.import_docx_parser.extract_by_extension",
        lambda _p, converted_markdown="": ExtractionResult(
            images=entries, markdown=converted_markdown))


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
        assert me.spool_relative_path == "media/portada.png"
        assert me.image.image_bytes == b"PORTADA-BYTES"
        assert me.candidate_id == captured["candidates"][0].candidate_id
        # PR1 spool persistence is wired: bytes exist where execution reads
        # them (spool_dir/job_id/media/<filename> — flat layout).
        stored = spool / job["job_id"] / "media" / "portada.png"
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
                        "relative_media_path": "media/portada.png",
                        "description": "Retrato", "verdict": "confirma",
                        "analysis": "", "tags": [], "confidence": 0.0,
                        "provenance": {"provider": "vision"},
                        "evidence": "image:media/portada.png",
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

    def test_vision_false_skips_seam(self, tmp_path, monkeypatch):
        """``AnalyzeRequest.vision=False`` opts out of the per-image pass: the
        vision seam is never called, yet the deterministic analysis still runs
        and candidates persist (text-only re-import, cost opt-out)."""
        _docx_seams(monkeypatch, [_entry()])
        called = {"vision": False}

        def fake_vision(candidates, media_entries):
            called["vision"] = True
            return candidates

        client, store, spool, _ = _make_app(tmp_path, vision=fake_vision)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        resp = client.post(
            f"/api/world1/imports/{job['job_id']}/analyze",
            json={"enrich": True, "vision": False})
        assert resp.status_code == 200, resp.text
        assert called["vision"] is False
        # candidates were still built + persisted by the deterministic flow
        assert store.candidates_for(job["job_id"])
        assert resp.json()["job"]["state"] == "review"

    def test_vision_runs_after_text_enrichment(self, tmp_path, monkeypatch):
        """Task 5.3 — vision merges AFTER text enrichment so both suggestion
        families coexist in the persisted enrichment payload."""
        _docx_seams(monkeypatch, [_entry()])

        def fake_enricher(candidates, progress_cb=None, on_phase=None, should_cancel=None):
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
                    "relative_media_path": "media/portada.png",
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
                    "relative_media_path": "media/portada.png",
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
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": ExtractionResult(
                images=[_entry()], markdown=converted_markdown))
        client, store, spool, _ = _make_app(tmp_path)  # no vision
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        _analyze(client, job["job_id"])
        cand = store.candidates_for(job["job_id"])[0]
        assert cand.provenance.source_path == "Lore/Enciclopedia.md"
        assert any(p.relative_media_path == "media/portada.png"
                   for p in cand.images)

    def test_media_attributed_to_owning_ficha_with_position(
            self, tmp_path, monkeypatch):
        """BUG 2 — extracted media lands on the ficha whose body references
        it (never folded into the FIRST ficha) and carries the DOCX position
        contract (document_order / paragraph_index)."""
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown",
            lambda _p: "# El Origen\n\nHistoria antigua.\n\n"
                       "# Breve Historia\n\n"
                       "![retrato](media/retrato.png)\n",
        )
        monkeypatch.setattr(
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": ExtractionResult(
                images=[_entry(filename="retrato.png", page=None,
                               document_order=1, paragraph_index=2,
                               anchor_type="inline",
                               structural_path="body/p[2]/r[0]/inline[0]",
                               heading_path="Breve Historia",
                               context_text="Retrato")],
                markdown=converted_markdown))
        client, store, spool, _ = _make_app(tmp_path)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        _analyze(client, job["job_id"])
        cands = {c.canonical_id: c for c in store.candidates_for(job["job_id"])}
        assert set(cands) == {"El Origen", "Breve Historia"}
        # The image is owned by the ficha whose body references it.
        owner = cands["Breve Historia"]
        assert any("retrato.png" in p.relative_media_path
                   for p in owner.images)
        assert not any("retrato.png" in p.relative_media_path
                       for p in cands["El Origen"].images)
        # DOCX position contract is preserved on the placement.
        placement = next(
            p for p in owner.images if "retrato.png" in p.relative_media_path)
        assert placement.document_order == 1
        assert placement.paragraph_index == 2
        assert placement.anchor_type == "inline"
        assert placement.structural_path == "body/p[2]/r[0]/inline[0]"
        assert placement.heading_path == "Breve Historia"
        assert placement.context_text == "Retrato"

    def test_spool_collision_rename_keeps_media_on_owning_ficha(
            self, tmp_path, monkeypatch):
        """BUG 2 gap — when a spool collision renames the stored file
        (``pic.png`` -> ``pic-1.png`` because a sibling source in the same
        job already stored it in the flat ``media/`` dir), the media must
        still be attributed to the ficha whose body references the ORIGINAL
        name (never folded into the FIRST ficha), with the DOCX position
        contract intact."""
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown",
            lambda _p: "# El Origen\n\nHistoria antigua.\n\n"
                       "# Breve Historia\n\n"
                       "![pic](media/pic.png)\n",
        )
        monkeypatch.setattr(
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": ExtractionResult(
                images=[_entry(filename="pic.png", page=None,
                               data=b"PIC-BYTES",
                               document_order=1, paragraph_index=2,
                               anchor_type="inline",
                               structural_path="body/p[2]/r[0]/inline[0]",
                               heading_path="Breve Historia",
                               context_text="Retrato")],
                markdown=converted_markdown))
        client, store, spool, _ = _make_app(tmp_path)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        # Sibling source in the same job already stored pic.png in the flat
        # media/ dir — the docx image then collides and is renamed on disk
        # (the injected ref keeps the ORIGINAL name).
        # Binary bytes so the stale file is not picked up as a text source.
        media_dir = spool / job["job_id"] / "media"
        media_dir.mkdir(parents=True)
        (media_dir / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\nSTALE")
        _analyze(client, job["job_id"])
        # ``BoundedSpool._load_existing`` walks the job dir, so the seeded
        # media file is also listed as an intake source; it reads as binary
        # garbage and yields an empty, harmless candidate. Only the docx
        # fichas matter for this scenario.
        cands = {c.canonical_id: c for c in store.candidates_for(job["job_id"])
                 if c.canonical_id in {"El Origen", "Breve Historia"}}
        assert set(cands) == {"El Origen", "Breve Historia"}
        # The collision really fired: bytes landed under the renamed path and
        # the stale sibling file was not overwritten.
        assert (media_dir / "pic-1.png").read_bytes() == b"PIC-BYTES"
        assert (media_dir / "pic.png").read_bytes() == b"\x89PNG\r\n\x1a\nSTALE"
        # The image is owned by the ficha whose body references the ORIGINAL
        # name — never folded into the FIRST ficha.
        owner = cands["Breve Historia"]
        assert any("pic" in p.relative_media_path for p in owner.images)
        assert not any("pic" in p.relative_media_path
                       for p in cands["El Origen"].images)
        # DOCX position contract survives the spool rename.
        placement = next(
            p for p in owner.images if "pic" in p.relative_media_path)
        assert placement.document_order == 1
        assert placement.paragraph_index == 2
        assert placement.anchor_type == "inline"
        assert placement.structural_path == "body/p[2]/r[0]/inline[0]"
        assert placement.heading_path == "Breve Historia"

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
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": ExtractionResult(
                images=[], markdown=converted_markdown))
        client, store, spool, _ = _make_app(tmp_path)
        job = _create_job(client)
        _stream(client, job["job_id"], b"PK..fake")
        _analyze(client, job["job_id"])
        first = store.candidates_for(job["job_id"])[0]
        assert first.images == []

        # Second analysis of the same bytes: media extraction now works.
        monkeypatch.setattr(
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": ExtractionResult(
                images=[_entry(filename="portada.png")],
                markdown=converted_markdown))
        _analyze(client, job["job_id"])
        cand = store.candidates_for(job["job_id"])[0]
        assert any(p.relative_media_path == "media/portada.png"
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
            spool_relative_path="media/portada.png",
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
        # Dense import disables vision by default; opt in for the composition
        # seam under test.
        monkeypatch.setenv("DEMIURGOS_IMPORT_VISION", "1")

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
        assert entry["relative_media_path"] == "media/portada.png"
        assert entry["description"] == "Un retrato"
        assert entry["verdict"] == "confirma"
        assert entry["review_state"] == "pending"
        assert out[0].enrichment_status == "ok"

    def test_vision_adapter_fail_open_on_analyze_error(self, monkeypatch):
        """The seam adapter never raises: a provider error returns the
        candidates unchanged."""
        import api_server
        monkeypatch.setenv("DEMIURGOS_IMPORT_VISION", "1")

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
        monkeypatch.setenv("DEMIURGOS_IMPORT_VISION", "1")

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
        monkeypatch.setenv("DEMIURGOS_IMPORT_VISION", "1")
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

    def test_vision_disabled_by_default_for_dense_import(self, monkeypatch):
        """Dense lore import must NOT run vision unless explicitly opted in.

        PR3 regression: a multimodal assistant would otherwise trigger one
        vision LLM call per image (huge cost) during import, which the author
        does not need — import placement already carries the DOCX position
        contract. `_make_vision_callable` returns None unless
        ``DEMIURGOS_IMPORT_VISION=1`` is set.
        """
        import api_server
        monkeypatch.setenv("DEMIURGOS_IMPORT_VISION", "0")
        # Even with a buildable vision callable present, default is off.
        monkeypatch.setattr(
            "import_vision.build_vision_callable",
            lambda **kw: (lambda images, context: []),
        )
        assert api_server._make_vision_callable() is None


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
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": ExtractionResult(
                images=[], markdown=converted_markdown))

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


# ---------------------------------------------------------------------------
# BLOQUE 1 piece 1 — per-document classifier (sections map)
# ---------------------------------------------------------------------------


class TestClassifierSections:
    """The per-document classifier contract.

    The server is the authority for validation: values outside
    ``{lore, personajes, referencias}`` are rejected with HTTP 400 and no job
    is persisted. Valid maps are persisted on the job (``sections_json``) and
    stamped onto each candidate so ``resolve_target`` roots the target under
    the chosen section.
    """

    def _create(self, client, files, sections=None):
        payload = {"source_kind": "loose", "files": files}
        if sections is not None:
            payload["sections"] = sections
        return client.post("/api/world1/imports", json=payload)

    def _stream(self, client, job_id, relative, data):
        resp = client.post(
            f"/api/world1/imports/{job_id}/stream",
            json={"relative": relative, "offset": 0,
                  "data_b64": base64.b64encode(data).decode()})
        assert resp.status_code == 200, resp.text

    def test_invalid_section_rejected_400(self, tmp_path):
        client, store, _, _ = _make_app(tmp_path)
        resp = self._create(client, ["a.md"], {"a.md": "sagas"})
        assert resp.status_code == 400, resp.text
        assert "Invalid section" in resp.json()["detail"]
        # No job may be persisted for an invalid request.
        assert store.list_jobs(principal="tester", world="world1",
                               limit=10)[0] == []

    def test_invalid_section_any_map_entry_rejected_400(self, tmp_path):
        """Validation covers every map value, not just selected files."""
        client, _, _, _ = _make_app(tmp_path)
        resp = self._create(client, ["a.md"],
                            {"a.md": "lore", "b.md": "glosario"})
        assert resp.status_code == 400, resp.text
        assert "b.md" in resp.json()["detail"]

    def test_empty_sections_accepted_201(self, tmp_path):
        client, store, _, _ = _make_app(tmp_path)
        resp = self._create(client, ["a.md"], {})
        assert resp.status_code == 201, resp.text
        job = store.get_job(resp.json()["job"]["job_id"])
        assert job is not None
        assert job.sections == {}

    def test_legacy_client_without_sections_accepted_201(self, tmp_path):
        """Pre-change clients omit ``sections`` entirely — still 201, map {}."""
        client, store, _, _ = _make_app(tmp_path)
        resp = self._create(client, ["a.md"])
        assert resp.status_code == 201, resp.text
        job = store.get_job(resp.json()["job"]["job_id"])
        assert job is not None
        assert job.sections == {}

    def test_valid_sections_accepted_201_and_persisted(self, tmp_path):
        client, store, _, _ = _make_app(tmp_path)
        resp = self._create(client, ["a.md", "b.md"],
                            {"a.md": "personajes", "b.md": "referencias"})
        assert resp.status_code == 201, resp.text
        job = store.get_job(resp.json()["job"]["job_id"])
        assert job is not None
        assert job.sections == {"a.md": "personajes", "b.md": "referencias"}
        # The API response exposes the persisted map (resume re-population).
        assert resp.json()["job"]["sections"] == \
            {"a.md": "personajes", "b.md": "referencias"}

    def test_candidates_stamped_from_sections_map(self, tmp_path):
        client, store, _, _ = _make_app(tmp_path)
        resp = self._create(client, ["Enciclopedia.md"],
                            {"Enciclopedia.md": "personajes"})
        assert resp.status_code == 201, resp.text
        job_id = resp.json()["job"]["job_id"]
        self._stream(client, job_id, "Enciclopedia.md",
                     b"# Protagonista\n\nEl clan del linaje.")
        result = _analyze(client, job_id)
        assert result["job"]["state"] == "review", result
        cands = store.candidates_for(job_id)
        assert len(cands) == 1
        assert cands[0].section == "personajes"
        # The chosen section roots the canonical target; BLOQUE 1 piece 2
        # (identity-path-mapping) makes the candidate's canonical_id drive
        # the path: the H1 ficha "Protagonista" → personajes/protagonista/
        # protagonista.md (folder-per-heading — its own folder + file; the
        # source filename stem no longer wins when a valid canonical_id
        # exists).
        assert cands[0].target_resolution["canonical_path"] == \
            "personajes/protagonista/protagonista.md"

    def test_candidate_without_map_entry_gets_empty_section(self, tmp_path):
        """Empty sections → candidate.section ``""`` → legacy branch derives
        the root from the source path (zero behavior change)."""
        client, store, _, _ = _make_app(tmp_path)
        resp = self._create(client, ["Lore/Enciclopedia.md"], {})
        assert resp.status_code == 201, resp.text
        job_id = resp.json()["job"]["job_id"]
        self._stream(client, job_id, "Lore/Enciclopedia.md",
                     b"# Enciclopedia\n\nCuerpo.")
        result = _analyze(client, job_id)
        assert result["job"]["state"] == "review", result
        cands = store.candidates_for(job_id)
        assert len(cands) == 1
        assert cands[0].section == ""
        assert cands[0].target_resolution["canonical_path"] == \
            "lore/Enciclopedia.md"


# ---------------------------------------------------------------------------
# BLOQUE 3 — analyze-time collision detection (identity/reference/path)
# ---------------------------------------------------------------------------


def _outer_resolver(inner):
    """Wrap an inner link resolver in the BLOQUE 3 outer-callable shape.

    ``create_import_router`` receives ``graph_resolver: (mundo) -> inner``;
    the inner resolver maps a link name to candidate entity paths (matches
    ``EntityGraphIndex._resolve_link_candidates``).
    """
    return lambda mundo: inner


def _funnel_enricher(type_name: str = "lore"):
    """Funnel frontmatter enricher: upgrades every candidate's manual stub to
    ``generated`` so analyze materializes the rendered document (matching
    execute-time) — required for the reference check to see wikilinks."""
    def enricher(candidates, progress_cb=None, on_phase=None, should_cancel=None):
        return [c.model_copy(update={
            "frontmatter": FrontmatterCandidate(
                title=c.display_title or c.normalized_identity,
                type=type_name, description="", relaciones=[],
                state=FrontmatterState.GENERATED),
        }) for c in candidates]
    return enricher


def _collision_job(client, files_sections, bodies):
    """Create + stream + analyze a loose job with a per-file sections map."""
    resp = client.post("/api/world1/imports", json={
        "source_kind": "loose",
        "files": list(files_sections),
        "sections": files_sections,
    })
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["job"]["job_id"]
    for rel, data in bodies.items():
        resp = client.post(
            f"/api/world1/imports/{job_id}/stream",
            json={"relative": rel, "offset": 0,
                  "data_b64": base64.b64encode(data).decode()})
        assert resp.status_code == 200, resp.text
    result = _analyze(client, job_id)
    assert result["job"]["state"] == "review", result
    return job_id


_COLLISION_CODES = {
    "identity-collision", "path-collision", "duplicate-target",
    "unresolved-reference", "ambiguous-reference",
}


class TestCollisionDetection:
    """BLOQUE 3 — analyze-time collision stamping (advisory, soft-gate §6.3).

    Each test drives the real router + ImportService (hermetic store/spool/
    world) with an injected ``graph_resolver`` seam and asserts the persisted
    candidate signals (``okf_issues`` codes + ``status``).
    """

    def test_analyze_stamps_identity_collision(self, tmp_path):
        """Resolver returns matches for the canonical_id → identity-collision
        issue + status=conflict (spec: Identity already claimed)."""
        resolver = _outer_resolver(
            lambda name: ["lore/ayagars/impacto-social.md"]
            if name == "Ayagars" else [])
        client, store, _, _ = _make_app(tmp_path, graph_resolver=resolver)
        job_id = _collision_job(
            client, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md": b"# Ayagars\n\nImpacto social."})
        cand = store.candidates_for(job_id)[0]
        assert any(i["code"] == "identity-collision" for i in cand.okf_issues)
        assert cand.status == "conflict"

    def test_analyze_identity_not_claimed(self, tmp_path):
        """Resolver returns [] for the canonical_id → no identity-collision,
        status stays pending (spec: Identity not claimed)."""
        resolver = _outer_resolver(lambda name: [])
        client, store, _, _ = _make_app(tmp_path, graph_resolver=resolver)
        job_id = _collision_job(
            client, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md": b"# Ayagars\n\nImpacto social."})
        cand = store.candidates_for(job_id)[0]
        assert not any(i["code"] == "identity-collision"
                       for i in cand.okf_issues)
        assert cand.status == "pending"

    def test_analyze_stamps_unresolved_reference_indexed_section(
            self, tmp_path):
        """lore candidate whose rendered doc contains [[Nonexistent]] →
        unresolved-reference + conflict (funnel frontmatter so the rendered
        document is parseable and ``resolve`` sees the wikilink)."""
        resolver = _outer_resolver(lambda name: [])
        client, store, _, _ = _make_app(
            tmp_path, graph_resolver=resolver,
            enricher=_funnel_enricher("lore"))
        job_id = _collision_job(
            client, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md":
             b"# Enciclopedia\n\nRelacionado con [[Nonexistent Entity]]."})
        cand = store.candidates_for(job_id)[0]
        assert any(i["code"] == "unresolved-reference"
                   for i in cand.okf_issues)
        assert cand.status == "conflict"

    def test_analyze_resolves_intra_batch_reference(self, tmp_path):
        """BUG 1 — a ficha referencing a SIBLING of the same import batch
        resolves: the batch fichas are not yet in the world graph, so the
        reference check must resolve against the batch first (the injected
        graph resolver knows nothing and returns [] for every name)."""
        resolver = _outer_resolver(lambda name: [])  # graph knows nothing

        def enricher(candidates, progress_cb=None, on_phase=None, should_cancel=None):
            out = []
            for c in candidates:
                # The funnel emits BARE canonical ids (render_frontmatter_document
                # wraps them into ``[[...]]`` wikilinks at render time).
                relaciones = (
                    ["Palacios"] if c.canonical_id == "Ayagares" else [])
                out.append(c.model_copy(update={
                    "frontmatter": FrontmatterCandidate(
                        title=c.display_title or c.normalized_identity,
                        type="lore", description="",
                        relaciones=relaciones,
                        state=FrontmatterState.GENERATED),
                }))
            return out

        client, store, _, _ = _make_app(
            tmp_path, graph_resolver=resolver, enricher=enricher)
        job_id = _collision_job(
            client, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md":
             b"# Ayagares\n\nSe relaciona con [[Palacios]].\n\n"
             b"# Palacios\n\nCapital del mundo."})
        cands = {c.canonical_id: c for c in store.candidates_for(job_id)}
        assert set(cands) == {"Ayagares", "Palacios"}
        # The intra-batch relation must NOT be flagged unresolved/ambiguous.
        assert not any(i["code"] in ("unresolved-reference",
                                     "ambiguous-reference")
                       for i in cands["Ayagares"].okf_issues)
        assert cands["Ayagares"].status == "pending"

    def test_analyze_skips_reference_check_referencias(self, tmp_path):
        """referencias candidate with [[Nonexistent]] → NO reference issue
        (referencias is excluded from the graph index)."""
        resolver = _outer_resolver(lambda name: [])
        client, store, _, _ = _make_app(
            tmp_path, graph_resolver=resolver,
            enricher=_funnel_enricher("referencia"))
        job_id = _collision_job(
            client, {"Enciclopedia.md": "referencias"},
            {"Enciclopedia.md":
             b"# Enciclopedia\n\nRelacionado con [[Nonexistent Entity]]."})
        cand = store.candidates_for(job_id)[0]
        assert not any(i["code"] in ("unresolved-reference",
                                     "ambiguous-reference")
                       for i in cand.okf_issues)
        assert cand.status == "pending"

    def test_analyze_stamps_ambiguous_reference(self, tmp_path):
        """personajes candidate with [[Ambiguous]] → ambiguous-reference +
        conflict (resolver returns multiple candidates)."""
        resolver = _outer_resolver(
            lambda name: ["personajes/a.md", "personajes/b.md"]
            if name == "Ambiguous" else [])
        client, store, _, _ = _make_app(
            tmp_path, graph_resolver=resolver,
            enricher=_funnel_enricher("personaje"))
        job_id = _collision_job(
            client, {"Enciclopedia.md": "personajes"},
            {"Enciclopedia.md":
             b"# Personaje Uno\n\nSe relaciona con [[Ambiguous]]."})
        cand = store.candidates_for(job_id)[0]
        assert any(i["code"] == "ambiguous-reference" for i in cand.okf_issues)
        assert cand.status == "conflict"

    def test_analyze_stamps_path_collision_existing_target(self, tmp_path):
        """Target exists at mundos/world1/lore/dottua/dottua.md with
        different content → plan_merge→review → path-collision + conflict."""
        resolver = _outer_resolver(lambda name: [])
        client, store, _, mundos = _make_app(tmp_path, graph_resolver=resolver)
        target = mundos / "world1" / "lore" / "dottua" / "dottua.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Vieja prosa.", encoding="utf-8")
        job_id = _collision_job(
            client, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md": b"# Dottua\n\nNueva prosa."})
        cand = store.candidates_for(job_id)[0]
        assert any(i["code"] == "path-collision" for i in cand.okf_issues)
        assert cand.status == "conflict"

    def test_analyze_target_does_not_exist(self, tmp_path):
        """Target path missing on disk → path preflight skipped cleanly, no
        path-collision (new ficha, no conflict)."""
        resolver = _outer_resolver(lambda name: [])
        client, store, _, _ = _make_app(tmp_path, graph_resolver=resolver)
        job_id = _collision_job(
            client, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md": b"# Dottua\n\nNueva prosa."})
        cand = store.candidates_for(job_id)[0]
        assert not any(i["code"] == "path-collision" for i in cand.okf_issues)
        assert cand.status == "pending"

    def test_analyze_skips_path_collision_identical_content(self, tmp_path):
        """Target exists with IDENTICAL content → plan_merge→keep → no
        path-collision."""
        resolver = _outer_resolver(lambda name: [])
        client, store, _, mundos = _make_app(tmp_path, graph_resolver=resolver)
        # The ficha body (content_preview) INCLUDES the H1 heading line, so
        # "identical content" is the rendered body (heading + prose). The
        # folder-per-heading target is lore/dottua/dottua.md.
        (mundos / "world1" / "lore" / "dottua").mkdir(parents=True, exist_ok=True)
        (mundos / "world1" / "lore" / "dottua" / "dottua.md").write_text(
            "# Dottua\n\nNueva prosa.", encoding="utf-8")
        job_id = _collision_job(
            client, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md": b"# Dottua\n\nNueva prosa."})
        cand = store.candidates_for(job_id)[0]
        assert not any(i["code"] == "path-collision" for i in cand.okf_issues)

    def test_analyze_stamps_duplicate_target_intra_import(self, tmp_path):
        """Two candidates in one job resolving to the same canonical path →
        BOTH receive duplicate-target + status=conflict."""
        resolver = _outer_resolver(lambda name: [])
        client, store, _, _ = _make_app(tmp_path, graph_resolver=resolver)
        job_id = _collision_job(
            client, {"A1.md": "lore", "A2.md": "lore"},
            {"A1.md": b"# Ayagars\n\nPrimero.",
             "A2.md": b"# Ayagars\n\nSegundo."})
        cands = store.candidates_for(job_id)
        assert len(cands) == 2
        assert (cands[0].target_resolution["canonical_path"]
                == cands[1].target_resolution["canonical_path"])
        for cand in cands:
            assert any(i["code"] == "duplicate-target"
                       for i in cand.okf_issues)
            assert cand.status == "conflict"

    def test_analyze_status_pending_advisory_only(self, tmp_path):
        """Only non-collision okf_issues (basic OKF validation, e.g. missing
        identity) → status stays pending."""
        resolver = _outer_resolver(lambda name: [])
        client, store, _, _ = _make_app(tmp_path, graph_resolver=resolver)
        job_id = _collision_job(
            client, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md": b"# Solo\n\nCuerpo."})
        cand = store.candidates_for(job_id)[0]
        assert cand.okf_issues  # basic validation produced advisory issues
        assert not any(i["code"] in _COLLISION_CODES for i in cand.okf_issues)
        assert cand.status == "pending"

    def test_analyze_fail_open_resolver_none(self, tmp_path):
        """graph_resolver=None → no collision checks; candidates persist with
        existing behavior (spec: Resolver not provided)."""
        client, store, _, _ = _make_app(tmp_path)  # no resolver seam
        job_id = _collision_job(
            client, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md": b"# Ayagars\n\nImpacto social."})
        cand = store.candidates_for(job_id)[0]
        assert not any(i["code"] in _COLLISION_CODES for i in cand.okf_issues)
        assert cand.status == "pending"

    def test_analyze_fail_open_resolver_raises(self, tmp_path):
        """The outer resolver callable raises → treated as unavailable → all
        collision checks skipped (spec: Index build fails)."""
        def boom(mundo):
            raise RuntimeError("graph index down")

        client, store, _, _ = _make_app(tmp_path, graph_resolver=boom)
        job_id = _collision_job(
            client, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md": b"# Ayagars\n\nImpacto social."})
        cand = store.candidates_for(job_id)[0]
        assert not any(i["code"] in _COLLISION_CODES for i in cand.okf_issues)
        assert cand.status == "pending"

    def test_analyze_empty_canonical_id_skips_identity(self, tmp_path):
        """canonical_id=\"\" → identity check skipped even when the resolver
        would match anything (spec: Empty canonical_id → skip identity)."""
        resolver = _outer_resolver(lambda name: ["lore/anything.md"])

        def provider(job, files):
            return [Candidate(
                candidate_id="c1", job_id=job.job_id, world=job.world,
                normalized_identity="Solo", canonical_id="",
                source_hash="sha256:x",
                provenance=Provenance(
                    source_path="Solo.md", source_kind="loose",
                    source_hash="sha256:x"),
                content_preview="# Solo\n\nCuerpo.",
                section="lore",
                target_resolution={"status": "resolved",
                                   "canonical_path": "lore/solo.md"},
            )]

        client, store, _, _ = _make_app(
            tmp_path, graph_resolver=resolver, provider=provider)
        job_id = _collision_job(client, {}, {})
        cand = store.candidates_for(job_id)[0]
        assert not any(i["code"] == "identity-collision"
                       for i in cand.okf_issues)
        assert cand.status == "pending"

    def test_analyze_no_target_resolution_skips_path(self, tmp_path):
        """target_resolution.status != resolved → path preflight skipped even
        when a conflicting file exists at the would-be path."""
        resolver = _outer_resolver(lambda name: [])

        def provider(job, files):
            return [Candidate(
                candidate_id="c1", job_id=job.job_id, world=job.world,
                normalized_identity="X", canonical_id="X",
                source_hash="sha256:x",
                provenance=Provenance(
                    source_path="X.md", source_kind="loose",
                    source_hash="sha256:x"),
                content_preview="# X\n\nNueva prosa.",
                section="lore",
                target_resolution={"status": "rejected",
                                   "canonical_path": "lore/x.md"},
            )]

        client, store, _, mundos = _make_app(
            tmp_path, graph_resolver=resolver, provider=provider)
        (mundos / "world1" / "lore" / "x.md").write_text(
            "Vieja prosa.", encoding="utf-8")
        job_id = _collision_job(client, {}, {})
        cand = store.candidates_for(job_id)[0]
        assert not any(i["code"] == "path-collision" for i in cand.okf_issues)

    def test_analyze_digest_unchanged_with_collisions(self, tmp_path):
        """The approval digest (identity:source_hash) never incorporates
        collision signals: identical source → identical digest with and
        without collisions (spec: Digest identical with or without)."""
        colliding = _outer_resolver(
            lambda name: ["lore/ayagars.md"] if name == "Ayagars" else [])
        client_a, store_a, _, _ = _make_app(tmp_path, graph_resolver=colliding)
        job_a = _collision_job(
            client_a, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md": b"# Ayagars\n\nImpacto social."})
        cand_a = store_a.candidates_for(job_a)[0]
        assert any(i["code"] == "identity-collision" for i in cand_a.okf_issues)
        assert cand_a.status == "conflict"

        client_b, store_b, _, _ = _make_app(tmp_path)  # no resolver
        job_b = _collision_job(
            client_b, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md": b"# Ayagars\n\nImpacto social."})
        cand_b = store_b.candidates_for(job_b)[0]
        assert cand_b.status == "pending"
        # Both jobs carry the same source; only the collision signals differ
        # (job B has none — its basic OKF identity issue is non-collision).
        assert not any(i["code"] in _COLLISION_CODES for i in cand_b.okf_issues)

        def digest(store, job_id):
            job = store.get_job(job_id)
            svc = ImportService(
                store=store, mundos_dir=tmp_path / "mundos",
                spool_dir=tmp_path / "spool")
            return svc.candidate_digest(job)

        assert digest(store_a, job_a) == digest(store_b, job_b)

    def test_analyze_path_preflight_includes_mundo_segment(self, tmp_path):
        """Preflight target is mundos_dir/mundo/canonical_path, NOT
        mundos_dir/canonical_path (corrected design): the file exists ONLY at
        the world-scoped path → path-collision fires."""
        resolver = _outer_resolver(lambda name: [])
        client, store, _, mundos = _make_app(tmp_path, graph_resolver=resolver)
        (mundos / "world1" / "lore" / "dottua").mkdir(parents=True, exist_ok=True)
        (mundos / "world1" / "lore" / "dottua" / "dottua.md").write_text(
            "Vieja prosa.", encoding="utf-8")
        # Guard: the mundo-less path must NOT exist, or this test cannot
        # distinguish the corrected behavior.
        assert not (mundos / "lore" / "dottua" / "dottua.md").exists()
        job_id = _collision_job(
            client, {"Enciclopedia.md": "lore"},
            {"Enciclopedia.md": b"# Dottua\n\nNueva prosa."})
        cand = store.candidates_for(job_id)[0]
        assert any(i["code"] == "path-collision" for i in cand.okf_issues)
        assert cand.status == "conflict"
class TestNotionZipDispatch:
    """Phase 3 — recognized exports route through the shared analysis
    contract; ambiguous exports fail closed with an actionable diagnostic;
    and the existing generic non-Notion ZIP flow is untouched."""

    NOTION_FIXTURE = _HERE / "fixtures" / "notion" / "export"

    def _notion_zip(self, tmp_path: Path,
                    extra: dict[str, str] | None = None) -> Path:
        """Deterministic Notion-shaped ZIP (real export fixture + extras)."""
        archive = tmp_path / "notion.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(self.NOTION_FIXTURE.rglob("*")):
                relative = path.relative_to(self.NOTION_FIXTURE)
                if path.is_dir():
                    zf.writestr(zipfile.ZipInfo(f"{relative}/"), b"")
                else:
                    zf.writestr(str(relative), path.read_bytes())
            for rel, content in (extra or {}).items():
                zf.writestr(rel, content)
        return archive

    def _create_zip_job(self, client: TestClient) -> dict:
        resp = client.post(
            "/api/world1/imports",
            json={"source_kind": "zip", "files": ["notion.zip"]},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["job"]

    def _stream_zip(self, client: TestClient, job_id: str,
                    archive: Path) -> None:
        resp = client.post(
            f"/api/world1/imports/{job_id}/stream",
            json={"relative": "notion.zip", "offset": 0,
                  "data_b64": base64.b64encode(archive.read_bytes()).decode()},
        )
        assert resp.status_code == 200, resp.text

    def test_recognized_notion_zip_yields_markdown_and_csv_candidates(
            self, tmp_path):
        """A Notion Markdown & CSV export yields pages AND CSV fichas with
        provenance through the shared candidate contract (task 3.1/3.3).

        The journal page's childless ``## Expedition Notes`` is its OWN ficha
        (folder-per-heading — every heading, any level, is a ficha), so the
        journal contributes two candidates."""
        client, store, spool, mundos = _make_app(tmp_path)
        job = self._create_zip_job(client)
        self._stream_zip(client, job["job_id"], self._notion_zip(tmp_path))

        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.status_code == 200, resp.text
        assert resp.json()["candidates"] == 6
        assert store.get_job(job["job_id"]).state == ImportJobState.REVIEW

        candidates = store.candidates_for(job["job_id"])
        # The UUID-named page was renamed from its first H1; the CSV rows
        # became folder-scoped fichas; the journal's childless H2 became its
        # own ficha (same source file, second candidate); all carry ZIP
        # provenance.
        assert len(candidates) == 6
        by_path = {c.provenance.source_path: c for c in candidates}
        assert sorted(by_path) == [
            "Database/dorin.md", "Database/elara.md", "Database/kael.md",
            "World Overview.md", "elara-s-journal.md",
        ]
        journal = next(c for c in candidates
                       if c.canonical_id == "Elara's Journal::Expedition Notes")
        assert journal.provenance.source_path == "elara-s-journal.md"
        for candidate in candidates:
            assert candidate.provenance.source_kind == "zip"
            assert candidate.provenance.source_hash.startswith("sha256:")
        # Folder provenance: CSV fichas keep their source folder.
        assert by_path["Database/elara.md"].provenance.source_folder == "Database"
        assert by_path["elara-s-journal.md"].provenance.source_folder == ""
        # The generated ficha is OKF-shaped: the title lives in display_title
        # (the per-ficha flow excludes the H1 from content_preview; a CSV ficha
        # has metadata-only body) and the page keeps its image.
        assert by_path["Database/elara.md"].display_title == "Elara"
        journal_root = next(c for c in candidates
                            if c.canonical_id == "Elara's Journal")
        assert any(
            p.relative_media_path == "assets/hero.png"
            for p in journal_root.images)
        # Read-only: no canon writes during analysis.
        assert list((mundos / "world1").rglob("*.md")) == []

    def test_notion_diagnostics_surface_as_actionable_event(self, tmp_path):
        """Fail-open adapter warnings (unresolved links) become an observable
        job event; the export is still analyzed (task 3.2/3.3)."""
        client, store, _, _ = _make_app(tmp_path)
        job = self._create_zip_job(client)
        archive = self._notion_zip(
            tmp_path,
            extra={"9a8b7c6d-5e4f-4321-abcd-1234567890ab.md":
                   "# Broken Page\n\n[missing](DoesNotExist.md)\n"},
        )
        self._stream_zip(client, job["job_id"], archive)

        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.status_code == 200, resp.text
        # 6 base candidates + the extra page's childless H2 ficha.
        assert resp.json()["candidates"] == 7
        events = _events(store, job)
        assert "notion_diagnostics:1" in events

    def test_ambiguous_notion_zip_fails_closed_with_diagnostic(
            self, tmp_path, monkeypatch):
        """A recognized export whose analysis raises fails closed: FAILED
        state, actionable error, event tag, zero candidates (task 3.2/3.3)."""
        client, store, spool, mundos = _make_app(tmp_path)
        job = self._create_zip_job(client)
        self._stream_zip(client, job["job_id"], self._notion_zip(tmp_path))

        def _boom(root, manifest):
            raise OSError("simulated ambiguous export")

        monkeypatch.setattr(import_notion, "analyze_export", _boom)
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.status_code == 200, resp.text
        assert resp.json()["job"]["state"] == "failed"
        stored = store.get_job(job["job_id"])
        assert stored.state == ImportJobState.FAILED
        assert "Notion export analysis failed" in stored.error
        assert "OSError" in stored.error
        assert "failed:notion_analysis" in _events(store, job)
        assert store.candidates_for(job["job_id"]) == []
        assert list((mundos / "world1").rglob("*.md")) == []

    def test_non_notion_zip_flow_unaffected(self, tmp_path):
        """A ZIP with no Notion content (no .md/.csv) keeps the generic
        analysis flow: candidates, REVIEW state, no Notion events (3.3)."""
        client, store, spool, mundos = _make_app(tmp_path)
        job = self._create_zip_job(client)
        archive = tmp_path / "plain.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("notes.txt", "plain notes")
            zf.writestr("decoration.gif", b"GIF89a")
        self._stream_zip(client, job["job_id"], archive)

        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.status_code == 200, resp.text
        assert resp.json()["candidates"] == 2
        assert store.get_job(job["job_id"]).state == ImportJobState.REVIEW
        paths = sorted(c.provenance.source_path
                       for c in store.candidates_for(job["job_id"]))
        assert paths == ["decoration.gif", "notes.txt"]
        events = _events(store, job)
        assert not any(e.startswith("notion_") for e in events)
        assert "failed:notion_analysis" not in events
        # Generic extraction still lands the entries on disk.
        assert (spool / job["job_id"] / "extracted" / "notes.txt").exists()


class TestCancelDuringAnalyze:
    """BUG A — cooperative cancellation of a long synchronous analyze.

    The ``POST /{job_id}/cancel`` endpoint raises an in-process cancel signal
    that a running ``analyze`` observes at its persistence point: the response
    is a clean cancellation result (never a 500), no REVIEW transition and no
    candidate rows are persisted for the cancelled job.
    """

    def test_cancel_during_analyze_returns_cleanly_without_persisting(
            self, tmp_path):
        """Analyze is blocked inside the (slow) enricher; cancel lands; the
        analyze thread then returns a cancellation result: 200 (no 500), no
        REVIEW, no candidates persisted, and the job row is reaped."""
        import threading as _threading

        release = _threading.Event()
        entered = _threading.Event()

        def blocking_enricher(candidates, progress_cb=None, on_phase=None,
                              should_cancel=None):
            entered.set()
            release.wait(timeout=10)
            return candidates

        client, store, spool, _ = _make_app(
            tmp_path, enricher=blocking_enricher)
        job = _create_job(client)
        _stream(client, job["job_id"], b"# Ayagares\n\nCuerpo de la ficha.")

        result: dict = {}

        def _run():
            result["resp"] = client.post(
                f"/api/world1/imports/{job['job_id']}/analyze",
                json={"enrich": True})

        t = _threading.Thread(target=_run)
        t.start()
        assert entered.wait(timeout=10), "analyze must reach the enricher"
        cancel = client.post(f"/api/world1/imports/{job['job_id']}/cancel")
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["job"]["state"] == "cancelled"
        release.set()
        t.join(timeout=10)
        resp = result.get("resp")
        assert resp is not None, "analyze must return (fail-open, no 500)"
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("cancelled") is True, (
            f"analyze must report a cancellation result, got {body}")
        assert body.get("enrichment_status") == "cancelled"
        # The cancelled job left no REVIEW transition and no candidate rows.
        assert store.get_job(job["job_id"]) is None, (
            "cancel (Opción A) reaps the DB row")
        assert store.candidates_for(job["job_id"]) == [], (
            "no candidates may be persisted for a cancelled analyze")
