"""Ideas adapter: both stores, per-item discovery, duplicates surfaced, never bulk."""

import re
from pathlib import Path
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import yaml

from engram_sync.compare import classify
from engram_sync.models import (Action, ApplyResult, NormalizedItem,
                                PersistenceBoundaryError, SourceState)

from ._common import COMPLETE_DISCOVERY_LIMIT, BaseAdapter, atomic_write, ref

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_TYPES = {"idea_loose", "character_seed", "scene_seed", "dialogue", "concept"}
_FORBIDDEN = {"date", "personaje", "entidades", "notas"}
_REQUIRED = {"id", "slug", "timestamp", "source", "type", "tags", "status"}
_PREFIX = "nec/ideas/"


def _base(slug):
    return re.sub(r"-\d+$", "", slug)


def _iso(value):
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


class IdeasAdapter(BaseAdapter):
    domain = "ideas"

    def __init__(self, client, project, primary_dir, secondary_dir):
        super().__init__(client, project)
        self._dirs = (Path(primary_dir), Path(secondary_dir))

    def discover(self):
        by_slug = {}
        for store in self._dirs:
            for path in sorted(store.glob("*.md")):
                if path.is_file():
                    slug = path.stem
                    item = self._item(path)
                    by_slug[slug] = self._merge(by_slug.get(slug), item)
        for row in self._client.search(self._project, "ideas", limit=COMPLETE_DISCOVERY_LIMIT):
            if isinstance(row, dict):
                slug = self._slug_of(row)
                if slug and slug not in by_slug:
                    remote = self._remote(f"{_PREFIX}{slug}", title=slug)
                    if remote is not None:
                        by_slug[slug] = NormalizedItem(domain=self.domain, item_key=slug,
                                                       local=None, remote=remote,
                                                       classification=classify(None, remote))
        groups = {}
        for slug in by_slug:
            groups.setdefault(_base(slug), []).append(slug)
        canon = {b: (b if b in by_slug else min(s)) for b, s in groups.items()}
        items = []
        for slug, item in by_slug.items():
            base = _base(slug)
            flag = base != slug and slug != canon[base] and item.local is not None
            items.append(self._flag(item, "duplicate_of", canon[base]) if flag else item)
        items.sort(key=lambda i: i.item_key)
        return items

    def _slug_of(self, row):
        topic = str(row.get("topic", ""))
        if topic.startswith(_PREFIX):
            return topic[len(_PREFIX):]
        title = str(row.get("title", ""))
        return title if re.match(r"^\d{4}-\d{2}-\d{2}-", title) else ""

    def _item(self, path):
        slug = path.stem
        fm, body, state = self._parse(path)
        local = ref(str(path), identity={"slug": slug}, metadata=dict(fm) if fm else {},
                    content={"text": body}, state=state)
        remote = self._remote(f"{_PREFIX}{slug}", title=slug)
        return NormalizedItem(domain=self.domain, item_key=slug, local=local, remote=remote,
                              classification=classify(local, remote))

    def _merge(self, existing, new):
        if existing is None:
            return new
        return self._flag(existing, "also_in", new.local.location)

    def _flag(self, item, key, value):
        local = item.local
        md = dict(local.metadata)
        md[key] = value
        return replace(item, local=ref(local.location, identity=local.identity, metadata=md,
                                       content=local.content, state=local.state))

    def _parse(self, path):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            return None, "", SourceState.UNREADABLE
        match = _FM.match(text)
        if not match:
            return None, text, SourceState.INVALID
        try:
            fm = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            fm = None
        body = text[match.end():]
        if not isinstance(fm, dict):
            return None, body, SourceState.INVALID
        return fm, body, SourceState.PRESENT if self._valid(fm) else SourceState.INVALID

    def _valid(self, fm):
        bad = (_REQUIRED - set(fm)) or not _UUID.match(str(fm.get("id", ""))) \
            or not isinstance(fm.get("timestamp"), str) or not _iso(fm.get("timestamp")) \
            or fm.get("type") not in _TYPES or not isinstance(fm.get("tags"), list) \
            or bool(set(fm) & _FORBIDDEN)
        return not bad

    def apply(self, operation):
        item, source = self._current(operation)
        if operation.action is Action.KEEP_LOCAL:
            path = Path(source.location)
            try:
                document = path.read_text(encoding="utf-8-sig")
            except OSError as error:
                raise PersistenceBoundaryError("idea source cannot be read losslessly") from error
            return self._save_remote(operation, topic=f"nec/ideas/{operation.item_key}",
                                     title=operation.item_key, content=document)

        text = str(source.content.get("text", ""))
        match = _FM.match(text)
        if not match:
            raise PersistenceBoundaryError(
                "remote Idea lacks a complete frontmatter document; local reconstruction is unsafe")
        try:
            fm = yaml.safe_load(match.group(1))
        except yaml.YAMLError as error:
            raise PersistenceBoundaryError("remote Idea frontmatter is not safely parseable") from error
        if not isinstance(fm, dict) or not self._valid(fm) or fm.get("slug") != operation.item_key:
            raise PersistenceBoundaryError(
                "remote Idea does not satisfy the closed schema for lossless local persistence")
        destination = Path(item.local.location) if item.local else self._dirs[0] / f"{operation.item_key}.md"
        if not destination.parent.exists():
            raise PersistenceBoundaryError("Idea destination directory does not exist")
        atomic_write(destination, text)
        return ApplyResult(operation.item_key, "saved", "local Idea updated")
