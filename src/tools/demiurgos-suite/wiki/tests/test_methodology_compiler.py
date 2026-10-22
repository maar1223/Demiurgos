"""RED/unit tests for the methodology compiler boundary.

The compiler turns an author-authored methodology manifest + markdown source
into a bounded runtime contract. Malformed manifests and authority-claiming
content (anything that tries to take over kernel-owned fields such as
authorization, allowlisted targets, minimums, or phase safety) must be
rejected without any side effect. The compiler is pure: it reads strings and
returns a result; it never writes to the filesystem, canon, or runtime.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

REPO_ROOT = _WIKI.parents[3]

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


class TestInventoryFields:
    """Taller de Herramientas Fase 1: optional inventory metadata.

    Inventory fields are validated, stored on the compiled contract, and
    explicitly EXCLUDED from the digest canonical (metadata, not identity).
    """

    def test_valid_taller_is_stored(self) -> None:
        manifest = dict(_valid_manifest(), taller="Creación")
        result = _compile(manifest, _valid_source())
        assert result.ok, result.issues
        assert result.compiled is not None
        assert result.compiled.taller == "Creación"

    def test_missing_taller_defaults_to_none(self) -> None:
        result = _compile(_valid_manifest(), _valid_source())
        assert result.ok
        assert result.compiled is not None
        assert result.compiled.taller is None

    def test_oversized_taller_is_rejected(self) -> None:
        manifest = dict(
            _valid_manifest(), taller="x" * (methodology_compiler.MAX_TALLER_LEN + 1),
        )
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "oversized" and issue.field == "taller"
                   for issue in result.issues)

    def test_non_string_taller_is_rejected(self) -> None:
        manifest = dict(_valid_manifest(), taller=123)
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "invalid-value" and issue.field == "taller"
                   for issue in result.issues)

    def test_valid_talleres_compatibles_are_stored(self) -> None:
        manifest = dict(_valid_manifest(), talleres_compatibles=["Investigación", "Diseño"])
        result = _compile(manifest, _valid_source())
        assert result.ok, result.issues
        assert result.compiled is not None
        assert result.compiled.talleres_compatibles == ("Investigación", "Diseño")

    def test_too_many_talleres_compatibles_are_rejected(self) -> None:
        many = [f"t{i}" for i in range(methodology_compiler.MAX_TALLERES_COMPATIBLES + 1)]
        result = _compile(dict(_valid_manifest(), talleres_compatibles=many), _valid_source())
        assert not result.ok
        assert any(issue.code == "invalid-value" and issue.field == "talleres_compatibles"
                   for issue in result.issues)

    def test_oversized_taller_item_is_rejected(self) -> None:
        manifest = dict(
            _valid_manifest(),
            talleres_compatibles=["x" * (methodology_compiler.MAX_TALLER_LEN + 1)],
        )
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "oversized" and issue.field == "talleres_compatibles"
                   for issue in result.issues)

    def test_empty_taller_item_is_rejected(self) -> None:
        manifest = dict(_valid_manifest(), talleres_compatibles=["Investigación", ""])
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "invalid-value" and issue.field == "talleres_compatibles"
                   for issue in result.issues)

    def test_non_list_talleres_compatibles_are_rejected(self) -> None:
        """A bare string must not be iterated as characters."""
        manifest = dict(_valid_manifest(), talleres_compatibles="Investigación")
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "invalid-value" and issue.field == "talleres_compatibles"
                   for issue in result.issues)

    def test_valid_categoria_funcional_is_stored(self) -> None:
        manifest = dict(_valid_manifest(), categoria_funcional="Investigación")
        result = _compile(manifest, _valid_source())
        assert result.ok, result.issues
        assert result.compiled is not None
        assert result.compiled.categoria_funcional == "Investigación"

    def test_invalid_categoria_funcional_is_rejected(self) -> None:
        manifest = dict(_valid_manifest(), categoria_funcional="Random")
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "invalid-value" and issue.field == "categoria_funcional"
                   for issue in result.issues)

    def test_valid_etiquetas_are_stored(self) -> None:
        manifest = dict(_valid_manifest(), etiquetas=["lore", "npc"])
        result = _compile(manifest, _valid_source())
        assert result.ok, result.issues
        assert result.compiled is not None
        assert result.compiled.etiquetas == ("lore", "npc")

    def test_too_many_etiquetas_are_rejected(self) -> None:
        many = [f"e{i}" for i in range(methodology_compiler.MAX_ETIQUETAS + 1)]
        result = _compile(dict(_valid_manifest(), etiquetas=many), _valid_source())
        assert not result.ok
        assert any(issue.code == "invalid-value" and issue.field == "etiquetas"
                   for issue in result.issues)

    def test_oversized_etiqueta_is_rejected(self) -> None:
        manifest = dict(
            _valid_manifest(),
            etiquetas=["x" * (methodology_compiler.MAX_ETIQUETA_LEN + 1)],
        )
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "oversized" and issue.field == "etiquetas"
                   for issue in result.issues)

    def test_empty_etiqueta_is_rejected(self) -> None:
        manifest = dict(_valid_manifest(), etiquetas=["lore", ""])
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "invalid-value" and issue.field == "etiquetas"
                   for issue in result.issues)

    def test_digest_is_stable_across_inventory_fields(self) -> None:
        """Inventory metadata must never change the canonical digest."""
        base = _compile(_valid_manifest(), _valid_source())
        with_inventory = _compile(dict(
            _valid_manifest(),
            taller="Creación",
            talleres_compatibles=["Investigación"],
            categoria_funcional="Análisis",
            etiquetas=["lore", "npc"],
        ), _valid_source())
        assert base.compiled is not None and with_inventory.compiled is not None
        assert base.compiled.digest == with_inventory.compiled.digest

    def test_as_dict_exposes_inventory_fields(self) -> None:
        manifest = dict(
            _valid_manifest(),
            taller="Creación",
            talleres_compatibles=["Investigación"],
            categoria_funcional="Análisis",
            etiquetas=["lore"],
        )
        result = _compile(manifest, _valid_source())
        assert result.ok
        assert result.compiled is not None
        data = result.compiled.as_dict()
        assert data["taller"] == "Creación"
        assert data["talleres_compatibles"] == ["Investigación"]
        assert data["categoria_funcional"] == "Análisis"
        assert data["etiquetas"] == ["lore"]

    def test_clasificacion_in_manifest_is_rejected(self) -> None:
        """System-derived classification is not author-claimable."""
        manifest = dict(_valid_manifest(), clasificacion="Oficiales")
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert any(issue.code == "unknown-field" and issue.field == "clasificacion"
                   for issue in result.issues)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_adjunto(
    *,
    path: str = "ejemplos/Axill_Garner.md",
    sha256: str | None = None,
    byte_count: int = 6115,
    nivel: str = "1º",
) -> dict:
    """One well-formed attachment entry per contract §4 (SR4)."""
    return {
        "path": path,
        "sha256": sha256 if sha256 is not None else _sha256(b"attachment bytes"),
        "bytes": byte_count,
        "nivel": nivel,
    }


class TestAdjuntosField:
    """Contract §4 (SR4): SHA-256-pinned ``adjuntos`` entries on the manifest.

    Entries carry exactly ``path``/``sha256``/``bytes``/``nivel``; violations
    surface as house-style ``MethodologyIssue`` codes naming the ``adjuntos``
    field. The compiler never raises on bad manifests.
    """

    def test_valid_entry_compiles_and_is_exposed(self) -> None:
        entry = _valid_adjunto()
        result = _compile(dict(_valid_manifest(), adjuntos=[entry]), _valid_source())
        assert result.ok, result.issues
        assert result.compiled is not None
        assert result.compiled.adjuntos == (
            methodology_compiler.AttachmentEntry(
                path=entry["path"],
                sha256=entry["sha256"],
                bytes=entry["bytes"],
                nivel=entry["nivel"],
            ),
        )
        data = result.compiled.as_dict()
        assert data["adjuntos"] == [entry]

    def test_missing_adjuntos_defaults_to_empty(self) -> None:
        result = _compile(_valid_manifest(), _valid_source())
        assert result.ok
        assert result.compiled is not None
        assert result.compiled.adjuntos == ()

    @pytest.mark.parametrize("extra_key", ["titulo", "id"])
    def test_unknown_entry_key_is_rejected(self, extra_key: str) -> None:
        entry = dict(_valid_adjunto(), **{extra_key: "x"})
        result = _compile(dict(_valid_manifest(), adjuntos=[entry]), _valid_source())
        assert not result.ok
        assert any(issue.code == "unknown-field" and issue.field == "adjuntos"
                   for issue in result.issues), result.issues

    @pytest.mark.parametrize("missing", ["path", "sha256", "bytes", "nivel"])
    def test_missing_entry_key_is_rejected(self, missing: str) -> None:
        entry = dict(_valid_adjunto())
        entry.pop(missing)
        result = _compile(dict(_valid_manifest(), adjuntos=[entry]), _valid_source())
        assert not result.ok
        assert any(issue.code == "missing-field" and issue.field == "adjuntos"
                   for issue in result.issues), result.issues

    def test_non_hex_sha256_is_rejected(self) -> None:
        entry = dict(_valid_adjunto(), sha256="nothex")
        result = _compile(dict(_valid_manifest(), adjuntos=[entry]), _valid_source())
        assert not result.ok
        assert any(issue.code == "invalid-value" and issue.field == "adjuntos"
                   for issue in result.issues), result.issues

    @pytest.mark.parametrize("path", [
        "mundos/nec/referencias/Korrane.md",
        "mundos/nec/ejemplos/Axill.md",
        "referencias/lore.md",
    ])
    def test_path_under_reserved_prefixes_is_rejected(self, path: str) -> None:
        """Attachment paths never live under ``mundos/**``/``referencias/**``."""
        entry = dict(_valid_adjunto(), path=path)
        result = _compile(dict(_valid_manifest(), adjuntos=[entry]), _valid_source())
        assert not result.ok
        assert any(issue.code == "invalid-value" and issue.field == "adjuntos"
                   for issue in result.issues), result.issues

    def test_eight_entries_are_accepted(self) -> None:
        many = [_valid_adjunto(path=f"ejemplos/e{i}.md") for i in range(8)]
        result = _compile(dict(_valid_manifest(), adjuntos=many), _valid_source())
        assert result.ok, result.issues

    def test_more_than_eight_entries_is_rejected(self) -> None:
        many = [_valid_adjunto(path=f"ejemplos/e{i}.md") for i in range(9)]
        result = _compile(dict(_valid_manifest(), adjuntos=many), _valid_source())
        assert not result.ok
        assert any(issue.code == "invalid-value" and issue.field == "adjuntos"
                   for issue in result.issues), result.issues

    def test_entry_over_byte_limit_is_rejected(self) -> None:
        entry = _valid_adjunto(byte_count=12_289)
        result = _compile(dict(_valid_manifest(), adjuntos=[entry]), _valid_source())
        assert not result.ok
        assert any(issue.code == "oversized" and issue.field == "adjuntos"
                   for issue in result.issues), result.issues


class TestAdjuntosDigestExclusion:
    """Locked D1 (discovery #3173): attachments never enter the digest canonical.

    Per-attachment ``sha256`` IS the contract pin; adding or removing
    ``adjuntos`` must never change a skill's methodology digest.
    """

    def test_digest_is_stable_across_adjuntos(self) -> None:
        base = _compile(_valid_manifest(), _valid_source())
        with_adjuntos = _compile(
            dict(_valid_manifest(), adjuntos=[_valid_adjunto()]),
            _valid_source(),
        )
        assert base.compiled is not None and with_adjuntos.compiled is not None
        assert base.compiled.digest == with_adjuntos.compiled.digest

    def test_seed_canonical_digest_is_unchanged_with_adjuntos(self) -> None:
        """Regression pin: ``narrative-character-creation@1.2`` stays ``5a28ca7a…``."""
        seed_dir = (
            REPO_ROOT / "data" / "methodology" / "seeds"
            / "narrative-character-creation"
        )
        manifest = parse_manifest((seed_dir / "manifest.yaml").read_text(encoding="utf-8"))
        source = (seed_dir / "source.md").read_text(encoding="utf-8")
        assert manifest is not None
        plain = _compile(manifest, source)
        with_adjuntos = _compile(
            dict(manifest, adjuntos=[_valid_adjunto()]), source,
        )
        assert plain.compiled is not None and with_adjuntos.compiled is not None
        assert plain.compiled.digest == "5a28ca7af37221b01db1b436e944ece752cbcea5af5669cef14577702b739bb4"
        assert with_adjuntos.compiled.digest == plain.compiled.digest


class TestGuidedFlowDeclaration:
    """S1: a methodology may declare its guided flow; the kernel validates it."""

    @staticmethod
    def _guided_flow() -> dict:
        return {
            "flow_id": "guided-system",
            "entity_type": "sistema",
            "ui_copy_key": "system",
            "index": True,
            "intent": {"terms": ["sistema"], "verbs": ["crear", "diseñar"]},
        }

    def test_valid_declaration_is_carried_in_the_contract(self) -> None:
        manifest = dict(_valid_manifest())
        manifest["guided_flow"] = self._guided_flow()
        result = _compile(manifest, _valid_source())
        assert result.ok, result.issues
        assert result.compiled is not None
        declaration = result.compiled.guided_flow
        assert declaration is not None
        assert declaration.flow_id == "guided-system"
        assert declaration.entity_type == "sistema"
        assert result.compiled.as_dict()["guided_flow"]["intent"]["verbs"] == [
            "crear", "diseñar",
        ]

    def test_declaration_is_part_of_the_digest(self) -> None:
        plain = _compile(_valid_manifest(), _valid_source())
        declared_manifest = dict(_valid_manifest())
        declared_manifest["guided_flow"] = self._guided_flow()
        declared = _compile(declared_manifest, _valid_source())
        assert plain.ok and declared.ok
        assert plain.compiled.digest != declared.compiled.digest

    def test_absent_declaration_keeps_the_pre_existing_digest(self) -> None:
        # Conditional inclusion: adding the field to the schema must not change
        # the digest of any already-published record (the character seed).
        manifest = _valid_manifest()
        result = _compile(manifest, _valid_source())
        canonical = {
            "skill_id": manifest["skill_id"],
            "version": manifest["version"],
            "name": manifest["name"],
            "description": manifest["description"],
            "phases": manifest["phases"],
            "language": manifest["language"],
            "source": _valid_source(),
        }
        expected = hashlib.sha256(
            json.dumps(
                canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        assert result.compiled.digest == expected

    def test_kernel_owned_fields_are_rejected(self) -> None:
        for key in ("target_section", "minimums", "persistence"):
            manifest = dict(_valid_manifest())
            manifest["guided_flow"] = {**self._guided_flow(), key: "x"}
            result = _compile(manifest, _valid_source())
            assert not result.ok
            assert any(issue.code == "unknown-field" for issue in result.issues)

    def test_incomplete_declaration_fails_closed(self) -> None:
        manifest = dict(_valid_manifest())
        manifest["guided_flow"] = {"flow_id": "guided-system"}
        result = _compile(manifest, _valid_source())
        assert not result.ok
        assert {issue.code for issue in result.issues} == {"missing-field"}
