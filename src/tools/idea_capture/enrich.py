"""Mandatory idea enrichment provider (type classification), fail-open.

The provider is the seam the processor calls at capture time. It returns
``(body, type)`` where ``type`` is one of the idea type taxonomy. It NEVER
blocks or crashes the capture: on any timeout, exception, or unknown
classification it fails open to ``sin_clasificar`` while preserving the body.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, NamedTuple

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
    """

    def __init__(self, hermes: Callable[[object], str] | None = None,
                 timeout_seconds: float = 10.0):
        self._hermes = hermes
        self._timeout_seconds = timeout_seconds

    def __call__(self, raw) -> EnrichResult:
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
