# -*- coding: utf-8 -*-
"""Security and persistence tests for Profile → Wiki assistant settings."""

import logging
from pathlib import Path
import sys

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _path in (str(_WIKI), str(_SUITE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import api_server  # noqa: E402
import assistant_settings  # noqa: E402
from assistant_provider_adapters import ProviderRegistry  # noqa: E402
from capability_probes.runner import ProbeResult  # noqa: E402
from hermes_runtime import HermesRuntimeResult, HermesRuntimeSeam  # noqa: E402


class _FakeProbeRunner:
    """Deterministic probe stand-in injected through the module ProbeRunner name."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "",
        text: ProbeResult | None = None,
        vision: ProbeResult | None = None,
    ) -> None:
        self._text = text if text is not None else ProbeResult("passed", "text-marker")
        self._vision = vision if vision is not None else ProbeResult("passed", "causal-vision")

    def run_text(self) -> ProbeResult:
        return self._text

    def run_vision(self) -> ProbeResult:
        return self._vision


def _install_fake_probes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: ProbeResult | None = None,
    vision: ProbeResult | None = None,
) -> None:
    monkeypatch.setattr(
        assistant_settings,
        "ProbeRunner",
        lambda *args, **kwargs: _FakeProbeRunner(*args, text=text, vision=vision, **kwargs),
    )


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    hermes = tmp_path / "hermes"
    hermes.mkdir()
    (hermes / "config.yaml").write_text(
        "model:\n  default: gpt-5.6-luna\n  provider: opencode-go\n"
        "  base_url: https://opencode.ai/zen/go/v1\n"
        "toolsets:\n  - hermes-cli\n",
        encoding="utf-8",
    )
    (hermes / ".env").write_text("HERMES_GATEWAY_KEY=gateway-fixture\nKEEP_ME=1\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    # Isolate the api_server registry too: the assistant router's ONB-3.6
    # acceptance wiring writes to the local registry on successful saves, and
    # this fixture drives the REAL api_server.app — otherwise those saves
    # would create data/local-state.json at the repo root.
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        api_server,
        "_resolve_principal",
        lambda request: api_server.EditPrincipal("assistant-tester"),
    )
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _unauthenticated_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "missing-hermes"))
    monkeypatch.setattr(api_server, "_resolve_principal", lambda request: None)
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _runtime_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seam: HermesRuntimeSeam,
) -> TestClient:
    hermes = tmp_path / "hermes-runtime"
    hermes.mkdir()
    (hermes / "config.yaml").write_text(
        "model:\n  default: gpt-5.6-luna\n  provider: opencode-go\n"
        "  base_url: https://opencode.ai/zen/go/v1\n",
        encoding="utf-8",
    )
    (hermes / ".env").write_text("HERMES_GATEWAY_KEY=gateway-fixture\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hermes))

    registry = ProviderRegistry()
    registry.transport = lambda method, url, headers: (200, {"data": []})
    local_app = FastAPI()
    local_app.include_router(
        assistant_settings.create_assistant_settings_router(
            require_principal=lambda request: object(),
            provider_registry=registry,
            runtime_seam=seam,
        )
    )
    return TestClient(local_app, client=("127.0.0.1", 50000))


class TestAuth:
    def test_all_routes_require_local_principal(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        client = _unauthenticated_client(tmp_path, monkeypatch)
        assert client.get("/api/profile/assistant").status_code == 401
        assert client.put("/api/profile/assistant", json={"model": "gpt-5.6-luna"}).status_code == 401
        assert client.delete("/api/profile/assistant/key").status_code == 401


class TestAssistantSettings:
    def test_get_returns_metadata_and_catalog_without_key(self, client: TestClient):
        response = client.get("/api/profile/assistant")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == "opencode-go"
        assert body["base_url"] == "https://opencode.ai/zen/go/v1"
        assert body["model"] == "gpt-5.6-luna"
        assert body["key_configured"] is False
        assert body["models"]
        assert "api_key" not in body

    def test_catalog_declares_luna_multimodal_and_others_text_only(self):
        models = {item["id"]: item for item in assistant_settings.ASSISTANT_MODEL_CATALOG}

        assert models["gpt-5.6-luna"]["capability"] == "multimodal"
        assert models["qwen3.6-plus"]["capability"] == "multimodal"
        for model_id in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4-lite"):
            assert models[model_id]["capability"] == "text-only"

    def test_model_metadata_resolves_catalog_capability_for_luna(self):
        model = assistant_settings._model_metadata("gpt-5.6-luna")

        assert model.capability == "multimodal"
        assert model.label == "GPT-5.6 Luna"

    def test_get_reports_luna_as_multimodal(self, client: TestClient):
        response = client.get("/api/profile/assistant")

        assert response.status_code == 200
        assert response.json()["model_metadata"]["capability"] == "multimodal"

    def test_status_exposes_gateway_running_boolean(self, client: TestClient):
        """S2b (degradable-ai-provider): the status surface carries an explicit
        presence boolean derived from HermesGatewayProbe.is_running() so the UI
        can distinguish gateway-up from configured-but-down. The real app
        wiring injects runtime_liveness, so the key must be a plain bool."""
        response = client.get("/api/profile/assistant/status")

        assert response.status_code == 200
        body = response.json()
        assert "gateway_running" in body
        assert isinstance(body["gateway_running"], bool)

    def test_get_uses_provider_default_when_endpoint_is_omitted(self, client: TestClient):
        paths = assistant_settings._resolve_profile_paths()
        paths.config.write_text(
            "model:\n  default: gpt-5.6-luna\n  provider: opencode-go\n",
            encoding="utf-8",
        )

        response = client.get("/api/profile/assistant/status")

        assert response.status_code == 200
        assert response.json()["base_url"] == "https://opencode.ai/zen/go/v1"

    def test_public_contract_redacts_url_credentials_and_normalizes_metadata(self):
        status = assistant_settings.AssistantSettingsStatus(
            provider="compatible",
            base_url="https://user:transient-secret@example.test/v1?api_key=transient-secret",
            model=assistant_settings.AssistantModel(
                id="custom-model", label="Custom", capability="unsupported"
            ),
            key_configured=True,
            revision=4,
        )

        public = status.public()
        assert public["base_url"] == "https://example.test/v1"
        assert public["model_metadata"]["capability"] == "unknown"
        assert "transient-secret" not in repr(public)

    def test_put_updates_model_and_key_without_disclosure(self, client: TestClient, caplog):
        fixture_key = "opaque-fixture-key-a"
        with caplog.at_level(logging.INFO):
            response = client.put(
                "/api/profile/assistant",
                json={"model": "deepseek-v4-flash", "api_key": fixture_key},
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["model"] == "deepseek-v4-flash"
        assert body["key_configured"] is True
        assert fixture_key not in response.text
        assert fixture_key not in caplog.text

        env_text = assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8")
        config_text = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")
        assert "OPENCODE_GO_API_KEY=" + fixture_key in env_text
        assert "HERMES_GATEWAY_KEY=gateway-fixture" in env_text
        assert "default: deepseek-v4-flash" in config_text
        assert "provider: opencode-go" in config_text
        assert "base_url: https://opencode.ai/zen/go/v1" in config_text

    def test_replacement_and_clear_preserve_gateway_key(self, client: TestClient):
        first = "opaque-fixture-key-b"
        second = "opaque-fixture-key-c"
        client.put("/api/profile/assistant", json={"api_key": first})
        client.put("/api/profile/assistant", json={"api_key": second})
        replaced = assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8")
        assert "OPENCODE_GO_API_KEY=" + second in replaced
        assert first not in replaced

        response = client.delete("/api/profile/assistant/key")
        assert response.status_code == 200
        assert response.json()["key_configured"] is False
        cleared = assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8")
        assert "OPENCODE_GO_API_KEY" not in cleared
        assert "HERMES_GATEWAY_KEY=gateway-fixture" in cleared
        assert "KEEP_ME=1" in cleared

    def test_clear_is_revisioned_and_migrates_legacy_metadata(self, client: TestClient):
        saved = client.put("/api/profile/assistant", json={"api_key": "opaque-clear-fixture"})
        assert saved.status_code == 200

        response = client.request(
            "DELETE",
            "/api/profile/assistant/key", json={"revision": saved.json()["revision"]}
        )

        assert response.status_code == 200
        assert response.json()["revision"] == saved.json()["revision"] + 1
        config_text = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")
        assert "assistant_settings:" in config_text
        assert "revision: 2" in config_text

    def test_migration_preserves_legacy_provider_and_unrelated_secrets(self, client: TestClient):
        response = client.put(
            "/api/profile/assistant",
            json={"model": "deepseek-v4-lite", "api_key": "opaque-migration-fixture"},
        )

        assert response.status_code == 200
        config_text = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")
        env_text = assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8")
        assert "assistant_settings:" in config_text
        assert "model_id: deepseek-v4-lite" in config_text
        assert "provider: opencode-go" in config_text
        assert "base_url: https://opencode.ai/zen/go/v1" in config_text
        assert "HERMES_GATEWAY_KEY=gateway-fixture" in env_text
        assert "KEEP_ME=1" in env_text
        assert "opaque-migration-fixture" not in response.text

    def test_stale_revision_is_rejected_without_overwrite(self, client: TestClient):
        first = client.put("/api/profile/assistant", json={"model": "deepseek-v4-flash", "revision": 0})
        before_config = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")
        before_env = assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8")

        response = client.put("/api/profile/assistant", json={"model": "qwen3.6-plus", "revision": 0})

        assert first.status_code == 200
        assert response.status_code == 409
        assert assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8") == before_config
        assert assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8") == before_env

    def test_failed_secret_write_restores_migrated_config(self, client: TestClient, monkeypatch):
        paths = assistant_settings._resolve_profile_paths()
        before_config = paths.config.read_text(encoding="utf-8")
        before_env = paths.env.read_text(encoding="utf-8")
        original_replace = assistant_settings.os.replace
        failed = False

        def fail_env_once(source, target):
            nonlocal failed
            if Path(target) == paths.env and not failed:
                failed = True
                raise OSError("simulated env write failure")
            original_replace(source, target)

        monkeypatch.setattr(assistant_settings.os, "replace", fail_env_once)
        response = client.put(
            "/api/profile/assistant",
            json={"model": "deepseek-v4-pro", "api_key": "opaque-failure-fixture"},
        )

        assert response.status_code == 503
        assert "opaque-failure-fixture" not in response.text
        assert paths.config.read_text(encoding="utf-8") == before_config
        assert paths.env.read_text(encoding="utf-8") == before_env

    def test_model_update_preserves_non_legacy_provider_fields(self, client: TestClient):
        paths = assistant_settings._resolve_profile_paths()
        paths.config.write_text(
            "model:\n  default: old-model\n  provider: compatible\n  base_url: https://provider.example/v1\n",
            encoding="utf-8",
        )

        response = client.put("/api/profile/assistant", json={"model": "qwen3.6-plus"})

        assert response.status_code == 200
        config_text = paths.config.read_text(encoding="utf-8")
        assert "base_url: https://provider.example/v1" in config_text
        # The endpoint survives; the persisted id becomes Hermes-resolvable and
        # the normalized block keeps the product provider for the UI.
        model_block = config_text.split("assistant_settings:", 1)[0]
        assert "provider: custom" in model_block
        assert "provider: compatible" in config_text.split("assistant_settings:", 1)[1]

    def test_config_and_key_persistence_use_same_directory_atomic_replacements(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        replacements: list[tuple[Path, Path]] = []
        original_replace = assistant_settings.os.replace

        def record_replace(source: str | bytes, target: str | bytes) -> None:
            replacements.append((Path(source), Path(target)))
            original_replace(source, target)

        monkeypatch.setattr(assistant_settings.os, "replace", record_replace)

        response = client.put(
            "/api/profile/assistant",
            json={"model": "deepseek-v4-pro", "api_key": "opaque-atomic-fixture"},
        )

        assert response.status_code == 200
        assert len(replacements) == 2
        assert all(source.parent == target.parent for source, target in replacements)
        assert all(not source.exists() for source, _ in replacements)

    @pytest.mark.parametrize(
        "payload",
        [
            {"model": "not-in-catalog"},
            {"api_key": ""},
            {"api_key": "contains whitespace"},
        ],
    )
    def test_invalid_values_are_rejected_without_persistence(self, client: TestClient, payload: dict):
        before_config = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")
        before_env = assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8")

        response = client.put("/api/profile/assistant", json=payload)

        assert response.status_code == 400
        assert assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8") == before_config
        assert assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8") == before_env

    def test_named_active_profile_is_selected_without_hardcoded_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        root = tmp_path / "hermes-root"
        profile = root / "profiles" / "staging"
        profile.mkdir(parents=True)
        (root / "active_profile").write_text("staging\n", encoding="utf-8")
        (profile / "config.yaml").write_text("model:\n  default: gpt-5.6-luna\n", encoding="utf-8")
        monkeypatch.setenv("HERMES_HOME", str(root))
        monkeypatch.setattr(
            api_server,
            "_resolve_principal",
            lambda request: api_server.EditPrincipal("assistant-tester"),
        )
        client = TestClient(api_server.app, client=("127.0.0.1", 50000))

        response = client.put("/api/profile/assistant", json={"model": "qwen3.6-plus"})

        assert response.status_code == 200
        assert response.json()["active_profile"] == "staging"
        assert "default: qwen3.6-plus" in (profile / "config.yaml").read_text(encoding="utf-8")

    def test_unresolvable_profile_fails_closed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "does-not-exist"))
        monkeypatch.setattr(
            api_server,
            "_resolve_principal",
            lambda request: api_server.EditPrincipal("assistant-tester"),
        )
        client = TestClient(api_server.app, client=("127.0.0.1", 50000))

        response = client.put("/api/profile/assistant", json={"model": "gpt-5.6-luna"})

        assert response.status_code == 503
        assert "config.yaml" in response.json()["detail"]


class TestProviderAdapters:
    @pytest.mark.parametrize("provider", ["opencode-go", "openai", "openrouter", "compatible"])
    def test_registry_supports_each_initial_provider(self, provider):
        registry = ProviderRegistry(transport=lambda *_: (200, {"data": [{"id": "model-a"}]}))
        payload = {"provider": provider, "api_key": "fixture-secret-value"}
        if provider == "compatible":
            payload["base_url"] = "https://compatible.example/v1"

        result = registry.validate(payload)

        assert result["outcome"] == "validated"

    def test_discovery_validates_first_and_keeps_telemetry_categorical(self):
        calls: list[str] = []
        telemetry: list[dict] = []
        secret_marker = "fixture-secret-value"

        def transport(method, url, headers):
            calls.append(url)
            return 200, {"data": [{"id": "model-a", "name": "Model A"}]}

        registry = ProviderRegistry(transport=transport, telemetry=telemetry.append)
        result = registry.discover({"provider": "openai", "api_key": secret_marker})

        assert result["outcome"] == "discovered"
        assert len(calls) == 2
        assert result["models"][0] == {
            "id": "model-a", "label": "Model A", "capability": "unknown", "pricing": None
        }
        assert all(set(event) == {"outcome", "latency_ms", "adapter", "failure_category", "activation_state"}
                   for event in telemetry)
        assert all(secret_marker not in repr(event) for event in telemetry)

    @pytest.mark.parametrize("status,category", [(401, "authentication"), (500, "provider")])
    def test_provider_failures_are_actionable_categories(self, status, category):
        secret_marker = "fixture-secret-value"
        registry = ProviderRegistry(transport=lambda *_: (status, {}))
        result = registry.validate({"provider": "openrouter", "api_key": secret_marker})

        assert result["outcome"] == "failed"
        assert result["category"] == category
        assert secret_marker not in repr(result)


class TestProviderAPI:
    def test_new_routes_preserve_authentication(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        client = _unauthenticated_client(tmp_path, monkeypatch)
        payload = {"provider": "openai", "api_key": "fixture-secret-value"}
        assert client.post("/api/profile/assistant/connection/validate", json=payload).status_code == 401
        assert client.post("/api/profile/assistant/models/discover", json=payload).status_code == 401
        assert client.post("/api/profile/assistant/probe/text", json=payload).status_code == 401
        assert client.post("/api/profile/assistant/probe/vision", json=payload).status_code == 401
        assert client.put("/api/profile/assistant/configuration", json=payload).status_code == 401

    def test_validate_discover_save_after_three_proofs(self, client: TestClient, monkeypatch):
        def transport(method, url, headers):
            return 200, {"data": [{"id": "manual-model", "name": "Manual Model"}]}

        monkeypatch.setattr(assistant_settings.PROVIDER_REGISTRY, "transport", transport)
        _install_fake_probes(monkeypatch)
        secret_marker = "fixture-secret-value"
        payload = {"provider": "openai", "api_key": secret_marker}
        assert client.post("/api/profile/assistant/connection/validate", json=payload).json()["outcome"] == "validated"
        discovery = client.post("/api/profile/assistant/models/discover", json=payload)
        assert discovery.json()["models"][0]["capability"] == "unknown"
        save = {**payload, "manual_model_id": "manual-model"}
        response = client.put("/api/profile/assistant/configuration", json=save)

        assert response.status_code == 200, response.text
        assert response.json()["provider"] == "openai"
        assert "api_key" not in response.text
        assert secret_marker not in response.text
        env = assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8")
        assert "OPENAI_API_KEY=" + secret_marker in env
        cleared = client.request("DELETE", "/api/profile/assistant/configuration/key",
                                json={"revision": response.json()["revision"]})
        assert cleared.status_code == 200
        assert "OPENAI_API_KEY" not in assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8")


class TestThreeProofGate:
    """ONB-2.1: only text + causal vision + runtime acceptance configure; no unknown_ack."""

    def _save(self, client: TestClient, payload: dict) -> dict:
        return client.put("/api/profile/assistant/configuration", json=payload)

    def _payload(self, model_id: str = "manual-model") -> dict:
        return {"provider": "openai", "api_key": "fixture-secret-value", "manual_model_id": model_id}

    def test_unknown_ack_is_ignored_when_probes_pass(self, client: TestClient, monkeypatch):
        def transport(method, url, headers):
            return 200, {"data": [{"id": "manual-model", "name": "Manual Model"}]}

        monkeypatch.setattr(assistant_settings.PROVIDER_REGISTRY, "transport", transport)
        _install_fake_probes(monkeypatch, vision=ProbeResult("passed", "causal-vision"))
        response = self._save(client, {**self._payload(), "unknown_ack": True})

        assert response.status_code == 200  # probes passed; ack is irrelevant metadata
        assert "unknown_ack" not in response.json()

    def test_failed_text_probe_never_configures(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(assistant_settings.PROVIDER_REGISTRY, "transport", lambda *_: (200, {}))
        _install_fake_probes(monkeypatch, text=ProbeResult("not_causal", "text-marker", "nope"))
        before_config = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")

        response = self._save(client, self._payload())

        assert response.status_code == 422
        assert "text probe" in response.json()["detail"]
        assert assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8") == before_config

    def test_failed_vision_probe_never_configures(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(assistant_settings.PROVIDER_REGISTRY, "transport", lambda *_: (200, {}))
        _install_fake_probes(monkeypatch, vision=ProbeResult("not_causal", "vision-fixture", "wrong"))
        before_env = assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8")

        response = self._save(client, self._payload())

        assert response.status_code == 422
        assert "vision" in response.json()["detail"]
        assert assistant_settings._resolve_profile_paths().env.read_text(encoding="utf-8") == before_env

    def test_malformed_and_timeout_probes_never_configure(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(assistant_settings.PROVIDER_REGISTRY, "transport", lambda *_: (200, {}))
        before_config = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")
        for outcome in ("malformed", "timeout", "provider_failure"):
            _install_fake_probes(monkeypatch, text=ProbeResult(outcome, "text-marker", "boom"))
            response = self._save(client, self._payload())
            assert response.status_code == 422, outcome
            assert assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8") == before_config

    def test_connection_failure_never_configures(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(assistant_settings.PROVIDER_REGISTRY, "transport", lambda *_: (401, {}))
        _install_fake_probes(monkeypatch)
        before_config = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")

        response = self._save(client, self._payload())

        assert response.status_code == 422
        assert assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8") == before_config

    def test_text_only_model_fails_vision_and_never_configures(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(assistant_settings.PROVIDER_REGISTRY, "transport", lambda *_: (200, {}))
        _install_fake_probes(monkeypatch, vision=ProbeResult("not_causal", "vision-variant", "text-only"))
        before_config = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")

        response = self._save(client, self._payload("text-only-model"))

        assert response.status_code == 422
        assert assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8") == before_config

    def test_probe_endpoints_report_independent_oracle_results(self, client: TestClient, monkeypatch):
        _install_fake_probes(monkeypatch, text=ProbeResult("passed", "text-marker"), vision=ProbeResult("not_causal", "vision-fixture", "wrong"))
        payload = self._payload()

        text = client.post("/api/profile/assistant/probe/text", json=payload)
        vision = client.post("/api/profile/assistant/probe/vision", json=payload)

        assert text.status_code == 200
        assert text.json()["outcome"] == "passed"
        assert text.json()["oracle"] == "text-marker"
        assert vision.status_code == 200
        assert vision.json()["outcome"] == "not_causal"
        assert vision.json()["oracle"] == "vision-fixture"


class TestHermesRuntimeSeam:
    @pytest.mark.parametrize(
        ("result", "expected_state"),
        [
            (HermesRuntimeResult("active", accepted=True), "active"),
            (HermesRuntimeResult("saved-not-active", accepted=False), "saved-not-active"),
            (HermesRuntimeResult("pending-reload", accepted=True, reload_required=True), "pending-reload"),
            (HermesRuntimeResult("unavailable", accepted=False), "saved-not-active"),
        ],
    )
    def test_runtime_outcomes_are_reported_after_persistence(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        result: HermesRuntimeResult,
        expected_state: str,
    ):
        seam = HermesRuntimeSeam(lambda revision: result)
        _install_fake_probes(monkeypatch)
        client = _runtime_client(tmp_path, monkeypatch, seam)

        response = client.put(
            "/api/profile/assistant/configuration",
            json={
                "provider": "openai",
                "api_key": "fixture-runtime-key",
                "manual_model_id": "manual-model",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["runtime_state"] == expected_state
        assert seam.applied_revisions == [1]
        assert assistant_settings._resolve_profile_paths().config.is_file()

    def test_activation_failure_keeps_prior_known_good_revision(self):
        outcomes = {
            1: HermesRuntimeResult("active", accepted=True),
            2: HermesRuntimeResult("saved-not-active", accepted=False),
        }
        seam = HermesRuntimeSeam(lambda revision: outcomes[revision])

        assert seam.apply(1).state == "active"
        assert seam.apply(2).state == "saved-not-active"
        assert seam.known_good_revision == 1

    def test_seam_has_no_process_control_dependency(self):
        import hermes_runtime

        assert "subprocess" not in hermes_runtime.__dict__


class TestAcceptanceEvidenceCallback:
    """ONB-3.6 — the router reports the runtime acceptance to the wired
    callback so api_server can record the three-proof evidence in the local
    registry (badge becomes configured only on real acceptance)."""

    def _build_client(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                      on_acceptance, seam: HermesRuntimeSeam) -> TestClient:
        hermes = tmp_path / "hermes-evidence"
        hermes.mkdir()
        (hermes / "config.yaml").write_text(
            "model:\n  default: gpt-5.6-luna\n  provider: opencode-go\n"
            "  base_url: https://opencode.ai/zen/go/v1\n",
            encoding="utf-8",
        )
        (hermes / ".env").write_text("HERMES_GATEWAY_KEY=gateway-fixture\n", encoding="utf-8")
        monkeypatch.setenv("HERMES_HOME", str(hermes))
        _install_fake_probes(monkeypatch)
        registry = ProviderRegistry()
        registry.transport = lambda method, url, headers: (200, {"data": []})
        local_app = FastAPI()
        local_app.include_router(
            assistant_settings.create_assistant_settings_router(
                require_principal=lambda request: object(),
                provider_registry=registry,
                runtime_seam=seam,
                on_acceptance=on_acceptance,
            )
        )
        return TestClient(local_app, client=("127.0.0.1", 50000))

    def test_callback_receives_accepted_runtime_after_successful_save(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        captured: list[str] = []
        seam = HermesRuntimeSeam(
            lambda revision: HermesRuntimeResult("active", accepted=True)
        )
        client = self._build_client(tmp_path, monkeypatch, captured.append, seam)

        response = client.put(
            "/api/profile/assistant/configuration",
            json={
                "provider": "openai",
                "api_key": "fixture-evidence-key",
                "manual_model_id": "manual-model",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["runtime_state"] == "active"
        assert captured == ["active"]

    def test_callback_receives_pending_reload_runtime(self, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch):
        captured: list[str] = []
        seam = HermesRuntimeSeam(
            lambda revision: HermesRuntimeResult("pending-reload", accepted=True,
                                                 reload_required=True)
        )
        client = self._build_client(tmp_path, monkeypatch, captured.append, seam)

        response = client.put(
            "/api/profile/assistant/configuration",
            json={
                "provider": "openai",
                "api_key": "fixture-evidence-key",
                "manual_model_id": "manual-model",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["runtime_state"] == "pending-reload"
        assert captured == ["pending-reload"]

    def test_callback_not_invoked_when_save_fails(self, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch):
        captured: list[str] = []
        seam = HermesRuntimeSeam(
            lambda revision: HermesRuntimeResult("active", accepted=True)
        )
        client = self._build_client(tmp_path, monkeypatch, captured.append, seam)
        _install_fake_probes(monkeypatch, text=ProbeResult("not_causal", "text-marker", "nope"))

        response = client.put(
            "/api/profile/assistant/configuration",
            json={
                "provider": "openai",
                "api_key": "fixture-evidence-key",
                "manual_model_id": "manual-model",
            },
        )

        assert response.status_code == 422
        assert captured == []


class TestRuntimeStateResolver:
    """When a resolver is wired, the router owns runtime_state from persisted
    evidence plus live liveness instead of the legacy in-memory seam."""

    def _build(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        resolver,
        liveness=None,
        on_acceptance=None,
        runtime_probe=None,
    ) -> TestClient:
        hermes = tmp_path / "hermes-resolver"
        hermes.mkdir()
        (hermes / "config.yaml").write_text(
            "model:\n  default: gpt-5.6-luna\n  provider: opencode-go\n"
            "  base_url: https://opencode.ai/zen/go/v1\n",
            encoding="utf-8",
        )
        (hermes / ".env").write_text("OPENCODE_GO_API_KEY=fixture\n", encoding="utf-8")
        monkeypatch.setenv("HERMES_HOME", str(hermes))
        _install_fake_probes(monkeypatch)
        registry = ProviderRegistry()
        registry.transport = lambda method, url, headers: (200, {"data": []})
        local_app = FastAPI()
        local_app.include_router(
            assistant_settings.create_assistant_settings_router(
                require_principal=lambda request: object(),
                provider_registry=registry,
                runtime_state_resolver=resolver,
                runtime_liveness=liveness,
                on_acceptance=on_acceptance,
                runtime_probe=runtime_probe,
            )
        )
        return TestClient(local_app, client=("127.0.0.1", 50000))

    @pytest.mark.parametrize("state", ["active", "pending-reload", "saved-not-active"])
    def test_get_reports_resolver_state(self, tmp_path, monkeypatch, state):
        client = self._build(tmp_path, monkeypatch, lambda revision: state)
        response = client.get("/api/profile/assistant")
        assert response.status_code == 200, response.text
        assert response.json()["runtime_state"] == state

    @pytest.mark.parametrize("live", [False, True])
    def test_save_reports_liveness_acceptance_and_resolver_response(
            self, tmp_path, monkeypatch, live):
        """F-3: one liveness observation drives both surfaces, so they agree.

        The save path must probe liveness exactly once and use that value for
        both the recorded acceptance (``on_acceptance``) and the response. The
        injected resolver is a tripwire: if the save path resolved a second
        time, this test would fail instead of silently normalising a
        response/evidence disagreement.
        """
        captured: list[str] = []

        def _resolver_must_not_be_called(revision):  # pragma: no cover - tripwire
            raise AssertionError("save must not resolve liveness twice")

        client = self._build(
            tmp_path,
            monkeypatch,
            resolver=_resolver_must_not_be_called,
            liveness=lambda: live,
            on_acceptance=captured.append,
        )

        response = client.put(
            "/api/profile/assistant/configuration",
            json={
                "provider": "openai",
                "api_key": "fixture-resolver-key",
                "manual_model_id": "manual-model",
            },
        )

        assert response.status_code == 200, response.text
        expected = "active" if live else "saved-not-active"
        assert captured == [expected]
        # Both the recorded acceptance and the response are the same observation.
        assert response.json()["runtime_state"] == captured[0]


    @pytest.mark.parametrize("ready", [True, False])
    def test_save_uses_the_real_run_probe_for_acceptance(
            self, tmp_path, monkeypatch, ready):
        """S5: the save acceptance is one real Hermes run. Gateway liveness
        alone must never accept a revision, and the probe must run exactly
        once so the recorded evidence and the response agree."""
        captured: list[str] = []
        calls: list[bool] = []

        def _probe() -> bool:
            calls.append(True)
            return ready

        def _liveness_must_not_be_used():  # pragma: no cover - tripwire
            raise AssertionError("gateway liveness alone must not accept a save")

        client = self._build(
            tmp_path,
            monkeypatch,
            resolver=lambda revision: "unused",
            liveness=_liveness_must_not_be_used,
            on_acceptance=captured.append,
            runtime_probe=_probe,
        )

        response = client.put(
            "/api/profile/assistant/configuration",
            json={
                "provider": "openai",
                "api_key": "fixture-probe-key",
                "manual_model_id": "manual-model",
            },
        )

        assert response.status_code == 200, response.text
        assert calls == [True]
        expected = "active" if ready else "saved-not-active"
        assert captured == [expected]
        assert response.json()["runtime_state"] == expected

    def test_run_probe_exception_fails_closed(self, tmp_path, monkeypatch):
        captured: list[str] = []

        def _probe() -> bool:
            raise RuntimeError("probe exploded")

        client = self._build(
            tmp_path,
            monkeypatch,
            resolver=lambda revision: "unused",
            on_acceptance=captured.append,
            runtime_probe=_probe,
        )

        response = client.put(
            "/api/profile/assistant/configuration",
            json={
                "provider": "openai",
                "api_key": "fixture-probe-key",
                "manual_model_id": "manual-model",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["runtime_state"] == "saved-not-active"
        assert captured == ["saved-not-active"]

    def test_current_config_revision_matches_active_profile(self, tmp_path, monkeypatch):
        hermes = tmp_path / "hermes-revision"
        hermes.mkdir()
        (hermes / "config.yaml").write_text(
            "model:\n  default: gpt-5.6-luna\n  provider: opencode-go\n"
            "  base_url: https://opencode.ai/zen/go/v1\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("HERMES_HOME", str(hermes))
        assert isinstance(assistant_settings.current_config_revision(), int)



class TestHermesProviderMapping:
    """S1-S4 — the persisted model block must use an id the installed Hermes
    runtime resolves, while the product vocabulary stays in the normalized
    block. ``compatible`` needs the stored secret reachable from the config
    without inlining it."""

    def _save(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        provider: str,
        *,
        api_key: str | None = None,
        model_id: str = "manual-model",
    ) -> "object":
        def transport(method, url, headers):
            return 200, {"data": [{"id": model_id, "name": "Manual Model"}]}

        monkeypatch.setattr(assistant_settings.PROVIDER_REGISTRY, "transport", transport)
        _install_fake_probes(monkeypatch)
        payload = {"provider": provider, "manual_model_id": model_id}
        if provider == "compatible":
            payload["base_url"] = "https://api.deepseek.com"
        payload["api_key"] = (
            api_key
            if api_key is not None
            else ("" if provider in {"ollama", "lm-studio"} else "fixture-mapping-key")
        )
        return client.put("/api/profile/assistant/configuration", json=payload)

    @pytest.mark.parametrize(
        ("provider", "hermes_id", "expects_reference"),
        [
            ("opencode-go", "opencode-go", False),
            ("openrouter", "openrouter", False),
            ("openai", "custom", False),
            ("compatible", "custom", True),
            ("ollama", "ollama", False),
            ("lm-studio", "lmstudio", False),
        ],
    )
    def test_save_writes_the_hermes_provider_id_and_keeps_the_product_one(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
        provider: str, hermes_id: str, expects_reference: bool,
    ):
        response = self._save(client, monkeypatch, provider)

        assert response.status_code == 200, response.text
        assert response.json()["provider"] == provider
        config = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")
        model_block = config.split("assistant_settings:", 1)[0]
        assert f"provider: {hermes_id}" in model_block
        assert "provider: ${}".format(hermes_id) not in model_block
        # The normalized block keeps the Demiurgos id (UI, vision gate, key env).
        assert f"provider: {provider}" in config.split("assistant_settings:", 1)[1]
        reference = "api_key: ${ASSISTANT_PROVIDER_API_KEY}"
        assert (reference in model_block) is expects_reference
        parsed = yaml.safe_load(config)["model"]
        assert parsed["provider"] == hermes_id
        assert ("api_key" in parsed) is expects_reference

    def test_switching_away_from_compatible_drops_only_the_managed_reference(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        first = self._save(client, monkeypatch, "compatible")
        assert first.status_code == 200, first.text
        assert "api_key: ${ASSISTANT_PROVIDER_API_KEY}" in (
            assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")
        )

        second = self._save(client, monkeypatch, "openai")

        assert second.status_code == 200, second.text
        config = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")
        assert "api_key: ${ASSISTANT_PROVIDER_API_KEY}" not in config
        assert "provider: custom" in config

    def test_key_clear_drops_the_managed_reference(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        saved = self._save(client, monkeypatch, "compatible")
        assert saved.status_code == 200, saved.text

        cleared = client.request(
            "DELETE",
            "/api/profile/assistant/configuration/key",
            json={"revision": saved.json()["revision"]},
        )

        assert cleared.status_code == 200, cleared.text
        config = assistant_settings._resolve_profile_paths().config.read_text(encoding="utf-8")
        assert "api_key: ${ASSISTANT_PROVIDER_API_KEY}" not in config
        assert "provider: custom" in config

    def test_a_foreign_model_api_key_is_preserved(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        paths = assistant_settings._resolve_profile_paths()
        paths.config.write_text(
            "model:\n  default: old-model\n  provider: opencode-go\n"
            "  base_url: https://opencode.ai/zen/go/v1\n"
            "  api_key: ${SOME_OTHER_VARIABLE}\n",
            encoding="utf-8",
        )

        response = client.put("/api/profile/assistant", json={"model": "deepseek-v4-flash"})

        assert response.status_code == 200, response.text
        config = paths.config.read_text(encoding="utf-8")
        assert "api_key: ${SOME_OTHER_VARIABLE}" in config


class TestRuntimeRunProbeWiring:
    """S5 — the wired acceptance probe uses the configured gateway and fails
    closed. Unit coverage for the probe itself lives in
    ``test_hermes_run_probe.py``; this pins the api_server seam."""

    def test_api_server_acceptance_uses_the_real_run_probe(self, monkeypatch):
        seen: dict[str, object] = {}

        class _FakeProbe:
            def __init__(self, base_url, *, api_key=""):
                seen["base_url"] = base_url
                seen["api_key"] = api_key

            def probe(self) -> bool:
                seen["called"] = True
                return True

        monkeypatch.setattr(api_server, "HermesRunProbe", _FakeProbe)
        monkeypatch.setattr(
            api_server, "_GATEWAY_URL", "http://127.0.0.1:8642/v1/chat/completions"
        )
        monkeypatch.setattr(api_server, "_GATEWAY_KEY", "gateway-fixture")

        assert api_server._assistant_runtime_run_probe() is True
        assert seen == {
            "base_url": "http://127.0.0.1:8642/v1",
            "api_key": "gateway-fixture",
            "called": True,
        }

    def test_api_server_run_probe_fails_closed_on_error(self, monkeypatch):
        class _ExplodingProbe:
            def __init__(self, *args, **kwargs):
                pass

            def probe(self) -> bool:
                raise RuntimeError("boom")

        monkeypatch.setattr(api_server, "HermesRunProbe", _ExplodingProbe)

        assert api_server._assistant_runtime_run_probe() is False
