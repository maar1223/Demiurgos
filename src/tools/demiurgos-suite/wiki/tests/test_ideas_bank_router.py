"""tests/test_ideas_bank_router.py — Integration tests for /api/ideas router.

Builds a standalone FastAPI app with the real ideas_bank router over a
hermetic tmp_path bank (mirrors test_import_router._make_app). Covers the
REST contract (R-IB-03), the materialization endpoint (R-CG-04), the
fail-closed auth guard, and structural canon safety (ideas/ is a sibling of
mundos/, never scanned as canon).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ideas_bank_router import create_ideas_bank_router  # noqa: E402


class _FakePrincipal:
    def __init__(self, pid: str = "tester"):
        self.id = pid


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_ideas_bank_router(
            require_principal=lambda request: _FakePrincipal(),
            ideas_root=tmp_path / "ideas",
            mundos_root=tmp_path / "mundos",
        )
    )
    return TestClient(app)


def _create(client: TestClient, slug: str = "arquero-ciego", type: str = "personaje",
            body: str = "Un arquero que perdió la vista.") -> dict:
    resp = client.post("/api/ideas", json={"slug": slug, "type": type, "body": body})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# R-IB-03 — list
# ---------------------------------------------------------------------------

def test_list_empty(client: TestClient) -> None:
    resp = client.get("/api/ideas")
    assert resp.status_code == 200
    assert resp.json() == {"ideas": [], "total": 0}


def test_list_with_type_filter(client: TestClient) -> None:
    _create(client, slug="a", type="personaje")
    _create(client, slug="b", type="personaje")
    _create(client, slug="c", type="trama")
    resp = client.get("/api/ideas", params={"type": "personaje"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert {i["slug"] for i in data["ideas"]} == {"a", "b"}
    assert all(i["type"] == "personaje" for i in data["ideas"])


def test_list_with_source_filter(client: TestClient) -> None:
    _create(client, slug="a", type="personaje")
    resp = client.post(
        "/api/ideas",
        json={"slug": "b", "type": "concepto", "body": "Idea.", "source": "telegram"},
    )
    assert resp.status_code == 201, resp.text
    data = client.get("/api/ideas", params={"source": "telegram"}).json()
    assert data["total"] == 1
    assert data["ideas"][0]["slug"] == "b"


# ---------------------------------------------------------------------------
# R-IB-03 — create / get / update
# ---------------------------------------------------------------------------

def test_create_returns_detail(client: TestClient) -> None:
    idea = _create(client)
    assert idea["slug"] == "arquero-ciego"
    assert idea["source"] == "manual"
    assert idea["status"] == "fresh"
    assert idea["used_in"] == []
    assert idea["body"] == "Un arquero que perdió la vista."


def test_create_conflict_is_409(client: TestClient) -> None:
    _create(client, slug="dupe")
    resp = client.post("/api/ideas", json={"slug": "dupe", "type": "personaje", "body": "x"})
    assert resp.status_code == 409


def test_create_invalid_type_is_400(client: TestClient) -> None:
    resp = client.post("/api/ideas", json={"slug": "mala", "type": "nope", "body": "x"})
    assert resp.status_code == 400


def test_create_requires_auth(tmp_path: Path) -> None:
    auth_client, _ = _make_closed_client(tmp_path)
    resp = auth_client.post("/api/ideas", json={"slug": "x", "type": "personaje", "body": "x"})
    assert resp.status_code == 401


def test_get_idea(client: TestClient) -> None:
    _create(client)
    resp = client.get("/api/ideas/arquero-ciego")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "arquero-ciego"
    assert resp.json()["type"] == "personaje"


def test_get_missing_is_404(client: TestClient) -> None:
    resp = client.get("/api/ideas/no-existe")
    assert resp.status_code == 404


def test_update_type(client: TestClient) -> None:
    _create(client, type="sin_clasificar")
    resp = client.patch("/api/ideas/arquero-ciego", json={"type": "trama"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "trama"
    assert client.get("/api/ideas/arquero-ciego").json()["type"] == "trama"


def test_update_invalid_type_is_400(client: TestClient) -> None:
    _create(client)
    resp = client.patch("/api/ideas/arquero-ciego", json={"type": "nope"})
    assert resp.status_code == 400


def test_update_missing_is_404(client: TestClient) -> None:
    resp = client.patch("/api/ideas/no-existe", json={"type": "trama"})
    assert resp.status_code == 404


def test_delete(client: TestClient) -> None:
    _create(client, slug="borrar")
    resp = client.delete("/api/ideas/borrar")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "slug": "borrar"}
    assert client.get("/api/ideas/borrar").status_code == 404


# ---------------------------------------------------------------------------
# R-2 / R-3 — media endpoint GET /api/ideas/media/{filename}
# ---------------------------------------------------------------------------

def test_media_traversal_rejected(client: TestClient) -> None:
    """Path traversal is rejected with 400 (S-2.1).

    Backslash is not a URL path separator, so ``..\\..\\etc\\passwd`` survives
    HTTP path normalization and reaches the ``{filename}`` param intact,
    exercising the endpoint's ``..``/``\\`` rejection.
    """
    resp = client.get("/api/ideas/media/..%5C..%5Cetc%5Cpasswd")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid filename"


def test_media_dotdot_in_segment_rejected(client: TestClient) -> None:
    """A single-segment filename containing ``..`` is rejected with 400."""
    resp = client.get("/api/ideas/media/foo..bar.png")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid filename"


def test_media_absolute_path_rejected(client: TestClient) -> None:
    """Absolute path (backslash form) in filename is rejected with 400."""
    resp = client.get("/api/ideas/media/%5Cetc%5Cpasswd")
    assert resp.status_code == 400


def test_media_unsupported_extension_is_400(client: TestClient) -> None:
    """Non-image extensions are rejected with 400 (R-3)."""
    resp = client.get("/api/ideas/media/notes.txt")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Unsupported file type"


def test_media_missing_file_is_404(client: TestClient) -> None:
    """Missing file returns 404 even for a valid image extension."""
    resp = client.get("/api/ideas/media/no-such.png")
    assert resp.status_code == 404


def test_media_valid_file_served_with_mime(client: TestClient, tmp_path: Path) -> None:
    """Valid image is served with 200 and correct Content-Type (S-2.2)."""
    media_dir = tmp_path / "ideas" / "media"
    media_dir.mkdir(parents=True)
    png = b"\x89PNG\r\n\x1a\nfakedata"
    (media_dir / "test.png").write_bytes(png)
    resp = client.get("/api/ideas/media/test.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == png


def test_media_jpeg_mime(client: TestClient, tmp_path: Path) -> None:
    """JPEG files are served with image/jpeg Content-Type."""
    media_dir = tmp_path / "ideas" / "media"
    media_dir.mkdir(parents=True)
    (media_dir / "foto.jpg").write_bytes(b"\xff\xd8\xff\xe0jpegdata")
    resp = client.get("/api/ideas/media/foto.jpg")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


# ---------------------------------------------------------------------------
# R-CG-04 — materialize
# ---------------------------------------------------------------------------

def test_materialize_updates_used_in(client: TestClient) -> None:
    _create(client)
    resp = client.post(
        "/api/ideas/arquero-ciego/materialize", json={"world": "vibrantes"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["used_in"] == ["vibrantes"]
    idea = client.get("/api/ideas/arquero-ciego").json()
    assert idea["used_in"] == ["vibrantes"]
    assert idea["status"] == "used"


def test_materialize_with_canon_rel(client: TestClient, tmp_path: Path) -> None:
    _create(client, slug="arquero-ciego")
    ficha = tmp_path / "mundos" / "vibrantes" / "lore" / "El_Arquero.md"
    ficha.parent.mkdir(parents=True)
    ficha.write_text("---\ntype: personaje\ntitle: El Arquero\n---\n# El Arquero\n",
                     encoding="utf-8")
    resp = client.post(
        "/api/ideas/arquero-ciego/materialize",
        json={"world": "vibrantes", "canon_rel": "lore/El_Arquero.md"},
    )
    assert resp.status_code == 200
    assert resp.json()["canon_path"] == str(ficha)
    assert "based_on: ideas/arquero-ciego" in ficha.read_text(encoding="utf-8")


def test_materialize_missing_is_404(client: TestClient) -> None:
    resp = client.post("/api/ideas/no-existe/materialize", json={"world": "vibrantes"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth guard (mirrors sibling routers: fail closed)
# ---------------------------------------------------------------------------

def test_all_routes_require_auth(tmp_path: Path) -> None:
    closed, _ = _make_closed_client(tmp_path)
    for method, url in [
        ("get", "/api/ideas"),
        ("get", "/api/ideas/x"),
        ("post", "/api/ideas"),
        ("patch", "/api/ideas/x"),
        ("delete", "/api/ideas/x"),
        ("post", "/api/ideas/x/materialize"),
        ("get", "/api/ideas/media/test.png"),
    ]:
        kwargs = {"json": {"slug": "x", "type": "personaje", "body": "x",
                           "world": "vibrantes"}} if method in ("post", "patch") else {}
        resp = getattr(closed, method)(url, **kwargs)
        assert resp.status_code == 401, f"{method.upper()} {url} must be 401"


# ---------------------------------------------------------------------------
# Canon safety (R-IB-05) — structural: ideas/ is a sibling of mundos/
# ---------------------------------------------------------------------------

def test_idea_file_never_lands_in_mundos(client: TestClient, tmp_path: Path) -> None:
    _create(client, slug="arquero-ciego")
    assert (tmp_path / "ideas" / "arquero-ciego.md").is_file()
    assert not (tmp_path / "mundos" / "ideas").exists()
    assert not (tmp_path / "mundos" / "arquero-ciego.md").exists()


def _make_closed_client(tmp_path: Path) -> tuple[TestClient, Path]:
    app = FastAPI()
    app.include_router(
        create_ideas_bank_router(
            require_principal=lambda request: None,
            ideas_root=tmp_path / "ideas",
            mundos_root=tmp_path / "mundos",
        )
    )
    return TestClient(app), tmp_path