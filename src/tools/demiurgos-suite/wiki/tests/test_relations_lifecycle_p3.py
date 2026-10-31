"""API-level tests for sweep candidates and the "leave as is" verdict (P3)."""

import api_server
from relation_state import state_path
from test_api_server import client, _principal  # noqa: F401


def _world():
    return api_server.MUNDOS_DIR / "test_mundo"


def _add(world, rel: str, fm: str, body: str) -> None:
    path = world / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}---\n{body}", encoding="utf-8")


def _seed(world) -> None:
    _add(
        world,
        "lore/beta.md",
        "type: personaje\nid: lore::beta\ntitle: Beta\n",
        "Beta.\n",
    )
    _add(
        world,
        "lore/alpha.md",
        "type: personaje\nid: lore::alpha\ntitle: Alpha\n",
        "Alpha served Beta.\n",
    )
    api_server._graph_indices.clear()


def test_candidates_lists_a_ficha_that_mentions_another(client, monkeypatch):
    _principal(monkeypatch)
    _seed(_world())

    response = client.get("/api/test_mundo/relations/candidates")

    assert response.status_code == 200, response.text
    body = response.json()
    paths = [item["path"] for item in body["items"]]
    assert "lore/alpha.md" in paths
    assert body["count"] == len(paths)
    alpha = next(item for item in body["items"] if item["path"] == "lore/alpha.md")
    assert alpha["missing"] == ["lore::beta"]


def test_mute_hides_the_candidate_and_unmute_restores_it(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _seed(world)

    muted = client.post(
        "/api/test_mundo/relations/mute", json={"path": "lore/alpha.md"}
    )
    assert muted.status_code == 200, muted.text
    assert muted.json()["changed"] is True
    assert state_path(world).is_file()

    paths = [item["path"] for item in client.get(
        "/api/test_mundo/relations/candidates"
    ).json()["items"]]
    assert "lore/alpha.md" not in paths

    unmuted = client.post(
        "/api/test_mundo/relations/unmute", json={"path": "lore/alpha.md"}
    )
    assert unmuted.status_code == 200, unmuted.text
    paths = [item["path"] for item in client.get(
        "/api/test_mundo/relations/candidates"
    ).json()["items"]]
    assert "lore/alpha.md" in paths


def test_mute_rejects_an_unknown_path(client, monkeypatch):
    _principal(monkeypatch)

    response = client.post(
        "/api/test_mundo/relations/mute", json={"path": "lore/nope.md"}
    )

    assert response.status_code == 404


def test_mute_requires_a_path(client, monkeypatch):
    _principal(monkeypatch)

    response = client.post("/api/test_mundo/relations/mute", json={})

    assert response.status_code == 400


def _theory():
    import json

    return json.dumps(
        {
            "relationships": [
                {
                    "source_candidate_id": "lore::alpha",
                    "target_canonical_id": "lore::beta",
                    "relationship_type": "aliado-de",
                    "confidence": 0.9,
                    "evidence": "Alpha served Beta.",
                }
            ]
        }
    )


def test_sweep_creates_a_proposal_and_accept_writes_it(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    monkeypatch.setattr(api_server, "_sync_hermes_enricher", lambda prompt, session: _theory())

    swept = client.post("/api/test_mundo/relations/sweep")

    assert swept.status_code == 200, swept.text
    body = swept.json()
    assert body["status"] == "swept"
    assert body["created"] == 1
    queue = client.get("/api/test_mundo/relations/proposals").json()
    assert queue["count"] == 1
    item = queue["items"][0]
    assert item["target_id"] == "lore::beta"
    assert item["relationship_type"] == "aliado-de"

    accepted = client.post(
        f"/api/test_mundo/relations/proposals/{item['id']}/accept"
    )

    assert accepted.status_code == 200, accepted.text
    saved = (world / "lore" / "alpha.md").read_text(encoding="utf-8")
    assert "lore::beta" in saved
    assert client.get("/api/test_mundo/relations/proposals").json()["count"] == 0


def test_reject_records_the_pair_and_removes_it(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    monkeypatch.setattr(api_server, "_sync_hermes_enricher", lambda prompt, session: _theory())
    assert client.post("/api/test_mundo/relations/sweep").json()["created"] == 1
    item = client.get("/api/test_mundo/relations/proposals").json()["items"][0]

    rejected = client.post(
        f"/api/test_mundo/relations/proposals/{item['id']}/reject"
    )

    assert rejected.status_code == 200, rejected.text
    assert client.get("/api/test_mundo/relations/proposals").json()["count"] == 0
    from relation_rejections import load_rejected

    assert ("lore::alpha", "lore::beta") in load_rejected(world)


def test_a_silent_provider_leaves_the_ficha_reviewable(client, monkeypatch):
    _principal(monkeypatch)
    _seed(_world())
    monkeypatch.setattr(api_server, "_sync_hermes_enricher", lambda prompt, session: "")

    swept = client.post("/api/test_mundo/relations/sweep")

    assert swept.status_code == 200, swept.text
    assert swept.json()["status"] == "unavailable"
    assert swept.json()["created"] == 0
    assert client.get("/api/test_mundo/relations/proposals").json()["count"] == 0
    paths = [
        item["path"]
        for item in client.get("/api/test_mundo/relations/candidates").json()["items"]
    ]
    assert "lore/alpha.md" in paths
