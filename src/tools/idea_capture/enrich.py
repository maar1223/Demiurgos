"""Mandatory idea enrichment provider (type classification), fail-open.

The provider is the seam the processor calls at capture time. It returns
``(body, type)`` where ``type`` is one of the idea type taxonomy. It NEVER
blocks or crashes the capture: on any timeout, exception, or unknown
classification it fails open to ``sin_clasificar`` while preserving the body.
"""

from __future__ import annotations

import logging
import os
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


def _normalize_type(classified) -> str:
    """Map a raw classification into the taxonomy; unknown -> sin_clasificar."""
    if isinstance(classified, str) and classified in TYPE_TAXONOMY:
        return classified
    return DEFAULT_TYPE


class HermesEnrichProvider:
    """Classify a raw capture via a timeout-bounded Hermes call.

    ``__call__`` always returns an ``EnrichResult`` and never raises. The
    injected ``hermes`` callable is optional: when omitted (or offline) the
    provider fails open to ``sin_clasificar``, so capture is never blocked by
    the classifier.

    ``__call__`` accepts a ``media_kind`` keyword so the processor seam can
    pass the capture's media kind through; this provider only classifies
    text, so the value is accepted for signature compatibility and ignored.
    ``media_path`` and ``mime`` are accepted the same way — the processor
    seam passes the capture's persisted media path and mime to every
    provider, and this text-only provider has no use for them.
    """

    def __init__(self, hermes: Callable[[object], str] | None = None,
                 timeout_seconds: float = 10.0):
        self._hermes = hermes
        self._timeout_seconds = timeout_seconds

    def __call__(self, raw, *, media_kind=None, media_path=None, mime=None) -> EnrichResult:
        body = _body_from_raw(raw)
        try:
            classified = self._classify(raw)
            type_ = _normalize_type(classified)
        except Exception as exc:  # noqa: BLE001 — fail open, never block capture
            log.warning("idea enrichment failed; failing open to %s: %s",
                        DEFAULT_TYPE, exc)
            type_ = DEFAULT_TYPE
        return EnrichResult(body=body, type=type_)

    def _classify(self, raw) -> str:
        if self._hermes is None:
            return DEFAULT_TYPE
        if self._timeout_seconds is None or self._timeout_seconds <= 0:
            return self._hermes(raw)
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._hermes, raw)
            try:
                return future.result(timeout=self._timeout_seconds)
            except FutureTimeoutError:
                # Timeout-bounded: return immediately, never block the capture.
                log.warning("idea enrichment timed out after %.1fs; failing open",
                            self._timeout_seconds)
                return DEFAULT_TYPE
        finally:
            # Fire-and-forget the stuck classifier; do NOT wait for it.
            executor.shutdown(wait=False)


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
        hermes: Callable[[object], str] | None = None,
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
        body = str(payload.get("descripcion") or "").strip()
        tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
        type_ = map_tags_to_taxonomy(tags, str(payload.get("veredicto") or ""))
        return EnrichResult(body=body, type=type_)

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