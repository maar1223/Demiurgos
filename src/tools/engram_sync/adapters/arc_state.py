"""Arc state adapter: local estado vs nec/{arc}/state; discovery only."""

import json
import re
from pathlib import Path

from engram_sync.compare import classify
from engram_sync.models import (Action, ApplyResult, NormalizedItem,
                                PersistenceBoundaryError, SourceState)

from ._common import COMPLETE_DISCOVERY_LIMIT, BaseAdapter, atomic_write, load_json, ref

_TOPIC = re.compile(r"^nec/([^/]+)/state$")


class ArcStateAdapter(BaseAdapter):
    domain = "arc-state"

    def __init__(self, client, project, estado_path):
        super().__init__(client, project)
        self._estado = Path(estado_path)

    def discover(self):
        if not self._estado.is_file():
            return self._arcs({})
        data, state = load_json(self._estado)
        if state is SourceState.UNREADABLE:
            return self._file_item(SourceState.UNREADABLE, None)
        if not isinstance(data, dict) or not isinstance(data.get("arcos"), dict):
            return self._file_item(SourceState.INVALID, data)
        return self._arcs(data["arcos"])

    def _file_item(self, state, data):
        local = ref(str(self._estado), content={"raw": data}, state=state)
        return [NormalizedItem(domain=self.domain, item_key="estado", local=local,
                               remote=None, classification=classify(local, None))]

    def _arcs(self, local_arcs):
        arcs = set(local_arcs)
        for row in self._client.search(self._project, "state", limit=COMPLETE_DISCOVERY_LIMIT):
            match = _TOPIC.match(str(row.get("topic", ""))) if isinstance(row, dict) else None
            if match:
                arcs.add(match.group(1))
        items = []
        for arc in sorted(arcs):
            if arc in local_arcs:
                data = local_arcs[arc]
                state = SourceState.PRESENT if isinstance(data, dict) else SourceState.INVALID
                local = ref(str(self._estado), identity={"arc": arc},
                            content=data if isinstance(data, dict) else {"raw": data}, state=state)
            else:
                local = None
            remote = self._remote(f"nec/{arc}/state", title=arc)
            items.append(NormalizedItem(domain=self.domain, item_key=arc, local=local,
                                        remote=remote, classification=classify(local, remote)))
        return items

    def apply(self, operation):
        item, source = self._current(operation)
        if operation.action is Action.KEEP_LOCAL:
            data = source.content.get("raw") if "raw" in source.content else source.content
            if not isinstance(data, dict):
                raise PersistenceBoundaryError("arc state is not a JSON object")
            return self._save_remote(operation, topic=f"nec/{operation.item_key}/state",
                                     title=operation.item_key,
                                     content=json.dumps(data, sort_keys=True, ensure_ascii=False))

        if not self._estado.is_file():
            raise PersistenceBoundaryError("missing local state root cannot be reconstructed safely")
        try:
            remote_data = json.loads(str(source.content.get("text", "")))
        except (TypeError, ValueError) as error:
            raise PersistenceBoundaryError("remote arc state is not serialized JSON") from error
        if not isinstance(remote_data, dict):
            raise PersistenceBoundaryError("remote arc state must be a JSON object")
        current, state = load_json(self._estado)
        if state is not SourceState.PRESENT or not isinstance(current, dict) \
                or not isinstance(current.get("arcos"), dict):
            raise PersistenceBoundaryError("local state root is not safely writable")
        updated = dict(current)
        updated["arcos"] = dict(current["arcos"])
        updated["arcos"][operation.item_key] = remote_data
        atomic_write(self._estado, json.dumps(updated, indent=2, ensure_ascii=False) + "\n")
        return ApplyResult(operation.item_key, "saved", "local arc state updated")
