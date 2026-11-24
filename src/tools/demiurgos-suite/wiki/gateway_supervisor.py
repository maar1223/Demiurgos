# -*- coding: utf-8 -*-
"""Supervised Hermes gateway child.

The launcher spawns this module in place of ``hermes gateway run``. It owns
exactly one child (the gateway), restarts it with a bounded backoff when it
exits on its own, and records every transition in one small JSON status file
that the API reads (see :mod:`assistant_recovery`).

Deliberate limits:

- It restarts **only** the gateway child. The API and the user's in-flight work
  are never touched.
- It never retries a refusal a restart cannot fix: a broken profile is reported
  as ``config_invalid`` and a missing runtime as ``not_started``, then it stops.
- It never reads gateway log text. Provider refusals and timeouts are classified
  per turn by the assistant failure taxonomy, not here (D11).
- ``DEMIURGOS_GATEWAY_SUPERVISOR=0`` restores the plain "spawn once and let it
  exit" behaviour (the rollback switch).
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # imported as ``wiki.gateway_supervisor`` (package) …
    from .assistant_recovery import (
        STATUS_SCHEMA,
        supervisor_status_path,
        write_supervisor_status,
    )
except ImportError:  # … or as a top-level module (the launcher runs it with -m)
    from assistant_recovery import (  # type: ignore[no-redef]
        STATUS_SCHEMA,
        supervisor_status_path,
        write_supervisor_status,
    )

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF = (5.0, 15.0, 45.0)
DEFAULT_RESET_AFTER_SECONDS = 60.0
_KILL_SWITCH_VALUES = frozenset({"0", "false", "no", "off"})
_POLL_SECONDS = 0.2
#: Must stay BELOW the launcher's own stop window (``_kill_process`` waits ~6 s
#: before SIGKILL). A gateway that ignores SIGTERM would otherwise outlive the
#: supervisor: the launcher would kill the supervisor first and reparent the
#: child, leaving an orphan holding the port (live-verify B1).
_TERMINATE_GRACE_SECONDS = 3.0


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _float_sequence(raw: str, fallback: Sequence[float]) -> tuple[float, ...]:
    values: list[float] = []
    for chunk in str(raw).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = float(chunk)
        except ValueError:
            return tuple(fallback)
        values.append(max(0.0, value))
    return tuple(values) if values else tuple(fallback)


def _non_negative_int(raw: Any, fallback: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    return max(0, value)


def _non_negative_float(raw: Any, fallback: float) -> float:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    return max(0.0, value)


def supervisor_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Kill switch: ``DEMIURGOS_GATEWAY_SUPERVISOR`` off disables supervision."""
    env = os.environ if environ is None else environ
    value = str(env.get("DEMIURGOS_GATEWAY_SUPERVISOR", "")).strip().lower()
    return value not in _KILL_SWITCH_VALUES


def validate_runtime_config(hermes_home: Path | str | None) -> str | None:
    """Return ``config_invalid`` for an unparsable profile, else ``None``.

    A missing file is not invalid: a fresh profile is seeded by the provisioner
    and the runtime falls back to its defaults.
    """
    if hermes_home is None:
        return None
    root = str(hermes_home).strip()
    if not root:
        return None
    config = Path(root) / "config.yaml"
    if not config.is_file():
        return None
    try:
        import yaml

        parsed = yaml.safe_load(config.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — any read/parse failure is invalid config
        return "config_invalid"
    if parsed is not None and not isinstance(parsed, Mapping):
        return "config_invalid"
    return None


class GatewaySupervisor:
    """Bounded restart loop around one child process."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        child_cwd: Path | str | None,
        status_path: Path | str,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff: Sequence[float] = DEFAULT_BACKOFF,
        reset_after: float = DEFAULT_RESET_AFTER_SECONDS,
        spawn: Callable[[], Any] | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
        write_status: Callable[[Mapping[str, Any]], Path] | None = None,
        validate_config: Callable[[], str | None] | None = None,
        stop_event: threading.Event | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.command = list(command)
        self.child_cwd = Path(child_cwd) if child_cwd else None
        self.status_path = Path(status_path)
        self.max_attempts = max(0, int(max_attempts))
        self.backoff = tuple(float(value) for value in backoff) or (0.0,)
        self.reset_after = max(0.0, float(reset_after))
        self._spawn = spawn or self._spawn_child
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._write = write_status or self._write_snapshot
        self._validate = validate_config
        self._stop = stop_event or threading.Event()
        self._environ = dict(environ) if environ is not None else dict(os.environ)
        self._child: Any = None
        self._last_restart_at: str | None = None

    # -- public -----------------------------------------------------------
    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> int:
        if self._validate is not None:
            cause = self._validate()
            if cause:
                self._snapshot(state="failed", cause=cause, attempts=0, last_exit_code=None)
                return 2

        attempts = 0
        last_exit_code: int | None = None
        first = True
        while True:
            if self._stop.is_set():
                self._snapshot(
                    state="stopped", cause=None, attempts=attempts,
                    last_exit_code=last_exit_code,
                )
                return 0
            self._snapshot(
                state="starting" if first else "restarting",
                cause=None if first else "exited",
                attempts=attempts,
                last_exit_code=last_exit_code,
            )
            try:
                child = self._spawn()
            except OSError:
                self._snapshot(
                    state="failed", cause="not_started", attempts=attempts,
                    last_exit_code=None,
                )
                return 2
            first = False
            self._child = child
            self._snapshot(
                state="running", cause=None, attempts=attempts,
                last_exit_code=last_exit_code, gateway_pid=getattr(child, "pid", None),
            )
            exit_code, elapsed = self._wait_for_exit(child)
            self._child = None
            if exit_code is None:
                self._terminate(child)
                self._snapshot(
                    state="stopped", cause=None, attempts=attempts, last_exit_code=None,
                )
                return 0
            if elapsed >= self.reset_after:
                attempts = 0
            if attempts >= self.max_attempts:
                self._snapshot(
                    state="failed", cause="exited", attempts=attempts,
                    last_exit_code=exit_code,
                )
                return 1
            delay = self.backoff[min(attempts, len(self.backoff) - 1)]
            attempts += 1
            last_exit_code = exit_code
            self._last_restart_at = _iso_now()
            self._snapshot(
                state="restarting", cause="exited", attempts=attempts,
                last_exit_code=exit_code,
            )
            if self._sleep_interruptible(delay):
                self._snapshot(
                    state="stopped", cause=None, attempts=attempts,
                    last_exit_code=exit_code,
                )
                return 0

    # -- internals --------------------------------------------------------
    def _spawn_child(self) -> Any:
        return subprocess.Popen(
            self.command,
            cwd=str(self.child_cwd) if self.child_cwd is not None else None,
            env=self._environ,
            close_fds=os.name != "nt",
        )

    def _wait_for_exit(self, child: Any) -> tuple[int | None, float]:
        started = self._clock()
        while True:
            if self._stop.is_set():
                return None, self._clock() - started
            try:
                code = child.wait(timeout=_POLL_SECONDS)
            except subprocess.TimeoutExpired:
                continue
            return code, self._clock() - started

    def _sleep_interruptible(self, seconds: float) -> bool:
        if self._sleep is time.sleep:
            return self._stop.wait(max(0.0, seconds))
        self._sleep(seconds)
        return self._stop.is_set()

    def _terminate(self, child: Any) -> None:
        try:
            child.terminate()
        except Exception:  # noqa: BLE001 — best effort
            pass
        try:
            child.wait(timeout=_TERMINATE_GRACE_SECONDS)
            return
        except Exception:  # noqa: BLE001
            pass
        try:
            child.kill()
        except Exception:  # noqa: BLE001
            pass

    def _write_snapshot(self, payload: Mapping[str, Any]) -> Path:
        return write_supervisor_status(payload, self.status_path)

    def _snapshot(
        self,
        *,
        state: str,
        cause: str | None,
        attempts: int,
        last_exit_code: int | None,
        gateway_pid: int | None = None,
    ) -> None:
        self._write(
            {
                "schema": STATUS_SCHEMA,
                "state": state,
                "cause": cause,
                "attempts": attempts,
                "max_attempts": self.max_attempts,
                "last_exit_code": last_exit_code,
                "last_restart_at": self._last_restart_at,
                "updated_at": _iso_now(),
                "supervisor_pid": os.getpid(),
                "gateway_pid": gateway_pid,
            }
        )


def _run_once(command: Sequence[str], child_cwd: Path | None, environ: Mapping[str, str]) -> int:
    try:
        child = subprocess.Popen(
            list(command),
            cwd=str(child_cwd) if child_cwd is not None else None,
            env=dict(environ),
            close_fds=os.name != "nt",
        )
    except OSError:
        return 2
    return child.wait()


def _install_signal_handlers(supervisor: GatewaySupervisor) -> None:
    for name in ("SIGTERM", "SIGINT"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            signal.signal(signum, lambda *_: supervisor.request_stop())
        except (ValueError, OSError):  # pragma: no cover - non-main thread
            pass


def _parse_arguments(
    argv: Sequence[str], environ: Mapping[str, str]
) -> tuple[argparse.Namespace, list[str]]:
    argv = list(argv)
    if "--" in argv:
        split = argv.index("--")
        head, command = argv[:split], argv[split + 1 :]
    else:
        head, command = argv, []
    parser = argparse.ArgumentParser(prog="gateway_supervisor")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--child-cwd", default=None)
    parser.add_argument("--hermes-home", default=None)
    parser.add_argument("--max-attempts", default=None)
    parser.add_argument("--backoff", default=None)
    parser.add_argument("--reset-after", default=None)
    args = parser.parse_args(head)
    if not command:
        parser.error("a child command is required after --")
    args.command = command
    return args, command


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    env = dict(os.environ if environ is None else environ)
    args, _command = _parse_arguments(sys.argv[1:] if argv is None else argv, env)
    child_cwd = Path(args.child_cwd) if args.child_cwd else None

    if not supervisor_enabled(env):
        return _run_once(args.command, child_cwd, env)

    state_dir = Path(args.state_dir)
    status_path = state_dir / supervisor_status_path(env).name
    hermes_home = args.hermes_home if args.hermes_home is not None else env.get("HERMES_HOME", "")

    supervisor = GatewaySupervisor(
        command=args.command,
        child_cwd=child_cwd,
        status_path=status_path,
        max_attempts=_non_negative_int(
            args.max_attempts if args.max_attempts is not None else env.get("DEMIURGOS_GATEWAY_MAX_ATTEMPTS"),
            DEFAULT_MAX_ATTEMPTS,
        ),
        backoff=_float_sequence(
            args.backoff if args.backoff is not None else env.get("DEMIURGOS_GATEWAY_BACKOFF", ""),
            DEFAULT_BACKOFF,
        ),
        reset_after=_non_negative_float(
            args.reset_after if args.reset_after is not None else env.get("DEMIURGOS_GATEWAY_RESET_AFTER_SECONDS"),
            DEFAULT_RESET_AFTER_SECONDS,
        ),
        validate_config=lambda: validate_runtime_config(hermes_home),
        environ=env,
    )
    _install_signal_handlers(supervisor)
    return supervisor.run()


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
