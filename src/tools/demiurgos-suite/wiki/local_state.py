"""BOM-safe, atomic, versioned local state registry.

Single source of truth for onboarding + capability state on the local
installation. Runtime truth lives HERE; Engram is recovery/context only and
never governs readiness.

Contract (design ONB-1.3):
- ``LocalState.load()`` -> state dict or a safe default. BOM-prefixed input is
  tolerated (legacy files) and stripped; corrupt/version-mismatched files are
  quarantined (backed up) and replaced by a fresh default so the runtime never
  dies on state damage.
- ``compare_version(expected)`` -> bool. Callers that read-modify-write must
  pass the revision they based their edit on; a mismatch is a conflict.
- ``atomic_commit(next)`` -> new revision. Serializes to UTF-8 **without BOM**,
  writes a ``.tmp`` sibling, validates the temp JSON, then renames into place.
  A lock serializes concurrent commits.

The narrative orchestrator's arc state (``.demiurgos-estado.json``) is owned
by a different subsystem. This module NEVER reads or writes it; the constant
``ARC_STATE_FILENAME`` exists so tests/auditors can prove the two stay
independent.
"""

from __future__ import annotations

import codecs
import json
import logging
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger("demiurgos-local-state")

SCHEMA_VERSION = 1
STATE_ENCODING = "utf-8"
TMP_SUFFIX = ".tmp"

# The narrative orchestrator's arc-state file. The registry must NEVER touch it.
ARC_STATE_FILENAME = ".demiurgos-estado.json"

# Card states for the Configuration Center (OC12). English machine vocabulary,
# presented localized by the frontend.
CARD_STATES = ("pending", "configured", "requires_connection", "error")


class LocalStateCommitError(RuntimeError):
    """Raised when an atomic commit could not be validated or persisted."""


def default_state() -> dict[str, Any]:
    """Fresh, unconfigured state. Never fabricates completion."""
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "onboarding": {
            "completed": False,
            "current_step": "step0",
            "completed_steps": [],
        },
        "locale": None,
        "capabilities": {
            "identity": "pending",
            "assistant": "pending",
            "telegram": "pending",
            "backup": "pending",
            "world": "pending",
            "offline": "pending",
            "import": "pending",
            # Local account slot (auth-vault-credentials, R-AC-01): the single
            # per-instance account. ``password_hash`` is the Argon2id hash of
            # the optional password, or null for passwordless accounts;
            # ``words_hash`` is ALWAYS an Argon2id hash once the account exists
            # (the recovery words are the ownership + recovery key).
            "account": {
                "username": None,
                "password_hash": None,
                "words_hash": None,
            },
        },
    }


class LocalState:
    """Atomic, versioned registry backed by one JSON file.

    ``path`` is the sole storage target. The registry never falls back to
    writing anywhere else (no Engram, no ``.demiurgos-estado.json``).
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._current: dict[str, Any] = self.load()

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """BOM-safe load; absent/corrupt/mismatched files fail safe to default."""
        if not self.path.is_file():
            return default_state()
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            logger.warning("local state unreadable (%s); using safe default", exc)
            return default_state()
        if raw.startswith(codecs.BOM_UTF8):
            raw = raw[len(codecs.BOM_UTF8):]
        try:
            data = json.loads(raw.decode(STATE_ENCODING))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._quarantine(raw, "corrupt")
            return default_state()
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            self._quarantine(raw, "schema-mismatch")
            return default_state()
        revision = data.get("revision")
        if not isinstance(revision, int) or revision < 0:
            self._quarantine(raw, "bad-revision")
            return default_state()
        return data

    def snapshot(self) -> dict[str, Any]:
        """Deep copy of the current in-memory state (safe to mutate)."""
        return deepcopy(self._current)

    def compare_version(self, expected: int | None) -> bool:
        """True when *expected* matches the current committed revision.

        ``None`` means "caller has no revision" and is treated as a mismatch
        for any already-committed state so a stale blind write never wins.
        """
        if expected is None:
            return False
        return self._current.get("revision") == expected

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def atomic_commit(self, next_state: Mapping[str, Any]) -> int:
        """Serialize, validate, and atomically replace the state file.

        The caller passes the FULL next state (a mutated snapshot). Revision
        and schema are enforced here; the new revision is returned. Concurrent
        commits are serialized by the lock; each commit observes the latest
        revision as its base.
        """
        with self._lock:
            state = deepcopy(dict(next_state))
            state["schema_version"] = SCHEMA_VERSION
            state["revision"] = int(self._current.get("revision", 0)) + 1
            self._write_atomic(state)
            self._current = state
            return int(state["revision"])

    def _write_atomic(self, state: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LocalStateCommitError(f"cannot create state directory: {exc}") from exc
        payload = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
        tmp = self.path.with_name(self.path.name + TMP_SUFFIX)
        try:
            # UTF-8 text writes never emit a BOM; newline="\\n" keeps bytes stable.
            tmp.write_text(payload, encoding=STATE_ENCODING, newline="\n")
            parsed = json.loads(tmp.read_text(encoding=STATE_ENCODING))
            if not isinstance(parsed, dict):
                raise LocalStateCommitError("temp state did not validate as an object")
            os.replace(tmp, self.path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            tmp.unlink(missing_ok=True)
            raise LocalStateCommitError(f"atomic commit failed: {exc}") from exc

    def _quarantine(self, raw: bytes, reason: str) -> None:
        """Back up a damaged file so evidence is preserved, then move on."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.path.with_name(f"{self.path.name}.{reason}.{stamp}.bak")
        try:
            backup.write_bytes(raw)
            logger.warning("local state quarantined as %s (%s)", backup.name, reason)
        except OSError:
            logger.warning("could not quarantine corrupt local state (%s)", reason)