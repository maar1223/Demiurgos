# -*- coding: utf-8 -*-
"""Fresh-install assistant setup — end-to-end, hermetic.

Reproduces the Owner's reported fresh-install shape with a temporary HOME that
has **no** ``~/.hermes``:

1. the installer's data-root seed (no ``HERMES_GATEWAY_KEY``);
2. ``provision-hermes.sh`` seeds the dedicated profile (``config.yaml`` +
   ``API_SERVER_ENABLED``);
3. the launcher generates and persists the gateway key and bridges
   ``API_SERVER_KEY`` into the profile ``.env``;
4. the API answers ``GET /api/profile/assistant`` with 200 for the still
   unconfigured profile and a save creates ``config.yaml`` + the provider key;
5. the bridged ``API_SERVER_KEY`` survives the save, so the gateway API server
   and the Demiurgos client keep sharing one secret.

No network, no real Hermes runtime, no user home.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _path in (str(_WIKI), str(_SUITE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import assistant_settings  # noqa: E402
from assistant_provider_adapters import ProviderRegistry  # noqa: E402
from capability_probes.runner import ProbeResult  # noqa: E402

REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo
PROVISION_SH = REPO_ROOT / "scripts" / "provision-hermes.sh"
LAUNCHER_SH = REPO_ROOT / "scripts" / "start-demiurgos.sh"

_BASH = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX-bash probe (on Windows `bash` is the WSL stub)",
)


class _FakeProbeRunner:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def run_text(self) -> ProbeResult:
        return ProbeResult("passed", "text-marker")

    def run_vision(self) -> ProbeResult:
        return ProbeResult("passed", "causal-vision")


def _env_value(path: Path, key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


@_BASH
def test_fresh_install_can_configure_the_assistant_without_a_personal_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "home"
    home.mkdir()
    assert not (home / ".hermes").exists()
    install = tmp_path / "install"
    data_root = tmp_path / "Demiurgos"
    data_root.mkdir()
    # The installer's seed: no HERMES_GATEWAY_KEY (the reported fresh-install gap).
    (data_root / ".env").write_text("DEMIURGOS_AUTH_MODE=local-dev\n", encoding="utf-8")

    probe = (
        'source "$1" __probe__ || true; '
        'source "$2" __probe__ || true; '
        'resolve_paths ""; seed_profile; '
        'DATA_ROOT="$3"; load_data_root_env; ensure_gateway_key; '
        'export HERMES_HOME="$PRODUCT_HERMES_HOME"; bridge_gateway_key; '
        'printf "%s" "${HERMES_GATEWAY_KEY:-}"'
    )
    result = subprocess.run(
        ["bash", "-c", probe, "bash", str(LAUNCHER_SH), str(PROVISION_SH), str(data_root)],
        env={
            "HOME": str(home),
            "DEMIURGOS_HOME": str(install),
            "TMPDIR": str(tmp_path / "tmp"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    gateway_key = result.stdout.strip()
    assert len(gateway_key) >= 16

    profile = install / "hermes"
    assert (profile / "config.yaml").read_text(encoding="utf-8") == "model: {}\n"
    assert _env_value(profile / ".env", "API_SERVER_ENABLED") == "true"
    assert _env_value(profile / ".env", "API_SERVER_KEY") == gateway_key
    assert _env_value(data_root / ".env", "HERMES_GATEWAY_KEY") == gateway_key
    # The personal profile was never created or touched.
    assert not (home / ".hermes").exists()

    # The API now configures the still-empty dedicated profile.
    monkeypatch.setenv("HERMES_HOME", str(profile))
    monkeypatch.setattr(
        assistant_settings, "ProbeRunner",
        lambda *args, **kwargs: _FakeProbeRunner(*args, **kwargs),
    )
    registry = ProviderRegistry()
    registry.transport = lambda method, url, headers: (
        200,
        {"data": [{"id": "gpt-5.6-luna", "name": "GPT-5.6 Luna"}]},
    )
    local_app = FastAPI()
    local_app.include_router(
        assistant_settings.create_assistant_settings_router(
            require_principal=lambda request: object(),
            provider_registry=registry,
        )
    )
    client = TestClient(local_app, client=("127.0.0.1", 50000))

    assert client.get("/api/profile/assistant").status_code == 200
    saved = client.put(
        "/api/profile/assistant/configuration",
        json={
            "provider": "openai",
            "api_key": "fresh-install-fixture-key",
            "manual_model_id": "manual-model",
        },
    )
    assert saved.status_code == 200, saved.text
    assert "default: manual-model" in (profile / "config.yaml").read_text(encoding="utf-8")
    assert _env_value(profile / ".env", "OPENAI_API_KEY") == "fresh-install-fixture-key"
    # The bridge survives the save: one secret for the client and the server.
    assert _env_value(profile / ".env", "API_SERVER_KEY") == gateway_key
    assert _env_value(profile / ".env", "API_SERVER_ENABLED") == "true"
