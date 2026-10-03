# -*- coding: utf-8 -*-
"""Pin the install-time auth default (design S0-A / tasks 0.5).

The pre-mortem (PM-1) proved that ``_auth_mode()`` defaults to ``disabled``
(api_server.py:1280-1282) and that every gated write 401s on a fresh install
unless an auth mode reaches the process environment. The existing suite hides
this path (``test_api_server.py:119`` delenvs the variable and ``:203-204``
monkeypatches ``_resolve_principal``). These tests un-hide it and pin the S0-A
contract:

- the app is ENV-ONLY for auth: a data-root ``.env`` sitting on disk changes
  nothing until the launcher parses and exports it (the launcher is the
  bridge between the installer's seed and ``_auth_mode()``);
- with the seed exported, a loopback local-dev session makes gated writes
  succeed (2xx) — the fresh-install posture (single-user, loopback-bound).

``_seed_data_root_env`` and ``_launcher_export`` model the S3a installer seed
and the S2a launcher export so the contract is pinned BEFORE those slices
land. ``test_install_auth_gated_write.py`` is the end-to-end RED harness that
requires the real seed/launcher to exist.
"""

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

INSTALL_AUTH_SEED = "DEMIURGOS_AUTH_MODE=local-dev\nDEMIURGOS_LANGUAGE=es\n"


def _seed_data_root_env(data_root: Path) -> Path:
    """S3a contract: seed ``<data_root>/.env`` once, never overwrite."""
    env_file = data_root / ".env"
    if not env_file.exists():
        env_file.write_text(INSTALL_AUTH_SEED, encoding="utf-8")
    return env_file


def _launcher_export(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """S2a contract: parse ``<data_root>/.env`` in pure shell and export it."""
    env_file = data_root / ".env"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            monkeypatch.setenv(key.strip(), value.strip().strip('"').strip("'"))


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
    api_server._GUIDED_SESSIONS = api_server.DurableGuidedSessionStore(
        db_path=tmp_path / "guided-sessions.sqlite3")
    api_server._IMPORT_STORE = None
    api_server._last_purge_at = None
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _delete_json(client: TestClient, url: str, payload: dict):
    """DELETE with a JSON body (httpx2 delete() has no body kwargs)."""
    return client.request("DELETE", url, json=payload)


class TestAuthDefaultBaseline:
    def test_unseeded_env_returns_401(self, client: TestClient):
        """No data-root .env, process env unset -> gated write fails closed."""
        assert "DEMIURGOS_AUTH_MODE" not in os.environ
        response = _delete_json(client, "/api/worlds/Avalor", {"confirm_name": "Avalor"})
        assert response.status_code == 401, response.text

    def test_seeded_env_without_launcher_export_returns_401(
        self, client: TestClient, tmp_path: Path
    ):
        """A .env on disk changes nothing by itself: the app is env-only and
        the launcher is the bridge. Pins the S0-A two-step contract."""
        _seed_data_root_env(tmp_path)
        response = _delete_json(client, "/api/worlds/Avalor", {"confirm_name": "Avalor"})
        assert response.status_code == 401, response.text

    def test_seeded_env_with_launcher_export_returns_2xx(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Seed + launcher export -> local-dev mode -> gated write is 2xx."""
        _seed_data_root_env(tmp_path)
        _launcher_export(tmp_path, monkeypatch)
        assert api_server._auth_mode() == "local-dev"

        started = client.post("/api/auth/local-dev/session")
        assert started.status_code == 200, started.text

        response = _delete_json(client, "/api/worlds/Avalor", {"confirm_name": "Avalor"})
        assert response.status_code == 200, response.text
        assert response.json()["world_name"] == "Avalor"