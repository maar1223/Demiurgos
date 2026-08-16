"""
Backup/mirror/restore adapters for the Demiurgos config wizard.

Google+rclone integration is OPTIONAL: an unavailable, missing, or
misbehaving rclone must never block the Core wizard. Every external process
invocation passes through four guarantees:

1. Argument allowlist — only known rclone commands and flags are forwarded.
2. Path validation — local paths must resolve inside the project root.
3. Bounded timeout — subprocesses never run unbounded.
4. Non-blocking status — unavailable/timeout/error return a ``BackupStatus``
   instead of raising, so the wizard stays usable.

The adapters are pure-stdlib so they are testable with a fake rclone binary.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------

ALLOWED_COMMANDS = frozenset({"sync", "copy", "lsf", "version"})

ALLOWED_FLAGS = frozenset(
    {
        "--transfers",
        "--checkers",
        "--timeout",
        "--contimeout",
        "--verbose",
        "--quiet",
        "--progress",
        "--stats",
        "--log-level",
        "--retries",
        "--fast-list",
        "--drive-chunk-size",
    }
)

# Safe values for ``--flag=value`` arguments (no shell metacharacters).
_SIMPLE_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:+-]{1,64}$")
# rclone remote refs look like ``remote:path``.
_REMOTE_REF_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*:[A-Za-z0-9_./-]*$")
_FLAG_VALUE_RE = re.compile(r"^--([A-Za-z0-9-]+)=(.*)$")


# ---------------------------------------------------------------------------
# Exceptions / status
# ---------------------------------------------------------------------------


class BackupError(Exception):
    """Base class for backup adapter errors."""


class DisallowedArgumentError(BackupError):
    """An argument was not on the allowlist (or was malformed)."""


class TraversalError(BackupError):
    """A path escaped the allowed project root."""


@dataclass(frozen=True)
class BackupStatus:
    """Non-blocking outcome of a backup/mirror/restore operation.

    ``state`` is one of: ``ok``, ``pending``, ``unavailable``, ``timeout``,
    ``error``, or ``conflict``. A status is always returned — the wizard never
    needs to catch an exception to stay usable.
    """

    state: str
    detail: str = ""
    workshop: str = ""

    @property
    def ok(self) -> bool:
        return self.state == "ok"


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


def validate_local_path(path: str, root: str | Path) -> Path:
    """Resolve *path* and assert it stays inside *root*.

    Raises :class:`TraversalError` on escape (``..``, absolute paths outside
    the root). Relative paths are resolved against *root*.
    """
    root_resolved = Path(root).resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root_resolved / candidate
    resolved = candidate.resolve()
    if not (resolved == root_resolved or root_resolved in resolved.parents):
        raise TraversalError(f"path escapes project root: {path}")
    return resolved


def build_rclone_argv(command: str, args: Iterable[str], root: str | Path | None) -> list[str]:
    """Build a safe rclone ``argv`` (without the binary).

    Each argument is classified:
    - an exact allowlisted flag (e.g. ``--verbose``),
    - an allowlisted ``--flag=value`` with a simple value,
    - a remote ref (``remote:path``, no traversal, no leading dash),
    - a local path validated inside *root*.

    Raises :class:`DisallowedArgumentError` or :class:`TraversalError`.
    """
    if command not in ALLOWED_COMMANDS:
        raise DisallowedArgumentError(f"command not allowlisted: {command}")

    argv: list[str] = [command]
    for arg in args:
        if arg in ALLOWED_FLAGS:
            argv.append(arg)
            continue

        match = _FLAG_VALUE_RE.match(arg)
        if match:
            flag = "--" + match.group(1)
            if flag not in ALLOWED_FLAGS:
                raise DisallowedArgumentError(arg)
            if not _SIMPLE_VALUE_RE.match(match.group(2)):
                raise DisallowedArgumentError(arg)
            argv.append(arg)
            continue

        if arg.startswith("-"):
            raise DisallowedArgumentError(arg)

        if ":" in arg:
            if not _REMOTE_REF_RE.match(arg) or ".." in arg:
                raise DisallowedArgumentError(arg)
            argv.append(arg)
            continue

        if root is None:
            raise DisallowedArgumentError(f"local path without a root: {arg}")
        argv.append(str(validate_local_path(arg, root)))

    return argv


# ---------------------------------------------------------------------------
# Rclone subprocess boundary
# ---------------------------------------------------------------------------


class RcloneRunner:
    """Invoke the ``rclone`` binary with allowlisted args and bounded timeout.

    Never raises for operational failures — it returns a ``BackupStatus``
    (``unavailable``, ``timeout``, or ``error``) so Core stays usable.
    """

    def __init__(
        self,
        binary: str = "rclone",
        timeout: float = 30.0,
        root: str | Path | None = None,
    ) -> None:
        self.binary = binary
        self.timeout = timeout
        self.root = root

    def available(self) -> bool:
        """True when the binary exists (either on PATH or at an absolute path)."""
        if shutil.which(self.binary):
            return True
        return Path(self.binary).exists()

    def run(self, command: str, args: Sequence[str], timeout: float | None = None) -> BackupStatus:
        """Run ``binary command args...`` and map the outcome to a status."""
        try:
            argv = build_rclone_argv(command, args, self.root)
        except BackupError as exc:
            return BackupStatus(state="error", detail=str(exc))

        full = [self.binary, *argv]
        effective_timeout = timeout if timeout is not None else self.timeout
        try:
            proc = subprocess.run(
                full,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
        except FileNotFoundError:
            return BackupStatus(
                state="unavailable",
                detail=f"rclone binary not found: {self.binary}",
            )
        except subprocess.TimeoutExpired:
            return BackupStatus(
                state="timeout",
                detail=f"rclone timed out after {effective_timeout}s",
            )
        except OSError as exc:
            return BackupStatus(state="unavailable", detail=str(exc))

        if proc.returncode != 0:
            return BackupStatus(
                state="error",
                detail=(proc.stderr or proc.stdout or "").strip()[:500],
            )
        return BackupStatus(state="ok")


# ---------------------------------------------------------------------------
# Restore adapter (atomic, explicit conflict/error)
# ---------------------------------------------------------------------------


def _trees_equal(a: Path, b: Path) -> bool:
    """Return True when both trees have the same relative file set + bytes."""
    a_files = {p.relative_to(a) for p in a.rglob("*") if p.is_file()}
    b_files = {p.relative_to(b) for p in b.rglob("*") if p.is_file()}
    if a_files != b_files:
        return False
    for rel in a_files:
        if (a / rel).read_bytes() != (b / rel).read_bytes():
            return False
    return True


class RestoreManager:
    """Restore a remote source into a local target atomically.

    The restore stages into a sibling ``.tmp`` directory and only swaps it
    into place on success. A target that already differs from the source is
    reported as ``conflict`` and left untouched — never silently overwritten.
    """

    def __init__(
        self,
        binary: str = "rclone",
        root: str | Path | None = None,
        remote: str | Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.runner = RcloneRunner(binary=binary, root=root, timeout=timeout)
        self.root = Path(root).resolve() if root is not None else None
        self.remote = remote

    def restore(self, source_relative: str, target: str | Path) -> BackupStatus:
        """Restore *source_relative* from the configured remote into *target*.

        *target* is validated against ``root`` when a root is configured.
        """
        target_path = Path(target)
        if self.root is not None:
            validate_local_path(str(target_path), self.root)

        staging = target_path.parent / f".{target_path.name}.tmp-restore-{uuid.uuid4().hex[:8]}"
        staging.mkdir(parents=True, exist_ok=True)

        remote_src = str(self.remote)
        if source_relative:
            remote_src = f"{remote_src}/{source_relative}"

        try:
            status = self.runner.run("copy", [remote_src, str(staging)])
        except BackupError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            return BackupStatus(state="error", detail=str(exc))

        if status.state != "ok":
            shutil.rmtree(staging, ignore_errors=True)
            return status

        # Conflict detection: an existing, non-empty target that differs from
        # the source is reported explicitly and never overwritten.
        if target_path.exists() and any(target_path.iterdir()):
            if not _trees_equal(staging, target_path):
                shutil.rmtree(staging, ignore_errors=True)
                return BackupStatus(
                    state="conflict",
                    detail="local changes differ from the remote source",
                )
            # Identical — nothing to do.
            shutil.rmtree(staging, ignore_errors=True)
            return BackupStatus(state="ok", detail="target already up to date")

        # Atomic swap: remove the (empty or missing) target, then rename.
        try:
            if target_path.exists():
                target_path.rmdir()
            os.replace(staging, target_path)
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            return BackupStatus(state="error", detail=str(exc))

        return BackupStatus(state="ok", detail="restore complete")


# ---------------------------------------------------------------------------
# Mirror adapter (per-workshop)
# ---------------------------------------------------------------------------

# Default per-workshop mirrors: local dir -> remote path under the remote base.
DEFAULT_WORKSHOPS: dict[str, dict[str, str]] = {
    "herramientas": {"local": "data/methodology", "remote": "taller-herramientas"},
    "mundo": {"local": "mundos", "remote": "taller-mundo"},
}

# Wizard-facing options: value -> (i18n key for the label, local dir hint).
WORKSHOP_OPTIONS: tuple[str, ...] = ("herramientas", "mundo")


def rclone_available() -> bool:
    """Non-blocking probe: is the rclone binary present and usable?

    The wizard treats Google+rclone as OPTIONAL: when this is False the
    backup surface reports ``pending``/``unavailable`` and Core stays usable.
    """
    return shutil.which("rclone") is not None


class MirrorManager:
    """Mirror each workshop directory separately to its own remote path."""

    def __init__(
        self,
        binary: str = "rclone",
        root: str | Path | None = None,
        remote_base: str = "gdrive:demiurgos",
        workshops: Optional[dict[str, dict[str, str]]] = None,
        timeout: float = 30.0,
    ) -> None:
        self.runner = RcloneRunner(binary=binary, root=root, timeout=timeout)
        self.root = root
        self.remote_base = remote_base.rstrip("/")
        self.workshops = workshops or DEFAULT_WORKSHOPS

    def mirror(self, workshop: str) -> BackupStatus:
        """Sync one workshop's local dir into its remote mirror path."""
        spec = self.workshops.get(workshop)
        if spec is None:
            return BackupStatus(state="error", detail=f"unknown workshop: {workshop}")
        local = spec["local"]
        remote_ref = f"{self.remote_base}/{spec['remote']}"
        try:
            argv = build_rclone_argv("sync", [local, remote_ref], self.root)
        except BackupError as exc:
            return BackupStatus(state="error", detail=str(exc), workshop=workshop)
        status = self.runner.run("sync", [local, remote_ref])
        return BackupStatus(
            state=status.state,
            detail=status.detail,
            workshop=workshop,
        )


# ---------------------------------------------------------------------------
# 30-second debounced post-edit sync
# ---------------------------------------------------------------------------


class SyncScheduler:
    """Debounce post-edit syncs into a single run, ``delay_seconds`` after
    the last ``notify_edit()``.

    Defaults to the wizard's 30-second post-edit window. A pending run can be
    cancelled with :meth:`stop` (e.g. on shutdown).
    """

    def __init__(self, callback: Callable[[], None], delay_seconds: float = 30.0) -> None:
        self._callback = callback
        self._delay = max(float(delay_seconds), 0.0)
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def notify_edit(self) -> None:
        """Reset the debounce window. The callback fires once, after the delay."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            self._timer = None
        try:
            self._callback()
        except Exception:  # noqa: BLE001 - never let a sync break the wizard
            logger.exception("post-edit sync callback failed")

    def stop(self) -> None:
        """Cancel any pending sync."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
