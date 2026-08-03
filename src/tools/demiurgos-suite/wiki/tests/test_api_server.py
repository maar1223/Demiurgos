# -*- coding: utf-8 -*-
"""API server tests — tree contract, save, and diff endpoints.

These endpoints were rebuilt in api_server.py and previously had no test
coverage, which is how the is_dir contract regression survived unnoticed.
"""

import sys
import tempfile
import time
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
