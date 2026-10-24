# -*- coding: utf-8 -*-
"""Chat document attachments — bounded store and fail-safe extraction (S2/S3/S10).

Real conversion is exercised with generated ``.docx``/``.pdf`` fixtures when
the optional extras are importable; the dependency-absent and conversion-failure
paths are simulated so the degradation contract is pinned without them.
"""

from __future__ import annotations

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
