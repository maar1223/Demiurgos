"""RED/unit tests for the methodology compiler boundary.

The compiler turns an author-authored methodology manifest + markdown source
into a bounded runtime contract. Malformed manifests and authority-claiming
content (anything that tries to take over kernel-owned fields such as
authorization, allowlisted targets, minimums, or phase safety) must be
rejected without any side effect. The compiler is pure: it reads strings and
returns a result; it never writes to the filesystem, canon, or runtime.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import methodology_compiler  # noqa: E402
from methodology_compiler import (  # noqa: E402
    CompiledMethodology,
    compile_methodology,
    parse_manifest,
)


def _valid_manifest() -> dict:
    return {
        "skill_id": "guided-character-v1",
        "version": "1.2.0",
        "name": "Guided character methodology",
        "description": "A safe construction methodology for guided characters.",
        "phases": ["conversation", "review", "complete"],
        "language": "es",
    }


def _valid_source() -> str:
    return (
        "## Construcción segura\n\n"
        "Haz preguntas de a una. Nunca inventes identidad ni deseo.\n"
    )


def _compile(manifest: dict, source: str):
    return compile_methodology(manifest, source)


class TestMalformedManifest:
    def test_missing_required_field_is_rejected(self) -> None:
        for missing in ("skill_id", "version", "name"):
            manifest = dict(_valid_manifest())
            manifest.pop(missing)
            result = _compile(manifest, _valid_source())
            assert not result.ok
            codes = {issue.code for issue in result.issues}
            assert "missing-field" in codes, codes

    def test_unknown_manifest_field_is_rejected(self) -> None:
        manifest = dict(_valid_manifest())
        manifest["unexpected"] = "x"
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "unknown-field" for issue in result.issues)

    def test_non_dict_manifest_is_rejected(self) -> None:
        result = _compile("not a manifest", _valid_source())
        assert not result.ok
        assert any(issue.code == "malformed-manifest" for issue in result.issues)

    def test_unparseable_yaml_returns_none(self) -> None:
        assert parse_manifest("skill_id: [unclosed") is None

    def test_empty_manifest_is_rejected(self) -> None:
        result = _compile({}, _valid_source())
        assert not result.ok

    def test_oversized_source_is_rejected(self) -> None:
        source = "x" * (methodology_compiler.MAX_SOURCE_CHARS + 1)
        result = _compile(_valid_manifest(), source)
        assert not result.ok
        assert any(issue.code == "oversized" for issue in result.issues)

    def test_invalid_phase_types_are_rejected(self) -> None:
        manifest = dict(_valid_manifest())
        manifest["phases"] = ["ok", 42]
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "invalid-value" for issue in result.issues)


class TestAuthorityClaimingContent:
    """Kernel-owned fields and authority markers are rejected, not loaded."""

    @pytest.mark.parametrize("field", [
        "authorization", "authorize", "permissions", "permission",
        "allowlisted_targets", "allowlist", "minimums", "phase_safety",
        "compatibility", "persistence", "approval", "gates", "kernel",
        "exec", "commands", "executables", "trust", "activate", "publish",
    ])
    def test_kernel_owned_manifest_field_is_rejected(self, field: str) -> None:
        manifest = dict(_valid_manifest())
        manifest[field] = "granted"
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "authority-claim" for issue in result.issues), field

    @pytest.mark.parametrize("marker", [
        "kernel_authority: true",
        "#!demiurgos-authority",
        "allowlisted_targets: lore",
        "authorization: granted",
        "permissions: all",
        "phase_safety: bypass",
        "grant_authority",
        "override_gates",
    ])
    def test_authority_claiming_source_is_rejected(self, marker: str) -> None:
        source = f"{_valid_source()}\n\n{marker}\n"
        result = _compile(_valid_manifest(), source)
        assert not result.ok
        assert any(issue.code == "authority-claim" for issue in result.issues), marker


class TestBoundedContract:
    def test_valid_manifest_compiles(self) -> None:
        result = _compile(_valid_manifest(), _valid_source())
        assert result.ok, result.issues
        assert result.compiled is not None
        if result.compiled is not None:
            assert result.compiled.skill_id == "guided-character-v1"
            assert result.compiled.version == "1.2.0"
            assert result.compiled.name == "Guided character methodology"
            assert result.compiled.phases == ("conversation", "review", "complete")

    def test_compiled_contract_is_immutable(self) -> None:
        result = _compile(_valid_manifest(), _valid_source())
        assert result.compiled is not None
        with pytest.raises(Exception):
            result.compiled.version = "9.9.9"  # type: ignore[misc]

    def test_digest_is_stable_and_content_sensitive(self) -> None:
        a = _compile(_valid_manifest(), _valid_source())
        b = _compile(_valid_manifest(), _valid_source())
        assert a.compiled is not None and b.compiled is not None
        assert a.compiled.digest == b.compiled.digest
        changed = _compile(_valid_manifest(), _valid_source() + "\n# extra\n")
        assert changed.compiled is not None
        assert changed.compiled.digest != a.compiled.digest

    def test_compiled_contract_carries_digest_identity(self) -> None:
        result = _compile(_valid_manifest(), _valid_source())
        assert result.compiled is not None
        assert isinstance(result.compiled, CompiledMethodology)
        assert len(result.compiled.digest) == 64  # sha256 hex


class TestNoSideEffect:
    def test_compile_never_writes_to_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            probe = Path(tmpdir) / "sentinel.md"
            before = sorted(p.name for p in Path(tmpdir).iterdir())
            _compile(dict(_valid_manifest(), authorization="granted"), _valid_source())
            _compile(_valid_manifest(), _valid_source())
            after = sorted(p.name for p in Path(tmpdir).iterdir())
            assert before == after
            assert not probe.exists(), "compiler must not create files"

    def test_rejected_content_is_surfaced_not_silently_fixed(self) -> None:
        result = _compile(dict(_valid_manifest(), phase_safety="bypass"), _valid_source())
        assert not result.ok
        assert result.compiled is None
        assert all(issue.code in {"authority-claim", "unknown-field"} for issue in result.issues)
