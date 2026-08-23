# -*- coding: utf-8 -*-
"""World trash API tests — DELETE world, trash list, restore, permanent purge.

Covers W-2 of the world-delete-trash change: the four recycle-bin endpoints
plus the lazy 24h purge on GET /api/worlds/trash. Auth follows the house
pattern: default fail-closed (401), explicit local-dev session for gated
requests.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with temp mundos/ + world-trash/ and two sample worlds."""
    mundos = tmp_path / "mundos"
    for name in ("Avalor", "Kaelia"):
        (mundos / name / "lore").mkdir(parents=True)
        (mundos / name / "lore" / "inicio.md").write_text("# Inicio\n", encoding="utf-8")
    trash = tmp_path / "world-trash"

    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api_server, "TRASH_ROOT", trash)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    api_server._graph_indices.clear()
    # The durable guided-session store is SQLite-backed (no in-memory
    # `_sessions` dict): reset the server store to a fresh tmp db so each test
    # starts isolated and never touches the repo-local data/ database.
    api_server._GUIDED_SESSIONS = api_server.DurableGuidedSessionStore(
        db_path=tmp_path / "guided-sessions.sqlite3")
    # Re-create the importer store lazily against the tmp PROJECT_ROOT so the
    # purge's import-jobs cleanup never hits a store opened on the real root.
    api_server._IMPORT_STORE = None
    api_server._last_purge_at = None
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture()
def authed(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Enable local-dev auth and start a loopback session (cookie persists)."""
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
    started = client.post("/api/auth/local-dev/session")
    assert started.status_code == 200, started.text
    return client


def _delete_json(client: TestClient, url: str, payload: dict):
    """DELETE with a JSON body (httpx2 delete() has no body kwargs)."""
    return client.request("DELETE", url, json=payload)


def _seed_trash_entry(trash: Path, world: str, deleted_at: datetime) -> Path:
    """Craft a trash entry with a controlled deleted_at (no API call)."""
    stamp = deleted_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
    stamp = stamp.replace(":", "-").replace("+00:00", "Z")
    entry = trash / world / stamp
    (entry / "lore").mkdir(parents=True)
    (entry / "lore" / "old.md").write_text("# Old\n", encoding="utf-8")
    (entry / "meta.json").write_text(
        json.dumps(
            {
                "world_name": world,
                "deleted_at": deleted_at.astimezone(timezone.utc)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z"),
                "size_bytes": 12,
                "lore_count": 1,
                "character_count": 0,
                "saga_count": 0,
                "note": "associated data hidden; cleaned on purge",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return entry


class TestAuthRequired:
    @pytest.mark.parametrize(
        "method, path, payload",
        [
            ("delete", "/api/worlds/Avalor", {"confirm_name": "Avalor"}),
            ("get", "/api/worlds/trash", None),
            ("post", "/api/worlds/Avalor/restore", None),
            ("delete", "/api/worlds/trash/Avalor", None),
        ],
    )
    def test_all_endpoints_fail_closed(self, client: TestClient, method, path, payload):
        if payload is None:
            response = getattr(client, method)(path)
        else:
            response = _delete_json(client, path, payload)
        assert response.status_code == 401, response.text


class TestDeleteWorld:
    def test_happy_path_moves_world_to_trash(self, authed: TestClient):
        response = _delete_json(authed, "/api/worlds/Avalor", {"confirm_name": "Avalor"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["world_name"] == "Avalor"
        assert body["deleted_at"].endswith("Z")
        assert body["lore_count"] == 1
        assert body["days_remaining"] == 30

        worlds = authed.get("/api/worlds").json()
        assert [w["name"] for w in worlds] == ["Kaelia"]
        trash_dirs = [p for p in (api_server.TRASH_ROOT / "Avalor").iterdir() if p.is_dir()]
        assert len(trash_dirs) == 1
        assert (trash_dirs[0] / "meta.json").is_file()
        assert (trash_dirs[0] / "lore" / "inicio.md").is_file()

    def test_confirm_name_is_case_insensitive(self, authed: TestClient):
        response = _delete_json(authed, "/api/worlds/Avalor", {"confirm_name": "avalor"})
        assert response.status_code == 200, response.text

    def test_confirm_name_mismatch_returns_400(self, authed: TestClient):
        response = _delete_json(authed, "/api/worlds/Avalor", {"confirm_name": "WRONG"})
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "confirm_name_mismatch"

    def test_unknown_world_returns_404(self, authed: TestClient):
        response = _delete_json(authed, "/api/worlds/Fantasia", {"confirm_name": "Fantasia"})
        assert response.status_code == 404

    def test_active_world_returns_409(self, authed: TestClient, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(api_server, "_active_world", lambda: "Avalor")
        response = _delete_json(authed, "/api/worlds/Avalor", {"confirm_name": "Avalor"})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "active_world"

    def test_only_world_returns_409(self, authed: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        only = tmp_path / "only-mundos"
        (only / "Solo").mkdir(parents=True)
        monkeypatch.setattr(api_server, "MUNDOS_DIR", only)
        response = _delete_json(authed, "/api/worlds/Solo", {"confirm_name": "SOLO"})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "only_world"

    def test_reserved_trash_name_returns_404(self, authed: TestClient):
        (api_server.MUNDOS_DIR / "trash").mkdir()
        response = _delete_json(authed, "/api/worlds/trash", {"confirm_name": "trash"})
        assert response.status_code == 404

    def test_delete_hides_associated_data(self, authed: TestClient):
        api_server._GUIDED_SESSIONS.create("s1", "Avalor", "local")
        api_server._graph_indices["Avalor"] = object()
        response = _delete_json(authed, "/api/worlds/Avalor", {"confirm_name": "Avalor"})
        assert response.status_code == 200
        assert "Avalor" not in api_server._graph_indices
        assert api_server._GUIDED_SESSIONS.recover("s1", "local") is None


class TestTrashList:
    def test_empty_trash_returns_empty_array(self, authed: TestClient):
        response = authed.get("/api/worlds/trash")
        assert response.status_code == 200
        assert response.json() == []

    def test_sorted_desc_with_metadata(self, authed: TestClient):
        older = _seed_trash_entry(api_server.TRASH_ROOT, "Kaelia",
                                  datetime.now(timezone.utc) - timedelta(days=10))
        assert _delete_json(authed, "/api/worlds/Avalor", {"confirm_name": "Avalor"}).status_code == 200
        body = authed.get("/api/worlds/trash").json()
        assert [e["world_name"] for e in body] == ["Avalor", "Kaelia"]
        assert body[0]["days_remaining"] == 30
        assert body[1]["days_remaining"] == 20
        assert older.exists()

    def test_lazy_purge_removes_expired(self, authed: TestClient, monkeypatch):
        _seed_trash_entry(api_server.TRASH_ROOT, "Expired",
                          datetime.now(timezone.utc) - timedelta(days=31))
        api_server._graph_indices["Expired"] = object()
        api_server._GUIDED_SESSIONS.create("s1", "Expired", "local")
        # C-1 regression guard: the automatic purge must run the FULL
        # associated-data cleanup (`_purge_world_associated_data`), not just
        # `_hide_world_data`, so idea-capture rows are not left orphaned.
        calls: list[str] = []

        def spy(world: str) -> None:
            calls.append(world)
            api_server._hide_world_data(world)

        monkeypatch.setattr(api_server, "_purge_world_associated_data", spy)
        response = authed.get("/api/worlds/trash")
        assert response.status_code == 200
        assert response.json() == []
        assert not (api_server.TRASH_ROOT / "Expired").exists()
        assert "Expired" not in api_server._graph_indices
        assert calls == ["Expired"]

    def test_lazy_purge_skips_recent(self, authed: TestClient):
        _seed_trash_entry(api_server.TRASH_ROOT, "Recent",
                          datetime.now(timezone.utc) - timedelta(days=10))
        body = authed.get("/api/worlds/trash").json()
        assert [e["world_name"] for e in body] == ["Recent"]

    def test_lazy_purge_respects_24h_guard(self, authed: TestClient):
        _seed_trash_entry(api_server.TRASH_ROOT, "Expired",
                          datetime.now(timezone.utc) - timedelta(days=31))
        api_server._last_purge_at = datetime.now(timezone.utc)
        body = authed.get("/api/worlds/trash").json()
        assert [e["world_name"] for e in body] == ["Expired"]
        assert (api_server.TRASH_ROOT / "Expired").exists()


class TestRestore:
    def test_happy_path_restores_world(self, authed: TestClient):
        assert _delete_json(authed, "/api/worlds/Avalor", {"confirm_name": "Avalor"}).status_code == 200
        response = authed.post("/api/worlds/Avalor/restore")
        assert response.status_code == 200
        assert response.json() == {"status": "restored", "world_name": "Avalor"}
        assert (api_server.MUNDOS_DIR / "Avalor" / "lore" / "inicio.md").is_file()
        assert not (api_server.TRASH_ROOT / "Avalor").exists()
        worlds = authed.get("/api/worlds").json()
        assert sorted(w["name"] for w in worlds) == ["Avalor", "Kaelia"]

    def test_not_in_trash_returns_404(self, authed: TestClient):
        response = authed.post("/api/worlds/Fantasia/restore")
        assert response.status_code == 404

    def test_name_conflict_returns_409(self, authed: TestClient):
        assert _delete_json(authed, "/api/worlds/Avalor", {"confirm_name": "Avalor"}).status_code == 200
        (api_server.MUNDOS_DIR / "Avalor").mkdir()  # manual re-creation
        response = authed.post("/api/worlds/Avalor/restore")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "world_exists"


class TestPermanentPurge:
    def test_purges_entry_and_cleans_associated_data(self, authed: TestClient):
        _seed_trash_entry(api_server.TRASH_ROOT, "Avalor",
                          datetime.now(timezone.utc) - timedelta(days=2))
        api_server._graph_indices["Avalor"] = object()
        api_server._GUIDED_SESSIONS.create("s1", "Avalor", "local")
        response = authed.delete("/api/worlds/trash/Avalor")
        assert response.status_code == 200
        assert response.json() == {"status": "purged", "world_name": "Avalor"}
        assert not (api_server.TRASH_ROOT / "Avalor").exists()
        assert "Avalor" not in api_server._graph_indices
        assert api_server._GUIDED_SESSIONS.recover("s1", "local") is None

    def test_unknown_world_returns_404(self, authed: TestClient):
        response = authed.delete("/api/worlds/trash/Fantasia")
        assert response.status_code == 404