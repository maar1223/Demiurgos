# -*- coding: utf-8 -*-
"""The world-reading gate must not false-PASS a blind wiring.

``scripts/check_assistant_graph.py`` expands the profile's ``${env:...}``
placeholders and must resolve a *relative* ``--mundos-path`` against the MCP
process' own ``cwd`` — never against the checker's cwd. Joining it to the
checker's cwd made the gate report PASS while the assistant was blind, which is
the exact failure class the gate exists to catch
(``docs/architecture/ASSISTANT_WORLD_READING.md``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from hermes_profile_config import (
    GRAPH_MCP_LAUNCHER_REL,
    GRAPH_MCP_SERVER_NAME,
    merge_graph_mcp_server,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
GATE = REPO_ROOT / "scripts" / "check_assistant_graph.py"


def _profile(home: Path, args: list[str], *, cwd: str = "${env:DEMIURGOS_ROOT}") -> Path:
    home.mkdir(parents=True, exist_ok=True)
    entry = {"command": "python3", "args": args}
    if cwd:
        entry["cwd"] = cwd
    (home / "config.yaml").write_text(
        yaml.safe_dump({"mcp_servers": {GRAPH_MCP_SERVER_NAME: entry}}, sort_keys=False),
        encoding="utf-8",
    )
    return home


def test_gate_rejects_relative_mundos_path(tmp_path):
    """A relative ``--mundos-path`` resolves against the MCP cwd, which in the
    installed layout has no ``mundos/`` — the gate must FAIL, not PASS."""
    decoy = tmp_path / "decoy"
    (decoy / "mundos" / "Vibrantes" / "lore").mkdir(parents=True)
    (decoy / "mundos" / "Vibrantes" / "lore" / "x.md").write_text("# x\n", encoding="utf-8")

    data_root = tmp_path / "data"
    (data_root / "mundos" / "Vibrantes" / "lore").mkdir(parents=True)
    (data_root / "mundos" / "Vibrantes" / "lore" / "x.md").write_text("# x\n", encoding="utf-8")

    current = tmp_path / "install" / "current"
    wiki = current / "src" / "tools" / "demiurgos-suite" / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "graph_mcp_server.py").write_text("", encoding="utf-8")
    # The installed app root intentionally has NO mundos/ directory.

    profile = _profile(
        tmp_path / "profile",
        [
            "${env:DEMIURGOS_ROOT}/src/tools/demiurgos-suite/wiki/graph_mcp_server.py",
            "--mundo", "Vibrantes",
            "--mundos-path", "mundos",
        ],
    )
    env = dict(
        os.environ,
        HOME=str(tmp_path / "home"),
        DEMIURGOS_HOME=str(tmp_path / "install"),
        DEMIURGOS_DATA_ROOT=str(data_root),
        HERMES_HOME=str(profile),
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [sys.executable, str(GATE)], cwd=decoy, env=env, capture_output=True, text=True
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "does not exist" in result.stdout


def test_gate_passes_a_launcher_entry(tmp_path):
    """The canonical launcher entry resolves the data root at runtime: PASS."""
    data_root = tmp_path / "data"
    (data_root / "mundos" / "Vibrantes" / "lore").mkdir(parents=True)
    (data_root / "mundos" / "Vibrantes" / "lore" / "x.md").write_text("# x\n", encoding="utf-8")

    current = tmp_path / "install" / "current"
    wiki = current / "src" / "tools" / "demiurgos-suite" / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "mcp_launcher.py").write_text("", encoding="utf-8")

    profile = _profile(
        tmp_path / "profile",
        ["${env:DEMIURGOS_ROOT}/" + GRAPH_MCP_LAUNCHER_REL.as_posix()],
    )
    env = dict(
        os.environ,
        HOME=str(tmp_path / "home"),
        DEMIURGOS_HOME=str(tmp_path / "install"),
        DEMIURGOS_DATA_ROOT=str(data_root),
        HERMES_HOME=str(profile),
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [sys.executable, str(GATE)], cwd=tmp_path, env=env, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERDICT: PASS" in result.stdout


def test_merge_preserves_extra_entry_keys(tmp_path):
    """Sibling entry keys (type/enabled) survive a no-op merge byte-for-byte."""
    config = tmp_path / "config.yaml"
    canonical = ["${env:DEMIURGOS_ROOT}/" + GRAPH_MCP_LAUNCHER_REL.as_posix()]
    config.write_text(
        yaml.safe_dump(
            {
                "mcp_servers": {
                    GRAPH_MCP_SERVER_NAME: {
                        "type": "stdio",
                        "enabled": False,
                        "command": "python3",
                        "cwd": "${env:DEMIURGOS_ROOT}",
                        "args": canonical,
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    before = config.read_bytes()

    assert merge_graph_mcp_server(config) is False
    assert config.read_bytes() == before

    entry = yaml.safe_load(before)["mcp_servers"][GRAPH_MCP_SERVER_NAME]
    assert entry["type"] == "stdio"
    assert entry["enabled"] is False


def test_gate_relative_mundos_path_without_cwd_uses_app_root(tmp_path):
    """No profile cwd: the relative path resolves against the app root Hermes
    runs from (the launcher sets CWD=APP_ROOT), never the checker's cwd."""
    decoy = tmp_path / "decoy"
    (decoy / "mundos" / "Vibrantes" / "lore").mkdir(parents=True)
    (decoy / "mundos" / "Vibrantes" / "lore" / "x.md").write_text("# x\n", encoding="utf-8")

    data_root = tmp_path / "data"
    (data_root / "mundos" / "Vibrantes" / "lore").mkdir(parents=True)
    (data_root / "mundos" / "Vibrantes" / "lore" / "x.md").write_text("# x\n", encoding="utf-8")

    current = tmp_path / "install" / "current"
    wiki = current / "src" / "tools" / "demiurgos-suite" / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "graph_mcp_server.py").write_text("", encoding="utf-8")
    # Installed app root intentionally has NO mundos/.

    profile = _profile(
        tmp_path / "profile",
        [
            "${env:DEMIURGOS_ROOT}/src/tools/demiurgos-suite/wiki/graph_mcp_server.py",
            "--mundo", "Vibrantes",
            "--mundos-path", "mundos",
        ],
        cwd="",
    )
    env = dict(
        os.environ,
        HOME=str(tmp_path / "home"),
        DEMIURGOS_HOME=str(tmp_path / "install"),
        DEMIURGOS_DATA_ROOT=str(data_root),
        HERMES_HOME=str(profile),
        PYTHONDONTWRITEBYTECODE="1",
    )
    env.pop("DEMIURGOS_ROOT", None)
    result = subprocess.run(
        [sys.executable, str(GATE)], cwd=decoy, env=env, capture_output=True, text=True
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "does not exist" in result.stdout
    assert str(current / "mundos") in result.stdout
