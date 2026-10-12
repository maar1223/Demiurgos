# -*- coding: utf-8 -*-
"""S2a — portable POSIX launcher contract (design S2-1/S2-4/S2-5/S2-9).

The portable launcher (``scripts/start-demiurgos.sh``) must run on Linux AND
macOS bash 3.2 with zero system Python and no hardcoded absolute paths. These
are text scans of the launcher artifact (matching ``test_port_ownership`` and
the idea-capture ingress test — the launcher is a CODE artifact of the
checkout, located from this file, NOT from a configured data root) plus ONE
hermetic sourcing probe that proves the script derives its layout paths and
exits without spawning anything or writing runtime state.

Assertions map 1:1 to task 2.1: no unconditional ``ss``/``/proc``/``xdg-open``;
a ``uname -s`` branch exists; macOS equivalents present (``lsof -iTCP``,
``ps -ww -o command=``, ``open``); no system Python call sites; ``ps -ww`` for
ownership; bash 3.2 lint (no ``declare -A``/``mapfile``/``readarray``/
``${var^^}``/``&>>``); no hardcoded temp paths; no forced data-root export;
the ``_kill_descendants`` self-kill guard preserved verbatim.
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
COMPAT_ALIAS = REPO_ROOT / "scripts" / "start-demiurgos-linux.sh"
PS_STACK = REPO_ROOT / "start-demiurgos.ps1"
PS_API = REPO_ROOT / "start-api.ps1"
PS_GATEWAY = REPO_ROOT / "start-gateway.ps1"
API_SERVER = _WIKI / "api_server.py"
SYSTEM_CONTROL = _WIKI / "system_control.py"

#: Every tracked PowerShell launcher (S2-8: PS 5.1 + ASCII/BOM).
PS_LAUNCHERS = (PS_STACK, PS_API, PS_GATEWAY)

_KILL_DESCENDANTS = """_kill_descendants() {
    local parent="$1" child
    for child in $(pgrep -P "$parent" 2>/dev/null || true); do
        [ "$child" = "$$" ] && continue
        _kill_descendants "$child"
    done
    kill -TERM "$parent" 2>/dev/null || true
}"""

_BASH_32_BANS = ("declare -A", "mapfile", "readarray", "^^}", "&>>")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _top_level_lines(text: str, needle: str) -> list[str]:
    """Lines containing ``needle`` at column 0 (outside any branch/function).

    A construct is "unconditional" exactly when it appears on such a line;
    indented occurrences and comments are inside the OS branch or a function.
    """
    return [
        line
        for line in text.splitlines()
        if needle in line and not line.startswith((" ", "\t", "#"))
    ]


class TestOSPortability:
    def test_has_uname_branch(self):
        text = _text(PORTABLE_LAUNCHER)
        assert 'OS="$(uname -s)"' in text
        assert 'case "$OS" in' in text

    def test_linux_tools_are_not_unconditional(self):
        text = _text(PORTABLE_LAUNCHER)
        for needle in ("ss ", "xdg-open", "/proc/"):
            assert _top_level_lines(text, needle) == [], needle

    def test_macos_equivalents_present(self):
        text = _text(PORTABLE_LAUNCHER)
        assert "lsof -iTCP:" in text
        assert "ps -ww -o command=" in text
        assert 'opener="open"' in text


class TestNoSystemPython:
    def test_no_system_python_call_sites(self):
        text = _text(PORTABLE_LAUNCHER)
        assert "python3" not in text

    def test_interpreter_comes_from_the_layout_venv(self):
        text = _text(PORTABLE_LAUNCHER)
        assert 'PYTHON_BIN="$APP_ROOT/.venv/bin/python"' in text


class TestProcessInspection:
    def test_ownership_uses_ps_ww(self):
        text = _text(PORTABLE_LAUNCHER)
        assert "ps -ww -o command=" in text

    def test_proc_cmdline_is_a_linux_fast_path_only(self):
        text = _text(PORTABLE_LAUNCHER)
        assert "/proc/$pid/cmdline" in text
        assert '[ "$OS" = "Linux" ]' in text

    def test_dev_tcp_listening_probe_present(self):
        text = _text(PORTABLE_LAUNCHER)
        assert "/dev/tcp" in text


class TestBash32Lint:
    def test_no_bash4_only_idioms(self):
        text = _text(PORTABLE_LAUNCHER)
        for banned in _BASH_32_BANS:
            assert banned not in text, banned


class TestLayoutContract:
    def test_no_hardcoded_tmp_paths(self):
        text = _text(PORTABLE_LAUNCHER)
        assert "/tmp" not in text

    def test_no_forced_data_root_export(self):
        text = _text(PORTABLE_LAUNCHER)
        assert 'export DEMIURGOS_DATA_ROOT="$PROJECT_ROOT"' not in text
        assert '"$PROJECT_ROOT/.venv"' not in text

    def test_self_kill_guard_preserved_verbatim(self):
        text = _text(PORTABLE_LAUNCHER)
        assert _KILL_DESCENDANTS in text


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX-bash sourcing probe: on Windows a bare `bash` is the WSL stub",
)
def test_sourcing_probe_derives_layout_and_has_no_side_effects():
    """Hermetic: source the real script with an unknown action.

    Sourcing sets the derived top-level paths, then ``main`` prints usage and
    returns without spawning anything, creating any runtime dir, or writing
    the data-root pointer.

    The no-side-effect check compares the ``<app_root>/logs`` state before and
    after sourcing. A pre-existing dev ``<repo>/logs/`` (left behind by a real
    launcher run, S2-6) is NOT a side effect of sourcing, so its mere presence
    must not fail the probe — what must never happen is sourcing CREATING it.
    """
    logs_dir = REPO_ROOT / "logs"
    existed_before = logs_dir.exists()
    probe = (
        'source "$1" __probe__ || true; '
        'printf %s "${APP_ROOT:-UNSET}|${PYTHON_BIN:-UNSET}"; '
        '[ -e "$APP_ROOT/logs" ] && printf "|SIDE_EFFECT" || printf "|NO_SIDE_EFFECT"'
    )
    result = subprocess.run(
        ["bash", "-c", probe, "bash", str(PORTABLE_LAUNCHER)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"{REPO_ROOT}|{REPO_ROOT}/.venv/bin/python")
    # Sourcing must not change the logs-dir existence (never create it, never
    # delete it); comparing to the pre-existing state keeps the probe hermetic.
    exists_after = result.stdout.endswith("|SIDE_EFFECT")
    assert exists_after == existed_before, (
        "sourcing the launcher changed <app_root>/logs existence "
        f"(before={existed_before}, after={exists_after})"
    )


# ---------------------------------------------------------------------------
# S2b — Hermes optional + OS-aware dispatch (tasks 3.4/3.5/3.7)
# ---------------------------------------------------------------------------


class TestHermesOptional:
    def test_hermes_fail_hard_gate_is_removed(self):
        """S2-2: the launcher must NOT return 1 when Hermes is absent."""
        text = _text(PORTABLE_LAUNCHER)
        start_block = text[text.index("start_all()"):text.index("open_browser()")]
        # The old gate (`:345-348` in the pre-S2a script) printed a bare
        # "Hermes CLI not found" and returned 1, aborting the whole boot.
        # The new contract prints an advisory and continues.
        assert "assistant will be unavailable" in start_block
        hermes_gate = start_block[start_block.index("Hermes CLI"):]
        assert "return 1" not in hermes_gate[:150]

    def test_gateway_started_only_when_hermes_found(self):
        text = _text(PORTABLE_LAUNCHER)
        start_block = text[text.index("start_all()"):text.index("open_browser()")]
        # The gateway component start is conditional on Hermes presence...
        assert 'if [ -z "$HERMES_BIN" ] || [ ! -x "$HERMES_BIN" ]; then' in start_block
        # ...and the API start is unconditional (outside the branch).
        assert 'start_component api' in start_block

    def test_gateway_port_not_in_required_readiness(self):
        """S2-2: GATEWAY_PORT is dropped from the REQUIRED readiness gate."""
        text = _text(PORTABLE_LAUNCHER)
        start_block = text[text.index("start_all()"):text.index("open_browser()")]
        # The API is the only REQUIRED readiness (S6-2/D6: a real HTTP 200 on
        # /health); the gateway is best-effort and never aborts the boot.
        assert 'if wait_for_health "$API_PORT"' in start_block
        assert 'wait_for_port "$GATEWAY_PORT"' in start_block
        # The gateway wait must not be able to fail the boot: no `return 1`
        # on the gateway path (it appears only in the API-required branch).
        gateway_wait = start_block[start_block.index('wait_for_port "$GATEWAY_PORT"'):]
        assert "return 1" not in gateway_wait[:200]


class TestCompatAliasRemoved:
    def test_linux_compat_alias_is_gone(self):
        """S2b removes the S2a compat alias; no call site remains."""
        assert not COMPAT_ALIAS.exists()

    def test_dispatch_has_no_stale_alias_reference(self):
        text = _text(API_SERVER)
        assert "start-demiurgos-linux.sh" not in text


class TestNoBrowserSuppression:
    def test_open_browser_honors_demiurgos_no_browser(self):
        """Incident fix (s2b-harness-gotcha): a truthy DEMIURGOS_NO_BROWSER
        (1|true|yes) skips the browser launch, so harnesses, system_control
        and CI can boot headless without ever opening a real browser."""
        text = _text(PORTABLE_LAUNCHER)
        open_browser = text[text.index("open_browser()"):text.index("show_status()")]
        assert "DEMIURGOS_NO_BROWSER" in open_browser
        assert "1|true|yes" in open_browser
        # The suppressed path must return early (no opener is even resolved).
        assert "return 0" in open_browser
        # The guard is documented at the top of the script for humans.
        assert "DEMIURGOS_NO_BROWSER" in text[:text.index("open_browser()")]

    def test_start_action_still_calls_open_browser(self):
        """The suppression switch is INSIDE open_browser: `start` keeps its
        behavior in interactive use, and every caller (start, future flags)
        inherits the headless guard."""
        text = _text(PORTABLE_LAUNCHER)
        main_block = text[text.index("main()"):]
        assert 'start) start_all; open_browser "http://127.0.0.1:$API_PORT"' in main_block


class TestPowerShell51Contract:
    def test_ps1_files_are_ascii_only(self):
        """S2-8: PS 5.1 mis-decodes BOM-less UTF-8; ASCII-only is the rule."""
        for path in PS_LAUNCHERS:
            raw = path.read_bytes()
            raw.decode("ascii")  # raises UnicodeDecodeError on non-ASCII

    def test_ps1_files_have_no_hardcoded_author_paths(self):
        for path in PS_LAUNCHERS:
            text = _text(path)
            assert "H:\\" not in text
            assert "C:\\Users" not in text

    def test_ps1_launchers_use_psscriptroot(self):
        for path in PS_LAUNCHERS:
            text = _text(path)
            assert "$PSScriptRoot" in text

    def test_ps1_launchers_resolve_hermes_portably(self):
        for path in (PS_STACK, PS_GATEWAY):
            text = _text(path)
            assert "Get-Command hermes" in text
            assert ".local\\bin\\hermes.exe" in text

    def test_ps_stack_starts_only_uvicorn(self):
        text = _text(PS_STACK)
        assert "uvicorn api_server:app" in text
        # The old stack started gateway + warmup + frontend; S2b collapses it
        # to the API only. No Vite/npm and no warmup entry points remain.
        assert "npm" not in text
        assert "warmup" not in text

    def test_ps_stack_keeps_tcp_ownership_validation(self):
        text = _text(PS_STACK)
        assert "Get-NetTCPConnection" in text
        # Command-line ownership: the listener pid must identify as the API
        # before it is adopted/killed (mirrors the POSIX ps -ww gate).
        assert "CommandLine" in text
        assert "uvicorn api_server:app" in text

    def test_ps_stack_readiness_covers_api_only(self):
        text = _text(PS_STACK)
        assert "/health" in text
        assert "npm" not in text
        # The exported contract env mirrors the POSIX launcher (S1-6/S2-3).
        assert "DEMIURGOS_FRONTEND_DIST" in text
        assert "DEMIURGOS_ROOT" in text
        # Runtime version identity (S1): exported from the install layout only.
        assert "DEMIURGOS_APP_VERSION" in text
        assert "Split-Path -Leaf" in text

    def test_version_export_present_in_both_launchers(self):
        """S1: both launchers export DEMIURGOS_APP_VERSION from the layout.

        POSIX: basename of the resolved `current` link inside the layout
        guard, so a dev checkout never exports an empty value. Windows: the
        junction `.Target` leaf with `@($target)[0]` array normalization.
        """
        sh_text = _text(PORTABLE_LAUNCHER)
        # The guard ties the export to the installed layout.
        assert 'basename "$(readlink "$INSTALL_ROOT/current")"' in sh_text
        assert 'readlink "$INSTALL_ROOT/current"' in sh_text
        # Never an unconditional empty export.
        assert 'export DEMIURGOS_APP_VERSION=""' not in sh_text

        ps_text = _text(PS_STACK)
        assert "$env:DEMIURGOS_APP_VERSION" in ps_text
        assert "(Split-Path -Leaf $appRoot) -eq \"current\"" in ps_text
        assert "Split-Path -Leaf @($target)[0]" in ps_text

    def test_ps_launchers_handle_data_root_pointer(self):
        for path in PS_LAUNCHERS:
            text = _text(path)
            assert "data-root.json" in text
            assert "DEMIURGOS_DATA_ROOT" in text


class TestSystemControlDispatch:
    def test_dispatch_resolves_per_os_launcher(self):
        text = _text(API_SERVER)
        # POSIX launcher from the S0-C contract...
        assert 'scripts" / "start-demiurgos.sh"' in text
        # ...and a Windows launcher (start-demiurgos.ps1) for nt.
        assert "start-demiurgos.ps1" in text

    def test_dispatch_validates_launcher_existence_at_boot(self):
        text = _text(API_SERVER)
        assert "is_file()" in text

    def test_missing_launcher_yields_clear_error_not_stale_dispatch(self):
        text = _text(SYSTEM_CONTROL)
        assert "launcher not available" in text