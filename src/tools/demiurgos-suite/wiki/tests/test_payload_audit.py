# -*- coding: utf-8 -*-
"""Payload audit tests (design v2 S5-3 / tasks 8.1-8.6) — the release gate.

Drives ``scripts/payload_audit.sh`` against fixture trees: deny-by-path
rejects every named deny entry, the content scan rejects planted secret
patterns inside ALLOWED files, a clean tree passes, and the audit is genuinely
default-DENY (a path not in the manifest is rejected). No network tools are
invoked — the audit and its content-scan dependency are local scripts.

S5b additions (tasks 8.1-8.6): the ``--allow`` flag for the packaging extras,
the threat-matrix "Documentation-like paths" assertions (requirements ship as
read-only references, no ``.md``/``.txt`` payload file is executed), the
Windows parity cells for ``scripts/payload_audit.ps1`` (ASCII + rule/deny-list
parity — runtime cells stay skipif on this Linux host), and the signed-manifest
end-to-end harness: an EPHEMERAL minisign keypair is generated at test time
(never committed) to prove sign -> verify -> reject-tampered through the real
``install.sh`` bootstrap and the real ``scripts/install-demiurgos.sh`` core.
The minisign cells skip when ``minisign`` is not on PATH (CI installs it; the
signed round-trip is the proof).

All planted values are obviously fake (the ``TESTONLY`` marker) — never real
credentials and never real author data. The audit must never echo a matched
value, and the tests assert that.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[4]
_AUDIT = _REPO_ROOT / "scripts" / "payload_audit.sh"
_VERIFY_LIB = _REPO_ROOT / "scripts" / "lib" / "verify_checksum.sh"
_INSTALL_SH = _REPO_ROOT / "install.sh"
_INSTALLER_CORE = _REPO_ROOT / "scripts" / "install-demiurgos.sh"
_PAYLOAD_AUDIT_PS1 = _REPO_ROOT / "scripts" / "payload_audit.ps1"
_SECRET_SCAN = _REPO_ROOT / "scripts" / "secret_scan.sh"

# Importing _minisign_stub provisions a CLI-only stub minisign when no real
# one is installed (import side effect), so the signed-channel cells RUN
# instead of silently skipping. With a real minisign present (CI) they
# exercise the real Ed25519 round-trip; with the stub they exercise the
# installer's ordering and fail-closed behavior. The stub never proves the
# crypto.
import _minisign_stub  # noqa: F401

#: POSIX-runner-only: the runtime cells execute the POSIX audit/installer core
#: directly (``scripts/payload_audit.sh`` / ``install.sh`` / ``scripts/lib/
#: verify_checksum.sh``) or via ``bash`` — impossible on Windows, where a bare
#: ``bash`` is the WSL launcher stub and a ``.sh`` file is not a Win32
#: executable (WinError 193). The ``.ps1`` parity cells stay ungated.
POSIX_RUNNER = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX audit/installer runtime cells shell out to bash or the .sh core",
)

# ---------------------------------------------------------------------------
# Fake fixture values. The TESTONLY marker lets .gitleaks.toml allowlist them
# by regex; the fixtures themselves live only in tmp_path.
# ---------------------------------------------------------------------------
FAKE_BOT_TOKEN = "123456789:TESTONLY_AAAAAAAAAAAAAAAAAAAAAAAAAA"
FAKE_OPENAI_KEY = "sk-TESTONLY0000000000000000000"
FAKE_GOOGLE_KEY = "AIzaTESTONLY" + "0" * 27
FAKE_AUTHOR_PATHS = [
    "H:\\TESTONLY\\fake",
    "/home/testonly/user",
    "C:\\Users\\TESTONLY\\fake",
    "spreadsheetId=TESTONLY_FAKE",
]

# (rel path, kind) — every explicit deny entry from tasks 8.1. The kind only
# documents the deny rule class; the audit must reject each of them.
DENY_CASES = [
    ("config/idea-capture.yaml", "file"),
    ("config/hermes-mcp-profile.yaml.example", "file"),
    ("docs/MARCA.md", "file"),
    ("src/tools/dev_diary.py", "file"),
    ("engram-export.json", "file"),
    (".env", "file"),
    (".env.backup", "file"),
    (".secrets/telegram.token", "dir"),
    ("mundos/Vibrantes/world.yaml", "dir"),
    (".git/config", "dir"),
    ("src/tools/opencode-bridge.py", "file"),
    ("start-opencode-dev.ps1", "glob"),
    ("sync-ideas.py.bak-20240101", "glob"),
]

# (value, rule-name) — every content-scan rule from tasks 8.1.
CONTENT_CASES = [
    (FAKE_BOT_TOKEN, "bot-token"),
    (FAKE_OPENAI_KEY, "openai-key"),
    (FAKE_GOOGLE_KEY, "google-api-key"),
    *[(path, "author-path") for path in FAKE_AUTHOR_PATHS],
]


def _run_audit(root: Path, manifest: Path, *extra: str) -> subprocess.CompletedProcess:
    """Run the audit against a fixture tree; manifest lives OUTSIDE the tree."""
    return subprocess.run(
        [str(_AUDIT), "--root", str(root), "--manifest", str(manifest), *extra],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _build_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _write_manifest(manifest: Path, payload: list[str]) -> None:
    manifest.write_text(
        json.dumps({"schema_version": 1, "payload": payload}),
        encoding="utf-8",
    )


def _fixture_tree(tmp_path: Path, deny_path: str | None = None) -> tuple[Path, Path]:
    """A tree that allows app/main.py and optionally plants a deny path."""
    root = tmp_path / "tree"
    files = {"app/main.py": "print('hello')\n"}
    if deny_path:
        files[deny_path] = "placeholder content\n"
    _build_tree(root, files)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["app/main.py"])
    return root, manifest


@POSIX_RUNNER
class TestDenyByPath:
    @pytest.mark.parametrize("deny_path,_kind", DENY_CASES, ids=[c[0] for c in DENY_CASES])
    def test_each_named_deny_path_is_rejected(self, tmp_path, deny_path, _kind):
        root, manifest = _fixture_tree(tmp_path, deny_path)
        result = _run_audit(root, manifest)
        assert result.returncode == 1, f"expected audit failure for {deny_path}: {result.stdout}"
        assert f"deny: {deny_path}" in result.stdout, (
            f"audit output for {deny_path}:\n{result.stdout}"
        )

    def test_denied_path_is_never_content_scanned(self, tmp_path):
        """A denied path containing a secret reports the deny, never the value."""
        root = tmp_path / "tree"
        _build_tree(root, {"app/main.py": "print('hello')\n"})
        _build_tree(root, {"config/idea-capture.yaml": f"token: {FAKE_BOT_TOKEN}\n"})
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py"])
        result = _run_audit(root, manifest)
        assert result.returncode == 1
        assert "deny: config/idea-capture.yaml" in result.stdout
        assert FAKE_BOT_TOKEN not in result.stdout


@POSIX_RUNNER
class TestContentScan:
    @pytest.mark.parametrize("value,rule", CONTENT_CASES, ids=[c[1] for c in CONTENT_CASES])
    def test_planted_pattern_in_allowed_file_is_rejected(self, tmp_path, value, rule):
        root = tmp_path / "tree"
        _build_tree(root, {"app/allowed.txt": f"prefix {value} suffix\n"})
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/allowed.txt"])
        result = _run_audit(root, manifest)
        assert result.returncode == 1, f"expected content hit for {rule}: {result.stdout}"
        assert rule in result.stdout, f"expected rule {rule} in:\n{result.stdout}"
        assert value not in result.stdout, "the audit must never echo a matched value"


@POSIX_RUNNER
class TestDefaultDeny:
    def test_clean_tree_passes(self, tmp_path):
        root = tmp_path / "tree"
        _build_tree(
            root,
            {
                "app/main.py": "print('hello')\n",
                "app/util.py": "def util():\n    return 1\n",
            },
        )
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py", "app/util.py"])
        result = _run_audit(root, manifest)
        assert result.returncode == 0, f"clean tree must pass:\n{result.stdout}"
        assert result.stdout == ""

    def test_unlisted_path_is_rejected(self, tmp_path):
        """A path not in the manifest is denied even when its content is clean."""
        root = tmp_path / "tree"
        _build_tree(
            root,
            {
                "app/main.py": "print('hello')\n",
                "app/extra.py": "def extra():\n    return 2\n",
            },
        )
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py"])
        result = _run_audit(root, manifest)
        assert result.returncode == 1
        assert "deny: app/extra.py" in result.stdout
        assert "not in manifest allow-list" in result.stdout

    def test_missing_manifest_is_a_usage_error(self, tmp_path):
        root = tmp_path / "tree"
        _build_tree(root, {"app/main.py": "print('hello')\n"})
        result = _run_audit(root, tmp_path / "does-not-exist.json")
        assert result.returncode == 2
        assert "manifest not found" in result.stderr


# ---------------------------------------------------------------------------
# S5b / task 8.2: the --allow flag — extra shippable paths beyond the manifest
# (the packaging extras and the shared dist tree).
# ---------------------------------------------------------------------------

@POSIX_RUNNER
class TestAllowFlag:
    def test_extra_path_listed_in_allow_file_passes(self, tmp_path):
        root = tmp_path / "tree"
        _build_tree(root, {"app/main.py": "print('hello')\n", "LICENSE": "terms\n"})
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py"])
        allow = tmp_path / "allow.txt"
        allow.write_text("LICENSE\n", encoding="utf-8")
        result = _run_audit(root, manifest, "--allow", str(allow))
        assert result.returncode == 0, f"LICENSE must pass via --allow:\n{result.stdout}"

    def test_extra_path_not_listed_is_denied(self, tmp_path):
        root = tmp_path / "tree"
        _build_tree(root, {"app/main.py": "print('hello')\n", "LICENSE": "terms\n"})
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py"])
        result = _run_audit(root, manifest)
        assert result.returncode == 1
        assert "deny: LICENSE" in result.stdout
        assert "not in manifest allow-list" in result.stdout

    def test_allow_directory_prefix_covers_the_dist_tree(self, tmp_path):
        root = tmp_path / "tree"
        _build_tree(
            root,
            {
                "app/main.py": "print('hello')\n",
                "frontend/dist/index.html": "<html></html>\n",
                "frontend/dist/assets/app-abc123.js": "console.log(1)\n",
            },
        )
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py"])
        allow = tmp_path / "allow.txt"
        allow.write_text("frontend/dist/\n", encoding="utf-8")
        result = _run_audit(root, manifest, "--allow", str(allow))
        assert result.returncode == 0, f"dist prefix must be allowed:\n{result.stdout}"

    def test_allow_comments_and_blank_lines_are_ignored(self, tmp_path):
        root = tmp_path / "tree"
        _build_tree(root, {"app/main.py": "print('hello')\n", "LICENSE": "terms\n"})
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py"])
        allow = tmp_path / "allow.txt"
        allow.write_text("# packaging extras\n\nLICENSE\n", encoding="utf-8")
        result = _run_audit(root, manifest, "--allow", str(allow))
        assert result.returncode == 0

    def test_deny_rules_win_over_allow(self, tmp_path):
        """A deny-listed path must be rejected even when --allow names it."""
        root = tmp_path / "tree"
        _build_tree(root, {"app/main.py": "print('hello')\n", ".env": "DEMIURGOS=1\n"})
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py"])
        allow = tmp_path / "allow.txt"
        allow.write_text(".env\n", encoding="utf-8")
        result = _run_audit(root, manifest, "--allow", str(allow))
        assert result.returncode == 1
        assert "deny: .env" in result.stdout
        assert "explicit deny path" in result.stdout


# ---------------------------------------------------------------------------
# S5b / task 8.1 — threat-matrix row "Documentation-like paths": requirements
# ship as read-only references and no .md/.txt payload file is ever executed.
# ---------------------------------------------------------------------------

REQUIREMENTS_REFERENCE_CASES = [
    "requirements.txt",
    "requirements.lock",
]

INSTALLER_SCRIPTS = [
    _INSTALL_SH,
    _INSTALLER_CORE,
    _AUDIT,
    _PAYLOAD_AUDIT_PS1,
]


@POSIX_RUNNER
class TestDocumentationLikePaths:
    @pytest.mark.parametrize("name", REQUIREMENTS_REFERENCE_CASES)
    def test_requirements_reference_ships_as_allowed(self, tmp_path, name):
        """requirements.txt / requirements.lock ship as read-only references."""
        root = tmp_path / "tree"
        _build_tree(root, {"app/main.py": "print('hello')\n", name: "# pinned\n"})
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py", name])
        result = _run_audit(root, manifest)
        assert result.returncode == 0, f"requirements reference must ship:\n{result.stdout}"

    @pytest.mark.parametrize("script", INSTALLER_SCRIPTS, ids=[s.name for s in INSTALLER_SCRIPTS])
    def test_no_payload_reference_file_is_executed(self, script):
        """No .md/.txt/requirements.* payload file is ever shell-executed.

        The installer runs uv, which READS the requirements lock as data, and
        the user starts the launcher; nothing in the distribution executes a
        documentation/reference file.
        """
        text = script.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if re.search(r"\b(bash|sh|source|exec)\b", line) and re.search(
                r"\.(md|txt)\b|requirements\.", line
            ):
                pytest.fail(
                    f"{script.name}:{lineno}: executes a reference file: {line.strip()}"
                )


@POSIX_RUNNER
class TestContentScanSkip:
    """The derived dist tree is path-checked but not content-scanned.

    The built bundle legitimately contains Tailwind/xyflow CSS utility names
    (``sk-background-color-default`` ...) that false-positive the openai-key
    heuristic. The skip scopes the SCANNED set; no rule is weakened — the same
    pattern in any scanned file still fails.
    """

    FAKE_CSS_NAME = "sk-background-color-default-with-a-long-name"

    def test_skipped_prefix_is_not_content_scanned(self, tmp_path):
        root = tmp_path / "tree"
        _build_tree(
            root,
            {
                "app/main.py": "print('hello')\n",
                "frontend/dist/assets/app.css": f".{self.FAKE_CSS_NAME} {{ color: red }}\n",
            },
        )
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py", "frontend/dist/assets/app.css"])
        result = _run_audit(root, manifest, "--content-scan-skip", "frontend/dist/")
        assert result.returncode == 0, f"skipped prefix must pass:\n{result.stdout}"

    def test_same_pattern_without_skip_still_fails(self, tmp_path):
        """The skip scopes the scanned set only; the rule is not weakened."""
        root = tmp_path / "tree"
        _build_tree(
            root,
            {
                "app/main.py": "print('hello')\n",
                "app/style.css": f".{self.FAKE_CSS_NAME} {{ color: red }}\n",
            },
        )
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py", "app/style.css"])
        result = _run_audit(root, manifest)
        assert result.returncode == 1
        assert "openai-key" in result.stdout

    def test_path_checks_still_apply_under_skipped_prefix(self, tmp_path):
        """Deny rules and the allow-list still win under the skipped prefix."""
        root = tmp_path / "tree"
        _build_tree(
            root,
            {
                "app/main.py": "print('hello')\n",
                "frontend/dist/rogue.js": "console.log(1)\n",
            },
        )
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py"])
        result = _run_audit(root, manifest, "--content-scan-skip", "frontend/dist/")
        assert result.returncode == 1
        assert "deny: frontend/dist/rogue.js" in result.stdout


# ---------------------------------------------------------------------------
# S5b / task 8.4 — signed manifest. An EPHEMERAL minisign keypair is generated
# per test (never committed) to prove sign -> verify -> reject-tampered.
# ---------------------------------------------------------------------------

def _ephemeral_keypair(tmp_path: Path) -> tuple[Path, str]:
    """Generate a throwaway minisign keypair in tmp_path.

    Returns (secret-key path, public-key base64 line). ``-W`` skips the
    password prompt; the key is a temp file and is never committed.
    """
    key = tmp_path / "test.key"
    pub = tmp_path / "test.pub"
    subprocess.run(
        ["minisign", "-G", "-W", "-s", str(key), "-p", str(pub)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    pubkey = pub.read_text(encoding="utf-8").strip().splitlines()[-1]
    return key, pubkey


def _sign_minisig(sums: Path, key: Path) -> None:
    """Sign ``sums`` with minisign, writing ``<sums>.minisig``."""
    subprocess.run(
        ["minisign", "-Sm", str(sums), "-s", str(key)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


@POSIX_RUNNER
class TestSignedManifest:
    def test_roundtrip_sign_verify_reject_tampered(self, tmp_path):
        sums = tmp_path / "SHA256SUMS"
        sums.write_text("abc123  payload.tar.gz\n", encoding="utf-8")
        key, pubkey = _ephemeral_keypair(tmp_path)
        _sign_minisig(sums, key)
        assert (tmp_path / "SHA256SUMS.minisig").is_file(), "minisign must emit SHA256SUMS.minisig"

        ok = subprocess.run(
            ["minisign", "-Vm", str(sums), "-P", pubkey],
            capture_output=True, text=True, timeout=30,
        )
        assert ok.returncode == 0, ok.stderr

        sums.write_text("abc123  payload.tar.gz\nTAMPERED\n", encoding="utf-8")
        bad = subprocess.run(
            ["minisign", "-Vm", str(sums), "-P", pubkey],
            capture_output=True, text=True, timeout=30,
        )
        assert bad.returncode != 0, "a tampered manifest must not verify"

    def test_verify_minisig_function_gate_fail_closed(self, tmp_path):
        """The shipped POSIX verifier library enforces the gate fail-closed."""
        sums = tmp_path / "SHA256SUMS"
        sums.write_text("abc123  payload.tar.gz\n", encoding="utf-8")
        key, pubkey = _ephemeral_keypair(tmp_path)
        _sign_minisig(sums, key)

        script = (
            f'source "{_VERIFY_LIB}"; '
            f'MINISIGN_PUBKEY="{pubkey}" verify_minisig "{sums}" "{sums}.minisig"'
        )
        good = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        assert good.returncode == 0, good.stderr

        sums.write_text("abc123  payload.tar.gz\nTAMPERED\n", encoding="utf-8")
        bad = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        assert bad.returncode != 0, "a tampered manifest must fail the shipped verifier"
        assert "SIGNATURE VERIFICATION FAILED" in bad.stderr

    def test_verify_minisig_requires_the_signature_file(self, tmp_path):
        sums = tmp_path / "SHA256SUMS"
        sums.write_text("abc123  payload.tar.gz\n", encoding="utf-8")
        key, pubkey = _ephemeral_keypair(tmp_path)
        script = (
            f'source "{_VERIFY_LIB}"; '
            f'MINISIGN_PUBKEY="{pubkey}" verify_minisig "{sums}" "{sums}.minisig"'
        )
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        assert result.returncode != 0
        assert "missing" in result.stderr


# ---------------------------------------------------------------------------
# S5b / task 8.4 + 8.6 — end-to-end consumer verification: the real
# install.sh bootstrap against a signed fixture channel (stub core).
# Tampered artifact -> verification fails -> installation aborted.
# ---------------------------------------------------------------------------

@POSIX_RUNNER
class TestConsumerSignedBootstrap:
    STUB_CORE = "#!/usr/bin/env bash\necho STUB-CORE-RAN\nexit 0\n"

    def _channel(self, tmp_path, *, tamper_core=False, tamper_manifest=False):
        """A signed file:// fixture channel with a stub core + the real lib.

        The channel is signed FIRST; the tamper flags then modify a file AFTER
        publication, exactly like an attacker (or a corrupted mirror) would.
        """
        channel = tmp_path / "channel"
        (channel / "scripts" / "lib").mkdir(parents=True)
        core = channel / "scripts" / "install-demiurgos.sh"
        core.write_text(self.STUB_CORE, encoding="utf-8")
        shutil.copy(_VERIFY_LIB, channel / "scripts" / "lib" / "verify_checksum.sh")

        sums = channel / "SHA256SUMS"
        entries = []
        for name in ("scripts/install-demiurgos.sh", "scripts/lib/verify_checksum.sh"):
            sha = hashlib.sha256((channel / name).read_bytes()).hexdigest()
            entries.append(f"{sha}  {name}")
        sums.write_text("\n".join(entries) + "\n", encoding="utf-8")

        key, pubkey = _ephemeral_keypair(tmp_path)
        _sign_minisig(sums, key)

        # post-publication tampering (signature no longer covers the change)
        if tamper_core:
            core.write_text(self.STUB_CORE + "# TAMPERED\n", encoding="utf-8")
        if tamper_manifest:
            sums.write_text(sums.read_text(encoding="utf-8") + "X\n", encoding="utf-8")
        return channel, pubkey

    def _run_bootstrap(self, channel: Path, pubkey: str, home: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(
            {
                "DEMIURGOS_URL_BASE": f"file://{channel}",
                "DEMIURGOS_HOME": str(home),
                "DEMIURGOS_VERSION": "9.9.9",
                "MINISIGN_PUBKEY": pubkey,
                "DEMIURGOS_NO_BROWSER": "1",
            }
        )
        return subprocess.run(
            ["bash", str(_INSTALL_SH)],
            capture_output=True, text=True, timeout=120, env=env,
        )

    def test_signed_channel_executes_the_verified_core(self, tmp_path):
        channel, pubkey = self._channel(tmp_path)
        result = self._run_bootstrap(channel, pubkey, tmp_path / "home")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "STUB-CORE-RAN" in result.stdout

    def test_tampered_core_aborts_before_execution(self, tmp_path):
        """Signature OK, core checksum wrong -> abort, stub never runs."""
        channel, pubkey = self._channel(tmp_path, tamper_core=True)
        result = self._run_bootstrap(channel, pubkey, tmp_path / "home")
        assert result.returncode != 0
        assert "checksum mismatch" in result.stdout + result.stderr
        assert "STUB-CORE-RAN" not in result.stdout

    def test_tampered_manifest_aborts_at_signature_before_checksums(self, tmp_path):
        """Manifest tampered (not re-signed) -> signature gate fails FIRST."""
        channel, pubkey = self._channel(tmp_path, tamper_manifest=True)
        result = self._run_bootstrap(channel, pubkey, tmp_path / "home")
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "signature" in combined.lower()
        assert "STUB-CORE-RAN" not in result.stdout


# ---------------------------------------------------------------------------
# S5b / task 8.4 — the real installer core's signature gate.
# ---------------------------------------------------------------------------

@POSIX_RUNNER
class TestInstallerCoreSignatureGate:
    def _channel(self, tmp_path, *, tamper_manifest=False, tamper_payload=False):
        """A signed file:// fixture channel for the real installer core.

        Signed FIRST; the tamper flags modify a file AFTER publication.
        """
        channel = tmp_path / "channel"
        channel.mkdir(parents=True)
        payload = channel / "demiurgos-app-9.9.9.tar.gz"
        payload.write_bytes(b"not-a-real-archive-bytes")
        (channel / "version.json").write_text(
            json.dumps({"version": "9.9.9", "posix": payload.name}), encoding="utf-8"
        )
        sums = channel / "SHA256SUMS"
        sha = hashlib.sha256(payload.read_bytes()).hexdigest()
        sums.write_text(f"{sha}  {payload.name}\n", encoding="utf-8")

        key, pubkey = _ephemeral_keypair(tmp_path)
        _sign_minisig(sums, key)

        # post-publication tampering
        if tamper_manifest:
            sums.write_text(sums.read_text(encoding="utf-8") + "X\n", encoding="utf-8")
        if tamper_payload:
            payload.write_bytes(b"tampered-bytes")
        return channel, pubkey

    def _run_core(self, channel: Path, pubkey: str, home: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(
            {
                "DEMIURGOS_URL_BASE": f"file://{channel}",
                "DEMIURGOS_HOME": str(home),
                "DEMIURGOS_VERSION": "9.9.9",
                "DEMIURGOS_FAKE_GLIBC_VERSION": "2.31",
                "MINISIGN_PUBKEY": pubkey,
            }
        )
        return subprocess.run(
            ["bash", str(_INSTALLER_CORE)],
            capture_output=True, text=True, timeout=120, env=env,
        )

    def test_signed_channel_passes_the_gates_then_stops_at_uv(self, tmp_path):
        """Signature + checksum gates pass; the core proceeds to uv, which has
        no baked checksum on this host -> the honest 'refusing an unverified
        toolchain' stop. That proves the gates were crossed BEFORE uv."""
        channel, pubkey = self._channel(tmp_path)
        result = self._run_core(channel, pubkey, tmp_path / "home")
        assert "no uv checksum available" in result.stderr, result.stderr
        assert "SIGNATURE VERIFICATION FAILED" not in result.stderr
        assert "checksum mismatch" not in result.stderr

    def test_tampered_manifest_aborts_at_signature_before_checksum(self, tmp_path):
        channel, pubkey = self._channel(tmp_path, tamper_manifest=True)
        result = self._run_core(channel, pubkey, tmp_path / "home")
        assert result.returncode != 0
        assert "SIGNATURE VERIFICATION FAILED" in result.stderr
        assert "no uv checksum" not in result.stderr, "must stop at the signature gate"

    def test_tampered_payload_aborts_at_checksum(self, tmp_path):
        """Signature still valid (manifest untouched) -> the payload checksum
        gate catches the tampered archive."""
        channel, pubkey = self._channel(tmp_path, tamper_payload=True)
        result = self._run_core(channel, pubkey, tmp_path / "home")
        assert result.returncode != 0
        assert "checksum mismatch" in result.stderr
        assert "no uv checksum" not in result.stderr, "must stop at the checksum gate"


class TestSignatureOrdering:
    def test_core_verifies_signature_before_payload_checksum(self):
        lines = _INSTALLER_CORE.read_text(encoding="utf-8").splitlines()
        sig = next(
            i for i, line in enumerate(lines) if 'verify_minisig "$workdir/SHA256SUMS"' in line
        )
        checksum = next(
            i for i, line in enumerate(lines) if 'verify_sha256 "$PAYLOAD_FILE"' in line
        )
        assert sig < checksum, "the manifest signature must be verified BEFORE the payload checksum"

    def test_bootstrap_verifies_signature_before_core_checksums(self):
        lines = _INSTALL_SH.read_text(encoding="utf-8").splitlines()
        sig = next(
            i for i, line in enumerate(lines) if 'verify_minisig "$BOOTSTRAP_WORK/SHA256SUMS"' in line
        )
        checksum = next(
            i for i, line in enumerate(lines) if 'verify_sha256 "$core_dir/install-demiurgos.sh"' in line
        )
        assert sig < checksum, "the bootstrap must verify the signature BEFORE the core checksums"


# ---------------------------------------------------------------------------
# S5b / task 8.2 — payload_audit.ps1 Windows parity (text cells on this Linux
# host; runtime cells would run on the Windows runner — skipif not-run here).
# ---------------------------------------------------------------------------

class TestPayloadAuditPowerShellParity:
    def test_ps_is_ascii_only(self):
        """S2-8: PS 5.1 mis-decodes BOM-less UTF-8; every .ps1 ships ASCII."""
        _PAYLOAD_AUDIT_PS1.read_bytes().decode("ascii")

    def test_ps_deny_lists_match_the_posix_audit(self):
        ps = _PAYLOAD_AUDIT_PS1.read_text(encoding="ascii")
        sh = _AUDIT.read_text(encoding="utf-8")
        deny_exact = re.search(r'DENY_EXACT="(.*?)"', sh, re.S).group(1).split()
        for token in deny_exact:
            assert token in ps, f"PS audit misses deny token {token}"
        for token in ("secrets", "mundos", ".git"):
            assert token in ps, f"PS audit misses deny dir {token}"
        for token in ("start-opencode-*.ps1", "sync-ideas.py.bak-*"):
            assert token in ps, f"PS audit misses deny glob {token}"

    def test_ps_content_scan_rules_match_the_single_source(self):
        ps = _PAYLOAD_AUDIT_PS1.read_text(encoding="ascii")
        scan = _SECRET_SCAN.read_text(encoding="utf-8")
        rules_src = re.search(r"RULES_SRC=\$\(cat <<'EOF'\n(.*?)EOF", scan, re.S).group(1)
        for line in rules_src.splitlines():
            name, pattern = line.split("\t")
            assert name in ps, f"PS audit misses rule name {name}"
            assert pattern in ps, f"PS audit misses rule pattern {pattern}"

    def test_ps_is_default_deny(self):
        ps = _PAYLOAD_AUDIT_PS1.read_text(encoding="ascii")
        assert "not in manifest allow-list" in ps
        assert "$payload" in ps
        assert "Test-Allowed" in ps

    def test_ps_has_content_scan_skip_parity(self):
        ps = _PAYLOAD_AUDIT_PS1.read_text(encoding="ascii")
        assert "ContentScanSkip" in ps
        assert "$rel.StartsWith($prefix)" in ps
        assert "frontend/dist" in ps

    def test_ps_never_prints_matched_values(self):
        """The PS scan emits path:line:rule only — never the matched value."""
        ps = _PAYLOAD_AUDIT_PS1.read_text(encoding="ascii")
        outputs = [l for l in ps.splitlines() if l.strip().startswith("Write-Output")]
        assert len(outputs) == 2, f"exactly two output lines expected, got: {outputs}"
        assert "rel, $h.LineNumber, $rule.Name" in outputs[0], "scan hit shape must be path:line:rule"
        assert "rel, $reason" in outputs[1], "deny shape must be path:reason"
        assert "$h.Value" not in ps and "$h.Matches" not in ps, "no output may echo a matched value"

# ---------------------------------------------------------------------------
# Release-payload allow-list parity (release-payload-audit-parity).
#
# The Windows port reimplemented the content scan WITHOUT the allow-list the
# POSIX path inherits from secret_scan.sh. The shipped content scanner carries
# its own rule literals by design (/home/, C:\Users), so the Windows cell
# flagged content_scan.py:48 and :73 (author-path) and the packaging gate went
# red on every push to master since the scanner shipped — while the POSIX cell
# stayed green. The allow-list now lives in ONE committed file that both ports
# read, and both ports are executed against the same fixture here.
# ---------------------------------------------------------------------------

_SCANNER_SELF_FILE = "src/tools/demiurgos-suite/wiki/content_scan.py"
_SHARED_ALLOWLIST = _REPO_ROOT / "scripts" / "payload_scan_allowlist.txt"

def _ps_host() -> str | None:
    """The PowerShell host to exercise: powershell.exe (PS 5.1) on Windows, pwsh elsewhere."""
    if os.name == "nt":
        return shutil.which("powershell") or shutil.which("pwsh")
    return shutil.which("pwsh")


#: The PowerShell runtime cells need a host, not an OS: the Windows package
#: gate is the one that ships, and pwsh on a POSIX runner exercises the same
#: script. Skipped only when no host exists at all.
PS_HOST = pytest.mark.skipif(_ps_host() is None, reason="no PowerShell host on this runner")


def _run_ps_audit(root: Path, manifest: Path, *extra: str) -> subprocess.CompletedProcess:
    """Run the PowerShell audit against a fixture tree (manifest outside it)."""
    host = _ps_host()
    assert host, "no PowerShell host available"
    argv = [host, "-NoProfile"]
    if os.name == "nt":
        argv += ["-ExecutionPolicy", "Bypass"]
    argv += ["-File", str(_PAYLOAD_AUDIT_PS1), "-Root", str(root), "-Manifest", str(manifest)]
    return subprocess.run(argv + list(extra), capture_output=True, text=True, timeout=120)


def _scanner_self_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A stage holding only the shipped content scanner, allowed by manifest.

    The scanner necessarily contains the deny-rule literals, so this tree is
    the exact shape that broke the Windows cell: allow-list or red.
    """
    root = tmp_path / "stage"
    target = root / _SCANNER_SELF_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_REPO_ROOT / _SCANNER_SELF_FILE, target)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [_SCANNER_SELF_FILE])
    return root, manifest


def _planted_secret_tree(tmp_path: Path) -> tuple[Path, Path]:
    """An allowed file carrying a fake key: both ports must report it identically."""
    root = tmp_path / "stage"
    _build_tree(root, {"app/main.py": FAKE_OPENAI_KEY + "\n"})
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["app/main.py"])
    return root, manifest


def _copy_shipped_scripts(tmp_path: Path) -> Path:
    """A private copy of scripts/, so a cell can hide or chmod the shared list."""
    dest = tmp_path / "scripts"
    shutil.copytree(_REPO_ROOT / "scripts", dest)
    return dest


def _run_sh_from(script: Path, root: Path, manifest: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(script), "--root", str(root), "--manifest", str(manifest), *extra],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _run_ps_from(script: Path, root: Path, manifest: Path, *extra: str) -> subprocess.CompletedProcess:
    host = _ps_host()
    assert host, "no PowerShell host available"
    argv = [host, "-NoProfile"]
    if os.name == "nt":
        argv += ["-ExecutionPolicy", "Bypass"]
    argv += ["-File", str(script), "-Root", str(root), "-Manifest", str(manifest)]
    return subprocess.run(argv + list(extra), capture_output=True, text=True, timeout=120)


class TestPayloadAuditPortParity:
    """One allow-list source; both ports reach the same verdict on one fixture."""

    def test_shared_allowlist_file_is_the_single_source(self):
        assert _SHARED_ALLOWLIST.is_file(), "the shared allow-list file must exist"
        entries = [
            line.strip()
            for line in _SHARED_ALLOWLIST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert _SCANNER_SELF_FILE in entries, "the shipped content scanner must stay allow-listed"
        assert "scripts/secret_scan.sh" in entries
        # Both ports must READ that file; neither may keep a private copy.
        assert "payload_scan_allowlist.txt" in _SECRET_SCAN.read_text(encoding="utf-8")
        assert "payload_scan_allowlist.txt" in _PAYLOAD_AUDIT_PS1.read_text(encoding="ascii")
        assert "DEFAULT_ALLOWLIST=(" not in _SECRET_SCAN.read_text(encoding="utf-8"), (
            "the POSIX default allow-list must live in the shared file, not inline"
        )

    def test_powershell_port_consults_the_shared_allowlist(self):
        ps = _PAYLOAD_AUDIT_PS1.read_text(encoding="ascii")
        assert "Test-ScanAllowed" in ps, "the PS scan must consult the shared allow-list"
        # exact-or-suffix matching, parity with secret_scan.sh _is_allowed
        assert "EndsWith('/' + $_entry)" in ps
        # the check runs INSIDE the scan loop, not after it
        scan = ps[ps.index("function Invoke-ContentScan"):]
        assert "Test-ScanAllowed" in scan, "allow-list must be applied per scanned file"

    def test_scanner_self_file_really_carries_the_patterns(self):
        """Guard the fixture: if the literals move, this cell stops proving anything."""
        text = (_REPO_ROOT / _SCANNER_SELF_FILE).read_text(encoding="utf-8")
        assert "/home/" in text and "C:\\\\Users" in text

    @POSIX_RUNNER
    def test_posix_port_ignores_scanner_self_patterns(self, tmp_path):
        root, manifest = _scanner_self_tree(tmp_path)
        result = _run_audit(root, manifest)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "content-scan" not in result.stdout

    @PS_HOST
    def test_powershell_port_ignores_scanner_self_patterns(self, tmp_path):
        root, manifest = _scanner_self_tree(tmp_path)
        result = _run_ps_audit(root, manifest)
        assert result.returncode == 0, (
            "the Windows payload gate must not flag the scanner's own rule literals; "
            + result.stdout
            + result.stderr
        )
        assert "content_scan.py:" not in result.stdout

    @POSIX_RUNNER
    def test_posix_port_flags_a_planted_secret(self, tmp_path):
        root, manifest = _planted_secret_tree(tmp_path)
        result = _run_audit(root, manifest)
        assert result.returncode == 1, result.stdout + result.stderr
        assert result.stdout.strip() == "app/main.py:1: openai-key"
        assert FAKE_OPENAI_KEY not in result.stdout, "never echo the matched value"

    @PS_HOST
    def test_powershell_port_flags_a_planted_secret(self, tmp_path):
        root, manifest = _planted_secret_tree(tmp_path)
        result = _run_ps_audit(root, manifest)
        assert result.returncode == 1, result.stdout + result.stderr
        # The finding line is parity with the POSIX port on the same tree. The
        # PS port also prints its summary to stdout (Write-Host) where POSIX
        # uses stderr, so only the finding is compared verbatim.
        hits = [l for l in result.stdout.splitlines() if l.startswith("app/main.py:")]
        assert hits == ["app/main.py:1: openai-key"], result.stdout
        assert FAKE_OPENAI_KEY not in result.stdout + result.stderr, "never echo the matched value"

    @PS_HOST
    def test_powershell_port_still_denies_an_unlisted_path(self, tmp_path):
        """The allow-list must not turn the default-DENY gate permissive."""
        root, manifest = _scanner_self_tree(tmp_path)
        _build_tree(root, {"rogue.txt": "rogue\n"})
        result = _run_ps_audit(root, manifest)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "deny: rogue.txt" in result.stdout

    # --- fail-closed: the shared allow-list is a contract input ---------------
    # A gate that cannot read its own allow-list must refuse to run (exit 2).
    # It must never report "clean" on a tree it could not scan under the
    # shared rules, and it must never abort with a different, ambiguous code.

    @POSIX_RUNNER
    def test_posix_audit_missing_allowlist_is_usage_error_with_no_targets(self, tmp_path):
        scripts = _copy_shipped_scripts(tmp_path)
        (scripts / "payload_scan_allowlist.txt").unlink()
        root = tmp_path / "empty"
        root.mkdir()
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, [])
        result = _run_sh_from(scripts / "payload_audit.sh", root, manifest)
        assert result.returncode == 2, result.stdout + result.stderr

    @POSIX_RUNNER
    def test_posix_audit_missing_allowlist_is_usage_error_with_a_target(self, tmp_path):
        scripts = _copy_shipped_scripts(tmp_path)
        (scripts / "payload_scan_allowlist.txt").unlink()
        root, manifest = _scanner_self_tree(tmp_path)
        result = _run_sh_from(scripts / "payload_audit.sh", root, manifest)
        assert result.returncode == 2, result.stdout + result.stderr

    @PS_HOST
    def test_powershell_audit_missing_allowlist_is_usage_error(self, tmp_path):
        scripts = _copy_shipped_scripts(tmp_path)
        (scripts / "payload_scan_allowlist.txt").unlink()
        root, manifest = _scanner_self_tree(tmp_path)
        result = _run_ps_from(scripts / "payload_audit.ps1", root, manifest)
        assert result.returncode == 2, result.stdout + result.stderr

    @PS_HOST
    @pytest.mark.skipif(
        not hasattr(os, "geteuid") or os.geteuid() == 0,
        reason="root can read mode-000 files; the readability probe needs a normal user",
    )
    def test_powershell_audit_unreadable_allowlist_is_usage_error(self, tmp_path):
        """Existence is not readability: an unreadable list exits 2, not 1."""
        scripts = _copy_shipped_scripts(tmp_path)
        (scripts / "payload_scan_allowlist.txt").chmod(0)
        root, manifest = _scanner_self_tree(tmp_path)
        result = _run_ps_from(scripts / "payload_audit.ps1", root, manifest)
        assert result.returncode == 2, result.stdout + result.stderr

    # --- the list is read from the scripts dir, never from the audited tree --
    @POSIX_RUNNER
    def test_posix_ignores_an_allowlist_in_the_audited_root(self, tmp_path):
        """An audited stage must never be able to supply its own exemptions."""
        root = tmp_path / "stage"
        _build_tree(
            root,
            {"app/main.py": FAKE_OPENAI_KEY + "\n", "payload_scan_allowlist.txt": "app/main.py\n"},
        )
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py"])
        result = _run_audit(root, manifest)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "app/main.py:1: openai-key" in result.stdout

    @PS_HOST
    def test_powershell_ignores_an_allowlist_in_the_audited_root(self, tmp_path):
        root = tmp_path / "stage"
        _build_tree(
            root,
            {"app/main.py": FAKE_OPENAI_KEY + "\n", "payload_scan_allowlist.txt": "app/main.py\n"},
        )
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, ["app/main.py"])
        result = _run_ps_audit(root, manifest)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "app/main.py:1: openai-key" in result.stdout

    @POSIX_RUNNER
    def test_posix_allowlist_tolerates_a_crlf_checkout(self, tmp_path):
        """A CRLF checkout must not silently disable the shared list.

        ``read`` keeps the carriage return, so every entry would stop matching
        and the POSIX gate would reject the shipped scanner again.
        """
        scripts = _copy_shipped_scripts(tmp_path)
        allowlist = scripts / "payload_scan_allowlist.txt"
        allowlist.write_bytes(allowlist.read_bytes().replace(b"\n", b"\r\n"))
        root, manifest = _scanner_self_tree(tmp_path)
        result = _run_sh_from(scripts / "payload_audit.sh", root, manifest)
        assert result.returncode == 0, result.stdout + result.stderr

    @POSIX_RUNNER
    def test_posix_no_default_allowlist_still_disables_the_shared_list(self, tmp_path):
        root, manifest = _scanner_self_tree(tmp_path)
        result = _run_audit(root, manifest, "--no-default-allowlist")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "content_scan.py:48: author-path" in result.stdout
