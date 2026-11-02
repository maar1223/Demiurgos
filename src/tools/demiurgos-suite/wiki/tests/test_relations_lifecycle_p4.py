"""API-level tests for the world-wide reconciliation (P4)."""

import api_server
from test_api_server import client, _principal  # noqa: F401


def _world():
    return api_server.MUNDOS_DIR / "test_mundo"


def _add(world, rel: str, fm: str, body: str) -> None:
    path = world / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}---\n{body}", encoding="utf-8")


def _seed(world) -> None:
    _add(world, "lore/beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    # Gamma lives in another folder: the removal below stays genuinely ungrounded.
    _add(
        world,
        "lore/familia-a/gamma.md",
        "type: personaje\nid: lore::gamma\ntitle: Gamma\n",
        "Gamma.\n",
    )
    _add(
        world,
        "lore/alpha.md",
        "type: personaje\nid: lore::alpha\ntitle: Alpha\nrelaciones:\n  - lore::gamma\n",
        "Alpha served Beta.\n",
    )
    api_server._graph_indices.clear()


def _alpha() -> str:
    return (_world() / "lore" / "alpha.md").read_text(encoding="utf-8")


def test_preview_reports_additions_and_removals(client, monkeypatch):
    _principal(monkeypatch)
    _seed(_world())

    response = client.get("/api/test_mundo/relations/reconcile/preview")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["files"] == 1
    assert body["additions"] == 1
    assert body["removals"] == 1
    item = body["items"][0]
    assert item["path"] == "lore/alpha.md"
    assert item["add"] == ["lore::beta"]
    assert item["remove"][0]["key"] == "lore::gamma"
    assert item["remove"][0]["reason"] == "ungrounded"


def test_apply_rewrites_the_ficha_and_keeps_a_preimage_backup(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _seed(world)

    response = client.post("/api/test_mundo/relations/reconcile")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] == 1
    assert body["failed"] == []
    saved = _alpha()
    assert "lore::beta" in saved
    assert "lore::gamma" not in saved
    backup = world / body["backup"]
    assert (backup / "manifest.json").is_file()
    assert (backup / "files" / "lore" / "alpha.md").is_file()


def test_a_second_pass_writes_nothing_and_creates_no_backup(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    assert client.post("/api/test_mundo/relations/reconcile").json()["applied"] == 1
    backups_before = list((world / ".relations" / "preimages").iterdir())

    preview = client.get("/api/test_mundo/relations/reconcile/preview").json()
    applied = client.post("/api/test_mundo/relations/reconcile").json()

    assert preview["files"] == 0
    assert applied["applied"] == 0
    assert applied["backup"] == ""
    assert list((world / ".relations" / "preimages").iterdir()) == backups_before


def test_a_muted_ficha_is_not_touched(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    before = _alpha()
    assert client.post(
        "/api/test_mundo/relations/mute", json={"path": "lore/alpha.md"}
    ).status_code == 200

    preview = client.get("/api/test_mundo/relations/reconcile/preview").json()
    applied = client.post("/api/test_mundo/relations/reconcile").json()

    assert preview["files"] == 0
    assert applied["applied"] == 0
    assert _alpha() == before


def test_same_folder_sibling_is_removed_as_redundant_folder(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _add(
        world,
        "lore/familia-a/beta.md",
        "type: personaje\nid: lore::familia-a::beta\ntitle: Beta\n",
        "Beta.\n",
    )
    _add(
        world,
        "lore/familia-a/alpha.md",
        "type: personaje\nid: lore::familia-a::alpha\ntitle: Alpha\n"
        "relaciones:\n  - lore::familia-a::beta\n",
        "Alpha saluda.\n",
    )
    api_server._graph_indices.clear()

    item = client.get("/api/test_mundo/relations/reconcile/preview").json()["items"][0]

    assert item["path"] == "lore/familia-a/alpha.md"
    assert item["remove"][0]["target_id"] == "lore::familia-a::beta"
    assert item["remove"][0]["reason"] == "redundant-folder"


def test_a_cross_folder_ungrounded_link_stays_ungrounded(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _add(
        world,
        "lore/familia-b/beta.md",
        "type: personaje\nid: lore::familia-b::beta\ntitle: Beta\n",
        "Beta.\n",
    )
    _add(
        world,
        "lore/familia-a/alpha.md",
        "type: personaje\nid: lore::familia-a::alpha\ntitle: Alpha\n"
        "relaciones:\n  - lore::familia-b::beta\n",
        "Alpha saluda.\n",
    )
    api_server._graph_indices.clear()

    item = client.get("/api/test_mundo/relations/reconcile/preview").json()["items"][0]

    assert item["remove"][0]["target_id"] == "lore::familia-b::beta"
    assert item["remove"][0]["reason"] == "ungrounded"


def test_preview_is_cached_until_the_world_changes(client, monkeypatch):
    """The whole-world plan is CPU work; a repeated preview must not redo it."""
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    calls: list[int] = []
    real_build = api_server.build_global_plan

    def counting_build(**kwargs):
        calls.append(1)
        return real_build(**kwargs)

    monkeypatch.setattr(api_server, "build_global_plan", counting_build)

    first = client.get("/api/test_mundo/relations/reconcile/preview").json()
    second = client.get("/api/test_mundo/relations/reconcile/preview").json()

    assert first == second
    assert len(calls) == 1

    # Any ficha write changes the tree fingerprint: the next preview is fresh.
    # A direct write bypasses the endpoint that would drop the graph index, so
    # the test drops it the same way `_seed` does.
    _add(
        world,
        "lore/alpha.md",
        "type: personaje\nid: lore::alpha\ntitle: Alpha\n"
        "relaciones:\n  - lore::gamma\n  - lore::beta\n",
        "Alpha served Beta.\n",
    )
    api_server._graph_indices.clear()
    third = client.get("/api/test_mundo/relations/reconcile/preview").json()

    assert len(calls) == 2
    assert third["files"] == 1
    assert third["additions"] == 0  # beta is declared now
    assert third["removals"] == 1


def test_a_curation_write_invalidates_the_cached_preview(client, monkeypatch):
    _principal(monkeypatch)
    _seed(_world())

    assert client.get(
        "/api/test_mundo/relations/reconcile/preview"
    ).json()["files"] == 1

    assert client.post(
        "/api/test_mundo/relations/mute", json={"path": "lore/alpha.md"}
    ).status_code == 200

    assert client.get(
        "/api/test_mundo/relations/reconcile/preview"
    ).json()["files"] == 0


def test_a_non_entity_ficha_is_not_touched(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    _add(
        world,
        "lore/ghost.md",
        "type: concepto\nid: lore::ghost\ntitle: Ghost\ngraph: false\n"
        "relaciones:\n  - lore::beta\n",
        "Ghost.\n",
    )
    api_server._graph_indices.clear()
    before = (world / "lore" / "ghost.md").read_text(encoding="utf-8")

    assert client.post("/api/test_mundo/relations/reconcile").status_code == 200

    assert (world / "lore" / "ghost.md").read_text(encoding="utf-8") == before
