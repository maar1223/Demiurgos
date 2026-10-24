# -*- coding: utf-8 -*-
"""Chat document attachments — bounded store and fail-safe extraction (S2/S3/S10).

Real conversion is exercised with generated ``.docx``/``.pdf`` fixtures when
the optional extras are importable; the dependency-absent and conversion-failure
paths are simulated so the degradation contract is pinned without them.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
_TOOLS = _SUITE.parent
for _p in (str(_WIKI), str(_SUITE), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import chat_attachments  # noqa: E402
import api_server  # noqa: E402
from chat_attachments import (  # noqa: E402
    ATTACHMENT_TTL_SECONDS,
    MAX_ATTACHMENT_FILE_BYTES,
    MAX_ATTACHMENT_TEXT_CHARS,
    MAX_STORED_ATTACHMENTS,
    ChatAttachmentError,
    ChatAttachmentStore,
    extract_attachment,
)

_PDF_BYTES = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 44>>stream
BT /F1 18 Tf 72 700 Td (Hola desde un PDF.) Tj ET
endstream
endobj
trailer<</Root 1 0 R>>
%%EOF
"""


def _docx_bytes(*paragraphs: str) -> bytes:
    docx = pytest.importorskip("docx")
    from io import BytesIO

    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_unsupported_suffix_is_rejected():
    with pytest.raises(ChatAttachmentError) as info:
        extract_attachment("notes.txt", b"plain text")
    assert info.value.code == "attachment.unsupported_type"
    assert info.value.status == 422


def test_oversized_file_is_rejected_before_conversion():
    with pytest.raises(ChatAttachmentError) as info:
        extract_attachment("big.pdf", b"x" * (MAX_ATTACHMENT_FILE_BYTES + 1))
    assert info.value.code == "attachment.too_large"
    assert info.value.status == 413


def test_empty_extraction_is_rejected(monkeypatch):
    monkeypatch.setattr(chat_attachments, "_convert_bytes", lambda *_: "   \n\n  ")
    with pytest.raises(ChatAttachmentError) as info:
        extract_attachment("empty.docx", b"anything")
    assert info.value.code == "attachment.empty"
    assert info.value.status == 422


def test_conversion_unavailable_when_dependency_is_missing(monkeypatch):
    def _missing(*_args, **_kwargs):
        raise chat_attachments.ChatAttachmentError(
            "attachment.conversion_unavailable", 422, "unavailable"
        )

    monkeypatch.setattr(chat_attachments, "_convert_bytes", _missing)
    with pytest.raises(ChatAttachmentError) as info:
        extract_attachment("doc.pdf", b"%PDF-1.4")
    assert info.value.code == "attachment.conversion_unavailable"


def test_conversion_failure_is_reported_not_raised(monkeypatch):
    def _explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(chat_attachments, "_convert_bytes", _explode)
    with pytest.raises(ChatAttachmentError) as info:
        extract_attachment("doc.docx", b"anything")
    assert info.value.code == "attachment.conversion_failed"


def test_docx_text_is_extracted():
    pytest.importorskip("mammoth")
    text, chars, truncated = extract_attachment(
        "Personaje.docx", _docx_bytes("Kael el Errante", "Vive en las alturas.")
    )
    assert "Kael el Errante" in text
    assert "Vive en las alturas." in text
    assert chars == len(text)
    assert truncated is False


def test_pdf_text_is_extracted():
    pytest.importorskip("pdfminer")
    text, chars, truncated = extract_attachment("Documento.pdf", _PDF_BYTES)
    assert "Hola desde un PDF" in text
    assert chars == len(text)
    assert truncated is False


def test_data_uri_image_placeholders_are_removed(monkeypatch):
    payload = (
        "# Titulo\n\n![foto](data:image/png;base64,AAAA)\n\n"
        "![rota](data:image/png;base64...)\n\nCuerpo real.\n"
    )
    monkeypatch.setattr(chat_attachments, "_convert_bytes", lambda *_: payload)
    text, _chars, _truncated = extract_attachment("doc.docx", b"x")
    assert "data:image" not in text
    assert "Titulo" in text
    assert "Cuerpo real." in text


def test_long_text_is_truncated_with_a_marker(monkeypatch):
    payload = "a" * (MAX_ATTACHMENT_TEXT_CHARS + 500)
    monkeypatch.setattr(chat_attachments, "_convert_bytes", lambda *_: payload)
    text, chars, truncated = extract_attachment("doc.docx", b"x")
    assert truncated is True
    assert chars == MAX_ATTACHMENT_TEXT_CHARS + 500
    assert text.startswith("a" * MAX_ATTACHMENT_TEXT_CHARS)
    assert "truncado" in text
    assert len(text) < chars


def test_store_round_trips_an_attachment():
    store = ChatAttachmentStore(clock=_Clock())
    record = store.put(name="doc.pdf", kind="pdf", text="Hola", chars=4, truncated=False)
    fetched = store.get(record.id)
    assert fetched is not None
    assert fetched.name == "doc.pdf"
    assert fetched.text == "Hola"
    assert store.get("missing") is None


def test_store_expires_entries_after_the_ttl():
    clock = _Clock()
    store = ChatAttachmentStore(clock=clock)
    record = store.put(name="doc.pdf", kind="pdf", text="Hola", chars=4, truncated=False)
    clock.now += ATTACHMENT_TTL_SECONDS + 1
    assert store.get(record.id) is None


def test_store_evicts_the_oldest_entry_beyond_capacity():
    clock = _Clock()
    store = ChatAttachmentStore(clock=clock)
    ids = []
    for index in range(MAX_STORED_ATTACHMENTS + 1):
        clock.now += 1
        ids.append(
            store.put(
                name=f"doc{index}.pdf",
                kind="pdf",
                text="Hola",
                chars=4,
                truncated=False,
            ).id
        )
    assert store.get(ids[0]) is None
    assert store.get(ids[-1]) is not None


# ---------------------------------------------------------------------------
# Endpoint: POST /api/{mundo}/ai/attachments
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    import api_server

    mundos = tmp_path / "mundos"
    world = mundos / "test_mundo"
    (world / "lore").mkdir(parents=True)
    (world / "lore" / "00_inicio.md").write_text(
        "---\ntype: criatura\ntitle: Inicio\n---\n# Inicio\n", encoding="utf-8"
    )
    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", None)
    chat_attachments.ATTACHMENTS.clear()
    yield TestClient(api_server.app, client=("127.0.0.1", 50000))
    chat_attachments.ATTACHMENTS.clear()


def _upload(client, filename: str, data: bytes, mundo: str = "test_mundo"):
    return client.post(
        f"/api/{mundo}/ai/attachments",
        files={"file": (filename, data, "application/octet-stream")},
    )


def test_upload_returns_the_attachment_contract(client):
    pytest.importorskip("mammoth")
    response = _upload(client, "Personaje.docx", _docx_bytes("Kael el Errante"))
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"id", "name", "kind", "chars", "truncated"}
    assert body["name"] == "Personaje.docx"
    assert body["kind"] == "docx"
    assert body["truncated"] is False
    assert body["chars"] > 0
    assert chat_attachments.ATTACHMENTS.get(body["id"]) is not None


def test_upload_accepts_the_global_assistant_context(client):
    pytest.importorskip("mammoth")
    response = _upload(client, "Idea.docx", _docx_bytes("Una idea"), mundo="ideas-global")
    assert response.status_code == 201, response.text


def test_upload_rejects_an_unknown_world(client):
    response = _upload(client, "doc.docx", b"x", mundo="no_such_world")
    assert response.status_code == 404
    assert response.json()["code"] == "world.not_found"


def test_upload_rejects_an_unsupported_type(client):
    response = _upload(client, "notes.txt", b"plain text")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "attachment.unsupported_type"


def test_upload_rejects_an_oversized_file(client, monkeypatch):
    monkeypatch.setattr(chat_attachments, "MAX_ATTACHMENT_FILE_BYTES", 8)
    response = _upload(client, "big.pdf", b"x" * 32)
    assert response.status_code == 413
    assert response.json()["code"] == "attachment.too_large"


def test_upload_reports_conversion_unavailable(client, monkeypatch):
    def _unavailable(*_args, **_kwargs):
        raise chat_attachments.ChatAttachmentError(
            "attachment.conversion_unavailable", 422, "unavailable"
        )

    monkeypatch.setattr(chat_attachments, "_convert_bytes", _unavailable)
    response = _upload(client, "doc.pdf", b"%PDF-1.4")
    assert response.status_code == 422
    assert response.json()["code"] == "attachment.conversion_unavailable"


def test_rejected_upload_stores_nothing(client):
    response = _upload(client, "notes.txt", b"plain text")
    assert response.status_code == 422
    assert len(chat_attachments.ATTACHMENTS) == 0


# ---------------------------------------------------------------------------
# Ask wiring: S4 (prompt context), S5 (grounded answer), S7 (expiry), S8 (memory)
# ---------------------------------------------------------------------------


class _CapturingSemanticProvider:
    """Minimal semantic provider that records the gate prompt it receives."""

    def __init__(self, state: str = "allow") -> None:
        self.state = state
        self.prompts: list[str] = []

    async def decide(self, prompt, *, request_id, session_id=None, context=None,
                     distilled_state=None, recent_turns=None):
        from semantic_intent import SemanticDecision, SemanticResult

        self.prompts.append(prompt)
        return SemanticResult(
            decision=SemanticDecision(
                state=self.state,  # type: ignore[arg-type]
                response="Answer about the attached document.",
                request_id=request_id,
            ),
            attempts=1,
            request_id=request_id,
            session_id=session_id,
        )


class _CapturingActivityAdapter:
    """Activity adapter that records the run request and exposes no events."""

    def __init__(self) -> None:
        from assistant_activity import CapabilityAssessment

        self.available = True
        self.capability = CapabilityAssessment(True, "", None)
        self.requests = []

    async def probe(self):
        return self.capability

    def start(self, request):
        self.requests.append(request)
        return "run-1"

    def events(self, run_id):
        async def _empty():
            if False:  # pragma: no cover - keeps this an async generator
                yield {}

        return _empty()

    def status(self, run_id):
        return {"status": "running"}


def _store_attachment(text: str = "El dragon vive en el norte.", name: str = "doc.pdf"):
    return chat_attachments.ATTACHMENTS.put(
        name=name, kind="pdf", text=text, chars=len(text), truncated=False
    )


def test_prompt_includes_the_attachment_body_and_header():
    import api_server

    record = chat_attachments.ChatAttachment(
        id="a1", name="doc.pdf", kind="pdf",
        text="El dragon vive en el norte.", chars=29, truncated=False,
        created_at=0.0,
    )
    prompt = api_server._build_ai_ask_prompt(
        "test_mundo",
        api_server.AskRequest(prompt="¿Donde vive el dragon?"),
        attachments=[record],
    )
    assert "El dragon vive en el norte." in prompt
    assert "doc.pdf" in prompt
    assert "¿Donde vive el dragon?" in prompt
    assert prompt.index("El dragon vive en el norte.") < prompt.index("¿Donde vive el dragon?")


def test_prompt_marks_a_truncated_attachment():
    import api_server

    record = chat_attachments.ChatAttachment(
        id="a1", name="doc.pdf", kind="pdf",
        text="Texto recortado.[…truncado: se muestran 30 de 50000 caracteres]",
        chars=50000, truncated=True, created_at=0.0,
    )
    prompt = api_server._build_ai_ask_prompt(
        "test_mundo",
        api_server.AskRequest(prompt="Resume"),
        attachments=[record],
    )
    assert "truncado" in prompt
    assert "50000" in prompt


def test_gate_receives_only_attachment_metadata(client, monkeypatch):
    provider = _CapturingSemanticProvider()
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", provider)
    record = _store_attachment(text="Contenido secreto del documento.")
    response = client.post(
        "/api/test_mundo/ai/ask",
        json={"prompt": "¿Que dice?", "attachment_ids": [record.id]},
    )
    assert response.status_code == 200, response.text
    assert provider.prompts, "the gate never ran"
    gate_prompt = provider.prompts[0]
    assert "doc.pdf" in gate_prompt
    assert "Contenido secreto del documento." not in gate_prompt


def test_activity_run_receives_the_attachment_text(client, monkeypatch):
    provider = _CapturingSemanticProvider()
    adapter = _CapturingActivityAdapter()
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", provider)
    monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
    record = _store_attachment(text="Contenido que el modelo debe leer.")
    response = client.post(
        "/api/test_mundo/ai/ask/activity",
        json={"prompt": "¿Que dice?", "attachment_ids": [record.id]},
    )
    assert response.status_code == 200, response.text
    assert adapter.requests, "the activity run never started"
    assert "Contenido que el modelo debe leer." in adapter.requests[0].prompt


def test_unknown_attachment_id_is_rejected_before_any_provider_call(client, monkeypatch):
    provider = _CapturingSemanticProvider()
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", provider)
    response = client.post(
        "/api/test_mundo/ai/ask",
        json={"prompt": "¿Que dice?", "attachment_ids": ["expired-id"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "attachment.expired"
    assert provider.prompts == []


def test_activity_rejects_an_unknown_attachment_id(client, monkeypatch):
    adapter = _CapturingActivityAdapter()
    monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
    response = client.post(
        "/api/test_mundo/ai/ask/activity",
        json={"prompt": "¿Que dice?", "attachment_ids": ["expired-id"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "attachment.expired"
    assert adapter.requests == []


def test_too_many_attachments_are_rejected(client, monkeypatch):
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", _CapturingSemanticProvider())
    ids = [_store_attachment(name=f"doc{index}.pdf").id for index in range(6)]
    response = client.post(
        "/api/test_mundo/ai/ask",
        json={"prompt": "Resume", "attachment_ids": ids},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "attachment.too_many"


def test_memory_user_prompt_keeps_names_only():
    import api_server

    record = chat_attachments.ChatAttachment(
        id="a1", name="doc.pdf", kind="pdf",
        text="Contenido privado del documento.", chars=31, truncated=False,
        created_at=0.0,
    )
    persisted = api_server._memory_user_prompt("Resume esto", [record])
    assert persisted.startswith("Resume esto")
    assert "doc.pdf" in persisted
    assert "Contenido privado del documento." not in persisted


def test_extraction_never_leaves_a_temporary_file_behind():
    pytest.importorskip("mammoth")
    import tempfile

    before = set(Path(tempfile.gettempdir()).iterdir())
    extract_attachment("Temporal.docx", _docx_bytes("Contenido"))
    after = set(Path(tempfile.gettempdir()).iterdir())
    leftovers = {
        path for path in after - before if path.name.startswith("demiurgos-chat-attachment")
    }
    assert leftovers == set()


def test_spec_machine_codes_are_exact(client, monkeypatch):
    r = _upload(client, "notes.txt", b"x")
    assert (r.status_code, r.json()["code"]) == (422, "attachment.unsupported_type")
    monkeypatch.setattr(chat_attachments, "MAX_ATTACHMENT_FILE_BYTES", 8)
    r = _upload(client, "big.pdf", b"x" * 32)
    assert (r.status_code, r.json()["code"]) == (413, "attachment.too_large")
    monkeypatch.setattr(chat_attachments, "_convert_bytes", lambda *_: "   ")
    r = _upload(client, "empty.docx", b"x")
    assert (r.status_code, r.json()["code"]) == (422, "attachment.empty")
    r = client.post(
        "/api/test_mundo/ai/ask",
        json={"prompt": "x", "attachment_ids": ["gone"]},
    )
    assert (r.status_code, r.json()["code"]) == (409, "attachment.expired")


def test_long_valid_docx_filename_is_accepted(client):
    pytest.importorskip("docx")
    response = _upload(client, "a" * 250 + ".docx", _docx_bytes("Kael"))
    assert response.status_code == 201, response.text
    assert response.json()["kind"] == "docx"
    assert response.json()["name"].endswith(".docx")
    assert len(response.json()["name"]) < 200


def test_missing_pdf_extra_is_conversion_unavailable(monkeypatch):
    exceptions = pytest.importorskip("markitdown._exceptions")

    def fake_convert(_path):
        raise exceptions.MissingDependencyException("pdf extra missing")

    monkeypatch.setattr("sync_lore.utils.converter.convert_to_markdown", fake_convert)
    with pytest.raises(ChatAttachmentError) as info:
        extract_attachment("doc.pdf", b"%PDF-1.4")
    assert info.value.code == "attachment.conversion_unavailable"
    assert info.value.status == 422


# ---------------------------------------------------------------------------
# T2 — Image attachments (S11-S16)
# ---------------------------------------------------------------------------

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_image_suffixes_are_supported():
    for name in ("foto.png", "foto.JPG", "foto.jpeg", "foto.webp", "foto.gif"):
        display, kind = chat_attachments.normalize_attachment_name(name)
        assert kind == "image"
        assert display.lower().endswith(Path(display).suffix.lower())


def test_image_upload_returns_the_generated_description(client, monkeypatch):
    async def _describe(image_bytes, **kwargs):
        assert image_bytes == _PNG_1X1
        assert kwargs["generate_thumbnail"] is not None
        return "Un faro rojo sobre un acantilado, con texto visible: VIBRANTES."

    monkeypatch.setattr(api_server, "describe_chat_image", _describe)
    response = _upload(client, "faro.png", _PNG_1X1)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "image"
    assert body["chars"] == len("Un faro rojo sobre un acantilado, con texto visible: VIBRANTES.")
    stored = chat_attachments.ATTACHMENTS.get(body["id"])
    assert stored is not None
    assert "VIBRANTES" in stored.text


def test_image_upload_without_vision_is_rejected_and_stores_nothing(client, monkeypatch):
    async def _unavailable(*args, **kwargs):
        raise ChatAttachmentError("attachment.vision_unavailable", 422, "no vision")

    monkeypatch.setattr(api_server, "describe_chat_image", _unavailable)
    response = _upload(client, "faro.png", _PNG_1X1)

    assert response.status_code == 422
    assert response.json()["code"] == "attachment.vision_unavailable"
    assert len(chat_attachments.ATTACHMENTS) == 0


def test_image_upload_provider_failure_is_vision_failed(client, monkeypatch):
    async def _failed(*args, **kwargs):
        raise ChatAttachmentError("attachment.vision_failed", 502, "down")

    monkeypatch.setattr(api_server, "describe_chat_image", _failed)
    response = _upload(client, "faro.png", _PNG_1X1)

    assert response.status_code == 502
    assert response.json()["code"] == "attachment.vision_failed"


def test_prompt_labels_an_image_description_as_vision_generated():
    record = chat_attachments.ChatAttachment(
        id="i1", name="faro.png", kind="image",
        text="Un faro rojo.", chars=14, truncated=False, created_at=0.0,
    )
    block = chat_attachments.attachment_context_block([record])
    assert "Imagen adjunta" in block
    assert "descripción generada por visión" in block
    assert "Un faro rojo." in block


def test_cap_attachment_text_marks_truncation(monkeypatch):
    monkeypatch.setattr(chat_attachments, "MAX_ATTACHMENT_TEXT_CHARS", 10)
    text, chars, truncated = chat_attachments.cap_attachment_text("a" * 30)
    assert truncated is True
    assert chars == 30
    assert text.startswith("a" * 10)
    assert "truncado" in text


def test_accepted_vision_capability_requires_matching_revision(client, monkeypatch):
    state = {
        "assistant_acceptance": {
            "text": "passed",
            "vision": "passed",
            "runtime": "accepted",
            "revision": 7,
        }
    }
    monkeypatch.setattr(api_server, "_local_state", lambda: type("S", (), {"snapshot": lambda self: state})())
    monkeypatch.setattr(api_server.assistant_settings, "current_config_revision", lambda: 7)
    assert api_server._accepted_vision_capability() == "multimodal"

    state["assistant_acceptance"]["revision"] = 6
    assert api_server._accepted_vision_capability() is None

    state["assistant_acceptance"]["revision"] = 7
    state["assistant_acceptance"]["vision"] = "failed"
    assert api_server._accepted_vision_capability() is None


def test_accepted_vision_capability_without_evidence_is_none(client, monkeypatch):
    monkeypatch.setattr(api_server, "_local_state", lambda: type("S", (), {"snapshot": lambda self: {}})())
    assert api_server._accepted_vision_capability() is None
