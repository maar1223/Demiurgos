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
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit
import uuid

import yaml
from fastapi import APIRouter, HTTPException, Request

from assistant_provider_adapters import ProviderRegistry, candidate_from_payload, normalize_model
from hermes_runtime import HermesRuntimeSeam


_PROVIDER = "opencode-go"
_BASE_URL = "https://opencode.ai/zen/go/v1"
_API_KEY_ENV = "OPENCODE_GO_API_KEY"
_PROVIDER_KEY_ENV = {
    "opencode-go": "OPENCODE_GO_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "compatible": "ASSISTANT_PROVIDER_API_KEY",
}
_API_KEY_MAX_LENGTH = 1024
_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Server-owned catalog. Values are bare Hermes model ids, never provider/model
# strings. Keep this list explicit so arbitrary model input cannot reach Hermes.
ASSISTANT_MODEL_CATALOG: tuple[dict[str, Any], ...] = (
    {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna", "capability": "unknown", "pricing": None},
    {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash", "capability": "unknown", "pricing": None},
    {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro", "capability": "unknown", "pricing": None},
    {"id": "deepseek-v4-lite", "label": "DeepSeek V4 Lite", "capability": "unknown", "pricing": None},
    {"id": "qwen3.6-plus", "label": "Qwen 3.6 Plus", "capability": "unknown", "pricing": None},
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


def _status_from_config(paths: HermesProfilePaths, data: dict[str, Any]) -> AssistantSettingsStatus:
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    normalized = data.get("assistant_settings")
    normalized = normalized if isinstance(normalized, dict) else {}
    provider = str(normalized.get("provider") or model.get("provider") or "")
    base_url = str(normalized.get("base_url") or model.get("base_url") or "")
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


def _set_model_config_content(content: str, model: str, provider: str, base_url: str) -> str:
    """Update only the top-level model block and preserve other config text."""
    lines = content.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in content else "\n"
    model_index = next(
        (index for index, line in enumerate(lines) if re.fullmatch(r"model:\s*(?:\r?\n)?", line)),
        None,
    )
    if model_index is None:
        return (
            f"model:{newline}"
            f"  default: {model}{newline}"
            f"  provider: {provider}{newline}"
            f"  base_url: {base_url}{newline}"
            + content
        )

    block_end = len(lines)
    for index in range(model_index + 1, len(lines)):
        if lines[index] and not lines[index][0].isspace() and not lines[index].lstrip().startswith("#"):
            block_end = index
            break

    desired = {
        "default": model,
        "provider": provider,
        "base_url": base_url,
    }
    found: set[str] = set()
    updated: list[str] = []
    for index, line in enumerate(lines):
        match = re.fullmatch(r"(\s{2})(default|provider|base_url):.*?(\r?\n)?", line)
        if model_index < index < block_end and match:
            key = match.group(2)
            found.add(key)
            updated.append(f"  {key}: {desired[key]}{newline}")
        else:
            updated.append(line)

    insert_at = block_end
    missing_lines = [f"  {key}: {desired[key]}{newline}" for key in desired if key not in found]
    updated[insert_at:insert_at] = missing_lines
    return "".join(updated)


def _atomic_write(path: Path, content: str) -> None:
    if not path.parent.is_dir():
        raise AssistantSettingsError("El directorio del perfil activo de Hermes no existe")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise AssistantSettingsError("No se pudo guardar la configuración del asistente") from exc


def _status(
    paths: HermesProfilePaths,
    model: dict[str, Any],
    data: dict[str, Any] | None = None,
    runtime_seam: HermesRuntimeSeam | None = None,
) -> dict[str, Any]:
    data = data or {"model": model}
    status = _status_from_config(paths, data)
    public = status.public()
    public["active_profile"] = paths.name
    if runtime_seam is not None:
        public["runtime_state"] = runtime_seam.state_for(status.revision)
    return public


def _persist_provider_configuration(payload: dict[str, Any], model: AssistantModel) -> dict[str, Any]:
    candidate = candidate_from_payload(payload)
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
        key_configured=True,
        revision=current_status.revision + 1,
    )
    next_config = _set_model_config_content(
        config_content, model.id, candidate.provider, candidate.base_url
    )
    next_config = _set_normalized_content(next_config, next_status)
    next_env, env_changed = _set_env_content(
        env_content, candidate.api_key, _provider_key_env(candidate.provider)
    )
    config_changed = next_config != config_content
    try:
        if config_changed:
            _atomic_write(paths.config, next_config)
        if env_changed:
            _atomic_write(paths.env, next_env)
    except AssistantSettingsError:
        if config_changed:
            _atomic_write(paths.config, config_content)
        if env_changed:
            _atomic_write(paths.env, env_content)
        raise
    _, refreshed_model, refreshed_data = _read_config(paths.config)
    return _status(paths, refreshed_model, refreshed_data)


def create_assistant_settings_router(
    require_principal: Callable[[Request], Any],
    provider_registry: ProviderRegistry | None = None,
    runtime_seam: HermesRuntimeSeam | None = None,
) -> APIRouter:
    """Build authenticated assistant settings routes."""
    router = APIRouter(prefix="/api/profile/assistant", tags=["assistant-settings"])
    registry = provider_registry or PROVIDER_REGISTRY
    seam = runtime_seam or HermesRuntimeSeam()

    def guard(request: Request) -> None:
        if require_principal(request) is None:
            raise HTTPException(status_code=401, detail="Autenticación requerida")

    def settings_error(exc: AssistantSettingsError) -> HTTPException:
        status = 409 if isinstance(exc, StaleRevisionError) else 503
        return HTTPException(status_code=status, detail=str(exc))

    @router.get("")
    @router.get("/status")
    def get_settings(request: Request) -> dict[str, Any]:
        guard(request)
        try:
            paths = _resolve_profile_paths()
            _, model, data = _read_config(paths.config)
            return _status(paths, model, data, seam)
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
            next_config = (
                _set_model_config_content(
                    config_content,
                    selected_model,
                    current_status.provider or _PROVIDER,
                    current_status.base_url or _BASE_URL,
                )
                if selected_model is not None
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
                    _atomic_write(paths.env, next_env)
            except AssistantSettingsError:
                # Restore every file touched by this transaction, including a
                # metadata migration that preceded a failed secret write.
                if config_changed:
                    _atomic_write(paths.config, config_content)
                if env_changed:
                    _atomic_write(paths.env, env_content)
                raise
            _, refreshed_model, refreshed_data = _read_config(paths.config)
            return _status(paths, refreshed_model, refreshed_data, seam)
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

    @router.put("/configuration")
    def save_configuration(request: Request, body: dict | None = None) -> dict[str, Any]:
        guard(request)
        payload = body if isinstance(body, dict) else {}
        model = normalize_model(payload.get("model") or payload.get("manual_model_id"))
        if model is None:
            raise HTTPException(status_code=400, detail="A usable model ID is required")
        if model["capability"] == "unknown" and payload.get("unknown_ack") is not True:
            raise HTTPException(status_code=400, detail="Unknown model capability requires acknowledgement")
        validation = registry.validate(payload)
        if validation["outcome"] != "validated":
            raise HTTPException(status_code=422, detail=validation.get("message", "Connection validation failed"))
        try:
            saved = _persist_provider_configuration(
                payload,
                AssistantModel(
                    id=model["id"], label=model["label"],
                    capability=model["capability"], pricing=model["pricing"],
                ),
            )
            saved["runtime_state"] = seam.apply(saved["revision"]).state
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
            next_config = _set_normalized_content(config_content, next_status)
            config_changed = next_config != config_content
            try:
                if config_changed:
                    _atomic_write(paths.config, next_config)
                if changed:
                    _atomic_write(paths.env, next_env)
            except AssistantSettingsError:
                if config_changed:
                    _atomic_write(paths.config, config_content)
                if changed:
                    _atomic_write(paths.env, env_content)
                raise
            _, refreshed_model, refreshed_data = _read_config(paths.config)
            return _status(paths, refreshed_model, refreshed_data, seam)
        except (AssistantSettingsError, OSError, UnicodeError) as exc:
            if isinstance(exc, AssistantSettingsError):
                raise settings_error(exc) from exc
            raise HTTPException(status_code=503, detail="No se pudo eliminar la clave del asistente") from exc

    return router
