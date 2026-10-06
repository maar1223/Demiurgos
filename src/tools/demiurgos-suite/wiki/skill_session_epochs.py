# -*- coding: utf-8 -*-
"""skill-materialization-sessions — (world, revision) epoch registry (D4 active).

The product binds its Hermes session identity to the pair ``(active world,
materialization revision)`` so a change in the materialized revision forces a
new session instead of reusing a live session whose system prompt is already
frozen (design D4). This module owns the deterministic key and a durable epoch
registry with lazy TTL pruning.

Etapa 1 wiring was **inert**: the registry was exercised at the materialization
seams (startup / world switch) purely to record the current ``(world,
revision)`` epoch and never fed the live run submission. Etapa 3 (WU-3.1)
**activates** it: the run path now keys the Hermes ``session_id`` through
``_channel_session_id`` (epoch-suffixed when the native channel is active), so
the recorded epoch is consumed for session invalidation (REQ-LP-6 / REQ-MM-2).
The durable-store schema and corrupt-store degradation are unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: Days a world's epoch survives after its last observation before a lazy prune.
SESSION_EPOCH_TTL_DAYS = 7

#: Durable store schema version (bumped only on an incompatible layout change).
SCHEMA_VERSION = 1

#: Relative path of the durable epoch store under the data root.
SESSION_STORE_REL = Path("data") / "methodology" / "materialization-sessions.json"

#: World separator hashed into the session key (never a valid world-name char).
_WORLD_SEPARATOR = "\x1f"


def resolve_session_store_path(project_root: Path) -> Path:
    """Resolve the durable epoch store under a checkout/data root."""
    return (Path(project_root).expanduser() / SESSION_STORE_REL).resolve()


def session_key_for(world: str, revision: str) -> str:
    """Deterministic epoch id for a ``(world, revision)`` pair.

    A change in either component yields a different key, so a new revision (or a
    new world) forces a new epoch instead of reusing a frozen session. The key
    is product-qualified so it can never collide with an external session id.
    """
    digest = hashlib.sha256(
        f"{world}{_WORLD_SEPARATOR}{revision}".encode("utf-8")
    ).hexdigest()
    return "demiurgos-" + digest[:32]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionEpochRegistry:
    """Durable ``world -> epoch`` map with lazy TTL pruning.

    The store is a JSON document ``{"schema_version": 1, "worlds": {...}}`` where
    each entry is ``{revision, epoch_id, created_at, last_seen_at}``. Writes are
    atomic (temp sibling + ``os.replace``), so a crash never leaves a partial
    JSON file. A missing or malformed store degrades to an empty registry;
    ``observe``/``prune`` never raise on a corrupt store.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """The store path this registry reads and writes."""
        return self._path

    # -- persistence --------------------------------------------------- #

    def _load(self) -> dict:
        """Load the store, degrading to an empty registry on any failure."""
        try:
            raw = self._path.read_bytes()
        except OSError:
            return {"schema_version": SCHEMA_VERSION, "worlds": {}}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {"schema_version": SCHEMA_VERSION, "worlds": {}}
        if not isinstance(data, dict):
            return {"schema_version": SCHEMA_VERSION, "worlds": {}}
        worlds = data.get("worlds")
        if not isinstance(worlds, dict):
            worlds = {}
        return {"schema_version": SCHEMA_VERSION, "worlds": worlds}

    def _save(self, data: dict) -> None:
        """Persist ``data`` atomically (temp sibling + ``os.replace``)."""
        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(
                    json.dumps(
                        data, sort_keys=True, ensure_ascii=False
                    ).encode("utf-8")
                )
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # -- TTL ----------------------------------------------------------- #

    @staticmethod
    def _parse_stamp(value) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _prune_worlds(
        self, worlds: dict, *, now: datetime, keep: str | None
    ) -> int:
        """Drop worlds whose ``last_seen_at`` predates the TTL, never ``keep``."""
        cutoff = now - timedelta(days=SESSION_EPOCH_TTL_DAYS)
        removed = 0
        for world in list(worlds):
            if world == keep:
                continue
            entry = worlds.get(world)
            seen = (
                self._parse_stamp(entry.get("last_seen_at"))
                if isinstance(entry, dict)
                else None
            )
            if seen is None or seen < cutoff:
                worlds.pop(world, None)
                removed += 1
        return removed

    # -- public API ---------------------------------------------------- #

    def observe(self, world: str, revision: str) -> str:
        """Record ``(world, revision)`` and return the epoch id bound to it.

        Reuses the stored epoch when the world's stored revision matches (only
        refreshing ``last_seen_at``); otherwise allocates and persists a fresh
        epoch keyed by the pair. Stale worlds are pruned lazily first — except
        the world being observed, which is always refreshed and never expires.
        """
        now = _utcnow()
        data = self._load()
        worlds = data["worlds"]
        self._prune_worlds(worlds, now=now, keep=world)
        stamp = now.isoformat()
        entry = worlds.get(world)
        if isinstance(entry, dict) and entry.get("revision") == revision:
            entry["last_seen_at"] = stamp
        else:
            worlds[world] = {
                "revision": revision,
                "epoch_id": session_key_for(world, revision),
                "created_at": stamp,
                "last_seen_at": stamp,
            }
        self._save(data)
        return worlds[world]["epoch_id"]

    def epoch_for(self, world: str) -> str | None:
        """Read the stored epoch id for ``world`` without mutating the store.

        The run-path lookup (D4, ``_channel_session_id``): returns the epoch id
        currently bound to the world, or ``None`` when there is no record or the
        store is missing/malformed (which degrades to an empty registry, so the
        caller falls back to the base session id). Never raises.
        """
        try:
            data = self._load()
            entry = data.get("worlds", {}).get(str(world))
        except Exception:  # noqa: BLE001 — a corrupt store is never fatal
            return None
        if not isinstance(entry, dict):
            return None
        epoch_id = entry.get("epoch_id")
        return epoch_id if isinstance(epoch_id, str) and epoch_id else None

    def prune(self, *, now: datetime | None = None) -> int:
        """Drop every world older than the TTL; return how many were removed.

        ``observe`` is what refreshes the active world, so a direct ``prune``
        treats every world uniformly. Callers that must preserve a world should
        ``observe`` it first.
        """
        moment = now or _utcnow()
        data = self._load()
        removed = self._prune_worlds(data["worlds"], now=moment, keep=None)
        if removed:
            self._save(data)
        return removed
