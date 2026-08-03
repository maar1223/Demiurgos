# -*- coding: utf-8 -*-
"""Media endpoint tests — serve, upload, list, and delete wiki images.

Covered:
- GET  /api/{mundo}/media?path=       — serve from wiki/media/ and referencias/
- POST /api/{mundo}/media/upload      — JPEG compression + thumbnail generation
- GET  /api/{mundo}/media/list        — recursive union of both media bases
- DELETE /api/{mundo}/media?path=     — wiki/media only, 403 on referencias
"""

import io
import sys
import urllib.parse
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

    def test_delete_referencias_forbidden_403(self, client: TestClient):
        resp = client.delete(
            "/api/test/media",
            params={"path": "../../referencias/visuales/imagenes/ref.png"},
        )
        assert resp.status_code == 403
        assert "referencias" in resp.json()["detail"].lower()

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
