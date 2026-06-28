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
        "default_endpoint": "https://generativelanguage.googleapis.com/v1beta",
        "default_text_model": "gemini-2.5-flash",
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
) -> tuple[Optional[list[str]], Optional[str]]:
    """Test connectivity to a provider's models endpoint.

    Calls ``GET {endpoint}/models`` and returns a ``(model_list,
    error_message)`` tuple — exactly one of them will be ``None`` on a given
    call.

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
    tuple[list[str] | None, str | None]
        - On success: ``(models, None)`` where *models* is the filtered list
          of model IDs.
        - On failure: ``(None, error_message)`` with a human-readable
          description.
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
        msg = f"Timeout: el endpoint no respondió en {timeout}s"
        logger.warning("Connection test timeout: %s", url)
        return (None, msg)
    except httpx.ConnectError:
        msg = "Error de conexión: endpoint inalcanzable"
        logger.warning("Connection test connect error: %s", url)
        return (None, msg)
    except httpx.RequestError as exc:
        msg = f"Error de red: {exc}"
        logger.warning("Connection test request error: %s", exc)
        return (None, msg)
    except Exception as exc:
        msg = f"Error inesperado: {exc}"
        logger.error("Connection test unexpected error: %s", exc)
        return (None, msg)

    # --- HTTP-level errors ---
    if response.status_code == 401:
        return (None, "Error de autenticación: API key inválida (401)")
    if response.status_code == 403:
        return (
            None,
            "Acceso denegado: verifica los permisos de la API key (403)",
        )
    if response.status_code == 404:
        return (
            None,
            "Endpoint /models no encontrado (404). ¿La URL base es correcta?",
        )
    if response.status_code >= 400:
        return (
            None,
            f"Error del servidor: HTTP {response.status_code}",
        )

    # --- parse body ---
    try:
        body = response.json()
    except Exception as exc:
        return (None, f"No se pudo parsear la respuesta JSON: {exc}")

    # Different providers use different keys: "data" (OpenAI), "models" (Ollama)
    models_raw = body.get("data") or body.get("models") or []

    if not isinstance(models_raw, list):
        return (None, "Formato de respuesta inesperado (no es una lista de modelos)")

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
        return (None, "No se encontraron modelos de texto/imagen compatibles")

    logger.info(
        "Connection test succeeded: %d models discovered",
        len(filtered),
    )
    return (filtered, None)
