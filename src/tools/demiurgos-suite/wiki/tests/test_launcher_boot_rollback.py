# -*- coding: utf-8 -*-
"""S6-2/D6 (task 9.4) — bounded boot rollback contract.

Both launchers must fall back to the previous bootable ``app/<version>`` when
the new version fails to boot (no HTTP 200 on ``GET /health``), with rollback
ONLY (no update/download logic, G9 untouched), a local ``app/`` scan only, and
at most ONE attempt guarded by an exported env marker so a broken previous
version cannot loop.

Coverage:

- Text scans of both launchers (house style, matching ``test_launcher_portable``):
  the health probe prefers ``curl`` with a venv-python ``urllib`` fallback; the
  API readiness gate is the bounded ``wait_for_health``; the rollback scans
  ``$INSTALL_ROOT/app/*/`` locally; the env-marker guard bounds the attempt;
  the flip is ``ln -sfn`` / ``New-Item -ItemType Junction`` + a launcher
  re-exec from the flipped ``current``.
- POSIX runtime harness that RUNS on this host: a fixture install root with
  ``app/v2`` (broken boot) and ``app/v1`` (good stub uvicorn) proves the flip
  ``current -> app/v1``, the single-attempt guard, and the actionable failure
  message. The broken-boot wait is shortened via the launcher's
  ``DEMIURGOS_HEALTH_POLLS`` / ``DEMIURGOS_HEALTH_POLL_INTERVAL`` env seams
  (product defaults stay 20 x 1s).
- Windows parity text tests only: the PS 5.1 runtime cell is NOT run on this
  Linux host (CI windows-latest / the ps51 job is the proof), reported honestly.
"""

from __future__ import annotations

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

#: No-op browser stub dir (same hard guard as the boot smoke): prepended to
#: the child PATH so a launcher that ignores DEMIURGOS_NO_BROWSER still cannot
#: open a real browser from a harness.
NOOP_BROWSER_BIN = Path("/tmp/opencode/noop-browser/bin")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _require_noop_stub() -> None:
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


def _http_status(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status
    except Exception:
        return None


def _stop_and_assert_clean(launcher: Path, env: dict[str, str], api_port: int) -> None:
    """Teardown contract (same as the boot smoke): stop the launcher, then
    assert NO leftover listener on the test port."""
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


# ---------------------------------------------------------------------------
# POSIX launcher — text-scan contract
# ---------------------------------------------------------------------------


class TestPosixRollbackContract:
    def test_health_probe_prefers_curl_with_venv_python_fallback(self):
        """S6-2/D6: the /health probe uses curl when present, else the layout
        venv python via urllib — never a new hard external dependency."""
        text = _text(PORTABLE_LAUNCHER)
        health_block = text[text.index("http_health_ok()"):text.index("wait_for_health()")]
        assert "command -v curl" in health_block
        assert "curl -fsS" in health_block
        assert "urllib.request" in health_block
        assert '"$PYTHON_BIN"' in health_block
        # Loopback only: the probe never leaves 127.0.0.1.
        assert "127.0.0.1" in health_block

    def test_api_readiness_is_bounded_health_not_plain_port(self):
        text = _text(PORTABLE_LAUNCHER)
        health_block = text[text.index("wait_for_health()"):text.index("find_previous_version()")]
        assert '"$HEALTH_POLLS"' in health_block
        assert '"$HEALTH_POLL_INTERVAL"' in health_block
        start_block = text[text.index("start_all()"):text.index("open_browser()")]
        # The API REQUIRED readiness is the health signal (S6-2/D6)...
        assert 'if wait_for_health "$API_PORT"' in start_block
        # ...while the gateway keeps the plain port wait (best-effort, S2-2).
        assert 'wait_for_port "$GATEWAY_PORT"' in start_block

    def test_rollback_scans_local_app_dirs_only(self):
        text = _text(PORTABLE_LAUNCHER)
        scan = text[text.index("find_previous_version()"):text.index("rollback_if_boot_failed()")]
        assert '"$INSTALL_ROOT"/app/*/' in scan
        # Bootable = launcher + layout venv present.
        assert 'scripts/start-demiurgos.sh' in scan
        assert '"$dir/.venv"' in scan
        # Directory-mtime selection: GNU stat -c %Y, BSD stat -f %m.
        assert "stat -c %Y" in scan
        assert "stat -f %m" in scan
        # No update/download logic (G9 untouched): nothing in the scan fetches.
        for banned in ("curl", "wget", "git", "DEMIURGOS_VERSION"):
            assert banned not in scan, banned

    def test_rollback_is_bounded_by_env_marker_and_reexecs(self):
        text = _text(PORTABLE_LAUNCHER)
        rollback = text[text.index("rollback_if_boot_failed()"):text.index("wait_for_port_free()")]
        assert "DEMIURGOS_ROLLBACK_ATTEMPTED" in rollback
        assert 'ln -sfn "app/$prev" "$INSTALL_ROOT/current"' in rollback
        assert 'exec "$INSTALL_ROOT/current/scripts/start-demiurgos.sh" restart' in rollback
        # The double-failure guard prints and returns 1 (no loop).
        assert "no further fallback" in rollback
        assert "return 1" in rollback
        # No fetch inside the rollback action itself.
        assert "curl" not in rollback
        assert "wget" not in rollback


# ---------------------------------------------------------------------------
# POSIX launcher — runtime rollback harness (RUNS on this Linux host)
# ---------------------------------------------------------------------------

_GOOD_STUB = """#!/usr/bin/env bash
# Stub uvicorn (good boot): a child python3 http server holds the requested
# port and answers 200 on ANY path (the readiness gate is a real HTTP 200 on
# /health — S6-2/D6; the plain http.server module would 404 unknown paths).
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

_BROKEN_STUB = """#!/usr/bin/env bash
# Stub uvicorn (broken boot): exits immediately; the port never listens and
# /health never answers.
exit 1
"""


def _make_version(version_dir: Path, *, broken: bool, bootable: bool = True) -> None:
    """One ``app/<version>`` tree: the real launcher + a stub venv python."""
    scripts = version_dir / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(PORTABLE_LAUNCHER, scripts / "start-demiurgos.sh")
    if bootable:
        stub_bin = version_dir / ".venv" / "bin"
        stub_bin.mkdir(parents=True)
        stub = _BROKEN_STUB if broken else _GOOD_STUB
        (stub_bin / "python").write_text(stub, encoding="utf-8")
        (stub_bin / "python").chmod(0o755)
    # The launcher cds into the API dir before spawning the child.
    (version_dir / "src" / "tools" / "demiurgos-suite" / "wiki").mkdir(parents=True)


def _build_install_root(
    tmp_path: Path, install_root: Path, *, broken: list[str],
    good: list[str] | None = None, current: str, non_bootable: list[str] | None = None,
) -> Path:
    """Fixture install root: ``app/<version>`` dirs + ``current`` symlink."""
    for version in broken:
        _make_version(install_root / "app" / version, broken=True)
    for version in (good or []):
        _make_version(install_root / "app" / version, broken=False)
    for version in (non_bootable or []):
        _make_version(install_root / "app" / version, broken=False, bootable=False)
    (install_root / "current").symlink_to(f"app/{current}", target_is_directory=True)
    return install_root / "current"


def _rollback_env(tmp_path: Path, install_root: Path, api_port: int) -> dict[str, str]:
    """Env for a hermetic rollback run: hermes scrubbed, fresh HOME/runtime
    dirs, headless guard, and a SHORT health budget (product default stays
    20 x 1s; the seams exist for exactly this harness)."""
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
        "DEMIURGOS_HOME": str(install_root),
        "DEMIURGOS_DATA_ROOT": str(tmp_path / "data"),
        "DEMIURGOS_API_PORT": str(api_port),
        "DEMIURGOS_GATEWAY_PORT": str(_free_port()),
        "DEMIURGOS_NO_BROWSER": "1",
        # Readiness headroom (issue #3): the "good" stub is a plain `python3
        # -c http.server` whose interpreter startup can exceed a sub-second
        # budget on a loaded/slow CI runner (the aarch64/macOS flake), making the
        # GOOD version look "not ready" and failing the rollback assertion. The
        # launcher's budget is polls x interval = 50 x 0.1s = 5s: still bounded
        # (a BROKEN version is only polled 5s before rollback) but ample for the
        # good version to answer /health.
        "DEMIURGOS_HEALTH_POLLS": "50",
        "DEMIURGOS_HEALTH_POLL_INTERVAL": "0.1",
    }
    env.pop("HERMES_BIN", None)
    env.pop("DEMIURGOS_ROLLBACK_ATTEMPTED", None)
    return env


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None or shutil.which("python3") is None,
    reason="POSIX rollback harness needs real bash + python3 (on Windows `bash` is the WSL stub)",
)
class TestPosixRollbackRuntime:
    def test_broken_new_version_rolls_back_to_previous(self, tmp_path: Path) -> None:
        install_root = tmp_path / "install"
        current = _build_install_root(
            tmp_path, install_root, broken=["v2"], good=["v1"], current="v2"
        )
        api_port = _free_port()
        env = _rollback_env(tmp_path, install_root, api_port)
        launcher = current / "scripts" / "start-demiurgos.sh"

        result = subprocess.run(
            ["bash", str(launcher), "start"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert "API did not become ready" in result.stderr
        assert "rolling back current -> app/v1" in result.stderr
        assert "API ready on" in result.stdout
        # The flip happened: current now points at the previous version.
        assert (install_root / "current").resolve().name == "v1"
        try:
            # The previous version is actually serving /health.
            status = None
            for _ in range(30):
                status = _http_status(f"http://127.0.0.1:{api_port}/health")
                if status == 200:
                    break
                time.sleep(0.5)
            assert status == 200, "previous version never served /health"
        finally:
            _stop_and_assert_clean(launcher, env, api_port)

    def test_broken_previous_version_does_not_loop(self, tmp_path: Path) -> None:
        install_root = tmp_path / "install"
        current = _build_install_root(
            tmp_path, install_root, broken=["v2", "v1"], current="v2"
        )
        api_port = _free_port()
        env = _rollback_env(tmp_path, install_root, api_port)
        launcher = current / "scripts" / "start-demiurgos.sh"

        result = subprocess.run(
            ["bash", str(launcher), "start"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode != 0, result.stderr
        assert "rolling back current -> app/v1" in result.stderr
        assert "Boot failed again after the rollback; no further fallback." in result.stderr
        # Exactly ONE flip: current still points at the previous version.
        assert (install_root / "current").resolve().name == "v1"
        # The launcher returned (no loop) and the port never serves.
        assert not _port_listening(api_port)

    def test_no_bootable_previous_prints_actionable_message(self, tmp_path: Path) -> None:
        install_root = tmp_path / "install"
        current = _build_install_root(
            tmp_path, install_root, broken=["v2"], current="v2"
        )
        api_port = _free_port()
        env = _rollback_env(tmp_path, install_root, api_port)
        launcher = current / "scripts" / "start-demiurgos.sh"

        result = subprocess.run(
            ["bash", str(launcher), "start"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode != 0, result.stderr
        assert "No bootable previous version found under" in result.stderr
        assert "cannot roll back" in result.stderr
        # No flip happened: current still points at the broken version.
        assert (install_root / "current").resolve().name == "v2"
        assert not _port_listening(api_port)

    def test_non_bootable_previous_is_not_selected(self, tmp_path: Path) -> None:
        install_root = tmp_path / "install"
        # v1 exists but lacks the layout venv -> not bootable -> not selected.
        current = _build_install_root(
            tmp_path, install_root, broken=["v2"], current="v2", non_bootable=["v1"]
        )
        api_port = _free_port()
        env = _rollback_env(tmp_path, install_root, api_port)
        launcher = current / "scripts" / "start-demiurgos.sh"

        result = subprocess.run(
            ["bash", str(launcher), "start"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode != 0, result.stderr
        assert "No bootable previous version found under" in result.stderr
        assert (install_root / "current").resolve().name == "v2"


# ---------------------------------------------------------------------------
# Windows launcher — parity text-scan contract (PS 5.1 runtime cell NOT run
# on this Linux host; CI windows-latest / the ps51 job is the proof)
# ---------------------------------------------------------------------------


class TestPowerShellRollbackParity:
    def test_ps1_stays_ascii_only(self):
        """S2-8: PS 5.1 mis-decodes BOM-less UTF-8; ASCII-only is the rule."""
        PS_STACK.read_bytes().decode("ascii")

    def test_ps_rollback_scans_local_app_dirs_only(self):
        text = _text(PS_STACK)
        scan = text[text.index("function Find-PreviousVersion"):text.index("function Invoke-BootRollback")]
        assert 'Join-Path $installRoot "app"' in scan
        assert "Get-ChildItem" in scan
        assert "scripts\\start-demiurgos.ps1" in scan
        assert '".venv"' in scan
        # Bootable selection by LastWriteTime (directory mtime equivalent).
        assert "LastWriteTime" in scan
        # No update/download logic (G9 untouched): nothing in the scan fetches.
        for banned in ("Invoke-WebRequest", "Invoke-RestMethod", "irm", "git", "DEMIURGOS_VERSION"):
            assert banned not in scan, banned

    def test_ps_rollback_is_bounded_by_env_marker_and_reexecs(self):
        text = _text(PS_STACK)
        rollback = text[text.index("function Invoke-BootRollback"):]
        assert '$env:DEMIURGOS_ROLLBACK_ATTEMPTED -eq "1"' in rollback
        assert "no further fallback" in rollback
        # Junction flip (link only, never the target) + launcher re-exec.
        assert "New-Item -ItemType Junction" in rollback
        assert 'Join-Path $current "scripts\\start-demiurgos.ps1"' in rollback
        assert "restart" in rollback
        assert "exit $child.ExitCode" in rollback
        # No fetch inside the rollback action itself.
        assert "Invoke-WebRequest" not in rollback
        assert "irm" not in rollback

    def test_ps_switch_hooks_rollback_on_readiness_failure(self):
        text = _text(PS_STACK)
        switch = text[text.index("switch ($Action)"):]
        assert "Invoke-BootRollback" in switch
        assert "exit 1" in switch
