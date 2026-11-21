# -*- coding: utf-8 -*-
"""Assistant world-reading — graph MCP provisioning (contract I1/I6).

The assistant reads the author's world through the ``demiurgos-graph`` MCP
server. That server's ``--mundos-path`` must come from the data root, never from
the code tree: on 2026-11-18 the profile pointed at
``${env:DEMIURGOS_ROOT}/mundos`` (a directory the install payload never ships)
and the assistant was blind for ~16 days while every other surface stayed
healthy. See ``docs/architecture/ASSISTANT_WORLD_READING.md``.

These tests pin the provisioning contract:

- the product registers the server itself (I6), idempotently;
- the registered entry launches ``mcp_launcher.py``, which resolves the data
  root at runtime instead of hardcoding an author-data path or a world (I1/I3);
- a stale/incident-shaped entry is *corrected*, not left behind (I5);
- sibling servers and every other top-level key survive the merge.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hermes_profile_config import (
    GRAPH_MCP_LAUNCHER_REL,
    GRAPH_MCP_SERVER_NAME,
    merge_graph_mcp_server,
    remove_engram_mcp_server,
)

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[4]
LAUNCHER = REPO_ROOT / GRAPH_MCP_LAUNCHER_REL


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _entry(config: Path) -> dict:
    return _read_yaml(config)["mcp_servers"][GRAPH_MCP_SERVER_NAME]


def test_registers_launcher_when_absent(tmp_path):
    """First run registers the server, and it launches mcp_launcher.py."""
    config = tmp_path / "config.yaml"

    assert merge_graph_mcp_server(config) is True

    entry = _entry(config)
    assert entry["command"] == "python3"
    assert entry["cwd"] == "${env:DEMIURGOS_ROOT}"
    assert entry["args"] == ["${env:DEMIURGOS_ROOT}/" + GRAPH_MCP_LAUNCHER_REL.as_posix()]


def test_rerun_is_idempotent(tmp_path):
    """A second run is a no-op and does not rewrite the file."""
    config = tmp_path / "config.yaml"
    assert merge_graph_mcp_server(config) is True
    before = config.read_bytes()

    assert merge_graph_mcp_server(config) is False
    assert config.read_bytes() == before


def test_corrects_the_incident_shape(tmp_path):
    """The 2026-11-18 entry (direct server + code-tree mundos path) is corrected."""
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "mcp_servers": {
                    GRAPH_MCP_SERVER_NAME: {
                        "command": "python3",
                        "cwd": "${env:DEMIURGOS_ROOT}",
                        "args": [
                            "${env:DEMIURGOS_ROOT}/src/tools/demiurgos-suite/wiki/graph_mcp_server.py",
                            "--mundo",
                            "Vibrantes",
                            "--mundos-path",
                            "${env:DEMIURGOS_ROOT}/mundos",
                        ],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert merge_graph_mcp_server(config) is True

    args = _entry(config)["args"]
    assert args == ["${env:DEMIURGOS_ROOT}/" + GRAPH_MCP_LAUNCHER_REL.as_posix()]
    assert "--mundos-path" not in args
    assert "--mundo" not in args


def test_preserves_other_servers_and_keys(tmp_path):
    """Sibling MCP servers and unrelated top-level keys survive untouched."""
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "model": {"default": "deepseek-v4.1-flash"},
                "mcp_servers": {
                    "engram": {"command": "engram", "args": ["mcp"]},
                    GRAPH_MCP_SERVER_NAME: {"command": "python3", "args": ["stale.py"]},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert merge_graph_mcp_server(config) is True

    data = _read_yaml(config)
    assert data["model"] == {"default": "deepseek-v4.1-flash"}
    assert data["mcp_servers"]["engram"] == {"command": "engram", "args": ["mcp"]}
    assert _entry(config)["args"] == [
        "${env:DEMIURGOS_ROOT}/" + GRAPH_MCP_LAUNCHER_REL.as_posix()
    ]


def test_never_hardcodes_author_data_or_a_world(tmp_path):
    """The registration carries no author-data path and no world name (I1/I3)."""
    config = tmp_path / "config.yaml"
    merge_graph_mcp_server(config)

    serialized = yaml.safe_dump(_entry(config))
    assert "mundos" not in serialized.replace("mcp_launcher.py", "")
    assert "Vibrantes" not in serialized
    assert str(REPO_ROOT) not in serialized


def test_registered_launcher_resolves_the_data_root():
    """The registered launcher exists in the checkout and resolves the data root."""
    assert LAUNCHER.is_file()
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "resolve_data_root" in source
    assert "--mundos-path={_project_root() / 'mundos'}" in source


def test_installer_registers_the_graph_server():
    """The checkout installer invokes the merge through the venv Python, after
    that venv is prepared and from the step that installs Demiurgos."""
    installer = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    assert "merge_graph_mcp_server" in installer
    assert "hermes_profile_config" in installer

    main_flow = installer[installer.index("main_cli_stack()"):]
    main_flow = main_flow[: main_flow.index("main() {")]
    assert main_flow.index("prepare_python_env") < main_flow.index("install_demiurgos")

    install_step = installer[installer.index("install_demiurgos() {"):]
    install_step = install_step[: install_step.index("merge_assistant_platform_hint() {")]
    assert "merge_graph_mcp" in install_step


def test_shipped_installer_wires_the_graph_after_provisioning_the_runtime():
    """The shipping installer registers the server through the payload merge,
    only after the Hermes runtime (and the app venv) exist, and never with a
    hardcoded author-data path."""
    installer = (REPO_ROOT / "scripts" / "install-demiurgos.sh").read_text(encoding="utf-8")
    assert "provision_graph_mcp()" in installer
    assert "merge_graph_mcp_server" in installer
    assert "DEMIURGOS_ROOT}/mundos" not in installer

    main_flow = installer[installer.index("# --- main ---"):]
    runtime = main_flow.index("provision_hermes_runtime")
    graph = main_flow.index("provision_graph_mcp")
    assert runtime < graph


def test_windows_core_wires_the_graph_after_provisioning_the_runtime():
    """Windows parity: the shipped .ps1 core must wire the graph server too.

    The POSIX core registers ``demiurgos-graph`` after provisioning Hermes; the
    Windows core did not, so a fresh Windows install left the assistant blind
    to the world while every other surface looked healthy.
    """
    installer = (
        REPO_ROOT / "scripts" / "install-demiurgos.ps1"
    ).read_text(encoding="utf-8")
    assert "function Invoke-GraphMcpProvision" in installer
    assert "merge_graph_mcp_server" in installer
    assert "remove_engram_mcp_server" in installer
    assert "current\\.venv\\Scripts\\python.exe" in installer
    assert "hermes_profile_config" in installer

    main_flow = installer[installer.index("# --- main"):]
    assert main_flow.index("Invoke-HermesProvision") < main_flow.index(
        "Invoke-GraphMcpProvision"
    )


# =============================================================================
# Engram cutover — corrective removal of the legacy MCP server
# =============================================================================


def _config_with_engram(tmp_path: Path, extra_server: dict | None = None) -> Path:
    mcp_servers = {
        "engram": {
            "command": "engram",
            "args": ["mcp", "--tools=mem_save,mem_search"],
        },
        GRAPH_MCP_SERVER_NAME: {"command": "python3", "args": ["stale.py"]},
        "other": extra_server or {"command": "other-binary"},
    }
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {"model": {"default": "deepseek-v4.1-flash"}, "mcp_servers": mcp_servers},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config


def test_removes_the_legacy_engram_server_and_preserves_everything_else(tmp_path):
    """The corrective removal drops only ``mcp_servers.engram``."""
    config = _config_with_engram(tmp_path)

    assert remove_engram_mcp_server(config) is True

    data = _read_yaml(config)
    assert "engram" not in data["mcp_servers"]
    assert data["mcp_servers"]["other"] == {"command": "other-binary"}
    assert data["mcp_servers"][GRAPH_MCP_SERVER_NAME] == {
        "command": "python3", "args": ["stale.py"],
    }
    assert data["model"] == {"default": "deepseek-v4.1-flash"}


def test_removal_is_idempotent_and_reports_no_write_when_absent(tmp_path):
    """A second run writes nothing and returns False."""
    config = _config_with_engram(tmp_path)

    assert remove_engram_mcp_server(config) is True
    assert remove_engram_mcp_server(config) is False
    assert remove_engram_mcp_server(config) is False


def test_removal_tolerates_a_missing_config(tmp_path):
    """No config yet is not an error — nothing to remove, nothing created."""
    config = tmp_path / "missing" / "config.yaml"

    assert remove_engram_mcp_server(config) is False
    assert not config.exists()


def test_removal_tolerates_a_non_mapping_mcp_servers_key(tmp_path):
    """A malformed config is left untouched instead of crashing provisioning."""
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"mcp_servers": ["nope"]}), encoding="utf-8")

    assert remove_engram_mcp_server(config) is False
    assert _read_yaml(config) == {"mcp_servers": ["nope"]}


def test_provisioning_sequence_heals_an_existing_install(tmp_path):
    """merge + remove is what both installers run: the graph is registered and
    the Engram block is gone, in one idempotent pass."""
    config = _config_with_engram(tmp_path)

    merge_graph_mcp_server(config)
    remove_engram_mcp_server(config)

    data = _read_yaml(config)
    assert "engram" not in data["mcp_servers"]
    assert data["mcp_servers"][GRAPH_MCP_SERVER_NAME]["args"] == [
        "${env:DEMIURGOS_ROOT}/" + GRAPH_MCP_LAUNCHER_REL.as_posix()
    ]
    assert data["mcp_servers"]["other"] == {"command": "other-binary"}
