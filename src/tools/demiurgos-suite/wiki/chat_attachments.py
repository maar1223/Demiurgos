# -*- coding: utf-8 -*-
"""Chat document attachments — bounded extraction and per-conversation store.

The Assistant chat is text-only: a document reaches the model as extracted
text injected into the run prompt. This module owns the two server-side
concerns of that feature and nothing else:

* extraction, through the same markitdown seam the world importer already
  uses, with a fail-safe contract (a missing optional dependency degrades,
  it never crashes the request);
* a bounded, expiring in-memory store so a conversation can reference an
  attachment on later turns without re-uploading the file.

Only ``.docx`` and ``.pdf`` are supported. Extracted text is cleaned of
markitdown's data-URI image placeholders (they are not real content and are
enormous) and capped at :data:`MAX_ATTACHMENT_TEXT_CHARS`; the full extracted
length is reported so the UI can say the attachment was truncated.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SUPPORTED_ATTACHMENT_SUFFIXES: dict[str, str] = {".docx": "docx", ".pdf": "pdf"}

#: Largest accepted upload. Bigger files are rejected before any conversion work.
MAX_ATTACHMENT_FILE_BYTES = 15 * 1024 * 1024

#: Largest text injected into one run prompt, per attachment.
MAX_ATTACHMENT_TEXT_CHARS = 30_000

#: How long an uploaded attachment stays referenceable by a conversation.
ATTACHMENT_TTL_SECONDS = 4 * 60 * 60

#: Hard cap on concurrently stored attachments (oldest evicted first).
MAX_STORED_ATTACHMENTS = 32

#: Hard cap on attachments attached to a single turn.
MAX_ATTACHMENTS_PER_TURN = 5

_TRUNCATION_MARKER = "\n\n[…truncado: se muestran {kept} de {total} caracteres]"

# Complete base64 payloads as well as markitdown's truncated ``base64...``
# placeholders: neither is document text, and an inlined image can be megabytes.
_RE_DATA_URI_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*data:[^)]*\)")
_RE_MANY_BLANK_LINES = re.compile(r"\n{3,}")


class ChatAttachmentError(Exception):
    """A rejected upload or extraction, carrying the stable wire contract."""

    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


@dataclass(frozen=True)
class ChatAttachment:
    """One stored attachment: metadata plus the truncated extracted text."""

    id: str
    name: str
    kind: str
    text: str
    chars: int
    truncated: bool
    created_at: float


def _suffix_kind(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    kind = SUPPORTED_ATTACHMENT_SUFFIXES.get(suffix)
    if kind is None:
        raise ChatAttachmentError(
            "attachment.unsupported_type",
            422,
            "Unsupported attachment type; only .docx and .pdf are accepted.",
        )
    return kind


def normalize_attachment_name(filename: str) -> tuple[str, str]:
    """Return ``(display_name, kind)`` for an uploaded filename.

    The display name keeps its extension: truncating a long name with a plain
    slice would drop the suffix and turn a valid ``.docx`` into an unsupported
    type. The stem is bounded and the suffix survives.
    """
    kind = _suffix_kind(filename)
    raw = Path(filename or "document").name or "document"
    stem = Path(raw).stem[:180] or "document"
    return f"{stem}{Path(raw).suffix.lower()}", kind


def _missing_dependency() -> ChatAttachmentError:
    return ChatAttachmentError(
        "attachment.conversion_unavailable",
        422,
        "Document conversion is unavailable on this platform.",
    )


def _require_converter(suffix: str) -> None:
    """Fail as ``conversion_unavailable`` BEFORE the seam swallows the cause.

    ``sync_lore``'s converter catches every exception and returns ``None``, so
    an absent optional extra is indistinguishable from a broken document once
    it reaches the caller. Checking the imports first keeps the documented
    degradation honest for the real packaging path.
    """
    try:
        import markitdown  # noqa: F401
    except ImportError as exc:  # pragma: no cover - packaging dependent
        raise _missing_dependency() from exc
    if suffix == ".pdf":
        try:
            import pdfminer  # noqa: F401
            import pdfplumber  # noqa: F401
        except ImportError as exc:  # pragma: no cover - packaging dependent
            raise _missing_dependency() from exc


def _convert_bytes(filename: str, data: bytes) -> str:
    """Convert one document to text, translating every failure to the contract.

    The temporary file lives outside the worktree and is always removed. A
    missing optional dependency (markitdown or its PDF extra) is reported as
    ``attachment.conversion_unavailable`` — the documented degradation — while
    an actual conversion error is ``attachment.conversion_failed``.
    """
    suffix = Path(filename).suffix.lower()
    _require_converter(suffix)
    directory = tempfile.mkdtemp(prefix="demiurgos-chat-attachment-")
    temp_path = Path(directory) / f"document{suffix}"
    try:
        temp_path.write_bytes(data)
        try:
            from sync_lore.utils.converter import convert_to_markdown
        except ImportError as exc:  # pragma: no cover - packaging dependent
            raise ChatAttachmentError(
                "attachment.conversion_unavailable",
                422,
                "Document conversion is unavailable on this platform.",
            ) from exc
        try:
            converted = convert_to_markdown(temp_path)
        except SystemExit as exc:
            raise _missing_dependency() from exc
        except Exception as exc:
            # ``markitdown`` raises ``MissingDependencyException`` when an extra
            # is absent; the protocol name is stable and avoids depending on a
            # private module path.
            if type(exc).__name__ == "MissingDependencyException":
                raise _missing_dependency() from exc
            raise ChatAttachmentError(
                "attachment.conversion_failed",
                422,
                "The document could not be converted.",
            ) from exc
        if converted is None:
            raise ChatAttachmentError(
                "attachment.conversion_failed",
                422,
                "The document could not be converted.",
            )
        return converted
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _clean_text(text: str) -> str:
    cleaned = _RE_DATA_URI_IMAGE.sub("", text)
    cleaned = _RE_MANY_BLANK_LINES.sub("\n\n", cleaned)
    return cleaned.strip()


def extract_attachment(filename: str, data: bytes) -> tuple[str, int, bool]:
    """Validate, convert, clean, and truncate one uploaded document.

    Returns ``(text, original_character_count, truncated)``. Every rejection is
    a :class:`ChatAttachmentError`; nothing is stored and no request state is
    mutated.
    """
    _suffix_kind(filename)
    if len(data) > MAX_ATTACHMENT_FILE_BYTES:
        raise ChatAttachmentError(
            "attachment.too_large",
            413,
            "The attachment exceeds the size limit.",
        )
    try:
        converted = _convert_bytes(filename, data)
    except ChatAttachmentError:
        raise
    except Exception as exc:  # noqa: BLE001 — the seam never escapes as a crash
        raise ChatAttachmentError(
            "attachment.conversion_failed",
            422,
            "The document could not be converted.",
        ) from exc
    cleaned = _clean_text(converted)
    if not cleaned:
        raise ChatAttachmentError(
            "attachment.empty",
            422,
            "The document has no extractable text.",
        )
    total = len(cleaned)
    if total <= MAX_ATTACHMENT_TEXT_CHARS:
        return cleaned, total, False
    marker = _TRUNCATION_MARKER.format(kept=MAX_ATTACHMENT_TEXT_CHARS, total=total)
    return cleaned[:MAX_ATTACHMENT_TEXT_CHARS] + marker, total, True


class ChatAttachmentStore:
    """Thread-safe, bounded, expiring attachment store.

    State is deliberately in-process: a restart invalidates outstanding
    attachment ids, and the frontend drops them (``attachment.expired``). The
    store owns no filesystem state, so a rejected upload leaves nothing behind.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = ATTACHMENT_TTL_SECONDS,
        max_entries: int = MAX_STORED_ATTACHMENTS,
        clock: Callable[[], float] = time.time,
        id_source: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max(1, max_entries)
        self._clock = clock
        self._id_source = id_source
        self._lock = threading.Lock()
        self._entries: dict[str, ChatAttachment] = {}

    def put(
        self,
        *,
        name: str,
        kind: str,
        text: str,
        chars: int,
        truncated: bool,
    ) -> ChatAttachment:
        now = self._clock()
        record = ChatAttachment(
            id=self._id_source(),
            name=name,
            kind=kind,
            text=text,
            chars=chars,
            truncated=truncated,
            created_at=now,
        )
        with self._lock:
            self._entries[record.id] = record
            self._prune_locked(now)
        return record

    def get(self, attachment_id: str) -> ChatAttachment | None:
        if not attachment_id:
            return None
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            return self._entries.get(attachment_id)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _prune_locked(self, now: float) -> None:
        expired = [
            key
            for key, record in self._entries.items()
            if now - record.created_at >= self._ttl
        ]
        for key in expired:
            del self._entries[key]
        while len(self._entries) > self._max_entries:
            oldest = min(self._entries.values(), key=lambda record: record.created_at)
            del self._entries[oldest.id]


#: Process-wide store behind the chat attachment endpoints.
ATTACHMENTS = ChatAttachmentStore()


def attachment_metadata_note(attachments: tuple[ChatAttachment, ...] | list[ChatAttachment]) -> str:
    """The classifier-facing note: names and kinds, never document text (S4).

    The semantic gate only needs to know that the author is talking about an
    attachment; the run prompt is the surface that receives the content.
    """
    if not attachments:
        return ""
    labels = ", ".join(f"{record.name} ({record.kind})" for record in attachments)
    return f"\n[Adjuntos en este turno: {labels}]"


def attachment_context_block(
    attachments: tuple[ChatAttachment, ...] | list[ChatAttachment],
) -> str | None:
    """The run-prompt block carrying the extracted text (S4/S5).

    Each attachment is delimited and labelled with its name, kind, extracted
    length and truncation state, so the model can distinguish documents and
    never silently treat a truncated document as complete.
    """
    if not attachments:
        return None
    header = (
        "[Documentos adjuntos del autor: usa su contenido para responder. "
        "Si la respuesta no está en ellos, dilo; no inventes contenido.]"
    )
    blocks = []
    for record in attachments:
        state = ", truncado" if record.truncated else ""
        blocks.append(
            f'[Adjunto "{record.name}" ({record.kind}, {record.chars} caracteres'
            f"{state}):\n{record.text}\n]"
        )
    return header + "\n" + "\n".join(blocks)
