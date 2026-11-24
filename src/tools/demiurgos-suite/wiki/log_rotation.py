# -*- coding: utf-8 -*-
"""Size-based rotation for the launcher's logs (Phase 1, S5).

Why this exists: the launcher opens ``<install_root>/logs/demiurgos-api.log``,
``demiurgos-gateway.log`` and ``launcher.log`` with ``>>`` and nothing bounds
them. After weeks of use the bug-report assembler finds a blob past its 64 KB
cap and drops the logs entirely, so the Owner's diagnostic goal (S5) fails
exactly when it matters. Rotation keeps a bounded, readable window on disk.

Deliberate limits:

- **Copy + truncate, never rename the live file.** The three logs are written by
  processes that hold an append handle on them (the shell redirection that runs
  uvicorn, the supervisor that respawns the gateway, the launcher's own
  ``log_event``). A rename would keep those handles writing into the archive and
  leave the live path empty until the next restart; truncating keeps the handle
  pointing at the live path. ``O_APPEND`` writers (all of them here) resume at
  file offset 0 after truncation, so no sparse hole appears. The archive inherits
  the live file's mode, so a hardened ``0600`` log never becomes world-readable.
  The copy and the truncation are not atomic: bytes appended inside that window
  are lost. That is accepted for logs (the window is microseconds and the check
  runs every few minutes), and it is the price of never touching a live handle.
- **Bounded archive count, not a byte ceiling.** At most ``keep`` archives per
  log, and a log is rotated only once it reaches ``max_bytes``, so the steady
  footprint is about ``(keep + 1) * max_bytes`` per file. It is a target, not a
  hard bound: a file that grows past the cap between two checks is archived
  whole, so what is guaranteed is the number of archives, never their size.
- **Archives are named ``<log>.N``** so the existing ``*.log`` glob in
  :mod:`bug_report` keeps reading exactly the live files and never counts the
  same bytes twice. Phase 1's tail assembly reads the archives explicitly.
- **Best effort.** Every filesystem error is swallowed: rotation is maintenance,
  it must never break boot, a request, or a report.
- The API owns the loop because it is the only long-running process of the
  stack; the launcher stays the owner of *where* the logs live (it exports
  ``DEMIURGOS_LOG_DIR``) and of *who writes* them.
"""

from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_KEEP = 3
DEFAULT_INTERVAL_SECONDS = 300.0

KILL_SWITCH_ENV = "DEMIURGOS_LOG_ROTATION"
MAX_BYTES_ENV = "DEMIURGOS_LOG_MAX_BYTES"
KEEP_ENV = "DEMIURGOS_LOG_KEEP"
INTERVAL_ENV = "DEMIURGOS_LOG_ROTATE_INTERVAL_SECONDS"
LOG_DIR_ENV = "DEMIURGOS_LOG_DIR"

_KILL_SWITCH_VALUES = frozenset({"0", "false", "no", "off"})
#: ``wiki`` -> ``demiurgos-suite`` -> ``tools`` -> ``src`` -> checkout root.
_DEV_WIKI_DEPTH = 4


def _checkout_root() -> Path:
    """The checkout that holds this module (a dev tree has no install root)."""
    return Path(__file__).resolve().parent.parents[_DEV_WIKI_DEPTH - 1]


@dataclass(frozen=True)
class RotationSettings:
    """Resolved tuning for one process (env is read once, at boot)."""

    enabled: bool
    max_bytes: int
    keep: int
    interval: float


def _clamped_int(raw: object, fallback: int, minimum: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    return value if value >= minimum else minimum


def _positive_float(raw: object, fallback: float) -> float:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def rotation_settings(environ: Mapping[str, str] | None = None) -> RotationSettings:
    """Resolve the kill switch, the size caps and the interval."""
    env = os.environ if environ is None else environ
    enabled = str(env.get(KILL_SWITCH_ENV, "")).strip().lower() not in _KILL_SWITCH_VALUES
    return RotationSettings(
        enabled=enabled,
        max_bytes=_clamped_int(env.get(MAX_BYTES_ENV), DEFAULT_MAX_BYTES, 1),
        # At least one archive: keep=0 would store nothing and make the setting
        # silently useless.
        keep=_clamped_int(env.get(KEEP_ENV), DEFAULT_KEEP, 1),
        interval=_positive_float(env.get(INTERVAL_ENV), DEFAULT_INTERVAL_SECONDS),
    )


def resolve_log_dir(
    *,
    install_root: Path | None = None,
    code_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Where the launcher writes its logs.

    Order: the launcher's own ``DEMIURGOS_LOG_DIR`` export (authoritative, one
    owner), then ``<install_root>/logs`` for an installed layout, then
    ``<code_root>/logs`` for a dev checkout (``code_root`` is the checkout root,
    i.e. the directory that holds ``src/``).
    """
    env = os.environ if environ is None else environ
    override = str(env.get(LOG_DIR_ENV, "")).strip()
    if override:
        return Path(override)
    if install_root is not None:
        return Path(install_root) / "logs"
    root = Path(code_root) if code_root is not None else _checkout_root()
    return root / "logs"


def rotate_if_needed(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    keep: int = DEFAULT_KEEP,
) -> list[str]:
    """Rotate ``path`` when it reached ``max_bytes``; return the archives touched.

    Returns an empty list when the file is missing, is not a regular file, is a
    symlink, or is still below the cap. Never raises: a filesystem error leaves
    the live log untouched.
    """
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            return []
        if path.stat().st_size < max_bytes:
            return []
        bound = max(1, keep)
        # Drop the oldest generation first, then shift every archive one slot
        # down. Only archives move: the live file keeps its path and its open
        # append handles.
        oldest = path.with_name(f"{path.name}.{bound}")
        if oldest.exists():
            oldest.unlink()
        for index in range(bound - 1, 0, -1):
            source = path.with_name(f"{path.name}.{index}")
            if source.exists():
                source.replace(path.with_name(f"{path.name}.{index + 1}"))
        first = path.with_name(f"{path.name}.1")
        shutil.copyfile(path, first)
        # The archive is as private as the live file was (a hardened 0600 log
        # must not become world-readable through rotation).
        try:
            shutil.copymode(path, first)
        except OSError:
            pass
        # Truncate instead of unlink so the running writers keep the live path.
        os.truncate(path, 0)
    except OSError:
        return []
    return [first.name]


def rotate_log_dir(
    log_dir: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    keep: int = DEFAULT_KEEP,
) -> dict[str, list[str]]:
    """Rotate every live ``*.log`` in ``log_dir``; keyed by the live file name.

    Archives end in ``.log.N`` and therefore never match ``*.log``, so this scan
    cannot rotate its own output.
    """
    log_dir = Path(log_dir)
    try:
        candidates = sorted(p for p in log_dir.glob("*.log") if not p.is_symlink())
    except OSError:
        return {}
    rotated: dict[str, list[str]] = {}
    for candidate in candidates:
        created = rotate_if_needed(candidate, max_bytes=max_bytes, keep=keep)
        if created:
            rotated[candidate.name] = created
    return rotated


def run_rotation_loop(
    log_dir: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    keep: int = DEFAULT_KEEP,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    stop_event: threading.Event | None = None,
) -> None:
    """Rotate once, then once per ``interval`` until ``stop_event`` is set."""
    stop = stop_event if stop_event is not None else threading.Event()
    while True:
        rotate_log_dir(log_dir, max_bytes=max_bytes, keep=keep)
        if stop.wait(interval):
            return


def start_rotation(
    *,
    install_root: Path | None = None,
    code_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    stop_event: threading.Event | None = None,
) -> threading.Thread | None:
    """Start the background rotation thread, or return None when it is off.

    None means "nothing to do": the kill switch is set, or there is no log
    directory yet (a fresh checkout that never ran the launcher).
    """
    settings = rotation_settings(environ)
    if not settings.enabled:
        return None
    log_dir = resolve_log_dir(install_root=install_root, code_root=code_root, environ=environ)
    try:
        if not log_dir.is_dir():
            return None
    except OSError:
        return None
    thread = threading.Thread(
        target=run_rotation_loop,
        name="log-rotation",
        daemon=True,
        kwargs={
            "log_dir": log_dir,
            "max_bytes": settings.max_bytes,
            "keep": settings.keep,
            "interval": settings.interval,
            "stop_event": stop_event,
        },
    )
    thread.start()
    return thread
