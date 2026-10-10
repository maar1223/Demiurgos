# -*- coding: utf-8 -*-
"""Idea-capture configuration panel endpoints (Profile → Integraciones → Captura de ideas).

Covers the temporary MVP contract: local-auth gating (fail closed), strict
config validation with empty allowlists preserved, secret non-disclosure for
TELEGRAM_BOT_TOKEN, and the exact serve command/readiness for the local
runtime. The round-trip tests load the written yaml with the REAL runtime
loader (idea_capture.config.load_policy) so the panel can never persist a
file the runtime refuses to parse.
"""

import logging
import os
import sys
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
_TOOLS = _SUITE.parent
for _p in (str(_WIKI), str(_SUITE), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402
import idea_capture_ui  # noqa: E402
from idea_capture.config import load_policy  # noqa: E402
from idea_capture.models import (  # noqa: E402
    CaptureRecord,
    CaptureState,
    MediaInput,
    MediaKind,
    TelegramUpdate,
)
from idea_capture.store import CaptureStore  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a sandboxed repo root (config/, .env, mundos/) and a
    sample world; auth disabled by default so gating tests fail closed."""
    root = tmp_path
    (root / "mundos" / "vibrantes" / "lore").mkdir(parents=True)
    (root / "mundos" / "vibrantes" / "lore" / "a.md").write_text("# A", encoding="utf-8")

    monkeypatch.setattr(idea_capture_ui, "REPO_ROOT", root)
    monkeypatch.setattr(api_server, "MUNDOS_DIR", root / "mundos")
    monkeypatch.setattr(api_server, "PROJECT_ROOT", root)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    api_server._graph_indices.clear()
    api_server._confirmation_store.clear()
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    api_server._target_locks.clear()
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _authed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind the panel endpoints to a trusted test principal."""
    monkeypatch.setattr(
        api_server,
        "_resolve_principal",
        lambda request: api_server.EditPrincipal("panel-tester"),
    )


def _save_config(client: TestClient, config: dict) -> TestClient:
    resp = client.put("/api/idea-capture/config", json={"config": config})
    assert resp.status_code == 200, resp.text
    return client


class TestAuthGate:
    """Every panel route fails closed without a trusted local principal."""

    def test_status_requires_local_session(self, client: TestClient):
        assert client.get("/api/idea-capture/status").status_code == 401

    def test_config_requires_local_session(self, client: TestClient):
        resp = client.put("/api/idea-capture/config",
                          json={"config": idea_capture_ui.default_config()})
        assert resp.status_code == 401

    def test_set_token_requires_local_session(self, client: TestClient):
        assert client.post("/api/idea-capture/token",
                           json={"token": "123:AA"}).status_code == 401

    def test_clear_token_requires_local_session(self, client: TestClient):
        assert client.delete("/api/idea-capture/token").status_code == 401

    def test_real_local_session_cookie_grants_access(self, client: TestClient,
                                                     monkeypatch: pytest.MonkeyPatch):
        """End-to-end: the server-issued loopback session unlocks the panel."""
        monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
        started = client.post("/api/auth/local-dev/session")
        assert started.status_code == 200, started.text
        assert client.get("/api/idea-capture/status").status_code == 200


class TestStatus:
    def test_default_status_is_fail_closed(self, client: TestClient,
                                           monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        data = client.get("/api/idea-capture/status").json()
        assert data["config"]["private_chat_ids"] == []
        assert data["config"]["approved_groups"] == {}
        assert data["config"]["active_world"] == ""
        assert data["has_token"] is False
        assert data["validation"] == {"ok": True, "errors": []}
        assert data["serve"]["runnable"] is False
        assert any("vacías" in reason for reason in data["serve"]["blocked_reasons"])
        assert "vibrantes" in data["worlds"]
        assert data["limitations"]

    def test_status_reflects_written_config(self, client: TestClient,
                                            monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _save_config(client, {
            "private_chat_ids": [111, 222],
            "approved_groups": {"-100999": [333, 444]},
            "active_world": "vibrantes",
            "limits": {"image_mb": 25, "audio_mb": 60, "audio_minutes": 7,
                       "raw_retention_days": 45},
        })
        data = client.get("/api/idea-capture/status").json()
        assert data["config"]["private_chat_ids"] == [111, 222]
        assert data["config"]["approved_groups"] == {"-100999": [333, 444]}
        assert data["config"]["active_world"] == "vibrantes"
        assert data["config"]["limits"]["raw_retention_days"] == 45
        assert data["validation"]["ok"] is True
        # Ready: allowlists non-empty — only the token is missing. A world is
        # NOT required (capture goes to the global Taller de Ideas).
        assert data["serve"]["runnable"] is False
        assert any("TELEGRAM_BOT_TOKEN" in r for r in data["serve"]["blocked_reasons"])

    def test_serve_status_does_not_require_world(self, client: TestClient,
                                                 monkeypatch: pytest.MonkeyPatch):
        """Capture enables for the global Taller without any active_world: the
        serve readiness only gates on token + non-empty allowlists."""
        _authed(monkeypatch)
        _save_config(client, {
            "private_chat_ids": [111],
            "approved_groups": {},
            "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                       "raw_retention_days": 30},
        })
        _set_token(client)
        data = client.get("/api/idea-capture/status").json()
        assert data["config"]["active_world"] == ""
        assert data["serve"]["runnable"] is True
        assert data["serve"]["blocked_reasons"] == []

    def test_hermes_command_is_exact_for_local_runtime(self, client: TestClient,
                                                       monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        data = client.get("/api/idea-capture/status").json()
        assert "start-gateway.ps1" in data["serve"]["command"]
        assert "idea_capture serve" not in data["serve"]["command"]

    def test_malformed_yaml_reports_validation_errors(self, client: TestClient,
                                                      monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        path = idea_capture_ui._config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private_chat_ids: [oops]\n", encoding="utf-8")
        data = client.get("/api/idea-capture/status").json()
        assert data["validation"]["ok"] is False
        assert data["validation"]["errors"]


class TestConfigSave:
    def test_non_dict_body_is_rejected_as_400(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        # FastAPI rejects a non-dict JSON body with 422 before the endpoint
        # runs (also fail-closed); the endpoint itself rejects a missing
        # config/token with 400.
        assert client.put("/api/idea-capture/config", json=[1, 2]).status_code >= 400
        assert client.post("/api/idea-capture/token", json=[1, 2]).status_code >= 400
        assert client.put("/api/idea-capture/config", json={}).status_code == 400
        assert client.post("/api/idea-capture/token", json={}).status_code == 400

    def test_valid_save_round_trips_into_the_runtime_loader(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _save_config(client, {
            "private_chat_ids": [111, 222],
            "approved_groups": {"-100999": [333, 444]},
            "active_world": "vibrantes",
            "limits": {"image_mb": 25, "audio_mb": 60, "audio_minutes": 7,
                       "raw_retention_days": 45},
        })
        path = idea_capture_ui._config_path()
        loaded = load_policy(path)  # the real runtime loader must accept it
        assert loaded.policy.private_chat_ids == frozenset({111, 222})
        assert loaded.policy.approved_group_senders == {-100999: frozenset({333, 444})}
        assert loaded.limits.image_mb == 25
        assert loaded.limits.raw_retention_days == 45
        text = path.read_text(encoding="utf-8")
        assert "FAIL-CLOSED" in text  # guidance header preserved

    def test_empty_allowlists_are_preserved_fail_closed(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        resp = client.put("/api/idea-capture/config", json={
            "config": {
                "private_chat_ids": [],
                "approved_groups": {},
                "active_world": "vibrantes",
                "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                           "raw_retention_days": 30},
            },
        })
        assert resp.status_code == 200, resp.text
        text = idea_capture_ui._config_path().read_text(encoding="utf-8")
        assert "private_chat_ids: []" in text
        assert "approved_groups:" in text
        loaded = load_policy(idea_capture_ui._config_path())
        assert loaded.policy.private_chat_ids == frozenset()
        assert loaded.policy.approved_group_senders == {}
        data = client.get("/api/idea-capture/status").json()
        assert data["validation"]["ok"] is True
        assert any("vacías" in r for r in data["serve"]["blocked_reasons"])

    @pytest.mark.parametrize("config", [
        {"private_chat_ids": ["abc"], "approved_groups": {}, "active_world": "",
         "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                    "raw_retention_days": 30}},
        {"private_chat_ids": 123, "approved_groups": {}, "active_world": "",
         "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                    "raw_retention_days": 30}},
        {"private_chat_ids": [1.5], "approved_groups": {}, "active_world": "",
         "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                    "raw_retention_days": 30}},
        {"private_chat_ids": [], "approved_groups": [1, 2], "active_world": "",
         "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                    "raw_retention_days": 30}},
        {"private_chat_ids": [], "approved_groups": {"abc": [1]}, "active_world": "",
         "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                    "raw_retention_days": 30}},
        {"private_chat_ids": [], "approved_groups": {"99": "x"}, "active_world": "",
         "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                    "raw_retention_days": 30}},
        {"private_chat_ids": [], "approved_groups": {}, "active_world": "",
         "limits": {"image_mb": 0, "audio_mb": 50, "audio_minutes": 5,
                    "raw_retention_days": 30}},
        {"private_chat_ids": [], "approved_groups": {}, "active_world": "",
         "limits": {"image_mb": -3, "audio_mb": 50, "audio_minutes": 5,
                    "raw_retention_days": 30}},
        {"private_chat_ids": [], "approved_groups": {}, "active_world": "",
         "limits": {"image_mb": "big", "audio_mb": 50, "audio_minutes": 5,
                    "raw_retention_days": 30}},
        {"private_chat_ids": [], "approved_groups": {}, "active_world": "../etc",
         "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                    "raw_retention_days": 30}},
    ])
    def test_invalid_config_is_rejected_and_file_untouched(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch, config: dict):
        _authed(monkeypatch)
        path = idea_capture_ui._config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private_chat_ids: []\n", encoding="utf-8")
        before = path.read_text(encoding="utf-8")

        resp = client.put("/api/idea-capture/config", json={"config": config})

        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"]
        assert path.read_text(encoding="utf-8") == before  # fail closed: no write


class TestToken:
    SECRET = "123456789:AA-test-secret"

    def test_set_token_persists_env_and_never_discloses_value(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        resp = client.post("/api/idea-capture/token", json={"token": self.SECRET})
        assert resp.status_code == 200, resp.text
        # The response carries the fresh card state alongside has_token.
        assert resp.json() == {"state": "requires_connection", "has_token": True}
        assert self.SECRET not in resp.text

        env = idea_capture_ui._env_path().read_text(encoding="utf-8")
        assert f"TELEGRAM_BOT_TOKEN={self.SECRET}" in env

        status = client.get("/api/idea-capture/status")
        assert status.status_code == 200
        assert status.json()["has_token"] is True
        assert self.SECRET not in status.text  # never in normal API responses

    def test_token_is_never_logged(self, client: TestClient,
                                   monkeypatch: pytest.MonkeyPatch, caplog):
        _authed(monkeypatch)
        with caplog.at_level(logging.INFO):
            client.post("/api/idea-capture/token", json={"token": self.SECRET})
        assert self.SECRET not in caplog.text

    def test_clear_token_removes_env_var_preserving_unrelated_lines(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        env_path = idea_capture_ui._env_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(
            "# demo comment\nDEMIURGOS_WORLD=nec\nOTHER_KEEP=1\n"
            f"TELEGRAM_BOT_TOKEN={self.SECRET}\n",
            encoding="utf-8")

        resp = client.delete("/api/idea-capture/token")
        assert resp.status_code == 200, resp.text
        # Deleting clears the token and the evidence; the card returns to pending.
        assert resp.json() == {"state": "pending", "has_token": False}

        text = env_path.read_text(encoding="utf-8")
        assert "TELEGRAM_BOT_TOKEN" not in text
        assert "# demo comment" in text
        assert "DEMIURGOS_WORLD=nec" in text
        assert "OTHER_KEEP=1" in text
        assert client.get("/api/idea-capture/status").json()["has_token"] is False

    def test_set_token_preserves_comments_and_unrelated_vars(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        env_path = idea_capture_ui._env_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(
            "# demo comment\nDEMIURGOS_WORLD=nec\nOTHER_KEEP=1\n",
            encoding="utf-8")

        client.post("/api/idea-capture/token", json={"token": self.SECRET})

        text = env_path.read_text(encoding="utf-8")
        assert f"TELEGRAM_BOT_TOKEN={self.SECRET}" in text
        assert "# demo comment" in text
        assert "DEMIURGOS_WORLD=nec" in text
        assert "OTHER_KEEP=1" in text

    @pytest.mark.parametrize("token", ["", "   ", "abc def", "x" * 300])
    def test_invalid_token_is_rejected_and_env_untouched(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch, token: str):
        _authed(monkeypatch)
        resp = client.post("/api/idea-capture/token", json={"token": token})
        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"]
        env_path = idea_capture_ui._env_path()
        if env_path.is_file():
            assert "TELEGRAM_BOT_TOKEN" not in env_path.read_text(encoding="utf-8")


def _set_token(client: TestClient, secret: str = "123456789:AA-test-secret") -> None:
    resp = client.post("/api/idea-capture/token", json={"token": secret})
    assert resp.status_code == 200, resp.text


def _sample_updates() -> list[dict]:
    """Raw getUpdates fixture: duplicates, private/groups, channel excluded."""
    return [
        {"update_id": 1, "message": {"chat": {"id": 111, "type": "private"},
                                     "from": {"id": 10, "first_name": "Ana",
                                              "last_name": "Perez"},
                                     "text": "idea secreta A"}},
        {"update_id": 2, "message": {"chat": {"id": 111, "type": "private"},
                                     "from": {"id": 10, "first_name": "Ana",
                                              "last_name": "Perez"},
                                     "text": "idea secreta A repetida"}},
        {"update_id": 3, "message": {"chat": {"id": 222, "type": "private"},
                                     "from": {"id": 11, "username": "usuario"},
                                     "text": "otra idea"}},
        {"update_id": 4, "message": {"chat": {"id": -100999, "type": "group",
                                              "title": "Equipo Narrativo"},
                                     "from": {"id": 12, "first_name": "Beto"},
                                     "text": "idea grupal"}},
        {"update_id": 5, "message": {"chat": {"id": -100777, "type": "supergroup",
                                              "title": "Canal G"},
                                     "from": {"id": 13, "first_name": "Cata"},
                                     "text": "idea de supergrupo"}},
        # channel_post and non-message updates must never become candidates
        {"update_id": 6, "channel_post": {"chat": {"id": -100555, "type": "channel",
                                                   "title": "Canal Público"},
                                          "text": "publicado"}},
        {"update_id": 7, "my_chat_member": {"chat": {"id": 333, "type": "private"}}},
    ]


class TestChatDiscoveryAuth:
    """Discovery and authorization routes fail closed without a principal."""

    def test_discover_requires_local_session(self, client: TestClient):
        assert client.post("/api/idea-capture/chats/discover").status_code == 401

    def test_authorize_requires_local_session(self, client: TestClient):
        assert client.post("/api/idea-capture/chats/authorize",
                           json={"chat_id": 1, "chat_type": "private"}).status_code == 401


class TestChatDiscovery:
    def test_discover_without_token_is_a_friendly_400(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "token" in detail.lower()

    def test_empty_updates_return_friendly_empty_result(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _set_token(client)
        monkeypatch.setattr(idea_capture_ui, "fetch_updates", lambda token: [])
        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert data["candidates"] == []
        assert "/start" in data["message"]

    def test_candidates_normalized_deduped_and_content_never_disclosed(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _set_token(client)
        monkeypatch.setattr(idea_capture_ui, "fetch_updates",
                            lambda token: _sample_updates())
        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # 111 duplicated (once), 222, -100999, -100777 -> 4; channel excluded.
        assert data["ok"] is True
        assert [c["id"] for c in data["candidates"]] == [111, 222, -100999, -100777]
        by_id = {c["id"]: c for c in data["candidates"]}
        assert by_id[111]["kind"] == "private" and by_id[111]["title"] == "Ana Perez"
        assert by_id[222]["kind"] == "private" and by_id[222]["title"] == "@usuario"
        assert by_id[-100999]["kind"] == "group" and by_id[-100999]["title"] == "Equipo Narrativo"
        assert by_id[-100777]["kind"] == "group" and by_id[-100777]["type"] == "supergroup"
        assert "idea secreta" not in resp.text  # message content never disclosed
        assert "publicado" not in resp.text
        assert "AA-test-secret" not in resp.text  # token never leaks

    def test_owner_active_refuses_with_409(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _set_token(client)
        lock = idea_capture_ui.owner_lock_path()
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()), encoding="utf-8")  # live owner
        assert idea_capture_ui.owner_is_active(lock) is True
        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 409
        assert "serve" in resp.json()["detail"].lower()

    def test_stale_owner_lock_does_not_block_discovery(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _set_token(client)
        lock = idea_capture_ui.owner_lock_path()
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999999", encoding="utf-8")  # dead pid
        assert idea_capture_ui.owner_is_active(lock) is False
        monkeypatch.setattr(idea_capture_ui, "fetch_updates", lambda token: [])
        assert client.post("/api/idea-capture/chats/discover").status_code == 200

    def test_telegram_auth_error_is_mapped_to_friendly_400(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _set_token(client)

        def bad_token_fetch(token):
            raise idea_capture_ui.TelegramDiscoveryError(
                400, "El token guardado no es válido o fue revocado.")
        monkeypatch.setattr(idea_capture_ui, "fetch_updates", bad_token_fetch)
        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 400
        assert "token" in resp.json()["detail"].lower()


class TestDiscoveryRuntimeImportFallback:
    """Regression for the persistent HTTP 500 on POST /chats/discover.

    The live wiki API server runs WITHOUT ``src/tools`` on its PYTHONPATH
    (start-api.ps1 / start-demiurgos.ps1), so the lazy
    ``from idea_capture.runtime import default_pid_alive`` inside
    ``owner_is_active`` raised ModuleNotFoundError and every authenticated
    discovery request returned an empty-body 500. The stdlib-only fallback
    probe must keep discovery working AND preserve the owner-active 409 guard
    (same semantics as ``runtime.default_pid_alive``).
    """

    @pytest.fixture()
    def runtime_unimportable(self, monkeypatch: pytest.MonkeyPatch):
        """Simulate the wiki API server environment: idea_capture absent."""
        monkeypatch.setitem(sys.modules, "idea_capture", None)
        monkeypatch.setitem(sys.modules, "idea_capture.runtime", None)

    def test_discovery_works_when_runtime_is_not_importable(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
            runtime_unimportable):
        _authed(monkeypatch)
        _set_token(client)
        monkeypatch.setattr(idea_capture_ui, "fetch_updates", lambda token: [])
        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 200, resp.text
        assert resp.json()["candidates"] == []

    def test_owner_guard_preserved_when_runtime_is_not_importable(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
            runtime_unimportable):
        _authed(monkeypatch)
        _set_token(client)
        lock = idea_capture_ui.owner_lock_path()
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()), encoding="utf-8")  # live owner
        assert idea_capture_ui.owner_is_active(lock) is True
        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 409
        assert "serve" in resp.json()["detail"].lower()

    def test_fallback_probe_semantics(self):
        """Mirrors runtime.default_pid_alive: dead/zero pids are False, the
        current process is alive."""
        assert idea_capture_ui._default_pid_alive(0) is False
        assert idea_capture_ui._default_pid_alive(os.getpid()) is True
        assert idea_capture_ui._default_pid_alive(999999999) is False


class TestDiscoveryFailSafeMapping:
    """Final fail-safe: any unexpected exception in the discovery path maps to
    a sanitized 500 with a stable ``unexpected`` code — never an empty body,
    never a traceback, never the token or message content. Auth failures stay
    401 (the guard runs before the handler) and TelegramDiscoveryError keeps
    its own status/code mapping."""

    def test_unexpected_exception_maps_to_sanitized_500(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _set_token(client)

        def boom(token):
            raise RuntimeError("secreto interno del token")
        monkeypatch.setattr(idea_capture_ui, "fetch_updates", boom)

        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 500
        body = resp.json()
        assert body["code"] == "unexpected"
        assert body["detail"]
        # Sanitized: neither the exception message nor the token leak.
        assert "secreto" not in resp.text
        assert "AA-test-secret" not in resp.text

    def test_failsafe_does_not_mask_auth_or_telegram_errors(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        # Unauthenticated -> still 401 (guard runs outside the fail-safe).
        assert client.post("/api/idea-capture/chats/discover").status_code == 401

        _authed(monkeypatch)
        _set_token(client)

        def conflict(token):
            raise idea_capture_ui.TelegramDiscoveryError(
                409, "El bot tiene un webhook activo…", code="webhook_conflict")
        monkeypatch.setattr(idea_capture_ui, "fetch_updates", conflict)

        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 409
        assert resp.json()["code"] == "webhook_conflict"

    def test_failsafe_catches_owner_probe_failures(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _set_token(client)

        def broken_owner():
            raise RuntimeError("probe falló")
        monkeypatch.setattr(idea_capture_ui, "owner_is_active", broken_owner)

        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 500
        body = resp.json()
        assert body["code"] == "unexpected"
        assert "probe" not in resp.text


class TestFetchUpgradesFailureMapping:
    """Telegram HTTP/API/network failures map to safe, actionable errors
    (never a raw 500) with a stable machine-readable ``code`` for the UI.

    Regression coverage for the "Detectar mi chat" HTTP 500 after /start:
    a stale webhook makes Telegram refuse getUpdates with 409 (description
    mentions the webhook) — the backend must identify that conflict, explain
    it, and NEVER delete the webhook automatically.
    """

    class _FakeResponse:
        def __init__(self, status_code: int, payload: dict | None,
                     invalid_json: bool = False):
            self.status_code = status_code
            self._payload = payload
            self._invalid_json = invalid_json

        def json(self) -> dict:
            if self._invalid_json:
                raise ValueError("invalid json body")
            return self._payload

    def _fake_get(self, monkeypatch: pytest.MonkeyPatch, responses: list,
                  raises: Exception | None = None):
        calls: list[tuple[str, dict]] = []

        def fake_get(url: str, **kwargs):
            calls.append((url, kwargs))
            if raises is not None:
                raise raises
            return responses.pop(0)

        monkeypatch.setattr(requests, "get", fake_get)
        return calls

    def test_409_webhook_conflict_is_identified_and_never_deleted(
            self, monkeypatch: pytest.MonkeyPatch):
        """Telegram's 409 for a stale webhook (getUpdates refused) maps to a
        409 with code webhook_conflict; the panel never issues deleteWebhook."""
        payload = {"ok": False, "error_code": 409,
                   "description": "Conflict: can't use getUpdates method while "
                                  "webhook is active. Use deleteWebhook to delete "
                                  "the webhook first."}
        calls = self._fake_get(monkeypatch, [self._FakeResponse(409, payload)])

        with pytest.raises(idea_capture_ui.TelegramDiscoveryError) as excinfo:
            idea_capture_ui.fetch_updates("123456789:AA-test-secret")

        err = excinfo.value
        assert err.status_code == 409
        assert err.code == "webhook_conflict"
        assert "webhook" in err.detail.lower()
        assert "deletewebhook" in err.detail.lower()  # actionable remediation
        assert "nunca" in err.detail  # never automatic deletion
        # Only the read-only getUpdates snapshot was requested — no
        # deleteWebhook call was ever issued.
        assert len(calls) == 1
        assert "getUpdates" in calls[0][0]
        assert "deleteWebhook" not in calls[0][0]

    def test_409_other_consumer_keeps_distinct_code(
            self, monkeypatch: pytest.MonkeyPatch):
        payload = {"ok": False, "error_code": 409,
                   "description": "Conflict: terminated by other getUpdates request"}
        self._fake_get(monkeypatch, [self._FakeResponse(409, payload)])

        with pytest.raises(idea_capture_ui.TelegramDiscoveryError) as excinfo:
            idea_capture_ui.fetch_updates("123456789:AA-test-secret")

        assert excinfo.value.status_code == 409
        assert excinfo.value.code == "conflicting_consumer"
        assert "consume" in excinfo.value.detail.lower() or "consum" in excinfo.value.detail.lower()

    def test_401_invalid_token_maps_to_friendly_400(
            self, monkeypatch: pytest.MonkeyPatch):
        self._fake_get(monkeypatch, [self._FakeResponse(
            401, {"ok": False, "error_code": 401, "description": "Unauthorized"})])

        with pytest.raises(idea_capture_ui.TelegramDiscoveryError) as excinfo:
            idea_capture_ui.fetch_updates("123456789:AA-bad")

        err = excinfo.value
        assert err.status_code == 400
        assert err.code == "invalid_token"
        assert "token" in err.detail.lower()

    def test_network_failure_maps_to_502(
            self, monkeypatch: pytest.MonkeyPatch):
        self._fake_get(monkeypatch, [], raises=requests.ConnectionError("down"))

        with pytest.raises(idea_capture_ui.TelegramDiscoveryError) as excinfo:
            idea_capture_ui.fetch_updates("123456789:AA-test-secret")

        err = excinfo.value
        assert err.status_code == 502
        assert err.code == "network"
        assert "conexión" in err.detail.lower()

    def test_non_json_body_maps_to_502_not_500(
            self, monkeypatch: pytest.MonkeyPatch):
        """An unparseable response body is a safe 502, never a raw 500."""
        self._fake_get(monkeypatch, [self._FakeResponse(200, None, invalid_json=True)])

        with pytest.raises(idea_capture_ui.TelegramDiscoveryError) as excinfo:
            idea_capture_ui.fetch_updates("123456789:AA-test-secret")

        assert excinfo.value.status_code == 502
        assert excinfo.value.code == "invalid_response"

    def test_non_list_result_maps_to_502_not_500(
            self, monkeypatch: pytest.MonkeyPatch):
        """A malformed `result` field is a safe 502, never a raw 500."""
        self._fake_get(monkeypatch, [self._FakeResponse(200, {"ok": True, "result": {"x": 1}})])

        with pytest.raises(idea_capture_ui.TelegramDiscoveryError) as excinfo:
            idea_capture_ui.fetch_updates("123456789:AA-test-secret")

        assert excinfo.value.status_code == 502
        assert excinfo.value.code == "invalid_response"

    def test_offset_loss_safeguard_is_preserved(
            self, monkeypatch: pytest.MonkeyPatch):
        """offset=-1 is always sent: discovery confirms NO pending update, so
        the real poller never loses a message."""
        calls = self._fake_get(monkeypatch, [self._FakeResponse(200, {"ok": True, "result": []})])

        result = idea_capture_ui.fetch_updates("123456789:AA-test-secret")

        assert result == []
        assert len(calls) == 1
        assert calls[0][1]["params"]["offset"] == -1

    def test_webhook_conflict_error_is_returned_with_code(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        """End-to-end: the discover endpoint surfaces the webhook conflict as a
        409 whose body carries detail + the machine-readable code."""
        _authed(monkeypatch)
        _set_token(client)

        def webhook_fetch(token):
            raise idea_capture_ui.TelegramDiscoveryError(
                409, "El bot tiene un webhook activo…", code="webhook_conflict")
        monkeypatch.setattr(idea_capture_ui, "fetch_updates", webhook_fetch)

        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 409
        body = resp.json()
        assert body["detail"]
        assert body["code"] == "webhook_conflict"

    def test_network_failure_error_is_returned_with_code(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _set_token(client)

        def net_fetch(token):
            raise idea_capture_ui.TelegramDiscoveryError(
                502, "No se pudo contactar la API de Telegram.", code="network")
        monkeypatch.setattr(idea_capture_ui, "fetch_updates", net_fetch)

        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 502
        body = resp.json()
        assert body["detail"]
        assert body["code"] == "network"

    def test_invalid_token_error_is_returned_with_code(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _set_token(client)

        def bad_fetch(token):
            raise idea_capture_ui.TelegramDiscoveryError(
                400, "El token guardado no es válido o fue revocado.",
                code="invalid_token")
        monkeypatch.setattr(idea_capture_ui, "fetch_updates", bad_fetch)

        resp = client.post("/api/idea-capture/chats/discover")
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]
        assert body["code"] == "invalid_token"


class TestChatAuthorization:
    def test_authorize_private_chat_appends_to_allowlist(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _save_config(client, {
            "private_chat_ids": [111],
            "approved_groups": {},
            "active_world": "vibrantes",
            "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                       "raw_retention_days": 30},
        })
        resp = client.post("/api/idea-capture/chats/authorize",
                           json={"chat_id": 222, "chat_type": "private"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["config"]["private_chat_ids"] == [111, 222]
        assert data["message"] == "Chat privado autorizado."
        # Round-trips through the real runtime loader.
        loaded = load_policy(idea_capture_ui._config_path())
        assert loaded.policy.private_chat_ids == frozenset({111, 222})

    def test_authorize_private_chat_deduplicates(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _save_config(client, {
            "private_chat_ids": [111],
            "approved_groups": {},
            "active_world": "",
            "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                       "raw_retention_days": 30},
        })
        resp = client.post("/api/idea-capture/chats/authorize",
                           json={"chat_id": 111, "chat_type": "private"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["config"]["private_chat_ids"] == [111]
        assert resp.json()["message"] == "Ese chat privado ya estaba autorizado."

    def test_group_authorization_fails_closed_without_explicit_consent(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _save_config(client, {
            "private_chat_ids": [],
            "approved_groups": {},
            "active_world": "",
            "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                       "raw_retention_days": 30},
        })
        # No confirmation at all.
        resp = client.post("/api/idea-capture/chats/authorize",
                           json={"chat_id": -100, "chat_type": "group",
                                 "sender_ids": [5]})
        assert resp.status_code == 400
        assert "confirm" in resp.json()["detail"].lower()
        # Confirmed but no senders.
        resp = client.post("/api/idea-capture/chats/authorize",
                           json={"chat_id": -100, "chat_type": "group",
                                 "confirm_group": True})
        assert resp.status_code == 400
        # Senders but confirm_group not literally true.
        resp = client.post("/api/idea-capture/chats/authorize",
                           json={"chat_id": -100, "chat_type": "group",
                                 "sender_ids": [5], "confirm_group": "yes"})
        assert resp.status_code == 400
        # Nothing was persisted (fail closed).
        loaded = load_policy(idea_capture_ui._config_path())
        assert loaded.policy.private_chat_ids == frozenset()
        assert loaded.policy.approved_group_senders == {}

    def test_group_authorization_with_explicit_senders_persists(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        _save_config(client, {
            "private_chat_ids": [111],
            "approved_groups": {},
            "active_world": "",
            "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                       "raw_retention_days": 30},
        })
        resp = client.post("/api/idea-capture/chats/authorize",
                           json={"chat_id": -100, "chat_type": "supergroup",
                                 "confirm_group": True, "sender_ids": [5, 6]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["config"]["approved_groups"] == {"-100": [5, 6]}
        assert data["message"] == "Grupo autorizado con remitentes explícitos."
        loaded = load_policy(idea_capture_ui._config_path())
        assert loaded.policy.approved_group_senders == {-100: frozenset({5, 6})}

    @pytest.mark.parametrize("payload", [
        {"chat_id": "abc", "chat_type": "private"},
        {"chat_id": 1},                       # chat_type missing
        {"chat_id": 1, "chat_type": "channel"},  # not authorizable
        {"chat_id": 1.5, "chat_type": "private"},
    ])
    def test_invalid_authorize_payload_rejected_and_config_untouched(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch, payload: dict):
        _authed(monkeypatch)
        _save_config(client, {
            "private_chat_ids": [111],
            "approved_groups": {},
            "active_world": "",
            "limits": {"image_mb": 20, "audio_mb": 50, "audio_minutes": 5,
                       "raw_retention_days": 30},
        })
        path = idea_capture_ui._config_path()
        before = path.read_text(encoding="utf-8")
        resp = client.post("/api/idea-capture/chats/authorize", json=payload)
        assert resp.status_code == 400, resp.text
        assert path.read_text(encoding="utf-8") == before


class TestPendingQueue:
    """Web review queue (R-7): GET /pending + POST confirm/discard + gate.

    S-7.1 list, S-7.2 confirm (SAVE_GLOBAL → PROCESSING), S-7.3 discard
    (CANCEL → CANCELLED), S-7.4 server-side ``_CONFIRMABLE_STATES`` gate
    (a resolved capture is rejected with 409 — never trust the client).
    """

    @staticmethod
    def _seed_pending(texts: tuple[str, ...]) -> list[str]:
        """Reserve + park text captures in the sandboxed shared state file."""
        store = CaptureStore(idea_capture_ui._pending_state_path())
        try:
            ids: list[str] = []
            for index, text in enumerate(texts, start=1):
                update = TelegramUpdate(
                    update_id=10_000 + index,
                    chat_id=111,
                    sender_id=111,
                    is_group=False,
                    media=MediaInput(kind=MediaKind.TEXT, text=text,
                                     data=text.encode("utf-8")),
                )
                record = store.reserve(update)
                store.set_awaiting_confirm(record.capture_id)
                ids.append(record.capture_id)
            return ids
        finally:
            store.close()

    @staticmethod
    def _read(capture_id: str) -> CaptureRecord:
        store = CaptureStore(idea_capture_ui._pending_state_path())
        try:
            return store.get(capture_id)
        finally:
            store.close()

    # -- auth gate ----------------------------------------------------------

    def test_pending_endpoints_require_local_session(self, client: TestClient):
        assert client.get("/api/idea-capture/pending").status_code == 401
        assert client.post("/api/idea-capture/pending/x/confirm").status_code == 401
        assert client.post("/api/idea-capture/pending/x/discard").status_code == 401

    # -- S-7.1 list ---------------------------------------------------------

    def test_pending_lists_awaiting_confirm_captures(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        ids = self._seed_pending(("Primera idea", "Segunda idea", "Tercera idea"))

        resp = client.get("/api/idea-capture/pending")

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["count"] == 3
        assert {item["capture_id"] for item in data["captures"]} == set(ids)
        for item in data["captures"]:
            assert item["slug"]
            assert item["raw_text"]
            assert item["created_at"]
            assert item["event_ts"] == ""
            assert item["media_kind"] == "text"

    def test_pending_empty_queue_returns_zero(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        resp = client.get("/api/idea-capture/pending")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"captures": [], "count": 0}

    # -- S-7.2 confirm ------------------------------------------------------

    def test_confirm_saves_parked_capture_as_global_idea(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        [capture_id] = self._seed_pending(("Idea a confirmar",))

        resp = client.post(f"/api/idea-capture/pending/{capture_id}/confirm")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True}
        record = self._read(capture_id)
        # S-7.2: SAVE_GLOBAL path — global flag (only set_global sets it),
        # world cleared, and the capture leaves the pending queue. The worker
        # may already have finished, so PROCESSING or the final SAVED both
        # prove the transition happened through SAVE_GLOBAL.
        assert record.global_ is True
        assert record.state in (CaptureState.PROCESSING, CaptureState.SAVED)
        store = CaptureStore(idea_capture_ui._pending_state_path())
        try:
            assert store.count_pending_confirm() == 0
        finally:
            store.close()

    def test_confirm_unknown_capture_returns_404(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        resp = client.post("/api/idea-capture/pending/no-such-id/confirm")
        assert resp.status_code == 404

    # -- S-7.3 discard ------------------------------------------------------

    def test_discard_cancels_parked_capture(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        [capture_id] = self._seed_pending(("Idea a descartar",))

        resp = client.post(f"/api/idea-capture/pending/{capture_id}/discard")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True}
        record = self._read(capture_id)
        assert record.state is CaptureState.CANCELLED
        store = CaptureStore(idea_capture_ui._pending_state_path())
        try:
            assert store.count_pending_confirm() == 0
        finally:
            store.close()

    # -- S-7.4 server-side gate ---------------------------------------------

    def test_confirm_rejects_resolved_capture_with_409(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        # A capture already saved: the server must reject a stale confirm
        # instead of re-queuing the worker (never trust the client).
        [capture_id] = self._seed_pending(("Ya guardada",))
        store = CaptureStore(idea_capture_ui._pending_state_path())
        try:
            store.mark_saved(capture_id, "nec/ideas/ya-guardada", {"slug": "ya-guardada"})
        finally:
            store.close()

        resp = client.post(f"/api/idea-capture/pending/{capture_id}/confirm")

        assert resp.status_code == 409
        assert self._read(capture_id).state is CaptureState.SAVED

    def test_discard_rejects_resolved_capture_with_409(
            self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        _authed(monkeypatch)
        [capture_id] = self._seed_pending(("Ya cancelada",))
        store = CaptureStore(idea_capture_ui._pending_state_path())
        try:
            store.set_world(capture_id, None)  # -> CANCELLED
        finally:
            store.close()

        resp = client.post(f"/api/idea-capture/pending/{capture_id}/discard")

        assert resp.status_code == 409
        assert self._read(capture_id).state is CaptureState.CANCELLED
