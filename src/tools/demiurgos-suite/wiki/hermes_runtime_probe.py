"""Read-only Hermes gateway liveness probe.

Demiurgos never owns the Hermes process lifecycle: it does not start, stop,
reload or restart Hermes. This probe only reads ``gateway_state.json`` and the
OS process table to answer "is the gateway up?".

Liveness follows Hermes' own contract (``gateway/status.py``): a live PID, never
``updated_at`` — an idle gateway never advances that timestamp, so treating a
stale timestamp as "down" would report false negatives. Every failure path is
fail-closed: an unreadable, corrupt, or mismatched snapshot is "not running".
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

_GATEWAY_STATE_FILE = "gateway_state.json"
_RUNNING_STATE = "running"
_DOWN_STATES = frozenset({"stopped", "startup_failed"})

RecordReader = Callable[[Path], "dict[str, Any] | None"]
PidProbe = Callable[[int], bool]


def _read_record(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def _windows_pid_alive(pid: int) -> bool:
    """Process-existence check that never signals the target.

    ``os.kill(pid, 0)`` is unusable on Windows: CPython's Windows ``os.kill``
    terminates any process for a signal it does not special-case, so signal 0
    would kill the gateway. ``OpenProcess(SYNCHRONIZE)`` + ``WaitForSingleObject``
    only observes the process state.
    """
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x00000102
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def _pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class HermesGatewayProbe:
    """Answer "is the Hermes gateway running?" from read-only evidence."""

    def __init__(
        self,
        home: Path | None = None,
        *,
        record_reader: RecordReader | None = None,
        pid_probe: PidProbe | None = None,
    ) -> None:
        self._home = Path(home) if home is not None else None
        self._read_record = record_reader or _read_record
        self._pid_probe = pid_probe or _pid_alive

    def _resolved_home(self) -> Path | None:
        if self._home is not None:
            return self._home
        try:
            from assistant_settings import _resolve_profile_paths

            return _resolve_profile_paths().root
        except Exception:
            return None

    def is_running(self) -> bool:
        try:
            home = self._resolved_home()
            if home is None:
                return False
            record = self._read_record(home / _GATEWAY_STATE_FILE)
            if not isinstance(record, dict):
                return False
            state = record.get("gateway_state")
            if state is None or state in _DOWN_STATES or state != _RUNNING_STATE:
                return False
            recorded_home = record.get("hermes_home")
            if isinstance(recorded_home, str) and recorded_home.strip():
                if Path(recorded_home).expanduser().resolve() != home.resolve():
                    return False
            pid = record.get("pid")
            return isinstance(pid, int) and self._pid_probe(pid)
        except Exception:
            return False
