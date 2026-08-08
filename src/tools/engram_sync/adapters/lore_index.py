"""Lore index adapter: configured output index vs Engram lore topic; read-only."""

import json
import re
from dataclasses import replace
from pathlib import Path

from engram_sync.canonicalize import fingerprint
from engram_sync.compare import classify
from engram_sync.models import (Action, ApplyResult, NormalizedItem,
                                PersistenceBoundaryError, SourceState)

from ._common import BaseAdapter, load_json, ref

_STATS = re.compile(r"(\d+)\s+(entities|terms|contradictions)")


class LoreIndexAdapter(BaseAdapter):
    domain = "lore-index"

    def __init__(self, client, project, index_path, topic=None):
        super().__init__(client, project)
        self._path = Path(index_path)
        self._topic = topic or f"lore/{project}/index"

    def discover(self):
        local = None
        if self._path.is_file():
            data, state = load_json(self._path)
            if state is SourceState.UNREADABLE:
                local = ref(str(self._path), state=state)
            elif not isinstance(data, dict):
                local = ref(str(self._path), content={"raw": data}, state=SourceState.INVALID)
            else:
                local = ref(str(self._path), content=self._counts(data))
        remote = self._remote(self._topic, title=f"Lore Index \u2014 {self._project}")
        if remote is not None:
            counts, ok = self._counts_text(remote.content.get("text", ""))
            remote = replace(remote, content=counts, fingerprint=fingerprint(counts),
                             state=SourceState.PRESENT if ok else SourceState.INVALID)
        if local is None and remote is None:
            return []
        return [NormalizedItem(domain=self.domain, item_key=self._topic, local=local,
                               remote=remote, classification=classify(local, remote))]

    def apply(self, operation):
        item, source = self._current(operation)
        if operation.action is Action.KEEP_LOCAL:
            counts = source.content
            if not isinstance(counts, dict) or set(counts) != {"entities", "terms", "contradictions"}:
                raise PersistenceBoundaryError("lore index counts are not safely serializable")
            return self._save_remote(
                operation, topic=self._topic, title=f"Lore Index — {self._project}",
                content=json.dumps({"counts": counts}, sort_keys=True, ensure_ascii=False))
        raise PersistenceBoundaryError(
            "remote lore metadata contains counts only and cannot reconstruct the full index")

    def _counts(self, data):
        meta = data.get("meta", {})
        meta = meta if isinstance(meta, dict) else {}
        return {"entities": meta.get("entities_extracted", 0),
                "terms": len(data.get("terms", [])),
                "contradictions": len(data.get("contradictions", []))}

    def _counts_text(self, text):
        found = {m.group(2): int(m.group(1)) for m in _STATS.finditer(text)}
        counts = {"entities": found.get("entities", -1), "terms": found.get("terms", -1),
                  "contradictions": found.get("contradictions", -1)}
        return counts, -1 not in counts.values()
