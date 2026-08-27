"""Mandatory idea enrichment provider (type classification + title + body structure), fail-open.

The provider is the seam the processor calls at capture time. It returns
``(body, type, title)`` where ``type`` is one of the idea type taxonomy,
``title`` is a short human-readable title derived from the enrichment (the
Hermes classifier for TEXT/AUDIO, the vision payload for IMAGE), and ``body``
is the idea's canonical markdown structure (``## Descripción`` + ``## Detalles``
+ optional ``## Notas``) so every idea in the bank is scannable and parseable.
It NEVER blocks or crashes the capture: on any timeout, exception, or unknown
classification it fails open to ``sin_clasificar`` / ``""`` while preserving
the raw content through the local structuring fallback.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Callable, NamedTuple

from .models import MediaKind

log = logging.getLogger(__name__)

# Idea type taxonomy — mirrors the global ideas/ bank schema (R-IB-01).
TYPE_TAXONOMY: tuple[str, ...] = (
    "personaje",
    "relacion",
    "ambientacion",
    "trama",
    "concepto",
    "sin_clasificar",
)

# Explicit fail-open bucket (R-CG-02): the capture always succeeds, never
# blocked by classification.
DEFAULT_TYPE = "sin_clasificar"


class EnrichResult(NamedTuple):
    body: str
    type: str  # one of TYPE_TAXONOMY
    title: str = ""  # short human-readable title from the enrichment


def _short_title(text: str, max_words: int = 5) -> str:
    """A short title from the first words of a description; ``""`` when empty.

    Lightweight heuristic used for IMAGE captures when the vision payload
    carries no explicit ``titulo``/``title`` field. The processor keeps its
    own body-first-words fallback for the fail-open case.
    """
    if not isinstance(text, str):
        return ""
    words = [w for w in text.strip().split() if w]
    if not words:
        return ""
    return " ".join(words[:max_words])


def _body_from_raw(raw) -> str:
    """Extract the capturable body text from a raw capture input.

    Voice/image captures carry no usable text in MVP; the caller (processor)
    rejects an empty body as retryable, which preserves the existing
    voice/image behavior without blocking the text path.
    """
    if isinstance(raw, bytes):
        return ""
    text = str(raw)
    return text.strip()


def _structure_body(text: str, *, bullets: list[str] | None = None,
                    notes: str = "") -> str:
    """Wrap a plain idea text into the canonical markdown body scheme.

    Returns the ``## Descripción`` section with the main content, a
    ``## Detalles`` bullet list when bullets are given, and an optional
    ``## Notas`` section when ``notes`` is non-empty. The text is kept
    verbatim (whitespace-trimmed only) and each bullet is collapsed to a
    single line so the markdown structure stays parseable. Returns ``""``
    when there is no content at all — the caller's caption fallback then
    takes over.
    """
    parts: list[str] = []
    text = str(text).strip() if text is not None else ""
    if text:
        parts.append(f"## Descripción\n\n{text}")
    bullets = [" ".join(str(b).split()) for b in (bullets or [])
               if isinstance(b, str) and b.strip()]
    if bullets:
        parts.append("## Detalles\n\n" + "\n".join(f"- {b}" for b in bullets))
    notes = str(notes).strip() if notes is not None else ""
    if notes:
        parts.append(f"## Notas\n\n{notes}")
    return "\n\n".join(parts)


def _derive_bullets(text: str, max_bullets: int = 3) -> list[str]:
    """Derive a small detail list from a plain text (fail-open fallback).

    Splits on sentence boundaries (period/question/exclamation followed by
    whitespace) and newlines, returning up to ``max_bullets`` non-empty
    trimmed chunks. Best-effort: a single-sentence text yields one bullet;
    an empty text yields ``[]``.
    """
    if not isinstance(text, str):
        return []
    chunks: list[str] = []
    for piece in re.split(r"(?<=[.!?])\s+|\n+", text.strip()):
        piece = " ".join(piece.split()).strip()
        if piece and piece not in chunks:
            chunks.append(piece)
    return chunks[:max_bullets]


def _normalize_type(classified) -> str:
    """Map a raw classification into the taxonomy; unknown -> sin_clasificar."""
    if isinstance(classified, str) and classified in TYPE_TAXONOMY:
        return classified
    return DEFAULT_TYPE


class HermesEnrichProvider:
    """Classify a raw capture via a timeout-bounded Hermes call.

    ``__call__`` always returns an ``EnrichResult`` and never raises. The
    injected ``hermes`` callable is optional: when omitted (or offline) the
    provider fails open to ``sin_clasificar`` and an empty title, so capture
    is never blocked by the classifier.

    The injected callable may return the taxonomy label (legacy string), a
    ``(label, title)`` tuple, or the extended ``(label, title, body,
    details)`` tuple where ``body`` is the structured markdown and
    ``details`` the bullet list (the gateway classifier built by
    ``build_hermes_classifier``). Whatever it returns, the provider produces
    a STRUCTURED ``body``: the classifier's own markdown when provided, else
    a local ``_structure_body`` fallback over the raw text (so text/audio
    never lose structure when the model under-delivers).

    ``__call__`` accepts a ``media_kind`` keyword so the processor seam can
    pass the capture's media kind through; this provider only classifies
    text, so the value is accepted for signature compatibility and ignored.
    ``media_path`` and ``mime`` are accepted the same way — the processor
    seam passes the capture's persisted media path and mime to every
    provider, and this text-only provider has no use for them.
    """

    def __init__(self, hermes: Callable[[object], str | tuple] | None = None,
                 timeout_seconds: float = 10.0):
        self._hermes = hermes
        self._timeout_seconds = timeout_seconds

    def __call__(self, raw, *, media_kind=None, media_path=None, mime=None) -> EnrichResult:
        raw_body = _body_from_raw(raw)
        try:
            label, title, structured_body, details = self._classify(raw)
            type_ = _normalize_type(label)
        except Exception as exc:  # noqa: BLE001 — fail open, never block capture
            log.warning("idea enrichment failed; failing open to %s: %s",
                        DEFAULT_TYPE, exc)
            type_ = DEFAULT_TYPE
            title = ""
            structured_body = ""
            details = []
        body = self._resolve_body(raw_body, structured_body, details)
        return EnrichResult(body=body, type=type_, title=title)

    @staticmethod
    def _resolve_body(raw_body: str, structured_body, details) -> str:
        """Pick the canonical structured body for the idea.

        The classifier's own ``body`` (``## Descripción`` + ``## Detalles``
        markdown) wins when the model provided one; otherwise the raw text is
        structured locally — with the classifier's ``details`` bullets when
        given, else a simple derived list. An empty raw text yields ``""``
        (the processor's caption fallback takes over). Never raises.
        """
        if isinstance(structured_body, str) and structured_body.strip():
            return structured_body.strip()
        if not raw_body:
            return ""
        bullets = [str(d) for d in details] if isinstance(details, list) else []
        if not bullets:
            bullets = _derive_bullets(raw_body)
        return _structure_body(raw_body, bullets=bullets)

    def _classify(self, raw) -> tuple[str, str, str, list[str]]:
        if self._hermes is None:
            return DEFAULT_TYPE, "", "", []
        if self._timeout_seconds is None or self._timeout_seconds <= 0:
            return self._unpack_classified(self._hermes(raw))
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._hermes, raw)
            try:
                return self._unpack_classified(future.result(timeout=self._timeout_seconds))
            except FutureTimeoutError:
                # Timeout-bounded: return immediately, never block the capture.
                log.warning("idea enrichment timed out after %.1fs; failing open",
                            self._timeout_seconds)
                return DEFAULT_TYPE, "", "", []
        finally:
            # Fire-and-forget the stuck classifier; do NOT wait for it.
            executor.shutdown(wait=False)

    @staticmethod
    def _unpack_classified(classified) -> tuple[str, str, str, list[str]]:
        """Normalize a classifier result into ``(label, title, body, details)``.

        New classifiers return a ``(label, title, body, details)`` tuple where
        ``body`` is the structured markdown (``## Descripción`` + ``## Detalles``)
        and ``details`` the bullet list; legacy string-returning classifiers
        (and the identity default) keep empty body/details so the provider
        structures the raw text locally (fail-open compatibility).
        """
        if isinstance(classified, tuple):
            if len(classified) >= 4:
                details = classified[3] if isinstance(classified[3], list) else []
                return classified[0], classified[1], classified[2], details
            if len(classified) == 3:
                return classified[0], classified[1], classified[2], []
            if len(classified) == 2:
                return classified[0], classified[1], "", []
            if len(classified) == 1:
                return classified[0], "", "", []
        return classified, "", "", []


def map_tags_to_taxonomy(tags, veredicto: str = "") -> str:
    """Map vision tags to the idea type taxonomy; ambiguous/empty -> concepto.

    The vision model returns free-form tags; this helper picks the single
    taxonomy type they clearly name (case/plural tolerant). Empty tags, tags
    with no taxonomy match, or tags naming several distinct types are all
    ambiguous and fall back to ``concepto``. ``veredicto`` is accepted for
    signature compatibility with the vision payload and reserved for future
    use — idea capture has no lore hypothesis for it to confirm.
    """
    if not isinstance(tags, list):
        tags = []
    candidates: set[str] = set()
    for tag in tags:
        if not isinstance(tag, str):
            continue
        token = tag.strip().lower()
        if token in TYPE_TAXONOMY:
            candidates.add(token)
        elif token.endswith("s") and token[:-1] in TYPE_TAXONOMY:
            candidates.add(token[:-1])
    if len(candidates) == 1:
        return next(iter(candidates))
    return "concepto"


def _normalize_media_kind(media_kind):
    """Coerce the seam kwarg to a ``MediaKind``; ``None`` when unrecognized."""
    if isinstance(media_kind, MediaKind):
        return media_kind
    if isinstance(media_kind, str):
        try:
            return MediaKind(media_kind)
        except ValueError:
            return None
    return None


class MediaEnrichProvider:
    """Media-aware enrichment: dispatches TEXT/IMAGE/AUDIO at the seam.

    ``__call__`` always returns an ``EnrichResult`` and never raises.
    Dispatches on ``media_kind``:

    - TEXT (and unknown kinds) delegate to the Hermes text classifier.
    - IMAGE runs the injected vision callable (flag-gated); the description
      becomes the body and the tags map to the idea taxonomy.
    - AUDIO runs the injected ``transcribe_fn`` on the persisted media file
      (or a temp copy of the raw bytes), resolves the STT language from the
      locale at call time, then classifies the transcript with the Hermes
      text classifier. The transcript becomes the idea body.

    Every path fails open to ``sin_clasificar`` — capture is never blocked by
    a missing classifier, a vision failure, a missing transcriber, or an
    unconfigured flag.
    """

    def __init__(
        self,
        hermes: Callable[[object], str | tuple[str, str]] | None = None,
        vision_fn: Callable[[bytes, str], dict] | None = None,
        transcribe_fn: Callable[[str, str], str] | None = None,
        language_resolver: Callable[[], str] | None = None,
        vision_enabled: bool = False,
        timeout_seconds: float = 30.0,
    ):
        self._hermes = HermesEnrichProvider(hermes=hermes,
                                            timeout_seconds=timeout_seconds)
        self._vision_fn = vision_fn
        self._transcribe_fn = transcribe_fn
        self._language_resolver = language_resolver
        self._vision_enabled = vision_enabled
        self._timeout_seconds = timeout_seconds

    def __call__(self, raw, *, media_kind=None, media_path=None, mime=None) -> EnrichResult:
        kind = _normalize_media_kind(media_kind)
        if kind is MediaKind.IMAGE:
            return self._enrich_image(raw)
        if kind is MediaKind.VOICE:
            return self._enrich_audio(raw, media_path=media_path, mime=mime)
        # TEXT and unrecognized kinds classify as text (the prior behavior).
        return self._hermes(raw)

    def _enrich_image(self, raw) -> EnrichResult:
        if not self._vision_enabled or self._vision_fn is None:
            log.warning("image vision is disabled or unavailable; failing open "
                        "to %s (raw retained)", DEFAULT_TYPE)
            return EnrichResult(body="", type=DEFAULT_TYPE)
        try:
            payload = self._vision_fn(raw, "")
        except Exception as exc:  # noqa: BLE001 — fail open, never block capture
            log.warning("image vision failed; failing open to %s: %s",
                        DEFAULT_TYPE, exc)
            return EnrichResult(body="", type=DEFAULT_TYPE)
        if not isinstance(payload, dict) or not payload:
            log.warning("image vision returned no payload; failing open to %s",
                        DEFAULT_TYPE)
            return EnrichResult(body="", type=DEFAULT_TYPE)
        descripcion = str(payload.get("descripcion") or "").strip()
        tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
        type_ = map_tags_to_taxonomy(tags, str(payload.get("veredicto") or ""))
        # Title from the vision payload: an explicit ``titulo``/``title``
        # field wins; otherwise derive a short title from the description's
        # first words. Fails open to "" (the processor falls back to the
        # body's first words when the title is empty).
        title = payload.get("titulo") or payload.get("title") or ""
        if not isinstance(title, str):
            title = ""
        title = title.strip()
        if not title:
            title = _short_title(descripcion)
        # Structure the description into the canonical body scheme; the
        # details derive from the description's sentences, falling back to
        # the vision tags when there is nothing to split. An empty
        # description stays empty so the processor's caption fallback works.
        bullets = _derive_bullets(descripcion)
        if not bullets:
            bullets = [str(t) for t in tags if isinstance(t, str) and t.strip()]
        body = _structure_body(descripcion, bullets=bullets) if descripcion else ""
        return EnrichResult(body=body, type=type_, title=title)

    def _enrich_audio(self, raw, *, media_path=None, mime=None) -> EnrichResult:
        """Transcribe the audio and classify the transcript (fail-open).

        The injected ``transcribe_fn`` receives a real file path (the
        persisted ``record.media_path`` when it still exists, otherwise a
        temp file written from the raw bytes) plus the resolved STT language.
        Any failure — missing transcriber, unreadable locale, empty or failed
        transcription — fails open to ``sin_clasificar`` with the raw media
        retained; the capture is never blocked (R-ME-05).
        """
        if self._transcribe_fn is None:
            log.warning("audio transcription unavailable; failing open to %s "
                        "(raw retained)", DEFAULT_TYPE)
            return EnrichResult(body="", type=DEFAULT_TYPE)
        temp_path: str | None = None
        try:
            language = (self._language_resolver() if self._language_resolver is not None
                        else "es")
            audio_path, temp_path = self._resolve_audio_path(raw, media_path, mime)
            transcript = self._transcribe_fn(audio_path, language)
        except Exception as exc:  # noqa: BLE001 — fail open, never block capture
            log.warning("audio transcription failed; failing open to %s: %s",
                        DEFAULT_TYPE, exc)
            return EnrichResult(body="", type=DEFAULT_TYPE)
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
        if not isinstance(transcript, str) or not transcript.strip():
            log.warning("audio transcription produced no text; failing open to %s",
                        DEFAULT_TYPE)
            return EnrichResult(body="", type=DEFAULT_TYPE)
        # Classify the transcript with the same Hermes classifier used for
        # text; the transcript itself becomes the idea body (no loss).
        return self._hermes(transcript.strip())

    @staticmethod
    def _resolve_audio_path(raw, media_path=None, mime=None) -> tuple[str, str | None]:
        """Return ``(path, temp_path_or_None)`` for the transcription call.

        ``transcribe_audio`` needs a real file path with a supported
        extension. ``record.media_path`` already points at the Hermes-cached
        media file when present — prefer it; otherwise the raw bytes are
        written to a temp file (suffix derived from the mime) that the caller
        removes after transcription.
        """
        if isinstance(media_path, str) and media_path.strip():
            candidate = Path(media_path).expanduser()
            if candidate.is_file():
                return str(candidate), None
            log.warning("media_path %s is not a file; writing raw bytes to a "
                        "temp file", media_path)
        suffix = _audio_suffix_for_mime(mime)
        fd, name = tempfile.mkstemp(prefix="idea-capture-audio-", suffix=suffix)
        os.close(fd)
        try:
            Path(name).write_bytes(raw if isinstance(raw, bytes) else b"")
        except OSError:
            Path(name).unlink(missing_ok=True)
            raise
        return name, name


# ``transcribe_audio`` validates the source extension against its supported
# set, so the temp fallback must pick a suffix the codec actually matches.
_AUDIO_MIME_SUFFIXES: dict[str, str] = {
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/oga": ".oga",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mpga": ".mpga",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/webm": ".webm",
    "audio/aac": ".aac",
    "audio/aacp": ".aac",
    "audio/flac": ".flac",
    "audio/x-caf": ".caf",
    "audio/caf": ".caf",
}


def _audio_suffix_for_mime(mime) -> str:
    """Map a media mime type to a ``transcribe_audio``-supported extension."""
    if isinstance(mime, str) and mime.strip():
        base = mime.strip().split(";", 1)[0].strip().lower()
        if base in _AUDIO_MIME_SUFFIXES:
            return _AUDIO_MIME_SUFFIXES[base]
    return ".ogg"  # Telegram voice notes default to ogg/opus