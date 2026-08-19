"""Focused remediation coverage for production boundaries and fail-closed paths."""

import json

import pytest

from engram_sync.adapter import AdapterRegistry
from engram_sync.adapters import ArcStateAdapter, IdeasAdapter, TemplatesAdapter
from engram_sync.confirm import ConfirmError, ConfirmedChoice, confirm
from engram_sync.engram_client import EngramUnauthorized
from engram_sync.journal import RunJournal
from engram_sync.models import Action, Classification, PersistenceBoundaryError


IDEA = ('---\nid: "b1c2d3e4-f5a6-7890-abcd-ef1234567890"\n'
        'slug: "2026-08-07-production"\ntimestamp: "2026-08-07T10:00:00Z"\n'
        'source: "direct"\ntype: "idea_loose"\ntags: []\nstatus: "synced"\n---\n\nBody\n')


class FakeEngram:
    def __init__(self, rows=(), save_error=None):
        self.rows = list(rows)
        self.save_error = save_error
        self.searches = []
        self.saves = []

    def search(self, project, query, limit=10):
        self.searches.append((project, query, limit))
        return list(self.rows)

    def save(self, operation, **kwargs):
        if self.save_error:
            raise self.save_error
        self.saves.append((operation, kwargs))
        return {"id": 42}


def _confirm(adapter, item, tmp_path):
    registry = AdapterRegistry()
    registry.register(adapter)
    journal = RunJournal(tmp_path / ".demiurgos-sync")
    source = item.local
    result = confirm(registry, [ConfirmedChoice(item.domain, item.item_key,
                                                Action.KEEP_LOCAL, source.revision)],
                     journal, confirmation="APPLY")
    return result, journal


@pytest.mark.parametrize("domain", ["ideas", "arc-state", "templates"])
def test_authorized_production_adapters_save_lossless_supported_metadata(tmp_path, domain):
    client = FakeEngram()
    if domain == "ideas":
        primary, secondary = tmp_path / "Ideas", tmp_path / "world" / "ideas"
        primary.mkdir(parents=True)
        secondary.mkdir(parents=True)
        path = primary / "2026-08-07-production.md"
        path.write_text(IDEA, encoding="utf-8")
        adapter = IdeasAdapter(client, "vibrantes", primary, secondary)
    elif domain == "arc-state":
        path = tmp_path / "estado.json"
        path.write_text(json.dumps({"arcos": {"arc": {"status": "active"}}}), encoding="utf-8")
        adapter = ArcStateAdapter(client, "vibrantes", path)
    else:
        path = tmp_path / "catalog.json"
        path.write_text(json.dumps([{"file": "a.md", "name": "A", "skill": "x", "tags": []}]),
                        encoding="utf-8")
        adapter = TemplatesAdapter(client, catalog_path=path)

    item = adapter.discover()[0]
    result, journal = _confirm(adapter, item, tmp_path)
    assert result[0].applied is True
    assert len(client.saves) == 1
    assert journal._rows()[0].state == "applied"
    assert client.searches and all(call[2] == 1_000 for call in client.searches)


def test_unauthorized_production_write_fails_and_is_journaled(tmp_path):
    primary, secondary = tmp_path / "Ideas", tmp_path / "world" / "ideas"
    primary.mkdir(parents=True)
    secondary.mkdir(parents=True)
    path = primary / "2026-08-07-production.md"
    path.write_text(IDEA, encoding="utf-8")
    client = FakeEngram(save_error=EngramUnauthorized("client is read-only"))
    adapter = IdeasAdapter(client, "vibrantes", primary, secondary)
    result, journal = _confirm(adapter, adapter.discover()[0], tmp_path)
    assert result[0].applied is False and "apply failed closed" in result[0].message
    assert journal._rows()[0].state == "failed"
    assert client.saves == []


def test_malformed_remote_reverse_apply_is_rejected_without_local_write(tmp_path):
    rows = [{"id": 4, "topic": "nec/ideas/remote-only", "title": "remote-only",
             "content": "body without the closed Idea schema"}]
    primary, secondary = tmp_path / "Ideas", tmp_path / "world" / "ideas"
    primary.mkdir(parents=True)
    secondary.mkdir(parents=True)
    client = FakeEngram(rows)
    adapter = IdeasAdapter(client, "vibrantes", primary, secondary)
    item = adapter.discover()[0]
    registry = AdapterRegistry()
    registry.register(adapter)
    journal = RunJournal(tmp_path / "sync")
    result = confirm(registry, [ConfirmedChoice("ideas", item.item_key, Action.KEEP_ENGRAM,
                                                item.remote.revision)], journal,
                     confirmation="APPLY")
    assert result[0].applied is False
    assert "nothing was written" in result[0].message
    assert not (primary / "remote-only.md").exists()
    assert journal._rows()[0].state == "failed"


def test_conflicting_and_invalid_apply_choices_fail_closed(tmp_path):
    from engram_sync.models import NormalizedItem, SourceRef
    from engram_sync.canonicalize import fingerprint

    local = SourceRef("local", "rev", content={"text": "local"}, fingerprint=fingerprint({"text": "local"}))
    item = NormalizedItem("ideas", "item", local=local, remote=local,
                          classification=Classification.INVALID)

    class Adapter:
        domain = "ideas"
        def discover(self): return [item]
        def apply(self, operation): pytest.fail("invalid choice must not apply")

    registry = AdapterRegistry()
    registry.register(Adapter())
    journal = RunJournal(tmp_path / "sync")
    with pytest.raises(ConfirmError, match="cannot be applied"):
        confirm(registry, [ConfirmedChoice("ideas", "item", Action.KEEP_LOCAL, "rev")],
                journal, confirmation="APPLY")
    assert not journal.path.exists()
