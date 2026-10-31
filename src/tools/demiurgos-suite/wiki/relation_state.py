"""World-local relations sweep state (P3).

Stored at ``<world>/.relations/state.json``, next to the P2 rejection memory:

* ``swept`` — path → body digest recorded when that ficha was last swept; a body
  edit changes the digest and makes the ficha reviewable again.
* ``muted`` — fichas the Author marked "leave as is".
* ``last_sweep_at`` — ISO timestamp of the last completed sweep, for the UI.

Fail-open by design: a missing, corrupt or unreadable store means "nothing swept,
nothing muted". Bookkeeping must never break a request.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

STORE_DIR = ".relations"
STATE_NAME = "state.json"
SCHEMA_VERSION = 1

# Serializes read-modify-write on the store inside this process.
_LOCK = threading.Lock()


@dataclass
class SweepState:
    """Swept digests, muted paths and the last sweep timestamp."""

    swept: dict[str, str] = field(default_factory=dict)
    muted: set[str] = field(default_factory=set)
    last_sweep_at: str = ""


def state_path(world_dir: Path) -> Path:
    return Path(world_dir) / STORE_DIR / STATE_NAME


def load_state(world_dir: Path) -> SweepState:
    path = state_path(world_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return SweepState()
    except OSError as exc:
        logger.warning("relations: cannot read sweep state at %s: %s", path, exc)
        return SweepState()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("relations: corrupt sweep state at %s; ignoring", path)
        return SweepState()
    if not isinstance(data, dict):
        return SweepState()
    swept_raw = data.get("swept")
    swept = {
        str(key): str(value)
        for key, value in (swept_raw.items() if isinstance(swept_raw, dict) else ())
        if isinstance(key, str) and isinstance(value, str)
    }
    muted_raw = data.get("muted")
    muted = {
        value for value in (muted_raw if isinstance(muted_raw, list) else ())
        if isinstance(value, str) and value
    }
    last = data.get("last_sweep_at")
    return SweepState(
        swept=swept,
        muted=muted,
        last_sweep_at=last if isinstance(last, str) else "",
    )


def save_state(world_dir: Path, state: SweepState) -> bool:
    """Persist the state. Returns True when the file changed."""
    try:
        _write(world_dir, state)
    except OSError as exc:
        logger.warning("relations: cannot persist sweep state for %s: %s", world_dir, exc)
        return False
    return True


def mute(world_dir: Path, path: str) -> bool:
    """Mark a ficha as "leave as is": never a candidate, never swept."""
    with _LOCK:
        state = load_state(world_dir)
        if path in state.muted:
            return False
        state.muted.add(path)
        return save_state(world_dir, state)


def unmute(world_dir: Path, path: str) -> bool:
    with _LOCK:
        state = load_state(world_dir)
        if path not in state.muted:
            return False
        state.muted.discard(path)
        return save_state(world_dir, state)


def mark_swept(world_dir: Path, path: str, digest: str, *, at: str = "") -> bool:
    """Record that this ficha was swept at the given body digest."""
    with _LOCK:
        state = load_state(world_dir)
        changed = state.swept.get(path) != digest
        state.swept[path] = digest
        if at:
            changed = changed or state.last_sweep_at != at
            state.last_sweep_at = at
        if not changed:
            return False
        return save_state(world_dir, state)


def _write(world_dir: Path, state: SweepState) -> None:
    path = state_path(world_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SCHEMA_VERSION,
        "swept": dict(sorted(state.swept.items())),
        "muted": sorted(state.muted),
        "last_sweep_at": state.last_sweep_at,
    }
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
