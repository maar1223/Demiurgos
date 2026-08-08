"""RED/GREEN: phase-1 adapters — ideas, arc state, lore index, templates (3.1-3.5)."""

import json
from pathlib import Path

import pytest

from engram_sync.adapters import (ArcStateAdapter, IdeasAdapter, LoreIndexAdapter,
                                  TemplatesAdapter, register_phase1)
from engram_sync.adapter import AdapterRegistry, DomainAdapter
from engram_sync.models import Action, AuthorizedOperation, Classification, SourceState

VALID = ('---\nid: "b1c2d3e4-f5a6-7890-abcd-ef1234567890"\nslug: "2026-08-02-idea-a"\n'
         'timestamp: "2026-08-02T10:00:00Z"\nsource: "direct"\ntype: "idea_loose"\n'
         'tags: []\nstatus: "synced"\n---\n\nBody A\n')
MALFORMED = '---\nid: "71"\ntimestamp: 1779711257\n---\n\nBroken body\n'
ESTADO = {"version": 1, "mundo_activo": "vibrantes", "last_session": "2026-08-07T00:00:00",
          "arcos": {"arc-x": {"status": "active", "fase_actual": "design"}}}
INDEX = {"meta": {"version": "0.1.0", "entities_extracted": 3}, "terms": [{"t": 1}],
         "contradictions": [{"c": 1}]}
CATALOG = [{"file": "plantillas/a.md", "name": "A", "skill": "skills/x.md", "tags": ["t"],
            "use_case": "desc"}]
LORE_ROW = {"id": 5, "topic": "lore/vibrantes/index", "title": "Lore Index \u2014 vibrantes",
            "content": "**Stats**: 3 entities, 1 terms, 1 contradictions"}


class FakeClient:
    def __init__(self, rows=None): self.rows, self.calls, self.saves = rows or [], [], []
    def search(self, project, query, limit=10):
        self.calls.append((project, query, limit))
        return self.rows
    def save(self, operation, **kwargs):
        self.saves.append((operation, kwargs))
        return {"id": 1}


def _write(p, name, obj=None, text=None):
    f = p / name
    f.write_text(text if text is not None else json.dumps(obj), encoding="utf-8")
    return f


def _ideas(tmp_path, client=None):
    primary, secondary = tmp_path / "primary", tmp_path / "secondary"
    primary.mkdir(), secondary.mkdir()
    for name in ("2026-08-02-idea-a.md", "2026-08-02-idea-dup.md",
                 "2026-08-02-idea-dup-2.md", "malformed.md"):
        _write(primary, name, text=VALID if "malformed" not in name else MALFORMED)
    _write(secondary, "2026-08-02-idea-a.md", text=VALID)
    _write(secondary, "2026-08-02-idea-b.md", text=VALID.replace("idea-a", "idea-b"))
    return IdeasAdapter(client or FakeClient(), "vibrantes", primary, secondary)


def test_ideas_scan_duplicates_malformed_no_writes(tmp_path, tree_snapshot):
    adapter = _ideas(tmp_path)
    before = tree_snapshot(tmp_path)
    items = {i.item_key: i for i in adapter.discover()}
    assert list(items) == ["2026-08-02-idea-a", "2026-08-02-idea-b", "2026-08-02-idea-dup",
                           "2026-08-02-idea-dup-2", "malformed"]
    assert tree_snapshot(tmp_path) == before
    dup = items["2026-08-02-idea-dup-2"]
    assert dup.local.metadata["duplicate_of"] == "2026-08-02-idea-dup"
    assert "duplicate_of" not in items["2026-08-02-idea-dup"].local.metadata
    assert "secondary" in items["2026-08-02-idea-a"].local.metadata["also_in"]
    bad = items["malformed"]
    assert bad.local.state is SourceState.INVALID and bad.classification is Classification.INVALID
    assert all(i.classification is Classification.LOCAL_ONLY
               for k, i in items.items() if k != "malformed")


def test_ideas_remote_matching_engram_only_repeat(tmp_path):
    rows = [{"id": 7, "topic": "nec/ideas/2026-08-02-idea-a", "title": "2026-08-02-idea-a",
             "content": "text"}, {"id": 8, "topic": "nec/ideas/only-memory",
                                  "title": "only-memory", "content": "text"}]
    adapter = _ideas(tmp_path, FakeClient(rows))
    first = [(i.item_key, i.classification, i.local.fingerprint if i.local else "")
             for i in adapter.discover()]
    assert first == [(i.item_key, i.classification, i.local.fingerprint if i.local else "")
                     for i in adapter.discover()]
    items = {i.item_key: i for i in adapter.discover()}
    assert items["2026-08-02-idea-a"].classification is Classification.DIVERGENT
    extra = items["only-memory"]
    assert extra.local is None and extra.classification is Classification.ENGRAM_ONLY


def test_arc_divergence_local_authority_remote_only_corrupt(tmp_path, tree_snapshot):
    path = _write(tmp_path, "estado.json", ESTADO)
    original = path.read_text(encoding="utf-8")
    before = tree_snapshot(tmp_path)
    rows = [{"id": 3, "topic": "nec/arc-x/state", "title": "arc-x", "content": "summary"},
            {"id": 4, "topic": "nec/arc-y/state", "title": "arc-y", "content": "text"}]
    items = {i.item_key: i for i in ArcStateAdapter(FakeClient(rows), "vibrantes", path).discover()}
    assert items["arc-x"].classification is Classification.DIVERGENT
    assert items["arc-y"].local is None and items["arc-y"].classification is Classification.ENGRAM_ONLY
    assert tree_snapshot(tmp_path) == before and path.read_text(encoding="utf-8") == original
    item = ArcStateAdapter(FakeClient(), "vibrantes",
                           _write(tmp_path, "bad.json", text="{not json")).discover()[0]
    assert item.item_key == "estado" and item.classification is Classification.UNREADABLE


def test_lore_equivalent_divergent_absent(tmp_path):
    path = _write(tmp_path, "lore.json", INDEX)
    assert LoreIndexAdapter(FakeClient([LORE_ROW]), "vibrantes", path).discover()[0] \
        .classification is Classification.EQUIVALENT
    row = dict(LORE_ROW)
    row["content"] = "**Stats**: 9 entities, 1 terms, 1 contradictions"
    assert LoreIndexAdapter(FakeClient([row]), "vibrantes", path).discover()[0] \
        .classification is Classification.DIVERGENT
    assert LoreIndexAdapter(FakeClient(), "vibrantes", tmp_path / "nope.json").discover() == []


def test_templates_metadata_only_remote_absent(tmp_path):
    path = _write(tmp_path, "catalog.json", CATALOG)
    item = TemplatesAdapter(FakeClient(), catalog_path=path).discover()[0]
    assert set(item.local.content["entries"][0]) == {"file", "name", "skill", "tags"}
    assert item.classification is Classification.LOCAL_ONLY
    rows = [{"id": 6, "topic": "plantillas/catalog", "title": "Plantillas Catalog",
             "content": "snapshot"}]
    assert TemplatesAdapter(FakeClient(rows), catalog_path=path).discover()[0] \
        .classification is Classification.DIVERGENT
    assert TemplatesAdapter(FakeClient(), catalog_path=tmp_path / "nope.json").discover() == []


def test_register_adapters_have_explicit_apply_contract(tmp_path):
    reg = register_phase1(AdapterRegistry(), FakeClient(), "vibrantes",
                          ideas_primary=str(tmp_path / "a"), ideas_secondary=str(tmp_path / "b"),
                          estado=str(tmp_path / "e.json"), lore_index=str(tmp_path / "l.json"),
                          templates_catalog=str(tmp_path / "t.json"))
    assert reg.domains() == ["arc-state", "ideas", "lore-index", "templates"]
    assert all(isinstance(reg.get(d), DomainAdapter) for d in reg.domains())
    assert all(callable(reg.get(d).apply) for d in reg.domains())
    pkg = Path(__file__).resolve().parents[1] / "adapters"
    src = "".join(p.read_text(encoding="utf-8") for p in pkg.glob("*.py"))
    for banned in ("sync_lore", "demiurgos_suite", "web_config_ui", "frontend"):
        assert banned not in src


def test_remote_discovery_is_explicitly_bounded_and_not_truncated(tmp_path):
    rows = [{"id": i, "topic": f"nec/ideas/2026-08-02-remote-{i}",
             "title": f"2026-08-02-remote-{i}", "content": f"body-{i}"}
            for i in range(25)]
    client = FakeClient(rows)
    items = IdeasAdapter(client, "vibrantes", tmp_path / "primary", tmp_path / "secondary").discover()
    assert len(items) == 25
    assert {item.item_key for item in items} == {f"2026-08-02-remote-{i}" for i in range(25)}
    assert all(call[2] == 1_000 for call in client.calls)


def test_remote_title_is_preserved_for_preview(tmp_path):
    rows = [{"id": 7, "topic": "nec/ideas/only", "title": "Human title", "content": "body"}]
    item = IdeasAdapter(FakeClient(rows), "vibrantes", tmp_path / "primary",
                        tmp_path / "secondary").discover()[0]
    assert item.remote.metadata["title"] == "Human title"
