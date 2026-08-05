# -*- coding: utf-8 -*-
"""API server tests — tree contract, save, and diff endpoints.

These endpoints were rebuilt in api_server.py and previously had no test
coverage, which is how the is_dir contract regression survived unnoticed.
"""

import json
import re
import sys
import tempfile
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
    api_server._graph_indices.clear()
    return TestClient(api_server.app)


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
    def test_save_writes_content(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/save?path=00_inicio.md",
            json={"content": "# Editado\n"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        saved = (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").read_text(encoding="utf-8")
        assert saved == "# Editado\n"

    def test_save_blocks_path_traversal(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/save?path=../../secrets.txt",
            json={"content": "x"},
        )
        # Either the traversal is rejected before writing, or the file is
        # written outside the world root — the response must not claim success
        # for an escaped path.
        assert resp.json().get("success") is not True


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
    """D8/S35: create_file and save_file now raise HTTPException with real
    statuses and Spanish detail instead of the legacy 200 + {"error"}."""

    def test_create_existing_returns_409(self, client: TestClient):
        resp = client.post("/api/test_mundo/lore/create?path=00_inicio.md", json={"content": "x"})
        assert resp.status_code == 409
        assert "ya existe" in resp.json()["detail"].lower()

    def test_create_invalid_section_returns_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/wiki/create?path=a.md", json={"content": "x"})
        assert resp.status_code == 400
        assert resp.json()["detail"]

    def test_create_missing_mundo_returns_404(self, client: TestClient):
        resp = client.post("/api/test_mundo_fantasma/lore/create?path=a.md", json={"content": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_create_traversal_returns_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/lore/create?path=../../x.md", json={"content": "x"})
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()

    def test_save_invalid_section_returns_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/wiki/save?path=a.md", json={"content": "x"})
        assert resp.status_code == 400

    def test_save_missing_mundo_returns_404(self, client: TestClient):
        resp = client.post("/api/test_mundo_fantasma/lore/save?path=a.md", json={"content": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_save_traversal_returns_400(self, client: TestClient):
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

    def test_save_mundo_traversal_404_never_writes(self, client: TestClient):
        outside = self._tmp_root() / "lore"
        outside.mkdir(exist_ok=True)
        resp = client.post(
            f"/api/{self.ENC_DOTS}/lore/save?path=pwned.md", json={"content": "x"}
        )
        assert resp.status_code == 404
        assert not (outside / "pwned.md").exists()

    def test_create_mundo_traversal_404_never_writes(self, client: TestClient):
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
