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
#   no-logs        — never creates ``<home>/logs`` (proves post-boot drift)
#   incidental     — mentions a hook name WITHOUT the ``registered hook:``
#                    prefix (proves an incidental mention is not evidence)
#   exit-78        — exits with the gateway's fatal-config code, no markers
#
# The marker strings mirror the exact gateway phrasing
# ``hermes_cli/plugins.py:914`` emits at DEBUG:
# ``Plugin <name> registered <kind>: <key>``.
_FAKE_HERMES_SOURCE = '''\
import os
import signal
import sys
import time
from pathlib import Path

mode = "__MODE__"
home = Path(os.environ["HERMES_HOME"])
logs = home / "logs"
if mode == "no-logs":
    # Never creates <home>/logs: proves post-boot drift detection (T4.1).
    sys.exit(0)
logs.mkdir(parents=True, exist_ok=True)
log = logs / "agent.log"


def emit(lines):
    with log.open("a", encoding="utf-8") as fh:
        fh.write("\\n".join(lines) + "\\n")


MARKER_TOOL = "registered hook: pre_tool_call"
MARKER_LLM = "registered hook: pre_llm_call"

if mode == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    emit([MARKER_TOOL, MARKER_LLM])
    time.sleep(600)
    sys.exit(0)

if mode == "silent":
    emit(["gateway starting", "no hook registration here"])
    sys.exit(0)

if mode == "incidental":
    # Mentions the hook names WITHOUT the "registered hook:" prefix.
    emit([
        "gateway boot",
        "pre_tool_call mentioned incidentally",
        "pre_llm_call mentioned incidentally",
    ])
    sys.exit(0)

if mode == "exit-78":
    emit(["gateway starting", "fatal config conflict"])
    sys.exit(78)

emit([
    "gateway boot",
    MARKER_TOOL,
    MARKER_LLM,
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


def test_gateway_log_path_is_pure(tmp_path: Path) -> None:
    """``gateway_log_path`` is a pure resolver: it returns the path and does NOT
    raise when ``<home>/logs`` is absent (the gateway creates it lazily on boot)."""
    home = tmp_path / "home"
    home.mkdir()  # no logs/ subdir
    assert hermes_probe_support.gateway_log_path(home) == home / "logs" / "agent.log"


def test_boot_creates_log_dir_and_reads_debug_markers(tmp_path: Path) -> None:
    """A fresh home (no pre-boot ``logs/``) boots and reads both
    ``registered hook:`` markers from the log the gateway creates (T4.1/T4.4)."""
    home = tmp_path / "home"
    home.mkdir()  # genuinely no logs/ dir before boot
    assert not (home / "logs").exists()
    fake = _write_fake_hermes(tmp_path)

    result = hermes_probe_support.boot_and_probe_gateway(
        str(fake), home, repo=hermes_probe_support.REPO_ROOT, timeout=10.0, environ={}
    )

    assert result.booted is True
    joined = "\n".join(result.hook_evidence).lower()
    assert "registered hook: pre_tool_call" in joined
    assert "registered hook: pre_llm_call" in joined
    assert result.hook_evidence, "expected the marker lines to be captured"


def test_no_incidental_hook_mention_marks_booted(tmp_path: Path) -> None:
    """A line that merely mentions ``pre_tool_call`` without the
    ``registered hook:`` prefix is NOT evidence (REQ-LPH-8, T4.4/T4.5)."""
    home = tmp_path / "home"
    home.mkdir()
    fake = _write_fake_hermes(tmp_path, mode="incidental")

    result = hermes_probe_support.boot_and_probe_gateway(
        str(fake), home, repo=hermes_probe_support.REPO_ROOT, timeout=10.0, environ={}
    )

    assert result.booted is False
    assert result.hook_evidence == []


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


def test_fatal_exit_surfaces_returncode_not_a_pass(tmp_path: Path) -> None:
    """A gateway that exits with the fatal-config code (78) and no markers must
    surface the observed return code and never report a pass (REQ-LPH-3/T4.5)."""
    home = tmp_path / "home"
    home.mkdir()
    fake = _write_fake_hermes(tmp_path, mode="exit-78")

    result = hermes_probe_support.boot_and_probe_gateway(
        str(fake), home, repo=hermes_probe_support.REPO_ROOT, timeout=10.0, environ={}
    )

    assert result.booted is False
    assert result.returncode == 78


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


# -- REQ-LPH-6: log-path drift (post-boot) -----------------------------------


def test_gateway_log_path_drift_raises(tmp_path: Path) -> None:
    """A missing ``<home>/logs`` pre-boot is NOT drift (the resolver is pure); a
    gateway that never creates it AFTER boot is honest drift, not a false pass."""
    home = tmp_path / "home"
    home.mkdir()  # no logs/ subdir
    # Pure resolver: no raise on a fresh profile.
    assert hermes_probe_support.gateway_log_path(home) == home / "logs" / "agent.log"

    fake = _write_fake_hermes(tmp_path, mode="no-logs")
    with pytest.raises(hermes_probe_support.ProbeLogDriftError):
        hermes_probe_support.boot_and_probe_gateway(
            str(fake),
            home,
            repo=hermes_probe_support.REPO_ROOT,
            timeout=10.0,
            environ={},
        )
    assert not (home / "logs").is_dir()


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


# -- REQ-LPH-9: model-level gate ------------------------------------------


def test_model_live_disabled_by_default() -> None:
    """The model-level gate is off unless ``DEMIURGOS_MODEL_LIVE`` is exactly ``"1"``."""
    assert hermes_probe_support.model_live_enabled({}) is False
    assert hermes_probe_support.model_live_enabled({"DEMIURGOS_MODEL_LIVE": ""}) is False
    assert hermes_probe_support.model_live_enabled({"DEMIURGOS_MODEL_LIVE": "0"}) is False
    assert (
        hermes_probe_support.model_live_enabled({"DEMIURGOS_MODEL_LIVE": "true"}) is False
    )


def test_model_live_enabled_only_on_exact_one() -> None:
    """``DEMIURGOS_MODEL_LIVE=1`` enables the assistant turn; the harness-level
    ``DEMIURGOS_PROBE_LIVE`` gate is DISTINCT and does not enable it."""
    assert hermes_probe_support.model_live_enabled({"DEMIURGOS_MODEL_LIVE": "1"}) is True
    assert hermes_probe_support.model_live_enabled({"DEMIURGOS_PROBE_LIVE": "1"}) is False
    assert (
        hermes_probe_support.model_live_enabled(
            {"DEMIURGOS_MODEL_LIVE": "1", "DEMIURGOS_PROBE_LIVE": "1"}
        )
        is True
    )


def test_model_gate_name_has_no_superseded_alias() -> None:
    """Guard: the exploration's provisional name ``DEMIURGOS_PROBE_MODEL`` is
    superseded and MUST NOT appear anywhere in the helper module."""
    source = Path(hermes_probe_support.__file__).read_text(encoding="utf-8")
    assert "DEMIURGOS_PROBE_MODEL" not in source


# -- REQ-LPH-5: shared gateway boot-env authority --------------------------


def test_gateway_boot_env_carries_plugin_contract(tmp_path: Path) -> None:
    """The single boot-env builder carries the plugin-load contract
    (``HERMES_ENABLE_PROJECT_PLUGINS=1``, ``DEMIURGOS_ROOT``, both home vars)."""
    env = hermes_probe_support._gateway_boot_env(
        tmp_path / "home", hermes_probe_support.REPO_ROOT, environ={}
    )
    assert env["HERMES_ENABLE_PROJECT_PLUGINS"] == "1"
    assert env["DEMIURGOS_ROOT"] == str(hermes_probe_support.REPO_ROOT)
    assert env["HERMES_HOME"] == str(tmp_path / "home")
    assert env["DEMIURGOS_HERMES_HOME"] == str(tmp_path / "home")


def test_gateway_boot_env_includes_api_key_and_port_when_given(tmp_path: Path) -> None:
    """``API_SERVER_KEY``/``API_SERVER_PORT`` are added when the driver supplies them,
    and stay absent on the plain probe path (behavior unchanged)."""
    env = hermes_probe_support._gateway_boot_env(
        tmp_path / "home",
        hermes_probe_support.REPO_ROOT,
        api_key="k" * 20,
        port=9876,
        environ={},
    )
    assert env["API_SERVER_KEY"] == "k" * 20
    assert env["API_SERVER_PORT"] == "9876"
    plain = hermes_probe_support._gateway_boot_env(
        tmp_path / "home", hermes_probe_support.REPO_ROOT, environ={}
    )
    assert "API_SERVER_KEY" not in plain
    assert "API_SERVER_PORT" not in plain


# -- REQ-LPH-9: assistant-turn driver --------------------------------------

# A tiny HTTP stand-in for the real gateway api_server. It writes its PID to
# ``<HERMES_HOME>/driver.pid``, binds ``API_SERVER_PORT``, accepts the driver's
# port-wait probe (a bare connect that closes), serves ONE
# ``POST /v1/chat/completions`` response, dumps the raw request to
# ``<HERMES_HOME>/driver-request.txt``, then sleeps. Modes:
#   driver-ok          — 200 SSE: role + content + ``hermes.tool.progress``
#                        (skills_list) + content + finish + ``[DONE]``
#   driver-no-evidence — 200 SSE: role + finish + ``[DONE]`` (no content/tools)
#   driver-sse-error   — 200 SSE: evidence, then a finish chunk carrying
#                        ``error.message`` (provider rate_limit) + ``[DONE]``
#   driver-http-error  — HTTP 502 JSON error body (non-2xx)
#   driver-ignore-term — ignores SIGTERM, never binds, sleeps (proves bounded kill)
_FAKE_GATEWAY_SOURCE = '''\
import os
import signal
import socket
import sys
import time
from pathlib import Path

mode = "__MODE__"
home = Path(os.environ["HERMES_HOME"])
home.mkdir(parents=True, exist_ok=True)
(home / "driver.pid").write_text(str(os.getpid()), encoding="utf-8")
port = int(os.environ.get("API_SERVER_PORT", "8642"))

ROLE = 'data: {"choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\\n\\n'
FINISH_STOP = 'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\\n\\n'
DONE = "data: [DONE]\\n\\n"

if mode == "driver-ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(600)
    sys.exit(0)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(5)
sock.settimeout(30)

SSE_HEADERS = (
    b"HTTP/1.1 200 OK\\r\\nContent-Type: text/event-stream\\r\\n"
    b"Connection: close\\r\\n\\r\\n"
)

for _ in range(5):
    try:
        conn, _ = sock.accept()
    except socket.timeout:
        break
    conn.settimeout(10)
    request = b""
    while b"\\r\\n\\r\\n" not in request:
        chunk = conn.recv(4096)
        if not chunk:
            break
        request += chunk
    head, _, _ = request.partition(b"\\r\\n\\r\\n")
    first = head.split(b"\\r\\n", 1)[0] if head else b""
    if first.startswith(b"POST /v1/chat/completions"):
        clen = 0
        for line in head.split(b"\\r\\n"):
            if line.lower().startswith(b"content-length:"):
                clen = int(line.split(b":", 1)[1].strip())
                break
        while clen and len(request) < len(head) + 4 + clen:
            chunk = conn.recv(4096)
            if not chunk:
                break
            request += chunk
        if mode == "driver-http-error":
            conn.sendall(
                b"HTTP/1.1 502 Bad Gateway\\r\\nContent-Type: application/json\\r\\n"
                b"Connection: close\\r\\n\\r\\n"
                b'{"error":{"message":"provider rate_limit observed","type":"server_error"}}'
            )
        else:
            if mode == "driver-ok":
                frames = [
                    ROLE.encode(),
                    'data: {"choices":[{"index":0,"delta":{"content":"Hello from the seeded skill world"},"finish_reason":null}]}\\n\\n'.encode(),
                    'event: hermes.tool.progress\\ndata: {"tool":"skills_list","status":"running"}\\n\\n'.encode(),
                    'data: {"choices":[{"index":0,"delta":{"content":" I can also view skills."},"finish_reason":null}]}\\n\\n'.encode(),
                    FINISH_STOP.encode(),
                    DONE.encode(),
                ]
            elif mode == "driver-sse-error":
                frames = [
                    ROLE.encode(),
                    'event: hermes.tool.progress\\ndata: {"tool":"skill_view","status":"running"}\\n\\n'.encode(),
                    'data: {"choices":[{"index":0,"delta":{"content":"partial"},"finish_reason":null}]}\\n\\n'.encode(),
                    # The real runtime's finish-chunk failure envelope puts "error"
                    # at the TOP level (api_server_openai_routes.py _chunk + finish_chunk["error"]).
                    'data: {"choices":[{"index":0,"delta":{},"finish_reason":"length"}],"error":{"message":"provider rate_limit hit","type":"agent_error"}}\\n\\n'.encode(),
                    DONE.encode(),
                ]
            else:  # driver-no-evidence
                frames = [ROLE.encode(), FINISH_STOP.encode(), DONE.encode()]
            conn.sendall(SSE_HEADERS + b"".join(frames))
        (home / "driver-request.txt").write_bytes(request)
        conn.close()
        break
    conn.close()
sock.close()
time.sleep(600)
sys.exit(0)
'''


def _write_fake_gateway(base: Path, mode: str = "driver-ok") -> Path:
    """Write an executable fake gateway api_server for the driver tests."""
    script = base / f"fake-gateway-{mode}"
    script.write_text(
        f"#!{sys.executable}\n" + _FAKE_GATEWAY_SOURCE.replace("__MODE__", mode),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_drive_assistant_turn_collects_reply_and_tool_calls(tmp_path: Path) -> None:
    """The driver boots the gateway, POSTs the chat-completions request, and
    returns the SSE reply text plus the ``hermes.tool.progress`` tool trace."""
    home = tmp_path / "home"
    fake = _write_fake_gateway(tmp_path, mode="driver-ok")
    key = "sk-" + "a" * 20

    result = hermes_probe_support.drive_assistant_turn(
        str(fake),
        home,
        prompt="List every skill you currently have available, by name.",
        api_key=key,
        port=8651,
        timeout=10.0,
        environ={},
    )

    assert result.status_code == 200
    assert result.reply_text == "Hello from the seeded skill world I can also view skills."
    assert result.tool_calls == ("skills_list",)
    assert result.error is None
    assert result.elapsed >= 0.0

    request = (home / "driver-request.txt").read_text(encoding="utf-8")
    assert request.startswith("POST /v1/chat/completions")
    assert f"Authorization: Bearer {key}" in request
    assert '"model": "hermes-agent"' in request
    assert '"stream": true' in request
    assert "List every skill you currently have available" in request


def test_driver_missing_key_is_named_skip(tmp_path: Path) -> None:
    """An empty ``api_key`` is a NAMED skip (ProbeUnavailable): no boot happens."""
    home = tmp_path / "home"
    fake = _write_fake_gateway(tmp_path, mode="driver-ok")
    for bad in ("", "   "):
        with pytest.raises(hermes_probe_support.ProbeUnavailable):
            hermes_probe_support.drive_assistant_turn(
                str(fake), home, prompt="p", api_key=bad, timeout=10.0, environ={},
            )
    assert not (home / "driver.pid").exists(), "the gateway must not boot on a missing key"


def test_driver_short_key_fails(tmp_path: Path) -> None:
    """A present but too-short key (< 16 chars) is a LOUD fail (ProbeTurnError)
    before any boot — never a false pass."""
    home = tmp_path / "home"
    fake = _write_fake_gateway(tmp_path, mode="driver-ok")
    with pytest.raises(hermes_probe_support.ProbeTurnError) as excinfo:
        hermes_probe_support.drive_assistant_turn(
            str(fake), home, prompt="p", api_key="short-key", timeout=10.0, environ={},
        )
    assert "16" in str(excinfo.value)
    assert not (home / "driver.pid").exists(), "the gateway must not boot with a malformed key"


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("driver-http-error", "502"),
        ("driver-sse-error", "rate_limit"),
    ],
)
def test_driver_surfaces_http_error(tmp_path: Path, mode: str, expected: str) -> None:
    """A non-2xx HTTP response or an SSE ``error`` chunk surfaces the observed
    HTTP/model error as a LOUD ProbeTurnError — never a pass."""
    home = tmp_path / "home"
    fake = _write_fake_gateway(tmp_path, mode=mode)
    with pytest.raises(hermes_probe_support.ProbeTurnError) as excinfo:
        hermes_probe_support.drive_assistant_turn(
            str(fake), home, prompt="p",
            api_key="sk-" + "b" * 20, port=8652, timeout=10.0, environ={},
        )
    assert expected in str(excinfo.value)
    assert (home / "driver.pid").is_file(), "the gateway booted before the loud failure"


def test_driver_no_evidence_raises(tmp_path: Path) -> None:
    """A 200 SSE stream with neither reply text nor a tool call is no evidence:
    the driver must fail loudly, never report a pass."""
    home = tmp_path / "home"
    fake = _write_fake_gateway(tmp_path, mode="driver-no-evidence")
    with pytest.raises(hermes_probe_support.ProbeTurnError) as excinfo:
        hermes_probe_support.drive_assistant_turn(
            str(fake), home, prompt="p",
            api_key="sk-" + "c" * 20, port=8653, timeout=10.0, environ={},
        )
    assert "evidence" in str(excinfo.value).lower()


def test_driver_teardown_kills_ignore_term(tmp_path: Path) -> None:
    """The driver's bounded teardown (terminate -> wait -> kill) force-kills a
    gateway child that ignores SIGTERM, running even on the failure path and
    without exceeding the overall deadline."""
    home = tmp_path / "home"
    fake = _write_fake_gateway(tmp_path, mode="driver-ignore-term")
    started = time.monotonic()
    with pytest.raises(hermes_probe_support.ProbeTurnError):
        hermes_probe_support.drive_assistant_turn(
            str(fake), home, prompt="p",
            api_key="sk-" + "d" * 20, port=8654, timeout=2.0, environ={},
        )
    elapsed = time.monotonic() - started
    assert elapsed < 8.0, "the driver exceeded the bounded overall deadline"
    pid = int((home / "driver.pid").read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # the ignore-term child was force-killed and reaped


def test_driver_refuses_personal_home(tmp_path: Path) -> None:
    """The driver refuses the personal ``~/.hermes`` (P0-8) before any boot."""
    fake = _write_fake_gateway(tmp_path, mode="driver-ok")
    with pytest.raises(hermes_probe_support.ProbeIsolationError):
        hermes_probe_support.drive_assistant_turn(
            str(fake),
            hermes_probe_support.personal_hermes_home(),
            prompt="p",
            api_key="sk-" + "e" * 20,
            timeout=10.0,
            environ={},
        )


# -- runtime anchors for the turn driver's runtime dependencies ----------------


def _installed_agent_dir() -> Path | None:
    """Resolve the installed Hermes agent root (mirrors test_native_channel_probe)."""
    override = os.environ.get("DEMIURGOS_HERMES_AGENT_DIR", "").strip()
    if override:
        return Path(override)
    candidate = Path.home() / ".hermes" / "hermes-agent"
    if (candidate / "gateway" / "run_turn.py").is_file():
        return candidate
    return None


def test_runtime_anchor_names_tool_progress_event() -> None:
    """Guard: the installed api_server keeps emitting the ``hermes.tool.progress``
    SSE event the driver parses; a phrasing change fails loudly, never silently
    breaks the tool-call trace. Skips honestly when the runtime is absent."""
    agent = _installed_agent_dir()
    if agent is None:
        pytest.skip("installed hermes-agent runtime not found; tool-progress anchor unchecked")
    routes = agent / "gateway" / "platforms" / "api_server_openai_routes.py"
    if not routes.is_file():
        pytest.skip(f"runtime anchor {routes} absent; tool-progress anchor unchecked")
    source = routes.read_text(encoding="utf-8")
    assert "hermes.tool.progress" in source, (
        "installed runtime no longer emits the hermes.tool.progress SSE event in "
        "api_server_openai_routes.py; the driver's tool-call trace has drifted"
    )


def test_runtime_anchor_secret_min_length_16() -> None:
    """Guard: the installed auth contract keeps the ``has_usable_secret`` guard
    with a ``min_length`` the driver mirrors for ``API_SERVER_KEY`` validation;
    drift fails loudly, never a silent mismatch."""
    agent = _installed_agent_dir()
    if agent is None:
        pytest.skip("installed hermes-agent runtime not found; secret-length anchor unchecked")
    auth_py = agent / "hermes_cli" / "auth.py"
    if not auth_py.is_file():
        pytest.skip(f"runtime anchor {auth_py} absent; secret-length anchor unchecked")
    source = auth_py.read_text(encoding="utf-8")
    assert "def has_usable_secret" in source, (
        "installed hermes_cli/auth.py no longer defines has_usable_secret; "
        "the driver's API_SERVER_KEY validation has no runtime counterpart"
    )
    assert "min_length" in source, (
        "installed hermes_cli/auth.py no longer exposes min_length on has_usable_secret; "
        "the driver's MIN_API_SERVER_KEY_LEN=16 assumption has drifted"
    )
