"""API-level tests: the Author's explicit relation wins over the sync (P3/P4 fix)."""

from __future__ import annotations

import api_server
from relation_curation import load_curated, pin
from relation_proposals import Proposal, add_proposals
from relation_rejections import load_rejected
from test_api_server import client, _principal  # noqa: F401


def _world():
    return api_server.MUNDOS_DIR / "test_mundo"


def _add(world, rel: str, fm: str, body: str) -> None:
    path = world / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}---\n{body}", encoding="utf-8")
    api_server._graph_indices.clear()


def _seed(world) -> None:
    _add(world, "lore/beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    _add(world, "lore/gamma.md", "type: personaje\nid: lore::gamma\ntitle: Gamma\n", "Gamma.\n")
    _add(
        world,
        "lore/alpha.md",
        "type: personaje\nid: lore::alpha\ntitle: Alpha\n",
        "Alpha served Beta.\n",
    )


def test_accepting_a_proposal_pins_the_pair(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    add_proposals(
        world,
        [
            Proposal(
                id="p1",
                source_path="lore/alpha.md",
                source_key="lore::alpha",
                target_id="lore::beta",
                relationship_type="aliado-de",
                confidence=0.9,
                evidence="Alpha served Beta.",
                created_at="2026-10-31T00:00:00",
            )
        ],
    )

    response = client.post("/api/test_mundo/relations/proposals/p1/accept")

    assert response.status_code == 200, response.text
    assert ("lore::alpha", "lore::beta") in load_curated(world)


def test_graph_create_pins_and_break_unpins(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _seed(world)

    created = client.post(
        "/api/test_mundo/graph/relation",
        json={"action": "create", "source_path": "lore/alpha.md", "target_id": "lore::beta"},
    )
    assert created.status_code == 200, created.text
    assert ("lore::alpha", "lore::beta") in load_curated(world)

    broken = client.post(
        "/api/test_mundo/graph/relation",
        json={"action": "break", "source_path": "lore/alpha.md", "target_id": "lore::beta"},
    )
    assert broken.status_code == 200, broken.text
    assert ("lore::alpha", "lore::beta") not in load_curated(world)
    assert ("lore::alpha", "lore::beta") in load_rejected(world)


def test_preview_keeps_a_curated_ungrounded_relation(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    _add(
        world,
        "lore/alpha.md",
        "type: personaje\nid: lore::alpha\ntitle: Alpha\nrelaciones:\n  - lore::gamma\n",
        "Alpha served Beta.\n",
    )
    pin(world, "lore::alpha", "lore::gamma")
    api_server._graph_indices.clear()

    preview = client.get("/api/test_mundo/relations/reconcile/preview")

    assert preview.status_code == 200, preview.text
    items = {item["path"]: item for item in preview.json()["items"]}
    assert items["lore/alpha.md"]["remove"] == []
    assert items["lore/alpha.md"]["add"] == ["lore::beta"]
