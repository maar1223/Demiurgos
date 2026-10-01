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

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

PORTABLE_LAUNCHER = REPO_ROOT / "scripts" / "start-demiurgos.sh"

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


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_sourcing_probe_derives_layout_and_has_no_side_effects():
    """Hermetic: source the real script with an unknown action.

    Sourcing sets the derived top-level paths, then ``main`` prints usage and
    returns without spawning anything, creating any runtime dir, or writing
    the data-root pointer.
    """
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
    assert result.stdout == f"{REPO_ROOT}|{REPO_ROOT}/.venv/bin/python|NO_SIDE_EFFECT"