"""Backend-only provider validation and model discovery adapters."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

import httpx


_DEFAULT_ENDPOINTS = {
    "opencode-go": "https://opencode.ai/zen/go/v1",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
_PROVIDERS = frozenset((*_DEFAULT_ENDPOINTS, "compatible"))
_CAPABILITIES = frozenset(("multimodal", "text-only", "unknown"))
Transport = Callable[[str, str, dict[str, str]], tuple[int, Any]]


@dataclass(frozen=True)
class ProviderCandidate:
    provider: str
    base_url: str
    api_key: str


def default_base_url(provider: str) -> str | None:
    """Return the server-owned endpoint for providers with a fixed default."""
    return _DEFAULT_ENDPOINTS.get(provider)


def _endpoint(provider: str, raw: Any) -> str | None:
    value = default_base_url(provider) or (raw if provider == "compatible" else None)
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        return None
    netloc = host if not port else f"{host}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def candidate_from_payload(payload: Mapping[str, Any]) -> ProviderCandidate | None:
    provider = payload.get("provider")
    key = payload.get("api_key")
    if not isinstance(provider, str) or provider not in _PROVIDERS:
        return None
    if not isinstance(key, str) or not key.strip() or len(key) > 2048 or any(c.isspace() for c in key):
        return None
    base_url = _endpoint(provider, payload.get("base_url"))
    if base_url is None:
        return None
    return ProviderCandidate(provider, base_url, key.strip())


def normalize_model(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        model_id = item.strip()
        source: Mapping[str, Any] = {}
    elif isinstance(item, Mapping):
        model_id = item.get("id")
        source = item
    else:
        return None
    if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 256:
        return None
    capability = source.get("capability")
    if capability not in _CAPABILITIES:
        evidence = source.get("capabilities")
        if isinstance(evidence, Mapping):
            if evidence.get("multimodal") is True:
                capability = "multimodal"
            elif evidence.get("text-only") is True:
                capability = "text-only"
        elif isinstance(evidence, (list, tuple, set)):
            values = set(evidence)
            if "multimodal" in values:
                capability = "multimodal"
            elif "text-only" in values:
                capability = "text-only"
    if capability not in _CAPABILITIES:
        capability = "unknown"
    label = source.get("label") or source.get("name") or model_id
    if not isinstance(label, str) or len(label) > 256:
        label = model_id
    pricing = source.get("pricing")
    if not isinstance(pricing, Mapping):
        pricing = None
    elif not all(isinstance(value, (int, float)) and value >= 0 for value in pricing.values()):
        pricing = None
    else:
        pricing = {str(key): value for key, value in pricing.items() if str(key) in {"input", "output"}}
        pricing = pricing or None
    return {"id": model_id.strip(), "label": label, "capability": capability, "pricing": pricing}


class ProviderRegistry:
    """Registry with bounded backend transport and categorical telemetry only."""

    def __init__(self, transport: Transport | None = None, telemetry: Callable[[dict[str, Any]], None] | None = None):
        self.transport = transport
        self.telemetry = telemetry

    def _record(self, outcome: str, candidate: ProviderCandidate, category: str | None, started: float) -> None:
        if self.telemetry:
            self.telemetry({
                "outcome": outcome,
                "latency_ms": min(120000, round((time.monotonic() - started) * 1000)),
                "adapter": candidate.provider,
                "failure_category": category,
                "activation_state": "not-attempted",
            })

    def _request(self, candidate: ProviderCandidate) -> tuple[int, Any]:
        headers = {"Authorization": f"Bearer {candidate.api_key}", "Accept": "application/json"}
        if self.transport:
            return self.transport("GET", f"{candidate.base_url}/models", headers)
        with httpx.Client(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            response = client.get(f"{candidate.base_url}/models", headers=headers)
            try:
                body = response.json()
            except ValueError:
                body = None
            return response.status_code, body

    def validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        candidate = candidate_from_payload(payload)
        if candidate is None:
            provider = payload.get("provider") if isinstance(payload.get("provider"), str) else "unknown"
            result = {"outcome": "failed", "category": "invalid-request", "provider": provider,
                      "message": "Provide a supported provider, endpoint, and API key."}
            if self.telemetry:
                self.telemetry({"outcome": "failed", "latency_ms": 0, "adapter": provider,
                                "failure_category": "invalid-request", "activation_state": "not-attempted"})
            return result
        try:
            status, _ = self._request(candidate)
        except (httpx.TimeoutException, TimeoutError):
            category, message = "timeout", "The provider did not respond before the timeout."
        except (httpx.HTTPError, OSError):
            category, message = "transport", "The provider endpoint could not be reached."
        else:
            if status in {401, 403}:
                category, message = "authentication", "The provider rejected the API key."
            elif status >= 400:
                category, message = "provider", "The provider rejected the connection request."
            else:
                self._record("success", candidate, None, started)
                return {"outcome": "validated", "category": "ok", "provider": candidate.provider}
        self._record("failed", candidate, category, started)
        return {"outcome": "failed", "category": category, "provider": candidate.provider, "message": message}

    def discover(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        validation = self.validate(payload)
        if validation["outcome"] != "validated":
            return {**validation, "models": []}
        candidate = candidate_from_payload(payload)
        assert candidate is not None
        started = time.monotonic()
        try:
            status, body = self._request(candidate)
        except (httpx.TimeoutException, TimeoutError):
            self._record("failed", candidate, "timeout", started)
            return {"outcome": "failed", "category": "timeout", "provider": candidate.provider,
                    "message": "Model discovery timed out.", "models": []}
        except (httpx.HTTPError, OSError):
            self._record("failed", candidate, "transport", started)
            return {"outcome": "failed", "category": "transport", "provider": candidate.provider,
                    "message": "Model discovery could not reach the provider.", "models": []}
        if status >= 400 or not isinstance(body, Mapping):
            self._record("failed", candidate, "invalid-response", started)
            return {"outcome": "failed", "category": "invalid-response", "provider": candidate.provider,
                    "message": "The provider returned no usable model list.", "models": []}
        raw_models = body.get("data", body.get("models"))
        models = [model for item in raw_models or [] if (model := normalize_model(item))]
        if not models:
            self._record("failed", candidate, "empty-discovery", started)
            return {"outcome": "failed", "category": "empty-discovery", "provider": candidate.provider,
                    "message": "No usable models were returned; enter a model ID manually or repair the connection.",
                    "models": []}
        self._record("success", candidate, None, started)
        return {"outcome": "discovered", "category": "ok", "provider": candidate.provider, "models": models}
