# -*- coding: utf-8 -*-
"""WU-2 — contract tests for the shared live-probe helper (REQ-LPH-1..7, R8).

``hermes_probe_support`` owns the single boot/read/teardown authority shared by
``test_native_channel_probe.py`` and ``test_native_channel_suppression.py``
(REQ-LPH-5, design N3). These tests drive a *fake* ``hermes`` script through a
temporary ``PATH``-independent interpreter shebang; they never invoke the real
binary and never read the process environment — every input is injected through
the helper's ``home``/``environ`` parameters.

The mandatory ``REPO_ROOT`` guard (R8) is the first test: a wrong ``parents[N]``
would point ``DEMIURGOS_ROOT``/``cwd`` at ``<repo>/src`` and Fix 2 would silently
fail to discover the project plugin.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import hermes_probe_support


# -- fake ``hermes`` binary ---------------------------------------------------

# A tiny stand-in for the real gateway. It writes JSON-free evidence lines to
# ``<HERMES_HOME>/logs/agent.log`` exactly where the helper reads them. Modes:
#   emit (default) — both hook markers + the boot env/CWD contract dump
#   silent         — no hook markers (proves "no evidence ⇒ not booted")
#   ignore-term    — ignores SIGTERM and sleeps (proves bounded kill)
_FAKE_HERMES_SOURCE = '''\
import os
import signal
import sys
import time
from pathlib import Path

mode = "__MODE__"
home = Path(os.environ["HERMES_HOME"])
logs = home / "logs"
logs.mkdir(parents=True, exist_ok=True)
log = logs / "agent.log"


def emit(lines):
    with log.open("a", encoding="utf-8") as fh:
        fh.write("\\n".join(lines) + "\\n")


if mode == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    emit(["pre_tool_call registered", "pre_llm_call registered"])
    time.sleep(600)
    sys.exit(0)

if mode == "silent":
    emit(["gateway starting", "no hook registration here"])
    sys.exit(0)

emit([
    "gateway boot",
    "pre_tool_call registered",
    "pre_llm_call registered",
    "ENV HERMES_ENABLE_PROJECT_PLUGINS=" + os.environ.get("HERMES_ENABLE_PROJECT_PLUGINS", ""),
    "ENV DEMIURGOS_ROOT=" + os.environ.get("DEMIURGOS_ROOT", ""),
    "ENV HERMES_HOME=" + os.environ.get("HERMES_HOME", ""),
    "ENV DEMIURGOS_HERMES_HOME=" + os.environ.get("DEMIURGOS_HERMES_HOME", ""),
    "CWD " + os.getcwd(),
])
sys.exit(0)
'''


def _write_fake_hermes(base: Path, mode: str = "emit") -> Path:
    """Write an executable fake ``hermes`` with an absolute interpreter shebang.

    The shebang is ``sys.executable`` so the child needs no ``PATH`` — the boot
    env contract test injects an empty ``environ`` on purpose.
    """
    script = base / f"fake-hermes-{mode}"
    script.write_text(
        f"#!{sys.executable}\n" + _FAKE_HERMES_SOURCE.replace("__MODE__", mode),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _env_dump(log_text: str) -> dict[str, str]:
    return {
        line.split(" ", 1)[1].split("=", 1)[0]: line.split("=", 1)[1]
        for line in log_text.splitlines()
        if line.startswith("ENV ")
    }


def _cwd_dump(log_text: str) -> str:
    for line in log_text.splitlines():
        if line.startswith("CWD "):
            return line.split(" ", 1)[1]
    raise AssertionError(f"no CWD line in {log_text!r}")


# -- R8: REPO_ROOT derivation guard ------------------------------------------


def test_repo_root_resolves_to_the_repo_root() -> None:
    """R8 guard: the helper's ``REPO_ROOT`` must be the real repo root.

    A wrong ``parents[N]`` would make ``DEMIURGOS_ROOT``/``cwd`` point at
    ``<repo>/src``, hiding ``.hermes/plugins/demiurgos-idea-capture`` from the
    gateway and making Fix 2 silently fail. Cross-checked against the git
    top-level when available.
    """
    here = Path(__file__).resolve()
    found: Path | None = None
    for parent in here.parents:
        if (
            parent / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
        ).is_file():
            found = parent
            break
    assert found is not None, "could not locate the repo root by plugin walk"
    assert hermes_probe_support.REPO_ROOT == found
    assert (
        hermes_probe_support.REPO_ROOT
        / ".hermes"
        / "plugins"
        / "demiurgos-idea-capture"
        / "__init__.py"
    ).is_file()

    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        top = ""
    if top:
        assert Path(top).resolve() == hermes_probe_support.REPO_ROOT


# -- REQ-LPH-2: boot env and CWD ---------------------------------------------


def test_boot_env_and_cwd_carry_the_plugin_load_contract(tmp_path: Path) -> None:
    """The child env carries the plugin-load contract and boots in the repo root.

    Mirrors ``scripts/start-demiurgos.sh:480-484``: ``HERMES_ENABLE_PROJECT_PLUGINS=1``,
    ``DEMIURGOS_ROOT=<repo>``, both ``HERMES_HOME``/``DEMIURGOS_HERMES_HOME`` equal
    the dedicated root, and ``cwd=<repo>``.
    """
    home = tmp_path / "home"
    (home / "logs").mkdir(parents=True)
    fake = _write_fake_hermes(tmp_path)

    result = hermes_probe_support.boot_and_probe_gateway(
        str(fake),
        home,
        repo=hermes_probe_support.REPO_ROOT,
        timeout=10.0,
        environ={},
    )

    log_text = result.log_path.read_text(encoding="utf-8")
    env = _env_dump(log_text)
    assert env["HERMES_ENABLE_PROJECT_PLUGINS"] == "1"
    assert env["DEMIURGOS_ROOT"] == str(hermes_probe_support.REPO_ROOT)
    assert env["HERMES_HOME"] == str(home)
    assert env["DEMIURGOS_HERMES_HOME"] == str(home)
    assert _cwd_dump(log_text) == str(hermes_probe_support.REPO_ROOT)


# -- REQ-LPH-3: evidence from the log, from a boot offset --------------------


def test_boot_offset_excludes_pre_existing_log_text(tmp_path: Path) -> None:
    """Only content written at/after boot counts as evidence (boot byte-offset)."""
    home = tmp_path / "home"
    logs = home / "logs"
    logs.mkdir(parents=True)
    (logs / "agent.log").write_text(
        "pre_tool_call OLD-STALE-EVIDENCE\n", encoding="utf-8"
    )
    before = (logs / "agent.log").stat().st_size
    fake = _write_fake_hermes(tmp_path)

    result = hermes_probe_support.boot_and_probe_gateway(
        str(fake), home, repo=hermes_probe_support.REPO_ROOT, timeout=10.0, environ={}
    )

    assert result.booted is True
    assert all("OLD-STALE-EVIDENCE" not in line for line in result.hook_evidence)
    # The stale bytes are still on disk: they were excluded, not truncated.
    assert (logs / "agent.log").stat().st_size > before


def test_missing_evidence_fails_not_passes(tmp_path: Path) -> None:
    """A gateway that emits no hook lines is never a pass (REQ-LPH-3)."""
    home = tmp_path / "home"
    (home / "logs").mkdir(parents=True)
    fake = _write_fake_hermes(tmp_path, mode="silent")

    result = hermes_probe_support.boot_and_probe_gateway(
        str(fake), home, repo=hermes_probe_support.REPO_ROOT, timeout=10.0, environ={}
    )

    assert result.booted is False
    assert result.hook_evidence == []
    # Not a pass even though the process exited cleanly.
    assert result.returncode == 0


# -- REQ-LPH-4: bounded teardown ---------------------------------------------


def test_teardown_kills_a_child_that_ignores_sigterm(tmp_path: Path) -> None:
    """Teardown is bounded and force-kills a child that ignores SIGTERM."""
    home = tmp_path / "home"
    (home / "logs").mkdir(parents=True)
    fake = _write_fake_hermes(tmp_path, mode="ignore-term")

    proc = subprocess.Popen(
        [str(fake), "gateway", "run"],
        env={**os.environ, "HERMES_HOME": str(home)},
        cwd=str(hermes_probe_support.REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if (home / "logs" / "agent.log").is_file():
                break
            time.sleep(0.05)
        started = time.monotonic()
        hermes_probe_support._terminate(proc, term_timeout=1.0)
        elapsed = time.monotonic() - started
        assert elapsed < 5.0, "teardown exceeded the bounded deadline"
        assert proc.poll() is not None, "child survived teardown"
        assert proc.returncode == -signal.SIGKILL, "child was not force-killed"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


# -- REQ-LPH-6: log-path drift -----------------------------------------------


def test_gateway_log_path_drift_raises(tmp_path: Path) -> None:
    """A missing ``<home>/logs`` directory is honest drift, not a false pass."""
    home = tmp_path / "home"
    home.mkdir()  # no logs/ subdir
    with pytest.raises(hermes_probe_support.ProbeLogDriftError):
        hermes_probe_support.gateway_log_path(home)


# -- REQ-LPH-7: P0-8 isolation -----------------------------------------------


def test_personal_profile_is_a_hard_failure(tmp_path: Path) -> None:
    """The personal ``~/.hermes`` is refused; a dedicated root passes."""
    with pytest.raises(hermes_probe_support.ProbeIsolationError):
        hermes_probe_support.assert_not_personal_profile(
            hermes_probe_support.personal_hermes_home()
        )
    # A dedicated root does not raise.
    hermes_probe_support.assert_not_personal_profile(tmp_path / "dedicated")


# -- REQ-LPH-1: opt-in gate --------------------------------------------------


def test_live_probe_disabled_by_default() -> None:
    """The live probe is off unless ``DEMIURGOS_PROBE_LIVE`` is exactly ``"1"``."""
    assert hermes_probe_support.live_probe_enabled({}) is False
    assert hermes_probe_support.live_probe_enabled({"DEMIURGOS_PROBE_LIVE": ""}) is False
    assert (
        hermes_probe_support.live_probe_enabled({"DEMIURGOS_PROBE_LIVE": "0"}) is False
    )
    assert (
        hermes_probe_support.live_probe_enabled({"DEMIURGOS_PROBE_LIVE": "true"})
        is False
    )
    assert (
        hermes_probe_support.live_probe_enabled({"DEMIURGOS_PROBE_LIVE": "1"}) is True
    )
