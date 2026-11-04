# -*- coding: utf-8 -*-
"""Fresh-install assistant setup — launcher gateway-key bridge.

A fresh install seeds the data-root ``.env`` without ``HERMES_GATEWAY_KEY``
and the dedicated Hermes profile without ``config.yaml``. The POSIX launcher
owns the bridge that makes the assistant work out of the box:

- generate and persist ``HERMES_GATEWAY_KEY`` once in ``$DATA_ROOT/.env``;
- export it to both children;
- hand ``API_SERVER_ENABLED=true`` / ``API_SERVER_KEY=<same key>`` to the
  gateway (which enables its API server only for a usable key);
- reconcile the product profile ``.env`` because the runtime loads it with
  ``override=True``.

Text scans pin the wiring; the behavioural probes source the real portable
script with an unknown action and drive the same helpers ``start_services``
calls, so nothing spawns and no user profile is touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

PORTABLE_LAUNCHER = REPO_ROOT / "scripts" / "start-demiurgos.sh"

_BASH = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX-bash sourcing probe (on Windows `bash` is the WSL stub)",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_probe(tmp_path: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script, "bash", str(PORTABLE_LAUNCHER), *args],
        env={
            "HOME": str(tmp_path / "home"),
            "TMPDIR": str(tmp_path / "tmp"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_launcher_loads_the_gateway_key_from_the_data_root_env():
    text = _text(PORTABLE_LAUNCHER)
    assert "DEMIURGOS_*|HERMES_GATEWAY_KEY)" in text


def test_launcher_generates_persists_and_bridges_the_gateway_key():
    text = _text(PORTABLE_LAUNCHER)
    assert "ensure_gateway_key" in text
    assert "bridge_gateway_key" in text
    assert 'HERMES_GATEWAY_KEY="$(generate_gateway_key)"' in text
    assert 'set_env_value "$env_file" HERMES_GATEWAY_KEY "$HERMES_GATEWAY_KEY"' in text


def test_launcher_bridge_precedes_both_children():
    text = _text(PORTABLE_LAUNCHER)
    assert text.index("ensure_gateway_key") < text.index("start_component gateway")
    assert text.index("bridge_gateway_key") < text.index("start_component api")


def test_gateway_child_receives_api_server_enabled_and_key():
    text = _text(PORTABLE_LAUNCHER)
    assert 'API_SERVER_ENABLED="${API_SERVER_ENABLED:-}"' in text
    assert 'API_SERVER_KEY="${API_SERVER_KEY:-}"' in text


def test_windows_launchers_mirror_the_gateway_key_bridge():
    gateway = _text(REPO_ROOT / "start-gateway.ps1")
    assert "Initialize-GatewayKey" in gateway
    assert "Bridge-GatewayKey" in gateway
    assert "$env:API_SERVER_KEY = $env:HERMES_GATEWAY_KEY" in gateway
    assert '$env:API_SERVER_ENABLED = "true"' in gateway
    assert '[guid]::NewGuid().ToString("N")' in gateway
    gateway.encode("ascii")

    launcher = _text(REPO_ROOT / "start-demiurgos.ps1")
    assert "Initialize-GatewayKey" in launcher
    assert '$key -eq "HERMES_GATEWAY_KEY"' in launcher
    assert "$env:HERMES_HOME = $productHermesHome" in launcher
    launcher.encode("ascii")


# ---------------------------------------------------------------------------
# Behaviour (hermetic)
# ---------------------------------------------------------------------------


@_BASH
def test_ensure_gateway_key_is_generated_once_and_persisted(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / ".env").write_text("DEMIURGOS_LANGUAGE=es\n", encoding="utf-8")
    probe = (
        'source "$1" __probe__ || true; '
        'DATA_ROOT="$2"; '
        'load_data_root_env; ensure_gateway_key; '
        'first="$HERMES_GATEWAY_KEY"; '
        'before="$(cksum "$DATA_ROOT/.env")"; '
        'unset HERMES_GATEWAY_KEY; '
        'load_data_root_env; ensure_gateway_key; '
        'after="$(cksum "$DATA_ROOT/.env")"; '
        'printf "LEN=%s|SAME=%s|STABLE=%s|EXPORTED=%s" '
        '"${#first}" "$([ "$before" = "$after" ] && echo yes || echo no)" '
        '"$([ "$first" = "$HERMES_GATEWAY_KEY" ] && echo yes || echo no)" '
        '"$([ -n "${HERMES_GATEWAY_KEY:-}" ] && echo yes || echo no)"'
    )
    result = _run_probe(tmp_path, probe, str(data_root))
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "LEN=" in out
    length = int(out.split("LEN=", 1)[1].split("|", 1)[0])
    assert length >= 16
    assert "SAME=yes" in out
    assert "STABLE=yes" in out
    assert "EXPORTED=yes" in out
    # The pre-existing line survives untouched.
    assert "DEMIURGOS_LANGUAGE=es" in (data_root / ".env").read_text(encoding="utf-8")


@_BASH
def test_ensure_gateway_key_keeps_an_existing_key(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / ".env").write_text(
        "HERMES_GATEWAY_KEY=keep-me-please-0123456789\n", encoding="utf-8"
    )
    probe = (
        'source "$1" __probe__ || true; '
        'DATA_ROOT="$2"; '
        'load_data_root_env; ensure_gateway_key; '
        'printf "%s" "$HERMES_GATEWAY_KEY"'
    )
    result = _run_probe(tmp_path, probe, str(data_root))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "keep-me-please-0123456789"


@_BASH
def test_bridge_gateway_key_reconciles_the_profile_env(tmp_path: Path):
    profile = tmp_path / "hermes"
    profile.mkdir()
    (profile / ".env").write_text(
        "KEEP_ME=1\nAPI_SERVER_KEY=stale-value\n", encoding="utf-8"
    )
    probe = (
        'source "$1" __probe__ || true; '
        'HERMES_GATEWAY_KEY="bridge-fixture-0123456789"; '
        'HERMES_HOME="$2"; '
        'bridge_gateway_key; '
        'printf "ENABLED=%s|KEY=%s|ENVKEY=%s" '
        '"${API_SERVER_ENABLED:-}" "${API_SERVER_KEY:-}" "${HERMES_GATEWAY_KEY:-}"'
    )
    result = _run_probe(tmp_path, probe, str(profile))
    assert result.returncode == 0, result.stderr
    assert (
        result.stdout
        == "ENABLED=true|KEY=bridge-fixture-0123456789|ENVKEY=bridge-fixture-0123456789"
    )
    text = (profile / ".env").read_text(encoding="utf-8")
    assert "KEEP_ME=1" in text
    assert "API_SERVER_ENABLED=true" in text
    assert "API_SERVER_KEY=bridge-fixture-0123456789" in text
    assert "stale-value" not in text


@_BASH
def test_bridge_gateway_key_is_idempotent(tmp_path: Path):
    profile = tmp_path / "hermes"
    profile.mkdir()
    (profile / ".env").write_text("KEEP_ME=1\n", encoding="utf-8")
    probe = (
        'source "$1" __probe__ || true; '
        'HERMES_GATEWAY_KEY="bridge-fixture-0123456789"; '
        'HERMES_HOME="$2"; '
        'bridge_gateway_key; before="$(cksum "$HERMES_HOME/.env")"; '
        'bridge_gateway_key; after="$(cksum "$HERMES_HOME/.env")"; '
        'printf "%s" "$([ "$before" = "$after" ] && echo SAME || echo CHANGED)"'
    )
    result = _run_probe(tmp_path, probe, str(profile))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "SAME"
