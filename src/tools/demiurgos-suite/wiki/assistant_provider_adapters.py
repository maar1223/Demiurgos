"""Backend-only provider validation and model discovery adapters.

Provider-neutral surface with runtime-specific adapters:

- **OpenAI-compatible/remote** (``opencode-go``, ``openai``, ``openrouter``,
  ``compatible``): discovery via ``GET {base}/models``; every model is
  available and loaded (no JIT concept).
- **Ollama** (local): installed models via ``GET {base}/api/tags``, loaded
  models via ``GET {base}/api/ps``; unloaded models load on demand.
- **LM Studio** (local): downloaded models and their state via
  ``GET {base}/api/v0/models``, JIT-visible models via
  ``GET {base}/v1/models``.

Local providers require no API key; remote providers require one. The
adapters never log, return, or persist credentials.
"""

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
    "ollama": "http://127.0.0.1:11434",
    "lm-studio": "http://127.0.0.1:1234/v1",
}
_PROVIDERS = frozenset((*_DEFAULT_ENDPOINTS, "compatible"))
_LOCAL_PROVIDERS = frozenset(("ollama", "lm-studio"))
_CAPABILITIES = frozenset(("multimodal", "text-only", "unknown"))
Transport = Callable[[str, str, dict[str, str]], tuple[int, Any]]


def _is_local(provider: str) -> bool:
    return provider in _LOCAL_PROVIDERS


def _jit_allowed(provider: str) -> bool:
    return _is_local(provider)


def _discovery_urls(provider: str, base_url: str) -> list[str]:
    if provider == "ollama":
        return [f"{base_url}/api/tags"]
    if provider == "lm-studio":
        return [f"{base_url}/api/v0/models", f"{base_url}/v1/models"]
    return [f"{base_url}/models"]


def _load_url(provider: str, base_url: str) -> str | None:
    if provider == "ollama":
        return f"{base_url}/api/ps"
    if provider == "lm-studio":
        return f"{base_url}/api/v0/models"
    return None


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
    if not isinstance(provider, str) or provider not in _PROVIDERS:
        return None
    key = payload.get("api_key")
    if _is_local(provider):
        # Local runtimes never require a secret; an empty key is valid.
        if key is not None and (not isinstance(key, str) or len(key) > 2048):
            return None
        normalized_key = key.strip() if isinstance(key, str) else ""
    else:
        if (
            not isinstance(key, str)
            or not key.strip()
            or len(key) > 2048
            or any(char.isspace() for char in key)
        ):
            return None
        normalized_key = key.strip()
    base_url = _endpoint(provider, payload.get("base_url"))
    if base_url is None:
        return None
    return ProviderCandidate(provider, base_url, normalized_key)


def normalize_model(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        model_id = item.strip()
        source: Mapping[str, Any] = {}
    elif isinstance(item, Mapping):
        model_id = item.get("id")
        if not isinstance(model_id, str) and isinstance(item.get("name"), str):
            model_id = item["name"]
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


def _parse_discovery(provider: str, body: Any) -> list[dict[str, Any]] | None:
    """Extract normalized models from a provider discovery payload."""
    if isinstance(body, list):  # LM Studio /api/v0/models returns a list
        raw_models = body
    elif isinstance(body, Mapping):
        raw_models = body.get("data", body.get("models"))
    else:
        return None
    if not isinstance(raw_models, list):
        return None
    models = [model for item in raw_models if (model := normalize_model(item))]
    return models or None


class ProviderRegistry:
    """Registry with bounded backend transport and categorical telemetry only.

    ``key_resolver`` (optional) supplies the stored API key for a provider
    when a payload omits it, so the registry can validate against an already
    configured secret (e.g. a model-only change from the settings wizard).
    The resolver receives the provider name and must return the key value;
    resolution failures degrade to the plain candidate path.
    """

    def __init__(
        self,
        transport: Transport | None = None,
        telemetry: Callable[[dict[str, Any]], None] | None = None,
        key_resolver: Callable[[str], str] | None = None,
    ):
        self.transport = transport
        self.telemetry = telemetry
        self._key_resolver = key_resolver

    def _candidate(self, payload: Mapping[str, Any]) -> ProviderCandidate | None:
        candidate = candidate_from_payload(payload)
        if candidate is not None:
            return candidate
        if self._key_resolver is None:
            return None
        provider = payload.get("provider")
        if not isinstance(provider, str) or provider not in _PROVIDERS:
            return None
        if _is_local(provider):
            return None  # local never fails due to key
        key = payload.get("api_key")
        if isinstance(key, str) and key.strip():
            return None  # had a key but still failed -> not a key issue
        try:
            stored = self._key_resolver(provider)
        except Exception:
            return None
        if not isinstance(stored, str) or not stored.strip():
            return None
        if any(c.isspace() for c in stored) or len(stored) > 2048:
            return None
        augmented = dict(payload)
        augmented["api_key"] = stored
        return candidate_from_payload(augmented)

    def _record(self, outcome: str, candidate: ProviderCandidate, category: str | None, started: float) -> None:
        if self.telemetry:
            self.telemetry({
                "outcome": outcome,
                "latency_ms": min(120000, round((time.monotonic() - started) * 1000)),
                "adapter": candidate.provider,
                "failure_category": category,
                "activation_state": "not-attempted",
            })

    def _request(self, candidate: ProviderCandidate, url: str) -> tuple[int, Any]:
        headers = {"Accept": "application/json"}
        if candidate.api_key:
            headers["Authorization"] = f"Bearer {candidate.api_key}"
        if self.transport:
            return self.transport("GET", url, headers)
        with httpx.Client(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            response = client.get(url, headers=headers)
            try:
                body = response.json()
            except ValueError:
                body = None
            return response.status_code, body

    def _discover_models(self, candidate: ProviderCandidate) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Collect models from every provider discovery URL, merged by id.

        LM Studio contributes both its downloaded set (``/api/v0/models``)
        and its JIT-visible set (``/v1/models``); Ollama and OpenAI-family
        providers contribute a single endpoint. An empty merged result fails
        with the most relevant error category.
        """
        urls = _discovery_urls(candidate.provider, candidate.base_url)
        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        error: dict[str, Any] | None = None
        for url in urls:
            try:
                status, body = self._request(candidate, url)
            except (httpx.TimeoutException, TimeoutError):
                error = {"outcome": "failed", "category": "timeout", "provider": candidate.provider,
                         "message": "Model discovery timed out."}
                continue
            except (httpx.HTTPError, OSError):
                error = {"outcome": "failed", "category": "transport", "provider": candidate.provider,
                         "message": "Model discovery could not reach the provider."}
                continue
            if status >= 400:
                continue
            models = _parse_discovery(candidate.provider, body)
            if models is None:
                continue
            for model in models:
                if model["id"] not in seen:
                    seen.add(model["id"])
                    collected.append(model)
        if collected:
            return collected, None
        return [], error or {"outcome": "failed", "category": "invalid-response",
                             "provider": candidate.provider,
                             "message": "The provider returned no usable model list."}

    def _loaded_ids(self, candidate: ProviderCandidate) -> list[str] | None:
        """Return in-memory loaded model ids, or None when the concept/runtime
        does not apply or the load endpoint is unavailable."""
        url = _load_url(candidate.provider, candidate.base_url)
        if url is None:
            return None
        try:
            status, body = self._request(candidate, url)
        except (httpx.HTTPError, OSError, TimeoutError):
            return None
        if status >= 400:
            return None
        if candidate.provider == "ollama":
            if not isinstance(body, Mapping):
                return None
            loaded = body.get("models")
            if not isinstance(loaded, list):
                return None
            return [str(item.get("name", "")) for item in loaded if isinstance(item, Mapping) and item.get("name")]
        if isinstance(body, list):  # LM Studio v0 state
            return [
                str(item.get("id", ""))
                for item in body
                if isinstance(item, Mapping) and item.get("state") == "loaded" and item.get("id")
            ]
        return None

    def validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        candidate = self._candidate(payload)
        if candidate is None:
            provider = payload.get("provider") if isinstance(payload.get("provider"), str) else "unknown"
            result = {"outcome": "failed", "category": "invalid-request", "provider": provider,
                      "message": "Provide a supported provider, endpoint, and API key."}
            if self.telemetry:
                self.telemetry({"outcome": "failed", "latency_ms": 0, "adapter": provider,
                                "failure_category": "invalid-request", "activation_state": "not-attempted"})
            return result
        target = _discovery_urls(candidate.provider, candidate.base_url)[0]
        try:
            status, _ = self._request(candidate, target)
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
            return {**validation, "models": [], "loaded_models": [], "jit_load_allowed": False}
        candidate = self._candidate(payload)
        assert candidate is not None
        started = time.monotonic()
        models, error = self._discover_models(candidate)
        if error is not None:
            self._record("failed", candidate, error["category"], started)
            return {**error, "models": [], "loaded_models": [], "jit_load_allowed": False}
        loaded = self._loaded_ids(candidate)
        self._record("success", candidate, None, started)
        return {
            "outcome": "discovered",
            "category": "ok",
            "provider": candidate.provider,
            "models": models,
            "loaded_models": list(loaded or []),
            "jit_load_allowed": _jit_allowed(candidate.provider),
        }

    def connection_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Report which models are available (installed/downloaded) vs loaded."""
        validation = self.validate(payload)
        if validation["outcome"] != "validated":
            return {**validation, "available_models": [], "loaded_models": [], "jit_load_allowed": False}
        candidate = self._candidate(payload)
        assert candidate is not None
        models, _ = self._discover_models(candidate)
        available = [model["id"] for model in models]
        loaded = self._loaded_ids(candidate)
        if loaded is None:
            # Remote SaaS has no JIT: every available model is loaded.
            loaded = available
        return {
            "outcome": "ok",
            "provider": candidate.provider,
            "available_models": available,
            "loaded_models": loaded,
            "jit_load_allowed": _jit_allowed(candidate.provider),
        }

    def load_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Per-model loaded flags derived from the runtime load endpoint."""
        state = self.connection_state(payload)
        if state["outcome"] != "ok":
            return {**state, "models": []}
        loaded = set(state["loaded_models"])
        models = [
            {"id": model_id, "loaded": model_id in loaded}
            for model_id in state["available_models"]
        ]
        return {**state, "models": models}