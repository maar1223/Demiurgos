# -*- coding: utf-8 -*-
"""hermes-isolated-profile (WU 0.1) — launcher HERMES_HOME conditional export.

The portable POSIX launcher (``scripts/start-demiurgos.sh``) derives the
dedicated product Hermes home with the SAME resolution chain as the installer
(explicit ``DEMIURGOS_HERMES_HOME`` -> ``${DEMIURGOS_HOME:-$HOME/.demiurgos}/hermes``)
and exports ``HERMES_HOME`` to the gateway and API children ONLY when that
dedicated root is provisioned (``<root>/config.yaml`` exists). Without a
provisioned profile the launcher leaves ``HERMES_HOME`` unset, prints an
advisory and the product falls back to today's personal-profile resolution —
absence is not an error condition (spec ``hermes-isolated-profile``).

Text scans mirror ``test_launcher_root_propagation.py``: the launcher is a CODE
artifact of the checkout, located from this file, never from a configured data
root. The behavioural probes source the real portable script with an unknown
action so it sets its environment and exits without spawning anything, then
drive the same conditional-export function ``start_all`` calls before the
children start — no server, no gateway, no port binding, no pointer write.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from assistant_settings import _resolve_profile_paths

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

PORTABLE_LAUNCHER = REPO_ROOT / "scripts" / "start-demiurgos.sh"

#: Exact resolution chain shared with install.sh (spec 'Dedicated root
#: resolution'): explicit override -> ${DEMIURGOS_HOME:-$HOME/.demiurgos}/hermes.
RESOLUTION_CHAIN = "${DEMIURGOS_HERMES_HOME:-${DEMIURGOS_HOME:-$HOME/.demiurgos}/hermes}"
_PROD_HOME_DERIVATION = 'PRODUCT_HERMES_HOME="' + RESOLUTION_CHAIN + '"'
_EXPORT_LINE = 'export HERMES_HOME="$PRODUCT_HERMES_HOME"'
_CONFIG_GUARD = '[ -f "$PRODUCT_HERMES_HOME/config.yaml" ]'
#: The dedicated root never carries an active_profile pointer; the children
#: receive the dedicated-root value even when the caller exported a stale
#: HERMES_HOME (spec 'Explicit HERMES_HOME already set in the environment').
_NO_PRESERVE_EXISTING = 'HERMES_HOME="${HERMES_HOME'


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_launcher_derives_dedicated_hermes_home_with_shared_chain():
    """Spec 'Dedicated root resolution': the launcher resolves the product
    Hermes home through the exact chain the installer uses."""
    text = _text(PORTABLE_LAUNCHER)
    assert _PROD_HOME_DERIVATION in text


def test_launcher_exports_hermes_home_guarded_by_provisioned_config():
    """Spec 'Launcher conditional export': the export exists, is guarded by
    the dedicated root's config.yaml, and never preserves a stale caller
    HERMES_HOME over the dedicated-root value."""
    text = _text(PORTABLE_LAUNCHER)
    assert _EXPORT_LINE in text
    assert _CONFIG_GUARD in text
    assert _NO_PRESERVE_EXISTING not in text


def test_launcher_export_precedes_both_children():
    """Spec 'Export when provisioned': the export occurs before either child
    (gateway or API) is started, so both subshells inherit HERMES_HOME."""
    text = _text(PORTABLE_LAUNCHER)
    assert _EXPORT_LINE in text
    assert text.index(_EXPORT_LINE) < text.index("start_component gateway")
    assert text.index(_EXPORT_LINE) < text.index("start_component api")


def test_launcher_prints_advisory_when_unprovisioned():
    """Spec 'No export when unprovisioned': the unprovisioned branch prints an
    advisory instead of silently ignoring the missing profile."""
    text = _text(PORTABLE_LAUNCHER)
    assert "not provisioned" in text


def test_launcher_dedicated_root_outside_personal_and_data_roots():
    """Spec 'Resolved root is outside the personal and data roots': the chain
    resolves under $HOME/.demiurgos — never under ~/.hermes and never a named
    profile under profiles/."""
    text = _text(PORTABLE_LAUNCHER)
    assert RESOLUTION_CHAIN in text
    assert "$HOME/.hermes" not in RESOLUTION_CHAIN
    assert "profiles/" not in RESOLUTION_CHAIN


def test_launcher_never_creates_active_profile():
    """Spec 'No active_profile in the dedicated root': the launcher never
    writes an active_profile pointer (a bare root resolves profile == root)."""
    assert "active_profile" not in _text(PORTABLE_LAUNCHER)


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX-bash sourcing probe (on Windows `bash` is the WSL stub)",
)
def test_launcher_sourcing_hermes_home_export_when_provisioned(tmp_path: Path):
    """Behavioural, hermetic (spec 'Export when provisioned'): source the real
    script with an unknown action, then drive the conditional-export function
    ``start_all`` calls. With a provisioned temp dedicated root (config.yaml
    present) HERMES_HOME is exported pointing at that root. No server, pointer
    or user config is touched."""
    root = tmp_path / "dedicated"
    root.mkdir()
    (root / "config.yaml").write_text("model:\n  provider: test\n", encoding="utf-8")

    probe = (
        'source "$1" __probe__ || true; '
        'export_product_hermes_home; '
        'printf "HH=%s|PHH=%s" "${HERMES_HOME:-UNSET}" "$PRODUCT_HERMES_HOME"'
    )
    result = subprocess.run(
        ["bash", "-c", probe, "bash", str(PORTABLE_LAUNCHER)],
        env={
            "HOME": str(tmp_path / "home"),
            "TMPDIR": str(tmp_path / "tmp"),
            "DEMIURGOS_HERMES_HOME": str(root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"HH={root}|PHH={root}"


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX-bash sourcing probe (on Windows `bash` is the WSL stub)",
)
def test_launcher_sourcing_hermes_home_unset_when_unprovisioned(tmp_path: Path):
    """Behavioural, hermetic (spec 'No export when unprovisioned' + 'Graceful
    fallback when unprovisioned'): with a temp dedicated root that has NO
    config.yaml, HERMES_HOME stays UNSET and an advisory is printed — the
    product falls back to today's resolution and does not fail."""
    root = tmp_path / "dedicated"
    root.mkdir()  # no config.yaml

    probe = (
        'source "$1" __probe__ || true; '
        'export_product_hermes_home; '
        'printf "HH=%s|PHH=%s" "${HERMES_HOME:-UNSET}" "$PRODUCT_HERMES_HOME"'
    )
    result = subprocess.run(
        ["bash", "-c", probe, "bash", str(PORTABLE_LAUNCHER)],
        env={
            "HOME": str(tmp_path / "home"),
            "TMPDIR": str(tmp_path / "tmp"),
            "DEMIURGOS_HERMES_HOME": str(root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"HH=UNSET|PHH={root}"
    assert "not provisioned" in result.stderr.lower()


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX-bash sourcing probe (on Windows `bash` is the WSL stub)",
)
def test_launcher_sourcing_default_chain_without_overrides(tmp_path: Path):
    """Behavioural, hermetic (spec 'Default path with no DEMIURGOS_HOME'): with
    neither override set, PRODUCT_HERMES_HOME resolves to $HOME/.demiurgos/hermes
    under the hermetic temp HOME."""
    home = tmp_path / "home"
    probe = (
        'source "$1" __probe__ || true; '
        'printf "%s" "$PRODUCT_HERMES_HOME"'
    )
    result = subprocess.run(
        ["bash", "-c", probe, "bash", str(PORTABLE_LAUNCHER)],
        env={
            "HOME": str(home),
            "TMPDIR": str(tmp_path / "tmp"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{home}/.demiurgos/hermes"


def test_assistant_settings_follows_hermes_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Spec 'Backend reads follow the environment' (both scenarios): with
    HERMES_HOME pointing at a dedicated root that carries no active_profile,
    the backend resolves root == profile == dedicated root and
    config == <root>/config.yaml — it never reads the personal ~/.hermes."""
    root = tmp_path / "dedicated"
    root.mkdir()
    (root / "config.yaml").write_text("model:\n  provider: test\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(root))

    paths = _resolve_profile_paths()
    assert paths.root == root.resolve()
    assert paths.profile == root.resolve()
    assert paths.config == root.resolve() / "config.yaml"
    assert paths.name == "default"