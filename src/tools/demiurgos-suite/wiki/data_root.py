# -*- coding: utf-8 -*-
"""Data-root resolver — one visible, user-chosen folder for author data.

Every module that derives an author-data path (``mundos``, ``ideas``,
``taller``, ``plantillas``, ``estado``, ``config``, ``data/world-trash``)
resolves it from here instead of from its own file location. The resolver has
exactly three steps, applied in this order:

1. ``DEMIURGOS_DATA_ROOT`` when it is set to a non-blank value. The value is
   returned as a normalized absolute path and the pointer is never rewritten.
2. The bootstrap pointer written by :func:`write_pointer` — a small JSON record
   in the OS config dir (``platformdirs.user_config_dir("demiurgos")`` when
   ``platformdirs`` is importable, otherwise the stdlib fallback
   ``$XDG_CONFIG_HOME``/``~/.config`` on POSIX or ``%APPDATA%`` on Windows)
   that holds the data-root path ONLY, never author data.
3. :class:`DataRootNotConfigured`.

``platformdirs`` is an optional dependency: the module soft-imports it and
records availability in :data:`_HAS_PLATFORMDIRS`. The pointer location is
preserved byte-for-byte when it is importable; the stdlib fallback activates
ONLY on absence, so a host that already resolves the pointer keeps it.

There is deliberately NO code-relative fallback and NO default root: a missing
configuration fails loudly instead of silently reading a path inside the code
checkout. Pointing the pointer at a folder moves no bytes — this change ships
no migration and no back-compat layer (pre-production).

**Pointer record** (``data-root.json``)::

    {"schema_version": 1, "data_root": "/abs/path", "updated_at": "2026-09-16T12:00:00Z"}

Writes are atomic: the record is staged as ``data-root.json.tmp-<uuid>`` in the
same directory and ``os.replace``d into place, so a reader always sees either
the previous or the new complete record. A corrupt, partial or unknown-version
pointer raises :class:`DataRootNotConfigured` naming the file and the reason —
the resolver never guesses and never falls back to code-relative.

**Migration contract for consumers (WU-2/WU-3)**: a module that today exposes a
module-level constant (e.g. ``world_recycle_bin.TRASH_ROOT``/``MUNDOS_DIR``)
must keep that constant monkeypatchable after migrating — resolve lazily and
rebind the module attribute, never resolve at import time. Those modules are
NOT migrated here; this module is additive and imported by nothing yet.

**Injection seams**: ``environ`` and ``config_dir`` are keyword arguments on
every public function, so tests are hermetic (``tmp_path`` plus a fake environ)
without touching the real process environment or the real user config dir.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

try:
    import platformdirs as _platformdirs
except ImportError:  # platformdirs is optional; the stdlib fallback below replaces it
    _platformdirs = None

#: Whether ``platformdirs`` is importable in this interpreter. When ``True``
#: the pointer location is preserved byte-for-byte; the stdlib fallback is
#: consulted ONLY when this is ``False``.
_HAS_PLATFORMDIRS = _platformdirs is not None


ENV_VAR = "DEMIURGOS_DATA_ROOT"
APP_NAME = "demiurgos"
POINTER_NAME = "data-root.json"
SCHEMA_VERSION = 1
_TMP_MARKER = ".tmp-"


class DataRootNotConfigured(RuntimeError):
    """No data root could be resolved.

    Raised when neither source is configured AND when a pointer exists but is
    unreadable, malformed or incomplete. In both cases the failure is explicit:
    no code-relative path is ever substituted.
    """


def _is_windows() -> bool:
    return os.name == "nt"


def _fallback_config_dir() -> Path:
    """Config dir used ONLY when ``platformdirs`` is unavailable.

    POSIX: ``$XDG_CONFIG_HOME`` when set and non-blank, else ``~/.config``.
    Windows: ``%APPDATA%`` when set and non-blank, else ``~/AppData/Roaming``.
    ``APP_NAME`` is always appended. This mirrors the platformdirs base only
    for the hosts that would otherwise raise ``ImportError``.
    """
    if _is_windows():
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = (
            Path(appdata).expanduser()
            if appdata
            else Path.home() / "AppData" / "Roaming"
        )
    else:
        xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
        base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / APP_NAME


def _config_dir(config_dir: Path | None) -> Path:
    if config_dir is not None:
        return Path(config_dir)
    if _HAS_PLATFORMDIRS:
        return Path(_platformdirs.user_config_dir(APP_NAME))
    return _fallback_config_dir()


def pointer_path(config_dir: Path | None = None) -> Path:
    """Absolute path of the bootstrap pointer record.

    ``config_dir`` defaults to ``platformdirs.user_config_dir("demiurgos")``.
    """
    return _config_dir(config_dir) / POINTER_NAME


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_pointer(config_dir: Path | None = None) -> Path | None:
    """Read the bootstrap pointer.

    Returns the recorded data root as a normalized absolute path, or ``None``
    when no pointer file exists. A pointer that exists but is unreadable,
    malformed, of an unsupported ``schema_version``, or missing a usable
    ``data_root`` raises :class:`DataRootNotConfigured` naming the file and the
    reason instead of guessing.
    """
    path = pointer_path(config_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DataRootNotConfigured(
            f"bootstrap pointer at {path} is not readable: {exc}"
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataRootNotConfigured(
            f"bootstrap pointer at {path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, Mapping):
        raise DataRootNotConfigured(
            f"bootstrap pointer at {path} is not a JSON object"
        )

    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise DataRootNotConfigured(
            f"bootstrap pointer at {path} has unsupported schema_version "
            f"{version!r} (expected {SCHEMA_VERSION})"
        )

    data_root = payload.get("data_root")
    if not isinstance(data_root, str) or not data_root.strip():
        raise DataRootNotConfigured(
            f"bootstrap pointer at {path} has no usable 'data_root' value"
        )

    return Path(data_root.strip()).expanduser().resolve()


def resolve_data_root(
    *,
    environ: Mapping[str, str] | None = None,
    config_dir: Path | None = None,
) -> Path:
    """Resolve the data root. See the module docstring for the exact order.

    ``environ`` defaults to ``os.environ``; ``config_dir`` defaults to the
    platformdirs config dir. Raises :class:`DataRootNotConfigured` when neither
    the env override nor the pointer yields a root.
    """
    env = os.environ if environ is None else environ

    override = (env.get(ENV_VAR) or "").strip()
    if override:
        return Path(override).expanduser().resolve()

    pointer = read_pointer(config_dir)
    if pointer is not None:
        return pointer

    raise DataRootNotConfigured(
        f"no data root configured: set {ENV_VAR} or write the bootstrap pointer "
        f"at {pointer_path(config_dir)}"
    )


def write_pointer(root: Path, *, config_dir: Path | None = None) -> None:
    """Atomically record ``root`` as the data root (pointer path ONLY).

    The record is staged as ``data-root.json.tmp-<uuid>`` in the pointer's
    directory and ``os.replace``d into place, so a reader always sees either the
    previous or the new complete record — never a partial one. The temp file is
    unlinked if the write or the replace fails. The config dir is created when
    missing. No author data is ever written here.
    """
    path = pointer_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "data_root": str(Path(root).expanduser().resolve()),
        "updated_at": _utc_now(),
    }
    tmp = path.with_name(f"{path.name}{_TMP_MARKER}{uuid.uuid4().hex}")
    try:
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
