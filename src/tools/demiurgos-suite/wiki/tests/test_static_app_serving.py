# -*- coding: utf-8 -*-
"""Hermetic static SPA serving tests (design S1-1..S1-6 / tasks 1.1-1.6).

The S1 catch-all ``@app.get("/{full_path:path}")`` serves the prebuilt
same-origin SPA. Every test here points ``DEMIURGOS_FRONTEND_DIST`` at a
``tmp_path`` fixture — NEVER the working-tree ``frontend/dist`` (which exists
and is gitignored; the suite-level ``hermetic_frontend_dist`` fixture in
``conftest.py`` keeps it inert for every other test).

Coverage contract (design §7 "Static serving (S1)"):
- index served ``text/html``; hashed asset served with the FIXED content type
  (explicitly ``.js`` -> ``text/javascript``, never ``mimetypes``);
- deep-link (client route) falls back to ``index.html``;
- known ``/api`` endpoint still responds; bare ``/api`` and unknown
  ``/api/...`` stay on the API's JSON 404, never ``index.html``;
- absent dist -> 503 ``app.not_served`` while ``/api/*`` and ``/health`` work;
- path traversal is rejected (containment check, never escapes the dist dir);
- ``/health``, ``/docs``, ``/redoc``, ``/openapi.json`` keep working
  (registered before the catch-all — regression, not a fix);
- cache policy: ``index.html`` revalidates (``no-cache``), ``/assets/*``
  immutable long-cache;
- ``_frontend_dist()`` precedence: env > patched attribute > ``_CODE_ROOT``
  default (S1-2 / task 1.9).
"""

from __future__ import annotations

import os
import sys
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

INDEX_MARKER = "Demiurgos SPA shell"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with a temp data root and two sample worlds."""
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
    api_server._GUIDED_SESSIONS = api_server.DurableGuidedSessionStore(
        db_path=tmp_path / "guided-sessions.sqlite3")
    api_server._IMPORT_STORE = None
    api_server._last_purge_at = None
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture()
def dist_dir(tmp_path: Path) -> Path:
    """A minimal Vite-shaped dist: index + hashed assets."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><head><title>Demiurgos</title></head>"
        '<body><div id="root"></div>'
        '<script type="module" src="/assets/app.abc123.js"></script>'
        f"<!-- {INDEX_MARKER} --></body></html>",
        encoding="utf-8",
    )
    (dist / "assets" / "app.abc123.js").write_text('console.log("app");\n', encoding="utf-8")
    (dist / "assets" / "app.abc123.css").write_text("body { color: #333; }\n", encoding="utf-8")
    (dist / "assets" / "app.abc123.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n', encoding="utf-8"
    )
    return dist


@pytest.fixture()
def dist_client(
    client: TestClient, dist_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    """Client with ``DEMIURGOS_FRONTEND_DIST`` staged at the fixture dist."""
    monkeypatch.setenv("DEMIURGOS_FRONTEND_DIST", str(dist_dir))
    return client


class TestIndexAndAssets:
    def test_root_serves_index_html(self, dist_client: TestClient):
        resp = dist_client.get("/")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/html")
        assert INDEX_MARKER in resp.text
        # index revalidates every load so a post-update hash change is seen
        assert resp.headers["cache-control"] == "no-cache"

    def test_hashed_js_asset_fixed_content_type(self, dist_client: TestClient):
        """``.js`` must be ``text/javascript`` — the Windows-mimetypes trap."""
        resp = dist_client.get("/assets/app.abc123.js")
        assert resp.status_code == 200, resp.text
        # Starlette appends "; charset=utf-8" to text/* types — assert the
        # fixed-map type, and that mimetypes' Windows "text/plain" never leaks.
        assert resp.headers["content-type"].startswith("text/javascript")
        assert not resp.headers["content-type"].startswith("text/plain")
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"

    def test_css_asset_content_type(self, dist_client: TestClient):
        resp = dist_client.get("/assets/app.abc123.css")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/css")

    def test_svg_asset_content_type(self, dist_client: TestClient):
        resp = dist_client.get("/assets/app.abc123.svg")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "image/svg+xml"

    def test_deep_link_falls_back_to_index(self, dist_client: TestClient):
        """A client route (SPA path, no file) gets the shell, not a 404."""
        resp = dist_client.get("/wiki/Avalor/lore/inicio")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/html")
        assert INDEX_MARKER in resp.text
        assert resp.headers["cache-control"] == "no-cache"


class TestApiPrecedence:
    def test_known_api_endpoint_still_served(self, dist_client: TestClient):
        resp = dist_client.get("/api/worlds")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("application/json")

    def test_bare_api_path_returns_api_404_not_index(self, dist_client: TestClient):
        resp = dist_client.get("/api")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not Found"}
        assert INDEX_MARKER not in resp.text

    def test_unknown_api_route_returns_json_404_not_index(
        self, dist_client: TestClient
    ):
        resp = dist_client.get("/api/no-such-route")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not Found"}
        assert INDEX_MARKER not in resp.text

    def test_get_on_post_only_api_route_keeps_405(
        self, dist_client: TestClient
    ):
        """The catch-all must not hide Starlette's 405 behind the carve-out 404.

        ``/api/migration/execute`` is a POST-only route; a GET on it is a
        method mismatch (405), not an unknown path (404).
        """
        resp = dist_client.get("/api/migration/execute")
        assert resp.status_code == 405, resp.text
        assert resp.json() == {"detail": "Method Not Allowed"}
        assert INDEX_MARKER not in resp.text


class TestAbsentDist:
    def test_absent_dist_503_while_api_and_health_stay_reachable(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Explicit absent-dist case: env points at a non-existent path."""
        monkeypatch.setenv("DEMIURGOS_FRONTEND_DIST", str(tmp_path / "no-dist"))
        resp = client.get("/")
        assert resp.status_code == 503, resp.text
        assert resp.json()["code"] == "app.not_served"
        assert INDEX_MARKER not in resp.text

        assert client.get("/api/worlds").status_code == 200
        assert client.get("/health").status_code == 200

    def test_dist_dir_without_index_is_absent(self, client: TestClient, tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch):
        empty_dist = tmp_path / "empty-dist"
        empty_dist.mkdir()
        monkeypatch.setenv("DEMIURGOS_FRONTEND_DIST", str(empty_dist))
        resp = client.get("/")
        assert resp.status_code == 503, resp.text
        assert resp.json()["code"] == "app.not_served"


class TestTraversal:
    ENC_DOTS = "%2e%2e"

    def test_traversal_is_rejected_never_served(
        self, dist_client: TestClient, dist_dir: Path
    ):
        # A secret planted OUTSIDE the dist dir must never be reachable.
        secret = dist_dir.parent / "secret.txt"
        secret.write_text("TOP SECRET\n", encoding="utf-8")
        resp = dist_client.get(f"/{self.ENC_DOTS}/{self.ENC_DOTS}/secret.txt")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not Found"}
        assert "TOP SECRET" not in resp.text
        assert INDEX_MARKER not in resp.text

    def test_nested_traversal_rejected(
        self, dist_client: TestClient, dist_dir: Path
    ):
        secret = dist_dir.parent / "secret.txt"
        secret.write_text("TOP SECRET\n", encoding="utf-8")
        resp = dist_client.get(f"/assets/{self.ENC_DOTS}/{self.ENC_DOTS}/secret.txt")
        assert resp.status_code == 404, resp.text
        assert "TOP SECRET" not in resp.text


class TestDocsHealthRegression:
    def test_health_still_ok(self, dist_client: TestClient):
        assert dist_client.get("/health").status_code == 200

    def test_docs_still_ok(self, dist_client: TestClient):
        assert dist_client.get("/docs").status_code == 200

    def test_redoc_still_ok(self, dist_client: TestClient):
        assert dist_client.get("/redoc").status_code == 200

    def test_openapi_still_ok(self, dist_client: TestClient):
        resp = dist_client.get("/openapi.json")
        assert resp.status_code == 200, resp.text
        assert resp.json()["openapi"].startswith("3.")


class TestFrontendDistResolution:
    def test_env_override_wins_over_patched_and_default(
        self, monkeypatch: pytest.MonkeyPatch, dist_dir: Path
    ):
        """S1-2 / task 1.9: the env override wins over ``_CODE_ROOT``."""
        monkeypatch.setenv("DEMIURGOS_FRONTEND_DIST", str(dist_dir))
        monkeypatch.setattr(api_server, "FRONTEND_DIST", dist_dir.parent / "patched")
        assert api_server._frontend_dist() == dist_dir

    def test_patched_attribute_wins_over_code_root_default(
        self, monkeypatch: pytest.MonkeyPatch, dist_dir: Path
    ):
        monkeypatch.delenv("DEMIURGOS_FRONTEND_DIST", raising=False)
        patched = dist_dir.parent / "patched-dist"
        monkeypatch.setattr(api_server, "FRONTEND_DIST", patched)
        assert api_server._frontend_dist() == patched

    def test_default_is_code_root_frontend_dist(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("DEMIURGOS_FRONTEND_DIST", raising=False)
        monkeypatch.setattr(api_server, "FRONTEND_DIST", None)
        assert api_server._frontend_dist() == api_server._CODE_ROOT / "frontend" / "dist"