# -*- coding: utf-8 -*-
"""API server tests — tree contract, save, and diff endpoints.

These endpoints were rebuilt in api_server.py and previously had no test
coverage, which is how the is_dir contract regression survived unnoticed.
"""

import base64
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402
from assistant_activity import assess_hermes_capabilities  # noqa: E402


def _activity_capability():
    return assess_hermes_capabilities(
        {
            "object": "hermes.api_server.capabilities",
            "platform": "hermes-agent",
            "features": {
                "run_submission": True,
                "run_status": True,
                "run_events_sse": True,
                "run_stop": True,
                "tool_progress_events": True,
            },
        }
    )


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a temp mundos dir and a sample world."""
    mundos = tmp_path / "mundos"
    world = mundos / "test_mundo"
    lore = world / "lore"
    (lore / "subdir").mkdir(parents=True)
    (lore / "00_inicio.md").write_text("---\ntype: criatura\ntitle: Inicio\n---\n# Inicio\n", encoding="utf-8")
    (lore / "subdir" / "detalle.md").write_text("# Detalle\n", encoding="utf-8")

    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    api_server._graph_indices.clear()
    api_server._confirmation_store.clear()
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    api_server._target_locks.clear()
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture()
def jpeg_bytes() -> bytes:
    """Minimal valid JPEG payload (survives PIL round-trip in uploads)."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def client_sorted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a world whose tree exercises ordering rules.

    Top level mixes dirs and files with case variations so that only a
    dirs-first, case-insensitive sort yields the expected order:
    `alpha/`, `Zeta/`, `Beta.md`, `gamma.md`.
    """
    mundos = tmp_path / "mundos"
    world = mundos / "test_mundo"
    lore = world / "lore"
    (lore / "Zeta").mkdir(parents=True)
    (lore / "Zeta" / "zeta_inner.md").write_text("# Z\n", encoding="utf-8")
    (lore / "alpha").mkdir()
    (lore / "alpha" / "aleph").mkdir()
    (lore / "alpha" / "aleph" / "a1.md").write_text("# A1\n", encoding="utf-8")
    (lore / "alpha" / "Beta").mkdir()
    (lore / "alpha" / "Beta" / "b1.md").write_text("# B1\n", encoding="utf-8")
    (lore / "alpha" / "gamma.md").write_text("# G\n", encoding="utf-8")
    (lore / "alpha" / "Delta.md").write_text("# D\n", encoding="utf-8")
    (lore / "Beta.md").write_text("# B\n", encoding="utf-8")
    (lore / "gamma.md").write_text("# G\n", encoding="utf-8")

    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    api_server._graph_indices.clear()
    return TestClient(api_server.app)


def _principal(monkeypatch: pytest.MonkeyPatch, pid: str = "tester") -> None:
    monkeypatch.setattr(api_server, "_resolve_principal", lambda request: api_server.EditPrincipal(pid))


def _confirm(client: TestClient, path: str, content: str,
             edit_id: str = "e1") -> tuple[dict, str]:
    full = api_server.MUNDOS_DIR / "test_mundo" / "lore" / path
    base_rev = hashlib.sha256(full.read_bytes()).hexdigest()
    resp = client.post(
        f"/api/test_mundo/lore/edit-confirmation?path={path}",
        json={"edit_id": edit_id, "base_revision": base_rev, "proposed_content": content},
    )
    assert resp.status_code == 200, resp.text
    return resp.json(), base_rev


def _gated_write(client: TestClient, path: str, content: str,
                 conf: dict, base_rev: str, edit_id: str = "e1"):
    return client.post(f"/api/test_mundo/lore/save?path={path}",
                       json={"content": content, "edit_id": edit_id,
                             "proposed_digest": conf["proposed_digest"],
                             "token": conf["token"], "base_revision": base_rev})


def _confirm_new(client: TestClient, path: str, content: str,
                 edit_id: str = "n1") -> dict:
    resp = client.post(
        f"/api/test_mundo/lore/edit-confirmation?path={path}",
        json={"edit_id": edit_id, "proposed_content": content, "kind": "new"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _gated_create(client: TestClient, path: str, content: str, conf: dict,
                  edit_id: str = "n1"):
    return client.post(f"/api/test_mundo/lore/create?path={path}",
                       json={"content": content, "edit_id": edit_id,
                             "proposed_digest": conf["proposed_digest"],
                             "token": conf["token"]})


class TestTreeContract:
    def test_tree_marks_directories_with_is_dir(self, client: TestClient):
        """Directories must carry is_dir=True so the frontend can expand them."""
        tree = client.get("/api/test_mundo/lore/tree").json()
        by_name = {node["name"]: node for node in tree}
        assert by_name["subdir"]["is_dir"] is True
        assert "children" in by_name["subdir"]
        assert by_name["00_inicio.md"]["is_dir"] is False
        # No node may carry the old broken 'type' field as the discriminator.
        for node in tree:
            assert "is_dir" in node

    def test_tree_includes_markdown_files(self, client: TestClient):
        tree = client.get("/api/test_mundo/lore/tree").json()
        names = [node["name"] for node in tree]
        assert "00_inicio.md" in names


class TestTreeOrdering:
    def test_dirs_before_files_case_insensitive(self, client_sorted: TestClient):
        """Directories come first; each group is sorted case-insensitively."""
        tree = client_sorted.get("/api/test_mundo/lore/tree").json()
        names = [node["name"] for node in tree]
        assert names == ["alpha", "Zeta", "Beta.md", "gamma.md"]

    def test_order_applies_recursively(self, client_sorted: TestClient):
        """Nested directories follow the same dirs-first, case-insensitive rule."""
        tree = client_sorted.get("/api/test_mundo/lore/tree").json()
        by_name = {node["name"]: node for node in tree}
        alpha = by_name["alpha"]
        inner_names = [node["name"] for node in alpha["children"]]
        assert inner_names == ["aleph", "Beta", "Delta.md", "gamma.md"]

    def test_dirs_without_files_are_omitted(self, client_sorted: TestClient):
        """Empty dirs and dirs without included files are still pruned."""
        (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "vacio").mkdir()
        tree = client_sorted.get("/api/test_mundo/lore/tree").json()
        names = [node["name"] for node in tree]
        assert "vacio" not in names


class TestSaveEndpoint:
    def test_save_writes_content(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, base_rev = _confirm(client, "00_inicio.md", "# Editado\n")
        resp = _gated_write(client, "00_inicio.md", "# Editado\n", conf, base_rev)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        saved = (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").read_text(encoding="utf-8")
        assert saved == "# Editado\n"

    def test_save_blocks_path_traversal(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/lore/save?path=../../secrets.txt",
                           json={"content": "x"})
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()


class TestDiffEndpoint:
    def test_diff_marks_added_removed_same(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/diff?path=00_inicio.md",
            json={"content": "# Inicio\n\nNueva línea\n"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["original_path"] == "00_inicio.md"
        types = [line["type"] for line in body["diff"]]
        assert "same" in types
        assert "added" in types
        for line in body["diff"]:
            assert line["type"] in ("same", "added", "removed")
            assert "text" in line

    def test_diff_identical_content_all_same(self, client: TestClient):
        content = (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").read_text(encoding="utf-8")
        resp = client.post(
            "/api/test_mundo/lore/diff?path=00_inicio.md",
            json={"content": content},
        )
        body = resp.json()
        assert len(body["diff"]) > 0
        assert all(line["type"] == "same" for line in body["diff"])


class TestTrashDelete:
    """S24-S27: delete_file moves to .papelera, never unlinks.

    v2 contract: every deleted item lives under
    ``.papelera/{section}/{entry_id12}/`` with a ``meta.json`` next to the
    original basename (file or directory tree) — no more ``{ts}_path`` names.
    """

    def _papelera_lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / ".papelera" / "lore"

    def _entry_dir(self, entry_id: str) -> Path:
        return self._papelera_lore() / entry_id

    def test_file_moves_to_papelera(self, client: TestClient):
        resp = client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert re.fullmatch(r"[0-9a-f]{12}", body["entry_id"])
        entry_dir = self._entry_dir(body["entry_id"])
        # entry_dir named as 12-hex id, holding meta.json + the original file
        assert entry_dir.name == body["entry_id"]
        assert entry_dir.is_dir()
        assert re.fullmatch(r"[0-9a-f]{12}", entry_dir.name)
        assert (entry_dir / "meta.json").is_file()
        assert (entry_dir / "00_inicio.md").read_text(encoding="utf-8").startswith("---")
        meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["entry_id"] == body["entry_id"]
        assert meta["original_path"] == "00_inicio.md"
        assert meta["kind"] == "file"
        assert meta["deleted_at"].endswith("Z")
        assert isinstance(meta["size"], int) and meta["size"] > 0
        # Original gone
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").exists()

    def test_dir_moves_recursively(self, client: TestClient):
        ciudades = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades"
        ciudades.mkdir()
        (ciudades / "alfa.md").write_text("# Alfa\n", encoding="utf-8")
        (ciudades / "beta.md").write_text("# Beta\n", encoding="utf-8")

        resp = client.delete("/api/test_mundo/lore/file?path=ciudades")
        assert resp.status_code == 200
        entry_dir = self._entry_dir(resp.json()["entry_id"])
        assert entry_dir.is_dir()
        # Directory content kept under the moved dir's basename inside entry_dir
        assert (entry_dir / "ciudades" / "alfa.md").read_text(encoding="utf-8") == "# Alfa\n"
        assert (entry_dir / "ciudades" / "beta.md").read_text(encoding="utf-8") == "# Beta\n"
        meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["kind"] == "dir"
        assert meta["original_path"] == "ciudades"
        assert not ciudades.exists()

    def test_subfolders_preserved(self, client: TestClient):
        planos = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades" / "planos"
        planos.mkdir(parents=True)
        (planos / "x.md").write_text("# X\n", encoding="utf-8")

        resp = client.delete("/api/test_mundo/lore/file?path=ciudades")
        assert resp.status_code == 200
        entry_dir = self._entry_dir(resp.json()["entry_id"])
        # Nested subfolders survive the move under entry_dir/{basename}/...
        assert (entry_dir / "ciudades" / "planos" / "x.md").read_text(encoding="utf-8") == "# X\n"
        assert (entry_dir / "meta.json").is_file()

    def test_rapid_deletes_get_distinct_entry_ids(self, client: TestClient):
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        (base / "a.md").write_text("# A\n", encoding="utf-8")
        (base / "b.md").write_text("# B\n", encoding="utf-8")

        r1 = client.delete("/api/test_mundo/lore/file?path=a.md")
        r2 = client.delete("/api/test_mundo/lore/file?path=b.md")
        assert r1.status_code == 200
        assert r2.status_code == 200
        e1, e2 = r1.json()["entry_id"], r2.json()["entry_id"]
        assert e1 != e2
        assert re.fullmatch(r"[0-9a-f]{12}", e1)
        assert re.fullmatch(r"[0-9a-f]{12}", e2)
        for eid in (e1, e2):
            assert (self._entry_dir(eid) / "meta.json").is_file()
            assert (self._entry_dir(eid) / "a.md").exists() or (self._entry_dir(eid) / "b.md").exists()
        # Exactly two entry dirs, each with a valid 12-hex name
        names = sorted(p.name for p in self._papelera_lore().iterdir())
        assert names == sorted([e1, e2])

    def test_tree_no_longer_lists_trashed_file(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert "00_inicio.md" not in [n["name"] for n in tree]

    def test_papelera_never_appears_in_tree(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        tree = client.get("/api/test_mundo/lore/tree").json()

        def walk(nodes):
            for node in nodes:
                assert ".papelera" not in node["path"]
                if node["is_dir"]:
                    walk(node["children"])

        walk(tree)

    def test_graph_search_excludes_trashed_entity(self, client: TestClient):
        before = client.get("/api/test_mundo/graph/search?q=inicio").json()
        assert any(h["path"] == "lore/00_inicio.md" for h in before)
        assert "test_mundo" in api_server._graph_indices

        assert client.delete("/api/test_mundo/lore/file?path=00_inicio.md").status_code == 200
        assert "test_mundo" not in api_server._graph_indices  # cache popped

        after = client.get("/api/test_mundo/graph/search?q=inicio").json()
        assert after == []
        assert all(h["path"] != "lore/00_inicio.md" for h in after)

    def test_missing_returns_404(self, client: TestClient):
        resp = client.delete("/api/test_mundo/lore/file?path=no_existe.md")
        assert resp.status_code == 404
        assert "no encontrado" in resp.json()["detail"].lower()

    def test_empty_path_returns_400(self, client: TestClient):
        resp = client.delete("/api/test_mundo/lore/file?path=")
        assert resp.status_code == 400


class TestErrorUpgrades:
    """D8/S35: create_file/save_file raise HTTPException with real statuses;
    slice 1B gates writes behind a trusted principal (seam fails closed)."""

    def test_create_existing_returns_409(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/lore/create?path=00_inicio.md", json={"content": "x"})
        assert resp.status_code == 409
        assert "ya existe" in resp.json()["detail"].lower()

    def test_create_invalid_section_returns_400(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/wiki/create?path=a.md", json={"content": "x"})
        assert resp.status_code == 400
        assert resp.json()["detail"]

    def test_create_missing_mundo_returns_404(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo_fantasma/lore/create?path=a.md", json={"content": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_create_traversal_returns_400(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/lore/create?path=../../x.md", json={"content": "x"})
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()

    def test_save_invalid_section_returns_400(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/wiki/save?path=a.md", json={"content": "x"})
        assert resp.status_code == 400

    def test_save_missing_mundo_returns_404(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo_fantasma/lore/save?path=a.md", json={"content": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_save_traversal_returns_400(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/lore/save?path=../../x.md", json={"content": "x"})
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()


class TestMoveEndpoint:
    """S15-S20: POST /api/{mundo}/move with independent path validation."""

    def test_rename_same_dir(self, client: TestClient):
        resp = client.post("/api/test_mundo/move", json={"from": "lore/00_inicio.md", "to": "lore/inicio.md"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "path": "lore/inicio.md"}
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "inicio.md").exists()
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").exists()

    def test_cross_section_recursive(self, client: TestClient):
        ciudades = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades"
        ciudades.mkdir()
        (ciudades / "planos").mkdir()
        (ciudades / "planos" / "x.md").write_text("# X\n", encoding="utf-8")

        resp = client.post("/api/test_mundo/move", json={"from": "lore/ciudades", "to": "personajes/ciudades"})
        assert resp.status_code == 200
        moved = api_server.MUNDOS_DIR / "test_mundo" / "personajes" / "ciudades"
        assert (moved / "planos" / "x.md").read_text(encoding="utf-8") == "# X\n"
        assert not ciudades.exists()

    def test_into_itself_400(self, client: TestClient):
        (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "c").mkdir()
        resp = client.post("/api/test_mundo/move", json={"from": "lore/c", "to": "lore/c/sub"})
        assert resp.status_code == 400
        assert "sí misma" in resp.json()["detail"]
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "c").is_dir()

    def test_to_exists_409(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/move",
            json={"from": "lore/00_inicio.md", "to": "lore/subdir/detalle.md"},
        )
        assert resp.status_code == 409
        assert "ya existe" in resp.json()["detail"].lower()
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").exists()

    def test_from_missing_404(self, client: TestClient):
        resp = client.post("/api/test_mundo/move", json={"from": "lore/no_existe.md", "to": "lore/x.md"})
        assert resp.status_code == 404

    def test_traversal_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/move", json={"from": "../secret.md", "to": "lore/x.md"})
        assert resp.status_code == 400
        resp2 = client.post("/api/test_mundo/move", json={"from": "lore/00_inicio.md", "to": "../fuera.md"})
        assert resp2.status_code == 400

    def test_invalid_section_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/move", json={"from": "lore/00_inicio.md", "to": "wiki/x.md"})
        assert resp.status_code == 400

    def test_deep_target_mkdir(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/move",
            json={"from": "lore/00_inicio.md", "to": "personajes/carpetas/nueva/x.md"},
        )
        assert resp.status_code == 200
        assert (api_server.MUNDOS_DIR / "test_mundo" / "personajes" / "carpetas" / "nueva" / "x.md").exists()

    def test_destination_referencias_200(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/move",
            json={"from": "lore/00_inicio.md", "to": "referencias/notas/x.md"},
        )
        assert resp.status_code == 200
        assert (api_server.MUNDOS_DIR / "test_mundo" / "referencias" / "notas" / "x.md").exists()

    def test_unicode_and_spaces(self, client: TestClient):
        bosque = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "El Bosque Oscuro"
        bosque.mkdir()
        (bosque / "Ñandú.md").write_text("# Ñ\n", encoding="utf-8")
        resp = client.post(
            "/api/test_mundo/move",
            json={"from": "lore/El Bosque Oscuro/Ñandú.md", "to": "lore/El Bosque Oscuro/Renombrado.md"},
        )
        assert resp.status_code == 200
        assert (bosque / "Renombrado.md").exists()
        assert not (bosque / "Ñandú.md").exists()

    def test_graph_cache_popped(self, client: TestClient):
        client.get("/api/test_mundo/graph/search?q=inicio")
        assert "test_mundo" in api_server._graph_indices
        resp = client.post("/api/test_mundo/move", json={"from": "lore/00_inicio.md", "to": "lore/inicio.md"})
        assert resp.status_code == 200
        assert "test_mundo" not in api_server._graph_indices

    def test_missing_fields_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/move", json={"from": "lore/00_inicio.md"})
        assert resp.status_code == 400


class TestDuplicateEndpoint:
    """S21-S23: POST /api/{mundo}/duplicate with server-side collision
    resolution and byte-identical copies."""

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def test_happy_creates_copia_with_identical_bytes(self, client: TestClient):
        content = "---\ntype: criatura\ntitle: Inicio\n---\n# Inicio\n"
        (self._lore() / "a.md").write_text(content, encoding="utf-8")
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/a.md"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "path": "lore/a-copia.md"}
        # Byte-identical to the source (S23)
        assert (self._lore() / "a-copia.md").read_bytes() == (self._lore() / "a.md").read_bytes()

    def test_collision_one_uses_suffix_2(self, client: TestClient):
        content = "# A\n"
        (self._lore() / "a.md").write_text(content, encoding="utf-8")
        (self._lore() / "a-copia.md").write_text("exists", encoding="utf-8")
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/a.md"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "path": "lore/a-2.md"}
        assert (self._lore() / "a-2.md").read_bytes() == (self._lore() / "a.md").read_bytes()

    def test_collision_two_uses_suffix_3(self, client: TestClient):
        content = "# A\n"
        (self._lore() / "a.md").write_text(content, encoding="utf-8")
        (self._lore() / "a-copia.md").write_text("1", encoding="utf-8")
        (self._lore() / "a-2.md").write_text("2", encoding="utf-8")
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/a.md"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "path": "lore/a-3.md"}

    def test_directory_returns_422(self, client: TestClient):
        (self._lore() / "carpeta").mkdir()
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/carpeta"})
        assert resp.status_code == 422
        assert "solo se pueden duplicar archivos" in resp.json()["detail"].lower()

    def test_missing_returns_404(self, client: TestClient):
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/no_existe.md"})
        assert resp.status_code == 404

    def test_traversal_returns_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/duplicate", json={"from": "../secret.md"})
        assert resp.status_code == 400

    def test_graph_cache_popped(self, client: TestClient):
        client.get("/api/test_mundo/graph/search?q=inicio")
        assert "test_mundo" in api_server._graph_indices
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/00_inicio.md"})
        assert resp.status_code == 200
        assert resp.json()["path"] == "lore/00_inicio-copia.md"
        assert "test_mundo" not in api_server._graph_indices


class TestCovers:
    """S29-S31: ?covers=true adds portada to file nodes; dirs null; field
    absent without the param; frontmatter value with body-image fallback."""

    def _world(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo"

    def _setup_media(self) -> Path:
        media = self._world() / "wiki" / "media"
        media.mkdir(parents=True)
        (media / "foto.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
        return media

    def test_valid_portada(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "a.md").write_text(
            "---\ntype: ficha\nportada: wiki/media/foto.jpg\n---\n# A\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "a.md")
        assert node["portada"] == "wiki/media/foto.jpg"

    def test_quoted_portada_value(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "f.md").write_text(
            '---\nportada: "wiki/media/foto.jpg"\n---\n# F\n', encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "f.md")
        assert node["portada"] == "wiki/media/foto.jpg"

    def test_portada_missing_falls_back_to_body_image(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "b.md").write_text(
            "---\nportada: wiki/media/inexistente.jpg\n---\n# B\n\n![alt](wiki/media/foto.jpg)\n",
            encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "b.md")
        assert node["portada"] == "wiki/media/foto.jpg"

    def test_body_image_without_portada(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "c.md").write_text(
            "# C\n\n![descripción](wiki/media/foto.jpg)\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "c.md")
        assert node["portada"] == "wiki/media/foto.jpg"

    def test_body_image_strips_fragment_suffix(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "d.md").write_text(
            "# D\n\n![x](wiki/media/foto.jpg#grande)\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "d.md")
        assert node["portada"] == "wiki/media/foto.jpg"

    def test_no_images_returns_null(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "e.md").write_text("# E\n\nSin imágenes\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "e.md")
        assert node["portada"] is None

    def test_directory_returns_null(self, client: TestClient):
        self._setup_media()
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        subdir = next(n for n in tree if n["is_dir"])
        assert subdir["portada"] is None

    def test_covers_false_field_absent(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "a.md").write_text(
            "---\nportada: wiki/media/foto.jpg\n---\n# A\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        node = next(n for n in tree if n["name"] == "a.md")
        assert "portada" not in node

    def test_covers_in_nested_files(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "subdir" / "g.md").write_text(
            "# G\n\n![x](wiki/media/foto.jpg)\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        subdir = next(n for n in tree if n["is_dir"])
        node = next(n for n in subdir["children"] if n["name"] == "g.md")
        assert node["portada"] == "wiki/media/foto.jpg"


class TestTreeStatus:
    """Item 14 follow-up: tree nodes expose the OKF frontmatter ``status``
    (draft|stable) — only known values, only for files, only from the
    leading frontmatter block (legacy body blocks never count)."""

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def _node(self, tree: list, name: str) -> dict:
        return next(n for n in tree if n["name"] == name)

    def test_file_with_draft_status(self, client: TestClient):
        (self._lore() / "d.md").write_text(
            "---\ntype: ficha\nstatus: draft\n---\n# D\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert self._node(tree, "d.md")["status"] == "draft"

    def test_file_with_stable_status(self, client: TestClient):
        (self._lore() / "s.md").write_text(
            "---\nstatus: stable\n---\n# S\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert self._node(tree, "s.md")["status"] == "stable"

    def test_quoted_status_value(self, client: TestClient):
        (self._lore() / "q.md").write_text(
            '---\nstatus: "draft"\n---\n# Q\n', encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert self._node(tree, "q.md")["status"] == "draft"

    def test_crlf_frontmatter_status(self, client: TestClient):
        (self._lore() / "crlf.md").write_bytes(
            "---\r\nstatus: draft\r\n---\r\n# CRLF\r\n".encode("utf-8"))
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert self._node(tree, "crlf.md")["status"] == "draft"

    def test_missing_status_field_absent(self, client: TestClient):
        (self._lore() / "plain.md").write_text("# Sin frontmatter\n", encoding="utf-8")
        (self._lore() / "fm.md").write_text(
            "---\ntype: ficha\n---\n# FM\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        for name in ("plain.md", "fm.md"):
            assert "status" not in self._node(tree, name)

    def test_unknown_status_field_absent(self, client: TestClient):
        (self._lore() / "synced.md").write_text(
            '---\nstatus: "synced"\n---\n# SY\n', encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert "status" not in self._node(tree, "synced.md")

    def test_legacy_body_blocks_are_ignored(self, client: TestClient):
        (self._lore() / "pert.md").write_text(
            "# Titulo\n\n---\nstatus: stable\n---\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert "status" not in self._node(tree, "pert.md")

    def test_directories_never_carry_status(self, client: TestClient):
        tree = client.get("/api/test_mundo/lore/tree").json()
        for node in tree:
            if node["is_dir"]:
                assert "status" not in node

    def test_status_survives_covers_param(self, client: TestClient):
        (self._lore() / "c.md").write_text(
            "---\nstatus: stable\n---\n# C\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = self._node(tree, "c.md")
        assert node["status"] == "stable"
        assert "portada" in node


class TestStatusEndpoint:
    """Item 14: POST /api/{mundo}/{section}/status rewrites ONLY the
    frontmatter `status:` line — CRLF-safe, never touching legacy body
    blocks (Pert.md regression)."""

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def test_updates_status_and_preserves_crlf_bytes(self, client: TestClient):
        content = "---\r\ntype: Personaje\r\ntitle: X\r\nstatus: draft\r\n---\r\n# Cuerpo\r\n"
        (self._lore() / "ficha.md").write_bytes(content.encode("utf-8"))
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "ficha.md", "status": "stable"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "path": "lore/ficha.md", "status": "stable"}
        # CRLF preserved byte-for-byte except the status line value
        expected = content.replace("status: draft\r\n", "status: stable\r\n")
        assert (self._lore() / "ficha.md").read_bytes() == expected.encode("utf-8")

    def test_legacy_body_block_untouched(self, client: TestClient):
        """Pert.md shape: `status` in the frontmatter AND a legacy
        `---\nstatus: draft\n---` block in the body — only the first block
        is rewritten."""
        content = (
            "---\ntype: Personaje\ntitle: Pert\nstatus: stable\n---\n\n"
            "---\nstatus: draft\n---\n\nCuerpo\n"
        )
        (self._lore() / "pert.md").write_text(content, encoding="utf-8")
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "pert.md", "status": "draft"},
        )
        assert resp.status_code == 200
        saved = (self._lore() / "pert.md").read_text(encoding="utf-8")
        # Frontmatter updated, legacy body block untouched
        assert saved == content.replace("status: stable\n", "status: draft\n", 1)
        assert saved.count("status: draft") == 2

    def test_legacy_body_block_untouched_crlf(self, client: TestClient):
        content = (
            "---\r\ntype: Personaje\r\ntitle: Pert\r\nstatus: stable\r\n---\r\n\r\n"
            "---\r\nstatus: draft\r\n---\r\n\r\nCuerpo\r\n"
        )
        (self._lore() / "pert.md").write_bytes(content.encode("utf-8"))
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "pert.md", "status": "stable"},
        )
        assert resp.status_code == 200
        saved = (self._lore() / "pert.md").read_bytes()
        assert saved.count(b"status: stable") == 1
        assert saved.count(b"status: draft") == 1  # legacy block untouched
        assert b"\r\n" in saved

    def test_inserts_status_line_when_field_missing(self, client: TestClient):
        content = "---\ntype: Nota\ntitle: X\n---\nCuerpo"
        (self._lore() / "nota.md").write_text(content, encoding="utf-8")
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "nota.md", "status": "draft"},
        )
        assert resp.status_code == 200
        saved = (self._lore() / "nota.md").read_text(encoding="utf-8")
        assert saved == "---\ntype: Nota\ntitle: X\nstatus: draft\n---\nCuerpo"

    def test_no_frontmatter_inserts_leading_block(self, client: TestClient):
        (self._lore() / "plain.md").write_text("# Plain\n", encoding="utf-8")
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "plain.md", "status": "draft"},
        )
        assert resp.status_code == 200
        saved = (self._lore() / "plain.md").read_text(encoding="utf-8")
        assert saved == "---\nstatus: draft\n---\n# Plain\n"

    def test_invalid_status_returns_422(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "00_inicio.md", "status": "published"},
        )
        assert resp.status_code == 422
        assert "estado inválido" in resp.json()["detail"].lower()
        # File untouched
        saved = (self._lore() / "00_inicio.md").read_text(encoding="utf-8")
        assert "status:" not in saved

    def test_missing_file_returns_404(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "no_existe.md", "status": "draft"},
        )
        assert resp.status_code == 404
        assert "no encontrado" in resp.json()["detail"].lower()

    def test_missing_mundo_returns_404(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo_fantasma/lore/status",
            json={"path": "a.md", "status": "draft"},
        )
        assert resp.status_code == 404

    def test_traversal_returns_400(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "../../secrets.md", "status": "draft"},
        )
        assert resp.status_code == 400

    def test_missing_path_field_returns_400(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"status": "draft"},
        )
        assert resp.status_code == 400


class TestAiAsk:
    def test_ai_ask_includes_file_context(self, client: TestClient):
        """The prompt sent to Hermes carries the wikilink and path of the open file."""
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        target.write_text("---\ntitle: Inicio\n---\nCuerpo\n", encoding="utf-8")
        with patch("api_server._run_hermes", new=AsyncMock(return_value="Hola desde Hermes")) as mock_run:
            resp = client.post(
                "/api/test_mundo/ai/ask",
                json={"prompt": "Hola", "section": "lore", "file_path": "00_inicio.md"},
            )
        assert resp.status_code == 200
        sent = mock_run.await_args.args[0]
        assert "[[Inicio]]" in sent
        assert "lore/00_inicio.md" in sent
        assert resp.json()["response"] == "Hola desde Hermes"

    def test_ai_ask_without_file_context(self, client: TestClient):
        """Without a file_path the prompt only carries the mundo prefix."""
        with patch("api_server._run_hermes", new=AsyncMock(return_value="ok")) as mock_run:
            resp = client.post(
                "/api/test_mundo/ai/ask",
                json={"prompt": "Hola"},
            )
        assert resp.status_code == 200
        sent = mock_run.await_args.args[0]
        assert "Ficha actual" not in sent
        assert "[Mundo: test_mundo]" in sent

    def test_activity_route_returns_sanitized_correlated_sse(self, client: TestClient, monkeypatch):
        class FakeAdapter:
            available = True
            capability = _activity_capability()

            def __init__(self):
                self.cancelled = []
                self.request_id = ""

            def start(self, request):
                assert request.request_id
                assert request.prompt == "[Mundo: test_mundo]\n\nHola"
                self.request_id = request.request_id
                return "run-1"

            async def events(self, run_id):
                assert run_id == "run-1"
                yield {
                    "event": "tool.started", "run_id": run_id, "tool": "graph_read",
                }
                yield {
                    "event": "tool.completed", "run_id": run_id, "tool": "graph_read",
                    "error": False,
                }
                yield {
                    "event": "run.completed", "run_id": run_id, "output": "safe answer",
                }

            def cancel(self, run_id):
                self.cancelled.append(run_id)

        adapter = FakeAdapter()
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
        response = client.post("/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: activity" in response.text
        assert '"response": "safe answer"' in response.text
        assert '"request_id": "activity-' in response.text
        assert '"path"' not in response.text
        assert "run-1" not in response.text

    @pytest.mark.parametrize("status", [404, 501, 503])
    def test_activity_route_unavailable_is_neutral_fallback(
        self, client: TestClient, monkeypatch, status: int
    ):
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", None)

        response = client.post("/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"})

        assert response.status_code == 503
        assert response.json() == {
            "detail": "Assistant activity is unavailable",
            "code": "activity_unavailable",
            "reason_code": "file_evidence_contract_unverified",
        }

    def test_activity_pre_acceptance_failure_does_not_leak_provider_error(
        self, client: TestClient, monkeypatch
    ):
        class FailingAdapter:
            available = True
            capability = _activity_capability()

            def start(self, request):
                raise RuntimeError("credential=secret /absolute/provider/path")

        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", FailingAdapter())
        response = client.post("/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"})

        assert response.status_code == 503
        assert response.json() == {
            "detail": "Assistant activity is unavailable",
            "code": "activity_unavailable",
            "reason_code": "provider_activity_unavailable",
        }

    def test_activity_partial_failure_preserves_answer_and_cancels_on_timeout(
        self, client: TestClient, monkeypatch
    ):
        class PartialAdapter:
            available = True
            capability = _activity_capability()

            def __init__(self):
                self.cancelled = []
                self.request_id = ""

            def start(self, request):
                self.request_id = request.request_id
                return "run-1"

            async def events(self, run_id):
                yield {
                    "event": "message.delta", "run_id": run_id,
                    "delta": "preserve this answer",
                }
                await asyncio.sleep(0.05)
                yield {"event": "run.completed", "run_id": run_id, "output": "preserve this answer"}

            def cancel(self, run_id):
                self.cancelled.append(run_id)

        adapter = PartialAdapter()
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
        monkeypatch.setattr(api_server, "ACTIVITY_EVENT_TIMEOUT_SECONDS", 0.01)
        response = client.post("/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"})

        assert response.status_code == 200
        assert '"response": "preserve this answer"' in response.text
        assert '"status": "unknown"' in response.text
        assert adapter.cancelled == ["run-1"]

    def test_legacy_ai_ask_contract_is_unchanged(self, client: TestClient):
        with patch("api_server._run_hermes", new=AsyncMock(return_value="legacy answer")):
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": "Hola"})

        assert response.status_code == 200
        assert response.json() == {"response": "legacy answer"}


class TestMundoValidation:
    """Audit 07-30 (item 13): every endpoint taking {mundo} must reject
    worlds that do not exist and block mundo-level traversal.

    ``%2e%2e`` is URL-encoded ``..`` — plain ``/api/../...`` is normalized
    away by clients, but encoded dots reach the endpoint verbatim, so the
    server must validate the mundo param itself. Established patterns:
    mutations raise 404 "Mundo no encontrado"; GET/list endpoints keep
    their soft-empty contract.
    """

    ENC_DOTS = "%2e%2e"

    def _tmp_root(self) -> Path:
        return api_server.MUNDOS_DIR.parent

    # -- world existence: GET/list keep their soft contract ------------------

    def test_tree_missing_mundo_returns_empty(self, client: TestClient):
        assert client.get("/api/mundo_fantasma/lore/tree").json() == []

    def test_get_file_missing_mundo_soft_error(self, client: TestClient):
        resp = client.get("/api/mundo_fantasma/lore/file?path=a.md")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_list_media_missing_mundo_empty(self, client: TestClient):
        resp = client.get("/api/mundo_fantasma/media/list")
        assert resp.json() == {"images": [], "total": 0}

    def test_graph_search_missing_mundo_empty(self, client: TestClient):
        assert client.get("/api/mundo_fantasma/graph/search?q=a").json() == []

    def test_graph_status_missing_mundo_zeroed(self, client: TestClient):
        assert client.get("/api/mundo_fantasma/graph/status").json() == {
            "node_count": 0,
            "link_count": 0,
            "indexed": False,
        }

    # -- world existence: mutations raise 404 --------------------------------

    def test_diff_missing_mundo_404(self, client: TestClient):
        resp = client.post("/api/mundo_fantasma/lore/diff?path=a.md", json={"content": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_diff_invalid_section_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/wiki/diff?path=a.md", json={"content": "x"})
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Sección inválida"

    def test_delete_missing_mundo_404(self, client: TestClient):
        resp = client.delete("/api/mundo_fantasma/lore/file?path=a.md")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_move_missing_mundo_404(self, client: TestClient):
        resp = client.post("/api/mundo_fantasma/move", json={"from": "lore/a.md", "to": "lore/b.md"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_duplicate_missing_mundo_404(self, client: TestClient):
        resp = client.post("/api/mundo_fantasma/duplicate", json={"from": "lore/a.md"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_upload_missing_mundo_404_never_creates_world(
        self, client: TestClient, jpeg_bytes: bytes
    ):
        resp = client.post(
            "/api/mundo_fantasma/media/upload",
            files={"file": ("x.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"
        assert not (api_server.MUNDOS_DIR / "mundo_fantasma").exists()

    def test_delete_media_missing_mundo_404(self, client: TestClient):
        resp = client.delete("/api/mundo_fantasma/media?path=wiki/media/x.jpg")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    # -- mundo-level traversal (%2e%2e = '..') --------------------------------

    def test_tree_mundo_traversal_empty_never_leaks(self, client: TestClient):
        outside = self._tmp_root() / "lore"
        outside.mkdir(exist_ok=True)
        (outside / "secreto.md").write_text("# SECRETO\n", encoding="utf-8")
        resp = client.get(f"/api/{self.ENC_DOTS}/lore/tree")
        assert resp.status_code == 200
        assert all(n["name"] != "secreto.md" for n in resp.json())

    def test_save_mundo_traversal_404_never_writes(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        outside = self._tmp_root() / "lore"
        outside.mkdir(exist_ok=True)
        resp = client.post(
            f"/api/{self.ENC_DOTS}/lore/save?path=pwned.md", json={"content": "x"}
        )
        assert resp.status_code == 404
        assert not (outside / "pwned.md").exists()

    def test_create_mundo_traversal_404_never_writes(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post(
            f"/api/{self.ENC_DOTS}/lore/create?path=pwned.md", json={"content": "x"}
        )
        assert resp.status_code == 404
        assert not (self._tmp_root() / "lore" / "pwned.md").exists()

    def test_status_mundo_traversal_404_never_rewrites(self, client: TestClient):
        outside = self._tmp_root() / "lore"
        outside.mkdir(exist_ok=True)
        (outside / "secreto.md").write_text("# SECRETO\n", encoding="utf-8")
        resp = client.post(
            f"/api/{self.ENC_DOTS}/lore/status",
            json={"path": "secreto.md", "status": "stable"},
        )
        assert resp.status_code == 404
        saved = (outside / "secreto.md").read_text(encoding="utf-8")
        assert "status:" not in saved

    def test_delete_mundo_traversal_404_never_moves(self, client: TestClient):
        outside = self._tmp_root() / "lore"
        outside.mkdir(exist_ok=True)
        (outside / "secreto.md").write_text("# SECRETO\n", encoding="utf-8")
        resp = client.delete(f"/api/{self.ENC_DOTS}/lore/file?path=secreto.md")
        assert resp.status_code == 404
        assert (outside / "secreto.md").exists()

    def test_upload_mundo_traversal_404_never_writes(
        self, client: TestClient, jpeg_bytes: bytes
    ):
        resp = client.post(
            f"/api/{self.ENC_DOTS}/media/upload",
            files={"file": ("y.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert resp.status_code == 404
        assert not (self._tmp_root() / "wiki" / "media" / "y.jpg").exists()

    def test_delete_media_mundo_traversal_404_never_deletes(
        self, client: TestClient, jpeg_bytes: bytes
    ):
        outside = self._tmp_root() / "wiki" / "media"
        outside.mkdir(parents=True, exist_ok=True)
        (outside / "z.jpg").write_bytes(jpeg_bytes)
        resp = client.delete(f"/api/{self.ENC_DOTS}/media?path=wiki/media/z.jpg")
        assert resp.status_code == 404
        assert (outside / "z.jpg").exists()

    def test_get_media_mundo_traversal_400(self, client: TestClient):
        resp = client.get(f"/api/{self.ENC_DOTS}/media?path=wiki/media/foto.jpg")
        assert resp.status_code == 400

    def test_graph_search_mundo_traversal_empty(self, client: TestClient):
        assert client.get(f"/api/{self.ENC_DOTS}/graph/search?q=a").json() == []

    def test_graph_entity_mundo_traversal_error(self, client: TestClient):
        resp = client.get(f"/api/{self.ENC_DOTS}/graph/entity?name=X")
        assert "error" in resp.json()


class TestTrashList:
    """GET /api/{mundo}/papelera — list trash entries across all sections."""

    def _papelera(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / ".papelera"

    def test_list_empty_returns_empty(self, client: TestClient):
        resp = client.get("/api/test_mundo/papelera")
        assert resp.status_code == 200
        assert resp.json() == {"entries": []}

    def test_list_after_delete_shows_entry(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        entries = client.get("/api/test_mundo/papelera").json()["entries"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["original_path"] == "00_inicio.md"
        assert entry["kind"] == "file"
        assert entry["deleted_at"].endswith("Z")

    def test_list_includes_section_and_entry_id(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        personajes = api_server.MUNDOS_DIR / "test_mundo" / "personajes"
        personajes.mkdir(parents=True)
        (personajes / "p.md").write_text("# P\n", encoding="utf-8")
        client.delete("/api/test_mundo/personajes/file?path=p.md")

        entries = client.get("/api/test_mundo/papelera").json()["entries"]
        by_section = {e["section"]: e for e in entries}
        assert set(by_section) == {"lore", "personajes"}
        for eid in (by_section["lore"]["entry_id"], by_section["personajes"]["entry_id"]):
            assert re.fullmatch(r"[0-9a-f]{12}", eid)

    def test_list_excludes_corrupt_meta(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        # Entry dir whose meta.json is not valid JSON must be skipped by the list
        bogus = self._papelera() / "lore" / "deadbeefdead"
        bogus.mkdir(parents=True)
        (bogus / "meta.json").write_text("{not json", encoding="utf-8")

        entries = client.get("/api/test_mundo/papelera").json()["entries"]
        ids = [e["entry_id"] for e in entries]
        assert "deadbeefdead" not in ids
        assert len(entries) == 1


class TestTrashRestore:
    """POST /api/{mundo}/papelera/restore — move an entry back to its path."""

    def _papelera(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / ".papelera"

    def test_restore_roundtrip_restores_file(self, client: TestClient):
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        resp = client.post(
            "/api/test_mundo/papelera/restore",
            json={"entry_id": entry_id, "section": "lore"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"restored_to": "lore/00_inicio.md", "entry_id": entry_id}
        # File back with original content, entry dir gone
        restored = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        assert restored.read_text(encoding="utf-8").startswith("---")
        assert not (self._papelera() / "lore" / entry_id).exists()

    def test_restore_to_dest_collision_dedups(self, client: TestClient):
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        # Original path reoccupied with different content -> restore dedups
        (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").write_text(
            "nuevo contenido\n", encoding="utf-8")

        resp = client.post(
            "/api/test_mundo/papelera/restore",
            json={"entry_id": entry_id, "section": "lore"},
        )
        assert resp.status_code == 200
        assert resp.json()["restored_to"] == "lore/00_inicio-copia.md"
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio-copia.md").read_text(
            encoding="utf-8").startswith("---")
        # Occupier untouched
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").read_text(
            encoding="utf-8") == "nuevo contenido\n"

    def test_restore_missing_entry_404(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/papelera/restore",
            json={"entry_id": "000000000000", "section": "lore"},
        )
        assert resp.status_code == 404
        assert "no encontrada" in resp.json()["detail"].lower()

    def test_restore_missing_section_400(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/papelera/restore",
            json={"entry_id": "000000000000", "section": "wiki"},
        )
        assert resp.status_code == 400
        assert "sección requerida" in resp.json()["detail"].lower()

    def test_restore_dir_roundtrip(self, client: TestClient):
        ciudades = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades"
        ciudades.mkdir()
        (ciudades / "planos").mkdir()
        (ciudades / "planos" / "x.md").write_text("# X\n", encoding="utf-8")
        (ciudades / "alfa.md").write_text("# Alfa\n", encoding="utf-8")
        entry_id = client.delete("/api/test_mundo/lore/file?path=ciudades").json()["entry_id"]

        resp = client.post(
            "/api/test_mundo/papelera/restore",
            json={"entry_id": entry_id, "section": "lore"},
        )
        assert resp.status_code == 200
        assert resp.json()["restored_to"] == "lore/ciudades"
        restored = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades"
        assert (restored / "planos" / "x.md").read_text(encoding="utf-8") == "# X\n"
        assert (restored / "alfa.md").read_text(encoding="utf-8") == "# Alfa\n"
        assert not (self._papelera() / "lore" / entry_id).exists()


class TestTrashPurge:
    """DELETE /api/{mundo}/papelera — remove one entry or empty the whole bin."""

    def _papelera(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / ".papelera"

    def test_purge_individual_removes_entry(self, client: TestClient):
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        resp = client.delete(f"/api/test_mundo/papelera?entry_id={entry_id}&section=lore")
        assert resp.status_code == 200
        assert resp.json() == {"purged": entry_id}
        assert not (self._papelera() / "lore" / entry_id).exists()
        assert client.get("/api/test_mundo/papelera").json() == {"entries": []}

    def test_purge_missing_entry_404(self, client: TestClient):
        resp = client.delete("/api/test_mundo/papelera?entry_id=000000000000&section=lore")
        assert resp.status_code == 404
        assert "no encontrada" in resp.json()["detail"].lower()

    def test_purge_all_empties_bin(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        client.delete("/api/test_mundo/lore/file?path=subdir/detalle.md")
        resp = client.delete("/api/test_mundo/papelera")
        assert resp.status_code == 200
        assert resp.json() == {"purged": "all", "entries": 2}
        assert not self._papelera().exists()
        assert client.get("/api/test_mundo/papelera").json() == {"entries": []}

    def test_purge_all_when_empty_returns_zero(self, client: TestClient):
        resp = client.delete("/api/test_mundo/papelera")
        assert resp.status_code == 200
        assert resp.json() == {"purged": "all", "entries": 0}


class TestTrashTTL:
    """Item 8 Phase 1: lazy TTL purge (30 days) triggered by GET /papelera.

    Boundary: an entry is expired when ``deleted_at < now - 30d`` (strictly
    less). Equal to the threshold → kept. Malformed/missing meta.json is
    skipped, never crashes the purge nor the list.
    """

    def _papelera(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / ".papelera"

    def _patch_deleted_at(self, entry_dir: Path, deleted_at: datetime) -> None:
        """Rewrite meta.json's deleted_at as ISO-8601 UTC ending in 'Z'."""
        meta_path = entry_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["deleted_at"] = deleted_at.isoformat().replace("+00:00", "Z")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    def test_ttl_purges_expired_on_list(self, client: TestClient):
        """deleted_at 31 days ago → purged before the list is returned."""
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        entry_dir = self._papelera() / "lore" / entry_id
        self._patch_deleted_at(entry_dir, datetime.now(timezone.utc) - timedelta(days=31))

        resp = client.get("/api/test_mundo/papelera")
        ids = [e["entry_id"] for e in resp.json()["entries"]]
        assert entry_id not in ids
        assert not entry_dir.exists()
        assert resp.json().get("purged") == 1

    def test_ttl_preserves_fresh_on_list(self, client: TestClient):
        """deleted_at = now (default delete flow) → kept."""
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        entry_dir = self._papelera() / "lore" / entry_id

        resp = client.get("/api/test_mundo/papelera")
        ids = [e["entry_id"] for e in resp.json()["entries"]]
        assert entry_id in ids
        assert entry_dir.exists()
        assert resp.json().get("purged") is None

    def test_ttl_boundary_exactly_30_days(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        """Boundary (MANDATORY): deleted_at == now - 30d exactly is KEPT.

        Expired means ``deleted_at < threshold`` (strictly). At exactly 30
        days the entry survives; at 30 days + 1 second it is purged. Time
        is frozen so the purge threshold matches the written value exactly,
        making the equality branch deterministic.
        """
        frozen = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        class _FrozenDateTime(api_server.datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen

        monkeypatch.setattr(api_server, "datetime", _FrozenDateTime)

        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        entry_dir = self._papelera() / "lore" / entry_id
        self._patch_deleted_at(entry_dir, frozen - timedelta(days=30))

        resp = client.get("/api/test_mundo/papelera")
        ids = [e["entry_id"] for e in resp.json()["entries"]]
        assert entry_id in ids
        assert entry_dir.exists()
        assert resp.json().get("purged") is None

    def test_ttl_malformed_meta_skipped(self, client: TestClient):
        """Unreadable meta.json → entry skipped (kept), no crash, nothing purged."""
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        entry_dir = self._papelera() / "lore" / entry_id
        (entry_dir / "meta.json").write_text("{not json", encoding="utf-8")

        resp = client.get("/api/test_mundo/papelera")
        assert resp.status_code == 200
        assert entry_dir.exists()
        assert resp.json().get("purged") is None

    def test_ttl_missing_meta_skipped(self, client: TestClient):
        """Entry dir with NO meta.json → skipped (kept), no crash."""
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        entry_dir = self._papelera() / "lore" / entry_id
        (entry_dir / "meta.json").unlink()

        resp = client.get("/api/test_mundo/papelera")
        assert resp.status_code == 200
        assert entry_dir.exists()
        assert resp.json().get("purged") is None


class TestFileRevision:
    """Slice 1A (task 1.1): GET /api/{mundo}/{section}/file returns
    ``revision`` = SHA-256 of the file's exact bytes on disk.

    The revision fingerprints raw bytes — never the newline-normalized text
    returned as ``content`` — so a future editor can detect stale bases
    before confirming a write.
    """

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def test_get_file_returns_sha256_revision(self, client: TestClient):
        resp = client.get("/api/test_mundo/lore/file?path=00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert "revision" in body
        assert len(body["revision"]) == 64
        expected = hashlib.sha256((self._lore() / "00_inicio.md").read_bytes()).hexdigest()
        assert body["revision"] == expected
        assert body["content"].startswith("---")
        assert isinstance(body["size"], int) and body["size"] > 0

    def test_revision_tracks_content_change(self, client: TestClient):
        target = self._lore() / "00_inicio.md"
        r1 = client.get("/api/test_mundo/lore/file?path=00_inicio.md").json()["revision"]
        target.write_text("# Cambiado\n", encoding="utf-8")
        r2 = client.get("/api/test_mundo/lore/file?path=00_inicio.md").json()["revision"]
        assert r1 != r2
        # Hash of the exact on-disk bytes (text writes may translate newlines).
        assert r2 == hashlib.sha256(target.read_bytes()).hexdigest()

    def test_revision_hashes_exact_bytes_not_normalized_text(self, client: TestClient):
        """CRLF file: read_text() normalizes line endings, but the revision
        must fingerprint the exact bytes on disk."""
        target = self._lore() / "crlf.md"
        target.write_bytes(b"# CRLF\r\nsegunda\r\n")
        body = client.get("/api/test_mundo/lore/file?path=crlf.md").json()
        assert body["revision"] == hashlib.sha256(b"# CRLF\r\nsegunda\r\n").hexdigest()
        # Sanity: the text layer normalizes, the revision layer must not.
        assert "\r" not in body["content"]

    def test_missing_file_keeps_soft_error_contract(self, client: TestClient):
        resp = client.get("/api/test_mundo/lore/file?path=no_existe.md")
        assert resp.status_code == 200
        assert "error" in resp.json()
        assert "revision" not in resp.json()


class TestReadPathAuthorization:
    """Slice 1A (tasks 1.3-1.4): centralized world/section/path authorization
    on read and proposal-adjacent boundaries.

    Traversal, sibling-world prefix collisions, symlink escapes, invalid
    sections, and internal ``.papelera``/``.history`` targets are all denied
    through the shared resolver — with zero disclosure and zero mutation.
    """

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def _assert_soft_denial(self, resp, marker: str) -> None:
        """get_file denies through its soft-error envelope (no disclosure)."""
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body
        assert marker not in json.dumps(body)

    def test_traversal_read_denied_with_zero_mutation(self, client: TestClient, tmp_path):
        escape = tmp_path / "mundos" / "secrets.txt"
        escape.write_text("TOP SECRET\n", encoding="utf-8")
        resp = client.get("/api/test_mundo/lore/file?path=../../secrets.txt")
        self._assert_soft_denial(resp, "TOP SECRET")
        # Zero mutation: the escape target is untouched and no file appeared
        # inside the world.
        assert escape.read_text(encoding="utf-8") == "TOP SECRET\n"
        assert not (self._lore() / "secrets.txt").exists()

    def test_sibling_world_prefix_collision_denied(self, client: TestClient):
        """The old weak ``startswith(root)`` check treats
        ``mundos/test_mundo2/...`` as a child of ``mundos/test_mundo``
        (string prefix). The centralized resolver must reject the sibling."""
        sibling = api_server.MUNDOS_DIR / "test_mundo2" / "lore"
        sibling.mkdir(parents=True)
        (sibling / "x.md").write_text("SIBLING SECRET\n", encoding="utf-8")
        resp = client.get("/api/test_mundo/lore/file?path=../../test_mundo2/lore/x.md")
        self._assert_soft_denial(resp, "SIBLING SECRET")
        # Zero mutation: sibling untouched.
        assert (sibling / "x.md").read_text(encoding="utf-8") == "SIBLING SECRET\n"

    def test_symlink_escape_read_denied(self, client: TestClient, tmp_path):
        outside = tmp_path / "outside.md"
        outside.write_text("OUTSIDE SECRET\n", encoding="utf-8")
        link = self._lore() / "escape.md"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("symlinks not permitted on this platform")
        try:
            resp = client.get("/api/test_mundo/lore/file?path=escape.md")
            self._assert_soft_denial(resp, "OUTSIDE SECRET")
            assert outside.read_text(encoding="utf-8") == "OUTSIDE SECRET\n"
        finally:
            if link.is_symlink():
                link.unlink()

    def test_papelera_target_denied(self, client: TestClient):
        trashed = api_server.MUNDOS_DIR / "test_mundo" / ".papelera" / "lore" / "x.md"
        trashed.parent.mkdir(parents=True)
        trashed.write_text("TRASHED SECRET\n", encoding="utf-8")
        for p in ("../.papelera/lore/x.md", ".papelera/lore/x.md"):
            resp = client.get(f"/api/test_mundo/lore/file?path={p}")
            self._assert_soft_denial(resp, "TRASHED SECRET")

    def test_history_target_denied(self, client: TestClient):
        snap = api_server.MUNDOS_DIR / "test_mundo" / ".history" / "lore" / "x.md"
        snap.parent.mkdir(parents=True)
        snap.write_text("SNAPSHOT SECRET\n", encoding="utf-8")
        for p in ("../.history/lore/x.md", ".history/lore/x.md"):
            resp = client.get(f"/api/test_mundo/lore/file?path={p}")
            self._assert_soft_denial(resp, "SNAPSHOT SECRET")

    def test_invalid_section_denied(self, client: TestClient):
        resp = client.get("/api/test_mundo/wiki/file?path=x.md")
        assert resp.status_code == 200
        body = resp.json()
        # Denied via the soft-error envelope: no content, no revision —
        # only the client's own requested path may be echoed back.
        assert "error" in body
        assert "revision" not in body
        assert "content" not in body

    def test_mundo_traversal_read_denied_never_leaks(self, client: TestClient, tmp_path):
        outside = tmp_path / "lore"
        outside.mkdir(exist_ok=True)
        (outside / "secreto.md").write_text("# SECRETO\n", encoding="utf-8")
        resp = client.get("/api/%2e%2e/lore/file?path=secreto.md")
        self._assert_soft_denial(resp, "SECRETO")

    def test_ai_ask_traversal_never_leaks_content(self, client: TestClient, tmp_path):
        """Proposal-adjacent read: ai/ask must not inject the content of an
        escaped target into the Hermes prompt."""
        escape = tmp_path / "mundos" / "secrets.md"
        escape.write_text("AI LEAK SECRET\n", encoding="utf-8")
        with patch("api_server._run_hermes", new=AsyncMock(return_value="ok")) as mock_run:
            resp = client.post(
                "/api/test_mundo/ai/ask",
                json={"prompt": "Hola", "section": "lore", "file_path": "../../secrets.md"},
            )
        assert resp.status_code == 200
        sent = mock_run.await_args.args[0]
        assert "AI LEAK SECRET" not in sent
        assert escape.read_text(encoding="utf-8") == "AI LEAK SECRET\n"


class TestEditPrincipalSeam:
    """Slice 1A (task 1.2): trusted EditPrincipal seam.

    Fails closed until a deployment supplies trusted auth/session middleware,
    and never promotes caller-supplied identity (headers/body) to a principal.
    """

    def test_resolve_principal_fails_closed_by_default(self):
        assert api_server._resolve_principal(None) is None

    def test_resolve_principal_ignores_client_supplied_identity(self):
        class _FakeRequest:
            def __init__(self, headers: dict):
                self.headers = headers

        req = _FakeRequest({
            "x-edit-principal": "admin",
            "x-user": "alice",
            "authorization": "Bearer forged-token",
        })
        assert api_server._resolve_principal(req) is None

    def test_edit_principal_requires_id(self):
        with pytest.raises(ValueError):
            api_server.EditPrincipal("")
        with pytest.raises(ValueError):
            api_server.EditPrincipal("   ")
        p = api_server.EditPrincipal("session-42")
        assert p.id == "session-42"
        assert p.label == ""

    def test_seam_pluggable_for_deployment_middleware(self, monkeypatch: pytest.MonkeyPatch):
        """Once a deployment wires trusted middleware, the seam returns an
        EditPrincipal — proving the plug contract for the confirmation gate
        (slice 1B) and for fail-closed callers."""
        def fake_middleware(request):
            return api_server.EditPrincipal("session-42", label="deployment-user")

        monkeypatch.setattr(api_server, "_resolve_principal", fake_middleware)
        principal = api_server._resolve_principal(object())
        assert isinstance(principal, api_server.EditPrincipal)
        assert principal.id == "session-42"
        assert principal.label == "deployment-user"


class TestLocalDevelopmentAuth:
    """Explicit loopback-only session provider for local editing tests."""

    def test_disabled_mode_is_visible_and_remains_fail_closed(self, client: TestClient):
        status = client.get("/api/auth/local-dev/session")
        assert status.status_code == 200
        assert status.json() == {
            "mode": "disabled",
            "enabled": False,
            "authenticated": False,
            "label": None,
        }
        assert client.post("/api/auth/local-dev/session").status_code == 403
        assert client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={"edit_id": "e1", "base_revision": "0" * 64, "proposed_content": "x"},
        ).status_code == 401
        assert client.post(
            "/api/test_mundo/lore/save?path=00_inicio.md",
            json={"content": "x"},
        ).status_code == 401

    def test_loopback_start_status_logout_and_cookie_contract(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")

        started = client.post(
            "/api/auth/local-dev/session",
            json={"principal_id": "caller-controlled"},
        )
        assert started.status_code == 200
        assert started.json() == {
            "mode": "local-dev",
            "enabled": True,
            "authenticated": True,
            "label": "Local development user",
        }
        assert "token" not in started.json()
        assert "principal_id" not in started.json()
        cookie = started.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=lax" in cookie

        assert client.get("/api/auth/local-dev/session").json()["authenticated"] is True
        confirmation, base_revision = _confirm(client, "00_inicio.md", "# Local edit\n")
        assert confirmation["token"]
        saved = _gated_write(client, "00_inicio.md", "# Local edit\n", confirmation, base_revision)
        assert saved.status_code == 200

        history = client.get("/api/test_mundo/history?path=lore/00_inicio.md")
        assert history.status_code == 200
        entry = history.json()["entries"][0]
        current_revision = hashlib.sha256(
            (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").read_bytes()
        ).hexdigest()
        restore_confirmation = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={
                "edit_id": "restore-1",
                "kind": "restore",
                "base_revision": current_revision,
                "snapshot_id": entry["snapshot_id"],
                "proposed_content": entry["content"],
            },
        )
        assert restore_confirmation.status_code == 200
        restored = client.post(
            "/api/test_mundo/history/restore",
            json={
                "path": "lore/00_inicio.md",
                "snapshot_id": entry["snapshot_id"],
                "edit_id": "restore-1",
                "base_revision": current_revision,
                "content": entry["content"],
                "proposed_digest": restore_confirmation.json()["proposed_digest"],
                "token": restore_confirmation.json()["token"],
            },
        )
        assert restored.status_code == 200

        logged_out = client.delete("/api/auth/local-dev/session")
        assert logged_out.status_code == 200
        assert logged_out.json()["authenticated"] is False
        assert client.get("/api/auth/local-dev/session").json()["authenticated"] is False
        assert client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={"edit_id": "e2", "base_revision": "0" * 64, "proposed_content": "x"},
        ).status_code == 401

    def test_non_loopback_clients_cannot_start_use_or_logout(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
        non_loopback = TestClient(api_server.app, client=("192.0.2.10", 50001))

        assert non_loopback.post("/api/auth/local-dev/session").status_code == 403
        assert non_loopback.get("/api/auth/local-dev/session").status_code == 403
        assert non_loopback.delete("/api/auth/local-dev/session").status_code == 403
        assert client.get("/api/auth/local-dev/session").status_code == 200

    def test_confirmation_and_save_are_bound_to_the_issuing_session(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
        first = TestClient(api_server.app, client=("127.0.0.1", 50002))
        second = TestClient(api_server.app, client=("127.0.0.1", 50003))
        assert first.post("/api/auth/local-dev/session").status_code == 200
        assert second.post("/api/auth/local-dev/session").status_code == 200

        confirmation, base_revision = _confirm(first, "00_inicio.md", "# Bound edit\n")
        response = _gated_write(second, "00_inicio.md", "# Bound edit\n", confirmation, base_revision)
        assert response.status_code == 403
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").read_text(
            encoding="utf-8"
        ).startswith("---")


class TestConfirmationStore:
    """Slice 1B (tasks 1.5 + 2.2): hashed, single-use, short-TTL confirmations."""

    def test_confirmation_requires_principal(self, client: TestClient):
        resp = client.post("/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
                           json={"edit_id": "e1", "base_revision": "0" * 64, "proposed_content": "x"})
        assert resp.status_code == 401

    def test_issue_returns_token_and_proposed_digest(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, _ = _confirm(client, "00_inicio.md", "# Nuevo\n")
        assert conf["token"] and conf["expires_at"]
        assert conf["proposed_digest"] == hashlib.sha256("# Nuevo\n".encode()).hexdigest()
        # Stored hashed only: the raw token never appears as a store key.
        assert conf["token"] not in api_server._confirmation_store
        assert api_server._hash_token(conf["token"]) in api_server._confirmation_store

    def test_confirm_stale_base_409_zero_mutation(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        resp = client.post("/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
                           json={"edit_id": "e1", "base_revision": "0" * 64, "proposed_content": "x"})
        assert resp.status_code == 409
        assert target.read_text(encoding="utf-8").startswith("---")

    def test_expired_token_rejected(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, base_rev = _confirm(client, "00_inicio.md", "# Vencido\n")
        api_server._confirmation_store[api_server._hash_token(conf["token"])][
            "expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        resp = _gated_write(client, "00_inicio.md", "# Vencido\n", conf, base_rev)
        assert resp.status_code == 403
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
                ).read_text(encoding="utf-8").startswith("---")

    def test_mismatched_edit_id_rejected(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, base_rev = _confirm(client, "00_inicio.md", "# A\n", edit_id="eA")
        resp = _gated_write(client, "00_inicio.md", "# A\n", conf, base_rev, edit_id="eB")
        assert resp.status_code == 403

    def test_mismatched_principal_rejected(self, client: TestClient, monkeypatch):
        _principal(monkeypatch, pid="alice")
        conf, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        _principal(monkeypatch, pid="bob")
        resp = _gated_write(client, "00_inicio.md", "# A\n", conf, base_rev)
        assert resp.status_code == 403


class TestGatedPersistence:
    """Slice 1B (task 2.1): save/create fail closed without valid proof."""

    def test_save_without_principal_401(self, client: TestClient):
        resp = client.post("/api/test_mundo/lore/save?path=00_inicio.md",
                           json={"content": "x", "edit_id": "e1", "token": "t",
                                 "proposed_digest": "0" * 64, "base_revision": "0" * 64})
        assert resp.status_code == 401

    def test_save_missing_token_400_zero_mutation(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        before = target.read_bytes()
        resp = client.post("/api/test_mundo/lore/save?path=00_inicio.md",
                           json={"content": "# HACKED\n", "edit_id": "e1",
                                 "base_revision": hashlib.sha256(before).hexdigest()})
        assert resp.status_code == 400
        assert target.read_bytes() == before

    def test_save_success_writes(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, base_rev = _confirm(client, "00_inicio.md", "# Editado\n")
        resp = _gated_write(client, "00_inicio.md", "# Editado\n", conf, base_rev)
        assert resp.status_code == 200
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        assert target.read_text(encoding="utf-8") == "# Editado\n"

    def test_save_stale_base_409_zero_mutation(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        conf, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        target.write_text("# Cambio externo\n", encoding="utf-8")
        resp = _gated_write(client, "00_inicio.md", "# A\n", conf, base_rev)
        assert resp.status_code == 409
        assert "base" in resp.json()["detail"].lower()
        assert target.read_text(encoding="utf-8") == "# Cambio externo\n"

    def test_save_replay_token_403_zero_mutation(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        conf, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        assert _gated_write(client, "00_inicio.md", "# A\n", conf, base_rev).status_code == 200
        new_base = hashlib.sha256(target.read_bytes()).hexdigest()
        replay = _gated_write(client, "00_inicio.md", "# A\n", conf, new_base)
        assert replay.status_code == 403  # token consumed by the first save
        assert target.read_text(encoding="utf-8") == "# A\n"

    def test_create_without_token_400_zero_mutation(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "nuevo.md"
        resp = client.post("/api/test_mundo/lore/create?path=nuevo.md",
                           json={"content": "# N\n", "edit_id": "e1"})
        assert resp.status_code == 400
        assert not target.exists()


class TestAtomicReplace:
    """Slice 1C (task 2.3): atomic same-dir replace + per-target lock +
    snapshot seam, with no temp leftovers and zero mutation on failure."""

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def _no_temps(self) -> list[str]:
        return [p.name for p in self._lore().iterdir() if p.name.endswith(".tmp")]

    def test_success_replaces_content_and_leaves_no_temp(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, base_rev = _confirm(client, "00_inicio.md", "# Editado\n")
        resp = _gated_write(client, "00_inicio.md", "# Editado\n", conf, base_rev)
        assert resp.status_code == 200
        target = self._lore() / "00_inicio.md"
        assert target.read_text(encoding="utf-8") == "# Editado\n"
        assert self._no_temps() == []

    def test_replace_failure_cleans_temp_target_intact(self, client: TestClient, monkeypatch):
        """A failed os.replace must remove the temp file and leave the
        original bytes untouched (500, not a torn write)."""
        _principal(monkeypatch)
        target = self._lore() / "00_inicio.md"
        before = target.read_bytes()

        def _boom(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(os, "replace", _boom)
        conf, base_rev = _confirm(client, "00_inicio.md", "# Editado\n")
        resp = _gated_write(client, "00_inicio.md", "# Editado\n", conf, base_rev)
        assert resp.status_code == 500
        assert target.read_bytes() == before
        assert self._no_temps() == []

    def test_snapshot_seam_fires_before_successful_replace(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        seen = []
        monkeypatch.setattr(api_server, "_snapshot_before_write",
                            lambda full: seen.append(str(full)))
        conf, base_rev = _confirm(client, "00_inicio.md", "# Editado\n")
        resp = _gated_write(client, "00_inicio.md", "# Editado\n", conf, base_rev)
        assert resp.status_code == 200
        assert seen == [str(self._lore() / "00_inicio.md")]

    def test_snapshot_seam_not_fired_on_rejected_write(self, client: TestClient, monkeypatch):
        """A stale-base rejection happens under the lock BEFORE the snapshot
        hook: the seam must not fire and the on-disk bytes must not change."""
        _principal(monkeypatch)
        seen = []
        monkeypatch.setattr(api_server, "_snapshot_before_write",
                            lambda full: seen.append(str(full)))
        target = self._lore() / "00_inicio.md"
        conf, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        target.write_text("# Cambio externo\n", encoding="utf-8")
        resp = _gated_write(client, "00_inicio.md", "# A\n", conf, base_rev)
        assert resp.status_code == 409
        assert seen == []
        assert target.read_text(encoding="utf-8") == "# Cambio externo\n"

    def test_stale_second_confirmation_409(self, client: TestClient, monkeypatch):
        """A second confirmation bound to the SAME base as the first cannot
        write after the first write advanced the on-disk digest: valid token,
        stale base → 409, not 403, and no mutation of the first write."""
        _principal(monkeypatch)
        target = self._lore() / "00_inicio.md"
        conf1, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        conf2, _ = _confirm(client, "00_inicio.md", "# B\n")  # same base still current
        assert _gated_write(client, "00_inicio.md", "# A\n", conf1, base_rev).status_code == 200
        resp = _gated_write(client, "00_inicio.md", "# B\n", conf2, base_rev)
        assert resp.status_code == 409
        assert "base" in resp.json()["detail"].lower()
        assert target.read_text(encoding="utf-8") == "# A\n"

    def test_concurrent_stale_writes_serialize(self, client: TestClient, monkeypatch):
        """Two writers with distinct valid tokens on the same base: the
        per-target lock serializes base recheck + replace, so exactly one
        write wins and the other 409s — the file is never torn."""
        _principal(monkeypatch)
        target = self._lore() / "00_inicio.md"
        conf_a, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        conf_b, _ = _confirm(client, "00_inicio.md", "# B\n")
        outcomes = []

        def _writer(conf, content):
            try:
                outcomes.append(
                    _gated_write(client, "00_inicio.md", content, conf, base_rev).status_code)
            except Exception as exc:  # pragma: no cover - defensive
                outcomes.append(("exc", exc))

        t1 = threading.Thread(target=_writer, args=(conf_a, "# A\n"))
        t2 = threading.Thread(target=_writer, args=(conf_b, "# B\n"))
        t1.start(); t2.start(); t1.join(); t2.join()
        assert sorted(outcomes) == [200, 409]
        assert target.read_text(encoding="utf-8") in ("# A\n", "# B\n")


class TestNewFileParity:
    """Slice 1C (task 2.4): new files share the manual edit confirmation
    flow; every rejection leaves the target absent (zero mutation)."""

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def test_new_file_identical_confirmation_flow(self, client: TestClient, monkeypatch):
        """A new file uses the same confirm → token → gated-create flow as an
        existing-file edit; success persists the exact proposed content."""
        _principal(monkeypatch)
        conf = _confirm_new(client, "nuevo.md", "# Nuevo\n")
        resp = _gated_create(client, "nuevo.md", "# Nuevo\n", conf)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert (self._lore() / "nuevo.md").read_text(encoding="utf-8") == "# Nuevo\n"

    def test_edit_kind_token_cannot_authorize_creation(self, client: TestClient, monkeypatch):
        """A kind='edit' token bound to an existing file must never authorize
        creating a new file (kind and target binding in the store)."""
        _principal(monkeypatch)
        conf, _ = _confirm(client, "00_inicio.md", "# A\n")
        resp = _gated_create(client, "nuevo.md", "# A\n", conf)
        assert resp.status_code == 403
        assert not (self._lore() / "nuevo.md").exists()

    def test_new_kind_token_cannot_authorize_edit(self, client: TestClient, monkeypatch):
        """Parity is bidirectional: a kind='new' token must not save an edit."""
        _principal(monkeypatch)
        conf = _confirm_new(client, "nuevo.md", "# Nuevo\n")
        target = self._lore() / "00_inicio.md"
        before = target.read_bytes()
        base_rev = hashlib.sha256(before).hexdigest()
        resp = _gated_write(client, "00_inicio.md", "# Nuevo\n", conf, base_rev)
        assert resp.status_code == 403
        assert target.read_bytes() == before

    def test_rejections_leave_new_file_absent(self, client: TestClient, monkeypatch):
        """Digest mismatch, forged token, and mismatched edit_id each consume
        their own fresh confirmation and must leave no file behind."""
        _principal(monkeypatch)
        path = "nuevo.md"
        for overrides in (
            {"content": "# OTHER\n"},
            {"token": "forged"},
            {"edit_id": "eX"},
        ):
            conf = _confirm_new(client, path, "# Nuevo\n")
            payload = {"content": "# Nuevo\n", "edit_id": "n1",
                       "proposed_digest": conf["proposed_digest"],
                       "token": conf["token"]}
            payload.update(overrides)
            resp = client.post(f"/api/test_mundo/lore/create?path={path}", json=payload)
            assert resp.status_code == 403, (overrides, resp.text)
            assert not (self._lore() / path).exists(), overrides

    def test_create_without_principal_leaves_new_file_absent(self, client: TestClient):
        """No trusted principal (default seam) → 401 and no file created."""
        resp = client.post("/api/test_mundo/lore/create?path=nuevo.md",
                           json={"content": "# N\n", "edit_id": "n1"})
        assert resp.status_code == 401
        assert not (self._lore() / "nuevo.md").exists()


class TestHistoryRestore:
    """PR 3: bounded, integrity-checked history and safe restoration."""

    def _target(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"

    def _write(self, client: TestClient, monkeypatch, content: str, edit_id: str):
        _principal(monkeypatch)
        target = self._target()
        base = hashlib.sha256(target.read_bytes()).hexdigest()
        conf, _ = _confirm(client, "00_inicio.md", content, edit_id=edit_id)
        response = _gated_write(client, "00_inicio.md", content, conf, base, edit_id=edit_id)
        assert response.status_code == 200, response.text

    def _entries(self, client: TestClient, monkeypatch) -> list[dict]:
        _principal(monkeypatch)
        response = client.get("/api/test_mundo/history?path=lore/00_inicio.md")
        assert response.status_code == 200, response.text
        return response.json()["entries"]

    def test_snapshot_before_write_and_new_file_has_no_snapshot(
            self, client: TestClient, monkeypatch):
        self._write(client, monkeypatch, "# First\n", "h1")
        entries = self._entries(client, monkeypatch)
        assert len(entries) == 1
        assert entries[0]["content"].startswith("---")
        assert entries[0]["target"] == "lore/00_inicio.md"

        _principal(monkeypatch)
        new_conf = _confirm_new(client, "new.md", "# New\n", edit_id="new-1")
        assert _gated_create(client, "new.md", "# New\n", new_conf,
                             edit_id="new-1").status_code == 200
        response = client.get("/api/test_mundo/history?path=lore/new.md")
        assert response.status_code == 200
        assert response.json()["entries"] == []

    def test_history_is_newest_first_and_scoped_to_target(
            self, client: TestClient, monkeypatch):
        self._write(client, monkeypatch, "# A\n", "h1")
        self._write(client, monkeypatch, "# B\n", "h2")
        other = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "other.md"
        other.write_text("# Other\n", encoding="utf-8")
        api_server._snapshot_before_write(other)

        entries = self._entries(client, monkeypatch)
        assert entries[0]["content"] == "# A\n"
        assert "title: Inicio" in entries[1]["content"]
        assert all(entry["target"] == "lore/00_inicio.md" for entry in entries)

    def test_history_record_preserves_exact_bytes_and_integrity_fields(
            self, client: TestClient, monkeypatch):
        target = self._target()
        original = b"# Exact bytes\r\nSecond line\r\n"
        target.write_bytes(original)
        api_server._snapshot_before_write(target)

        bucket, canonical_target = api_server._history_bucket(target)
        record_path = next(bucket.glob("*.json"))
        record = json.loads(record_path.read_text(encoding="utf-8"))

        assert set(record) == api_server._HISTORY_FIELDS
        assert record["version"] == api_server._HISTORY_VERSION
        assert record["snapshot_id"] == record_path.stem
        assert record["target"] == canonical_target == "lore/00_inicio.md"
        assert base64.b64decode(record["content_b64"], validate=True) == original
        assert record["content_digest"] == hashlib.sha256(original).hexdigest()
        assert record["size"] == len(original)
        assert api_server._parse_history_time(record["created_at"]) <= datetime.now(timezone.utc)

        entries = self._entries(client, monkeypatch)
        assert entries[0]["content"].encode("utf-8") == original
        assert entries[0]["revision"] == record["content_digest"]
        assert target.read_bytes() == original

    @pytest.mark.parametrize("mutation", [
        "extra_field", "missing_field", "target", "snapshot_id", "digest",
        "size", "encoding", "utf8", "future_timestamp",
    ])
    def test_history_record_integrity_rejects_each_invalid_field_without_mutation(
            self, client: TestClient, monkeypatch, mutation: str):
        self._write(client, monkeypatch, "# Current\n", f"integrity-{mutation}")
        target = self._target()
        bucket, _ = api_server._history_bucket(target)
        record_path = next(bucket.glob("*.json"))
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if mutation == "extra_field":
            record["unexpected"] = True
        elif mutation == "missing_field":
            del record["size"]
        elif mutation == "target":
            record["target"] = "lore/other.md"
        elif mutation == "snapshot_id":
            record["snapshot_id"] = "0" * 32
        elif mutation == "digest":
            record["content_digest"] = "0" * 64
        elif mutation == "size":
            record["size"] += 1
        elif mutation == "encoding":
            record["content_b64"] = "%%%"
        elif mutation == "utf8":
            record["content_b64"] = "/w=="
        else:
            record["created_at"] = (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).isoformat().replace("+00:00", "Z")
        record_bytes = json.dumps(record, sort_keys=True).encode("utf-8")
        record_path.write_bytes(record_bytes)
        target_before = target.read_bytes()
        storage_before = sorted(path.name for path in bucket.iterdir())

        entries = self._entries(client, monkeypatch)
        assert entries == []
        _principal(monkeypatch)
        confirmation = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={
                "kind": "restore", "snapshot_id": record_path.stem,
                "edit_id": f"restore-{mutation}",
                "base_revision": hashlib.sha256(target_before).hexdigest(),
            },
        )
        assert confirmation.status_code in (400, 404)
        assert target.read_bytes() == target_before
        assert sorted(path.name for path in bucket.iterdir()) == storage_before
        assert record_path.read_bytes() == record_bytes

    @pytest.mark.parametrize("storage", ["root", "bucket", "entry"])
    def test_symlinked_history_storage_is_rejected_without_mutation(
            self, client: TestClient, monkeypatch, tmp_path: Path, storage: str):
        target = self._target()
        target_before = target.read_bytes()
        world = api_server.MUNDOS_DIR / "test_mundo"
        history_root = world / ".history"
        bucket_id = hashlib.sha256("lore/00_inicio.md".encode("utf-8")).hexdigest()
        external = tmp_path / f"unsafe-{storage}"
        external.mkdir()
        try:
            if storage == "root":
                history_root.symlink_to(external, target_is_directory=True)
            else:
                history_root.mkdir()
                bucket = history_root / bucket_id
                if storage == "bucket":
                    bucket.symlink_to(external, target_is_directory=True)
                else:
                    bucket.mkdir()
                    external_record = external / "record.json"
                    external_record.write_text("must remain untouched", encoding="utf-8")
                    (bucket / ("a" * 32 + ".json")).symlink_to(external_record)
        except OSError as error:
            pytest.skip(f"symlink creation unavailable: {error}")

        external_before = sorted(
            (path.name, path.read_bytes()) for path in external.iterdir()
        )
        _principal(monkeypatch)
        response = client.get("/api/test_mundo/history?path=lore/00_inicio.md")
        if storage in ("root", "bucket"):
            assert response.status_code == 400
        else:
            assert response.status_code == 200
            assert response.json()["entries"] == []
        assert target.read_bytes() == target_before
        assert sorted(
            (path.name, path.read_bytes()) for path in external.iterdir()
        ) == external_before

    def test_history_retains_at_most_twenty_entries(
            self, client: TestClient, monkeypatch):
        for index in range(21):
            self._write(client, monkeypatch, f"# Version {index}\n", f"h-{index}")
        entries = self._entries(client, monkeypatch)
        assert len(entries) == api_server._HISTORY_MAX_SNAPSHOTS
        assert entries[0]["content"] == "# Version 19\n"
        assert entries[-1]["content"] == "# Version 0\n"

    def test_expired_entry_is_hidden_without_mutation(
            self, client: TestClient, monkeypatch):
        self._write(client, monkeypatch, "# Current\n", "ttl")
        target = self._target()
        bucket, _ = api_server._history_bucket(target)
        entry = next(bucket.glob("*.json"))
        metadata_before = entry.read_bytes()
        metadata = json.loads(metadata_before)
        metadata["created_at"] = (
            datetime.now(timezone.utc) - timedelta(days=31)
        ).isoformat().replace("+00:00", "Z")
        entry.write_text(json.dumps(metadata), encoding="utf-8")
        target_before = target.read_bytes()

        entries = self._entries(client, monkeypatch)
        assert entries == []
        assert target.read_bytes() == target_before
        assert entry.exists()

    @pytest.mark.parametrize("mutation", ["missing", "corrupt", "tampered", "incompatible"])
    def test_invalid_entry_is_rejected_without_mutation(
            self, client: TestClient, monkeypatch, mutation: str):
        self._write(client, monkeypatch, "# Current\n", f"invalid-{mutation}")
        target = self._target()
        entry_data = self._entries(client, monkeypatch)[0]
        bucket, _ = api_server._history_bucket(target)
        entry = bucket / f"{entry_data['snapshot_id']}.json"
        if mutation == "missing":
            entry.unlink()
        elif mutation == "corrupt":
            entry.write_text("not json", encoding="utf-8")
        else:
            metadata = json.loads(entry.read_text(encoding="utf-8"))
            if mutation == "tampered":
                metadata["content_b64"] = "YXR0YWNrZWQ="
            else:
                metadata["version"] = 999
            entry.write_text(json.dumps(metadata), encoding="utf-8")

        before = target.read_bytes()
        assert self._entries(client, monkeypatch) == []
        _principal(monkeypatch)
        base = hashlib.sha256(before).hexdigest()
        confirmation = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={
                "kind": "restore", "snapshot_id": entry_data["snapshot_id"],
                "edit_id": "restore-invalid", "base_revision": base,
            },
        )
        assert confirmation.status_code in (400, 404)
        assert target.read_bytes() == before

    def test_unauthorized_and_traversal_history_requests_fail_closed(
            self, client: TestClient, monkeypatch, tmp_path: Path):
        target = self._target()
        before = target.read_bytes()
        unauthorized = client.get("/api/test_mundo/history?path=lore/00_inicio.md")
        assert unauthorized.status_code == 401
        restore_unauthorized = client.post(
            "/api/test_mundo/history/restore",
            json={"path": "lore/00_inicio.md", "snapshot_id": "0" * 32},
        )
        assert restore_unauthorized.status_code == 401

        _principal(monkeypatch)
        outside = tmp_path / "secret.md"
        outside.write_text("SECRET\n", encoding="utf-8")
        traversal = client.get("/api/test_mundo/history?path=../../secret.md")
        assert traversal.status_code == 400
        assert target.read_bytes() == before
        assert outside.read_text(encoding="utf-8") == "SECRET\n"

    def test_history_requires_section_prefixed_path(
            self, client: TestClient, monkeypatch):
        """Frontend boundary: a section-relative path (`00_inicio.md`) is
        rejected; only the canonical mundo-relative form (`lore/00_inicio.md`)
        is accepted."""
        _principal(monkeypatch)
        relative = client.get("/api/test_mundo/history?path=00_inicio.md")
        assert relative.status_code == 400
        assert relative.json()["detail"] == "Invalid history path"
        canonical = client.get("/api/test_mundo/history?path=lore/00_inicio.md")
        assert canonical.status_code == 200, canonical.text

    def test_restore_snapshots_current_content_before_replacement(
            self, client: TestClient, monkeypatch):
        self._write(client, monkeypatch, "# Current\n", "restore-source")
        entries = self._entries(client, monkeypatch)
        original = entries[0]
        target = self._target()
        current_base = hashlib.sha256(target.read_bytes()).hexdigest()
        _principal(monkeypatch)
        confirmation = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={
                "kind": "restore", "snapshot_id": original["snapshot_id"],
                "edit_id": "restore-1", "base_revision": current_base,
                "proposed_content": original["content"],
            },
        )
        assert confirmation.status_code == 200, confirmation.text
        response = client.post(
            "/api/test_mundo/history/restore",
            json={
                "path": "lore/00_inicio.md",
                "snapshot_id": original["snapshot_id"],
                "edit_id": "restore-1", "base_revision": current_base,
                "content": original["content"],
                "token": confirmation.json()["token"],
                "proposed_digest": confirmation.json()["proposed_digest"],
            },
        )
        assert response.status_code == 200, response.text
        assert target.read_bytes().decode("utf-8") == original["content"]
        restored_entries = self._entries(client, monkeypatch)
        assert restored_entries[0]["content"] == "# Current\n"

    def test_restore_stale_base_rejects_before_safety_snapshot(
            self, client: TestClient, monkeypatch):
        self._write(client, monkeypatch, "# Current\n", "restore-stale")
        original = self._entries(client, monkeypatch)[0]
        target = self._target()
        base = hashlib.sha256(target.read_bytes()).hexdigest()
        _principal(monkeypatch)
        confirmation = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={"kind": "restore", "snapshot_id": original["snapshot_id"],
                  "edit_id": "restore-stale", "base_revision": base},
        )
        assert confirmation.status_code == 200
        before_count = len(self._entries(client, monkeypatch))
        target.write_text("# External\n", encoding="utf-8")
        response = client.post(
            "/api/test_mundo/history/restore",
            json={"path": "lore/00_inicio.md", "snapshot_id": original["snapshot_id"],
                  "edit_id": "restore-stale", "base_revision": base,
                  "token": confirmation.json()["token"],
                  "proposed_digest": confirmation.json()["proposed_digest"]},
        )
        assert response.status_code == 409
        assert target.read_text(encoding="utf-8") == "# External\n"
        assert len(self._entries(client, monkeypatch)) == before_count

    def test_snapshot_failure_rolls_back_without_replacing_target(
            self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = self._target()
        before = target.read_bytes()
        conf, base = _confirm(client, "00_inicio.md", "# New\n", edit_id="snapshot-fail")

        def fail_snapshot(*args):
            raise OSError("history unavailable")

        monkeypatch.setattr(api_server, "_snapshot_before_write", fail_snapshot)
        response = _gated_write(client, "00_inicio.md", "# New\n", conf, base,
                                edit_id="snapshot-fail")
        assert response.status_code == 500
        assert target.read_bytes() == before


class TestAIEditSuggest:
    """PR 2 (tasks 3.1-3.4): diskless validated Hermes proposals with a hard
    cap of exactly 3 total attempts and a safe, non-persisting fallback.

    Hermes is mocked via ``api_server._run_hermes``; every test asserts zero
    persistence (target bytes unchanged, no new file, no temp leftovers) and
    the observability test proves content never reaches the logs.
    """

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def _no_temps(self) -> list[str]:
        return [p.name for p in self._lore().iterdir() if p.name.endswith(".tmp")]

    def _valid_payload(self, content: str, new: bool = False) -> dict:
        base = "" if new else hashlib.sha256(
            (self._lore() / "00_inicio.md").read_bytes()).hexdigest()
        return {
            "proposal_id": "prop-1",
            "target": "lore/nuevo.md" if new else "lore/00_inicio.md",
            "base_revision": base,
            "content": content,
            "rationale": "test rationale",
            "is_new_file": new,
        }

    def _suggest(self, client: TestClient, path: str, **overrides) -> dict:
        body = {"section": "lore", "path": path, "prompt": "mejora este archivo"}
        body.update(overrides)
        return client.post("/api/test_mundo/ai/edit-suggest", json=body)

    def test_valid_existing_file_proposal(self, client: TestClient):
        """A contract-valid reply yields the full proposal and writes nothing."""
        target = self._lore() / "00_inicio.md"
        before = target.read_bytes()
        payload = self._valid_payload("# Propuesta\n")
        fenced = "```json\n" + json.dumps(payload) + "\n```"  # fence tolerance
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value=fenced)) as mock_run:
            resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "proposal" and body["attempts"] == 1
        prop = body["proposal"]
        assert prop["proposal_id"] == "prop-1"
        assert prop["target"] == "lore/00_inicio.md"
        assert prop["base_revision"] == hashlib.sha256(before).hexdigest()
        assert prop["content"] == "# Propuesta\n"
        assert prop["proposed_digest"] == hashlib.sha256("# Propuesta\n".encode()).hexdigest()
        assert prop["rationale"] and prop["is_new_file"] is False
        assert mock_run.await_count == 1
        # No-write invariant: proposal never touches the target on disk.
        assert target.read_bytes() == before
        assert self._no_temps() == []

    def test_valid_new_file_proposal(self, client: TestClient):
        """A new-target proposal is marked new with an empty base and stays
        unpersisted pending review."""
        payload = self._valid_payload("# Nuevo\n", new=True)
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value=json.dumps(payload))):
            resp = self._suggest(client, "nuevo.md")
        assert resp.status_code == 200
        prop = resp.json()["proposal"]
        assert prop["is_new_file"] is True
        assert prop["base_revision"] == ""
        assert prop["content"] == "# Nuevo\n"
        assert not (self._lore() / "nuevo.md").exists()  # still diskless

    def test_malformed_and_schema_invalid_exhaust_fallback(self, client: TestClient):
        """Unparseable, missing-field, and wrong-base replies each count as
        retryable attempts; after exactly 3 the user gets a safe fallback."""
        target = self._lore() / "00_inicio.md"
        before = target.read_bytes()
        replies = [
            "not json at all",
            json.dumps({"proposal_id": "p1"}),  # missing required fields
            json.dumps({"proposal_id": "p2", "target": "lore/00_inicio.md",
                        "base_revision": "0" * 64, "content": "x",
                        "rationale": "r", "is_new_file": False}),  # bad base
        ]
        with patch("api_server._run_hermes",
                   new=AsyncMock(side_effect=replies)) as mock_run:
            resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "fallback" and body["attempts"] == 3
        assert body["proposal"] is None
        assert body["fallback_action"] == "manual-edit-or-chat"
        assert mock_run.await_count == 3  # exactly 3, never more
        assert target.read_bytes() == before

    def test_transient_twice_then_success_attempts_three(self, client: TestClient):
        """Two transient gateway failures then a valid reply: attempts == 3
        and the proposal is returned (no fallback)."""
        payload = self._valid_payload("# Recuperado\n")
        replies = ["Error: timeout", "Error: HTTP 500", json.dumps(payload)]
        with patch("api_server._run_hermes",
                   new=AsyncMock(side_effect=replies)) as mock_run:
            resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "proposal" and body["attempts"] == 3
        assert body["proposal"]["content"] == "# Recuperado\n"
        assert body["proposal"]["base_revision"] == hashlib.sha256(
            (self._lore() / "00_inicio.md").read_bytes()).hexdigest()
        assert mock_run.await_count == 3

    def test_schema_invalid_target_mismatch_retries_then_success(self, client: TestClient):
        """Hermes must never select arbitrary targets: a mismatched target is
        schema-invalid (retryable) and a corrected reply succeeds on attempt 2."""
        wrong = self._valid_payload("# A\n")
        wrong["target"] = "lore/other.md"
        good = self._valid_payload("# B\n")
        with patch("api_server._run_hermes",
                   new=AsyncMock(side_effect=[json.dumps(wrong), json.dumps(good)])):
            resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "proposal" and body["attempts"] == 2
        assert body["proposal"]["content"] == "# B\n"
        assert body["proposal"]["target"] == "lore/00_inicio.md"

    def test_exhaustion_writes_nothing(self, client: TestClient):
        """On exhaustion the section tree is byte-identical: no edits, no new
        files, no temp leftovers."""
        target = self._lore() / "00_inicio.md"
        before = target.read_bytes()
        before_entries = sorted(p.name for p in self._lore().iterdir())
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value="garbage")):
            resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "fallback"
        assert target.read_bytes() == before
        assert sorted(p.name for p in self._lore().iterdir()) == before_entries
        assert self._no_temps() == []

    def test_traversal_and_internal_targets_rejected_without_gateway_call(
            self, client: TestClient, tmp_path):
        """Traversal and .history targets are rejected before any Hermes
        call, with zero mutation and zero disclosure."""
        escape = tmp_path / "mundos" / "secrets.md"
        escape.write_text("EDIT SUGGEST SECRET\n", encoding="utf-8")
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value="{}")) as mock_run:
            resp = self._suggest(client, "../../secrets.md")
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()
        assert mock_run.await_count == 0
        assert escape.read_text(encoding="utf-8") == "EDIT SUGGEST SECRET\n"

        snap = api_server.MUNDOS_DIR / "test_mundo" / ".history" / "lore" / "x.md"
        snap.parent.mkdir(parents=True)
        snap.write_text("SNAPSHOT\n", encoding="utf-8")
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value="{}")) as mock_run2:
            resp2 = self._suggest(client, "../.history/lore/x.md")
        assert resp2.status_code == 400
        assert mock_run2.await_count == 0
        assert snap.read_text(encoding="utf-8") == "SNAPSHOT\n"

    def test_observability_logs_metadata_only_not_content(self, client: TestClient,
                                                          monkeypatch, caplog):
        """Diagnostics record target/attempts/category/outcome/opaque principal
        but never proposal content or prompt secrets."""
        _principal(monkeypatch, pid="opaque-42")
        marker = "SUPER SECRET PROPOSAL CONTENT"
        payload = self._valid_payload(f"# Propuesta\n{marker}\n")
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value=json.dumps(payload))):
            with caplog.at_level(logging.INFO):
                resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        assert marker not in caplog.text
        assert "# Propuesta" not in caplog.text
        assert "ai/edit-suggest:" in caplog.text
        assert "lore/00_inicio.md" in caplog.text
        assert "attempts=1" in caplog.text and "outcome=proposal" in caplog.text
        assert "principal=opaque-42" in caplog.text
