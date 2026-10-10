# -*- coding: utf-8 -*-
"""Shared live-probe harness for the Demiurgos Hermes gateway (WU-2, REQ-LPH-1..7).

One authority owns the gateway boot contract, log discovery, byte-offset
evidence polling and bounded teardown, so ``test_native_channel_probe.py`` and
``test_native_channel_suppression.py`` cannot drift apart (design N3, REQ-LPH-5).

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

import os
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

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


class ProbeIsolationError(RuntimeError):
    """The probe was pointed at the personal ``~/.hermes`` (P0-8). Hard fail."""


class ProbeUnavailable(RuntimeError):
    """A live-probe precondition is missing (opt-in, binary, profile). Skip."""


class ProbeLogDriftError(RuntimeError):
    """The expected gateway log path is not present (runtime drift). Skip."""


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a gateway boot attempt: hook evidence read from the log."""

    booted: bool
    returncode: int | None
    hook_evidence: list[str]
    log_path: Path
    elapsed: float


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

    base = dict(os.environ) if environ is None else dict(environ)
    env = {
        **base,
        "HERMES_HOME": str(home),
        "DEMIURGOS_HERMES_HOME": str(home),
        "HERMES_ENABLE_PROJECT_PLUGINS": "1",
        "DEMIURGOS_ROOT": str(repo),
    }

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
