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
import re
from pathlib import Path
from typing import Any, Callable, Mapping

import httpx

OUTCOME_PASSED = "passed"
OUTCOME_MALFORMED = "malformed"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_PROVIDER_FAILURE = "provider_failure"
OUTCOME_NOT_CAUSAL = "not_causal"

TEXT_MARKER = "mercurio"
VISION_QUESTION = (
    "Does this image contain a bright magenta square in its top-left corner? "
    "Answer with exactly yes or no."
)

# Redactions applied to provider-reported error details so an echo of the
# request can never carry credentials or the full base64 image blob back to UI.
_REDACT_DATA_URI = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+")
_REDACT_BEARER = re.compile(r"\b(?:bearer|api[_-]?key|sk-)[A-Za-z0-9._-]+", re.IGNORECASE)

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
    """Carries a probe outcome for an HTTP/transport-level failure."""

    def __init__(self, outcome: str, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message


def chat_completions_url(base_url: str) -> str:
    """Normalize a provider base URL to its chat-completions endpoint."""
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _yes_no(answer: str) -> bool | None:
    token = answer.strip().lower().split()[0].rstrip(",.!?") if answer.strip() else ""
    if token == "yes":
        return True
    if token == "no":
        return False
    return None


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
        return None
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    return None


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
    # Cap the detail to a short diagnostic snippet so an echo of the request
    # (some providers echo malformed payloads) cannot carry it back to the UI.
    if len(message) > 120:
        message = message[:120] + "…"
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
        timeout: float = 30.0,
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

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _chat(self, content: Mapping[str, Any]) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 32,
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
                OUTCOME_PROVIDER_FAILURE, _provider_rejection_message(status, body)
            )
        content_text = _extract_content(body)
        if content_text is None:
            raise ProbeFailure(OUTCOME_MALFORMED, "The provider returned a malformed probe response.")
        return content_text

    def _image_content(self, path: Path) -> Mapping[str, Any]:
        try:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise ProbeFailure(OUTCOME_PROVIDER_FAILURE, "The probe fixture could not be read.") from exc
        return {
            "type": "image_url",
            "image_url": f"data:image/jpeg;base64,{encoded}",
        }

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
                content = self._chat(
                    [{"type": "text", "text": VISION_QUESTION}, self._image_content(path)]
                )
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