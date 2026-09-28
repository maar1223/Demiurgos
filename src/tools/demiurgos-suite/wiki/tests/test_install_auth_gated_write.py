# -*- coding: utf-8 -*-
"""End-to-end install-auth gated-write harness (design S0-A / tasks 0.6).

Models the full fresh-install chain on a clean machine:

1. a fresh payload is staged (a clean checkout of the app tree);
2. a fresh data root exists with NO pre-seeded ``.env`` (nothing installed);
3. ``DEMIURGOS_AUTH_MODE`` is UNSET in the process environment;
4. the installer (S3a) seeds ``<data_root>/.env`` and the launcher (S2a)
   parses it and exports ``DEMIURGOS_AUTH_MODE`` into uvicorn's env;
5. the app boots and an end-to-end gated write must return **2xx, not 401**.

Step 4 is the seed contract. Until S2a/S3a land, no shipping code performs it:
the harness stands in with ``_apply_install_auth_seed`` below, which refuses to
run when the contract is not wired — so this test is **RED by construction in
PR 0** (recorded honestly, NOT faked green). When S3a (installer seed) and S2a
(launcher export) exist, the stand-in is replaced by the real
installer/launcher invocation and this test becomes the permanent regression
guard: a fresh install must never boot into a 401 for gated writes again.
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


def _apply_install_auth_seed(data_root: Path) -> None:
    """S0-A seed contract — stand-in for the S3a installer + S2a launcher.

    On a clean machine the INSTALLER writes ``<data_root>/.env`` exactly once
    and the LAUNCHER exports ``DEMIURGOS_AUTH_MODE`` from it before starting
    uvicorn. Neither exists in PR 0, so this stand-in fails with a single
    explicit error instead of pretending the chain works (expected RED until
    S2a/S3a wire the seed).
    """
    env_file = data_root / ".env"
    if not env_file.is_file():
        raise AssertionError(
            "install auth seed contract is not wired yet: "
            f"{env_file} does not exist. The S3a installer must seed "
            "<data_root>/.env and the S2a launcher must export it before "
            "this end-to-end gated-write harness can be GREEN. "
            "Expected RED in PR 0 (tasks 0.6)."
        )
    exported: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            exported[key.strip()] = value.strip().strip('"').strip("'")
    if "DEMIURGOS_AUTH_MODE" not in exported:
        raise AssertionError("seeded .env must carry DEMIURGOS_AUTH_MODE=local-dev")
    os.environ["DEMIURGOS_AUTH_MODE"] = exported["DEMIURGOS_AUTH_MODE"]


@pytest.fixture()
def fresh_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Boot the app against a fresh data root; returns the booted client."""
    data_root = tmp_path / "data-root"
    data_root.mkdir()
    (data_root / "mundos").mkdir()
    for name in ("Avalor", "Kaelia"):
        (data_root / "mundos" / name / "lore").mkdir(parents=True)
        (data_root / "mundos" / name / "lore" / "inicio.md").write_text(
            "# Inicio\n", encoding="utf-8"
        )

    monkeypatch.setattr(api_server, "MUNDOS_DIR", data_root / "mundos")
    monkeypatch.setattr(api_server, "PROJECT_ROOT", data_root)
    monkeypatch.setattr(api_server, "TRASH_ROOT", tmp_path / "world-trash")
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    api_server._graph_indices.clear()
    api_server._GUIDED_SESSIONS = api_server.DurableGuidedSessionStore(
        db_path=tmp_path / "guided-sessions.sqlite3")
    api_server._IMPORT_STORE = None
    api_server._last_purge_at = None
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    return client, data_root


def _delete_json(client: TestClient, url: str, payload: dict):
    """DELETE with a JSON body (httpx2 delete() has no body kwargs)."""
    return client.request("DELETE", url, json=payload)


class TestInstallAuthGatedWrite:
    def test_fresh_install_gated_write_is_2xx_not_401(
        self, fresh_install: tuple[TestClient, Path]
    ):
        client, data_root = fresh_install

        # Fresh machine: no seed anywhere, auth mode UNSET in the process env.
        assert not (data_root / ".env").exists()
        assert "DEMIURGOS_AUTH_MODE" not in os.environ

        # The app is booted; without the seed contract it fails closed.
        unseeded = _delete_json(client, "/api/worlds/Avalor", {"confirm_name": "Avalor"})
        assert unseeded.status_code == 401, unseeded.text

        # Install chain: seed the data-root .env and let the launcher export
        # take effect. RED by construction until S2a/S3a wire the seed.
        _apply_install_auth_seed(data_root)

        started = client.post("/api/auth/local-dev/session")
        assert started.status_code == 200, started.text

        response = _delete_json(client, "/api/worlds/Avalor", {"confirm_name": "Avalor"})
        assert response.status_code == 200, response.text  # 2xx, not 401
        assert response.json()["world_name"] == "Avalor"