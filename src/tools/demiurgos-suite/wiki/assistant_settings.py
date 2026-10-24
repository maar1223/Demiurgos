# -*- coding: utf-8 -*-
"""Secure Profile settings for the Wiki assistant.

The browser can select a model and submit a replacement OpenCode Go key, but
the key is never returned or logged. The service writes the active Hermes
profile only: ``model.default`` is the bare model id, while the provider and
base URL remain the OpenCode Go contract. Hermes reloads those files by mtime
and size on the next gateway request, so the Wiki assistant does not send a
browser-supplied model override. ``HERMES_GATEWAY_KEY`` remains a separate
project-level credential used only by the Wiki-to-Hermes gateway client.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit
import uuid

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request

# Ensure sibling tool packages (capability_probes) are importable.
_TOOLS_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from assistant_provider_adapters import (
    ProviderCandidate,
    ProviderRegistry,
    candidate_from_payload,
    default_base_url,
    normalize_model,
)
from capability_probes.runner import ProbeRunner
from hermes_runtime import HermesRuntimeSeam


_PROVIDER = "opencode-go"
_BASE_URL = default_base_url(_PROVIDER) or ""
_API_KEY_ENV = "OPENCODE_GO_API_KEY"
_PROVIDER_KEY_ENV = {
    "opencode-go": "OPENCODE_GO_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "compatible": "ASSISTANT_PROVIDER_API_KEY",
}
# Hermes resolves ``model.provider`` against its own registry; the Demiurgos
# provider ids are a product vocabulary the installed runtime does not know
# (``compatible`` and even ``openai`` are rejected — the latter is only a
# models.dev alias of ``openrouter``). Persist the Hermes-resolvable identity
# for the same OpenAI-compatible chat-completions transport the probes
# validated. ``compatible``/``openai`` use Hermes' bare ``custom`` endpoint
# instead of the native ``openai-api`` identity because the latter forces the
# Responses transport, which Demiurgos never probes.
_HERMES_PROVIDERS = {
    "opencode-go": "opencode-go",
    "openrouter": "openrouter",
    "openai": "custom",
    "compatible": "custom",
    "ollama": "ollama",
    "lm-studio": "lmstudio",
}
# ``model.api_key`` references Demiurgos owns. Only the generic ``compatible``
# endpoint needs one: its host is unknown, so Hermes cannot fall back to a
# host-gated ``<VENDOR>_API_KEY``. The reference resolves the secret Demiurgos
# already stores in the profile .env (mode 600); the secret never lands in
# config.yaml.
_MODEL_API_KEY_REFERENCES = {
    "compatible": "${ASSISTANT_PROVIDER_API_KEY}",
}
_API_KEY_MAX_LENGTH = 1024
_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Server-owned catalog. Values are bare Hermes model ids, never provider/model
# strings. Keep this list explicit so arbitrary model input cannot reach Hermes.
ASSISTANT_MODEL_CATALOG: tuple[dict[str, Any], ...] = (
    {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna", "capability": "multimodal", "pricing": None},
    {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash", "capability": "text-only", "pricing": None},
    {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro", "capability": "text-only", "pricing": None},
    {"id": "deepseek-v4-lite", "label": "DeepSeek V4 Lite", "capability": "text-only", "pricing": None},
    {"id": "qwen3.6-plus", "label": "Qwen 3.6 Plus", "capability": "multimodal", "pricing": None},
)
_ALLOWED_MODELS = frozenset(item["id"] for item in ASSISTANT_MODEL_CATALOG)
PROVIDER_REGISTRY = ProviderRegistry()


class AssistantSettingsError(RuntimeError):
    """Raised when the active Hermes profile cannot be resolved safely."""


class StaleRevisionError(AssistantSettingsError):
    """Raised when a saved wizard snapshot is older than the profile."""


@dataclass(frozen=True)
class HermesProfilePaths:
    root: Path
    profile: Path
    config: Path
    env: Path
    name: str


@dataclass(frozen=True)
class AssistantModel:
    id: str
    label: str
    capability: str = "unknown"
    pricing: dict[str, Any] | None = None


@dataclass(frozen=True)
class AssistantSettingsStatus:
    provider: str
    base_url: str
    model: AssistantModel
    key_configured: bool
    revision: int
    runtime_state: str = "saved-not-active"

    def public(self) -> dict[str, Any]:
        """Return metadata only; credentials are intentionally unrepresentable."""
        capability = self.model.capability
        if capability not in {"multimodal", "text-only", "unknown"}:
            capability = "unknown"
        return {
            "provider": self.provider,
            "base_url": _public_base_url(self.base_url),
            "model": self.model.id,
            "model_metadata": {
                "id": self.model.id,
                "label": self.model.label,
                "capability": capability,
                "pricing": self.model.pricing,
            },
            "key_configured": self.key_configured,
            "revision": self.revision,
            "runtime_state": self.runtime_state,
            "models": [dict(item) for item in ASSISTANT_MODEL_CATALOG],
        }


def _public_base_url(value: str) -> str:
    """Remove URL credentials and query material before crossing the API boundary."""
    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.hostname:
            return ""
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = host if not parsed.port else f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except ValueError:
        return ""


def _resolve_profile_paths() -> HermesProfilePaths:
    """Resolve the same profile layout used by Hermes without a user path."""
    override = os.environ.get("HERMES_HOME", "").strip()
    if override:
        root = Path(override).expanduser()
    elif os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if not local_app_data:
            raise AssistantSettingsError(
                "No se pudo resolver LOCALAPPDATA para el perfil de Hermes"
            )
        root = Path(local_app_data) / "hermes"
    else:
        home = os.environ.get("HOME", "").strip()
        if not home:
            raise AssistantSettingsError(
                "No se pudo resolver HOME para el perfil de Hermes"
            )
        root = Path(home) / ".hermes"

    try:
        root = root.resolve()
        active_file = root / "active_profile"
        active_name = "default"
        if active_file.is_file():
            active_name = active_file.read_text(encoding="utf-8").strip() or "default"
    except (OSError, UnicodeError) as exc:
        raise AssistantSettingsError(
            "No se pudo leer el perfil activo de Hermes; verificá HERMES_HOME"
        ) from exc

    if active_name == "default":
        profile = root
    elif _PROFILE_NAME.fullmatch(active_name):
        profiles_root = (root / "profiles").resolve()
        profile = (profiles_root / active_name).resolve()
        try:
            profile.relative_to(profiles_root)
        except ValueError as exc:
            raise AssistantSettingsError(
                "El perfil activo de Hermes no está dentro de profiles/"
            ) from exc
    else:
        raise AssistantSettingsError("El nombre del perfil activo de Hermes no es válido")

    return HermesProfilePaths(
        root=root,
        profile=profile,
        config=profile / "config.yaml",
        env=profile / ".env",
        name=active_name,
    )


def _read_config(path: Path) -> tuple[str, dict[str, Any], str]:
    if not path.is_file():
        raise AssistantSettingsError(
            "No se encontró config.yaml en el perfil activo de Hermes; iniciá Hermes "
            "con ese perfil y volvé a intentar"
        )
    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise AssistantSettingsError(
            "No se pudo leer config.yaml del perfil activo de Hermes"
        ) from exc
    if not isinstance(data, dict):
        raise AssistantSettingsError("config.yaml del perfil activo de Hermes no es válido")
    model = data.get("model")
    if not isinstance(model, dict):
        model = {}
    return content, model, data


def _model_metadata(model_id: str, stored: dict[str, Any] | None = None) -> AssistantModel:
    stored = stored or {}
    catalog = next((item for item in ASSISTANT_MODEL_CATALOG if item["id"] == model_id), None)
    capability = stored.get("capability") or (catalog or {}).get("capability") or "unknown"
    if capability not in {"multimodal", "text-only", "unknown"}:
        capability = "unknown"
    return AssistantModel(
        id=model_id,
        label=str(stored.get("label") or (catalog or {}).get("label") or model_id),
        capability=capability,
        pricing=stored.get("pricing") if isinstance(stored.get("pricing"), dict) else None,
    )


def _provider_key_env(provider: str) -> str:
    return _PROVIDER_KEY_ENV.get(provider, _API_KEY_ENV)


def _hermes_provider(provider: str) -> str:
    """Hermes-resolvable id for a Demiurgos provider (S1).

    Unknown ids pass through unchanged: they come from a legacy profile, and
    rewriting them into a guess would be worse than the existing value.
    """
    return _HERMES_PROVIDERS.get(provider, provider)


def _managed_api_key_reference(provider: str) -> str | None:
    """The ``model.api_key`` reference Demiurgos owns for ``provider``, if any."""
    return _MODEL_API_KEY_REFERENCES.get(provider)


def _status_from_config(paths: HermesProfilePaths, data: dict[str, Any]) -> AssistantSettingsStatus:
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    normalized = data.get("assistant_settings")
    normalized = normalized if isinstance(normalized, dict) else {}
    provider = str(normalized.get("provider") or model.get("provider") or "")
    base_url = str(
        normalized.get("base_url")
        or model.get("base_url")
        or default_base_url(provider)
        or ""
    )
    model_id = str(normalized.get("model_id") or model.get("default") or "")
    revision = normalized.get("revision", 0)
    try:
        revision = max(0, int(revision))
    except (TypeError, ValueError):
        revision = 0
    return AssistantSettingsStatus(
        provider=provider,
        base_url=base_url,
        model=_model_metadata(model_id, normalized),
        key_configured=_env_has_key(paths.env, provider),
        revision=revision,
    )


def _set_normalized_content(content: str, status: AssistantSettingsStatus) -> str:
    """Append/replace only our top-level metadata block; leave legacy YAML intact."""
    lines = content.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith("assistant_settings:")), None)
    end = len(lines)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()), len(lines))
        del lines[start:end]
    newline = "\r\n" if "\r\n" in content else "\n"
    block = [
        f"assistant_settings:{newline}", f"  revision: {status.revision}{newline}",
        f"  provider: {status.provider}{newline}", f"  base_url: {status.base_url}{newline}",
        f"  model_id: {status.model.id}{newline}", f"  model_label: {status.model.label}{newline}",
        f"  capability: {status.model.capability}{newline}",
        f"  pricing: {yaml.safe_dump(status.model.pricing, default_flow_style=True).strip() if status.model.pricing else 'null'}{newline}",
    ]
    if lines and lines[-1].strip():
        lines.append(newline)
    lines.extend(block)
    return "".join(lines)


def _check_revision(expected: Any, actual: int) -> None:
    if expected is not None and (not isinstance(expected, int) or expected != actual):
        raise StaleRevisionError("La configuración cambió; recargá antes de guardar")


def _env_has_key(path: Path, provider: str = "opencode-go") -> bool:
    if not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise AssistantSettingsError(
            "No se pudo leer el .env del perfil activo de Hermes"
        ) from exc
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{_provider_key_env(provider)}="):
            return bool(stripped.split("=", 1)[1].strip().strip('"').strip("'"))
    return False


def _env_key_value(path: Path, provider: str = "opencode-go") -> str:
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return ""
    env_key = _provider_key_env(provider)
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{env_key}="):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _stored_api_key(provider: str) -> str:
    try:
        paths = _resolve_profile_paths()
        return _env_key_value(paths.env, provider)
    except AssistantSettingsError:
        return ""


def _candidate_from_payload_with_fallback(payload: Mapping[str, Any]) -> ProviderCandidate | None:
    candidate = candidate_from_payload(payload)
    if candidate is not None:
        return candidate
    key = payload.get("api_key")
    if isinstance(key, str) and key.strip():
        return None
    provider = payload.get("provider")
    if not isinstance(provider, str):
        return None
    stored = _stored_api_key(provider)
    if not stored:
        return None
    augmented = dict(payload)
    augmented["api_key"] = stored
    return candidate_from_payload(augmented)


def _validate_model(value: Any) -> str:
    if not isinstance(value, str) or value not in _ALLOWED_MODELS:
        raise ValueError("modelo no permitido; elegí uno del catálogo del asistente")
    return value


def _validate_api_key(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("api_key debe ser texto")
    normalized = value.strip()
    if not normalized:
        raise ValueError("api_key requerido; para quitarlo usá DELETE")
    if any(char.isspace() for char in normalized):
        raise ValueError("api_key no puede contener espacios")
    if len(normalized) > _API_KEY_MAX_LENGTH:
        raise ValueError("api_key demasiado largo")
    return normalized


def _set_env_content(content: str, value: str | None, env_key: str = _API_KEY_ENV) -> tuple[str, bool]:
    lines = content.splitlines(keepends=True)
    new_lines: list[str] = []
    found = False
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key == env_key:
                found = True
                if value is not None:
                    new_lines.append(f"{env_key}={value}\n")
                continue
        new_lines.append(line)

    if value is not None and not found:
        if new_lines and new_lines[-1].strip():
            new_lines.append("\n")
        new_lines.append(f"{env_key}={value}\n")
    updated = "".join(new_lines)
    return updated, updated != content


def _set_model_config_content(
    content: str,
    model: str,
    provider: str,
    base_url: str,
    api_key: str | None = None,
) -> str:
    """Update only the top-level model block and preserve other config text.

    ``provider`` is the Demiurgos id; the persisted ``model.provider`` is its
    Hermes-resolvable counterpart (S1). ``api_key`` is the reference Demiurgos
    owns for that provider (S2). When it is ``None`` a previously owned
    reference is removed while any other ``model.api_key`` value is preserved
    untouched (S4).
    """
    hermes_provider = _hermes_provider(provider)
    lines = content.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in content else "\n"
    model_index = next(
        (index for index, line in enumerate(lines) if re.fullmatch(r"model:\s*(?:\r?\n)?", line)),
        None,
    )
    if model_index is None:
        reference = f"  api_key: {api_key}{newline}" if api_key else ""
        return (
            f"model:{newline}"
            f"  default: {model}{newline}"
            f"  provider: {hermes_provider}{newline}"
            f"  base_url: {base_url}{newline}"
            f"{reference}"
            + content
        )

    block_end = len(lines)
    for index in range(model_index + 1, len(lines)):
        if lines[index] and not lines[index][0].isspace() and not lines[index].lstrip().startswith("#"):
            block_end = index
            break

    desired = {
        "default": model,
        "provider": hermes_provider,
        "base_url": base_url,
    }
    if api_key:
        desired["api_key"] = api_key
    managed_references = frozenset(_MODEL_API_KEY_REFERENCES.values())
    found: set[str] = set()
    updated: list[str] = []
    dropped = 0
    for index, line in enumerate(lines):
        if model_index < index < block_end:
            match = re.fullmatch(r"(\s{2})(default|provider|base_url|api_key):(.*?)(\r?\n)?", line)
            if match:
                key = match.group(2)
                if key == "api_key" and "api_key" not in desired:
                    if match.group(3).strip() in managed_references:
                        # Demiurgos' own stale reference: drop it so a later
                        # provider never expands a secret it does not use.
                        dropped += 1
                        continue
                    # A value Demiurgos does not own is preserved verbatim.
                    found.add(key)
                else:
                    found.add(key)
                    line = f"  {key}: {desired[key]}{newline}"
        updated.append(line)

    insert_at = block_end - dropped
    missing_lines = [f"  {key}: {desired[key]}{newline}" for key in desired if key not in found]
    updated[insert_at:insert_at] = missing_lines
    return "".join(updated)


def _atomic_write(path: Path, content: str, mode: int | None = None) -> None:
    if not path.parent.is_dir():
        raise AssistantSettingsError("El directorio del perfil activo de Hermes no existe")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if mode is not None:
            try:
                os.chmod(path, mode)
            except OSError:
                # Read-only bit is the only portable chmod effect on Windows.
                pass
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise AssistantSettingsError("No se pudo guardar la configuración del asistente") from exc


_ENV_FILE_MODE = 0o600


def current_config_revision() -> int | None:
    """Current normalized config revision for the active Hermes profile.

    Returns ``None`` (never raises) when the profile cannot be resolved, so a
    best-effort evidence recorder can stay total.
    """
    try:
        paths = _resolve_profile_paths()
        _, _, data = _read_config(paths.config)
        return _status_from_config(paths, data).revision
    except (AssistantSettingsError, OSError, UnicodeError):
        return None


def _status(
    paths: HermesProfilePaths,
    model: dict[str, Any],
    data: dict[str, Any] | None = None,
    runtime_seam: HermesRuntimeSeam | None = None,
    runtime_state_resolver: Callable[[int], str] | None = None,
) -> dict[str, Any]:
    data = data or {"model": model}
    status = _status_from_config(paths, data)
    public = status.public()
    public["active_profile"] = paths.name
    if runtime_state_resolver is not None:
        public["runtime_state"] = runtime_state_resolver(status.revision)
    elif runtime_seam is not None:
        public["runtime_state"] = runtime_seam.state_for(status.revision)
    return public


def _persist_provider_configuration(payload: dict[str, Any], model: AssistantModel) -> dict[str, Any]:
    candidate = _candidate_from_payload_with_fallback(payload)
    if candidate is None:
        raise ValueError("Provider, endpoint, and API key are required")
    paths = _resolve_profile_paths()
    config_content, _, config_data = _read_config(paths.config)
    current_status = _status_from_config(paths, config_data)
    _check_revision(payload.get("revision"), current_status.revision)
    env_content = paths.env.read_text(encoding="utf-8") if paths.env.is_file() else ""
    next_status = AssistantSettingsStatus(
        provider=candidate.provider,
        base_url=candidate.base_url,
        model=model,
        key_configured=bool(candidate.api_key),
        revision=current_status.revision + 1,
    )
    next_config = _set_model_config_content(
        config_content,
        model.id,
        candidate.provider,
        candidate.base_url,
        _managed_api_key_reference(candidate.provider),
    )
    next_config = _set_normalized_content(next_config, next_status)
    payload_had_key = isinstance(payload.get("api_key"), str) and bool(payload.get("api_key").strip())
    if payload_had_key and candidate.api_key:
        next_env, env_changed = _set_env_content(
            env_content, candidate.api_key, _provider_key_env(candidate.provider)
        )
    else:
        # Model-only save (or a local provider with no secret): the stored
        # key was resolved from the env file, so leave the env untouched.
        next_env, env_changed = env_content, False
    config_changed = next_config != config_content
    try:
        if config_changed:
            _atomic_write(paths.config, next_config)
        if env_changed:
            _atomic_write(paths.env, next_env, mode=_ENV_FILE_MODE)
    except AssistantSettingsError:
        if config_changed:
            _atomic_write(paths.config, config_content)
        if env_changed:
            _atomic_write(paths.env, env_content, mode=_ENV_FILE_MODE)
        raise
    _, refreshed_model, refreshed_data = _read_config(paths.config)
    return _status(paths, refreshed_model, refreshed_data)


def _default_probe_factory(payload: dict[str, Any], model_id: str) -> ProbeRunner:
    candidate = _candidate_from_payload_with_fallback(payload)
    if candidate is None:
        raise ValueError("Provider, endpoint, and API key are required")
    return ProbeRunner(candidate.base_url, model_id, api_key=candidate.api_key)


def create_assistant_settings_router(
    require_principal: Callable[[Request], Any],
    provider_registry: ProviderRegistry | None = None,
    runtime_seam: HermesRuntimeSeam | None = None,
    probe_factory: Callable[[dict[str, Any], str], ProbeRunner] | None = None,
    on_acceptance: Callable[[str], None] | None = None,
    runtime_state_resolver: Callable[[int], str] | None = None,
    runtime_liveness: Callable[[], bool] | None = None,
) -> APIRouter:
    """Build authenticated assistant settings routes.

    ``on_acceptance`` (optional) is invoked after a successful three-proof
    save with the applied runtime state (``active``/``pending-reload``/
    ``saved-not-active``) so the host can record acceptance evidence (ONB-3.6).
    It is never called when probes fail or the save is rejected.

    ``runtime_state_resolver`` (optional) derives the runtime state for a config
    revision from persisted evidence plus live liveness; when provided it owns
    every read/save state (``runtime_seam`` then stays as the legacy fallback for
    callers that inject only the seam). ``runtime_liveness`` reports whether the
    runtime is up right now and feeds the save-time acceptance state.
    """
    router = APIRouter(prefix="/api/profile/assistant", tags=["assistant-settings"])
    if provider_registry is None:
        def _resolver(provider: str) -> str:
            return _stored_api_key(provider)

        # The router owns an isolated registry: the stored-key resolver never
        # lands on the shared PROVIDER_REGISTRY (injected-test registries stay
        # untouched). Transport/telemetry are read LIVE from the shared global
        # at call time so doubles attached to it at runtime (e.g. the test
        # transport monkeypatched on PROVIDER_REGISTRY) still apply; when the
        # global carries none, fall back to the default HTTP client path that
        # ProviderRegistry._request would use.
        def _shared_transport(method: str, url: str, headers: dict[str, str]) -> tuple[int, Any]:
            transport = getattr(PROVIDER_REGISTRY, "transport", None)
            if transport is not None:
                return transport(method, url, headers)
            with httpx.Client(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
                response = client.get(url, headers=headers)
                try:
                    body = response.json()
                except ValueError:
                    body = None
                return response.status_code, body

        def _shared_telemetry(event: dict[str, Any]) -> None:
            telemetry = getattr(PROVIDER_REGISTRY, "telemetry", None)
            if telemetry is not None:
                telemetry(event)

        registry = ProviderRegistry(
            transport=_shared_transport,
            telemetry=_shared_telemetry,
            key_resolver=_resolver,
        )
    else:
        registry = provider_registry
    seam = runtime_seam or HermesRuntimeSeam()
    probe_factory = probe_factory or _default_probe_factory

    def guard(request: Request) -> None:
        if require_principal(request) is None:
            raise HTTPException(status_code=401, detail="Autenticación requerida")

    def settings_error(exc: AssistantSettingsError) -> HTTPException:
        status = 409 if isinstance(exc, StaleRevisionError) else 503
        return HTTPException(status_code=status, detail=str(exc))

    def selected_model(payload: dict[str, Any]) -> dict[str, Any]:
        model = normalize_model(payload.get("model") or payload.get("manual_model_id"))
        if model is None:
            raise HTTPException(status_code=400, detail="A usable model ID is required")
        return model

    @router.get("")
    @router.get("/status")
    def get_settings(request: Request) -> dict[str, Any]:
        guard(request)
        try:
            paths = _resolve_profile_paths()
            _, model, data = _read_config(paths.config)
            public = _status(paths, model, data, seam, runtime_state_resolver)
            # S2b (degradable-ai-provider): an explicit presence boolean so
            # the UI can distinguish "gateway up" from "configured state".
            # Derived from the same read-only liveness probe that feeds the
            # save-time acceptance; purely additive, no new endpoint.
            if runtime_liveness is not None:
                public["gateway_running"] = bool(runtime_liveness())
            return public
        except AssistantSettingsError as exc:
            raise settings_error(exc) from exc

    @router.put("")
    def update_settings(request: Request, body: dict | None = None) -> dict[str, Any]:
        guard(request)
        payload = body if isinstance(body, dict) else {}
        has_model = "model" in payload
        has_key = "api_key" in payload
        if not has_model and not has_key:
            raise HTTPException(status_code=400, detail="Indicá model o api_key")

        try:
            selected_model = _validate_model(payload.get("model")) if has_model else None
            api_key = _validate_api_key(payload.get("api_key")) if has_key else None
            paths = _resolve_profile_paths()
            config_content, _, config_data = _read_config(paths.config)
            current_status = _status_from_config(paths, config_data)
            _check_revision(payload.get("revision"), current_status.revision)
            env_content = paths.env.read_text(encoding="utf-8") if paths.env.is_file() else ""
            next_model_id = selected_model or current_status.model.id
            provider = current_status.provider or _PROVIDER
            # A model-only save must also keep a previously owned api_key
            # reference; a key-only save refreshes the block so a legacy profile
            # gains the Hermes-resolvable provider and the reference.
            reference = (
                _managed_api_key_reference(provider)
                if (has_key or current_status.key_configured)
                else None
            )
            next_config = (
                _set_model_config_content(
                    config_content,
                    next_model_id,
                    provider,
                    current_status.base_url or _BASE_URL,
                    reference,
                )
                if next_model_id and (selected_model is not None or has_key)
                else config_content
            )
            next_status = AssistantSettingsStatus(
                provider=current_status.provider or _PROVIDER,
                base_url=current_status.base_url or _BASE_URL,
                model=_model_metadata(selected_model or current_status.model.id),
                key_configured=current_status.key_configured or has_key,
                revision=current_status.revision + 1,
            )
            next_config = _set_normalized_content(next_config, next_status)
            next_env, env_changed = (
                _set_env_content(env_content, api_key, _provider_key_env(current_status.provider or _PROVIDER))
                if has_key else (env_content, False)
            )

            config_changed = next_config != config_content
            try:
                if config_changed:
                    _atomic_write(paths.config, next_config)
                if env_changed:
                    _atomic_write(paths.env, next_env, mode=_ENV_FILE_MODE)
            except AssistantSettingsError:
                # Restore every file touched by this transaction, including a
                # metadata migration that preceded a failed secret write.
                if config_changed:
                    _atomic_write(paths.config, config_content)
                if env_changed:
                    _atomic_write(paths.env, env_content, mode=_ENV_FILE_MODE)
                raise
            _, refreshed_model, refreshed_data = _read_config(paths.config)
            return _status(paths, refreshed_model, refreshed_data, seam, runtime_state_resolver)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (AssistantSettingsError, OSError, UnicodeError) as exc:
            if isinstance(exc, AssistantSettingsError):
                raise settings_error(exc) from exc
            raise HTTPException(status_code=503, detail="No se pudo leer la configuración del asistente") from exc

    @router.post("/connection/validate")
    def validate_connection(request: Request, body: dict | None = None) -> dict[str, Any]:
        guard(request)
        return registry.validate(body if isinstance(body, dict) else {})

    @router.post("/models/discover")
    def discover_models(request: Request, body: dict | None = None) -> dict[str, Any]:
        guard(request)
        return registry.discover(body if isinstance(body, dict) else {})

    @router.post("/probe/text")
    def probe_text(request: Request, body: dict | None = None) -> dict[str, Any]:
        guard(request)
        payload = body if isinstance(body, dict) else {}
        model = selected_model(payload)
        try:
            result = probe_factory(payload, model["id"]).run_text()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"outcome": result.outcome, "oracle": result.oracle, "message": result.message}

    @router.post("/probe/vision")
    def probe_vision(request: Request, body: dict | None = None) -> dict[str, Any]:
        guard(request)
        payload = body if isinstance(body, dict) else {}
        model = selected_model(payload)
        try:
            result = probe_factory(payload, model["id"]).run_vision()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"outcome": result.outcome, "oracle": result.oracle, "message": result.message}

    @router.put("/configuration")
    def save_configuration(request: Request, body: dict | None = None) -> dict[str, Any]:
        guard(request)
        payload = body if isinstance(body, dict) else {}
        model = selected_model(payload)
        validation = registry.validate(payload)
        if validation["outcome"] != "validated":
            raise HTTPException(status_code=422, detail=validation.get("message", "Connection validation failed"))
        # Three proofs gate (OC14/OC15/OC16): text + causal vision are re-run
        # server-side; the provider label never substitutes for the probes.
        # The Hermes runtime acceptance is applied after persistence below.
        try:
            runner = probe_factory(payload, model["id"])
            text = runner.run_text()
            vision = runner.run_vision()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if text.outcome != "passed" or vision.outcome != "passed":
            failing = "text probe" if text.outcome != "passed" else "causal vision probe"
            raise HTTPException(
                status_code=422,
                detail=f"Assistant cannot be configured: the {failing} did not pass.",
            )
        try:
            saved = _persist_provider_configuration(
                payload,
                AssistantModel(
                    id=model["id"], label=model["label"],
                    capability=model["capability"], pricing=model["pricing"],
                ),
            )
            if runtime_state_resolver is not None:
                # Real runtime truth: exactly ONE liveness observation drives
                # both the recorded acceptance and the response. Probing a
                # second time (through the resolver) could disagree with itself
                # — a TOCTOU race — and the recorded acceptance is the arbiter,
                # so the response must be the value that was just recorded. A
                # save with the gateway down therefore stays non-active until a
                # later save observes it up (fail closed, by design).
                live = runtime_liveness is not None and runtime_liveness()
                runtime_state = "active" if live else "saved-not-active"
            else:
                runtime_state = seam.apply(saved["revision"]).state
            saved["runtime_state"] = runtime_state
            # ONB-3.6: record the runtime acceptance evidence so the Center
            # badge may become configured only on real acceptance.
            if on_acceptance is not None:
                on_acceptance(runtime_state)
            return saved
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (AssistantSettingsError, OSError, UnicodeError) as exc:
            if isinstance(exc, AssistantSettingsError):
                raise settings_error(exc) from exc
            raise HTTPException(status_code=503, detail="Could not save assistant configuration") from exc

    @router.delete("/key")
    @router.delete("/configuration/key")
    def clear_key(request: Request, body: dict | None = None) -> dict[str, Any]:
        guard(request)
        try:
            paths = _resolve_profile_paths()
            config_content, _, config_data = _read_config(paths.config)
            current_status = _status_from_config(paths, config_data)
            _check_revision((body or {}).get("revision"), current_status.revision)
            env_content = paths.env.read_text(encoding="utf-8") if paths.env.is_file() else ""
            next_env, changed = _set_env_content(
                env_content, None, _provider_key_env(current_status.provider)
            )
            next_status = AssistantSettingsStatus(
                provider=current_status.provider,
                base_url=current_status.base_url,
                model=current_status.model,
                key_configured=False,
                revision=current_status.revision + 1,
            )
            # Clearing the key also releases the reference Demiurgos owns, so
            # the runtime never expands an unset variable into a bearer token.
            base_url = (
                current_status.base_url
                or default_base_url(current_status.provider)
                or ""
            )
            next_config = (
                _set_model_config_content(
                    config_content,
                    current_status.model.id,
                    current_status.provider,
                    base_url,
                    None,
                )
                if base_url and current_status.model.id
                else config_content
            )
            next_config = _set_normalized_content(next_config, next_status)
            config_changed = next_config != config_content
            try:
                if config_changed:
                    _atomic_write(paths.config, next_config)
                if changed:
                    _atomic_write(paths.env, next_env, mode=_ENV_FILE_MODE)
            except AssistantSettingsError:
                if config_changed:
                    _atomic_write(paths.config, config_content)
                if changed:
                    _atomic_write(paths.env, env_content, mode=_ENV_FILE_MODE)
                raise
            _, refreshed_model, refreshed_data = _read_config(paths.config)
            return _status(paths, refreshed_model, refreshed_data, seam, runtime_state_resolver)
        except (AssistantSettingsError, OSError, UnicodeError) as exc:
            if isinstance(exc, AssistantSettingsError):
                raise settings_error(exc) from exc
            raise HTTPException(status_code=503, detail="No se pudo eliminar la clave del asistente") from exc

    return router
