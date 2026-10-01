# -*- coding: utf-8 -*-
"""Payload audit tests (design v2 S5-3 / tasks 8.1) — the release gate.

Drives ``scripts/payload_audit.sh`` against fixture trees: deny-by-path
rejects every named deny entry, the content scan rejects planted secret
patterns inside ALLOWED files, a clean tree passes, and the audit is genuinely
default-DENY (a path not in the manifest is rejected). No network tools are
invoked — the audit and its content-scan dependency are local scripts.

All planted values are obviously fake (the ``TESTONLY`` marker) — never real
credentials and never real author data. The audit must never echo a matched
value, and the tests assert that.
"""

import json
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[4]
_AUDIT = _REPO_ROOT / "scripts" / "payload_audit.sh"

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
FAKE_AUTHOR_ID = "<telegram-id>"

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
    (FAKE_AUTHOR_ID, "author-id"),
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