# -*- coding: utf-8 -*-
"""tests/test_bug_report_router.py — ``/api/bugreport`` router (Slice S1b).

Slice S1b ships ONLY the read-only assemble endpoint (``GET
/api/bugreport/assemble``). Submit, fallback, caps, rate limiting and the relay
arrive in later slices; the tests here cover exactly the S1b contract:

* fail-closed 401 auth for a missing principal;
* the bundle exposes ONLY allow-listed keys (default-DENY posture);
* world data (``mundos/``), ``.env`` and the local account username are excluded
  BY CONSTRUCTION — the handler opens only ``install_root/logs``;
* a log line matching a shared secret rule is redacted before it can be
  previewed or submitted.

The app is hermetic: a bare ``FastAPI()`` with an injected ``require_principal``
and an injected ``log_source``, so no real install state, data root or network
is ever touched (mirrors ``test_update_router.py`` / ``test_system_control.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from bug_report import (  # noqa: E402
    ALLOWED_FIELDS,
    ALLOWED_PLATFORM_KEYS,
    create_bug_report_router,
)

AUTH_REQUIRED = {"detail": "Autenticación requerida"}

# Matches the shared ``bot-token`` rule (``[0-9]{8,10}:[A-Za-z0-9_-]{35}``).
BOT_TOKEN = "1234567890:" + "A" * 35

_TOP_LEVEL_KEYS = {"app_version", "platform", "logs", "allow_list", "contact_slot"}


class _FakePrincipal:
    def __init__(self, pid: str = "tester"):
        self.id = pid


def _make_app(
    *,
    install_root: Path | None = None,
    log_source=None,
    authed: bool = True,
    app_version: str = "0.2.0",
) -> FastAPI:
    """Build a hermetic app around the bug-report router."""

    def _require_principal(_request):
        return _FakePrincipal() if authed else None

    app = FastAPI()
    app.include_router(
        create_bug_report_router(
            _require_principal,
            app_version=lambda: app_version,
            install_root=install_root,
            log_source=log_source,
        )
    )
    return app


def _seed_install_tree(tmp_path: Path) -> Path:
    """Seed a tmp install root with benign logs AND world-data/``.env`` canaries.

    The canaries make the exclusion assertions meaningful: if the assemble
    handler ever read the world-data root or ``.env``, one of them would leak
    into the response.
    """
    install_root = tmp_path / "install"
    (install_root / "logs").mkdir(parents=True)
    (install_root / "logs" / "demiurgos-api.log").write_text(
        "server started\nlistening on http://localhost:8001\n", encoding="utf-8"
    )
    worlds = install_root / "mundos"
    worlds.mkdir()
    (worlds / "secreto.md").write_text(
        "CANARY_WORLD a hidden world body\n", encoding="utf-8"
    )
    (install_root / ".env").write_text(
        "CANARY_ENV=super-secret-value\n", encoding="utf-8"
    )
    return install_root


def _log_source_from(install_root: Path):
    """An injected log source that reads ONLY ``install_root/logs`` (prod shape)."""

    def _source():
        pairs = []
        for path in sorted((install_root / "logs").glob("*.log")):
            pairs.append(
                (path.name, path.read_text(encoding="utf-8", errors="replace"))
            )
        return pairs

    return _source


# ---------------------------------------------------------------------------
# Fail-closed auth (spec: submit/assemble are principal-gated)
# ---------------------------------------------------------------------------


def test_assemble_requires_principal(tmp_path: Path) -> None:
    install_root = _seed_install_tree(tmp_path)
    app = _make_app(
        install_root=install_root,
        log_source=_log_source_from(install_root),
        authed=False,
    )
    resp = TestClient(app).get("/api/bugreport/assemble")
    assert resp.status_code == 401
    assert resp.json() == AUTH_REQUIRED


# ---------------------------------------------------------------------------
# Default-DENY allow-list (spec: 'Assemble returns exactly the allow-listed keys')
# ---------------------------------------------------------------------------


def test_assemble_returns_only_allowlisted_keys(tmp_path: Path) -> None:
    install_root = _seed_install_tree(tmp_path)
    app = _make_app(
        install_root=install_root, log_source=_log_source_from(install_root)
    )
    resp = TestClient(app).get("/api/bugreport/assemble")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Exactly the allow-listed top-level keys — nothing outside the list.
    assert set(body.keys()) == _TOP_LEVEL_KEYS
    assert set(body["platform"].keys()) <= ALLOWED_PLATFORM_KEYS
    assert set(body["allow_list"]) == set(ALLOWED_FIELDS)
    assert body["app_version"] == "0.2.0"
    # No identity key of any kind is assembled.
    assert "username" not in body
    assert "contact" not in body


# ---------------------------------------------------------------------------
# Exclusion by construction (spec: world data / `.env` / username)
# ---------------------------------------------------------------------------


def test_assemble_excludes_env_world_username(tmp_path: Path) -> None:
    install_root = _seed_install_tree(tmp_path)
    app = _make_app(
        install_root=install_root, log_source=_log_source_from(install_root)
    )
    resp = TestClient(app).get("/api/bugreport/assemble")
    assert resp.status_code == 200, resp.text
    text = resp.text
    # The benign log content IS assembled (proving the logs path is live)...
    assert "server started" in text
    # ...but no world-data, `.env` or username content ever reaches the bundle.
    assert "CANARY_WORLD" not in text
    assert "CANARY_ENV" not in text
    assert "secreto" not in text
    assert "super-secret-value" not in text


# ---------------------------------------------------------------------------
# Secret redaction (spec: 'A log line containing a secret is redacted or blocked')
# ---------------------------------------------------------------------------


def test_assemble_redacts_secret_log_line(tmp_path: Path) -> None:
    def _leaky_source():
        return [
            ("demiurgos-api.log", "boot\nleaked token %s\nready" % BOT_TOKEN),
        ]

    app = _make_app(install_root=tmp_path, log_source=_leaky_source)
    resp = TestClient(app).get("/api/bugreport/assemble")
    assert resp.status_code == 200, resp.text
    logs = resp.json()["logs"]
    assert logs["included"] is True
    # The raw secret never appears; the line is replaced by its rule placeholder.
    assert BOT_TOKEN not in logs["content"]
    assert "[redacted:" in logs["content"]
    assert logs["redacted_lines"] == 1
    # Useful reproduction structure survives around the redacted line.
    assert "boot" in logs["content"]
    assert "ready" in logs["content"]


# ---------------------------------------------------------------------------
# Registration smoke: the production app imports cleanly and exposes the route
# ---------------------------------------------------------------------------


def test_assemble_registered_in_api_server_app() -> None:
    """The production ``api_server`` app registers the assemble route.

    Importing the real app doubles as the clean-import smoke check for the
    ``include_router`` wiring (mirrors ``test_system_control``). The endpoint
    itself is NOT invoked here: against the real app it requires an
    authenticated local session, so registration is asserted through the
    OpenAPI schema instead.
    """
    import api_server  # noqa: F401

    # Included routers are nested behind wrapper objects in app.routes, so the
    # OpenAPI schema is the reliable surface to assert registration.
    paths = api_server.app.openapi()["paths"]
    assert "/api/bugreport/assemble" in paths
