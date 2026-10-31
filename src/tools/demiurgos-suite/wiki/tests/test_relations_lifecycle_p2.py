"""API-level tests for the rejection memory (P2)."""

import api_server
from relation_rejections import load_rejected
from test_api_server import client, _confirm, _gated_write, _principal  # noqa: F401


def _world():
    return api_server.MUNDOS_DIR / "test_mundo"


def _add_target(world):
    lore = world / "lore"
    (lore / "beta.md").write_text(
        "---\ntype: personaje\nid: lore::beta\ntitle: Beta\n---\nBeta.\n",
        encoding="utf-8",
    )
    api_server._graph_indices.clear()


def _save(client, content, edit_id="e1"):
    conf, base = _confirm(client, "00_inicio.md", content, edit_id=edit_id)
    return _gated_write(client, "00_inicio.md", content, conf, base, edit_id=edit_id)


def _relation(client, action, target_id="lore::beta"):
    return client.post(
        "/api/test_mundo/graph/relation",
        json={
            "action": action,
            "source_path": "lore/00_inicio.md",
            "target_id": target_id,
        },
    )


def test_break_records_the_pair_and_a_save_does_not_re_add_it(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _add_target(world)
    content = "---\ntype: criatura\ntitle: Inicio\n---\nBeta arrives.\n"
    assert _save(client, content).status_code == 200
    assert "lore::beta" in (world / "lore" / "00_inicio.md").read_text(encoding="utf-8")

    assert _relation(client, "break").status_code == 200

    # A legacy ficha without a canonical id keys the verdict by its path.
    assert load_rejected(world) == {("lore/00_inicio.md", "lore::beta")}
    assert "lore::beta" not in (world / "lore" / "00_inicio.md").read_text(encoding="utf-8")

    current = (world / "lore" / "00_inicio.md").read_text(encoding="utf-8")
    assert _save(client, current, edit_id="e2").status_code == 200
    assert "lore::beta" not in (world / "lore" / "00_inicio.md").read_text(encoding="utf-8")


def test_break_and_save_on_a_canonical_source_keeps_the_verdict(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _add_target(world)
    pipeline = "---\ntype: criatura\nid: lore::inicio\ntitle: Inicio\n---\nBeta arrives.\n"
    assert _save(client, pipeline).status_code == 200
    assert "lore::beta" in (world / "lore" / "00_inicio.md").read_text(encoding="utf-8")

    assert _relation(client, "break").status_code == 200
    assert load_rejected(world) == {("lore::inicio", "lore::beta")}

    # Resaving the same body must not undo the Author's decision.
    current = (world / "lore" / "00_inicio.md").read_text(encoding="utf-8")
    assert _save(client, current, edit_id="e2").status_code == 200
    assert "lore::beta" not in (world / "lore" / "00_inicio.md").read_text(encoding="utf-8")


def test_create_clears_the_rejection(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _add_target(world)
    content = "---\ntype: criatura\nid: lore::inicio\ntitle: Inicio\n---\nBeta arrives.\n"
    assert _save(client, content).status_code == 200
    assert _relation(client, "break").status_code == 200
    assert load_rejected(world) == {("lore::inicio", "lore::beta")}

    assert _relation(client, "create").status_code == 200

    assert load_rejected(world) == set()
    assert "lore::beta" in (world / "lore" / "00_inicio.md").read_text(encoding="utf-8")

    # With the verdict cleared, the next save keeps the relation.
    current = (world / "lore" / "00_inicio.md").read_text(encoding="utf-8")
    assert _save(client, current, edit_id="e2").status_code == 200
    assert "lore::beta" in (world / "lore" / "00_inicio.md").read_text(encoding="utf-8")


def test_store_is_unreachable_as_content():
    assert api_server._resolve_mundo_path("test_mundo", ".relations/rejected.json") is None
    assert api_server._resolve_mundo_path(
        "test_mundo", "lore/../.relations/rejected.json"
    ) is None
