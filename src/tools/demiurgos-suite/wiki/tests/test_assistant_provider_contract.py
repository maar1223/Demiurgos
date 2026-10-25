# -*- coding: utf-8 -*-
"""Provider-contract regression probes (S1-S5). No network.

Committed from the independent verifier's probe set: the S4 cases failed on
the pre-correction candidate (a keyless save replaced a foreign inline
``model.api_key``) and now pin the corrected lifecycle.
"""

from pathlib import Path
import sys

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _path in (str(_WIKI), str(_WIKI.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import assistant_settings  # noqa: E402
from capability_probes.runner import ProbeResult  # noqa: E402


class _PassingProbes:
    def run_text(self):
        return ProbeResult("passed", "text")

    def run_vision(self):
        return ProbeResult("passed", "vision")


class _ValidatingRegistry:
    def validate(self, payload):
        return {"outcome": "validated"}


def _write_profile(tmp_path: Path, monkeypatch, config: str, env: str = "") -> Path:
    hermes = tmp_path / "hermes"
    hermes.mkdir()
    (hermes / "config.yaml").write_text(config, encoding="utf-8")
    (hermes / ".env").write_text(env, encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    return hermes


def _client(**kwargs) -> TestClient:
    app = FastAPI()
    app.include_router(
        assistant_settings.create_assistant_settings_router(
            require_principal=lambda request: object(),
            provider_registry=_ValidatingRegistry(),
            probe_factory=lambda payload, model_id: _PassingProbes(),
            runtime_state_resolver=lambda revision: "saved-not-active",
            **kwargs,
        )
    )
    return TestClient(app, client=("127.0.0.1", 50000))


def _model(hermes: Path) -> dict:
    return yaml.safe_load((hermes / "config.yaml").read_text(encoding="utf-8"))["model"]


@pytest.mark.parametrize(
    ("product", "hermes_id"),
    [
        ("opencode-go", "opencode-go"),
        ("openrouter", "openrouter"),
        ("openai", "custom"),
        ("compatible", "custom"),
        ("ollama", "ollama"),
        ("lm-studio", "lmstudio"),
    ],
)
def test_s1_persisted_provider_is_the_hermes_identity(product, hermes_id):
    written = assistant_settings._set_model_config_content(
        "", "deepseek-flash", product, "https://api.example.test/v1"
    )
    assert yaml.safe_load(written)["model"]["provider"] == hermes_id


def test_s2_compatible_save_writes_a_reference_not_a_secret(tmp_path, monkeypatch):
    hermes = _write_profile(
        tmp_path, monkeypatch,
        "model:\n  default: deepseek-flash\n  provider: compatible\n"
        "  base_url: https://api.deepseek.com\n",
    )

    response = _client().put(
        "/api/profile/assistant/configuration",
        json={
            "provider": "compatible",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-verifier-live-secret",
            "manual_model_id": "deepseek-flash",
        },
    )

    assert response.status_code == 200, response.text
    config = (hermes / "config.yaml").read_text(encoding="utf-8")
    model = yaml.safe_load(config)["model"]
    assert model["provider"] == "custom"
    assert model["api_key"] == "${ASSISTANT_PROVIDER_API_KEY}"
    assert "sk-verifier-live-secret" not in config
    assert yaml.safe_load(config)["assistant_settings"]["provider"] == "compatible"


def test_s4_keyless_save_preserves_a_foreign_api_key(tmp_path, monkeypatch):
    hermes = _write_profile(
        tmp_path, monkeypatch,
        "model:\n  default: deepseek-flash\n  provider: compatible\n"
        "  base_url: https://api.deepseek.com\n"
        "  api_key: sk-user-inline-secret\n",
        env="ASSISTANT_PROVIDER_API_KEY=sk-different-env-secret\n",
    )

    response = _client().put("/api/profile/assistant", json={"model": "deepseek-v4-pro"})

    assert response.status_code == 200, response.text
    model = _model(hermes)
    assert model["provider"] == "custom"
    assert model["api_key"] == "sk-user-inline-secret"


def test_s4_keyless_configuration_save_preserves_a_foreign_api_key(tmp_path, monkeypatch):
    hermes = _write_profile(
        tmp_path, monkeypatch,
        "model:\n  default: deepseek-flash\n  provider: compatible\n"
        "  base_url: https://api.deepseek.com\n"
        "  api_key: sk-user-inline-secret\n",
        env="ASSISTANT_PROVIDER_API_KEY=sk-different-env-secret\n",
    )

    response = _client().put(
        "/api/profile/assistant/configuration",
        json={
            "provider": "compatible",
            "base_url": "https://api.deepseek.com",
            "manual_model_id": "deepseek-flash",
        },
    )

    assert response.status_code == 200, response.text
    assert _model(hermes)["api_key"] == "sk-user-inline-secret"


def test_s4_explicit_key_replaces_a_foreign_inline_key(tmp_path, monkeypatch):
    """A save that supplies a NEW secret is explicit intent: its reference wins."""
    hermes = _write_profile(
        tmp_path, monkeypatch,
        "model:\n  default: deepseek-flash\n  provider: compatible\n"
        "  base_url: https://api.deepseek.com\n"
        "  api_key: sk-user-inline-secret\n",
    )

    response = _client().put(
        "/api/profile/assistant/configuration",
        json={
            "provider": "compatible",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-new-secret",
            "manual_model_id": "deepseek-flash",
        },
    )

    assert response.status_code == 200, response.text
    config = (hermes / "config.yaml").read_text(encoding="utf-8")
    assert _model(hermes)["api_key"] == "${ASSISTANT_PROVIDER_API_KEY}"
    assert "sk-new-secret" not in config
    assert "ASSISTANT_PROVIDER_API_KEY=sk-new-secret" in (
        hermes / ".env"
    ).read_text(encoding="utf-8")


_BODY = {
    "provider": "compatible",
    "base_url": "https://api.deepseek.com",
    "api_key": "sk-verifier-live-secret",
    "manual_model_id": "deepseek-flash",
}
_CONFIG = (
    "model:\n  default: deepseek-flash\n  provider: custom\n"
    "  base_url: https://api.deepseek.com\n"
)


def test_s5_liveness_without_a_completed_run_is_not_active(tmp_path, monkeypatch):
    _write_profile(tmp_path, monkeypatch, _CONFIG)
    recorded: list[str] = []

    response = _client(
        runtime_liveness=lambda: True,
        runtime_probe=lambda: False,
        on_acceptance=recorded.append,
    ).put("/api/profile/assistant/configuration", json=_BODY)

    assert response.status_code == 200, response.text
    assert response.json()["runtime_state"] == "saved-not-active"
    assert recorded == ["saved-not-active"]


def test_s5_a_raising_probe_fails_closed(tmp_path, monkeypatch):
    _write_profile(tmp_path, monkeypatch, _CONFIG)

    def broken() -> bool:
        raise RuntimeError("probe exploded")

    response = _client(
        runtime_liveness=lambda: True, runtime_probe=broken
    ).put("/api/profile/assistant/configuration", json=_BODY)

    assert response.status_code == 200, response.text
    assert response.json()["runtime_state"] == "saved-not-active"


def test_s5_completed_run_is_the_only_active_path(tmp_path, monkeypatch):
    _write_profile(tmp_path, monkeypatch, _CONFIG)
    calls: list[bool] = []

    response = _client(
        runtime_liveness=lambda: False,
        runtime_probe=lambda: calls.append(True) or True,
    ).put("/api/profile/assistant/configuration", json=_BODY)

    assert response.status_code == 200, response.text
    assert response.json()["runtime_state"] == "active"
    assert calls == [True]
