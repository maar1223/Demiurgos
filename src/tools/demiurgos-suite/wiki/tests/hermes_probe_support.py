# -*- coding: utf-8 -*-
"""Shared live-probe harness for the Demiurgos Hermes gateway (WU-2, REQ-LPH-1..7, REQ-LPH-9).

One authority owns the gateway boot contract, log discovery, byte-offset
evidence polling and bounded teardown, so ``test_native_channel_probe.py`` and
``test_native_channel_suppression.py`` cannot drift apart (design N3, REQ-LPH-5).

The same boot contract (via :func:`_gateway_boot_env`) plus ``API_SERVER_KEY``
feeds :func:`drive_assistant_turn`, the REQ-LPH-9 assistant-turn driver: it boots
the gateway api_server and drives one real ``POST /v1/chat/completions`` turn.

Boot mirrors ``scripts/start-demiurgos.sh:480-484``: ``HERMES_ENABLE_PROJECT_PLUGINS=1``,
``DEMIURGOS_ROOT=<repo>``, both ``HERMES_HOME``/``DEMIURGOS_HERMES_HOME`` set to the
dedicated profile, and ``cwd=<repo>``. Registration evidence is read in **binary**
from ``<HERMES_HOME>/logs/agent.log`` starting at the boot byte offset — never
from the process stdout (REQ-LPH-3). Teardown is the bounded
``terminate()`` → ``wait(timeout)`` → ``kill()`` sequence in a ``finally``
(REQ-LPH-4). Missing evidence is a hard fail; a gateway that never creates
``<home>/logs`` AFTER boot is an honest ``ProbeLogDriftError`` (REQ-LPH-6); the
personal ``~/.hermes`` is a hard fail (REQ-LPH-7).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# This module lives at <repo>/src/tools/demiurgos-suite/wiki/tests/hermes_probe_support.py.
_HERE: Path = Path(__file__).resolve().parent  # <repo>/src/tools/demiurgos-suite/wiki/tests
_WIKI: Path = _HERE.parent  # <repo>/src/tools/demiurgos-suite/wiki
# wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> <repo>   (parents index 3, the repo convention)
REPO_ROOT: Path = _WIKI.parents[3]
# Self-check: fail loudly at import if the path layout ever changes, instead of
# silently booting the gateway with DEMIURGOS_ROOT=<repo>/src (which would make
# .hermes/plugins/demiurgos-idea-capture undiscoverable and Fix 2 silently fail).
assert "demiurgos-suite/wiki/tests" in str(Path(__file__).resolve()), str(
    Path(__file__).resolve()
)
_PLUGIN_INIT: Path = REPO_ROOT / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
assert _PLUGIN_INIT.is_file(), f"REPO_ROOT derivation is wrong; expected plugin at {_PLUGIN_INIT}"

LIVE_ENV_VAR = "DEMIURGOS_PROBE_LIVE"
HOME_ENV_VARS = ("DEMIURGOS_HERMES_HOME", "HERMES_HOME")
# Match the exact ``_track_callback`` phrasing (hermes_cli/plugins.py:914,
# DEBUG-only: ``Plugin %s registered %s: %s``) so an incidental DEBUG line that
# merely mentions a hook name is not mistaken for registration evidence.
HOOK_MARKERS = ("registered hook: pre_tool_call", "registered hook: pre_llm_call")
DEFAULT_TIMEOUT = 90.0
TERM_TIMEOUT = 10.0

# Model-level turn gate (REQ-LPH-9). DISTINCT from ``LIVE_ENV_VAR``
# (``DEMIURGOS_PROBE_LIVE``, the harness-level opt-in).
MODEL_LIVE_ENV_VAR = "DEMIURGOS_MODEL_LIVE"
# gateway/platforms/api_server.py DEFAULT_PORT (pinned runtime): the api_server
# binds ``API_SERVER_PORT`` (default 8642, gateway/config_env.py).
API_SERVER_DEFAULT_PORT = 8642
# gateway/config.py _has_usable_api_server_key / hermes_cli/auth.py
# has_usable_secret(min_length=16): the driver mirrors the gateway's own key
# strength guard before booting.
MIN_API_SERVER_KEY_LEN = 16


class ProbeIsolationError(RuntimeError):
    """The probe was pointed at the personal ``~/.hermes`` (P0-8). Hard fail."""


class ProbeUnavailable(RuntimeError):
    """A live-probe precondition is missing (opt-in, binary, profile). Skip."""


class ProbeLogDriftError(RuntimeError):
    """The expected gateway log path is not present (runtime drift). Skip."""


class ProbeTurnError(RuntimeError):
    """The turn driver booted/ran but could not produce evidence.

    Malformed ``API_SERVER_KEY``, a non-2xx chat-completions response, an SSE
    error frame, a child exit before the port opened, a deadline expiry, or a
    stream with neither reply text nor a tool call — loud fail, never a pass
    (REQ-LPH-9).
    """


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a gateway boot attempt: hook evidence read from the log."""

    booted: bool
    returncode: int | None
    hook_evidence: list[str]
    log_path: Path
    elapsed: float


@dataclass(frozen=True)
class TurnResult:
    """Outcome of one real assistant turn driven through the gateway
    api_server (REQ-LPH-9).

    ``reply_text`` is the concatenated ``choices[].delta.content`` SSE stream;
    ``tool_calls`` lists the tool names observed on ``hermes.tool.progress``
    events, in first-seen order with duplicates removed. ``error`` is reserved
    for an observed HTTP/model error on a structurally completed turn; the hard
    failure paths raise :class:`ProbeTurnError` instead of returning a result.
    """

    reply_text: str
    tool_calls: tuple[str, ...]
    status_code: int
    elapsed: float
    error: str | None = None


def personal_hermes_home() -> Path:
    """The personal Hermes profile the probe must never touch (P0-8)."""
    return Path.home() / ".hermes"


def assert_not_personal_profile(root: Path) -> None:
    """Raise :class:`ProbeIsolationError` when ``root`` resolves to the personal profile."""
    root = Path(root).expanduser().resolve()
    if root == personal_hermes_home().resolve():
        raise ProbeIsolationError(
            f"probe refused personal profile {personal_hermes_home()}: the live "
            "probe only runs against a dedicated test profile (P0-8)"
        )


def live_probe_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """True iff ``DEMIURGOS_PROBE_LIVE`` is exactly ``"1"`` (REQ-LPH-1)."""
    env = os.environ if environ is None else environ
    return env.get(LIVE_ENV_VAR) == "1"


def model_live_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """True iff ``DEMIURGOS_MODEL_LIVE`` is exactly ``"1"`` (REQ-LPH-9).

    DISTINCT from :func:`live_probe_enabled`: the model-level gate controls the
    assistant-turn driver specifically, not the whole live-probe harness.
    """
    env = os.environ if environ is None else environ
    return env.get(MODEL_LIVE_ENV_VAR) == "1"


def resolve_dedicated_profile_root(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the dedicated profile root, refusing the personal profile.

    ``DEMIURGOS_HERMES_HOME`` then ``HERMES_HOME``; raises :class:`ProbeUnavailable`
    when unset and :class:`ProbeIsolationError` when it resolves to ``~/.hermes``.
    """
    env = os.environ if environ is None else environ
    value = ""
    for name in HOME_ENV_VARS:
        candidate = (env.get(name) or "").strip()
        if candidate:
            value = candidate
            break
    if not value:
        raise ProbeUnavailable(
            "no dedicated test profile is provisioned (DEMIURGOS_HERMES_HOME unset)"
        )
    root = Path(value).expanduser().resolve()
    assert_not_personal_profile(root)
    return root


def gateway_log_path(home: Path) -> Path:
    """Return ``<home>/logs/agent.log`` (pure path; existence NOT required).

    The gateway creates ``<home>/logs`` lazily in ``setup_logging()`` on boot
    (``hermes_logging.py:181``), so requiring the directory BEFORE boot falsely
    reports drift on a fresh profile. Drift is detected post-boot in
    :func:`boot_and_probe_gateway` (REQ-LPH-6).
    """
    return Path(home) / "logs" / "agent.log"


def _terminate(proc: subprocess.Popen, *, term_timeout: float = TERM_TIMEOUT) -> None:
    """``terminate()`` → ``wait(term_timeout)`` → ``kill()``; never raises TimeoutExpired."""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except (ProcessLookupError, OSError):
        return
    try:
        proc.wait(timeout=term_timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        return
    try:
        proc.wait(timeout=term_timeout)
    except subprocess.TimeoutExpired:
        pass


def _read_new_lines(log_path: Path, offset: int, sink: list[str]) -> int:
    """Append complete new lines from ``offset``; return the new byte offset.

    Works on raw bytes so the offset advances exactly and a partial trailing
    line is left for the next poll (REQ-LPH-3 byte-offset exactness).
    """
    try:
        with log_path.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read()
    except OSError:
        return offset
    if not chunk:
        return offset
    last_newline = chunk.rfind(b"\n")
    if last_newline == -1:
        return offset  # incomplete line; wait for the rest
    complete = chunk[: last_newline + 1]
    for line in complete.splitlines():
        decoded = line.decode("utf-8", errors="replace")
        if decoded.strip():
            sink.append(decoded)
    return offset + len(complete)


def _gateway_boot_env(
    home: Path,
    repo: Path,
    *,
    api_key: str | None = None,
    port: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The single gateway boot-env authority (REQ-LPH-5 no-drift).

    Both :func:`boot_and_probe_gateway` and :func:`drive_assistant_turn` build
    their child env here so the plugin-load contract cannot diverge (mirrors
    ``scripts/start-demiurgos.sh:480-484``): ``HERMES_HOME``/``DEMIURGOS_HERMES_HOME``
    point at the dedicated profile, ``HERMES_ENABLE_PROJECT_PLUGINS=1``,
    ``DEMIURGOS_ROOT=<repo>``. ``API_SERVER_KEY``/``API_SERVER_PORT`` are added
    only when the turn driver supplies them; the plain probe path is unchanged.
    """
    base = dict(os.environ) if environ is None else dict(environ)
    env = {
        **base,
        "HERMES_HOME": str(home),
        "DEMIURGOS_HERMES_HOME": str(home),
        "HERMES_ENABLE_PROJECT_PLUGINS": "1",
        "DEMIURGOS_ROOT": str(repo),
    }
    if api_key is not None:
        env["API_SERVER_KEY"] = api_key
    if port is not None:
        env["API_SERVER_PORT"] = str(port)
    return env


def boot_and_probe_gateway(
    hermes_bin: str,
    home: Path,
    *,
    repo: Path = REPO_ROOT,
    timeout: float = DEFAULT_TIMEOUT,
    environ: Mapping[str, str] | None = None,
) -> ProbeResult:
    """Boot the real gateway under the plugin-load contract and read evidence.

    Evidence is read from ``<home>/logs/agent.log`` starting at the boot byte
    offset. One overall monotonic deadline bounds the wait; teardown always runs.
    """
    home = Path(home)
    assert_not_personal_profile(home)
    log_path = gateway_log_path(home)
    boot_offset = log_path.stat().st_size if log_path.exists() else 0

    env = _gateway_boot_env(home, repo, environ=environ)

    proc = subprocess.Popen(
        [hermes_bin, "gateway", "run"],
        env=env,
        cwd=str(repo),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    evidence: list[str] = []
    offset = boot_offset
    started = time.monotonic()
    deadline = started + timeout
    try:
        while time.monotonic() < deadline:
            offset = _read_new_lines(log_path, offset, evidence)
            joined = "\n".join(evidence).lower()
            if all(marker in joined for marker in HOOK_MARKERS):
                break
            if proc.poll() is not None:
                offset = _read_new_lines(log_path, offset, evidence)  # final drain
                break
            time.sleep(0.5)
    finally:
        _terminate(proc)

    # Post-boot drift: the gateway creates <home>/logs lazily in setup_logging()
    # (hermes_logging.py:181). If it never appeared after boot, the installed
    # runtime no longer writes logs/agent.log there — an honest skip, never a
    # pass (REQ-LPH-6). A pre-boot absence is NOT drift (the resolver is pure).
    logs_dir = home / "logs"
    if not logs_dir.is_dir():
        raise ProbeLogDriftError(
            f"gateway log path drifted: {logs_dir} was not created by the gateway "
            "after boot (the installed runtime no longer writes logs/agent.log there)"
        )

    joined = "\n".join(evidence).lower()
    hook_evidence = [
        line for line in evidence if any(marker in line.lower() for marker in HOOK_MARKERS)
    ]
    return ProbeResult(
        booted=all(marker in joined for marker in HOOK_MARKERS),
        returncode=proc.returncode,
        hook_evidence=hook_evidence,
        log_path=log_path,
        elapsed=time.monotonic() - started,
    )


def _wait_for_api_server(proc: subprocess.Popen, port: int, deadline: float) -> None:
    """Block until ``127.0.0.1:port`` accepts a connection, or fail loudly.

    Enforces the ONE overall monotonic deadline and surfaces a child exit before
    the port opened (a fatal api_server config, e.g. a port already in use).
    """
    while True:
        if time.monotonic() > deadline:
            raise ProbeTurnError(
                f"the gateway api_server did not open port {port} before the "
                "assistant-turn deadline expired"
            )
        if proc.poll() is not None:
            raise ProbeTurnError(
                "the gateway exited before the api_server opened "
                f"(returncode={proc.returncode})"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.25)


def _consume_sse_frame(
    event: str, data: str, reply_parts: list[str], tool_names: list[str]
) -> None:
    """Fold one complete SSE frame into the reply/tool accumulators (REQ-LPH-9).

    An ``error`` payload (the runtime's finish-chunk failure envelope) is a loud
    :class:`ProbeTurnError`. ``hermes.tool.progress`` frames contribute their
    ``tool`` name; chat-completion chunks contribute ``choices[].delta.content``.
    """
    payload_text = data.strip()
    if not payload_text or payload_text == "[DONE]":
        return
    try:
        payload = json.loads(payload_text)
    except ValueError:
        return  # keepalive/comment line: not a data frame
    if not isinstance(payload, dict):
        return
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str) and error["message"]:
        raise ProbeTurnError(f"the model turn reported an error: {error['message']}")
    if event == "hermes.tool.progress" or ("tool" in payload and "choices" not in payload):
        name = payload.get("tool")
        if isinstance(name, str) and name:
            if name not in tool_names:
                tool_names.append(name)
        return
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str) and content:
                    reply_parts.append(content)


def _consume_sse_stream(
    response: Any, reply_parts: list[str], tool_names: list[str], deadline: float
) -> None:
    """Read an SSE chat-completions stream frame by frame until EOF.

    The stream is delimited by blank lines (``event:`` line optional, then one
    or more ``data:`` lines). Every iteration re-checks the ONE overall deadline
    so a slow trickle cannot outlive it.
    """
    current_event = ""
    data_lines: list[str] = []
    for raw_line in response:
        if time.monotonic() > deadline:
            raise ProbeTurnError(
                "the assistant-turn deadline expired while reading the SSE stream"
            )
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            if data_lines:
                _consume_sse_frame(current_event, "\n".join(data_lines), reply_parts, tool_names)
                data_lines = []
                current_event = ""
            continue
        if line.startswith("event:"):
            current_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
    if data_lines:  # defensive: a trailing frame without a blank-line terminator
        _consume_sse_frame(current_event, "\n".join(data_lines), reply_parts, tool_names)


def _http_error_text(exc: urllib.error.HTTPError) -> str:
    """Human text for a non-2xx chat-completions response: the JSON
    ``error.message`` when present, else the raw body, prefixed with the status."""
    detail = ""
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            error = parsed.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                detail = error["message"]
    except ValueError:
        pass
    if not detail:
        detail = raw.strip()[:200]
    return f"chat-completions HTTP {exc.code}: {detail}".strip()


def _post_chat_completion(
    port: int,
    api_key: str,
    prompt: str,
    reply_parts: list[str],
    tool_names: list[str],
    deadline: float,
) -> int:
    """POST the OpenAI-compatible chat-completions request over SSE.

    ``stream=true`` is REQUIRED: the tool-call trace is emitted only on the SSE
    path (``hermes.tool.progress`` frames). Returns the HTTP status; raises
    :class:`ProbeTurnError` on a non-2xx status (with the observed error text) or
    a transport failure.
    """
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    body = json.dumps(
        {
            "model": "hermes-agent",
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProbeTurnError(
            "the assistant-turn deadline expired before the chat-completions request"
        )
    try:
        with urllib.request.urlopen(request, timeout=remaining) as response:
            status_code = int(response.status)
            _consume_sse_stream(response, reply_parts, tool_names, deadline)
            return status_code
    except urllib.error.HTTPError as exc:
        raise ProbeTurnError(_http_error_text(exc)) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ProbeTurnError(f"chat-completions request to {url} failed: {exc}") from exc


def drive_assistant_turn(
    hermes_bin: str,
    home: Path,
    *,
    prompt: str,
    api_key: str,
    port: int = API_SERVER_DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT,
    environ: Mapping[str, str] | None = None,
) -> TurnResult:
    """Boot the gateway (plugin-load contract + ``API_SERVER_KEY``) and drive one real turn.

    ``api_key`` is validated before any boot: empty -> :class:`ProbeUnavailable`
    (named skip, no process); present but shorter than
    :data:`MIN_API_SERVER_KEY_LEN` -> :class:`ProbeTurnError` (loud fail, no
    process). The gateway boots under the same :func:`_gateway_boot_env` contract
    as :func:`boot_and_probe_gateway` plus ``API_SERVER_KEY``/``API_SERVER_PORT``.
    The driver waits for the api_server port, POSTs ``/v1/chat/completions``
    (``stream=true``, ``model="hermes-agent"``), accumulates the reply text and
    the ``hermes.tool.progress`` tool-call trace, and tears down with the bounded
    :func:`_terminate` in a ``finally`` under ONE monotonic deadline.

    A non-2xx status, an SSE error frame, a child exit before the port opens, a
    deadline expiry, or a stream with neither reply text nor a tool call raises
    :class:`ProbeTurnError` with the observed error — never a false pass.
    """
    home = Path(home)
    assert_not_personal_profile(home)

    stripped_key = api_key.strip() if api_key else ""
    if not stripped_key:
        raise ProbeUnavailable(
            "API_SERVER_KEY is unset/empty: named skip, the assistant-turn "
            "driver cannot authenticate the chat-completions request"
        )
    if len(stripped_key) < MIN_API_SERVER_KEY_LEN:
        raise ProbeTurnError(
            f"API_SERVER_KEY is too short ({len(stripped_key)} chars < "
            f"{MIN_API_SERVER_KEY_LEN}): the gateway rejects it as unusable; "
            "refusing to boot with a malformed credential (never a false pass)"
        )

    repo = REPO_ROOT
    env = _gateway_boot_env(home, repo, api_key=stripped_key, port=port, environ=environ)
    proc = subprocess.Popen(
        [hermes_bin, "gateway", "run"],
        env=env,
        cwd=str(repo),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    started = time.monotonic()
    deadline = started + timeout
    reply_parts: list[str] = []
    tool_names: list[str] = []
    try:
        _wait_for_api_server(proc, port, deadline)
        status_code = _post_chat_completion(
            port, stripped_key, prompt, reply_parts, tool_names, deadline
        )
        if not "".join(reply_parts).strip() and not tool_names:
            raise ProbeTurnError(
                "the assistant turn returned no reply text and no tool-call "
                "trace: no skill-visibility evidence (never a false pass)"
            )
    finally:
        # One bounded teardown, on every path (including failures); the wait is
        # clamped so teardown cannot outlive the overall deadline.
        _terminate(
            proc,
            term_timeout=min(TERM_TIMEOUT, max(0.5, deadline - time.monotonic())),
        )

    return TurnResult(
        reply_text="".join(reply_parts),
        tool_calls=tuple(tool_names),
        status_code=status_code,
        elapsed=time.monotonic() - started,
    )
