# -*- coding: utf-8 -*-
"""Launcher diagnostics log: a Terminal=false boot must stay explainable."""
from __future__ import annotations

import socket
import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]
LAUNCHER = REPO_ROOT / "scripts" / "start-demiurgos.sh"
#: Source WITHOUT running main(): $0 must differ from BASH_SOURCE[0].
_PREFIX = 'set -euo pipefail; source "$1"; shift; '


def _run(body: str, log: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    script = _PREFIX + f'LAUNCHER_LOG="{log}"; ' + body
    return subprocess.run(
        ["bash", "-c", script, "_", str(LAUNCHER)],
        capture_output=True,
        text=True,
        timeout=30,
        env={"HOME": str(tmp_path), "TMPDIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )


def test_launcher_syntax_is_clean() -> None:
    done = subprocess.run(["bash", "-n", str(LAUNCHER)], capture_output=True)
    assert done.returncode == 0


def test_log_event_never_aborts_a_boot(tmp_path) -> None:
    log = tmp_path / "absent" / "launcher.log"
    done = _run('log_event "probe"; echo "rc=$?"', log, tmp_path)
    assert done.returncode == 0
    assert "rc=0" in done.stdout


def test_no_log_event_argument_carries_a_secret() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    calls = [line for line in text.splitlines() if "log_event" in line]
    forbidden = ("KEY", "TOKEN", "SECRET", "PASSWORD")
    assert not [line for line in calls if any(word in line for word in forbidden)]


def test_port_conflict_is_written_to_the_launcher_log(tmp_path) -> None:
    """A boot aborted by a squatted port must leave the reason in the log."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        log = tmp_path / "logs" / "launcher.log"
        log.parent.mkdir()
        done = _run(f"API_PORT={port}; start_component api || true", log, tmp_path)
    assert done.returncode == 0
    assert "port" in log.read_text(encoding="utf-8").lower()
