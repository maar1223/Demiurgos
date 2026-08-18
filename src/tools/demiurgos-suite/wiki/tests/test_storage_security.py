# -*- coding: utf-8 -*-
"""Secret-safe persistence boundary tests (ONB-2.4).

Local providers never require a key; remote keys enter protected backend
storage only (Hermes profile .env written atomically with mode 0600) and
never appear in frontend state, logs, config metadata, or API responses.
"""

import logging
import os
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
_TOOLS = _SUITE.parent
for _path in (str(_WIKI), str(_SUITE), str(_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import api_server  # noqa: E402
import assistant_settings  # noqa: E402
from assistant_provider_adapters import ProviderRegistry  # noqa: E402
from capability_probes.runner import ProbeResult  # noqa: E402


class _FakeProbeRunner:
    def __init__(self, base_url: str, model: str, *, api_key: str = "", **_: object) -> None:
        self._api_key = api_key

    def run_text(self) -> ProbeResult:
        return ProbeResult("passed", "text-marker")

    def run_vision(self) -> ProbeResult:
        return ProbeResult("passed", "causal-vision")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    hermes = tmp_path / "hermes"
    hermes.mkdir()
    (hermes / "config.yaml").write_text(
        "model:\n  default: gpt-5.6-luna\n  provider: opencode-go\n"
        "  base_url: https://opencode.ai/zen/go/v1\n",
        encoding="utf-8",
    )
    (hermes / ".env").write_text("HERMES_GATEWAY_KEY=gateway-fixture\nKEEP_ME=1\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    monkeypatch.setattr(
        api_server,
        "_resolve_principal",
        lambda request: api_server.EditPrincipal("storage-tester"),
    )
    monkeypatch.setattr(assistant_settings, "ProbeRunner", _FakeProbeRunner)
    monkeypatch.setattr(assistant_settings.PROVIDER_REGISTRY, "transport", lambda *_: (200, {}))
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _env_path() -> Path:
    return assistant_settings._resolve_profile_paths().env


class TestEnvFileProtection:
    @pytest.mark.skipif(os.name == "nt", reason="POSIX file mode semantics")
    def test_remote_key_env_file_is_written_mode_0600(self, client: TestClient):
        before = _env_path().stat().st_mode & 0o777

        response = client.put(
            "/api/profile/assistant/configuration",
            json={"provider": "openai", "api_key": "opaque-0600-secret", "manual_model_id": "m"},
        )

        assert response.status_code == 200, response.text
        assert (_env_path().stat().st_mode & 0o777) == 0o600
        assert before != 0o600  # fixture wrote the file with default permissions

    @pytest.mark.skipif(os.name == "nt", reason="POSIX file mode semantics")
    def test_clear_keeps_env_file_mode_0600(self, client: TestClient):
        saved = client.put(
            "/api/profile/assistant/configuration",
            json={"provider": "openai", "api_key": "opaque-clear-0600", "manual_model_id": "m"},
        )
        assert saved.status_code == 200
        cleared = client.request(
            "DELETE", "/api/profile/assistant/configuration/key", json={"revision": saved.json()["revision"]}
        )

        assert cleared.status_code == 200
        assert (_env_path().stat().st_mode & 0o777) == 0o600


class TestLocalNoKey:
    @pytest.mark.parametrize("payload", [
        {"provider": "ollama", "manual_model_id": "llama3:8b"},
        {"provider": "lm-studio", "api_key": "", "manual_model_id": "qwen2.5:7b"},
    ])
    def test_local_provider_saves_without_any_key(self, client: TestClient, payload: dict):
        before_env = _env_path().read_text(encoding="utf-8")

        response = client.put("/api/profile/assistant/configuration", json=payload)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["key_configured"] is False
        assert _env_path().read_text(encoding="utf-8") == before_env
        assert "OPENAI_API_KEY" not in _env_path().read_text(encoding="utf-8")
        assert "ASSISTANT_PROVIDER_API_KEY" not in _env_path().read_text(encoding="utf-8")


class TestSecretBoundary:
    def test_remote_key_is_write_only_never_in_config_metadata(self, client: TestClient):
        secret = "opaque-write-only-secret"
        response = client.put(
            "/api/profile/assistant/configuration",
            json={"provider": "openai", "api_key": secret, "manual_model_id": "m"},
        )

        assert response.status_code == 200
        config_text = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")
        env_text = _env_path().read_text(encoding="utf-8")
        assert secret in env_text
        assert secret not in config_text
        assert secret not in response.text

    def test_secret_never_reaches_logs_or_status_payload(self, client: TestClient, caplog):
        secret = "opaque-log-free-secret"
        with caplog.at_level(logging.INFO):
            saved = client.put(
                "/api/profile/assistant/configuration",
                json={"provider": "openai", "api_key": secret, "manual_model_id": "m"},
            )
            status = client.get("/api/profile/assistant")

        assert saved.status_code == 200
        assert secret not in saved.text
        assert secret not in status.text
        assert secret not in caplog.text

    def test_delete_purges_the_secret(self, client: TestClient):
        secret = "opaque-purge-secret"
        saved = client.put(
            "/api/profile/assistant/configuration",
            json={"provider": "openai", "api_key": secret, "manual_model_id": "m"},
        )
        assert saved.status_code == 200

        cleared = client.request(
            "DELETE", "/api/profile/assistant/configuration/key", json={"revision": saved.json()["revision"]}
        )

        assert cleared.status_code == 200
        env_text = _env_path().read_text(encoding="utf-8")
        assert secret not in env_text
        assert "OPENAI_API_KEY" not in env_text
        assert "HERMES_GATEWAY_KEY=gateway-fixture" in env_text
        assert "KEEP_ME=1" in env_text

    def test_probe_responses_never_echo_credentials_or_fixture_bytes(self, client: TestClient):
        secret = "opaque-probe-boundary"
        payload = {"provider": "openai", "api_key": secret, "manual_model_id": "m"}

        text = client.post("/api/profile/assistant/probe/text", json=payload)
        vision = client.post("/api/profile/assistant/probe/vision", json=payload)

        assert text.status_code == 200
        assert vision.status_code == 200
        assert secret not in text.text
        assert secret not in vision.text
        assert "base64" not in vision.text
        assert "image" not in vision.text