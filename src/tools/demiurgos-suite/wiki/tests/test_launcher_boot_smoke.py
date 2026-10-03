# -*- coding: utf-8 -*-
"""S2b — provider-optional boot harnesses and launcher behaviour matrix.

Task 3.8: the harness code for the four runtime checks:

1. POSIX Hermes-absent boot — scrubs ``hermes`` from ``PATH`` and a fake
   ``HOME`` (so the ``~/.local/bin`` fallback also misses), starts the REAL
   launcher against the REAL layout venv, and asserts ``/health`` and ``/``
   respond. RUNS on this Linux host.
2. Windows runner — ``powershell.exe -NoProfile -File start-demiurgos.ps1``
   with Hermes absent. Needs a Windows host with PowerShell 5.1: marked
   ``skipif`` here (NOT run on this Linux host — this is the S2b/CI matrix
   proof).
3. M1 — Defender enabled (default on ``windows-latest``) + a username
   containing a space (path like ``C:\\Users\\Miguel Angel\\...``). Same
   Windows-only guard.
4. Launcher behaviour matrix (ubuntu / macos / windows) with a stub uvicorn:
   start twice -> exactly one process; stop-when-down -> exit 0; restart ->
   exactly one. The ubuntu cell runs here against a stub ``python``; the
   darwin/win32 cells are written and skipped on this host (CI matrix).

Every Windows/macOS cell documents itself as ``not-run`` here on purpose;
nothing is fabricated as passing.

Headless guard (incident s2b-harness-gotcha): every harness that runs the
launcher's ``start`` MUST (a) set ``DEMIURGOS_NO_BROWSER=1`` in the child env
and (b) prepend ``/tmp/opencode/noop-browser/bin`` (no-op xdg-open/open/gio
stubs that only log to ``calls.log``) to the child PATH. A missing stub fails
loudly — a real browser must NEVER open from a harness.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

PORTABLE_LAUNCHER = REPO_ROOT / "scripts" / "start-demiurgos.sh"
PS_STACK = REPO_ROOT / "start-demiurgos.ps1"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

#: No-op browser stub dir (incident fix): prepended to the child PATH so a
#: launcher that ignores the env flag still cannot open a real browser. The
#: stubs log every invocation to /tmp/opencode/noop-browser/calls.log.
NOOP_BROWSER_BIN = Path("/tmp/opencode/noop-browser/bin")

_SMOKE_POLLS = 60
_SMOKE_POLL_INTERVAL = 1.0


def _require_noop_stub() -> None:
    """Hard harness guard: fail (never skip) when the no-op browser stubs are
    absent — launching the launcher without both headless guards is what opened
    three real Brave windows on the maintainer's desktop."""
    if not (NOOP_BROWSER_BIN / "xdg-open").is_file():
        raise RuntimeError(
            "harness guard missing: /tmp/opencode/noop-browser/bin stubs are "
            "required before launching the launcher (s2b-harness-gotcha)"
        )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _stop_and_assert_clean(launcher: Path, env: dict[str, str], api_port: int) -> None:
    """Teardown contract (incident): stop the launcher, then assert NO leftover
    listener on the test port. A leaked process fails loudly instead of being
    silently reparented to init."""
    stop = subprocess.run(
        ["bash", str(launcher), "stop"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert stop.returncode == 0, stop.stderr
    for _ in range(20):
        if not _port_listening(api_port):
            break
        time.sleep(0.25)
    assert not _port_listening(api_port), (
        f"port {api_port} still listening after stop: leaked launcher process"
    )


def _hermes_free_env(tmp_path: Path, api_port: int, gateway_port: int) -> dict[str, str]:
    """Env for a hermetic boot: hermes scrubbed from PATH and HOME.

    ``HERMES_BIN`` resolves via ``command -v hermes`` and a
    ``$HOME/.local/bin/hermes`` fallback; pointing HOME at a fresh temp dir
    kills BOTH paths, so the launcher provably boots with the provider absent.

    ``XDG_RUNTIME_DIR`` is pointed at the temp tree so the launcher's pid
    files (runtime state, S0-C) never collide with the live dev stack's
    ``/tmp/demiurgos-launcher`` state on this machine.

    Headless guard: ``DEMIURGOS_NO_BROWSER=1`` plus the no-op browser stub dir
    on PATH — the launcher's ``start`` never opens a real browser here.
    """
    _require_noop_stub()
    scrubbed_path = ":".join(
        part for part in os.environ.get("PATH", "").split(":")
        if part
        and "hermes" not in part.lower()
        and ".local" not in part.lower()
        and not part.startswith("/home/")
    ) or "/usr/bin:/bin"
    env = {
        **os.environ,
        "PATH": f"{NOOP_BROWSER_BIN}:{scrubbed_path}",
        "HOME": str(tmp_path / "home"),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        "DEMIURGOS_HOME": str(tmp_path / "install"),
        "DEMIURGOS_DATA_ROOT": str(tmp_path / "data"),
        "DEMIURGOS_API_PORT": str(api_port),
        "DEMIURGOS_GATEWAY_PORT": str(gateway_port),
        "DEMIURGOS_NO_BROWSER": "1",
    }
    env.pop("HERMES_BIN", None)
    return env


def _http_status(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status
    except Exception:
        return None


@pytest.mark.skipif(
    shutil.which("bash") is None or not VENV_PYTHON.is_file(),
    reason="needs bash and the layout venv",
)
class TestPosixHermesAbsentBoot:
    """Cell 1 — POSIX boot with Hermes absent (spec cross-platform-launcher
    "Start with Hermes absent", degradable-ai-provider "Boot with provider
    absent"). RUNS on this Linux host."""

    def test_boot_serves_health_and_root_without_hermes(self, tmp_path: Path) -> None:
        api_port = _free_port()
        env = _hermes_free_env(tmp_path, api_port, _free_port())

        start = subprocess.run(
            ["bash", str(PORTABLE_LAUNCHER), "start"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert start.returncode == 0, start.stderr
        # The boot must NOT have found hermes anywhere (scrubbed PATH + HOME).
        assert "Hermes CLI not found; the assistant will be unavailable." in start.stderr

        try:
            health = None
            root = None
            for _ in range(_SMOKE_POLLS):
                health = _http_status(f"http://127.0.0.1:{api_port}/health")
                if health == 200:
                    break
                time.sleep(_SMOKE_POLL_INTERVAL)
            assert health == 200, "API /health never became ready"

            # The SPA is served same-origin (S1): / returns the built app.
            root = _http_status(f"http://127.0.0.1:{api_port}/")
            assert root == 200, "API / never became ready"
        finally:
            _stop_and_assert_clean(PORTABLE_LAUNCHER, env, api_port)


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows runner harness needs powershell.exe (NOT run on this Linux host)",
)
class TestWindowsPsLauncherHermesAbsent:
    """Cell 2 — Windows runner: powershell.exe -NoProfile -File
    start-demiurgos.ps1 with Hermes absent -> app serves.

    NOT run here: this host has no powershell.exe. The S2b/CI matrix
    (windows-latest) is the runtime proof; this code is the harness.
    """

    def test_powershell_stack_serves_without_hermes(self, tmp_path: Path) -> None:
        api_port = _free_port()
        env = {
            **os.environ,
            "DEMIURGOS_HOME": str(tmp_path / "install"),
            "DEMIURGOS_DATA_ROOT": str(tmp_path / "data"),
            "DEMIURGOS_API_PORT": str(api_port),
            "DEMIURGOS_NO_BROWSER": "1",
        }
        env.pop("HERMES_BIN", None)
        # Scrub hermes from the Windows PATH.
        env["PATH"] = ";".join(
            part for part in env.get("PATH", "").split(";")
            if "hermes" not in part.lower()
        )

        start = subprocess.run(
            ["powershell.exe", "-NoProfile", "-File", str(PS_STACK), "start"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert start.returncode == 0, start.stderr
        try:
            status = None
            for _ in range(_SMOKE_POLLS):
                status = _http_status(f"http://127.0.0.1:{api_port}/health")
                if status == 200:
                    break
                time.sleep(_SMOKE_POLL_INTERVAL)
            assert status == 200, "API /health never became ready"
            assert _http_status(f"http://127.0.0.1:{api_port}/") == 200
        finally:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-File", str(PS_STACK), "stop"],
                env=env, capture_output=True, text=True, timeout=60,
            )

    def test_m1_defender_and_username_with_space(self, tmp_path: Path) -> None:
        """M1 (errata): Defender enabled (default on windows-latest) + a
        username containing a space -> the install path contains a space
        (e.g. ``C:\\Users\\Miguel Angel\\AppData\\Local\\Demiurgos``).

        NOT run here (Windows-only). The launcher must derive APP_ROOT from
        $PSScriptRoot and never choke on the space in the path.
        """
        spaced_root = tmp_path / "Miguel Angel" / "AppData" / "Local" / "Demiurgos"
        spaced_root.mkdir(parents=True)
        env = {
            **os.environ,
            "DEMIURGOS_HOME": str(spaced_root),
            "DEMIURGOS_DATA_ROOT": str(tmp_path / "data root with spaces"),
            "DEMIURGOS_API_PORT": str(_free_port()),
        }
        probe = subprocess.run(
            ["powershell.exe", "-NoProfile", "-File", str(PS_STACK), "stop"],
            env=env, capture_output=True, text=True, timeout=60,
        )
        # `stop` when down must exit cleanly; reaching it proves the script
        # parsed and derived paths under a username-with-space install root.
        assert probe.returncode == 0, probe.stderr


class TestLauncherBehaviourMatrix:
    """Cell 4 — launcher behaviour matrix with a stub uvicorn.

    A stub ``python`` (bash, holds the port via the real system python3 HTTP
    server) stands in for the layout venv; cmdline carries
    ``uvicorn api_server:app`` so the ownership gate matches. Assertions:
    start twice -> exactly one process; stop when down -> exit 0; restart ->
    exactly one process. The ubuntu cell RUNS here; darwin/win32 cells are
    written and skipped (CI matrix is their runtime proof).
    """

    _STUB = """#!/usr/bin/env bash
# Stub uvicorn: keep THIS process's cmdline (stub path + uvicorn module) so
# the launcher ownership gate matches, while a child python3 http server
# holds the requested port and answers 200 on ANY path (the launcher
# readiness gate is now a real HTTP 200 on /health — S6-2/D6; the plain
# http.server module would 404 unknown paths). The launcher's
# _kill_descendants reaps the child.
PORT=""
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        *) shift ;;
    esac
done
python3 -c 'import http.server, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()' "${PORT:-8000}" &
wait
"""

    def _stub_env(self, tmp_path: Path, api_port: int) -> tuple[Path, dict[str, str]]:
        app_root = tmp_path / "current"
        stub_bin = app_root / ".venv" / "bin"
        stub_bin.mkdir(parents=True)
        (stub_bin / "python").write_text(self._STUB, encoding="utf-8")
        (stub_bin / "python").chmod(0o755)
        scripts_dir = app_root / "scripts"
        scripts_dir.mkdir(parents=True)
        shutil.copy2(PORTABLE_LAUNCHER, scripts_dir / "start-demiurgos.sh")
        # The launcher cds into the API dir before spawning the child
        # (start_component api); the stub tree needs that directory present.
        (app_root / "src" / "tools" / "demiurgos-suite" / "wiki").mkdir(parents=True)
        env = _hermes_free_env(tmp_path, api_port, _free_port())
        return app_root, env

    def _api_pid_count(self, app_root: Path, api_port: int, env: dict[str, str]) -> int:
        """Count launcher-managed API processes, scoped to the stub venv.

        The real dev stack also runs ``uvicorn api_server:app`` on this
        machine, so the count must match the stub ``python`` path inside the
        temp app root — never the system-wide pattern. The ``[u]vicorn``
        bracket trick keeps the counting pipeline from matching itself.
        """
        stub_bin = app_root / ".venv" / "bin" / "python"
        probe = subprocess.run(
            ["bash", "-c",
             f'ps -eo pid=,args= | grep "[u]vicorn api_server:app" | grep -F "{stub_bin}" | wc -l'],
            env=env, capture_output=True, text=True, timeout=30,
        )
        return int(probe.stdout.strip() or 0)

    @pytest.mark.skipif(
        shutil.which("bash") is None or shutil.which("python3") is None,
        reason="stub matrix needs bash + python3",
    )
    def test_ubuntu_stub_uvicorn_matrix(self, tmp_path: Path) -> None:
        self._run_posix_matrix(tmp_path)

    @pytest.mark.skipif(
        os.uname().sysname != "Darwin" if os.name == "posix" else True,
        reason="darwin cell is the CI matrix proof (NOT run on this host)",
    )
    def test_macos_stub_uvicorn_matrix(self, tmp_path: Path) -> None:
        # Same launcher, Darwin branch (lsof/ps -ww -o command=): the stub
        # holds the port identically. CI macos-latest is the runtime proof.
        self._run_posix_matrix(tmp_path)

    @pytest.mark.skipif(
        os.name != "nt",
        reason="windows cell is the CI matrix proof (NOT run on this host)",
    )
    def test_windows_stub_uvicorn_matrix(self, tmp_path: Path) -> None:
        # The PS stack launcher derives the same contract env; the stub venv
        # would be .venv\\Scripts\\python.exe. CI windows-latest is the proof.
        pytest.fail("windows matrix cell must be driven by the CI job, not pytest here")

    def _run_posix_matrix(self, tmp_path: Path) -> None:
        api_port = _free_port()
        app_root, env = self._stub_env(tmp_path, api_port)
        launcher = app_root / "scripts" / "start-demiurgos.sh"

        # start -> running
        first = subprocess.run(["bash", str(launcher), "start"], env=env,
                               capture_output=True, text=True, timeout=120)
        assert first.returncode == 0, first.stderr
        try:
            assert self._api_pid_count(app_root, api_port, env) == 1

            # start again -> still exactly one process
            second = subprocess.run(["bash", str(launcher), "start"], env=env,
                                    capture_output=True, text=True, timeout=120)
            assert second.returncode == 0, second.stderr
            assert self._api_pid_count(app_root, api_port, env) == 1

            # restart -> exactly one process
            restart = subprocess.run(["bash", str(launcher), "restart"], env=env,
                                     capture_output=True, text=True, timeout=120)
            assert restart.returncode == 0, restart.stderr
            assert self._api_pid_count(app_root, api_port, env) == 1
        finally:
            stop = subprocess.run(["bash", str(launcher), "stop"], env=env,
                                  capture_output=True, text=True, timeout=60)
            assert stop.returncode == 0, stop.stderr
            _stop_and_assert_clean(launcher, env, api_port)

        # stop when down -> exit 0 (spec "Stop when not running")
        again = subprocess.run(["bash", str(launcher), "stop"], env=env,
                               capture_output=True, text=True, timeout=60)
        assert again.returncode == 0, again.stderr