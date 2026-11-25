# -*- coding: utf-8 -*-
"""Assistant recovery read model: gateway supervisor status and its UI view.

The launcher owns process lifecycle. It spawns a small supervisor
(:mod:`gateway_supervisor`) in place of ``hermes gateway run``; that supervisor
writes one small JSON status file beside the launcher pid files. This module is
the single place that knows where that file lives, how to validate it, and how
to translate it into the closed cause vocabulary the UI may show.

Nothing here starts, stops or restarts anything, and nothing here reads gateway
log text: the UI must never receive raw provider or log output (S11c).
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: Schema marker written by the supervisor; a reader that sees another value
#: fails closed instead of guessing at a different shape.
STATUS_SCHEMA = "demiurgos.gateway-supervisor/v1"

#: Supervisor lifecycle states (closed set).
STATES = ("starting", "running", "restarting", "failed", "stopped")

#: Causes the supervisor can observe without reading log text (D11).
#: Provider refusals and timeouts stay in the per-turn failure taxonomy.
CAUSES = ("not_started", "exited", "config_invalid")

#: Mirrors ``STATE_DIR`` in ``scripts/start-demiurgos.sh``.
LAUNCHER_STATE_DIRNAME = "demiurgos-launcher"
SUPERVISOR_STATUS_FILENAME = "gateway-supervisor.json"

_NON_RESTARTABLE_CAUSES = frozenset({"not_started", "config_invalid"})


def _value(environ: Mapping[str, str], name: str) -> str:
    """Mirror shell ``${NAME:-fallback}``: empty values count as unset."""
    raw = environ.get(name)
    if raw is None:
        return ""
    return str(raw).strip()


def launcher_state_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the launcher's per-user state dir exactly like the shell chain.

    Shell: ``RUNTIME_BASE="${XDG_RUNTIME_DIR:-${TMPDIR:-${XDG_CACHE_HOME:-$HOME/.cache}/demiurgos/runtime}}"``
    then ``STATE_DIR="$RUNTIME_BASE/demiurgos-launcher"``.
    """
    env = os.environ if environ is None else environ
    runtime_dir = _value(env, "XDG_RUNTIME_DIR")
    if runtime_dir:
        base = Path(runtime_dir)
    else:
        tmpdir = _value(env, "TMPDIR")
        if tmpdir:
            base = Path(tmpdir)
        else:
            cache = _value(env, "XDG_CACHE_HOME")
            home = _value(env, "HOME") or str(Path.home())
            base = Path(cache) if cache else Path(home) / ".cache"
            base = base / "demiurgos" / "runtime"
    return base / LAUNCHER_STATE_DIRNAME


def supervisor_status_path(environ: Mapping[str, str] | None = None) -> Path:
    return launcher_state_dir(environ) / SUPERVISOR_STATUS_FILENAME


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def normalize_status(payload: Any) -> dict[str, Any] | None:
    """Validate a status snapshot; return the normalized dict or ``None``.

    Unknown schema, state or cause, or a malformed attempt counter, fails
    closed: a corrupt snapshot is "no status", never a guessed cause.
    """
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schema") != STATUS_SCHEMA:
        return None
    state = payload.get("state")
    if state not in STATES:
        return None
    cause = payload.get("cause")
    if cause is not None and cause not in CAUSES:
        return None
    attempts = _int_or_none(payload.get("attempts"))
    if attempts is None:
        return None
    max_attempts = _int_or_none(payload.get("max_attempts"))
    if max_attempts is None:
        return None
    last_exit_code = payload.get("last_exit_code")
    if last_exit_code is not None and not isinstance(last_exit_code, int):
        return None
    return {
        "schema": STATUS_SCHEMA,
        "state": state,
        "cause": cause,
        "attempts": attempts,
        "max_attempts": max_attempts,
        "last_exit_code": last_exit_code,
        "last_restart_at": _str_or_none(payload.get("last_restart_at")),
        "updated_at": _str_or_none(payload.get("updated_at")),
        "supervisor_pid": _int_or_none(payload.get("supervisor_pid")),
        "gateway_pid": _int_or_none(payload.get("gateway_pid")),
    }


def read_supervisor_status(
    path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Read and validate the supervisor status file; fail closed on any error."""
    target = Path(path) if path is not None else supervisor_status_path(environ)
    try:
        with target.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, UnicodeError):
        return None
    return normalize_status(data)


def write_supervisor_status(
    payload: Mapping[str, Any],
    path: Path | None = None,
) -> Path:
    """Atomically write a status snapshot (temp file in the same directory)."""
    target = Path(path) if path is not None else supervisor_status_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(dict(payload), stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def recovery_view(
    gateway_running: bool,
    status: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Translate liveness + supervisor status into the UI read model.

    The view carries only contract fields: no exit codes, no paths, no log
    text, no provider output. ``can_restart`` is False only for refusals a
    restart cannot fix.
    """
    running = bool(gateway_running)
    updated_at = status.get("updated_at") if isinstance(status, Mapping) else None
    if running:
        return {
            "gateway_running": True,
            "state": "running",
            "cause": None,
            "attempts": 0,
            "can_restart": False,
            "updated_at": updated_at if isinstance(updated_at, str) else None,
        }
    if not isinstance(status, Mapping):
        return {
            "gateway_running": False,
            "state": "stopped",
            "cause": "not_started",
            "attempts": 0,
            "can_restart": True,
            "updated_at": None,
        }

    state = status.get("state")
    cause = status.get("cause")
    if state in ("starting", "running"):
        # The file says it is up but the probe says down: it died before the
        # supervisor recorded the next transition.
        state = "running"
        cause = "exited"
    if cause is None:
        cause = "not_started" if state == "stopped" else "exited"

    restartable = not (state == "failed" and cause in _NON_RESTARTABLE_CAUSES)
    attempts = status.get("attempts")
    return {
        "gateway_running": False,
        "state": state if state in STATES else "stopped",
        "cause": cause if cause in CAUSES else "not_started",
        "attempts": attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0,
        "can_restart": restartable,
        "updated_at": updated_at if isinstance(updated_at, str) else None,
    }


__all__ = [
    "CAUSES",
    "LAUNCHER_STATE_DIRNAME",
    "STATES",
    "STATUS_SCHEMA",
    "SUPERVISOR_STATUS_FILENAME",
    "launcher_state_dir",
    "normalize_status",
    "read_supervisor_status",
    "recovery_view",
    "supervisor_status_path",
    "write_supervisor_status",
]
