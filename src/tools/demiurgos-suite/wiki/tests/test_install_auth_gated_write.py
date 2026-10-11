# -*- coding: utf-8 -*-
"""End-to-end install-auth gated-write harness (design S0-A / tasks 0.6).

Models the full fresh-install chain on a clean machine:

1. a fresh data root exists with NO pre-seeded ``.env`` (nothing installed);
2. ``DEMIURGOS_AUTH_MODE`` is UNSET in the process environment;
3. the REAL shipping installer (S3a, ``scripts/install-demiurgos.sh``) runs in
   its documented seed-only mode (``DEMIURGOS_SEED_ONLY=1``) against a tmp
   ``HOME``/``XDG_CONFIG_HOME``/``DEMIURGOS_HOME`` and bootstraps the pointer +
   seeds ``<data_root>/.env`` (design S3-7, ``DEMIURGOS_AUTH_MODE=local-dev``);
4. the launcher export is modelled (S2a ``load_data_root_env``): the seeded
   ``.env`` is parsed and every ``DEMIURGOS_*`` key exported into uvicorn's env;
5. the app boots and an end-to-end gated write must return **2xx, not 401**.

Step 3 is the permanent regression guard for the S0-A contract: it runs the
REAL installer as a subprocess — no Python re-implementation of the seed — and
this test additionally proves the bash-written pointer is readable by Python's
``data_root.read_pointer`` (byte-compatible contract) and that the seed is
idempotent (a re-run leaves pointer and ``.env`` byte-identical). A fresh
install must never boot into a 401 for gated writes again.
"""

import os
import subprocess
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
import data_root  # noqa: E402

_REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo
INSTALLER = _REPO_ROOT / "scripts" / "install-demiurgos.sh"

#: No-op browser stub dir (incident s2b-harness-gotcha): prepended to the child
#: PATH so a launcher that ignores the env flag still cannot open a real
#: browser. The installer never opens a browser; the guard is belt-and-braces.
NOOP_BROWSER_BIN = Path("/tmp/opencode/noop-browser/bin")


def _seed_env(tmp_path: Path) -> dict[str, str]:
    """Hermetic env for the REAL installer's seed-only mode.

    tmp HOME/XDG_CONFIG_HOME/DEMIURGOS_HOME so the real ``~/.demiurgos`` and
    the real data-root pointer are never touched. ``DEMIURGOS_DATA_ROOT`` is
    deliberately NOT set: the installer bootstraps the pointer once — the real
    install-time path. ``DEMIURGOS_AUTH_MODE`` is deliberately absent.
    """
    return {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "DEMIURGOS_HOME": str(tmp_path / "install"),
        "DEMIURGOS_SEED_ONLY": "1",
        "DEMIURGOS_LANGUAGE": "en",
        "DEMIURGOS_NO_BROWSER": "1",
        "PATH": f"{NOOP_BROWSER_BIN}:{os.environ.get('PATH', '/usr/bin:/bin')}",
    }


def _run_seed_only(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Invoke the REAL shipping installer in its documented seed-only mode."""
    return subprocess.run(
        ["bash", str(INSTALLER)],
        env=env, capture_output=True, text=True, timeout=120,
    )


def _launcher_export_env(data_root_path: Path) -> dict[str, str]:
    """Model the S2a launcher's pure-shell export (``load_data_root_env``).

    The launcher reads the resolved data-root ``.env`` in pure shell and
    exports every ``DEMIURGOS_*`` key into uvicorn's env (no system Python).
    This mirrors those semantics exactly: skip blank/``#`` lines, split on the
    first ``=``, strip one layer of surrounding quotes and a trailing CR.
    """
    exported: dict[str, str] = {}
    for line in data_root_path.joinpath(".env").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value[:1] == '"' and value[-1:] == '"':
            value = value[1:-1]
        elif value[:1] == "'" and value[-1:] == "'":
            value = value[1:-1]
        if value.endswith("\r"):
            value = value[:-1]
        if key.startswith("DEMIURGOS_"):
            exported[key] = value
    return exported


@pytest.fixture()
def fresh_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Boot the app against a fresh data root; returns (client, data_root_path,
    seed_env). The data root pre-exists with worlds but NO ``.env`` — the
    installer bootstrap-once must not clobber it (design S3-7)."""
    data_root_path = tmp_path / "install" / "data"  # installer bootstrap default
    (data_root_path / "mundos").mkdir(parents=True)
    for name in ("Avalor", "Kaelia"):
        (data_root_path / "mundos" / name / "lore").mkdir(parents=True)
        (data_root_path / "mundos" / name / "lore" / "inicio.md").write_text(
            "# Inicio\n", encoding="utf-8"
        )

    monkeypatch.setattr(api_server, "MUNDOS_DIR", data_root_path / "mundos")
    monkeypatch.setattr(api_server, "PROJECT_ROOT", data_root_path)
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
    return client, data_root_path, _seed_env(tmp_path)


def _delete_json(client: TestClient, url: str, payload: dict):
    """DELETE with a JSON body (httpx2 delete() has no body kwargs)."""
    return client.request("DELETE", url, json=payload)


@pytest.mark.skipif(
    os.name == "nt",
    reason="runs the POSIX installer core through bash (not available on Windows)",
)
class TestInstallAuthGatedWrite:
    def test_fresh_install_gated_write_is_2xx_not_401(
        self,
        fresh_install: tuple[TestClient, Path, dict[str, str]],
        monkeypatch: pytest.MonkeyPatch,
    ):
        client, data_root_path, seed_env = fresh_install

        # Fresh machine: no seed anywhere, auth mode UNSET in the process env.
        assert not (data_root_path / ".env").exists()
        assert "DEMIURGOS_AUTH_MODE" not in os.environ

        # Unseeded baseline: the app fails closed — gated write is 401 (pinned).
        unseeded = _delete_json(client, "/api/worlds/Avalor", {"confirm_name": "Avalor"})
        assert unseeded.status_code == 401, unseeded.text

        # REAL install-chain seed: the shipping installer's seed-only mode.
        seeded = _run_seed_only(seed_env)
        assert seeded.returncode == 0, seeded.stdout + seeded.stderr

        env_file = data_root_path / ".env"
        assert env_file.is_file(), seeded.stdout + seeded.stderr
        exported = _launcher_export_env(data_root_path)
        assert exported["DEMIURGOS_AUTH_MODE"] == "local-dev"

        # Pointer byte-compat: bash wrote it, Python's read_pointer resolves it.
        pointer_dir = Path(seed_env["XDG_CONFIG_HOME"]) / "demiurgos"
        assert data_root.read_pointer(config_dir=pointer_dir) == data_root_path.resolve()

        # Idempotence: a second seed run leaves pointer and .env untouched.
        pointer_file = pointer_dir / data_root.POINTER_NAME
        env_before, pointer_before = env_file.read_bytes(), pointer_file.read_bytes()
        again = _run_seed_only(seed_env)
        assert again.returncode == 0, again.stderr
        assert env_file.read_bytes() == env_before
        assert pointer_file.read_bytes() == pointer_before

        # Launcher export (S2a load_data_root_env): DEMIURGOS_* into the app env.
        for key, value in exported.items():
            monkeypatch.setenv(key, value)

        started = client.post("/api/auth/local-dev/session")
        assert started.status_code == 200, started.text

        response = _delete_json(client, "/api/worlds/Avalor", {"confirm_name": "Avalor"})
        assert response.status_code == 200, response.text  # 2xx, not 401
        assert response.json()["world_name"] == "Avalor"