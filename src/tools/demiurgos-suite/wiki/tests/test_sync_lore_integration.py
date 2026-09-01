# -*- coding: utf-8 -*-
"""sync-lore-in-importer — PR4 end-to-end integration tests (Phase 9).

Covers tasks 9.1-9.8 through the REAL router + ImportService + the REAL
PR2/PR3 vision pipeline (settings gate, 300px thumbnail gate, SHA-256 content
cache) with a mocked LlmProvider: the full .docx flow, text-only skip,
cache-hit on re-import, approved→gallery+alt-text, rejected→no registration,
vision failure fail-open, thumbnail-for-vision/original-for-gallery, and the
PDF review-to-execute flow with unchanged digest.

The vision seam adapts ``import_vision.build_vision_callable`` output to the
router seam shape — the same adaptation ``api_server._make_vision_callable``
performs (its behavior is pinned separately in ``test_import_router.py``);
here every component behind it is real (settings read, thumbnail gate, cache
orchestration) and only the LLM provider itself is faked.
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

from import_router import create_import_router  # noqa: E402
from import_service import ImportService  # noqa: E402
from import_store import ImportJobStore  # noqa: E402
from import_vision import build_vision_callable  # noqa: E402
from sync_lore.import_docx_parser import ExtractionResult  # noqa: E402
from sync_lore.schemas import ImageAnalysis, ImageEntry  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakePrincipal:
    def __init__(self, pid: str = "tester"):
        self.id = pid


class _CountingVisionProvider:
    """Deterministic provider; records every (thumbnail, context) call.

    One instance is constructed per ``analyze_images`` invocation (PR2), so
    the class-level ``instances`` list is the record of every provider ever
    built; summing ``calls`` across instances counts real provider traffic.
    """

    instances: list["_CountingVisionProvider"] = []

    def __init__(self, config) -> None:
        self.config = config
        self.calls: list[tuple[bytes, str]] = []
        self.instances.append(self)

    async def analyze_image(self, image: bytes, context: str):
        self.calls.append((image, context))
        return ImageAnalysis(
            descripcion="Retrato sombrío en claroscuro",
            veredicto="confirma",
            analisis="La imagen coincide con la descripción del texto.",
            tags=["retrato", "claroscuro"],
        )


class _BoomVisionProvider:
    """Fails every analysis — used for the fail-open path."""

    instances: list["_BoomVisionProvider"] = []

    def __init__(self, config) -> None:
        self.config = config
        self.instances.append(self)

    async def analyze_image(self, image: bytes, context: str):
        raise RuntimeError("vision provider down")


class _ThumbRecorder:
    """Returns a fixed thumbnail payload; records every request.

    The payload is opaque bytes (the fake provider never decodes it), so no
    image codecs are required anywhere in the test.
    """

    def __init__(self, payload: bytes = b"THUMB-300px-jpeg") -> None:
        self.calls: list[tuple[bytes, int]] = []
        self.payload = payload

    def __call__(self, image_bytes: bytes, width: int) -> bytes:
        self.calls.append((image_bytes, width))
        return self.payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(filename: str = "portada.png", data: bytes = b"PORTADA-BYTES",
           document_order: int = 0, paragraph_index: int = 0,
           anchor_type: str = "", structural_path: str = "",
           heading_path: str = "", context_text: str = "",
           warnings: list[str] | None = None) -> ImageEntry:
    return ImageEntry(
        id=str(uuid.uuid4()),
        source_file="Lore/Enciclopedia.docx",
        page=None, chunk_ref="", context_text=context_text,
        filename=filename, image_bytes=data,
        document_order=document_order,
        paragraph_index=paragraph_index,
        anchor_type=anchor_type,
        structural_path=structural_path,
        heading_path=heading_path,
        section_context=context_text,
        warnings=list(warnings or []),
    )


def _settings_file(tmp_path: Path, *, model_id: str = "gpt-5.6-luna") -> Path:
    """Hermes config.yaml with a multimodal assistant block (PR2 fixture)."""
    path = tmp_path / "config.yaml"
    body = (
        "model:\n"
        f"  default: {model_id}\n"
        "  provider: opencode-go\n"
        "  base_url: https://opencode.ai/zen/go/v1\n"
        "assistant_settings:\n"
        "  revision: 1\n"
        "  provider: opencode-go\n"
        "  base_url: https://opencode.ai/zen/go/v1\n"
        f"  model_id: {model_id}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def _provider_calls(provider_cls) -> int:
    """Total real provider calls across every instance ever constructed."""
    return sum(len(inst.calls) for inst in provider_cls.instances)


def _vision_seam(settings: Path, thumb, store, *, provider_cls):
    """Compose the REAL vision pipeline into the router seam shape.

    Mirrors ``api_server._make_vision_callable``'s adapter: runs the PR2
    ``analyze_images`` over the preserved media bundle and turns each result
    into an advisory ``vision:<sha256>`` suggestion on its owning candidate.
    Returns ``None`` for a text-only/unconfigured assistant — the router then
    runs without vision.
    """
    analyze_images = build_vision_callable(
        settings,
        generate_thumbnail=thumb,
        vision_cache_lookup=store.vision_cache_lookup,
        vision_cache_store=store.vision_cache_store,
    )
    if analyze_images is None:
        return None

    def vision(candidates, media_entries):
        if not candidates or not media_entries:
            return candidates
        try:
            results = analyze_images([m.image for m in media_entries], "")
        except Exception:  # noqa: BLE001 — vision is advisory, fail-open
            return candidates
        by_hash = {r.image_hash: r for r in results}
        by_candidate: dict[str, list[dict]] = {}
        for m in media_entries:
            result = by_hash.get(
                hashlib.sha256(m.image.image_bytes).hexdigest())
            if result is None:
                continue
            by_candidate.setdefault(m.candidate_id, []).append({
                "__type__": "vision",
                "id": f"vision:{result.image_hash}",
                "candidate_id": m.candidate_id,
                "relative_media_path": m.spool_relative_path,
                "description": result.description,
                "verdict": result.verdict,
                "analysis": result.analysis,
                "tags": list(result.tags),
                "confidence": 0.0,
                "provenance": {"provider": "vision", "capability": "multimodal"},
                "evidence": f"image:{m.spool_relative_path}",
                "review_state": "pending",
            })
        out: list = []
        for candidate in candidates:
            entries = by_candidate.get(candidate.candidate_id)
            if not entries:
                out.append(candidate)
                continue
            payload = (list(candidate.enrichment_json)
                       if candidate.enrichment_json else [])
            payload.extend(entries)
            out.append(candidate.model_copy(update={
                "enrichment_json": payload,
                "enrichment_status": "ok",
            }))
        return out

    return vision


def _app(tmp_path, *, vision=None, register_gallery=None, world="world1",
         store=None):
    """Real router + ImportService on a hermetic store/spool/world.

    The SAME store backs the job lifecycle AND the vision cache — matching
    production (the singleton ``api_server`` store provides both). Callers
    create the store first and pass it in so the vision seam can be composed
    with its cache before the router is built.
    """
    store = store or ImportJobStore(":memory:")
    spool = tmp_path / "spool"
    mundos = tmp_path / "mundos"
    (mundos / world / "lore").mkdir(parents=True, exist_ok=True)

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
    app.include_router(create_import_router(
        require_principal=lambda request: _FakePrincipal(),
        mundos_dir=lambda: mundos,
        spool_dir=lambda: spool,
        store=store,
        service=service,
        vision=vision,
    ))
    return TestClient(app), store, spool, mundos


def _create_job(client: TestClient, relative: str = "Lore/Enciclopedia.docx") -> dict:
    resp = client.post(
        "/api/world1/imports",
        json={"source_kind": "loose", "files": [relative]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["job"]


def _stream(client: TestClient, job_id: str, relative: str, data: bytes) -> None:
    resp = client.post(
        f"/api/world1/imports/{job_id}/stream",
        json={"relative": relative, "offset": 0,
              "data_b64": base64.b64encode(data).decode()},
    )
    assert resp.status_code == 200, resp.text


def _analyze(client: TestClient, job_id: str) -> dict:
    resp = client.post(f"/api/world1/imports/{job_id}/analyze", json=None)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _review(client: TestClient, job_id: str) -> dict:
    resp = client.get(f"/api/world1/imports/{job_id}/review")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _decide(client: TestClient, job_id: str, suggestion_id: str,
            decision: str) -> dict:
    resp = client.post(
        f"/api/world1/imports/{job_id}/review/decisions",
        json={"decisions": [{"suggestion_id": suggestion_id, "decision": decision}]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _approve(client: TestClient, job_id: str, group_ids, suggestion_ids) -> dict:
    body: dict = {"group_ids": list(group_ids)}
    if suggestion_ids:
        body["suggestion_ids"] = list(suggestion_ids)
    resp = client.post(f"/api/world1/imports/{job_id}/approve", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _execute(client: TestClient, job_id: str, digest: str, token: str,
             suggestion_ids) -> dict:
    body: dict = {"digest": digest, "token": token}
    if suggestion_ids:
        body["suggestion_ids"] = list(suggestion_ids)
    resp = client.post(f"/api/world1/imports/{job_id}/execute", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _vision_entries(candidate: dict) -> list[dict]:
    return [e for e in (candidate.get("enrichment_json") or [])
            if e.get("__type__") == "vision"]


def _events(store, job_id: str) -> list[str]:
    stored = store.get_job(job_id)
    obs = store.observability(stored.opaque_token)
    return [e["event"] for e in obs["events"]]

def _docx_seams(monkeypatch, entries, md_text):
    """Mock the lazy conversion + extraction seams for a .docx source.

    The converted markdown references the extracted images at their FLAT
    spool paths (``media/<file>`` — the DOCX parser's ``_image_ref`` form,
    without any source-stem prefix) so placements, vision suggestions, and
    the executor's gallery lookup all resolve to the same path (BUG 2a
    coverage WITHOUT the stem prefix). The strategy seam returns the mock
    entries and passes the converted markdown through unchanged (PR2
    dispatch through ``extract_by_extension``).
    """
    monkeypatch.setattr(
        "sync_lore.utils.converter.convert_to_markdown",
        lambda _p: md_text,
    )
    monkeypatch.setattr(
        "sync_lore.import_docx_parser.extract_by_extension",
        lambda _p, converted_markdown="": ExtractionResult(
            images=entries, markdown=converted_markdown),
    )


_DOCX_MD = (
    "---\ntype: personaje\nname: A\n---\n"
    "# Origen\n"
    "Body with context\n\n"
    "![retrato](media/portada.png)"
)


# ---------------------------------------------------------------------------
# Phase 9 — integration tests
# ---------------------------------------------------------------------------


class TestFullDocxVisionFlow:
    """Tasks 9.1/9.4/9.5/9.7 — .docx -> convert -> extract -> vision -> review
    -> approve -> execute -> gallery, with the original for the gallery and
    the thumbnail for vision."""

    def test_full_flow_approved_image_registers_gallery_with_alt_text(
            self, tmp_path, monkeypatch):
        """Task 9.1 + 9.4 — the full pipeline lands the approved original in
        the gallery and overlays the vision description as markdown alt-text."""
        _CountingVisionProvider.instances.clear()
        thumb = _ThumbRecorder()
        _docx_seams(monkeypatch, [_entry()], _DOCX_MD)
        monkeypatch.setattr(
            "sync_lore.providers.llm.LlmProvider", _CountingVisionProvider)

        registered: list[tuple[str, str, str, bytes]] = []
        store = ImportJobStore(":memory:")
        client, store, spool, mundos = _app(
            tmp_path,
            vision=_vision_seam(
                _settings_file(tmp_path), thumb, store,
                provider_cls=_CountingVisionProvider),
            register_gallery=lambda world, src, rel: registered.append(
                (world, str(src), rel, Path(src).read_bytes())),
            store=store,
        )

        # Analyze: conversion + extraction + vision run before persistence.
        job = _create_job(client)
        _stream(client, job["job_id"], "Lore/Enciclopedia.docx", b"PK..docx")
        result = _analyze(client, job["job_id"])
        assert result["job"]["state"] == "review"
        assert result["enrichment_status"] == "ok"

        # Vision suggestions ride in the review payload (advisory).
        review = _review(client, job["job_id"])
        cand = review["candidates"][0]
        vision = _vision_entries(cand)
        assert len(vision) == 1
        vid = vision[0]["id"]
        assert vision[0]["verdict"] == "confirma"
        assert vision[0]["relative_media_path"] == (
            "media/portada.png")
        assert vision[0]["review_state"] == "pending"

        # Approve the image suggestion and execute with the bound token.
        _decide(client, job["job_id"], vid, "approve")
        approval = _approve(client, job["job_id"], ["fichas", "imagenes"], [vid])
        executed = _execute(client, job["job_id"], approval["digest"],
                            approval["token"], [vid])
        assert executed["job"]["state"] == "completed"
        assert any(o["written"] for o in executed["outcomes"])

        # Gallery: the ORIGINAL spool bytes were registered (not the thumb).
        assert len(registered) == 1
        _, src, rel, original_bytes = registered[0]
        assert rel == "media/portada.png"
        assert src == str(
            spool / job["job_id"] / "media" / "portada.png")
        # The bytes are captured at registration time (during execute, before
        # the spool is reclaimed on the terminal COMPLETED transition) —
        # mirroring production's `_register_import_gallery` copy.
        assert original_bytes == b"PORTADA-BYTES"

        # The written ficha carries the vision description as alt-text.
        fichas = list((mundos / "world1").rglob("*.md"))
        assert fichas
        ficha_text = "".join(f.read_text(encoding="utf-8") for f in fichas)
        assert "![Retrato sombrío en claroscuro](media/portada.png)" in ficha_text
        assert "![retrato](media/portada.png)" not in ficha_text

        # The provider saw the 300px thumbnail, never the original bytes.
        assert _provider_calls(_CountingVisionProvider) == 1
        provider = _CountingVisionProvider.instances[-1]
        assert provider.calls[0][0] == b"THUMB-300px-jpeg"
        assert provider.calls[0][0] != b"PORTADA-BYTES"
        # The thumbnail generator received the ORIGINAL bytes at 300px.
        assert thumb.calls == [(b"PORTADA-BYTES", 300)]

    def test_thumbnail_used_for_vision_original_for_gallery(
            self, tmp_path, monkeypatch):
        """Task 9.7 — explicit proof of the boundary: vision never crosses
        originals; the gallery receives originals, not thumbnails."""
        _CountingVisionProvider.instances.clear()
        thumb = _ThumbRecorder(payload=b"THUMB-BYTES-NOT-ORIGINAL")
        _docx_seams(monkeypatch, [_entry(data=b"ORIGINAL-BYTES")], _DOCX_MD)
        monkeypatch.setattr(
            "sync_lore.providers.llm.LlmProvider", _CountingVisionProvider)

        registered: list[tuple[str, bytes]] = []
        store = ImportJobStore(":memory:")
        client, store, spool, mundos = _app(
            tmp_path,
            vision=_vision_seam(
                _settings_file(tmp_path), thumb, store,
                provider_cls=_CountingVisionProvider),
            register_gallery=lambda world, src, rel: registered.append(
                (rel, Path(src).read_bytes())),
            store=store,
        )

        job = _create_job(client)
        _stream(client, job["job_id"], "Lore/Enciclopedia.docx", b"PK..docx")
        _analyze(client, job["job_id"])
        review = _review(client, job["job_id"])
        vid = _vision_entries(review["candidates"][0])[0]["id"]

        _decide(client, job["job_id"], vid, "approve")
        approval = _approve(client, job["job_id"], ["imagenes"], [vid])
        _execute(client, job["job_id"], approval["digest"], approval["token"], [vid])

        # Vision boundary: thumbnail generator got originals, provider got
        # thumbnails only.
        assert thumb.calls == [(b"ORIGINAL-BYTES", 300)]
        provider = _CountingVisionProvider.instances[-1]
        assert provider.calls[0][0] == b"THUMB-BYTES-NOT-ORIGINAL"
        assert b"ORIGINAL-BYTES" not in provider.calls[0][0]

        # Gallery boundary: the registered file is the ORIGINAL spool bytes,
        # captured at registration time (during execute, before the spool is
        # reclaimed on the terminal COMPLETED transition).
        assert registered == [("media/portada.png", b"ORIGINAL-BYTES")]

    def test_rejected_image_not_registered_import_continues(
            self, tmp_path, monkeypatch):
        """Tasks 9.5 — reject one image, approve another: only the approved
        original reaches the gallery; the rejected one is not registered and
        the import completes."""
        _CountingVisionProvider.instances.clear()
        thumb = _ThumbRecorder()
        md = (
            "---\ntype: personaje\nname: A\n---\n# Origen\nBody\n\n"
            "![retrato](media/portada.png)\n\n"
            "![mapa](media/mapa.png)"
        )
        _docx_seams(monkeypatch, [
            _entry(filename="portada.png", data=b"PORTADA-BYTES"),
            _entry(filename="mapa.png", data=b"MAPA-BYTES"),
        ], md)
        monkeypatch.setattr(
            "sync_lore.providers.llm.LlmProvider", _CountingVisionProvider)

        registered: list[str] = []
        store = ImportJobStore(":memory:")
        client, store, spool, mundos = _app(
            tmp_path,
            vision=_vision_seam(
                _settings_file(tmp_path), thumb, store,
                provider_cls=_CountingVisionProvider),
            register_gallery=lambda world, src, rel: registered.append(rel),
            store=store,
        )

        job = _create_job(client)
        _stream(client, job["job_id"], "Lore/Enciclopedia.docx", b"PK..docx")
        _analyze(client, job["job_id"])
        review = _review(client, job["job_id"])
        vision = _vision_entries(review["candidates"][0])
        assert len(vision) == 2
        by_path = {v["relative_media_path"]: v["id"] for v in vision}
        vid_portada = by_path["media/portada.png"]
        vid_mapa = by_path["media/mapa.png"]

        # Independent decisions: approve the portrait, reject the map.
        _decide(client, job["job_id"], vid_portada, "approve")
        _decide(client, job["job_id"], vid_mapa, "reject")
        approval = _approve(client, job["job_id"], ["imagenes"], [vid_portada])
        executed = _execute(client, job["job_id"], approval["digest"],
                            approval["token"], [vid_portada])
        assert executed["job"]["state"] == "completed"
        assert any(o["written"] for o in executed["outcomes"])

        # Only the approved image is registered.
        assert registered == ["media/portada.png"]

        # The approved image's description overlays its alt-text exactly once;
        # the rejected image keeps its original markdown ref and its vision
        # description was NEVER overlaid (source fidelity + no write).
        fichas = list((mundos / "world1").rglob("*.md"))
        ficha_text = "".join(f.read_text(encoding="utf-8") for f in fichas)
        assert ficha_text.count(
            "![Retrato sombrío en claroscuro](media/portada.png)") == 1
        assert "![mapa](media/mapa.png)" in ficha_text
        assert "![Retrato sombrío en claroscuro](media/mapa.png)" not in ficha_text


class TestVisionSkipAndFailure:
    """Tasks 9.2/9.3/9.6 — text-only and failing vision never block imports."""

    def test_text_only_assistant_skips_vision_import_works(
            self, tmp_path, monkeypatch):
        """Task 9.3 — a text-only model yields no vision callable; analyze and
        execute continue exactly as the legacy flow."""
        _docx_seams(monkeypatch, [_entry()], _DOCX_MD)
        # deepseek-v4-flash is text-only in the catalog -> vision=None.
        store = ImportJobStore(":memory:")
        vision = _vision_seam(
            _settings_file(tmp_path, model_id="deepseek-v4-flash"),
            _ThumbRecorder(), store, provider_cls=_CountingVisionProvider)
        assert vision is None

        client, store, spool, mundos = _app(tmp_path, vision=vision, store=store)
        job = _create_job(client)
        _stream(client, job["job_id"], "Lore/Enciclopedia.docx", b"PK..docx")
        result = _analyze(client, job["job_id"])
        assert result["job"]["state"] == "review"
        assert result["enrichment_status"] == "disabled"

        review = _review(client, job["job_id"])
        assert _vision_entries(review["candidates"][0]) == []
        assert not any(e.startswith("vision_error") for e in _events(store, job["job_id"]))

        # The import still executes (image placed with its fallback alt-text).
        approval = _approve(client, job["job_id"], ["fichas", "imagenes"], [])
        executed = _execute(client, job["job_id"], approval["digest"],
                            approval["token"], [])
        assert executed["job"]["state"] == "completed"
        fichas = list((mundos / "world1").rglob("*.md"))
        ficha_text = "".join(f.read_text(encoding="utf-8") for f in fichas)
        assert "![retrato](media/portada.png)" in ficha_text

    def test_vision_failure_fails_open_import_continues(
            self, tmp_path, monkeypatch):
        """Tasks 9.2/9.6 — the provider exploding leaves candidates persisted
        without vision data; the job stays reviewable and executes."""
        _BoomVisionProvider.instances.clear()
        _docx_seams(monkeypatch, [_entry()], _DOCX_MD)
        monkeypatch.setattr(
            "sync_lore.providers.llm.LlmProvider", _BoomVisionProvider)

        store = ImportJobStore(":memory:")
        client, store, spool, mundos = _app(
            tmp_path,
            vision=_vision_seam(
                _settings_file(tmp_path), _ThumbRecorder(), store,
                provider_cls=_BoomVisionProvider),
            store=store,
        )
        job = _create_job(client)
        _stream(client, job["job_id"], "Lore/Enciclopedia.docx", b"PK..docx")
        result = _analyze(client, job["job_id"])
        assert result["job"]["state"] == "review"
        assert result["enrichment_status"] == "disabled"

        # No vision data landed, no vision error event surfaced (the seam
        # fails open inside the PR2 pipeline), and the candidate persisted.
        cand = store.candidates_for(job["job_id"])[0]
        assert _vision_entries(cand.model_dump()) == []
        assert not any(e.startswith("vision_error") for e in _events(store, job["job_id"]))

        # Import continues: approve + execute succeed without vision data.
        review = _review(client, job["job_id"])
        digest = review["digest"]
        approval = _approve(client, job["job_id"], ["fichas", "imagenes"], [])
        executed = _execute(client, job["job_id"], digest, approval["token"], [])
        assert executed["job"]["state"] == "completed"

    def test_vision_seam_exception_records_event_and_persists(
            self, tmp_path, monkeypatch):
        """Task 9.2 — a seam-level exception is the router's fail-open path:
        diagnostic event recorded, candidates persisted unchanged."""
        _docx_seams(monkeypatch, [_entry()], _DOCX_MD)

        def boom(candidates, media_entries):
            raise RuntimeError("seam exploded")

        client, store, spool, mundos = _app(tmp_path, vision=boom)
        job = _create_job(client)
        _stream(client, job["job_id"], "Lore/Enciclopedia.docx", b"PK..docx")
        result = _analyze(client, job["job_id"])
        assert result["job"]["state"] == "review"
        assert store.candidates_for(job["job_id"])
        assert any(e.startswith("vision_error:") for e in _events(store, job["job_id"]))


class TestVisionCacheAndDigest:
    """Tasks 9.4/9.7 (tasks doc) — the content cache skips the provider on
    re-import and the digest never depends on vision."""

    def test_cache_hit_on_reimport_no_second_provider_call(
            self, tmp_path, monkeypatch):
        """Task 9.4 — analyzing the same job twice (same image bytes) hits the
        vision cache: the provider is never called a second time and the
        cached description is reused on review."""
        _CountingVisionProvider.instances.clear()
        thumb = _ThumbRecorder()
        _docx_seams(monkeypatch, [_entry()], _DOCX_MD)
        monkeypatch.setattr(
            "sync_lore.providers.llm.LlmProvider", _CountingVisionProvider)

        store = ImportJobStore(":memory:")
        client, store, spool, mundos = _app(
            tmp_path,
            vision=_vision_seam(
                _settings_file(tmp_path), thumb, store,
                provider_cls=_CountingVisionProvider),
            store=store,
        )

        job = _create_job(client)
        _stream(client, job["job_id"], "Lore/Enciclopedia.docx", b"PK..docx")

        # First analyze: cache miss -> one provider call, result stored.
        _analyze(client, job["job_id"])
        assert _provider_calls(_CountingVisionProvider) == 1

        # Re-analyze the same job: same bytes -> cache hit -> NO provider call
        # and no thumbnail regeneration for the cached image.
        thumb.calls.clear()
        _analyze(client, job["job_id"])
        assert _provider_calls(_CountingVisionProvider) == 1
        assert thumb.calls == []

        # The cached result is what the reviewer sees (persisted enrichment).
        review = _review(client, job["job_id"])
        vision = _vision_entries(review["candidates"][0])
        assert len(vision) == 1
        assert vision[0]["description"] == "Retrato sombrío en claroscuro"

    def test_digest_unchanged_by_vision_or_decisions(
            self, tmp_path, monkeypatch):
        """Tasks 9.7 (doc) — the review digest covers identity+source_hash
        only: vision suggestions and reviewer decisions never alter it."""
        _CountingVisionProvider.instances.clear()
        thumb = _ThumbRecorder()
        _docx_seams(monkeypatch, [_entry()], _DOCX_MD)
        monkeypatch.setattr(
            "sync_lore.providers.llm.LlmProvider", _CountingVisionProvider)

        store = ImportJobStore(":memory:")
        client, store, spool, mundos = _app(
            tmp_path,
            vision=_vision_seam(
                _settings_file(tmp_path), thumb, store,
                provider_cls=_CountingVisionProvider),
            store=store,
        )

        job = _create_job(client)
        _stream(client, job["job_id"], "Lore/Enciclopedia.docx", b"PK..docx")
        _analyze(client, job["job_id"])

        digest_before = _review(client, job["job_id"])["digest"]
        assert digest_before

        # Reviewer decisions + vision suggestions never move the digest: the
        # approve binds the SAME digest and execute validates it successfully.
        review = _review(client, job["job_id"])
        vid = _vision_entries(review["candidates"][0])[0]["id"]
        _decide(client, job["job_id"], vid, "approve")
        digest_after = _review(client, job["job_id"])["digest"]
        assert digest_after == digest_before

        # The bound approval carries the reviewed digest and the execute
        # accepts it — if vision or decisions had touched the digest, the
        # token validation would have failed closed with 409.
        approval = _approve(client, job["job_id"], ["fichas", "imagenes"], [vid])
        assert approval["digest"] == digest_before
        executed = _execute(client, job["job_id"], digest_before,
                            approval["token"], [vid])
        assert executed["job"]["state"] == "completed"


class TestConversionFailureSurvival:
    """Task 9.6 (doc) — conversion failures never kill the server."""

    def test_converter_systemexit_does_not_terminate_server(
            self, tmp_path, monkeypatch):
        """A converter raising SystemExit (markitdown missing) never kills the
        server: the request returns 200 and the job lands in FAILED with a
        clear message and a diagnostic event — never a silent empty REVIEW."""
        _docx_seams(monkeypatch, [], _DOCX_MD)
        # Force the lazy converter import path to raise SystemExit.
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown",
            lambda _p: (_ for _ in ()).throw(SystemExit(1)),
        )

        client, store, spool, mundos = _app(tmp_path, vision=None)
        job = _create_job(client)
        _stream(client, job["job_id"], "Lore/Enciclopedia.docx", b"PK..docx")
        result = _analyze(client, job["job_id"])
        # Server alive: the request returns 200 and the job is FAILED with a
        # clear error (no silent empty preview reaching REVIEW).
        stored = store.get_job(job["job_id"])
        assert stored.state.value == "failed"
        # SystemExit (markitdown missing) => conversion_unavailable => the
        # message must name the missing converter, not guess a corrupt file.
        assert "Conversion unavailable" in stored.error
        assert "markitdown[docx]" in stored.error
        assert store.candidates_for(job["job_id"]) == []
        assert "failed:conversion" in _events(store, job["job_id"])
        # A new request still works (the server process survived the SystemExit).
        job2 = _create_job(client)
        assert job2["job_id"] != job["job_id"]


class TestPdfFlow:
    """Tasks 9.7 (doc) — the PDF path goes through the same seam with the same
    identity normalization and a stable digest."""

    _PDF_MD = (
        "---\ntype: lugar\nname: Manual\n---\n"
        "# Manual\n"
        "Body of the manual\n\n"
        "![diagrama](media/diagrama.png)"
    )

    def test_pdf_review_to_execute_digest_unchanged(self, tmp_path, monkeypatch):
        _CountingVisionProvider.instances.clear()
        thumb = _ThumbRecorder()
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown",
            lambda _p: self._PDF_MD,
        )
        monkeypatch.setattr(
            "import_analysis.extract_images_from_file",
            lambda _p: [_entry(filename="diagrama.png", data=b"DIAGRAMA-BYTES")],
        )
        monkeypatch.setattr(
            "sync_lore.providers.llm.LlmProvider", _CountingVisionProvider)

        registered: list[str] = []
        store = ImportJobStore(":memory:")
        client, store, spool, mundos = _app(
            tmp_path,
            vision=_vision_seam(
                _settings_file(tmp_path), thumb, store,
                provider_cls=_CountingVisionProvider),
            register_gallery=lambda world, src, rel: registered.append(rel),
            store=store,
        )

        job = _create_job(client, relative="Lore/Manual.pdf")
        _stream(client, job["job_id"], "Lore/Manual.pdf", b"%PDF-fake")
        _analyze(client, job["job_id"])

        # The converted identity keeps the .md suffix (PR1 rule).
        cand = store.candidates_for(job["job_id"])[0]
        assert cand.provenance.source_path == "Lore/Manual.md"

        review = _review(client, job["job_id"])
        digest = review["digest"]
        vid = _vision_entries(review["candidates"][0])[0]["id"]

        _decide(client, job["job_id"], vid, "approve")
        # Vision + decisions never move the digest: the approval binds the
        # reviewed digest and execute validates it (a moved digest would 409).
        approval = _approve(client, job["job_id"], ["fichas", "imagenes"], [vid])
        assert approval["digest"] == digest
        executed = _execute(client, job["job_id"], digest, approval["token"], [vid])
        assert executed["job"]["state"] == "completed"
        assert registered == ["media/diagrama.png"]
        fichas = list((mundos / "world1").rglob("*.md"))
        ficha_text = "".join(f.read_text(encoding="utf-8") for f in fichas)
        assert "![Retrato sombrío en claroscuro](media/diagrama.png)" in ficha_text


class TestDocxPositionPropagation:
    """PR2 (docx-image-extraction) — scenario R3-S1: the DOCX position
    contract survives ``analyze_source → spool → candidate persistence →
    review`` and is visible in the serialized review payload."""

    _MD = (
        "---\ntype: personaje\nname: A\n---\n"
        "# Origen\n"
        "Body with context\n\n"
        "![retrato](media/portada.png)"
    )

    def test_review_payload_carries_position_fields(
            self, tmp_path, monkeypatch):
        _CountingVisionProvider.instances.clear()
        thumb = _ThumbRecorder()
        entry = _entry(
            filename="portada.png",
            document_order=1, paragraph_index=1, anchor_type="inline",
            structural_path="body/p[1]/r[0]/inline[0]",
            heading_path="Origen", context_text="Body with context",
            warnings=["media part 'word/media/x.png' missing; skipped"],
        )
        _docx_seams(monkeypatch, [entry], self._MD)
        monkeypatch.setattr(
            "sync_lore.providers.llm.LlmProvider", _CountingVisionProvider)

        store = ImportJobStore(":memory:")
        client, store, spool, _ = _app(
            tmp_path,
            vision=_vision_seam(
                _settings_file(tmp_path), thumb, store,
                provider_cls=_CountingVisionProvider),
            store=store,
        )
        job = _create_job(client)
        _stream(client, job["job_id"], "Lore/Enciclopedia.docx", b"PK..docx")
        _analyze(client, job["job_id"])
        review = _review(client, job["job_id"])
        cand = review["candidates"][0]
        placements = cand["images"]
        # One candidate per DOCX, one placement for the referenced image.
        assert len(review["candidates"]) == 1
        assert len(placements) == 1
        placement = placements[0]
        assert placement["relative_media_path"] == (
            "media/portada.png")
        # The position contract survives persistence + review serialization.
        assert placement["document_order"] == 1
        assert placement["paragraph_index"] == 1
        assert placement["anchor_type"] == "inline"
        assert placement["structural_path"] == "body/p[1]/r[0]/inline[0]"
        assert placement["heading_path"] == "Origen"
        assert placement["context_text"] == "Body with context"
        assert placement["warnings"] == [
            "media part 'word/media/x.png' missing; skipped"]