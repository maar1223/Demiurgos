# -*- coding: utf-8 -*-
"""S3a — POSIX installer core contract (design S3-1..S3-7, tasks 4.1-4.12).

The installer core (``scripts/install-demiurgos.sh`` + the shared checksum
library ``scripts/lib/verify_checksum.sh``) must:

- never clone the private source repository (no ``git`` at all), never run
  ``npm``, never invoke ``sudo``, and never embed the private repo URL
  (D1 — the leak lives at ``install.sh:27``, which S4 owns);
- install the mandatory closure wheels-only and hash-locked
  (``--only-binary=:all:`` AND ``--require-hashes``);
- verify every download against its published checksum BEFORE staging;
- stage atomically on the same filesystem as the install root
  (``<install_root>/.staging/<version>-<rand>``, never ``/tmp``), rename into
  ``app/<version>`` and flip ``current`` only on success;
- bootstrap the data-root pointer and the ``<data_root>/.env`` seed exactly
  once (only when neither the env override nor a pointer exists; an existing
  pointer and an existing ``.env`` are preserved byte-for-byte);
- install optional extras best-effort (non-fatal, warn-degrade);
- never execute arbitrary payload files (only the launcher the user starts
  runs);
- provision a pinned, checksum-verified ``uv`` (musl/glibc aware), with
  ``codesign`` verification on macOS when available (M2);
- enforce the NARROWED support matrix (decision #3579, supersedes #3565):
  Windows 10/11 x86_64; macOS >= 13 arm64 (Apple Silicon) ONLY; Linux
  x86_64/aarch64 glibc >= 2.28. Intel macOS, macOS below the floor,
  musl/Alpine and glibc < 2.28 fail fast with a clear message + the documented
  manual-install alternative — BEFORE any download;
- keep the S3b Windows ``LongPathsEnabled`` floor as a parity note.

The second half of this file is a fixture-only harness (task 4.11): a local
``file://`` channel with a STUB ``uv`` and a STUB python stands in for the
real toolchain (real uv/CPython/wheels download is CI-owned, S5a — reported
``not-run`` here). It proves install -> boot -> ``curl /health`` + ``/``,
re-run idempotency, checksum-mismatch abort with no runnable state, M3
coexistence (``repo/`` clone preserved) and the byte-compatible pointer that
Python's ``data_root.read_pointer`` can read back (task 4.9).

Text scans mirror ``test_launcher_portable.py``: the installer is a CODE
artifact of the checkout, located from this file — never from a configured
data root.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

INSTALLER = _REPO_ROOT / "scripts" / "install-demiurgos.sh"
VERIFY_LIB = _REPO_ROOT / "scripts" / "lib" / "verify_checksum.sh"
PS_INSTALLER = _REPO_ROOT / "scripts" / "install-demiurgos.ps1"
PS_VERIFY_LIB = _REPO_ROOT / "scripts" / "lib" / "verify_checksum.ps1"
INSTALL_SH = _REPO_ROOT / "install.sh"
INSTALL_PS1 = _REPO_ROOT / "install.ps1"
# The historical Windows installer, preserved as the explicit opt-in overlay
# (mirrors `install.sh --with-cli-stack`). Always run with -File.
PS_CLI_OVERLAY = _REPO_ROOT / "scripts" / "install-cli-stack.ps1"
POINTER_NAME = "data-root.json"
STUB_UV_VERSION = "0.5.24-test"

_BASH_32_BANS = ("declare -A", "mapfile", "readarray", "^^}", "&>>")

#: POSIX-runner-only: cells that SHELL OUT to the POSIX installer core
#: (``scripts/install-demiurgos.sh`` / ``scripts/lib/verify_checksum.sh``) and
#: therefore cannot run on Windows, where a bare ``bash`` resolves to the WSL
#: launcher (``C:\\Windows\\System32\\bash.exe``, no distribution installed) and
#: dies printing a UTF-16 "no installed distributions" error. The Windows
#: parity cells live in the ``*Windows*`` classes and are gated to ``nt`` via
#: ``PS_RUNNER``; this is the mirror gate for the POSIX half.
POSIX_RUNNER = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX installer cells shell out to the POSIX core; Windows runs the *Windows* cells",
)

#: No-op browser stub dir (incident s2b-harness-gotcha): prepended to the
#: child PATH so a launcher that ignores the env flag still cannot open a
#: real browser.
NOOP_BROWSER_BIN = Path("/tmp/opencode/noop-browser/bin")
# The no-op browser stubs are PROVISIONED by the harness (see
# _require_noop_stub) so the suite never depends on an out-of-band /tmp dir
# that the OS may clean between runs.
_NOOP_BROWSER_TOOLS = (
    "xdg-open", "open", "sensible-browser", "x-www-browser", "gio",
    "brave-browser-stable", "brave-browser", "google-chrome",
    "chromium", "chromium-browser", "firefox",
)
_NOOP_BROWSER_SCRIPT = (
    "#!/bin/sh\n"
    "# no-op browser stub (s2b-harness-gotcha guard): record, never open.\n"
    'log="$(dirname "$0")/../calls.log"\n'
    'printf "%s %s\\n" "$0" "$*" >> "$log" 2>/dev/null || true\n'
    "exit 0\n"
)

_UV_STUB_SH = r"""#!/usr/bin/env bash
# Stub uv for the S3a fixture harness (task 4.11). Emulates the commands the
# installer uses and RECORDS its argv so the contract test can assert the
# exact flags. The "python" it installs is the repository's real venv
# interpreter (DEMIURGOS_STUB_PYTHON), so the staged app genuinely boots.
# Real uv/CPython/wheels download is CI-owned (S5a) — never run here.
set -u
printf 'uv %s\n' "$*" >> "${DEMIURGOS_STUB_LOG:?}"
cmd="${1:-}"
shift || true
case "$cmd" in
  python)
    mkdir -p "${UV_PYTHON_INSTALL_DIR:?}/bin"
    ln -sfn "${DEMIURGOS_STUB_PYTHON:?}" "$UV_PYTHON_INSTALL_DIR/bin/python"
    ;;
  venv)
    # uv venv --python 3.12 <dest>  ->  create a REAL venv from the managed
    # python with system-site-packages, so the staged app genuinely boots.
    # The managed python is the repository venv python (which carries the
    # full dependency set); the .pth below makes those dependencies visible
    # to the staged venv regardless of HOME isolation (real uv pip install
    # puts wheels into the venv itself — CI-owned, not-run here).
    dest=""
    for a in "$@"; do
      case "$a" in
        --python) continue ;;
        -*) continue ;;
        *) dest="$a" ;;
      esac
    done
    [ -n "$dest" ] || { echo "stub uv: venv missing dest" >&2; exit 2; }
    "${DEMIURGOS_STUB_PYTHON:?}" -m venv --system-site-packages "$dest" || exit 1
    repo_site="$("${DEMIURGOS_STUB_PYTHON:?}" -c 'import site; print(site.getsitepackages()[0])' 2>/dev/null || true)"
    if [ -n "$repo_site" ]; then
      mkdir -p "$dest/lib/python3.12/site-packages"
      printf '%s\n' "$repo_site" > "$dest/lib/python3.12/site-packages/demiurgos-repo.pth"
    fi
    ;;
  pip)
    if [ "${DEMIURGOS_STUB_FAIL_PIP:-0}" = "1" ]; then
      echo "stub uv: pip install failed (stub)" >&2
      exit 1
    fi
    ;;
  run)
    # uv run python -c ... -> drop the leading "python", delegate to the stub
    shift || true
    exec "${DEMIURGOS_STUB_PYTHON:?}" "$@"
    ;;
  *)
    echo "stub uv: unknown command: $cmd" >&2
    exit 2
    ;;
esac
"""


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _require_noop_stub() -> None:
    """Hard harness guard (incident s2b-harness-gotcha): the launcher under
    test must never open a real browser. The stubs are (re)created here,
    idempotently, so the suite is self-contained and never depends on an
    out-of-band /tmp directory the OS may clean. Fails loudly if the stubs
    cannot be provisioned (never silently proceeds toward a real browser)."""
    NOOP_BROWSER_BIN.mkdir(parents=True, exist_ok=True)
    for tool in _NOOP_BROWSER_TOOLS:
        stub = NOOP_BROWSER_BIN / tool
        if not stub.is_file():
            stub.write_text(_NOOP_BROWSER_SCRIPT, encoding="utf-8")
            stub.chmod(0o755)
    if not (NOOP_BROWSER_BIN / "xdg-open").is_file():
        raise RuntimeError(
            "harness guard could not provision the no-op browser stubs at "
            f"{NOOP_BROWSER_BIN}"
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
    listener on the test port."""
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
# 4.1 — Contract text assertions
# ---------------------------------------------------------------------------


class TestNoPrivateCloneOrNpm:
    def test_no_git_at_all_in_installer(self):
        text = _text(INSTALLER)
        assert "git" not in text

    def test_no_npm_in_installer(self):
        text = _text(INSTALLER)
        assert "npm" not in text

    def test_no_private_repo_url(self):
        """D1: the leak is at install.sh:27 (S4 owns it); the core never embeds
        the private owner or any github URL."""
        text = _text(INSTALLER) + _text(VERIFY_LIB)
        assert "maar1223" not in text
        assert "github.com" not in text

    def test_no_sudo(self):
        text = _text(INSTALLER)
        assert "sudo" not in text


class TestWheelsOnlyHashLocked:
    def test_only_binary_all_present(self):
        assert "--only-binary=:all:" in _text(INSTALLER)

    def test_require_hashes_present(self):
        assert "--require-hashes" in _text(INSTALLER)

    def test_mandatory_pip_line_uses_both_flags(self):
        text = _text(INSTALLER)
        line = next(
            ln for ln in text.splitlines()
            if 'uv" pip install' in ln and "--require-hashes" in ln
        )
        assert "--only-binary=:all:" in line


class TestChecksumBeforeStaging:
    def test_payload_verify_precedes_extraction(self):
        """The payload archive is verified against SHA256SUMS BEFORE it is
        extracted into the staging tree (task 4.1, spec 'Checksum mismatch')."""
        text = _text(INSTALLER)
        verify_at = text.index('verify_sha256 "$PAYLOAD_FILE"')
        extract_at = text.index('tar -xzf "$PAYLOAD_FILE" -C "$STAGE_DIR"')
        assert verify_at < extract_at

    def test_mismatch_aborts_with_clean_rerun_path(self):
        text = _text(INSTALLER)
        assert "checksum" in text
        assert "re-run" in text


class TestAtomicSameFsStaging:
    def test_staging_under_install_root(self):
        text = _text(INSTALLER)
        assert 'STAGING_ROOT="$INSTALL_ROOT/.staging"' in text

    def test_no_hardcoded_tmp(self):
        text = _text(INSTALLER)
        assert "/tmp" not in text

    def test_atomic_rename_and_current_flip(self):
        text = _text(INSTALLER)
        assert 'mv "$STAGE_DIR" "$INSTALL_ROOT/app/$VERSION"' in text
        assert 'ln -sfn "app/$VERSION" "$INSTALL_ROOT/current"' in text


class TestPointerBootstrapOnly:
    def test_pointer_guarded_by_env_and_pointer(self):
        """Pointer is written ONLY when neither the env override nor an
        existing pointer is present; an existing pointer is never re-oriented
        (spec 'Existing data root preserved', design S3-7)."""
        text = _text(INSTALLER)
        assert 'if [ -n "${DEMIURGOS_DATA_ROOT:-}" ]' in text
        assert '[ -r "$POINTER_FILE" ]' in text
        assert "data-root.json" in text

    def test_env_seed_guarded_by_absence(self):
        text = _text(INSTALLER)
        assert 'if [ ! -f "$ENV_FILE" ]' in text
        assert "DEMIURGOS_AUTH_MODE=local-dev" in text

    def test_pointer_format_byte_compatible_with_data_root(self):
        """The pointer record MUST be the data_root.py JSON shape
        (schema_version 1, data_root, updated_at)."""
        text = _text(INSTALLER)
        assert '"schema_version": 1' in text
        assert '"data_root"' in text
        assert '"updated_at"' in text


class TestOptionalExtrasBestEffort:
    def test_optional_install_non_fatal(self):
        text = _text(INSTALLER)
        assert "requirements-optional" in text
        assert "|| warn" in text


class TestChannelConfigPersisted:
    """Slice 2b — the installer persists ``<install_root>/channel.json``
    (``schema_version`` + ``url_base``) at install time so the runtime updater
    resolves the channel base URL without the env override (design S2-b)."""

    def test_posix_writes_channel_json_with_schema_and_url(self):
        text = _text(INSTALLER)
        assert "channel.json" in text
        assert '"schema_version": 1' in text
        assert '"url_base"' in text
        # The record is written beside the install root, like the pointer.
        assert "INSTALL_ROOT/channel.json" in text
        # The scheme-validated URL_BASE is the source (installer scheme gate).
        assert '"$URL_BASE"' in text

    def test_windows_parity_writes_channel_json_with_schema_and_url(self):
        text = _text(PS_INSTALLER)
        assert "channel.json" in text
        assert '"schema_version": 1' in text
        assert '"url_base"' in text
        assert 'Join-Path $installRoot "channel.json"' in text
        assert "$urlBase" in text


class TestNoArbitraryPayloadExecution:
    def test_installer_never_executes_payload_files(self):
        """Threat-matrix 'Documentation-like paths' (execution half): the
        installer only runs the verified uv binary and standard tools; it
        never sources, execs or bash-runs anything extracted from the
        payload. The user starts the launcher afterwards."""
        text = _text(INSTALLER)
        assert 'source "$STAGE' not in text
        assert 'exec "$STAGE' not in text
        assert 'bash "$STAGE' not in text
        assert 'source "$PAYLOAD' not in text


class TestUvProvisioning:
    def test_uv_pinned_and_checksum_verified(self):
        text = _text(INSTALLER)
        assert "UV_VERSION" in text
        assert 'verify_sha256 "$UV_ARCHIVE"' in text
        assert "$INSTALL_ROOT/bin/uv" in text

    def test_codesign_on_macos(self):
        """M2: codesign --verify --deep --strict when available on Darwin."""
        text = _text(INSTALLER)
        assert "codesign --verify --deep --strict" in text
        assert "Darwin" in text

    def test_uv_python_and_venv_commands(self):
        text = _text(INSTALLER)
        assert "UV_PYTHON_INSTALL_DIR" in text
        assert "venv --python 3.12" in text
        assert "python install 3.12" in text


class TestSupportMatrixNarrowed3579:
    def test_libc_detection_present(self):
        """S3-3 detection points: getconf GNU_LIBC_VERSION, /etc/alpine-release,
        ldd --version."""
        text = _text(INSTALLER)
        assert "getconf GNU_LIBC_VERSION" in text
        assert "/etc/alpine-release" in text
        assert "ldd --version" in text

    def test_musl_fails_fast_with_manual_alternative(self):
        """Decision #3579 (supersedes the #3565 'musl proceeds' wording):
        musl/Alpine is NOT supported — the installer fails fast with the
        explicit message + the documented manual-install alternative and never
        attempts a wheels-only install that cannot satisfy the closure."""
        text = _text(INSTALLER)
        assert "musl/Alpine" in text
        assert "not supported" in text
        assert "manual" in text

    def test_before_s5_gate_referenced_without_rephrasing(self):
        """D3: single authoritative gate statement — later references point to
        (D3) without restating the timing."""
        text = _text(INSTALLER)
        assert "(D3)" in text


class TestFloorsPreflight:
    def test_macos_floor(self):
        """Decision #3579: macOS >= 13 on Apple Silicon (arm64) ONLY."""
        text = _text(INSTALLER)
        assert "sw_vers -productVersion" in text
        assert "13" in text
        assert "Apple Silicon" in text

    def test_macos_intel_fails_fast(self):
        """Decision #3579: Intel macOS is NOT supported — fail fast with a
        clear message + the documented manual-install alternative."""
        text = _text(INSTALLER)
        assert "Intel Macs are not supported" in text

    def test_glibc_floor(self):
        text = _text(INSTALLER)
        assert "2.28" in text

    def test_free_disk_floor(self):
        text = _text(INSTALLER)
        assert "df -Pk" in text

    def test_windows_longpaths_parity_note(self):
        """S3b parity: the POSIX core documents the Windows LongPathsEnabled
        floor; the S3b Windows core enforces it."""
        text = _text(INSTALLER)
        assert "LongPathsEnabled" in text


def _floors_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    """Minimal env that reaches the floors preflight (``check_floors``) with
    the installer's ``DEMIURGOS_FAKE_*`` detection seams (same pattern as the
    ``DEMIURGOS_UV_SHA256`` test seam — never by editing the script at
    runtime). ``URL_BASE`` points at an EMPTY channel: unsupported platforms
    abort at ``check_floors`` BEFORE any download; supported platforms pass
    the floors and then fail LATER at version resolution — proving the failure
    is not a floors rejection. tmp HOME/XDG/RUNTIME so the real ``~/.demiurgos``
    and the real data-root pointer are never touched."""
    empty_channel = tmp_path / "empty-channel"
    empty_channel.mkdir(exist_ok=True)
    env = {
        "DEMIURGOS_URL_BASE": f"file://{empty_channel}",
        "DEMIURGOS_HOME": str(tmp_path / "install"),
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
        "DEMIURGOS_NO_BROWSER": "1",
        "PATH": f"{NOOP_BROWSER_BIN}:{os.environ.get('PATH', '/usr/bin:/bin')}",
    }
    env.update(overrides)
    return env


def _run_floors(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALLER)], env=env,
        capture_output=True, text=True, timeout=120,
    )


@POSIX_RUNNER
class TestUnsupportedPlatformsFailFast:
    """Decision #3579 — narrowed matrix. Intel macOS, macOS below the floor,
    musl/Alpine and glibc < 2.28 are NOT supported: each fails fast with a
    clear, friendly message + the documented manual-install alternative BEFORE
    any download. Platforms are simulated via the installer's
    ``DEMIURGOS_FAKE_*`` detection seams."""

    def test_intel_macos_fails_fast(self, tmp_path: Path):
        result = _run_floors(_floors_env(
            tmp_path,
            DEMIURGOS_FAKE_OS="Darwin",
            DEMIURGOS_FAKE_ARCH="x86_64",
            DEMIURGOS_FAKE_MACOS_VERSION="13.6",
        ))
        assert result.returncode != 0
        assert "Intel Macs are not supported" in result.stderr
        assert "manual" in result.stderr.lower()

    def test_macos_below_floor_fails_fast_naming_version(self, tmp_path: Path):
        result = _run_floors(_floors_env(
            tmp_path,
            DEMIURGOS_FAKE_OS="Darwin",
            DEMIURGOS_FAKE_ARCH="arm64",
            DEMIURGOS_FAKE_MACOS_VERSION="12.7",
        ))
        assert result.returncode != 0
        assert "macOS 13 or newer is required" in result.stderr
        assert "found 12.7" in result.stderr

    def test_musl_fails_fast(self, tmp_path: Path):
        result = _run_floors(_floors_env(tmp_path, DEMIURGOS_FAKE_LIBC="musl"))
        assert result.returncode != 0
        assert "musl/Alpine" in result.stderr
        assert "not supported" in result.stderr

    def test_glibc_below_floor_fails_fast_naming_version(self, tmp_path: Path):
        result = _run_floors(
            _floors_env(tmp_path, DEMIURGOS_FAKE_GLIBC_VERSION="2.27")
        )
        assert result.returncode != 0
        assert "glibc 2.28 or newer is required" in result.stderr
        assert "found 2.27" in result.stderr


@POSIX_RUNNER
class TestSupportedPlatformsProceed:
    """Supported combos (decision #3579) PASS the floors preflight: the run
    fails later at version resolution against the empty channel, so the
    failure is provably NOT a floors rejection."""

    def test_macos_arm64_proceeds_past_floors(self, tmp_path: Path):
        result = _run_floors(_floors_env(
            tmp_path,
            DEMIURGOS_FAKE_OS="Darwin",
            DEMIURGOS_FAKE_ARCH="arm64",
            DEMIURGOS_FAKE_MACOS_VERSION="13.0",
        ))
        assert result.returncode != 0  # empty channel — NOT a floors failure
        assert "not supported" not in result.stderr
        assert "or newer is required" not in result.stderr

    def test_linux_glibc_floor_proceeds_past_floors(self, tmp_path: Path):
        result = _run_floors(
            _floors_env(tmp_path, DEMIURGOS_FAKE_GLIBC_VERSION="2.28")
        )
        assert result.returncode != 0  # empty channel — NOT a floors failure
        assert "not supported" not in result.stderr
        assert "or newer is required" not in result.stderr

    def test_linux_aarch64_proceeds_past_floors(self, tmp_path: Path):
        result = _run_floors(_floors_env(
            tmp_path,
            DEMIURGOS_FAKE_OS="Linux",
            DEMIURGOS_FAKE_ARCH="aarch64",
            DEMIURGOS_FAKE_GLIBC_VERSION="2.28",
        ))
        assert result.returncode != 0  # empty channel — NOT a floors failure
        assert "not supported" not in result.stderr
        assert "or newer is required" not in result.stderr


class TestBash32Lint:
    def test_installer_bash32_compatible(self):
        text = _text(INSTALLER)
        for banned in _BASH_32_BANS:
            assert banned not in text, banned

    def test_verify_lib_bash32_compatible(self):
        text = _text(VERIFY_LIB)
        for banned in _BASH_32_BANS:
            assert banned not in text, banned


# ---------------------------------------------------------------------------
# 4.2 — verify_checksum.sh: order + no system python
# ---------------------------------------------------------------------------


@POSIX_RUNNER
class TestVerifyChecksumLibrary:
    def test_branch_order_sha256sum_then_shasum_then_uv(self):
        """S3-2 order: sha256sum -> shasum -a 256 (macOS) -> bundled-Python
        hashlib via `uv run python -c` (never system Python)."""
        text = _text(VERIFY_LIB)
        assert text.index("sha256sum") < text.index("shasum -a 256")
        assert text.index("shasum -a 256") < text.index("run python")

    def test_no_system_python_in_lib(self):
        text = _text(VERIFY_LIB)
        assert "python3" not in text
        assert "command -v python" not in text

    def test_standalone_matches(self, tmp_path: Path):
        payload = tmp_path / "blob.bin"
        payload.write_bytes(b"hello checksum")
        expected = hashlib.sha256(b"hello checksum").hexdigest()
        result = subprocess.run(
            ["bash", str(VERIFY_LIB), str(payload), expected],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr

    def test_standalone_mismatch(self, tmp_path: Path):
        payload = tmp_path / "blob.bin"
        payload.write_bytes(b"hello checksum")
        wrong = "0" * 64
        result = subprocess.run(
            ["bash", str(VERIFY_LIB), str(payload), wrong],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1
        assert "MISMATCH" in result.stderr

    def test_shasum_branch_used_when_sha256sum_absent(self, tmp_path: Path):
        """Simulate macOS: no sha256sum on PATH, shasum present."""
        payload = tmp_path / "blob.bin"
        payload.write_bytes(b"hello checksum")
        expected = hashlib.sha256(b"hello checksum").hexdigest()
        bin_dir = tmp_path / "fakebin"
        bin_dir.mkdir()
        shim = bin_dir / "shasum"
        shim.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"-a\" ]; then shift 2; fi\n"
            "/usr/bin/sha256sum \"$@\"\n"
        )
        shim.chmod(0o755)
        shim_awk = bin_dir / "awk"
        shim_awk.write_text("#!/bin/sh\n/usr/bin/awk \"$@\"\n")
        shim_awk.chmod(0o755)
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "DEMIURGOS_UV_SHA256": "unused",
        }
        # The library must pick the shasum branch: force sha256sum to be
        # invisible by putting a broken sha256sum shim on PATH that exits 1.
        broken = bin_dir / "sha256sum"
        broken.write_text("#!/bin/sh\nexit 1\n")
        broken.chmod(0o755)
        result = subprocess.run(
            ["bash", str(VERIFY_LIB), str(payload), expected],
            env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr

    def test_hashlib_branch_used_when_no_native_tool(self, tmp_path: Path):
        """Bundled-Python hashlib via `uv run python -c`: neither sha256sum nor
        shasum on PATH — the stub uv delegates to the real interpreter."""
        payload = tmp_path / "blob.bin"
        payload.write_bytes(b"hello checksum")
        expected = hashlib.sha256(b"hello checksum").hexdigest()
        bin_dir = tmp_path / "fakebin"
        bin_dir.mkdir()
        stub = bin_dir / "uv"
        stub.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "run" ] && [ "$2" = "python" ]; then shift 2; '
            'exec /usr/bin/python3 "$@"; fi\n'
        )
        stub.chmod(0o755)
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "UV_BIN": str(stub),
        }
        result = subprocess.run(
            ["bash", str(VERIFY_LIB), str(payload), expected],
            env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 4.11 — Fixture-only channel harness (file:// + stub uv/python)
# ---------------------------------------------------------------------------

# S5b (task 8.4): the consumer verifies the manifest SIGNATURE before the
# checksums, so the runtime harness cells that run the REAL installer/core
# need a REAL channel signature (ephemeral keypair, never committed). Cells
# skip honestly when minisign is not on PATH; CI installs it.
# Importing _minisign_stub provisions a CLI-only stub minisign when no real
# one is installed (import side effect), so the signed-channel cells RUN
# instead of silently skipping. With a real minisign present (CI) they
# exercise the real Ed25519 round-trip; with the stub they exercise the
# installer's ordering and fail-closed behavior. The stub never proves the
# crypto.
import _minisign_stub  # noqa: F401


def _sign_fixture_manifest(channel: Path, tmp_path: Path) -> None:
    """Sign the channel SHA256SUMS with an EPHEMERAL minisign keypair and
    record the public key at ``channel/.test-pubkey`` for the harness env
    (MINISIGN_PUBKEY seam). The keypair is a temp file — never committed."""
    key = tmp_path / "fixture.key"
    pub = tmp_path / "fixture.pub"
    subprocess.run(
        ["minisign", "-G", "-W", "-s", str(key), "-p", str(pub)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    subprocess.run(
        ["minisign", "-Sm", str(channel / "SHA256SUMS"), "-s", str(key)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    (channel / ".test-pubkey").write_text(
        pub.read_text(encoding="utf-8").strip().splitlines()[-1], encoding="utf-8"
    )


def _host_uv_target() -> str:
    """The uv release target the installer resolves on THIS host.

    Mirrors ``scripts/install-demiurgos.sh::uv_target`` (glibc Linux/macOS —
    the fixture cells never run on musl; Alpine is the separate docker job).
    The stub uv archive the fixture publishes must carry this exact target or
    the installer cannot find it and fails fast.
    """
    machine = platform.machine().lower()
    arch = "x86_64" if machine in ("x86_64", "amd64") else "aarch64"
    if platform.system() == "Darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def _build_fixture_channel(
    tmp_path: Path, *, with_minisig: bool = True, wrong_payload_sha: str | None = None,
    include_core: bool = False,
) -> tuple[Path, str, str]:
    """Build a local file:// release channel.

    Contents: ``latest`` (plain text version), ``version.json``,
    ``SHA256SUMS`` (+ ``.minisig`` when requested), the payload archive and a
    STUB ``uv`` archive. The payload is the derived allow-list
    (``payload_manifest.json``) plus the real launcher, a minimal
    ``frontend/dist`` and the requirements files — the release-artifact shape
    (S5-1). When ``include_core`` is set (S4 bootstrap harness), the channel
    also hosts the versioned installer core
    (``scripts/install-demiurgos.sh`` + ``scripts/lib/verify_checksum.sh``)
    with their own ``SHA256SUMS`` entries. Returns ``(channel, uv_sha256,
    version)``.
    """
    channel = tmp_path / "channel"
    channel.mkdir()
    version = "0.9.0-test"
    (channel / "latest").write_text(version + "\n", encoding="utf-8")

    if include_core:
        for rel in ("scripts/install-demiurgos.sh", "scripts/lib/verify_checksum.sh"):
            dst = channel / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_REPO_ROOT / rel, dst)

    # Payload tree = manifest allow-list + launcher + minimal dist + reqs.
    manifest = json.loads(
        (_REPO_ROOT / "payload_manifest.json").read_text(encoding="utf-8")
    )
    payload_root = tmp_path / "payload-src"
    for rel in manifest["payload"]:
        src = _REPO_ROOT / rel
        if src.is_file():
            dst = payload_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    launcher_src = _REPO_ROOT / "scripts" / "start-demiurgos.sh"
    dst = payload_root / "scripts" / "start-demiurgos.sh"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(launcher_src, dst)
    dst.chmod(0o755)
    dist = payload_root / "frontend" / "dist"
    dist.mkdir(parents=True, exist_ok=True)  # manifest may already carry dist entries
    (dist / "index.html").write_text(
        "<!doctype html><html><body>fixture dist</body></html>", encoding="utf-8"
    )
    for name in ("requirements.lock", "requirements-optional.txt"):
        shutil.copy2(_REPO_ROOT / name, payload_root / name)

    payload_name = f"demiurgos-app-{version}.tar.gz"
    payload_tar = channel / payload_name
    with tarfile.open(payload_tar, "w:gz") as tf:
        tf.add(payload_root, arcname=".")
    payload_sha = hashlib.sha256(payload_tar.read_bytes()).hexdigest()

    # Stub uv archive: uv-<target>-<UV_VERSION>.tar.gz containing `uv`. The
    # target MUST match what scripts/install-demiurgos.sh::uv_target resolves
    # on THIS host (a hardcoded x86_64-linux target made every aarch64/macOS
    # fixture cell fail with "uv provider unreachable").
    uv_dir = tmp_path / "stub-uv"
    uv_dir.mkdir()
    stub = uv_dir / "uv"
    stub.write_text(_UV_STUB_SH, encoding="utf-8")
    stub.chmod(0o755)
    uv_archive = (
        channel / "uv" / f"uv-{_host_uv_target()}-{STUB_UV_VERSION}.tar.gz"
    )
    uv_archive.parent.mkdir()
    with tarfile.open(uv_archive, "w:gz") as tf:
        tf.add(stub, arcname="uv")
    uv_sha = hashlib.sha256(uv_archive.read_bytes()).hexdigest()

    version_json = {
        "version": version,
        "artifacts": {
            "posix": payload_name,
            "windows": "demiurgos-app-windows.zip",
        },
        "sha256": {"posix": payload_sha},
        "floors": {"macos": 13, "glibc": "2.28", "windows": 10},
    }
    (channel / "version.json").write_text(
        json.dumps(version_json, indent=2) + "\n", encoding="utf-8"
    )
    if with_minisig:
        (channel / "SHA256SUMS.minisig").write_text("untrusted-test-minisig\n")
    declared_sha = payload_sha if wrong_payload_sha is None else wrong_payload_sha
    sums_lines = [f"{declared_sha}  {payload_name}\n"]
    if include_core:
        for rel in ("scripts/install-demiurgos.sh", "scripts/lib/verify_checksum.sh"):
            sums_lines.append(
                f"{hashlib.sha256((channel / rel).read_bytes()).hexdigest()}  {rel}\n"
            )
    (channel / "SHA256SUMS").write_text("".join(sums_lines), encoding="utf-8")
    if with_minisig and shutil.which("minisign") is not None:
        # S5b: replace the placeholder minisig with a REAL signature so the
        # runtime cells pass the consumer's signature gate (task 8.4).
        _sign_fixture_manifest(channel, tmp_path)
    return channel, uv_sha, version


def _installer_env(
    tmp_path: Path, channel: Path, uv_sha: str, install_root: Path, *,
    fail_pip: bool = False,
) -> dict[str, str]:
    """Env for one installer run: file:// channel, stub python/log, tmp
    XDG_CONFIG_HOME/HOME/RUNTIME so the REAL ~/.demiurgos and the real
    data-root pointer are never touched. conftest's hermetic env vars are
    deliberately NOT inherited — the installer must bootstrap its own pointer."""
    env = {
        "DEMIURGOS_URL_BASE": f"file://{channel}",
        "DEMIURGOS_HOME": str(install_root),
        "DEMIURGOS_UV_SHA256": uv_sha,
        "UV_VERSION": STUB_UV_VERSION,
        "DEMIURGOS_STUB_PYTHON": str(_REPO_ROOT / ".venv" / "bin" / "python"),
        "DEMIURGOS_STUB_LOG": str(tmp_path / "uv-stub.log"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "HOME": str(tmp_path / "home"),
        "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
        "DEMIURGOS_NO_BROWSER": "1",
        "DEMIURGOS_LANGUAGE": "en",
        "PATH": f"{NOOP_BROWSER_BIN}:{os.environ.get('PATH', '/usr/bin:/bin')}",
    }
    if fail_pip:
        env["DEMIURGOS_STUB_FAIL_PIP"] = "1"
    # S5b: the consumer verifies the manifest signature via the MINISIGN_PUBKEY
    # seam; pass the fixture's ephemeral public key when the channel is signed.
    pubkey_file = channel / ".test-pubkey"
    if pubkey_file.is_file():
        env["MINISIGN_PUBKEY"] = pubkey_file.read_text(encoding="utf-8").strip()
    for key in ("DEMIURGOS_DATA_ROOT", "DEMIURGOS_FRONTEND_DIST"):
        env.pop(key, None)
    return env


def _run_installer(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALLER)],
        env=env, capture_output=True, text=True, timeout=240,
    )


def _boot_launcher(tmp_path: Path, env: dict[str, str], install_root: Path) -> int:
    """Start the installed launcher headless and return the API port."""
    _require_noop_stub()
    api_port = _free_port()
    gateway_port = _free_port()
    env = {**env, "DEMIURGOS_API_PORT": str(api_port),
           "DEMIURGOS_GATEWAY_PORT": str(gateway_port)}
    launcher = install_root / "current" / "scripts" / "start-demiurgos.sh"
    start = subprocess.run(
        ["bash", str(launcher), "start"],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert start.returncode == 0, start.stderr
    return api_port


def _fetch(url: str) -> int:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status


def _wait_health(port: int, polls: int = 40) -> None:
    for _ in range(polls):
        try:
            if _fetch(f"http://127.0.0.1:{port}/health") == 200:
                return
        except OSError:
            pass
        time.sleep(0.5)
    raise AssertionError(f"/health never returned 200 on port {port}")


def _read_pointer(config_dir: Path):
    """Python-side read of the pointer bash wrote (task 4.9)."""
    import data_root  # conftest puts _WIKI on sys.path

    return data_root.read_pointer(config_dir=config_dir)


@POSIX_RUNNER
class TestFixtureChannelInstall:
    def test_install_then_boot_serves_health_and_root(self, tmp_path: Path):
        channel, uv_sha, version = _build_fixture_channel(tmp_path)
        install_root = tmp_path / "install"
        env = _installer_env(tmp_path, channel, uv_sha, install_root)

        install = _run_installer(env)
        assert install.returncode == 0, install.stdout + install.stderr

        # Installed layout from the frozen contract (S0-C).
        assert (install_root / "app" / version).is_dir()
        assert (install_root / "current").is_symlink()
        assert (install_root / "current").resolve() == (
            install_root / "app" / version
        ).resolve()
        assert (install_root / "bin" / "uv").is_file()
        assert (install_root / "app" / version / ".venv" / "bin" / "python").exists()

        # Slice 2b: install-root channel.json records the validated channel
        # base with the runtime schema (design S2-b).
        channel_json = install_root / "channel.json"
        assert channel_json.is_file()
        record = json.loads(channel_json.read_text(encoding="utf-8"))
        assert record["schema_version"] == 1
        assert record["url_base"] == f"file://{channel}"

        # Stub uv recorded the mandatory flags (hash-locked wheels-only).
        log = (tmp_path / "uv-stub.log").read_text(encoding="utf-8")
        assert "--require-hashes" in log
        assert "--only-binary=:all:" in log
        assert "--require-hashes" in log and "requirements.lock" in log

        # Boot the installed app headless and probe /health + /.
        api_port = _boot_launcher(tmp_path, env, install_root)
        try:
            _wait_health(api_port)
            assert _fetch(f"http://127.0.0.1:{api_port}/health") == 200
            assert _fetch(f"http://127.0.0.1:{api_port}/") == 200
        finally:
            _stop_and_assert_clean(
                install_root / "current" / "scripts" / "start-demiurgos.sh",
                env, api_port,
            )

    def test_rerun_is_idempotent_single_env(self, tmp_path: Path):
        channel, uv_sha, version = _build_fixture_channel(tmp_path)
        install_root = tmp_path / "install"
        env = _installer_env(tmp_path, channel, uv_sha, install_root)

        first = _run_installer(env)
        assert first.returncode == 0, first.stdout + first.stderr
        pointer_before = _read_pointer(
            Path(env["XDG_CONFIG_HOME"]) / "demiurgos"
        )
        env_before = (pointer_before / ".env").read_bytes()

        second = _run_installer(env)
        assert second.returncode == 0, second.stdout + second.stderr

        # One environment: exactly one app/<version>, one current.
        app_dirs = [p.name for p in (install_root / "app").iterdir()]
        assert app_dirs == [version]
        # Pointer and .env are bootstrap-only: preserved byte-for-byte.
        pointer_after = _read_pointer(Path(env["XDG_CONFIG_HOME"]) / "demiurgos")
        assert pointer_after == pointer_before
        assert (pointer_after / ".env").read_bytes() == env_before

        # channel.json is persisted on first install and survives the re-run.
        channel_json = install_root / "channel.json"
        assert channel_json.is_file()
        record = json.loads(channel_json.read_text(encoding="utf-8"))
        assert record["schema_version"] == 1
        assert record["url_base"] == f"file://{channel}"

        # Re-run still boots (one instance).
        api_port = _boot_launcher(tmp_path, env, install_root)
        try:
            _wait_health(api_port)
            assert _fetch(f"http://127.0.0.1:{api_port}/health") == 200
        finally:
            _stop_and_assert_clean(
                install_root / "current" / "scripts" / "start-demiurgos.sh",
                env, api_port,
            )


@POSIX_RUNNER
class TestChecksumMismatchAborts:
    def test_wrong_sha256_aborts_with_no_runnable_state(self, tmp_path: Path):
        channel, uv_sha, _version = _build_fixture_channel(
            tmp_path, wrong_payload_sha="0" * 64
        )
        install_root = tmp_path / "install"
        env = _installer_env(tmp_path, channel, uv_sha, install_root)

        result = _run_installer(env)
        assert result.returncode != 0
        assert "checksum" in (result.stdout + result.stderr).lower()

        # No runnable state: no app/, no current, staging cleaned up.
        assert not (install_root / "current").exists()
        assert not (install_root / "app").exists()
        staging = install_root / ".staging"
        if staging.exists():
            assert list(staging.iterdir()) == []


@POSIX_RUNNER
class TestM3Coexistence:
    def test_existing_repo_clone_and_pointer_preserved(self, tmp_path: Path):
        """M3: an existing ~/.demiurgos/repo CLI clone is neither clobbered nor
        adopted as the app root; a pointer pointing at the clone is preserved."""
        channel, uv_sha, version = _build_fixture_channel(tmp_path)
        install_root = tmp_path / "install"

        # Simulate the pre-existing CLI stack (D5): repo/ clone with a marker.
        repo_clone = install_root / "repo"
        repo_clone.mkdir(parents=True)
        marker = repo_clone / "README.md"
        marker.write_text("cli clone marker\n", encoding="utf-8")

        # Pre-existing pointer pointing AT the clone (author continuity).
        config_dir = tmp_path / "config" / "demiurgos"
        config_dir.mkdir(parents=True)
        pointer = config_dir / POINTER_NAME
        pointer_before = (
            "{\n"
            '  "schema_version": 1,\n'
            f'  "data_root": "{repo_clone}",\n'
            '  "updated_at": "2026-09-30T00:00:00Z"\n'
            "}\n"
        )
        pointer.write_text(pointer_before, encoding="utf-8")
        env = _installer_env(tmp_path, channel, uv_sha, install_root)

        result = _run_installer(env)
        assert result.returncode == 0, result.stdout + result.stderr

        # Clone is intact and untouched.
        assert marker.read_text(encoding="utf-8") == "cli clone marker\n"
        # Pointer is preserved byte-for-byte (never re-oriented).
        assert pointer.read_text(encoding="utf-8") == pointer_before
        # The app root is app/<version>, NOT the clone.
        assert (install_root / "current").resolve() == (
            install_root / "app" / version
        ).resolve()
        assert (install_root / "current" / "src").exists()


@POSIX_RUNNER
class TestPointerAndEnvSeed:
    def test_python_reads_what_bash_wrote(self, tmp_path: Path):
        """Task 4.9: the pointer written by the installer is byte-compatible
        with data_root.py — Python reads back exactly the bootstrapped root."""
        channel, uv_sha, _version = _build_fixture_channel(tmp_path)
        install_root = tmp_path / "install"
        env = _installer_env(tmp_path, channel, uv_sha, install_root)

        result = _run_installer(env)
        assert result.returncode == 0, result.stdout + result.stderr

        data_root = _read_pointer(Path(env["XDG_CONFIG_HOME"]) / "demiurgos")
        assert data_root == (install_root / "data").resolve()

        env_file = data_root / ".env"
        content = env_file.read_text(encoding="utf-8")
        assert "DEMIURGOS_AUTH_MODE=local-dev" in content
        assert "DEMIURGOS_LANGUAGE=en" in content
        # Never shipped inside the payload: the seeded .env lives only in the
        # data root, not in the staged app tree.
        assert list((install_root / "app").rglob(".env")) == []

    def test_existing_env_preserved_untouched(self, tmp_path: Path):
        """S0-A/S3-7: an existing data-root .env is preserved byte-for-byte."""
        channel, uv_sha, _version = _build_fixture_channel(tmp_path)
        install_root = tmp_path / "install"
        data_root = tmp_path / "existing-data"
        data_root.mkdir()
        env_file = data_root / ".env"
        original = "DEMIURGOS_AUTH_MODE=credentials\nDEMIURGOS_LANGUAGE=es\n"
        env_file.write_text(original, encoding="utf-8")

        # The data root already exists via env override -> no pointer write,
        # and the existing .env is never re-seeded.
        env = _installer_env(tmp_path, channel, uv_sha, install_root)
        env["DEMIURGOS_DATA_ROOT"] = str(data_root)
        env.pop("XDG_CONFIG_HOME", None)

        result = _run_installer(env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert env_file.read_text(encoding="utf-8") == original
        assert not (tmp_path / "config").exists() or not list(
            (tmp_path / "config").rglob(POINTER_NAME)
        )


@POSIX_RUNNER
class TestMandatoryInstallFailure:
    def test_pip_failure_leaves_no_runnable_state(self, tmp_path: Path):
        channel, uv_sha, _version = _build_fixture_channel(tmp_path)
        install_root = tmp_path / "install"
        env = _installer_env(tmp_path, channel, uv_sha, install_root, fail_pip=True)

        result = _run_installer(env)
        assert result.returncode != 0
        assert not (install_root / "current").exists()
        assert not (install_root / "app").exists()
        staging = install_root / ".staging"
        if staging.exists():
            assert list(staging.iterdir()) == []


# ---------------------------------------------------------------------------
# 5.1 — Windows parity: contract text assertions over the .ps1 core + lib
# ---------------------------------------------------------------------------
# Mirrors the 4.1 contract for scripts/install-demiurgos.ps1 and
# scripts/lib/verify_checksum.ps1 (task 5.1; design S3-1..S3-7 parity + S2-8).
# Text scans run on every host; the runtime cells at the bottom are
# Windows-runner-only and skipif here (reported not-run on this Linux host).

PS_RUNNER = pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows runner harness needs powershell.exe (NOT run on this Linux host)",
)


class TestWindowsNoPrivateCloneOrNpm:
    def test_ps1_no_git_at_all(self):
        text = _text(PS_INSTALLER)
        assert "git" not in text

    def test_ps1_no_npm(self):
        text = _text(PS_INSTALLER)
        assert "npm" not in text

    def test_ps1_no_private_repo_url(self):
        """D1 parity: the Windows core never embeds the private owner or any
        github URL (the leak lives at install.sh:27, S4 owns it)."""
        text = _text(PS_INSTALLER) + _text(PS_VERIFY_LIB)
        assert "maar1223" not in text
        assert "github.com" not in text

    def test_ps1_no_elevation(self):
        """Spec 'No elevated privileges': no RunAs, no UAC, no admin-gated
        operation — the core installs into user-writable locations only."""
        text = _text(PS_INSTALLER)
        assert "RunAs" not in text
        assert "UAC" not in text

    def test_ps1_no_hardcoded_author_paths(self):
        text = _text(PS_INSTALLER) + _text(PS_VERIFY_LIB)
        # The literals are assembled from parts on purpose: the repo-wide
        # secret scan treats the Windows drive+user-profile prefix as an
        # author path, so this file must not spell it out verbatim. Building
        # it from parts keeps the assertion identical while preserving FULL
        # scan coverage of this file: a real author path pasted here would
        # still fail the scan.
        assert "H:" + "\\" not in text
        assert "C:" + "\\Users" not in text


class TestWindowsWheelsOnlyHashLocked:
    def test_ps1_only_binary_all_present(self):
        assert "--only-binary=:all:" in _text(PS_INSTALLER)

    def test_ps1_require_hashes_present(self):
        assert "--require-hashes" in _text(PS_INSTALLER)

    def test_ps1_mandatory_pip_line_uses_both_flags(self):
        text = _text(PS_INSTALLER)
        line = next(
            ln for ln in text.splitlines()
            if "uvBin pip install" in ln and "--require-hashes" in ln
        )
        assert "--only-binary=:all:" in line

    def test_ps1_core_verifies_the_manifest_signature_before_checksums(self):
        """S5b (task 8.4) parity: the POSIX core verifies the channel manifest
        signature BEFORE trusting any checksum. The Windows core must do the
        same - otherwise a same-channel unsigned/tampered manifest is
        tamper-together on Windows only (gatekeeper finding #2)."""
        core = _text(PS_INSTALLER)
        lib = _text(PS_VERIFY_LIB)
        assert "Test-Minisig" in lib
        assert "MINISIGN_PUBKEY" in lib
        assert "Test-Minisig" in core
        # Ordering: the signature gate runs before the first checksum check.
        assert core.index("Test-Minisig") < core.index("Verify-Sha256")


class TestWindowsChecksumBeforeStaging:
    def test_ps1_payload_verify_precedes_extraction(self):
        """The payload archive is verified against SHA256SUMS BEFORE it is
        extracted into the staging tree (spec 'Checksum mismatch')."""
        text = _text(PS_INSTALLER)
        verify_at = text.index("Verify-Sha256 -FilePath $payloadFile")
        extract_at = text.index("Expand-Archive -LiteralPath $payloadFile")
        assert verify_at < extract_at

    def test_ps1_mismatch_aborts_with_clean_rerun_path(self):
        text = _text(PS_INSTALLER)
        assert "checksum" in text
        assert "re-run" in text


class TestWindowsAtomicSameFsStaging:
    def test_ps1_staging_under_install_root(self):
        text = _text(PS_INSTALLER)
        assert 'Join-Path $installRoot ".staging"' in text

    def test_ps1_no_temp_dirs(self):
        """Staging is on the SAME filesystem as the install root — never a
        temp dir on another FS (design S3-5)."""
        text = _text(PS_INSTALLER)
        assert "/tmp" not in text
        assert "$env:TEMP" not in text
        assert "$env:TMP" not in text

    def test_ps1_atomic_move_and_junction_flip(self):
        """S0-C: Windows `current` is a JUNCTION (not a symlink), flipped
        after a same-FS rename — never a cross-volume copy."""
        text = _text(PS_INSTALLER)
        assert 'Move-Item -LiteralPath $stageDir -Destination $target' in text
        assert "New-Item -ItemType Junction" in text


class TestWindowsPointerBootstrapOnly:
    def test_ps1_pointer_guarded_by_env_and_pointer(self):
        """Pointer is written ONLY when neither the env override nor an
        existing pointer is present; an existing pointer is never re-oriented
        (spec 'Existing data root preserved', design S3-7)."""
        text = _text(PS_INSTALLER)
        assert "DEMIURGOS_DATA_ROOT" in text
        assert "$pointerFile" in text
        assert "data-root.json" in text

    def test_ps1_env_seed_guarded_by_absence(self):
        text = _text(PS_INSTALLER)
        assert 'Test-Path -LiteralPath $envFile' in text
        assert "DEMIURGOS_AUTH_MODE=local-dev" in text

    def test_ps1_pointer_format_byte_compatible_with_data_root(self):
        """The pointer record MUST be the data_root.py JSON shape
        (schema_version 1, data_root, updated_at)."""
        text = _text(PS_INSTALLER)
        assert '"schema_version": 1' in text
        assert '"data_root"' in text
        assert '"updated_at"' in text

    def test_ps1_seed_only_seam_present(self):
        """The DEMIURGOS_SEED_ONLY env seam (S0-A) is mirrored: seed-only runs
        ONLY the data-root bootstrap-once + .env seed, never a download."""
        text = _text(PS_INSTALLER)
        assert "DEMIURGOS_SEED_ONLY" in text


class TestWindowsOptionalExtrasBestEffort:
    def test_ps1_optional_install_non_fatal(self):
        text = _text(PS_INSTALLER)
        assert "requirements-optional" in text
        assert "Warn" in text


class TestWindowsNoArbitraryPayloadExecution:
    def test_ps1_never_executes_payload_files(self):
        """Threat-matrix 'Documentation-like paths' (execution half, Windows):
        the installer only runs the verified uv binary and standard cmdlets;
        it never dot-sources, Invoke-Expression's or runs anything extracted
        from the payload."""
        text = _text(PS_INSTALLER)
        assert "Invoke-Expression" not in text
        assert "& $stageDir" not in text
        assert "& $payloadFile" not in text


class TestWindowsUvProvisioning:
    def test_ps1_uv_pinned_and_checksum_verified(self):
        text = _text(PS_INSTALLER)
        assert "UV_VERSION" in text
        assert "Verify-Sha256 -FilePath $archive" in text
        assert 'Join-Path $installRoot "bin"' in text

    def test_ps1_uv_python_and_venv_commands(self):
        text = _text(PS_INSTALLER)
        assert "UV_PYTHON_INSTALL_DIR" in text
        assert "venv --python 3.12" in text
        assert "python install 3.12" in text


class TestWindowsSupportMatrixNarrowed3579:
    def test_ps1_unsupported_arch_fails_fast_with_manual_alternative(self):
        """Decision #3579: Windows 10/11 x86_64 ONLY — ARM/32-bit Windows fail
        fast with the documented manual-install alternative."""
        text = _text(PS_INSTALLER)
        assert "not supported" in text
        assert "x86_64" in text
        assert "manual" in text

    def test_ps1_windows_below_floor_fails_fast_naming_version(self):
        text = _text(PS_INSTALLER)
        assert "Windows 10 or newer is required" in text

    def test_ps1_longpaths_floor(self):
        text = _text(PS_INSTALLER)
        assert "LongPathsEnabled" in text

    def test_ps1_before_s5_gate_referenced_without_rephrasing(self):
        """D3: single authoritative gate statement — later references point to
        (D3) without restating the timing."""
        text = _text(PS_INSTALLER)
        assert "(D3)" in text


class TestWindowsPowerShell51Contract:
    def test_ps1_files_are_ascii_only(self):
        """S2-8: PS 5.1 mis-decodes BOM-less UTF-8; ASCII-only is the rule."""
        for path in (PS_INSTALLER, PS_VERIFY_LIB):
            path.read_bytes().decode("ascii")  # raises UnicodeDecodeError

    def test_ps1_files_avoid_pwsh_only_isms(self):
        """$IsWindows / $IsLinux are pwsh 6+ automatic variables; PS 5.1 has
        no such variables, so their use would break the 5.1 target."""
        for path in (PS_INSTALLER, PS_VERIFY_LIB):
            text = _text(path)
            assert "$IsWindows" not in text
            assert "$IsLinux" not in text


class TestWindowsVerifyChecksumLibrary:
    def test_ps1_branch_order_native_then_certutil_then_uv(self):
        """S3-2 parity: Get-FileHash (native PS 5.1) -> certutil (legacy
        Windows) -> bundled-Python hashlib via `uv run python -c` (never
        system Python)."""
        text = _text(PS_VERIFY_LIB)
        assert text.index("Get-FileHash") < text.index("certutil")
        assert text.index("certutil") < text.index("run python")

    def test_ps1_no_system_python_in_lib(self):
        text = _text(PS_VERIFY_LIB)
        assert "python3" not in text
        assert "python.exe" not in text
        assert "Get-Command python" not in text


# ---------------------------------------------------------------------------
# 6.1 — S4 public bootstraps (install.sh + install.ps1) contract text
# ---------------------------------------------------------------------------
# The public one-liners are thin delegators (design S4-1..S4-4): they fetch
# the versioned installer core from the channel, verify it, then execute it.
# They must never carry the private repo URL (D1 — the leak lived at
# install.sh:27), never request elevation, and the Windows one must be
# `irm | iex`-safe (no script-file assumptions, TLS 1.2 before any download).


class TestPublicBootstrapsS4:
    # --- POSIX bootstrap (install.sh) --------------------------------------

    def test_posix_bootstrap_delegates_to_the_core(self):
        """The default path passes the pinned version, install root and channel
        base through to the versioned core (env passthrough)."""
        text = _text(INSTALL_SH)
        assert "install-demiurgos.sh" in text
        assert "DEMIURGOS_VERSION" in text
        assert "DEMIURGOS_HOME" in text
        assert "DEMIURGOS_URL_BASE" in text

    def test_posix_bootstrap_has_no_private_repo_url(self):
        """D1/S4-4: the private address never appears verbatim — the owner and
        repo names are built from parts at runtime."""
        text = _text(INSTALL_SH)
        assert "maar1223" not in text
        assert "Demiurgos.git" not in text

    def test_posix_bootstrap_no_sudo(self):
        assert "sudo" not in _text(INSTALL_SH)

    def test_posix_bootstrap_no_npm(self):
        assert "npm" not in _text(INSTALL_SH)

    def test_posix_bootstrap_default_path_never_clones_or_npms(self):
        """The web-app default path is clone-free: the only `git` in the file
        lives inside the CLI-stack opt-in (install_demiurgos), never in the
        delegating bootstrap_web_app body."""
        text = _text(INSTALL_SH)
        body = text.split("bootstrap_web_app() {", 1)[1].split("\n}\n", 1)[0]
        assert "git" not in body
        assert "npm" not in body
        assert "sudo" not in body

    def test_posix_bootstrap_cli_stack_is_explicit_opt_in(self):
        text = _text(INSTALL_SH)
        assert "--with-cli-stack" in text
        assert "DEMIURGOS_WITH_CLI_STACK" in text
        assert "main_cli_stack" in text

    def test_posix_bootstrap_hardened_curl_flags(self):
        """S4-3: https-only, retries, timeout and silent-fail-on-error."""
        text = _text(INSTALL_SH)
        assert "--proto '=https'" in text
        assert "--retry" in text
        assert "--max-time" in text
        assert "-fsSL" in text

    def test_posix_bootstrap_download_then_verify_then_execute(self):
        """The core is verified against SHA256SUMS BEFORE it is executed."""
        text = _text(INSTALL_SH)
        assert "verify_sha256" in text
        assert "SHA256SUMS" in text
        # The download step precedes the execution step in the default path.
        assert (
            text.index("Downloading the installer core")
            < text.index("bash \"$core_dir/install-demiurgos.sh\"")
        )

    # --- Windows bootstrap (install.ps1) -----------------------------------

    def test_ps1_bootstrap_is_iex_safe(self):
        """S4-2: under `irm | iex` there is no script file — $PSScriptRoot and
        $MyInvocation.MyCommand.Path are both NULL; the bootstrap must not use
        them and must not declare a param() block (unsupported under iex)."""
        text = _text(INSTALL_PS1)
        assert "$PSScriptRoot" not in text
        assert "$MyInvocation.MyCommand.Path" not in text
        assert "param(" not in text

    def test_ps1_bootstrap_tls12_before_any_download(self):
        """S4-3: PS 5.1 defaults to TLS 1.0/1.1; the SecurityProtocol line must
        precede the first download call."""
        text = _text(INSTALL_PS1)
        assert "SecurityProtocol" in text
        assert "Invoke-WebRequest" in text
        assert text.index("SecurityProtocol") < text.index("Invoke-WebRequest")

    def test_ps1_bootstrap_executes_core_with_bypass_file(self):
        text = _text(INSTALL_PS1)
        assert "-ExecutionPolicy Bypass -File" in text
        assert "install-demiurgos.ps1" in text

    def test_ps1_bootstrap_computes_root_from_environment(self):
        """S4-2: %LOCALAPPDATA%\\Demiurgos default; env-only paths."""
        text = _text(INSTALL_PS1)
        assert "LOCALAPPDATA" in text
        assert "Join-Path $env:LOCALAPPDATA \"Demiurgos\"" in text
        assert "GetTempPath" in text

    def test_ps1_bootstrap_delegates_with_pinned_version(self):
        text = _text(INSTALL_PS1)
        assert "DEMIURGOS_VERSION" in text
        assert "DEMIURGOS_HOME" in text
        assert "DEMIURGOS_URL_BASE" in text

    def test_ps1_bootstrap_no_elevation(self):
        text = _text(INSTALL_PS1)
        assert "RunAs" not in text
        assert "Start-Process" not in text

    def test_ps1_bootstrap_has_no_private_repo_url(self):
        text = _text(INSTALL_PS1)
        assert "maar1223" not in text
        assert "Demiurgos.git" not in text

    def test_ps1_bootstrap_is_ascii_only(self):
        """S2-8: PS 5.1 mis-decodes BOM-less UTF-8; ASCII-only is the rule."""
        INSTALL_PS1.read_bytes().decode("ascii")  # raises UnicodeDecodeError

    def test_ps1_bootstrap_no_author_paths(self):
        """Scanner-safe: no hardcoded Windows user paths in a public artifact.
        The literals are built from parts so this negative assertion does not
        itself match the scanner's author-path rule (secret_scan.sh is frozen
        for this slice, so no allowlist entry is added)."""
        text = _text(INSTALL_PS1)
        assert "C:" + chr(92) + "Users" not in text
        assert "H:" + chr(92) not in text

    # --- Windows CLI-stack overlay (S4 follow-up) --------------------------

    def test_ps1_bootstrap_cli_stack_is_explicit_opt_in(self):
        """The historical Windows installer is preserved behind an explicit
        opt-in, mirroring `install.sh --with-cli-stack`; the iex-safe default
        path never runs it (it delegates to the versioned core instead)."""
        text = _text(INSTALL_PS1)
        assert "-WithCliStack" in text
        assert "DEMIURGOS_WITH_CLI_STACK" in text
        assert "install-cli-stack.ps1" in text

    def test_ps1_cli_stack_overlay_is_tracked_and_ascii_only(self):
        assert PS_CLI_OVERLAY.is_file()
        PS_CLI_OVERLAY.read_bytes().decode("ascii")  # raises UnicodeDecodeError

    def test_ps1_cli_stack_overlay_is_file_context_only(self):
        """The overlay is always run with -File, so it MAY use the script-file
        location; the iex-safe public bootstrap must not (S4-2)."""
        assert "$PSScriptRoot" in _text(PS_CLI_OVERLAY)
        assert "$PSScriptRoot" not in _text(INSTALL_PS1)

    def test_ps1_cli_stack_overlay_has_no_private_url_or_elevation(self):
        text = _text(PS_CLI_OVERLAY)
        assert "maar1223" not in text
        assert "Demiurgos.git" not in text
        assert "RunAs" not in text
        assert "Start-Process" not in text
        assert "sudo" not in text


# ---------------------------------------------------------------------------
# 5.4 — Windows-runner fixture harness (file:// + stub uv.ps1 + real venv)
# ---------------------------------------------------------------------------
# Cells mirror the S3a fixture harness (task 4.11) for the Windows core: a
# local file:// channel with a STUB uv.ps1 and the repository venv python
# stands in for the real toolchain (real uv/CPython/wheels download is
# CI-owned, S5a — reported not-run here). They need powershell.exe 5.1, a
# Windows-hosted repo venv (.venv\Scripts\python.exe) and Defender semantics,
# so every cell is marked skipif on this Linux host and reported not-run; the
# S3b/CI windows-latest matrix is the runtime proof.

_UV_STUB_PS1 = r"""# Stub uv for the S3b Windows fixture harness (task 5.4). Emulates the
# commands the installer uses and RECORDS its argv so the harness can assert
# the exact flags. The "python" it installs is the repository venv
# interpreter (DEMIURGOS_STUB_PYTHON), so the staged app genuinely boots.
# Real uv/CPython/wheels download is CI-owned (S5a) - never run here.
$cmd = $args[0]
("uv " + ($args -join " ")) | Out-File -LiteralPath $env:DEMIURGOS_STUB_LOG -Append -Encoding ascii
switch ($cmd) {
  "python" {
    New-Item -ItemType Directory -Force -Path (Join-Path $env:UV_PYTHON_INSTALL_DIR "bin") | Out-Null
    Copy-Item -LiteralPath $env:DEMIURGOS_STUB_PYTHON -Destination (Join-Path $env:UV_PYTHON_INSTALL_DIR "bin\python.exe") -Force
    exit 0
  }
  "venv" {
    # uv venv --python 3.12 <dest> -> create a REAL venv from the managed
    # python with system-site-packages so the staged app genuinely boots; the
    # .pth makes the repo venv's site-packages visible to the staged venv
    # regardless of APPDATA isolation (real uv pip install puts wheels into
    # the venv itself - CI-owned, not-run here).
    $dest = $null
    foreach ($a in $args[1..($args.Length - 1)]) {
      if ($a -notlike "-*" -and $a -ne "3.12") { $dest = $a }
    }
    if (-not $dest) { Write-Error "stub uv: venv missing dest"; exit 2 }
    & $env:DEMIURGOS_STUB_PYTHON -m venv --system-site-packages $dest
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $repoVenv = Split-Path -Parent (Split-Path -Parent $env:DEMIURGOS_STUB_PYTHON)
    $repoSite = Join-Path $repoVenv "Lib\site-packages"
    if (Test-Path -LiteralPath $repoSite) {
      $pthDir = Join-Path $dest "Lib\site-packages"
      New-Item -ItemType Directory -Force -Path $pthDir | Out-Null
      Set-Content -LiteralPath (Join-Path $pthDir "demiurgos-repo.pth") -Value $repoSite -Encoding ASCII
    } else {
      Write-Warning "stub uv: repo site-packages not found at $repoSite"
    }
    exit 0
  }
  "pip" {
    if ($env:DEMIURGOS_STUB_FAIL_PIP -eq "1") { Write-Error "stub uv: pip install failed (stub)"; exit 1 }
    exit 0
  }
  "run" {
    # uv run python <args...> -> drop the leading "python", delegate to the
    # stub interpreter (never system python).
    if ($args.Length -ge 2 -and $args[1] -eq "python") {
      & $env:DEMIURGOS_STUB_PYTHON $args[2..($args.Length - 1)]
    } else {
      & $env:DEMIURGOS_STUB_PYTHON $args[1..($args.Length - 1)]
    }
    exit $LASTEXITCODE
  }
  default {
    Write-Error "stub uv: unknown command: $cmd"
    exit 2
  }
}
"""


def _build_windows_fixture_channel(
    tmp_path: Path, *, wrong_payload_sha: str | None = None,
    include_core: bool = False,
) -> tuple[Path, str, str]:
    r"""Build a local file:// release channel for the Windows core.

    Contents: ``latest``, ``version.json``, ``SHA256SUMS`` (+ ``.minisig``),
    a .zip payload (manifest allow-list + the PS launcher at the frozen
    ``scripts\start-demiurgos.ps1`` path + a minimal ``frontend/dist`` + the
    requirements files) and a STUB ``uv.ps1`` archive for
    ``x86_64-pc-windows-msvc``. When ``include_core`` is set (S4 bootstrap
    harness), the channel also hosts the Windows installer core
    (``scripts\install-demiurgos.ps1`` + ``scripts\lib\verify_checksum.ps1``)
    with their own ``SHA256SUMS`` entries. Returns ``(channel, uv_sha256,
    version)``.
    """
    channel = tmp_path / "channel"
    channel.mkdir()
    version = "0.9.0-test"
    (channel / "latest").write_text(version + "\n", encoding="utf-8")

    if include_core:
        for rel in (
            "scripts/install-demiurgos.ps1",
            "scripts/lib/verify_checksum.ps1",
        ):
            dst = channel / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_REPO_ROOT / rel, dst)

    manifest = json.loads(
        (_REPO_ROOT / "payload_manifest.json").read_text(encoding="utf-8")
    )
    payload_root = tmp_path / "payload-src"
    for rel in manifest["payload"]:
        src = _REPO_ROOT / rel
        if src.is_file():
            dst = payload_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    # Windows launcher at the frozen layout path (S0-C):
    # <current>\scripts\start-demiurgos.ps1.
    launcher_src = _REPO_ROOT / "start-demiurgos.ps1"
    dst = payload_root / "scripts" / "start-demiurgos.ps1"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(launcher_src, dst)
    dist = payload_root / "frontend" / "dist"
    dist.mkdir(parents=True, exist_ok=True)  # manifest may already carry dist entries
    (dist / "index.html").write_text(
        "<!doctype html><html><body>fixture dist</body></html>", encoding="utf-8"
    )
    for name in ("requirements.lock", "requirements-optional.txt"):
        shutil.copy2(_REPO_ROOT / name, payload_root / name)

    payload_name = f"demiurgos-app-{version}.zip"
    payload_zip = channel / payload_name
    with zipfile.ZipFile(payload_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in payload_root.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(payload_root).as_posix())
    payload_sha = hashlib.sha256(payload_zip.read_bytes()).hexdigest()

    # Stub uv archive: uv-<target>-<UV_VERSION>.zip containing uv.ps1.
    uv_dir = tmp_path / "stub-uv"
    uv_dir.mkdir()
    stub = uv_dir / "uv.ps1"
    stub.write_text(_UV_STUB_PS1, encoding="utf-8")
    uv_archive = (
        channel / "uv" / f"uv-x86_64-pc-windows-msvc-{STUB_UV_VERSION}.zip"
    )
    uv_archive.parent.mkdir()
    with zipfile.ZipFile(uv_archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(stub, "uv.ps1")
    uv_sha = hashlib.sha256(uv_archive.read_bytes()).hexdigest()

    version_json = {
        "version": version,
        "artifacts": {
            "posix": "demiurgos-app-posix.tar.gz",
            "windows": payload_name,
        },
        "sha256": {"posix": "0" * 64, "windows": payload_sha},
        "floors": {"macos": 13, "glibc": "2.28", "windows": 10},
    }
    (channel / "version.json").write_text(
        json.dumps(version_json, indent=2) + "\n", encoding="utf-8"
    )
    (channel / "SHA256SUMS.minisig").write_text("untrusted-test-minisig\n")
    declared_sha = payload_sha if wrong_payload_sha is None else wrong_payload_sha
    sums_lines = [f"{declared_sha}  {payload_name}\n"]
    if include_core:
        for rel in (
            "scripts/install-demiurgos.ps1",
            "scripts/lib/verify_checksum.ps1",
        ):
            sums_lines.append(
                f"{hashlib.sha256((channel / rel).read_bytes()).hexdigest()}  {rel}\n"
            )
    (channel / "SHA256SUMS").write_text("".join(sums_lines), encoding="utf-8")
    if shutil.which("minisign") is not None:
        # S5b: real signature so the Windows bootstrap cell passes install.ps1's
        # signature gate (task 8.4) on the Windows runner.
        _sign_fixture_manifest(channel, tmp_path)
    return channel, uv_sha, version


def _ps_installer_env(
    tmp_path: Path, channel: Path, uv_sha: str, install_root: Path, *,
    fail_pip: bool = False,
) -> dict[str, str]:
    """Env for one Windows installer run: file:// channel, stub uv log, tmp
    APPDATA/LOCALAPPDATA/USERPROFILE so the REAL %APPDATA% pointer and data
    root are never touched. The installer must bootstrap its own pointer
    (conftest's hermetic env vars are deliberately NOT inherited)."""
    env = {
        "DEMIURGOS_URL_BASE": f"file://{channel}",
        "DEMIURGOS_HOME": str(install_root),
        "DEMIURGOS_UV_SHA256": uv_sha,
        "UV_VERSION": STUB_UV_VERSION,
        "DEMIURGOS_STUB_PYTHON": str(_REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
        "DEMIURGOS_STUB_LOG": str(tmp_path / "uv-stub.log"),
        "APPDATA": str(tmp_path / "appdata"),
        "LOCALAPPDATA": str(tmp_path / "localappdata"),
        "USERPROFILE": str(tmp_path / "userprofile"),
        "DEMIURGOS_NO_BROWSER": "1",
        "DEMIURGOS_LANGUAGE": "en",
        "PATH": os.environ.get("PATH", ""),
    }
    if fail_pip:
        env["DEMIURGOS_STUB_FAIL_PIP"] = "1"
    # S5b: install.ps1 verifies the manifest signature via the MINISIGN_PUBKEY
    # seam; pass the fixture's ephemeral public key when the channel is signed.
    pubkey_file = channel / ".test-pubkey"
    if pubkey_file.is_file():
        env["MINISIGN_PUBKEY"] = pubkey_file.read_text(encoding="utf-8").strip()
    for key in ("DEMIURGOS_DATA_ROOT", "DEMIURGOS_FRONTEND_DIST"):
        env.pop(key, None)
    # Windows PowerShell 5.1 cannot load its managed runtime from a MINIMAL
    # environment block: without ``SystemRoot`` (and the other OS-critical
    # variables) ``powershell.exe`` prints "Loading managed Windows PowerShell
    # failed with error 8009001d" and exits before running the installer. Carry
    # them through from the parent process while keeping every hermetic override
    # above intact (the real %APPDATA%/%USERPROFILE% are still replaced and the
    # DEMIURGOS_* env is still popped).
    for _win_key in (
        "SystemRoot", "windir", "SystemDrive", "PATHEXT", "ComSpec",
        "TEMP", "TMP", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
        "ProgramData", "ProgramFiles", "PUBLIC",
    ):
        if _win_key in os.environ:
            env[_win_key] = os.environ[_win_key]
    return env


def _run_ps_captured(cmd, env, timeout):
    """Run a PS command with output to temp FILES (not pipes) + stdin=DEVNULL.
    A detached grandchild (uvicorn) that inherits the pipes makes
    communicate() hang on Windows and defeats the timeout (issue #2)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        outp = Path(td) / "out"; errp = Path(td) / "err"
        with open(outp, "wb") as o, open(errp, "wb") as e:
            proc = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL,
                                  stdout=o, stderr=e, timeout=timeout)
        return proc.returncode, outp.read_text(encoding="utf-8", errors="replace"), errp.read_text(encoding="utf-8", errors="replace")


def _run_ps_installer(env: dict[str, str]) -> tuple[int, str, str]:
    return _run_ps_captured(
        ["powershell.exe", "-NoProfile", "-File", str(PS_INSTALLER)],
        env, timeout=300,
    )


def _boot_ps_launcher(install_root: Path, env: dict[str, str]) -> int:
    """Start the installed Windows launcher headless and return the API port.

    The caller's ``env`` is MUTATED in place (not copied) so the teardown
    ``stop`` targets the very ports this ``start`` used (issue #2: a copied
    env made ``stop`` fall back to the DEFAULT port and leak the API on the
    test port)."""
    api_port = _free_port()
    env["DEMIURGOS_API_PORT"] = str(api_port)
    env["DEMIURGOS_GATEWAY_PORT"] = str(_free_port())
    launcher = install_root / "current" / "scripts" / "start-demiurgos.ps1"
    rc, stdout, stderr = _run_ps_captured(
        ["powershell.exe", "-NoProfile", "-File", str(launcher), "start"],
        env, timeout=180,
    )
    err_log = install_root / "logs" / "demiurgos-api.err.log"
    api_err = (
        err_log.read_text(encoding="utf-8", errors="replace")
        if err_log.is_file() else "<no api err log>"
    )
    assert rc == 0, (
        f"PS launcher start failed (rc={rc})\n"
        f"stdout: {stdout}\nstderr: {stderr}\n"
        f"api err log ({err_log}):\n{api_err}"
    )
    return api_port


def _stop_ps_launcher_and_assert_clean(
    install_root: Path, env: dict[str, str], api_port: int,
) -> None:
    """Teardown contract (incident parity): stop the PS launcher, then assert
    NO leftover listener on the test port."""
    launcher = install_root / "current" / "scripts" / "start-demiurgos.ps1"
    rc, _stdout, stderr = _run_ps_captured(
        ["powershell.exe", "-NoProfile", "-File", str(launcher), "stop"],
        env, timeout=60,
    )
    assert rc == 0, stderr
    for _ in range(20):
        if not _port_listening(api_port):
            break
        time.sleep(0.25)
    assert not _port_listening(api_port), (
        f"port {api_port} still listening after stop: leaked launcher process"
    )


@PS_RUNNER
class TestWindowsFixtureChannelInstall:
    def test_ps1_install_then_boot_serves_health_and_root(self, tmp_path: Path):
        """Task 5.4: .ps1 core against a file:// fixture -> app serves."""
        channel, uv_sha, version = _build_windows_fixture_channel(tmp_path)
        install_root = tmp_path / "install"
        env = _ps_installer_env(tmp_path, channel, uv_sha, install_root)

        install_rc, install_out, install_err = _run_ps_installer(env)
        assert install_rc == 0, install_out + install_err

        # Installed layout from the frozen contract (S0-C).
        assert (install_root / "app" / version).is_dir()
        assert (install_root / "current").exists()
        assert (install_root / "bin" / "uv.ps1").is_file()
        assert (
            install_root / "app" / version / ".venv" / "Scripts" / "python.exe"
        ).exists()

        # Stub uv recorded the mandatory flags (hash-locked wheels-only).
        log = (tmp_path / "uv-stub.log").read_text(encoding="utf-8")
        assert "--require-hashes" in log
        assert "--only-binary=:all:" in log
        assert "requirements.lock" in log

        # Boot the installed app headless and probe /health + /.
        api_port = _boot_ps_launcher(install_root, env)
        try:
            _wait_health(api_port)
            assert _fetch(f"http://127.0.0.1:{api_port}/health") == 200
            assert _fetch(f"http://127.0.0.1:{api_port}/") == 200
        finally:
            _stop_ps_launcher_and_assert_clean(install_root, env, api_port)

    def test_ps1_rerun_is_idempotent_single_env(self, tmp_path: Path):
        """Task 5.4: re-run converges — one environment, pointer and .env
        preserved byte-for-byte (spec 'Re-run the installer')."""
        channel, uv_sha, version = _build_windows_fixture_channel(tmp_path)
        install_root = tmp_path / "install"
        env = _ps_installer_env(tmp_path, channel, uv_sha, install_root)

        first_rc, first_out, first_err = _run_ps_installer(env)
        assert first_rc == 0, first_out + first_err
        pointer = _read_pointer(Path(env["APPDATA"]) / "demiurgos")
        env_before = (pointer / ".env").read_bytes()

        second_rc, second_out, second_err = _run_ps_installer(env)
        assert second_rc == 0, second_out + second_err

        # One environment: exactly one app/<version>, one current junction.
        app_dirs = [p.name for p in (install_root / "app").iterdir()]
        assert app_dirs == [version]
        # Pointer and .env are bootstrap-only: preserved byte-for-byte.
        assert (pointer / ".env").read_bytes() == env_before


@PS_RUNNER
class TestWindowsChecksumMismatchAborts:
    def test_ps1_wrong_sha256_aborts_with_no_runnable_state(self, tmp_path: Path):
        """Task 5.4: corrupted checksum -> abort with no runnable state."""
        channel, uv_sha, _version = _build_windows_fixture_channel(
            tmp_path, wrong_payload_sha="0" * 64
        )
        install_root = tmp_path / "install"
        env = _ps_installer_env(tmp_path, channel, uv_sha, install_root)

        result_rc, result_out, result_err = _run_ps_installer(env)
        assert result_rc != 0
        assert "checksum" in (result_out + result_err).lower()

        # No runnable state: no current, no app, staging cleaned up.
        assert not (install_root / "current").exists()
        assert not (install_root / "app").exists()
        staging = install_root / ".staging"
        if staging.exists():
            assert list(staging.iterdir()) == []


@PS_RUNNER
class TestWindowsM1DefenderSpaceUser:
    def test_ps1_install_under_username_with_space(self, tmp_path: Path):
        """M1 (errata): Defender enabled (default on windows-latest) + a
        username containing a space -> the install root path contains a space
        (like C:\\Users\\Miguel Angel\\AppData\\Local\\Demiurgos). The core
        must install, junction and boot without choking on the space;
        Defender's real-time scan runs on the CI runner."""
        channel, uv_sha, version = _build_windows_fixture_channel(tmp_path)
        space_home = tmp_path / "Users" / "Miguel Angel" / "AppData" / "Local"
        install_root = space_home / "Demiurgos"
        env = _ps_installer_env(tmp_path, channel, uv_sha, install_root)

        install_rc, install_out, install_err = _run_ps_installer(env)
        assert install_rc == 0, install_out + install_err
        current = install_root / "current"
        assert current.exists()
        assert (install_root / "app" / version / "src").exists()

        # Boot from the spaced path proves the junction + venv + launcher
        # handle spaces.
        api_port = _boot_ps_launcher(install_root, env)
        try:
            _wait_health(api_port)
            assert _fetch(f"http://127.0.0.1:{api_port}/health") == 200
        finally:
            _stop_ps_launcher_and_assert_clean(install_root, env, api_port)


# ---------------------------------------------------------------------------
# 6.5 — S4 public bootstrap harness (install.sh here; install.ps1 on Windows)
# ---------------------------------------------------------------------------
# The public bootstrap is the thin delegator: it fetches the versioned core
# from the fixture channel, verifies it, then runs it. The POSIX cells run on
# this host (task 6.5); the Windows iex-mode cell is marked skipif and
# reported not-run here (no powershell on this Linux host).


def _run_posix_bootstrap(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALL_SH)],
        env=env, capture_output=True, text=True, timeout=240,
    )


@POSIX_RUNNER
class TestPublicBootstrapPosix:
    def test_bootstrap_installs_then_boots(self, tmp_path: Path):
        """Task 6.5: install.sh against the fixture channel -> app serves."""
        channel, uv_sha, version = _build_fixture_channel(
            tmp_path, include_core=True
        )
        install_root = tmp_path / "install"
        env = _installer_env(tmp_path, channel, uv_sha, install_root)

        run = _run_posix_bootstrap(env)
        assert run.returncode == 0, run.stdout + run.stderr

        # Installed layout from the frozen contract (S0-C).
        assert (install_root / "app" / version).is_dir()
        assert (install_root / "current").exists()

        api_port = _boot_launcher(tmp_path, env, install_root)
        try:
            _wait_health(api_port)
            assert _fetch(f"http://127.0.0.1:{api_port}/health") == 200
            assert _fetch(f"http://127.0.0.1:{api_port}/") == 200
        finally:
            _stop_and_assert_clean(
                install_root / "current" / "scripts" / "start-demiurgos.sh",
                env, api_port,
            )

    def test_bootstrap_rerun_is_idempotent(self, tmp_path: Path):
        """Task 6.5: run twice -> one environment, exit 0 (spec 'Re-run the
        installer')."""
        channel, uv_sha, version = _build_fixture_channel(
            tmp_path, include_core=True
        )
        install_root = tmp_path / "install"
        env = _installer_env(tmp_path, channel, uv_sha, install_root)

        first = _run_posix_bootstrap(env)
        assert first.returncode == 0, first.stdout + first.stderr
        second = _run_posix_bootstrap(env)
        assert second.returncode == 0, second.stdout + second.stderr

        # Exactly one environment: one app/<version>, one current symlink.
        app_dirs = [p.name for p in (install_root / "app").iterdir()]
        assert app_dirs == [version]
        assert (install_root / "current").is_symlink()


def _run_ps_bootstrap_iex(env: dict[str, str]) -> tuple[int, str, str]:
    """Faithful `irm | iex`-mode: pipe install.ps1 CONTENT through iex (no
    -File, no script file — exactly what the public one-liner does)."""
    ps_code = (
        "Get-Content -Raw -LiteralPath '" + str(INSTALL_PS1) + "' | Invoke-Expression"
    )
    return _run_ps_captured(
        ["powershell.exe", "-NoProfile", "-Command", ps_code],
        env, timeout=300,
    )


@PS_RUNNER
class TestPublicBootstrapWindows:
    def test_ps1_bootstrap_iex_installs_then_boots(self, tmp_path: Path):
        """Task 6.5: iex-mode dry-run of install.ps1 against the fixture
        channel -> the delegated core installs and the app serves."""
        channel, uv_sha, version = _build_windows_fixture_channel(
            tmp_path, include_core=True
        )
        install_root = tmp_path / "install"
        env = _ps_installer_env(tmp_path, channel, uv_sha, install_root)

        run_rc, run_out, run_err = _run_ps_bootstrap_iex(env)
        assert run_rc == 0, run_out + run_err

        assert (install_root / "app" / version).is_dir()
        assert (install_root / "current").exists()

        api_port = _boot_ps_launcher(install_root, env)
        try:
            _wait_health(api_port)
            assert _fetch(f"http://127.0.0.1:{api_port}/health") == 200
            assert _fetch(f"http://127.0.0.1:{api_port}/") == 200
        finally:
            _stop_ps_launcher_and_assert_clean(install_root, env, api_port)