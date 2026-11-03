# -*- coding: utf-8 -*-
"""Product-owned Hermes runtime provisioning (hermes-core-runtime T3/T4).

``scripts/provision-hermes.{sh,ps1}`` are the ONE provisioning owner invoked by
the app installers and the CLI stack. The contract:

- the runtime is the pinned public fork, fetched by commit (no upstream-latest
  at install time) and verified against a fixed 40-hex pin;
- the checkout, ``HERMES_HOME`` and the tool store live under the product root;
- a pre-existing Hermes/personal profile is reported and never modified;
- the pinned setup runs with product paths and a scratch HOME, so the user's
  ``~/.local/bin`` and shell rc files are never written;
- the checkout's own launcher is the entry point; the pin is verified with
  expected-vs-found failures (S7).

The helper probes are hermetic: a local git fixture stands in for the fork and
no network, home directory, or personal profile is touched.
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

PROVISION_SH = REPO_ROOT / "scripts" / "provision-hermes.sh"
PROVISION_PS1 = REPO_ROOT / "scripts" / "provision-hermes.ps1"

PIN = "d046ff9905b8470c4a0cfd5e9da566986056b438"
FORK_URL = "https://github.com/maar1223/hermes-agent-demiurgos.git"

_BASH = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX-bash probe: on Windows a bare `bash` is the WSL stub",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_probe(script: str, env: dict[str, str], *args: str):
    return subprocess.run(
        ["bash", "-c", script, "bash", str(PROVISION_SH), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


# ---------------------------------------------------------------------------
# Contract text (both platforms)
# ---------------------------------------------------------------------------


def test_provisioner_pins_the_public_fork_commit():
    text = _text(PROVISION_SH)
    assert f'HERMES_FORK_URL="${{DEMIURGOS_HERMES_FORK_URL:-{FORK_URL}}}"' in text
    assert f'HERMES_PIN="${{DEMIURGOS_HERMES_PIN:-{PIN}}}"' in text
    # No upstream-latest install at run time.
    assert "hermes-agent.nousresearch.com" not in text


def test_provisioner_uses_product_owned_paths():
    text = _text(PROVISION_SH)
    assert 'INSTALL_ROOT="${DEMIURGOS_HOME:-$HOME/.demiurgos}"' in text
    assert 'HERMES_HOME="${DEMIURGOS_HERMES_HOME:-$INSTALL_ROOT/hermes}"' in text
    assert 'AGENT_ROOT="${DEMIURGOS_HERMES_AGENT_ROOT:-$INSTALL_ROOT/hermes-agent}"' in text
    assert 'RUNTIME_DIR="$HERMES_HOME/tools"' in text


def test_provisioner_never_writes_the_personal_profile():
    text = _text(PROVISION_SH)
    assert "$HOME/.hermes/config.yaml" not in text
    assert "$HOME/.hermes/profiles" not in text
    # Prior installs are reported, never modified.
    assert "left untouched" in text


def test_provisioner_runs_setup_with_product_env_and_scratch_home():
    text = _text(PROVISION_SH)
    assert 'HERMES_HOME="$HERMES_HOME"' in text
    assert 'HERMES_RUNTIME_DIR="$RUNTIME_DIR"' in text
    assert 'HERMES_AGENT_ROOT="$AGENT_ROOT"' in text
    # The setup script is bash-only (dash fails on its substitutions).
    assert 'bash "$setup"' in text
    # Scratch HOME keeps setup's ~/.local/bin + shell rc writes off the user.
    assert 'HOME="$scratch"' in text
    assert 'UV_CACHE_DIR="$scratch/uv-cache"' in text


def test_provisioner_has_the_hermetic_skip_seam():
    assert "DEMIURGOS_HERMES_SKIP" in _text(PROVISION_SH)
    assert "DEMIURGOS_HERMES_SKIP" in _text(PROVISION_PS1)


def test_windows_provisioner_mirrors_the_contract():
    text = _text(PROVISION_PS1)
    assert PIN in text
    assert FORK_URL in text
    assert ".hermes\\bin\\hermes.exe" in text
    assert "$env:HERMES_HOME = $hermesHome" in text
    assert "$env:HERMES_AGENT_ROOT = $agentRoot" in text
    raw = PROVISION_PS1.read_bytes()
    raw.decode("ascii")  # PS 5.1 BOM-less UTF-8 contract


def test_release_artifact_carries_provisioners_and_license():
    workflow = _text(REPO_ROOT / ".github" / "workflows" / "release.yml")
    for rel in (
        "scripts/provision-hermes.sh",
        "scripts/provision-hermes.ps1",
        "third-party/hermes/LICENSE",
    ):
        assert rel in workflow, f"{rel} must be shipped and verified in the channel"
    assert (REPO_ROOT / "third-party" / "hermes" / "LICENSE").is_file()


# ---------------------------------------------------------------------------
# Helpers (behavioural, local git fixture)
# ---------------------------------------------------------------------------


def _git_fixture(tmp_path: Path) -> tuple[Path, str]:
    """A local fork stand-in with two commits; returns (repo, pinned_sha)."""
    repo = tmp_path / "fork"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for key, value in (("user.email", "t@example.test"), ("user.name", "test")):
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    (repo / "gateway" / "platforms").mkdir(parents=True)
    (repo / "gateway" / "platforms" / "api_server.py").write_text(
        "no_tools = True\n", encoding="utf-8"
    )
    (repo / "setup-hermes.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "pinned"], check=True)
    pinned = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "later"], check=True)
    return repo, pinned


def _probe_env(tmp_path: Path, repo: Path, pin: str) -> dict[str, str]:
    return {
        "HOME": str(tmp_path / "home"),
        "DEMIURGOS_HERMES_PIN": pin,
        "DEMIURGOS_HERMES_FORK_URL": str(repo),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }


@_BASH
def test_fetch_pinned_checkout_checks_out_the_exact_commit(tmp_path: Path):
    repo, pin = _git_fixture(tmp_path)
    dest = tmp_path / "agent"
    result = _run_probe(
        'source "$1"; resolve_paths ""; fetch_pinned_checkout "$2"; '
        'printf "HEAD=%s" "$(checkout_head "$2")"',
        _probe_env(tmp_path, repo, pin),
        str(dest),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"HEAD={pin}"
    assert (dest / "gateway" / "platforms" / "api_server.py").is_file()


@_BASH
def test_fetch_pinned_checkout_fails_when_the_patch_is_missing(tmp_path: Path):
    repo, _pin = _git_fixture(tmp_path)
    (repo / "gateway" / "platforms" / "api_server.py").write_text(
        "no patch here\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "no patch"], check=True)
    pin = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    result = _run_probe(
        'source "$1"; resolve_paths ""; fetch_pinned_checkout "$2"',
        _probe_env(tmp_path, repo, pin),
        str(tmp_path / "agent"),
    )
    assert result.returncode != 0
    assert "no_tools" in result.stderr


@_BASH
def test_check_runtime_reports_expected_vs_found(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    agent = tmp_path / "install" / "hermes-agent"
    agent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(agent)], check=True)
    for key, value in (("user.email", "t@example.test"), ("user.name", "test")):
        subprocess.run(["git", "-C", str(agent), "config", key, value], check=True)
    (agent / "x").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(agent), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(agent), "commit", "-qm", "other"], check=True)

    env = {
        "HOME": str(home),
        "DEMIURGOS_HOME": str(tmp_path / "install"),
        "DEMIURGOS_HERMES_PIN": PIN,
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    result = _run_probe(
        'source "$1"; resolve_paths ""; check_runtime',
        env,
    )
    assert result.returncode == 1
    assert PIN in result.stderr
    assert "expected pin" in result.stderr
    assert "found" in result.stderr


@_BASH
def test_is_provisioned_requires_pin_and_launcher(tmp_path: Path):
    repo, pin = _git_fixture(tmp_path)
    install_root = tmp_path / "install"
    agent = install_root / "hermes-agent"
    agent.mkdir(parents=True)
    for item in repo.iterdir():
        if item.name == ".git":
            continue
        target = agent / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    shutil.copytree(repo / ".git", agent / ".git")
    subprocess.run(["git", "-C", str(agent), "checkout", "-q", pin], check=True)

    env = {
        "HOME": str(tmp_path / "home"),
        "DEMIURGOS_HOME": str(install_root),
        "DEMIURGOS_HERMES_PIN": pin,
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    probe = 'source "$1"; resolve_paths ""; is_provisioned && echo YES || echo NO'
    result = _run_probe(probe, env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "NO"

    launcher = agent / ".hermes" / "bin" / "hermes"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    result = _run_probe(probe, env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "YES"
