"""
web-config-ui config module.

Provides .env and default-config.json read/write, provider connection
testing, and the KNOWN_PROVIDERS registry.
"""

import json
import os
import shutil
import logging
from typing import Optional

import httpx
from dotenv import dotenv_values

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known Provider Registry
# ---------------------------------------------------------------------------

KNOWN_PROVIDERS: list[dict] = [
    {
        "id": "openai",
        "name": "OpenAI",
        "default_endpoint": "https://api.openai.com/v1",
        "default_text_model": "gpt-4o",
        "supports_vision": True,
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "default_endpoint": "https://api.anthropic.com/v1",
        "default_text_model": "claude-sonnet-4-20250514",
        "supports_vision": True,
    },
    {
        "id": "google",
        "name": "Google (Gemini)",
        "default_endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_text_model": "gemini-2.0-flash",
        "supports_vision": True,
    },
    {
        "id": "groq",
        "name": "Groq",
        "default_endpoint": "https://api.groq.com/openai/v1",
        "default_text_model": "llama-3.3-70b-versatile",
        "supports_vision": False,
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_endpoint": "https://api.deepseek.com/v1",
        "default_text_model": "deepseek-chat",
        "supports_vision": False,
    },
    {
        "id": "ollama",
        "name": "Ollama (Local)",
        "default_endpoint": "http://localhost:11434/v1",
        "default_text_model": "llama3.2",
        "supports_vision": False,
    },
    {
        "id": "opencode-go",
        "name": "OpenCode Go",
        "default_endpoint": "https://opencode.ai/zen/go/v1",
        "default_text_model": "deepseek-v4-flash",
        "supports_vision": True,
    },
    {
        "id": "opencode-zen",
        "name": "OpenCode Zen",
        "default_endpoint": "https://opencode.ai/zen/zen/v1",
        "default_text_model": "deepseek-v4-flash",
        "supports_vision": True,
    },
]

# ---------------------------------------------------------------------------
# Model Vision Registry
# ---------------------------------------------------------------------------
# Maps provider_id -> {model_id: has_vision (bool)} for known models.
# Provider not in dict → all models unknown (return None, not False).
# Provider in dict but model not → unknown (return None).
# Unknown means "we don't know" ≠ "no vision".

MODEL_VISION: dict[str, dict[str, bool]] = {
    "openai": {
        "gpt-4o": True,
        "gpt-4o-mini": True,
        "gpt-4-turbo": True,
        "gpt-4.1": True,
        "gpt-4": False,
        "gpt-3.5-turbo": False,
    },
    "anthropic": {
        "claude-sonnet-4-20250514": True,
        "claude-opus-4-20250514": True,
        "claude-3-5-sonnet": True,
        "claude-3-5-haiku": True,
        "claude-3-opus": True,
        "claude-3-sonnet": True,
        "claude-3-haiku": True,
    },
    "google": {
        "gemini-2.5-flash": True,
        "gemini-2.5-pro": True,
        "gemini-2.0-flash": True,
        "gemini-1.5-flash": True,
        "gemini-1.5-pro": True,
    },
    "groq": {
        "qwen/qwen3.6-27b": True,
        "meta-llama/llama-4-scout-17b-16e-instruct": True,
        "llama-3.3-70b-versatile": False,
        "llama-3.1-8b-instant": False,
        "openai/gpt-oss-120b": False,
        "openai/gpt-oss-20b": False,
    },
    "deepseek": {
        "deepseek-chat": False,
        "deepseek-reasoner": False,
    },
    "ollama": {
        "gemma4": True,
        "qwen3.5": True,
        "qwen3.6": True,
        "minimax-m3": True,
        "kimi-k2.7-code": True,
        "nemotron3": True,
        "translategemma": True,
        "glm-ocr": True,
        "llava": True,
        "bakllava": True,
        "llama3.2-vision": True,
    },
    "opencode-go": {
        "deepseek-v4-flash": False,
        "deepseek-v4-pro": False,
        "deepseek-v4-lite": False,
    },
    "opencode-zen": {
        "deepseek-v4-flash": False,
        "deepseek-v4-pro": False,
        "deepseek-v4-lite": False,
    },
}

# Keywords that strongly suggest a model supports vision.
# Used as heuristic fallback when neither provider nor model is in MODEL_VISION.
_VISION_HEURISTIC_KEYWORDS: list[str] = [
    "vl",
    "vision",
    "gpt-4o",
    "claude",
    "gemini",
    "omni",
    "llava",
    "bakllava",
    "minimax",
]


def get_vision_tag(provider_id: str, model_id: str) -> dict:
    """Return a vision capability tag for *provider_id* / *model_id*.

    Returns
    -------
    dict
        ``{"tag": "👁️+✍️"|"✍️"|"❓", "confidence": "confirmed"|"probable"|"unknown"}``
    """
    # 1. Look up confirmed entry
    provider_models = MODEL_VISION.get(provider_id)
    if provider_models is not None:
        has_vision = provider_models.get(model_id)
        if has_vision is not None:
            return {
                "tag": "👁️+✍️" if has_vision else "✍️",
                "confidence": "confirmed",
            }

    # 2. Heuristic fallback: check model name for vision keywords
    model_lower = model_id.lower()
    for kw in _VISION_HEURISTIC_KEYWORDS:
        if kw in model_lower:
            return {"tag": "👁️+✍️", "confidence": "probable"}

    # 3. Unknown
    return {"tag": "❓", "confidence": "unknown"}


def get_vision_models(provider_id: str, models: list[str]) -> list[dict]:
    """Tag every model in *models* with its vision capability.

    Returns
    -------
    list[dict]
        Each item: ``{"id": str, "tag": str, "confidence": str}``
    """
    return [
        {"id": m, **get_vision_tag(provider_id, m)}
        for m in models
    ]


# Env variable names managed by this tool
_TEXT_VARS = {
    "text_provider": "DEMIURGOS_TEXT_PROVIDER",
    "text_endpoint": "DEMIURGOS_TEXT_ENDPOINT",
    "text_model": "DEMIURGOS_TEXT_MODEL",
    "text_api_key": "DEMIURGOS_TEXT_API_KEY",
}
_VISION_VARS = {
    "vision_provider": "DEMIURGOS_VISION_PROVIDER",
    "vision_endpoint": "DEMIURGOS_VISION_ENDPOINT",
    "vision_model": "DEMIURGOS_VISION_MODEL",
    "vision_api_key": "DEMIURGOS_VISION_API_KEY",
}
_ALL_DEMIURGOS_VARS: set[str] = {
    *_TEXT_VARS.values(),
    *_VISION_VARS.values(),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def mask_api_key(key: Optional[str]) -> str:
    """Mask an API key for safe logging — never expose keys in output."""
    if not key:
        return "***"
    if len(key) <= 6:
        return "***"
    return key[:3] + "***" + key[-4:]


def _find_provider_by_id(provider_id: str) -> Optional[dict]:
    """Return the KNOWN_PROVIDERS entry for *provider_id* or None."""
    for p in KNOWN_PROVIDERS:
        if p["id"] == provider_id:
            return p
    return None


# ---------------------------------------------------------------------------
# .env read / write
# ---------------------------------------------------------------------------


def read_env(path: str) -> dict:
    """Parse *.path* (dotenv format) and return a dict with known
    ``DEMIURGOS_TEXT_*`` / ``DEMIURGOS_VISION_*`` variables populated.

    Returns
    -------
    dict
        Keys: ``text_provider``, ``text_endpoint``, ``text_model``,
        ``text_api_key``, ``vision_provider``, ``vision_endpoint``,
        ``vision_model``, ``vision_api_key``.
        Missing keys default to ``""``.
    """
    result = {
        "text_provider": "",
        "text_endpoint": "",
        "text_model": "",
        "text_api_key": "",
        "vision_provider": "",
        "vision_endpoint": "",
        "vision_model": "",
        "vision_api_key": "",
    }

    try:
        values = dotenv_values(path)
    except Exception:
        logger.debug("Could not read env file %s, returning defaults", path)
        return result

    for result_key, env_key in _TEXT_VARS.items():
        result[result_key] = values.get(env_key, "")

    for result_key, env_key in _VISION_VARS.items():
        result[result_key] = values.get(env_key, "")

    logger.debug(
        "Read env from %s — text_provider=%s vision_provider=%s",
        path,
        result["text_provider"] or "(none)",
        result["vision_provider"] or "(none)",
    )
    return result


def write_env(path: str, data: dict) -> bool:
    """Write Demiurgos LLM env vars back to *.path*, **preserving** all
    comments, blank lines, and non-Demiurgos variables.

    Steps
    -----
    1. Copy ``.env`` → ``.env.backup`` (if source exists).
    2. Read original lines to keep comments and unrelated vars.
    3. Build new content, replace/add the eight ``DEMIURGOS_*`` vars.
    4. Write atomically: ``.env.tmp`` → ``fsync`` → ``os.replace``.

    Returns ``True`` on success, ``False`` on any I/O error.
    """
    logger.info("Writing env to %s", path)

    # --- backup ---
    if os.path.exists(path):
        backup_path = path + ".backup"
        try:
            shutil.copy2(path, backup_path)
            logger.debug("Backup created: %s", backup_path)
        except OSError as exc:
            logger.warning("Could not create backup: %s", exc)

    # --- read original lines (to preserve comments / unrelated vars) ---
    original_lines: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            original_lines = fh.readlines()
    except FileNotFoundError:
        logger.debug("No existing .env — will create from scratch")
    except OSError as exc:
        logger.error("Cannot read %s: %s", path, exc)
        return False

    # --- mapping: result key → env var name → value ---
    new_values: dict[str, str] = {}
    for result_key, env_key in _TEXT_VARS.items():
        val = data.get(result_key, "")
        if val:
            new_values[env_key] = val
    for result_key, env_key in _VISION_VARS.items():
        val = data.get(result_key, "")
        if val:
            new_values[env_key] = val

    written_env_keys: set[str] = set()
    new_lines: list[str] = []

    for line in original_lines:
        stripped = line.strip()
        # Keep comments and blank lines verbatim
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue

        # Parse KEY=VALUE lines
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in _ALL_DEMIURGOS_VARS and key in new_values:
                # Replace with the new value (only if we have one)
                new_lines.append(f"{key}={new_values[key]}\n")
                written_env_keys.add(key)
            elif key in _ALL_DEMIURGOS_VARS:
                # Demiurgos var we no longer want — remove the line
                logger.debug("Removing env var %s (no value provided)", key)
                continue
            else:
                # Unrelated var — keep as-is
                new_lines.append(line)
        else:
            new_lines.append(line)

    # --- Append any new DEMIURGOS_ vars that didn't exist in the file ---
    pending = [
        (k, v) for k, v in new_values.items() if k not in written_env_keys
    ]
    if pending:
        new_lines.append(
            "\n# --------------------------------------------------------------------\n"
        )
        new_lines.append(
            "# Demiurgos LLM Configuration (managed by web-config-ui)\n"
        )
        new_lines.append(
            "# --------------------------------------------------------------------\n"
        )
        for key, value in pending:
            new_lines.append(f"{key}={value}\n")

    # --- atomic write ---
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.writelines(new_lines)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        logger.info("Env written successfully to %s", path)
        return True
    except OSError as exc:
        logger.error("Failed to write env: %s", exc)
        # Clean up stale .tmp
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False


# ---------------------------------------------------------------------------
# default-config.json read / write
# ---------------------------------------------------------------------------


def read_json_config(path: str) -> dict:
    """Read a JSON config file.

    Returns an empty dict if the file does not exist or is unparseable.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        logger.debug("Config file not found: %s", path)
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not parse %s: %s", path, exc)
        return {}


def write_json_config(path: str, data: dict) -> bool:
    """Write *data* as a JSON config file.

    Creates parent directories if necessary.
    Returns ``True`` on success, ``False`` on error.
    """
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        logger.info("JSON config written to %s", path)
        return True
    except OSError as exc:
        logger.error("Failed to write JSON config %s: %s", path, exc)
        return False


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------

# Model IDs whose name contains any of these substrings are filtered out
_EXCLUDE_MODEL_KEYWORDS: list[str] = [
    "embedding",
    "tts",
    "whisper",
    "moderation",
    "dall-e",
    "dalle",
    "audio",
]


def test_connection(
    endpoint: str, api_key: str, timeout: int = 5
) -> tuple[Optional[list[str]], Optional[str], Optional[dict]]:
    """Test connectivity to a provider's models endpoint.

    Calls ``GET {endpoint}/models`` and returns a ``(model_list,
    error_code, error_params)`` tuple.

    Parameters
    ----------
    endpoint:
        Base URL of the provider (e.g. ``https://api.openai.com/v1``).
        Trailing slashes are stripped automatically.
    api_key:
        API key sent as ``Authorization: Bearer``.
    timeout:
        Request timeout in seconds (default 5).

    Returns
    -------
    tuple[list[str] | None, str | None, dict | None]
        - On success: ``(models, None, None)`` where *models* is the filtered
          list of model IDs.
        - On failure: ``(None, error_code, error_params)`` with a
          machine-readable error code and optional parameters for i18n.
    """
    url = endpoint.rstrip("/") + "/models"
    masked = mask_api_key(api_key)
    logger.info("Testing connection to %s with key %s", url, masked)

    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    except httpx.TimeoutException:
        logger.warning("Connection test timeout: %s", url)
        return (None, "timeout", {"seconds": timeout})
    except httpx.ConnectError:
        logger.warning("Connection test connect error: %s", url)
        return (None, "connect_error", {})
    except httpx.RequestError as exc:
        logger.warning("Connection test request error: %s", exc)
        return (None, "network_error", {"error": str(exc)})
    except Exception as exc:
        logger.error("Connection test unexpected error: %s", exc)
        return (None, "unexpected_error", {"error": str(exc)})

    # --- HTTP-level errors ---
    if response.status_code == 401:
        return (None, "auth_401", {})
    if response.status_code == 403:
        return (None, "auth_403", {})
    if response.status_code == 404:
        return (None, "endpoint_404", {})
    if response.status_code >= 400:
        return (None, "server_error", {"code": response.status_code})

    # --- parse body ---
    try:
        body = response.json()
    except Exception:
        return (None, "json_parse", {})

    # Different providers use different keys: "data" (OpenAI), "models" (Ollama)
    models_raw = body.get("data") or body.get("models") or []

    if not isinstance(models_raw, list):
        return (None, "unexpected_format", {})

    # --- filter ---
    filtered: list[str] = []
    for model in models_raw:
        if isinstance(model, dict):
            model_id = model.get("id", model.get("name", ""))
        else:
            model_id = str(model)

        if not model_id:
            continue

        model_lower = model_id.lower()
        if any(kw in model_lower for kw in _EXCLUDE_MODEL_KEYWORDS):
            continue

        filtered.append(model_id)

    if not filtered:
        return (None, "no_models", {})

    logger.info(
        "Connection test succeeded: %d models discovered",
        len(filtered),
    )
    return (filtered, None, None)
