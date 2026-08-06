# -*- coding: utf-8 -*-
"""Media endpoint tests — serve, upload, list, and trash wiki images.

Covered:
- GET  /api/{mundo}/media?path=       — serve from wiki/media/ and referencias/
- POST /api/{mundo}/media/upload      — JPEG compression + thumbnail generation
- GET  /api/{mundo}/media/list        — recursive union of both media bases
- DELETE /api/{mundo}/media?path=     — trash from BOTH bases (media section);
                                        thumbnail travels as a unit
"""

import io
import json
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a temp mundos dir and a sample world with media."""
    mundos = tmp_path / "mundos"
    world = mundos / "test"
    wiki_media = world / "wiki" / "media"
    wiki_media.mkdir(parents=True)
    (wiki_media / "test.jpg").write_text("fake jpg", encoding="utf-8")
    (wiki_media / "photo.png").write_text("fake png", encoding="utf-8")

    referencias = world / "referencias" / "visuales" / "imagenes"
    referencias.mkdir(parents=True)
    (referencias / "ref.png").write_text("fake ref png", encoding="utf-8")

    empty = mundos / "empty_world"
    (empty / "lore").mkdir(parents=True)

    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    return TestClient(api_server.app)


def _make_test_image(width: int = 100, height: int = 80, fmt: str = "JPEG") -> bytes:
    """Create a minimal in-memory test image and return its bytes."""
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _make_transparent_png() -> bytes:
    """Create a minimal RGBA PNG (for testing transparency handling)."""
    img = Image.new("RGBA", (50, 50), (255, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestGetMedia:
    """GET /api/{mundo}/media?path= — serve image files."""

    def test_serve_wiki_media(self, client: TestClient):
        resp = client.get("/api/test/media", params={"path": "test.jpg"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/")

    def test_serve_referencias(self, client: TestClient):
        resp = client.get("/api/test/media", params={"path": "ref.png"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/")

    def test_serve_world_relative_path(self, client: TestClient):
        resp = client.get("/api/test/media", params={"path": "wiki/media/photo.png"})
        assert resp.status_code == 200

    def test_path_traversal_400(self, client: TestClient):
        resp = client.get("/api/test/media", params={"path": "../../../.env"})
        assert resp.status_code == 400
        assert "Path traversal" in resp.json()["detail"]

    def test_url_encoded_traversal_400(self, client: TestClient):
        encoded = urllib.parse.quote("../../.env", safe="")
        resp = client.get(f"/api/test/media?path={encoded}")
        assert resp.status_code == 400
        assert "Path traversal" in resp.json()["detail"]

    def test_not_found_404(self, client: TestClient):
        resp = client.get("/api/test/media", params={"path": "no_existe.jpg"})
        assert resp.status_code == 404
        assert "Archivo no encontrado" in resp.json()["detail"]


class TestUploadMedia:
    """POST /api/{mundo}/media/upload — upload and compress images."""

    def test_upload_jpeg_201(self, client: TestClient):
        resp = client.post(
            "/api/test/media/upload",
            files={"file": ("foto.jpg", _make_test_image(), "image/jpeg")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert "foto.jpg" in data["path"]
        assert data["size_bytes"] > 0
        assert data["thumbnail_path"] is not None
        assert "foto_thumb.jpg" in data["thumbnail_path"]

        served = client.get("/api/test/media", params={"path": "wiki/media/foto.jpg"})
        assert served.status_code == 200

    def test_upload_png_to_jpeg(self, client: TestClient):
        resp = client.post(
            "/api/test/media/upload",
            files={"file": ("logo.png", _make_test_image(fmt="PNG"), "image/png")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "logo.jpg" in data["path"]
        assert data["thumbnail_path"] is not None

    def test_upload_transparent_png_converts(self, client: TestClient):
        resp = client.post(
            "/api/test/media/upload",
            files={"file": ("transparente.png", _make_transparent_png(), "image/png")},
        )
        assert resp.status_code == 201
        assert "transparente.jpg" in resp.json()["path"]

    def test_upload_invalid_type_422(self, client: TestClient):
        resp = client.post(
            "/api/test/media/upload",
            files={"file": ("documento.pdf", b"fake pdf", "application/pdf")},
        )
        assert resp.status_code == 422
        assert "no permitido" in resp.json()["detail"].lower()

    def test_upload_oversize_413(self, client: TestClient):
        big_data = b"x" * (10 * 1024 * 1024 + 1)
        resp = client.post(
            "/api/test/media/upload",
            files={"file": ("grande.jpg", big_data, "image/jpeg")},
        )
        assert resp.status_code == 413
        assert "demasiado grande" in resp.json()["detail"].lower()

    def test_upload_conflict_409(self, client: TestClient):
        first = client.post(
            "/api/test/media/upload",
            files={"file": ("conflicto.jpg", _make_test_image(), "image/jpeg")},
        )
        assert first.status_code == 201

        second = client.post(
            "/api/test/media/upload",
            files={"file": ("conflicto.jpg", _make_test_image(), "image/jpeg")},
        )
        assert second.status_code == 409
        assert "ya existe" in second.json()["detail"].lower()

    def test_upload_overwrite_201(self, client: TestClient):
        client.post(
            "/api/test/media/upload",
            files={"file": ("sobrescribir.jpg", _make_test_image(), "image/jpeg")},
        )
        resp = client.post(
            "/api/test/media/upload",
            files={"file": ("sobrescribir.jpg", _make_test_image(), "image/jpeg")},
            params={"overwrite": "true"},
        )
        assert resp.status_code == 201
        assert resp.json()["success"] is True

    def test_upload_sanitizes_filename(self, client: TestClient):
        evil_name = "../../../etc/evil.jpg"
        resp = client.post(
            "/api/test/media/upload",
            files={"file": (evil_name, _make_test_image(), "image/jpeg")},
        )
        assert resp.status_code == 201
        basename = Path(resp.json()["path"]).name
        assert basename == "evil.jpg"
        assert ".." not in basename


class TestListMedia:
    """GET /api/{mundo}/media/list — list all images."""

    def test_list_returns_all_images(self, client: TestClient):
        resp = client.get("/api/test/media/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 3  # test.jpg + photo.png + ref.png
        assert isinstance(data["images"], list)

        paths = {img["path"] for img in data["images"]}
        assert "wiki/media/test.jpg" in paths
        assert "wiki/media/photo.png" in paths
        assert "referencias/visuales/imagenes/ref.png" in paths

    def test_list_empty_mundo(self, client: TestClient):
        resp = client.get("/api/empty_world/media/list")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        resp = client.get("/api/noexiste/media/list")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_includes_uploaded_file(self, client: TestClient):
        client.post(
            "/api/test/media/upload",
            files={"file": ("lista_test.jpg", _make_test_image(), "image/jpeg")},
        )
        resp = client.get("/api/test/media/list")
        paths = {img["path"] for img in resp.json()["images"]}
        assert any("lista_test.jpg" in p for p in paths)


class TestDeleteMedia:
    """DELETE /api/{mundo}/media?path= — delete images."""

    def test_delete_wiki_media_success(self, client: TestClient):
        client.post(
            "/api/test/media/upload",
            files={"file": ("borrame.jpg", _make_test_image(), "image/jpeg")},
        )
        resp = client.delete("/api/test/media", params={"path": "wiki/media/borrame.jpg"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        gone = client.get("/api/test/media", params={"path": "wiki/media/borrame.jpg"})
        assert gone.status_code == 404

    def test_delete_nonexistent_404(self, client: TestClient):
        resp = client.delete("/api/test/media", params={"path": "no_existe.jpg"})
        assert resp.status_code == 404
        assert "Archivo no encontrado" in resp.json()["detail"]

    def test_delete_path_traversal_400(self, client: TestClient):
        resp = client.delete("/api/test/media", params={"path": "../../../.env"})
        assert resp.status_code == 400
        assert "Path traversal" in resp.json()["detail"]

    def test_delete_also_removes_thumbnail(self, client: TestClient):
        client.post(
            "/api/test/media/upload",
            files={"file": ("con_thumb.jpg", _make_test_image(), "image/jpeg")},
        )
        listed = client.get("/api/test/media/list").json()
        assert any("con_thumb_thumb.jpg" in img["path"] for img in listed["images"])

        resp = client.delete("/api/test/media", params={"path": "wiki/media/con_thumb.jpg"})
        assert resp.status_code == 200

        listed = client.get("/api/test/media/list").json()
        assert not any("con_thumb_thumb" in img["path"] for img in listed["images"])


class TestTrashMedia:
    """DELETE /media now trashes images to the Papelera (media section).

    Both media bases (wiki/media/ and referencias/visuales/imagenes/) share
    one synthetic ``media`` trash section; the thumbnail travels with the
    main image as a unit and never appears as its own entry.
    """

    def _papelera_media(self) -> Path:
        return api_server.MUNDOS_DIR / "test" / ".papelera" / "media"

    def _entry_dirs(self) -> list[Path]:
        root = self._papelera_media()
        if not root.is_dir():
            return []
        return sorted(d for d in root.iterdir() if d.is_dir())

    def _upload(self, client: TestClient, name: str) -> None:
        resp = client.post(
            "/api/test/media/upload",
            files={"file": (name, _make_test_image(), "image/jpeg")},
        )
        assert resp.status_code == 201

    def test_delete_wiki_media_goes_to_papelera(self, client: TestClient):
        resp = client.delete("/api/test/media", params={"path": "wiki/media/test.jpg"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        original = api_server.MUNDOS_DIR / "test" / "wiki" / "media" / "test.jpg"
        assert not original.exists()

        entry_dirs = self._entry_dirs()
        assert len(entry_dirs) == 1
        entry_dir = entry_dirs[0]
        assert re.fullmatch(r"[0-9a-f]{12}", entry_dir.name)
        assert (entry_dir / "test.jpg").exists()
        meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["original_path"].startswith("wiki/media/")
        assert meta["deleted_at"].endswith("Z")

    def test_delete_referencias_media_goes_to_papelera(self, client: TestClient):
        resp = client.delete(
            "/api/test/media",
            params={"path": "referencias/visuales/imagenes/ref.png"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        original = api_server.MUNDOS_DIR / "test" / "referencias" / "visuales" / "imagenes" / "ref.png"
        assert not original.exists()

        entry_dirs = self._entry_dirs()
        assert len(entry_dirs) == 1
        entry_dir = entry_dirs[0]
        assert (entry_dir / "ref.png").exists()
        meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["original_path"].startswith("referencias/visuales/imagenes/")

    def test_delete_media_also_moves_thumbnail(self, client: TestClient):
        self._upload(client, "unidad.jpg")
        resp = client.delete("/api/test/media", params={"path": "wiki/media/unidad.jpg"})
        assert resp.status_code == 200

        media = api_server.MUNDOS_DIR / "test" / "wiki" / "media"
        assert not (media / "unidad.jpg").exists()
        assert not (media / "unidad_thumb.jpg").exists()

        entry_dir = self._entry_dirs()[0]
        names = {p.name for p in entry_dir.iterdir()}
        assert "unidad.jpg" in names
        assert "unidad_thumb.jpg" in names

    def test_restore_media_from_papelera(self, client: TestClient):
        self._upload(client, "volver.jpg")
        client.delete("/api/test/media", params={"path": "wiki/media/volver.jpg"})
        entry_id = self._entry_dirs()[0].name

        resp = client.post(
            "/api/test/papelera/restore",
            json={"entry_id": entry_id, "section": "media"},
        )
        assert resp.status_code == 200
        assert resp.json()["restored_to"] == "wiki/media/volver.jpg"

        media = api_server.MUNDOS_DIR / "test" / "wiki" / "media"
        assert (media / "volver.jpg").exists()
        assert (media / "volver_thumb.jpg").exists()
        assert not (self._papelera_media() / entry_id).exists()

    def test_restore_referencias_media_from_papelera(self, client: TestClient):
        resp = client.delete(
            "/api/test/media",
            params={"path": "referencias/visuales/imagenes/ref.png"},
        )
        assert resp.status_code == 200
        entry_id = self._entry_dirs()[0].name

        resp = client.post(
            "/api/test/papelera/restore",
            json={"entry_id": entry_id, "section": "media"},
        )
        assert resp.status_code == 200
        assert resp.json()["restored_to"] == "referencias/visuales/imagenes/ref.png"

        original = api_server.MUNDOS_DIR / "test" / "referencias" / "visuales" / "imagenes" / "ref.png"
        assert original.exists()
        assert not (self._papelera_media() / entry_id).exists()

    def test_list_papelera_includes_media_and_hides_thumbnail(self, client: TestClient):
        self._upload(client, "unica.jpg")
        client.delete("/api/test/media", params={"path": "wiki/media/unica.jpg"})

        resp = client.get("/api/test/papelera")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["section"] == "media"
        assert entry["kind"] == "file"
        assert entry["original_path"].startswith("wiki/media/")
        assert not any("_thumb" in e["original_path"] for e in entries)

    def test_ttl_purge_media(self, client: TestClient):
        client.delete("/api/test/media", params={"path": "wiki/media/test.jpg"})
        entry_dir = self._entry_dirs()[0]
        meta_path = entry_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["deleted_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat().replace("+00:00", "Z")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        resp = client.get("/api/test/papelera")
        assert resp.status_code == 200
        assert not entry_dir.exists()
        assert resp.json().get("purged") == 1

    def test_restore_media_collision_renames(self, client: TestClient):
        self._upload(client, "choque.jpg")
        client.delete("/api/test/media", params={"path": "wiki/media/choque.jpg"})
        # Re-upload the same name — occupies the original target path
        self._upload(client, "choque.jpg")
        entry_id = self._entry_dirs()[0].name

        resp = client.post(
            "/api/test/papelera/restore",
            json={"entry_id": entry_id, "section": "media"},
        )
        assert resp.status_code == 200
        assert resp.json()["restored_to"] == "wiki/media/choque-copia.jpg"

        media = api_server.MUNDOS_DIR / "test" / "wiki" / "media"
        assert (media / "choque.jpg").exists()
        assert (media / "choque-copia.jpg").exists()
        assert (media / "choque-copia_thumb.jpg").exists()
        assert not (self._papelera_media() / entry_id).exists()

    def test_delete_media_missing_thumb_ok(self, client: TestClient):
        media = api_server.MUNDOS_DIR / "test" / "wiki" / "media"
        (media / "sinthumb.png").write_bytes(b"fake png")

        resp = client.delete("/api/test/media", params={"path": "wiki/media/sinthumb.png"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert not (media / "sinthumb.png").exists()

        entry_dir = self._entry_dirs()[0]
        assert (entry_dir / "sinthumb.png").exists()
        meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["original_path"] == "wiki/media/sinthumb.png"
