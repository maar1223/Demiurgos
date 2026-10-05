# -*- coding: utf-8 -*-
"""hermes-isolated-profile (WU 0.1) — installer dedicated-root isolation.

The one-command bootstrap (``install.sh``) is the SOLE provisioner of the
dedicated product Hermes root: it resolves ``DEMIURGOS_HERMES_HOME`` with the
same chain as the launcher and points ``HERMES_CONFIG`` at
``<dedicated root>/config.yaml``, so the Engram MCP block and every product
write target the dedicated profile — never the personal ``~/.hermes``. No
``active_profile`` pointer is ever created under the dedicated root (spec
``hermes-isolated-profile``).

Text scans mirror ``test_installer_contract.py``: the installer is a CODE
artifact of the checkout, located from this file. ``configure_mcp_profile``
stays personal/dev-only per the ratified design; the isolation contract here is
that no product write touches ``$HOME/.hermes/config.yaml``. The skills-merge
half of this file belongs to work unit 0.2 and is NOT implemented here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

INSTALL_SH = REPO_ROOT / "install.sh"

#: Exact resolution chain shared with scripts/start-demiurgos.sh (spec
#: 'Dedicated root resolution'): explicit override -> ${DEMIURGOS_HOME:-$HOME/.demiurgos}/hermes.
RESOLUTION_CHAIN = "${DEMIURGOS_HERMES_HOME:-${DEMIURGOS_HOME:-$HOME/.demiurgos}/hermes}"
_HERMES_HOME_DERIVATION = 'DEMIURGOS_HERMES_HOME="' + RESOLUTION_CHAIN + '"'
_HERMES_CONFIG = 'HERMES_CONFIG="$DEMIURGOS_HERMES_HOME/config.yaml"'
_OLD_PERSONAL_CONFIG = 'HERMES_CONFIG="$HOME/.hermes/config.yaml"'


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_installer_derives_dedicated_hermes_home_with_shared_chain():
    """Spec 'Dedicated root resolution': the installer resolves the product
    Hermes home through the exact chain the launcher uses."""
    text = _text(INSTALL_SH)
    assert _HERMES_HOME_DERIVATION in text


def test_installer_points_hermes_config_at_dedicated_root():
    """Spec 'Installer writes only the dedicated config': HERMES_CONFIG is the
    dedicated root's config.yaml, so every write through the variable (the
    Engram MCP block) targets the product profile."""
    text = _text(INSTALL_SH)
    assert _HERMES_CONFIG in text


def test_installer_never_writes_personal_hermes_config():
    """Spec 'Installer never writes the personal profile': no product write
    targets $HOME/.hermes/config.yaml — the historical constant is gone and
    the literal appears nowhere in the installer."""
    text = _text(INSTALL_SH)
    assert _OLD_PERSONAL_CONFIG not in text
    assert "$HOME/.hermes/config.yaml" not in text


def test_installer_config_writes_go_through_hermes_config_variable():
    """Spec 'Installer writes only the dedicated config': configure_engram's
    provisioning writes (parent mkdir, the `---` seed, the mcp: heredocs) all
    go through $HERMES_CONFIG, which now resolves under the dedicated root."""
    text = _text(INSTALL_SH)
    assert 'mkdir -p "$(dirname "$HERMES_CONFIG")"' in text
    assert '> "$HERMES_CONFIG"' in text
    assert '>> "$HERMES_CONFIG"' in text


def test_installer_creates_no_active_profile():
    """Spec 'No active_profile in the dedicated root': the installer never
    creates an active_profile pointer; the bare root resolves profile == root."""
    assert "active_profile" not in _text(INSTALL_SH)


def test_installer_dedicated_root_outside_personal_and_data_roots():
    """Spec 'Resolved root is outside the personal and data roots': the chain
    resolves under $HOME/.demiurgos — never under ~/.hermes and never a named
    profile under profiles/."""
    text = _text(INSTALL_SH)
    assert RESOLUTION_CHAIN in text
    assert "$HOME/.hermes" not in RESOLUTION_CHAIN
    assert "profiles/" not in RESOLUTION_CHAIN


def test_installer_resolution_chain_evaluates_per_spec(tmp_path: Path):
    """Spec 'Dedicated root resolution' (behavioural): evaluate the exact chain
    bash reads. Environment override wins; DEMIURGOS_HOME supplies the default;
    with neither, the root is $HOME/.demiurgos/hermes."""
    home = tmp_path / "home"
    override = tmp_path / "custom-hermes-root"
    chain_expr = (
        'PRODUCT="${DEMIURGOS_HERMES_HOME:-${DEMIURGOS_HOME:-$HOME/.demiurgos}/hermes}"; '
        'printf "%s" "$PRODUCT"'
    )
    base_env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    # Environment override wins (never falls back to the default path).
    result = subprocess.run(
        ["bash", "-c", chain_expr],
        env={**base_env, "DEMIURGOS_HERMES_HOME": str(override)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(override)

    # Default path when DEMIURGOS_HOME is set.
    demiurgos_home = tmp_path / "opt"
    result = subprocess.run(
        ["bash", "-c", chain_expr],
        env={**base_env, "DEMIURGOS_HOME": str(demiurgos_home)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{demiurgos_home}/hermes"

    # Default path with no DEMIURGOS_HOME: $HOME/.demiurgos/hermes.
    result = subprocess.run(
        ["bash", "-c", chain_expr],
        env=base_env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{home}/.demiurgos/hermes"