# -*- coding: utf-8 -*-
"""API server tests — tree contract, save, and diff endpoints.

These endpoints were rebuilt in api_server.py and previously had no test
coverage, which is how the is_dir contract regression survived unnoticed.
"""

import sys
import tempfile
import time
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
    """S24-S27: delete_file moves to .papelera, never unlinks."""

    def _papelera_lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / ".papelera" / "lore"

    def test_file_moves_to_papelera(self, client: TestClient):
        resp = client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert self._papelera_lore().is_dir()
        files = [p for p in self._papelera_lore().iterdir() if p.is_file()]
        assert len(files) == 1
        assert files[0].name.endswith("_00_inicio.md")
        assert files[0].name.startswith("20")  # ISO timestamp prefix
        # Original gone
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").exists()

    def test_dir_moves_recursively(self, client: TestClient):
        ciudades = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades"
        ciudades.mkdir()
        (ciudades / "alfa.md").write_text("# Alfa\n", encoding="utf-8")
        (ciudades / "beta.md").write_text("# Beta\n", encoding="utf-8")

        resp = client.delete("/api/test_mundo/lore/file?path=ciudades")
        assert resp.status_code == 200

        moved = [p for p in self._papelera_lore().iterdir() if p.is_dir() and p.name.endswith("_ciudades")]
        assert len(moved) == 1
        assert (moved[0] / "alfa.md").read_text(encoding="utf-8") == "# Alfa\n"
        assert (moved[0] / "beta.md").read_text(encoding="utf-8") == "# Beta\n"
        assert not ciudades.exists()

    def test_subfolders_preserved(self, client: TestClient):
        planos = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades" / "planos"
        planos.mkdir(parents=True)
        (planos / "x.md").write_text("# X\n", encoding="utf-8")

        resp = client.delete("/api/test_mundo/lore/file?path=ciudades")
        assert resp.status_code == 200

        moved = [p for p in self._papelera_lore().iterdir() if p.is_dir() and p.name.endswith("_ciudades")]
        assert len(moved) == 1
        assert (moved[0] / "planos" / "x.md").read_text(encoding="utf-8") == "# X\n"

    def test_rapid_deletes_have_distinct_timestamps(self, client: TestClient):
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        (base / "a.md").write_text("# A\n", encoding="utf-8")
        (base / "b.md").write_text("# B\n", encoding="utf-8")

        assert client.delete("/api/test_mundo/lore/file?path=a.md").status_code == 200
        time.sleep(0.005)
        assert client.delete("/api/test_mundo/lore/file?path=b.md").status_code == 200

        names = sorted(p.name for p in self._papelera_lore().iterdir())
        assert len(names) == 2
        assert any(n.endswith("_a.md") for n in names)
        assert any(n.endswith("_b.md") for n in names)
        assert names[0] != names[1]

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
