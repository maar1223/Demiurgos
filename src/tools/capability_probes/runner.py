"""Independent text and causal-vision probe runner.

Outcomes follow the design contract: ``passed | malformed | timeout |
provider_failure | not_causal``. Each probe uses a fixed, independent oracle:

- **Text oracle**: the model must echo the fixed marker word ``mercurio``.
- **Vision oracle**: the model must answer a binary question about an
  injected bright-magenta square in the top-left corner. The versioned
  fixture (no square) expects ``no``; the controlled altered variant
  (square injected) expects ``yes``. Correct answers on BOTH images prove
  the model actually sees the pixels instead of echoing a memorized
  description of the logo.

The runner talks to any OpenAI-compatible ``/chat/completions`` endpoint
(Ollama and LM Studio expose one), so the oracle is provider-neutral.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import logging
import re
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

OUTCOME_PASSED = "passed"
OUTCOME_MALFORMED = "malformed"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_PROVIDER_FAILURE = "provider_failure"
OUTCOME_NOT_CAUSAL = "not_causal"

#: Statuses that can mean "the JSON was parsed and the SHAPE was rejected":
#: 400 Bad Request, 415 Unsupported Media Type, 422 Unprocessable Entity.
#: Only these justify retrying the other image encoding. Credentials (401/403),
#: rate limits and quota (429) and server faults (5xx) are NOT shape problems.
_ENCODING_RETRY_STATUSES = frozenset({400, 415, 422})

TEXT_MARKER = "mercurio"
VISION_QUESTION = (
    "Does this image contain a bright magenta square in its top-left corner? "
    "Answer with exactly yes or no."
)

# Redactions applied to provider-reported error details so an echo of the
# request can never carry credentials or the full base64 image blob back to UI.
_REDACT_DATA_URI = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+")
_REDACT_BEARER = re.compile(r"\b(?:bearer|api[_-]?key|sk-)[A-Za-z0-9._-]+", re.IGNORECASE)

# UI cap for the provider's rejection detail. A schema/format rejection puts the
# actionable part AFTER a fixed preamble (~107 chars: "Upstream request failed:
# [invalid_request_error] Failed to deserialize the JSON body into the target
# type: messages[0]: …"), so the old 120-char cap cut away exactly the useful
# tail and left the user with an undiagnosable error.
_DETAIL_LIMIT = 400

_DEFAULT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "logo-demiurgos.jpg"
_DEFAULT_VARIANT = Path(__file__).resolve().parent / "fixtures" / "logo-demiurgos-altered.jpg"

# (oracle name, image path, expected yes/no answer)
_VISION_CASES = (
    ("vision-fixture", _DEFAULT_FIXTURE, "no"),
    ("vision-variant", _DEFAULT_VARIANT, "yes"),
)

ProbeTransport = Callable[[str, str, dict[str, str], Mapping[str, Any]], tuple[int, Any]]


@dataclass(frozen=True)
class ProbeResult:
    outcome: str
    oracle: str
    message: str = ""


class ProbeFailure(RuntimeError):
    """Carries a probe outcome for an HTTP/transport-level failure.

    ``status`` is the provider's HTTP status when the failure came from a
    response, and ``None`` for transport/timeout failures. Callers MUST branch
    on it instead of matching words in ``message``: the rendered message cannot
    tell a schema rejection from a ``401 invalid_api_key``, so wording-based
    retries either miss the real format errors or repeat an auth/quota failure.
    """

    def __init__(
        self, outcome: str, message: str, *, status: int | None = None
    ) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message
        self.status = status


def chat_completions_url(base_url: str) -> str:
    """Normalize a provider base URL to its chat-completions endpoint."""
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _yes_no(answer: str) -> bool | None:
    # Be tolerant of reasoning wrappers like "<think>...</think> yes" — the
    # vision oracle requires a clear final yes/no, so look for the last
    # isolated yes/no token in the (think-stripped) answer rather than only
    # the first word.
    stripped_think = re.sub(r"<think>.*?</think>", " ", answer, flags=re.DOTALL | re.IGNORECASE)
    matches = re.findall(r"\b(yes|no)\b", stripped_think.lower())
    if not matches:
        return None
    return matches[-1] == "yes"


def _coerce_content_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
            elif isinstance(item.get("content"), str) and item["content"].strip():
                parts.append(item["content"].strip())
        if parts:
            return " ".join(parts)
    if isinstance(value, Mapping):
        # Some providers wrap text as {"text": "..."} or {"value": "..."}
        for key in ("text", "value", "content"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return None


def _deep_collect_strings(value: Any, *, depth: int = 0, max_depth: int = 7, seen: int = 0) -> list[str]:
    """Exhaustive, bounded collection of all strings in a JSON value.

    This is the definitive fallback — future field names or nesting levels
    are covered without per-model patches. Bounded to avoid blowup on huge
    payloads; image data URIs, bearer shapes, and structural type tags are
    skipped.
    """
    if seen > 400 or depth > max_depth:
        return []
    if isinstance(value, str):
        if not value.strip():
            return []
        if "data:image" in value and "base64," in value:
            return []
        if len(value) > 2000:
            value = value[:2000] + "…"
        return [value.strip()]
    if isinstance(value, Mapping):
        out: list[str] = []
        for k, v in value.items():
            # Structural tags like "type": "image_url" are not answer text.
            if k == "type" and isinstance(v, str) and v in ("image_url", "text", "image", "audio", "video", "input_text", "output_text"):
                continue
            out.extend(_deep_collect_strings(v, depth=depth + 1, max_depth=max_depth, seen=len(out)))
            if len(out) > 400:
                break
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_deep_collect_strings(item, depth=depth + 1, max_depth=max_depth, seen=len(out)))
            if len(out) > 400:
                break
        return out
    return []


def _extract_content(body: Any) -> str | None:
    if not isinstance(body, Mapping):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, Mapping):
        return None
    message = first.get("message")
    if not isinstance(message, Mapping):
        # Some completions-style providers put the text directly on the choice
        for alt in ("text", "content"):
            alt_val = first.get(alt)
            coerced = _coerce_content_value(alt_val)
            if coerced:
                return coerced
        # Last resort: deep search inside the choice itself
        deep = _deep_collect_strings(first)
        if deep:
            joined = " ".join(deep)
            if joined.strip():
                return joined.strip()
        return None
    # Primary: message.content in its various shapes.
    content = message.get("content")
    coerced = _coerce_content_value(content)
    if coerced:
        return coerced
    # Fallback for reasoning models that put the answer in reasoning fields
    # while returning content as null/empty (e.g. MiMo, DeepSeek-reasoner).
    for fallback_key in ("reasoning_content", "reasoning", "reasoning_text", "thinking", "thought", "output_text", "response", "answer"):
        fallback = message.get(fallback_key)
        coerced = _coerce_content_value(fallback)
        if coerced:
            return coerced
    # Definitive fallback: exhaustive recursive search inside the message
    # (and the whole choice) — any future field name or nesting is covered
    # without a per-model patch. Only used when the known paths failed.
    deep = _deep_collect_strings(message)
    if deep:
        joined = " ".join(deep)
        if joined.strip():
            return joined.strip()
    deep_choice = _deep_collect_strings(first)
    if deep_choice:
        joined = " ".join(deep_choice)
        if joined.strip() and joined.strip() != " ".join(_deep_collect_strings(message)).strip():
            return joined.strip()
    return None


def _malformed_hint(body: Any) -> str:
    """One-line redacted shape hint for malformed responses (no secrets, no image blobs)."""
    try:
        if not isinstance(body, Mapping):
            return f"body_type={type(body).__name__}"
        choices = body.get("choices")
        if not isinstance(choices, list):
            return "choices_missing_or_not_list"
        if not choices:
            return "choices_empty"
        first = choices[0] if isinstance(choices[0], Mapping) else {}
        message = first.get("message", {}) if isinstance(first, Mapping) else {}
        if not isinstance(message, Mapping):
            return f"message_type={type(message).__name__}"
        keys = ",".join(sorted(str(k) for k in message.keys()))[:80]
        content = message.get("content")
        ctype = type(content).__name__
        if isinstance(content, list):
            return f"message_keys=[{keys}] content=list[{len(content)}] ctype={ctype}"
        if isinstance(content, str):
            preview = content.strip()[:40].replace("\n", " ")
            preview = _REDACT_DATA_URI.sub("<image-data>", preview)
            preview = _REDACT_BEARER.sub("<bearer-token>", preview)
            return f"message_keys=[{keys}] content=str:{preview!r} ctype={ctype}"
        return f"message_keys=[{keys}] content_type={ctype}"
    except Exception:
        return "unavailable"


def _provider_rejection_message(status: int, body: Any) -> str:
    """Build a safe, useful rejection message from the provider error body.

    The returned detail never echoes credentials, the prompt, or image data:
    only a short provider-reported ``error.message`` (or a stable fallback) is
    surfaced so the UI can distinguish unsupported formats, unknown models, and
    invalid endpoints without leaking secrets.
    """
    base = f"The provider rejected the probe request (HTTP {status})."
    if not isinstance(body, Mapping):
        return base
    error = body.get("error")
    if not isinstance(error, Mapping):
        return base
    message = error.get("message")
    if not isinstance(message, str):
        return base
    message = message.strip()
    if not message:
        return base
    # Collapse whitespace, then redact anything that could carry a secret or
    # the full image blob: base64 data URIs and common credential shapes.
    message = " ".join(message.split())
    message = _REDACT_DATA_URI.sub("<image-data>", message)
    message = _REDACT_BEARER.sub("<bearer-token>", message)
    # Record the FULL redacted detail before the UI cap. A field report of a
    # provider rejection would otherwise be truncated to the fixed preamble,
    # which is exactly the part that says nothing about the cause.
    logger.warning("probe rejected by provider (HTTP %s): %s", status, message)
    # Cap the detail so an echo of the request (some providers echo malformed
    # payloads) cannot carry the whole body back to the UI.
    if len(message) > _DETAIL_LIMIT:
        message = message[: _DETAIL_LIMIT - 1] + "…"
    return f"{base} Provider detail: {message}"


class ProbeRunner:
    """Run the text and causal-vision oracles against one model endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "",
        transport: ProbeTransport | None = None,
        fixture: Path | None = None,
        variant: Path | None = None,
        timeout: float = 75.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._transport = transport or self._default_transport
        self._fixture = Path(fixture) if fixture is not None else _DEFAULT_FIXTURE
        self._variant = Path(variant) if variant is not None else _DEFAULT_VARIANT
        self._timeout = timeout

    # -- transport ---------------------------------------------------------

    def _default_transport(
        self, method: str, url: str, headers: dict[str, str], payload: Mapping[str, Any]
    ) -> tuple[int, Any]:
        with httpx.Client(timeout=httpx.Timeout(self._timeout, connect=3.0)) as client:
            response = client.post(url, json=dict(payload), headers=headers)
            try:
                body = response.json()
            except ValueError:
                body = None
            return response.status_code, body

    def _is_opencode_host(self) -> bool:
        """True when the probe target is OpenCode Go (requires a session id)."""
        host = (urlsplit(self.base_url).hostname or "").lower()
        return host == "opencode.ai" or host.endswith(".opencode.ai")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # OpenCode Go (Console Go) requires a stable per-conversation session id
        # in ``x-opencode-session`` for routing/prompt-cache optimization; a
        # probe without it is rejected with HTTP 400 "missing x-opencode-session".
        # Send a stable identifier derived from the probed model. Other providers
        # ignore the extra header, so this only gates on the OpenCode host.
        if self._is_opencode_host():
            headers["x-opencode-session"] = f"demiurgos-probe-{self.model or 'default'}"
        return headers

    def _chat(self, content: Mapping[str, Any]) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            # 512 covers heavy reasoning preambles (MiMo, DeepSeek-reasoner)
            # without truncating the oracle answer; the cost is negligible
            # for a one-shot probe and the 45s timeout absorbs the latency.
            "max_tokens": 512,
            "temperature": 0,
        }
        try:
            status, body = self._transport(
                "POST", chat_completions_url(self.base_url), self._headers(), payload
            )
        except (httpx.TimeoutException, TimeoutError):
            raise ProbeFailure(OUTCOME_TIMEOUT, "The provider did not respond before the probe timeout.")
        except (httpx.HTTPError, OSError):
            raise ProbeFailure(OUTCOME_PROVIDER_FAILURE, "The provider endpoint could not be reached.")
        if status >= 400:
            raise ProbeFailure(
                OUTCOME_PROVIDER_FAILURE,
                _provider_rejection_message(status, body),
                status=status,
            )
        content_text = _extract_content(body)
        if content_text is None:
            hint = _malformed_hint(body)
            raise ProbeFailure(
                OUTCOME_MALFORMED,
                f"The provider returned a malformed probe response. Hint: {hint}",
            )
        return content_text

    def _image_content(self, path: Path) -> Mapping[str, Any]:
        """Legacy direct-string form (some providers like Ollama/LM Studio)."""
        try:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise ProbeFailure(OUTCOME_PROVIDER_FAILURE, "The probe fixture could not be read.") from exc
        return {
            "type": "image_url",
            "image_url": f"data:image/jpeg;base64,{encoded}",
        }

    def _image_content_object(self, path: Path) -> Mapping[str, Any]:
        """Spec-compliant object form {"url": data_uri} (OpenAI + strict gateways)."""
        try:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise ProbeFailure(OUTCOME_PROVIDER_FAILURE, "The probe fixture could not be read.") from exc
        return {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
        }

    def _chat_vision(self, vision_question: str, path: Path) -> str:
        """Vision chat with automatic fallback between image encodings.

        Tries the legacy direct-string form first (Ollama/LM Studio) and, when
        the provider rejects the SHAPE, retries with the spec-compliant
        ``{"url": data_uri}`` object form (strict OpenAI-schema gateways, e.g.
        OpenCode Go, which answers ``422 invalid type: string "<image-data>",
        expected struct ...ImageUrl`` for the bare string).

        Only shape rejections are retried. A 401/403 (credentials) or 429
        (quota) is the same failure however the image is encoded, so retrying it
        would repeat the failure, double the credential attempts and burn quota
        — while hiding the real cause behind the second response.
        """
        try:
            return self._chat(
                [{"type": "text", "text": vision_question}, self._image_content(path)]
            )
        except ProbeFailure as exc:
            if (
                exc.outcome != OUTCOME_PROVIDER_FAILURE
                or exc.status not in _ENCODING_RETRY_STATUSES
            ):
                raise
            # The status says "unprocessable"; only a format-class detail tells
            # us the encoding itself is what it could not parse.
            lower_msg = exc.message.lower()
            retry_triggers = ("param", "deserialize", "format", "invalid", "malformed")
            if not any(trigger in lower_msg for trigger in retry_triggers):
                raise
            return self._chat(
                [{"type": "text", "text": vision_question}, self._image_content_object(path)]
            )

    # -- oracles -----------------------------------------------------------

    def run_text(self) -> ProbeResult:
        """Ask the model to echo the fixed marker word and verify it."""
        try:
            content = self._chat(f"Reply with exactly the word {TEXT_MARKER} and nothing else.")
        except ProbeFailure as exc:
            return ProbeResult(exc.outcome, "text-marker", exc.message)
        if TEXT_MARKER not in content.lower():
            return ProbeResult(
                OUTCOME_NOT_CAUSAL, "text-marker", "The model did not pass the text oracle."
            )
        return ProbeResult(OUTCOME_PASSED, "text-marker", "Text oracle passed.")

    def run_vision(self) -> ProbeResult:
        """Prove causal vision: correct answers on the fixture AND the variant."""
        for oracle, path, expected in _VISION_CASES:
            try:
                content = self._chat_vision(VISION_QUESTION, path)
            except ProbeFailure as exc:
                return ProbeResult(exc.outcome, oracle, exc.message)
            verdict = _yes_no(content)
            if verdict is None:
                return ProbeResult(
                    OUTCOME_NOT_CAUSAL, oracle, "The model did not answer the vision oracle with yes or no."
                )
            if (verdict is True) != (expected == "yes"):
                return ProbeResult(
                    OUTCOME_NOT_CAUSAL, oracle, "The model's answer did not match the vision oracle."
                )
        return ProbeResult(
            OUTCOME_PASSED, "causal-vision", "Text and causal vision probes passed."
        )