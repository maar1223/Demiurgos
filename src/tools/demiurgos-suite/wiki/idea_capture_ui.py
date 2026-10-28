# -*- coding: utf-8 -*-
"""Local-auth-protected idea-capture configuration endpoints.

Temporary MVP panel backend for Profile → Integraciones → Captura de ideas.
Single-user and local-only by design: every endpoint is gated by the same
local-dev session used for secure wiki editing (``_resolve_principal``) and
fails closed with 401 when no trusted principal is present.

What is persisted
-----------------
- ``config/idea-capture.yaml`` — the ingress policy (private chat ids,
  approved group senders, active world, media limits, raw retention).
  Empty allowlists stay empty: the runtime is fail-closed and rejects every
  update until an operator authorizes explicitly.
- ``.env`` — ``TELEGRAM_BOT_TOKEN`` only. The token is written server-side
  with a comment/unrelated-variable-preserving writer and is NEVER returned
  in API responses, logged, or sent to the DOM: endpoints expose only
  ``has_token``.

Deliberate non-goals (temporary panel): it does not start Telegram polling,
does not wire the real Engram publisher or voice/image enrichment providers.
Hermes is the production Telegram supervisor; the legacy ``serve`` command is
kept only as a migration fallback and is never started by this panel.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from data_root import resolve_data_root
from state_paths import resolve_state_dir

log = logging.getLogger("demiurgos-idea-capture")

# Data-root seam (WU-2). ``None`` means "resolve from the data root on use";
# tests keep monkeypatching ``REPO_ROOT`` directly, exactly as before.
REPO_ROOT: Path | None = None


def _repo_root() -> Path:
    """Resolve the data root lazily; never at import time (WU-2).

    An import-time resolution would raise ``DataRootNotConfigured`` during
    pytest collection, before the suite's hermetic root exists.
    """
    if REPO_ROOT is not None:
        return REPO_ROOT
    return resolve_data_root()

_ENV_TOKEN_NAME = "TELEGRAM_BOT_TOKEN"
_TOKEN_MAX_LENGTH = 200
_WORLD = re.compile(r"^[A-Za-z0-9_-]+$")
_ID = re.compile(r"^-?\d+$")
_LIMIT_DEFAULTS = {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                   "raw_retention_days": 30}
_LIMIT_KEYS = tuple(_LIMIT_DEFAULTS)


def _config_path() -> Path:
    return _repo_root() / "config" / "idea-capture.yaml"


def _env_path() -> Path:
    return _repo_root() / ".env"


def _mundos_root() -> Path:
    return _repo_root() / "mundos"


# ---------------------------------------------------------------------------
# Worlds (reuse the repo visibility rules: skip hidden, `_`-prefixed, Ideas)
# ---------------------------------------------------------------------------


def list_world_names() -> list[str]:
    """Available worlds for the active-world selector, sorted by name."""
    root = _mundos_root()
    if not root.is_dir():
        return []
    names = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        # Same visibility rules as api_server._list_worlds: hidden dirs,
        # `_`-prefixed dirs, and reserved names (Ideas, trash) are excluded.
        if entry.name.startswith((".", "_")) or entry.name in {"Ideas", "trash"}:
            continue
        names.append(entry.name)
    return names


# ---------------------------------------------------------------------------
# Config model — strict parse mirrors src/tools/idea_capture/config.py
# ---------------------------------------------------------------------------


def default_config() -> dict:
    return {
        "private_chat_ids": [],
        "approved_groups": {},
        "active_world": "",
        "limits": dict(_LIMIT_DEFAULTS),
    }


def _native_bindings(private: list[int], groups: dict[int, list[int]]) -> list[dict[str, str]]:
    """Build exact Hermes identities from the panel's explicit allowlists."""
    bindings = [
        {"platform": "telegram", "chat_id": str(chat), "user_id": str(chat),
         "profile": "default"}
        for chat in private
    ]
    bindings.extend(
        {"platform": "telegram", "chat_id": str(chat), "user_id": str(sender),
         "profile": "default"}
        for chat, senders in groups.items()
        for sender in senders
    )
    return bindings


def _as_id(value: Any, label: str) -> int:
    """Integer chat/sender id; accepts int or a digit-only string (bools and
    floats are rejected so a UI typo can never be silently truncated)."""
    if isinstance(value, bool):
        raise ValueError(f"{label} debe ser un entero")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _ID.fullmatch(value.strip()):
        return int(value.strip())
    raise ValueError(f"{label} debe ser un entero, se recibió {value!r}")


def _as_limit(value: Any, label: str) -> int:
    """Positive integer limit (>= 1)."""
    parsed = _as_id(value, label)
    if parsed < 1:
        raise ValueError(f"{label} debe ser un entero positivo")
    return parsed


def _parse_config_values(payload: dict) -> dict:
    """Validate and normalize a UI payload into the persisted config shape.

    Raises ValueError with a Spanish message on the first invalid field.
    Empty allowlists are preserved verbatim (fail-closed contract).
    """
    if not isinstance(payload, dict):
        raise ValueError("config requerido")

    private_raw = payload.get("private_chat_ids", [])
    if not isinstance(private_raw, list):
        raise ValueError("private_chat_ids debe ser una lista de enteros")
    private = [_as_id(item, "private_chat_ids") for item in private_raw]

    groups_raw = payload.get("approved_groups", {})
    if not isinstance(groups_raw, dict):
        raise ValueError("approved_groups debe ser un mapeo de chat_id -> [remitentes]")
    groups: dict[int, list[int]] = {}
    for chat, senders in groups_raw.items():
        chat_id = _as_id(chat, "approved_groups (chat_id)")
        if not isinstance(senders, list):
            raise ValueError(f"approved_groups.{chat_id} debe ser una lista de enteros")
        groups[chat_id] = [_as_id(item, f"approved_groups.{chat_id}") for item in senders]

    active_world = payload.get("active_world", "")
    if not isinstance(active_world, str):
        raise ValueError("active_world debe ser texto")
    active_world = active_world.strip()
    if active_world and not _WORLD.fullmatch(active_world):
        raise ValueError("active_world debe ser un nombre de mundo seguro "
                         "(solo letras, números, guiones y guiones bajos)")

    limits_raw = payload.get("limits") or {}
    if not isinstance(limits_raw, dict):
        raise ValueError("limits debe ser un mapeo")
    limits = {}
    for key in _LIMIT_KEYS:
        value = limits_raw.get(key, _LIMIT_DEFAULTS[key])
        limits[key] = _as_limit(value, f"limits.{key}")

    return {
        "private_chat_ids": private,
        "approved_groups": groups,
        "authorized_bindings": _native_bindings(private, groups),
        "active_world": active_world,
        "limits": limits,
    }


def _lenient_read(raw: dict) -> dict:
    """Best-effort display values for a malformed file (form keeps working
    while the validation errors are shown). Never used for persistence."""
    config = default_config()
    groups: dict[int, list[int]] = {}
    if isinstance(raw.get("private_chat_ids"), list):
        out = []
        for item in raw["private_chat_ids"]:
            if isinstance(item, bool):
                continue
            if isinstance(item, int):
                out.append(item)
            elif isinstance(item, str) and _ID.fullmatch(item.strip()):
                out.append(int(item.strip()))
        config["private_chat_ids"] = out
    if isinstance(raw.get("approved_groups"), dict):
        for chat, senders in raw["approved_groups"].items():
            if isinstance(chat, bool):
                continue
            if isinstance(chat, int):
                chat_id = chat
            elif isinstance(chat, str) and _ID.fullmatch(chat.strip()):
                chat_id = int(chat.strip())
            else:
                continue
            if isinstance(senders, list):
                ids = []
                for s in senders:
                    if isinstance(s, bool):
                        continue
                    if isinstance(s, int):
                        ids.append(s)
                    elif isinstance(s, str) and _ID.fullmatch(s.strip()):
                        ids.append(int(s.strip()))
                groups[chat_id] = ids
    config["approved_groups"] = groups
    config["authorized_bindings"] = _native_bindings(
        config["private_chat_ids"], groups,
    )
    if isinstance(raw.get("active_world"), str):
        config["active_world"] = raw["active_world"].strip()
    limits_raw = raw.get("limits") if isinstance(raw.get("limits"), dict) else {}
    for key in _LIMIT_KEYS:
        value = limits_raw.get(key, _LIMIT_DEFAULTS[key])
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 1:
            config["limits"][key] = value
        elif isinstance(value, str) and _ID.fullmatch(value.strip()):
            parsed = int(value.strip())
            if parsed >= 1:
                config["limits"][key] = parsed
    return config


def read_config() -> tuple[dict, list[str]]:
    """Read and validate the yaml on disk.

    Returns ``(config, errors)``. A missing file is a valid empty (fail
    closed) config with no errors; a malformed file yields best-effort
    display values plus the validation error list.
    """
    path = _config_path()
    if not path.is_file():
        return default_config(), []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return default_config(), [f"config/idea-capture.yaml no se pudo leer: {exc}"]
    if raw is None:
        return default_config(), []
    if not isinstance(raw, dict):
        return default_config(), ["config/idea-capture.yaml debe ser un mapeo"]
    try:
        return _parse_config_values(raw), []
    except ValueError as exc:
        return _lenient_read(raw), [str(exc)]


_CONFIG_HEADER = """\
# Native Hermes Telegram ingress policy. Groups are deny-by-default.
#
# FAIL-CLOSED: empty allowlists reject EVERY update. Authorize explicitly:
#
#   private_chat_ids: [123456789]            # owner chat ids
#   approved_groups:                          # group chat id -> approved senders
#     987654321: [123456789, 555000111]
#
# Loaded by src/tools/idea_capture/config.py (load_policy). Hermes consumes
# authorized_bindings after its own gateway authorization. The legacy `serve`
# entrypoint remains compatibility-only and is not the production supervisor.
"""


def _serialize_config(config: dict) -> str:
    """Deterministic yaml text with the original header preserved."""
    private = ", ".join(str(chat) for chat in config["private_chat_ids"])
    lines = [_CONFIG_HEADER.rstrip("\n"),
             f"private_chat_ids: [{private}]",
             "approved_groups:"]
    groups = config["approved_groups"]
    if not groups:
        lines.append("  {}")
    for chat_id, senders in groups.items():
        senders_text = ", ".join(str(s) for s in senders)
        lines.append(f"  {chat_id}: [{senders_text}]")
    lines.append("authorized_bindings:")
    for binding in config.get("authorized_bindings", []):
        lines.append(
            f"  - platform: {binding['platform']}\n"
            f"    chat_id: {binding['chat_id']}\n"
            f"    user_id: {binding['user_id']}\n"
            f"    profile: {binding['profile']}"
        )
    if config.get("active_world"):
        lines.append(f"active_world: {config['active_world']}")
    lines.append("limits:")
    for key in _LIMIT_KEYS:
        lines.append(f"  {key}: {config['limits'][key]}")
    return "\n".join(lines) + "\n"


def write_config(config: dict) -> None:
    """Persist *config* atomically (same-directory tmp + os.replace)."""
    text = _serialize_config(config)
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=500,
                            detail=f"No se pudo escribir la configuración: {exc}")


# ---------------------------------------------------------------------------
# .env — server-side secret storage (TELEGRAM_BOT_TOKEN)
# ---------------------------------------------------------------------------


def read_env_var(name: str) -> str:
    """Read *name* from the project .env (gitignored) — secrets never live
    in code and are never exposed by the API."""
    path = _env_path()
    if not path.is_file():
        return ""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def write_env_var(name: str, value: str) -> bool:
    """Set (or, when *value* is empty, remove) *name* in .env, preserving
    comments, blank lines, and every unrelated variable.

    Mirrors the preserving dotenv writer used by web-config-ui. Writes are
    atomic (tmp + os.replace) and a ``.env.backup`` copy is kept first.
    """
    path = _env_path()
    if path.is_file():
        try:
            shutil.copy2(path, _env_path().with_name(".env.backup"))
        except OSError as exc:
            log.warning("no se pudo crear .env.backup: %s", exc)
    elif not value:
        # Nothing to remove and no file to touch — no-op.
        return True

    original: list[str] = []
    try:
        original = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.error("no se pudo leer %s: %s", path, exc)
        return False

    new_lines: list[str] = []
    found = False
    for line in original:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key == name:
                found = True
                if value:
                    new_lines.append(f"{name}={value}\n")
                continue
        new_lines.append(line)

    if value and not found:
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("\n")
        new_lines.append(
            "# --------------------------------------------------------------------\n"
            "# Hermes idea capture (managed by the Profile panel)\n"
            "# --------------------------------------------------------------------\n"
        )
        new_lines.append(f"{name}={value}\n")

    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.writelines(new_lines)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        return True
    except OSError as exc:
        log.error("no se pudo escribir %s: %s", path, exc)
        tmp.unlink(missing_ok=True)
        return False


def validate_token(token: Any) -> str:
    """Normalize a bot token for storage; never echoes the value."""
    if not isinstance(token, str):
        raise ValueError("token debe ser texto")
    value = token.strip()
    if not value:
        raise ValueError("token requerido")
    if any(char.isspace() for char in value):
        raise ValueError("token no puede contener espacios")
    if len(value) > _TOKEN_MAX_LENGTH:
        raise ValueError(f"token demasiado largo (máximo {_TOKEN_MAX_LENGTH} caracteres)")
    return value


# ---------------------------------------------------------------------------
# "Detectar mi chat" — read-only Telegram chat discovery (fail-closed)
#
# Contract (see the panel UX task):
#   * The server-side token is used server-side only: it is never returned,
#     logged, or rendered. Candidates expose human-readable titles/types and
#     numeric ids that are INTERNAL selection values — the UI never asks the
#     user to type them.
#   * getUpdates is called with ``offset=-1`` so NO pending update is
#     acknowledged/consumed: discovery is a read-only snapshot that cannot
#     lose messages for the real poller.
#   * If the real serve owner holds the OwnershipLock (live pid), discovery
#     REFUSES (409) rather than becoming a second getUpdates consumer.
#   * Channels and other update kinds are never candidates; group/supergroup
#     chats are listed but authorization is explicit and fail-closed (see
#     POST /chats/authorize). Message content is never disclosed.
# ---------------------------------------------------------------------------

_OWNER_LOCK_NAME = "idea-capture.sqlite3.lock"
_DISCOVER_MAX_UPDATES = 100
_DISCOVER_MAX_CANDIDATES = 25
_TELEGRAM_API = "https://api.telegram.org"


class TelegramDiscoveryError(RuntimeError):
    """Error talking to the Telegram Bot API, mapped to an HTTP response.

    ``code`` is a stable, machine-readable remediation key the frontend uses
    to render specific guidance (webhook_conflict, conflicting_consumer,
    invalid_token, network, invalid_response, telegram_http, telegram_api).
    """

    def __init__(self, status_code: int, detail: str, code: str = ""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


def owner_lock_path() -> Path:
    """The exact lock file the serve entrypoint uses (runtime OwnershipLock).

    Beside the capture database in the state directory, so the web discovery
    path and the serve entrypoint observe the same owner lock.
    """
    return resolve_state_dir() / _OWNER_LOCK_NAME


def _default_pid_alive(pid: int) -> bool:
    """Stdlib-only liveness probe used when ``idea_capture.runtime`` is not
    importable from the wiki API server.

    ``default_pid_alive`` lives in the runtime package (``src/tools``), but
    the API server is launched with
    ``PYTHONPATH=src\\tools\\demiurgos-suite\\wiki;src\\tools\\demiurgos-suite``
    (see start-api.ps1 / start-demiurgos.ps1) — ``src\\tools`` is NOT on that
    path, so the lazy import inside ``owner_is_active`` raised
    ``ModuleNotFoundError`` and every authenticated discovery request ended
    in an empty-body 500. This probe mirrors ``runtime.default_pid_alive``
    semantics exactly (never uses ``os.kill`` on Windows: it terminates), so
    the owner-active guard keeps working in that environment.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            alive = bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)))
            return alive and exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def owner_is_active(lock_path: Path | None = None) -> bool:
    """True when the serve poller owns the bot (live pid in the lock file).

    Mirrors OwnershipLock.acquire semantics: a dead/stale pid means the owner
    is gone and discovery may proceed. A missing lock means no owner.

    The runtime probe is imported lazily (same pattern as the runtime's own
    lazy ``requests`` import) so importing this panel module never pulls the
    whole idea_capture runtime chain into the wiki API server. When the
    runtime is NOT importable at all (the wiki API server runs without
    ``src/tools`` on its PYTHONPATH), the stdlib-only ``_default_pid_alive``
    fallback keeps the exact same probe semantics.
    """
    try:
        from idea_capture.runtime import default_pid_alive
    except ImportError:
        log.warning("idea-capture: runtime probe not importable; using stdlib fallback")
        default_pid_alive = _default_pid_alive
    path = Path(lock_path) if lock_path is not None else owner_lock_path()
    if not path.is_file():
        return False
    try:
        pid = int((path.read_text(encoding="utf-8") or "0").strip() or "0")
    except (OSError, ValueError):
        return False
    return pid > 0 and default_pid_alive(pid)


def _person_display_name(sender: dict) -> str:
    """Human-readable name for a private-chat user; never the numeric id."""
    first = (sender.get("first_name") or "").strip()
    last = (sender.get("last_name") or "").strip()
    name = " ".join(part for part in (first, last) if part)
    if name:
        return name
    username = (sender.get("username") or "").strip()
    return f"@{username}" if username else ""


def candidate_from_update(update: dict) -> dict | None:
    """One candidate chat from a raw Bot API update, or None (not a chat
    message: channels, service updates, malformed payloads are excluded).

    Only message-bearing updates with an integer chat id qualify. No message
    content is carried over — never disclose what the user wrote.
    """
    if not isinstance(update, dict):
        return None
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    chat_type = chat.get("type")
    if not isinstance(chat_id, int):
        return None
    if chat_type == "private":
        return {"id": chat_id, "type": "private", "kind": "private",
                "title": _person_display_name(message.get("from") or {})}
    if chat_type in ("group", "supergroup"):
        title = (chat.get("title") or "").strip()
        return {"id": chat_id, "type": chat_type, "kind": "group", "title": title}
    return None


def normalize_candidates(updates: list[dict], limit: int = _DISCOVER_MAX_CANDIDATES) -> list[dict]:
    """Deduplicate raw updates by chat id (first occurrence wins) and cap the
    result so the response stays small and recent-first."""
    seen: set[int] = set()
    candidates: list[dict] = []
    for update in updates[:_DISCOVER_MAX_UPDATES]:
        if not isinstance(update, dict):
            continue
        candidate = candidate_from_update(update)
        if candidate is None or candidate["id"] in seen:
            continue
        seen.add(candidate["id"])
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def fetch_updates(token: str, api: str = _TELEGRAM_API) -> list[dict]:
    """Read-only getUpdates snapshot. ``offset=-1`` retrieves pending updates
    WITHOUT confirming any, so the real poller never loses a message.

    Every Telegram HTTP/API/network failure is mapped to a safe, actionable
    ``TelegramDiscoveryError`` (status + detail + machine-readable code) so the
    panel can render the right remediation. The webhook/getUpdates conflict is
    detected from Telegram's own 409 description and surfaced as
    ``webhook_conflict`` — the webhook is NEVER deleted automatically.
    """
    import requests
    try:
        resp = requests.get(f"{api}/bot{token}/getUpdates",
                            params={"offset": -1, "timeout": 0}, timeout=15)
    except requests.RequestException as exc:
        raise TelegramDiscoveryError(
            502,
            "No se pudo contactar la API de Telegram. Verificá la conexión e intentá de nuevo.",
            code="network") from exc

    # Defensive body parse: a non-JSON / non-dict body is a safe 502, never a 500.
    data = None
    try:
        data = resp.json()
    except ValueError:
        data = None
    description = str(data.get("description") or "") if isinstance(data, dict) else ""

    if resp.status_code == 401:
        raise TelegramDiscoveryError(
            400,
            "El token guardado no es válido o fue revocado. Guardá un token nuevo desde este panel.",
            code="invalid_token")
    if resp.status_code == 409:
        if "webhook" in description.lower():
            raise TelegramDiscoveryError(
                409,
                "El bot tiene un webhook activo: Telegram no permite usar getUpdates mientras "
                "haya un webhook configurado (por eso «Detectar mi chat» no puede ver los "
                "mensajes). Eliminá el webhook manualmente — con /deletewebhook en BotFather o "
                "llamando al método deleteWebhook de la Bot API — y volvé a intentar. Este panel "
                "nunca borra el webhook automáticamente.",
                code="webhook_conflict")
        raise TelegramDiscoveryError(
            409,
            "Otro proceso ya está consumiendo getUpdates del mismo bot. Detené el serve y reintentá.",
            code="conflicting_consumer")
    if resp.status_code >= 400:
        raise TelegramDiscoveryError(
            502, f"Telegram respondió con error HTTP {resp.status_code}.", code="telegram_http")
    if not isinstance(data, dict):
        raise TelegramDiscoveryError(
            502, "Telegram respondió con una respuesta inválida. Reintentá en unos segundos.",
            code="invalid_response")
    if not data.get("ok"):
        raise TelegramDiscoveryError(
            502, f"Telegram respondió con error: {description}", code="telegram_api")
    result = data.get("result")
    if not isinstance(result, list):
        raise TelegramDiscoveryError(
            502, "Telegram respondió con una respuesta inválida. Reintentá en unos segundos.",
            code="invalid_response")
    return result


def authorize_chat_into_config(config: dict, payload: dict) -> tuple[dict, str]:
    """Merge an explicit chat authorization into *config*; raises ValueError
    (Spanish) on the first invalid field. Private chats append to
    private_chat_ids; group/supergroup chats require an explicit sender list
    AND ``confirm_group`` (fail-closed: never silently authorize a group)."""
    chat_id = _as_id(payload.get("chat_id"), "chat_id")
    chat_type = payload.get("chat_type")
    if chat_type == "private":
        if chat_id in config["private_chat_ids"]:
            return config, "Ese chat privado ya estaba autorizado."
        config["private_chat_ids"] = [*config["private_chat_ids"], chat_id]
        return config, "Chat privado autorizado."
    if chat_type not in ("group", "supergroup"):
        raise ValueError("chat_type debe ser private, group o supergroup")
    if payload.get("confirm_group") is not True:
        raise ValueError("La autorización de grupos requiere confirmación explícita "
                         "(confirm_group=true): nunca se autoriza un grupo en silencio")
    senders_raw = payload.get("sender_ids")
    if not isinstance(senders_raw, list) or not senders_raw:
        raise ValueError("La autorización de grupos requiere al menos un remitente "
                         "autorizado (sender_ids)")
    senders = [_as_id(item, "sender_ids") for item in senders_raw]
    existing = config["approved_groups"].get(chat_id, [])
    merged = [*existing, *[sender for sender in senders if sender not in existing]]
    config["approved_groups"][chat_id] = merged
    return config, "Grupo autorizado con remitentes explícitos."


# ---------------------------------------------------------------------------
# Serve command / readiness
# ---------------------------------------------------------------------------

_LIMITATIONS = [
    "La captura va siempre al Taller de Ideas global (ideas/): el mundo se elige recién al materializar una idea desde el taller.",
    "Publicador real de Engram no conectado: las ideas se persisten en el store local (outbox) pero aún no se publican a Engram.",
    "Los proveedores de enriquecimiento de voz e imágenes no están conectados: solo se captura texto plano.",
    "Para probar de verdad hace falta un bot y un chat de staging — nunca credenciales de producción.",
    "Los límites de medios y la retención bruta se guardan en esta config, pero la validación de medios y la retención actuales usan valores fijos en el runtime.",
    "La captura de producción la supervisa Hermes y el plugin nativo es el único dueño de Telegram.",
    "El comando `python -m idea_capture serve` queda disponible solo para migración y compatibilidad; no lo uses como segundo consumidor.",
]


def build_serve_status(config: dict, has_token: bool) -> dict:
    """Native Hermes startup command for the current local runtime + readiness.

    Capture always goes to the global Taller de Ideas bank (no world chosen at
    capture), so a world is NOT required to start: the only fail-closed gates
    are the bot token and non-empty allowlists (an optional ``active_world``
    is still read backward-compatibly when present, but never blocks).
    """
    private = config["private_chat_ids"]
    groups = config["approved_groups"]
    blocked: list[str] = []
    if not has_token:
        blocked.append("No hay TELEGRAM_BOT_TOKEN configurado en .env")
    if not private and not groups:
        blocked.append("Las listas de autorización están vacías (fail-closed): se rechaza todo ingreso")
    if os.name == "nt":
        command = "powershell -ExecutionPolicy Bypass -File start-gateway.ps1"
    else:
        command = "./start-gateway.ps1"
    return {"command": command, "runnable": not blocked, "blocked_reasons": blocked}


# ---------------------------------------------------------------------------
# Pending review queue (R-7) — web list/confirm/discard for parked captures
#
# The web Taller reviews captures parked in AWAITING_CONFIRM (R-8). This
# server builds its OWN IdeaCaptureRuntime (design decision 5: config + store
# + worker pool) instead of sharing Hermes' gateway runtime: cross-process
# SQLite is safe (per-thread connections + busy_timeout), so confirming from
# the web never contends with the bot owner. The runtime is created lazily on
# first use and cached per state file — importing this module never pulls the
# idea_capture runtime chain (same lazy-import rule as ``owner_is_active``).
# ---------------------------------------------------------------------------

# Server-side replication of the bot adapter's gate (design decision 6; the
# canonical set lives in ``.hermes/plugins/demiurgos-idea-capture/
# capture_adapter.py`` and is not importable from this wiki server). A capture
# outside this set (PROCESSING/SAVED/CANCELLED/RETRYABLE/ERROR) is rejected
# with 409 — never trust the client, never re-queue a worker.
_CONFIRMABLE_STATES = frozenset({
    "RECEIVED",
    "RAW_PERSISTED",
    "AWAITING_WORLD",
    "AWAITING_CONFIRM",
})

_pending_runtimes: dict[str, Any] = {}
_pending_runtimes_lock = threading.Lock()


def _pending_state_path() -> Path:
    """SQLite state file shared with the Hermes idea-capture runtime."""
    return resolve_state_dir() / "idea-capture.sqlite3"


def _build_pending_runtime() -> Any:
    """Compose the web-confirm runtime over the CURRENT repo root.

    Fail-closed policy (empty allowlists reject every update), the shared
    state file (per-thread connections + 10s busy timeout make concurrent
    web/bot writers safe), and the global ideas bank as the SAVE_GLOBAL
    destination. ``IdeaCaptureRuntime`` is imported lazily so this module
    never hard-depends on the runtime chain at import time.
    """
    from idea_capture.config import load_active_world, load_policy
    from idea_capture.runtime import IdeaCaptureRuntime

    config = load_policy(_config_path())
    return IdeaCaptureRuntime(
        config=config,
        state_path=_pending_state_path(),
        mundos_root=_mundos_root(),
        active_world=load_active_world(_config_path()),
        global_ideas_root=_repo_root() / "ideas",
        busy_timeout_seconds=10.0,
    )


def _pending_runtime() -> Any:
    """One runtime per state file (reuse existing instances; never rebuild).

    Keyed by the resolved state path so tests that relocate ``REPO_ROOT`` get
    an isolated runtime per sandbox while production keeps a single instance.
    """
    path = str(_pending_state_path())
    with _pending_runtimes_lock:
        runtime = _pending_runtimes.get(path)
        if runtime is None:
            try:
                runtime = _build_pending_runtime()
            except ImportError:
                log.warning("idea-capture runtime not importable; pending endpoints unavailable")
                raise HTTPException(
                    status_code=503,
                    detail="El runtime de captura no está disponible en este servidor.",
                )
            _pending_runtimes[path] = runtime
        return runtime


# ---------------------------------------------------------------------------
# Router — every route requires a trusted local principal (fail closed)
# ---------------------------------------------------------------------------


def _discover_candidates() -> dict:
    """Run the read-only discovery snapshot (token, owner guard, Telegram).

    Raises ``TelegramDiscoveryError`` for every Telegram HTTP/API/network
    failure; the endpoint maps it. Any other exception is unexpected and is
    turned into a sanitized 500 by the endpoint's fail-safe handler.
    """
    token = read_env_var(_ENV_TOKEN_NAME)
    if not token:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "Todavía no hay token guardado. Guardá el token del bot, "
                          "enviale un mensaje a tu bot en Telegram y reintentá.",
                "code": "no_token",
            })
    if owner_is_active():
        return JSONResponse(
            status_code=409,
            content={
                "detail": "El serve de captura ya está activo y es el único consumidor "
                          "del bot. Detené el serve antes de usar «Detectar mi chat» "
                          "para no crear un segundo consumidor.",
                "code": "owner_active",
            })
    updates = fetch_updates(token)
    candidates = normalize_candidates(updates)
    if not candidates:
        return {
            "ok": True,
            "candidates": [],
            "message": "Todavía no hay mensajes de este bot. Enviá /start (o "
                       "cualquier mensaje) a tu bot en Telegram y volvé a "
                       "intentar.",
        }
    log.info("idea-capture: %d chat(s) candidato(s) detectados (contenido no expuesto)",
             len(candidates))
    return {"ok": True, "candidates": candidates, "message": ""}


class _UnwiredRegistry:
    """Read-only fallback registry so the router imports without a wired store.

    api_server always wires the real local registry; this only guarantees the
    module is importable standalone. Any evidence commit through it raises
    loudly rather than silently dropping evidence.
    """

    def snapshot(self) -> dict[str, Any]:
        return {}

    def atomic_commit(self, next_state: Mapping[str, Any]) -> int:
        raise RuntimeError("idea-capture router used without a wired registry")


def create_idea_capture_router(
    require_principal: Callable[[Request], Any],
    registry: Callable[[], Any] | None = None,
) -> APIRouter:
    """Build the /api/idea-capture router.

    ``require_principal`` must return a trusted principal for the request or
    None; None maps to 401. api_server passes ``_resolve_principal`` through
    a call-time lambda so tests can monkeypatch it.

    ``registry`` returns the authoritative local registry (``LocalState``-like
    with ``snapshot()`` and ``atomic_commit()``); it defaults to a read-only
    fallback so the router stays importable in isolation, and api_server wires
    the real registry.
    """
    router = APIRouter(prefix="/api/idea-capture", tags=["idea-capture"])

    def _registry() -> Any:
        if registry is None:
            return _UnwiredRegistry()
        return registry()

    def _guard(request: Request) -> None:
        if require_principal(request) is None:
            raise HTTPException(status_code=401, detail="Autenticación requerida")

    def _commit_evidence(next_state: Mapping[str, Any]) -> None:
        """Single evidence write path shared by the probe and token handlers."""
        _registry().atomic_commit(dict(next_state))

    @router.get("/status")
    def get_status(request: Request) -> dict:
        _guard(request)
        config, errors = read_config()
        has_token = bool(read_env_var(_ENV_TOKEN_NAME))
        return {
            "config": config,
            "has_token": has_token,
            "validation": {"ok": not errors, "errors": errors},
            "serve": build_serve_status(config, has_token),
            "worlds": list_world_names(),
            "limitations": _LIMITATIONS,
        }

    @router.put("/config")
    def put_config(request: Request, body: dict | None = None) -> dict:
        _guard(request)
        payload = (body if isinstance(body, dict) else {}).get("config")
        try:
            config = _parse_config_values(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        write_config(config)
        has_token = bool(read_env_var(_ENV_TOKEN_NAME))
        return {
            "config": config,
            "has_token": has_token,
            "validation": {"ok": True, "errors": []},
            "serve": build_serve_status(config, has_token),
            "worlds": list_world_names(),
            "limitations": _LIMITATIONS,
        }

    @router.post("/token")
    def set_token(request: Request, body: dict | None = None) -> dict:
        from telegram_settings import EVIDENCE_KEY

        _guard(request)
        raw = (body if isinstance(body, dict) else {}).get("token")
        try:
            value = validate_token(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not write_env_var(_ENV_TOKEN_NAME, value):
            raise HTTPException(status_code=500,
                                detail="No se pudo escribir .env (token no guardado)")
        log.info("idea-capture: TELEGRAM_BOT_TOKEN configurado (valor no expuesto)")
        # A freshly stored token is untested: commit fresh requires_connection
        # evidence so the card can never render green on save alone. The 400
        # and 500 paths above return before this commit, so a rejected or
        # failed write never mutates evidence.
        next_state = dict(_registry().snapshot())
        next_state[EVIDENCE_KEY] = {
            "state": "requires_connection",
            "tested_at": None,
            "error_code": "",
        }
        _commit_evidence(next_state)
        return {"state": "requires_connection", "has_token": True}

    @router.delete("/token")
    def clear_token(request: Request) -> dict:
        from telegram_settings import EVIDENCE_KEY

        _guard(request)
        write_env_var(_ENV_TOKEN_NAME, "")
        log.info("idea-capture: TELEGRAM_BOT_TOKEN eliminado (valor no expuesto)")
        # Clear evidence too: a stale configured entry must never survive a
        # delete (and a later re-save) once the token is gone.
        next_state = dict(_registry().snapshot())
        next_state.pop(EVIDENCE_KEY, None)
        _commit_evidence(next_state)
        return {"state": "pending", "has_token": False}

    @router.post("/test-connection")
    def test_connection_probe(request: Request) -> dict:
        """Probe the STORED token against Telegram; never accept one in body.

        Reads the token server-side; a missing token returns 409 with NO
        Telegram call and NO evidence write. Network/offline failures map to
        ``requires_connection`` (retryable); invalid-token or API failures map
        to ``error``; success maps to ``configured``. The committed evidence
        reuses the exact ``{state, tested_at, error_code}`` shape. Only the
        resulting state is logged — never the token.
        """
        from datetime import datetime, timezone

        from telegram_settings import EVIDENCE_KEY, test_connection

        _guard(request)
        token = read_env_var(_ENV_TOKEN_NAME)
        if not token:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "Todavía no hay token guardado. Guardá el token "
                              "del bot antes de probar la conexión.",
                    "code": "no_token",
                })
        result = test_connection(token)
        next_state = dict(_registry().snapshot())
        next_state[EVIDENCE_KEY] = {
            "state": result["state"],
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "error_code": result["error_code"],
        }
        _commit_evidence(next_state)
        log.info("idea-capture: prueba de conexión finalizada (estado=%s, "
                 "valor no expuesto)", result["state"])
        evidence = next_state[EVIDENCE_KEY]
        return {
            "state": result["state"],
            "has_token": True,
            "tested_at": evidence["tested_at"],
            "error_code": evidence["error_code"],
            "message": result["message"],
        }

    @router.post("/chats/discover")
    def discover_chats(request: Request) -> dict:
        """Read-only candidate snapshot for "Detectar mi chat".

        Requires the stored server-side token (never exposed), refuses while
        the real serve owner is active (409, no second consumer), and calls
        getUpdates with offset=-1 so no pending message is acknowledged.

        Telegram HTTP/API/network failures are mapped to safe, actionable
        errors: the response body carries a human ``detail`` plus a stable
        machine-readable ``code`` the frontend uses to render the right
        remediation (e.g. ``webhook_conflict`` when a stale webhook blocks
        getUpdates). The webhook is NEVER deleted automatically.

        Final fail-safe: any OTHER unexpected exception is also mapped to a
        sanitized 500 with code ``unexpected`` — never an empty body, never a
        traceback, never the token or message content. The auth guard runs
        BEFORE this handler so failures are never masked as 401/403.
        """
        _guard(request)
        try:
            return _discover_candidates()
        except TelegramDiscoveryError as exc:
            return JSONResponse(status_code=exc.status_code,
                                content={"detail": exc.detail, "code": exc.code})
        except Exception as exc:
            # Log ONLY the exception type: the message could embed the token
            # (e.g. a malformed request URL) and must never be logged.
            log.error("idea-capture: discovery failed unexpectedly (%s); "
                      "returning sanitized error", type(exc).__name__)
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "No se pudo detectar chats por un error inesperado. "
                              "Reintentá; si el problema persiste, revisá los "
                              "registros del servidor.",
                    "code": "unexpected",
                })

    @router.post("/chats/authorize")
    def authorize_chat(request: Request, body: dict | None = None) -> dict:
        """Authorize a discovered chat explicitly and fail-closed.

        Private chats append to private_chat_ids. Group/supergroup chats
        require an explicit sender list plus confirm_group=true — a group is
        never authorized silently. Persists through the same config writer as
        PUT /config and returns the refreshed panel status.
        """
        _guard(request)
        payload = body if isinstance(body, dict) else {}
        config, errors = read_config()
        if errors:
            raise HTTPException(
                status_code=400,
                detail="config/idea-capture.yaml no se pudo leer; corregilo antes "
                       "de autorizar un chat.")
        try:
            config, message = authorize_chat_into_config(config, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        write_config(config)
        has_token = bool(read_env_var(_ENV_TOKEN_NAME))
        return {
            "config": config,
            "has_token": has_token,
            "validation": {"ok": True, "errors": []},
            "serve": build_serve_status(config, has_token),
            "worlds": list_world_names(),
            "limitations": _LIMITATIONS,
            "message": message,
        }

    # -- Web review queue (R-7): captures parked in AWAITING_CONFIRM ---------

    @router.get("/pending")
    def get_pending(request: Request) -> dict:
        """List every capture parked in AWAITING_CONFIRM plus their count.

        S-7.1: the response carries all parked captures with ``count`` equal
        to the list length; the frontend counter and review panel consume it.
        """
        _guard(request)
        runtime = _pending_runtime()
        captures = runtime.store.pending_confirm()
        return {
            "captures": [
                {
                    "capture_id": record.capture_id,
                    "slug": record.slug,
                    "raw_text": record.raw_text,
                    "created_at": record.created_at,
                    "event_ts": record.event_ts,
                    "media_kind": record.media_kind.value,
                }
                for record in captures
            ],
            "count": len(captures),
        }

    @router.post("/pending/{capture_id}/confirm")
    def confirm_pending_capture(capture_id: str, request: Request) -> dict:
        """Confirm a parked capture as a global idea (SAVE_GLOBAL, S-7.2).

        The server replicates the bot adapter's ``_CONFIRMABLE_STATES`` gate:
        a capture already resolved is rejected with 409 so a stale/second
        confirm can never re-queue the worker (S-7.4). The client is never
        trusted.
        """
        from idea_capture.models import WorldAction

        _guard(request)
        runtime = _pending_runtime()
        try:
            record = runtime.store.get(capture_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Captura no encontrada")
        if record.state.value not in _CONFIRMABLE_STATES:
            raise HTTPException(status_code=409, detail="La captura ya fue resuelta")
        runtime.confirm(capture_id, WorldAction.SAVE_GLOBAL)
        return {"ok": True}

    @router.post("/pending/{capture_id}/discard")
    def discard_pending_capture(capture_id: str, request: Request) -> dict:
        """Discard a parked capture (CANCEL → CANCELLED, S-7.3). Same gate."""
        from idea_capture.models import WorldAction

        _guard(request)
        runtime = _pending_runtime()
        try:
            record = runtime.store.get(capture_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Captura no encontrada")
        if record.state.value not in _CONFIRMABLE_STATES:
            raise HTTPException(status_code=409, detail="La captura ya fue resuelta")
        runtime.confirm(capture_id, WorldAction.CANCEL)
        return {"ok": True}

    return router
