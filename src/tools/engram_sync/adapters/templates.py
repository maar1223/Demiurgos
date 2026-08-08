"""Templates adapter: catalog metadata only; template content never loaded."""

import json
from pathlib import Path

from engram_sync.compare import classify
from engram_sync.models import (Action, ApplyResult, NormalizedItem,
                                PersistenceBoundaryError, SourceState)

from ._common import BaseAdapter, load_json, ref


class TemplatesAdapter(BaseAdapter):
    domain = "templates"

    def __init__(self, client, project="demiurgos", catalog_path="plantillas/_catalog.json",
                 topic="plantillas/catalog", title="Plantillas Catalog"):
        super().__init__(client, project)
        self._path, self._topic, self._title = Path(catalog_path), topic, title

    def discover(self):
        local = None
        if self._path.is_file():
            data, state = load_json(self._path)
            if state is SourceState.UNREADABLE:
                local = ref(str(self._path), state=state)
            elif not isinstance(data, list):
                local = ref(str(self._path), content={"raw": data}, state=SourceState.INVALID)
            else:
                local = ref(str(self._path), content={"entries": self._meta(data)})
        remote = self._remote(self._topic, title=self._title)
        if local is None and remote is None:
            return []
        return [NormalizedItem(domain=self.domain, item_key=self._topic, local=local,
                               remote=remote, classification=classify(local, remote))]

    def apply(self, operation):
        item, source = self._current(operation)
        if operation.action is Action.KEEP_LOCAL:
            entries = source.content.get("entries")
            if not isinstance(entries, list):
                raise PersistenceBoundaryError("template metadata is not safely serializable")
            return self._save_remote(operation, topic=self._topic, title=self._title,
                                     content=json.dumps({"entries": entries}, sort_keys=True,
                                                        ensure_ascii=False))
        raise PersistenceBoundaryError(
            "remote template metadata cannot reconstruct the catalog safely")

    def _meta(self, data):
        entries = ({"file": e.get("file"), "name": e.get("name"),
                    "skill": e.get("skill"), "tags": e.get("tags")}
                   for e in data if isinstance(e, dict))
        return sorted(entries, key=lambda e: str(e["file"]))
