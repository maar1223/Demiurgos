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
