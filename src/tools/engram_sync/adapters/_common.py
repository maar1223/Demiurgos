"""Shared discovery and fail-closed persistence helpers for Phase-1 adapters."""

import json
import os
from typing import Any

from engram_sync.canonicalize import fingerprint
from engram_sync.models import (Action, ApplyResult, AuthorizedOperation, Preview,
                                SourceRef, SourceState)
from engram_sync.engram_client import EngramError


def load_json(path) -> tuple[Any, SourceState]:
    """Read one JSON file; never writes. UNREADABLE on any failure."""
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh), SourceState.PRESENT
    except (OSError, ValueError):
        return None, SourceState.UNREADABLE


def ref(location, *, identity=None, metadata=None, content=None, state=SourceState.PRESENT):
    """Build a comparable source and a revision covering every persisted field."""
    canon = {"identity": identity or {}, "metadata": metadata or {}, "content": content or {}}
    fp = fingerprint(content or {}) if state is SourceState.PRESENT else ""
    revision = fingerprint(canon) if state is SourceState.PRESENT else ""
    return SourceRef(location=location, revision=revision, identity=canon["identity"],
                     metadata=canon["metadata"], content=canon["content"],
                     fingerprint=fp, state=state)


class BaseAdapter:
    """Read-only base; remote reads cross the client search boundary."""

    domain = ""

    def __init__(self, client: Any, project: str) -> None:
        self._client, self._project = client, project

    def _remote(self, topic: str, title: str = "") -> SourceRef | None:
        rows = self._client.search(self._project, title or topic, limit=COMPLETE_DISCOVERY_LIMIT)
        hits = [r for r in rows if isinstance(r, dict)
                and (r.get("topic") == topic or r.get("title") == title)]
        if not hits:
            return None
        row = min(hits, key=lambda r: str(r.get("id", "")))
        text = str(row.get("content", ""))
        return ref(f"engram:{row.get('id', '?')}", content={"text": text},
                   metadata={"topic": row.get("topic") or topic, "id": row.get("id"),
                             "title": row.get("title") or title},
                   state=SourceState.UNREADABLE if not text else SourceState.PRESENT)

    def preview(self, item, action) -> Preview:
        label = item.classification.label if item.classification else "Ready to review"
        return Preview(item_key=item.item_key, action=action, label=label,
                       detail=f"{item.domain}: {item.item_key}")

    def _current(self, operation: AuthorizedOperation):
        if operation.domain != self.domain:
            raise EngramError("operation domain does not match adapter")
        item = next((candidate for candidate in self.discover()
                     if candidate.item_key == operation.item_key), None)
        if item is None:
            raise EngramError("source item is no longer available")
        source = item.local if operation.action is Action.KEEP_LOCAL else item.remote
        if source is None or source.state is not SourceState.PRESENT:
            raise EngramError("authorized source is unavailable")
        if source.revision != operation.source_revision:
            raise EngramError("source changed since confirmation")
        return item, source

    def _save_remote(self, operation, *, topic: str, title: str, content: str) -> ApplyResult:
        if operation.action is not Action.KEEP_LOCAL:
            raise EngramError("remote persistence requires keep-local")
        self._client.save(operation, project=self._project, topic=topic,
                          title=title, content=content)
        return ApplyResult(operation.item_key, "saved", "saved copy updated")


COMPLETE_DISCOVERY_LIMIT = 1_000


def atomic_write(path, content: str) -> None:
    """Replace one local source atomically; callers must validate before calling."""
    path = os.fspath(path)
    temporary = f"{path}.engram-sync.tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
