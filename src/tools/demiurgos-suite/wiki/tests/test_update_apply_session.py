# -*- coding: utf-8 -*-
"""The accepted update apply clears the REAL caller session, once.

``test_update_router`` proves the router contract with an injected spy. This
file proves the production wiring: ``api_server._clear_request_session``
removes the session the request authenticated with, in memory and on disk, and
only after the apply is accepted.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402
import updater  # noqa: E402
from test_api_auth import _create_account, _login, _make_vault_client  # noqa: E402


class _Proc:
    def poll(self):
        return None


def _apply_app() -> FastAPI:
    """The production wiring of the update router, on a minimal app."""
    app = FastAPI()
    app.include_router(
        updater.create_update_router(
            lambda request: api_server._resolve_principal(request),
            app_version=lambda: "0.1.1",
            install_root=None,
            local_state=api_server._local_state,
            install_argv=["/bin/true"],
            install_available=True,
            channel_fetch=lambda url: "0.2.0",
            clear_session=api_server._clear_request_session,
        )
    )
    return app


def test_accepted_apply_clears_the_real_session_and_spawns_once(
    tmp_path: Path, monkeypatch
) -> None:
    client = _make_vault_client(tmp_path, monkeypatch, vault_enabled=True)
    _create_account(client, password=None)
    token = _login(client)
    token_hash = api_server._hash_token(token)

    spawns: list[dict] = []

    def fake_popen(argv, **kwargs):
        spawns.append(kwargs)
        return _Proc()

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)

    apply_client = TestClient(
        _apply_app(), base_url="http://testserver", client=("127.0.0.1", 50000),
    )
    apply_client.cookies.set(api_server._SESSION_COOKIE, token, domain="", path="/")
    resp = apply_client.post("/api/update/apply")

    assert resp.status_code == 200, resp.text
    assert len(spawns) == 1
    assert spawns[0]["start_new_session"] is True
    assert spawns[0]["stderr"] is not subprocess.PIPE
    with api_server._local_session_lock:
        assert token_hash not in api_server._sessions
    assert client.get("/api/auth/session/status").json()["authenticated"] is False
    sessions_file = api_server._sessions_file()
    if sessions_file.exists():
        assert token_hash not in sessions_file.read_text(encoding="utf-8")


def test_unauthenticated_apply_clears_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    client = _make_vault_client(tmp_path, monkeypatch, vault_enabled=True)
    _create_account(client, password=None)
    token = _login(client)
    token_hash = api_server._hash_token(token)

    spawns: list[dict] = []
    monkeypatch.setattr(
        updater.subprocess, "Popen",
        lambda *args, **kwargs: spawns.append(kwargs) or _Proc(),
    )

    resp = TestClient(
        _apply_app(), base_url="http://testserver", client=("127.0.0.1", 50000),
    ).post("/api/update/apply")

    assert resp.status_code == 401
    assert spawns == []
    with api_server._local_session_lock:
        assert token_hash in api_server._sessions
