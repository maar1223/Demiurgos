"""Focused tests for deterministic server-side draft materialization.

Covers: deterministic template rendering, ``create_draft`` called with the
correct fields, ``compile_draft`` issues surfaced, and the hard rule that the
materializer NEVER publishes without explicit Author approval.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from co_creation_materializer import (  # noqa: E402
    DEFAULT_SOURCE_TEMPLATE,
    AttachmentMaterializationError,
    CoCreationMaterializer,
    MaterializationResult,
    ValidateResult,
    move_publish_pins,
    parse_rendered_source,
)
from methodology_library import MethodologyLibrary  # noqa: E402
from methodology_compiler import AttachmentEntry  # noqa: E402


def _library(tmp_path: Path) -> MethodologyLibrary:
    return MethodologyLibrary(tmp_path / "library.json")


def _payload(**overrides: object) -> dict:
    payload = {
        "name": "Mi skill de importación",
        "description": "Automatiza la importación de lore.",
        "purpose": "Reducir el trabajo manual al importar mundos.",
        "scope": "Importación de archivos OKF.",
        "world": "nec",
        "main_flow": "1. Subir archivo 2. Validar 3. Importar.",
        "branches": "Si el archivo es inválido, mostrar errores.",
        "rules": "No sobrescribir lore existente sin confirmación.",
    }
    payload.update(overrides)
    return payload


def test_template_renders_deterministically(tmp_path: Path) -> None:
    materializer = CoCreationMaterializer(_library(tmp_path))
    first = materializer.render_source(_payload())
    second = materializer.render_source(_payload())
    assert first == second
    assert first.startswith("# Mi skill de importación")
    assert "## Propósito" in first
    assert "## Alcance" in first
    assert "## Flujo principal" in first
    assert "## Ramas y reglas" in first
    assert "(mundo: nec)" in first
    assert "No sobrescribir lore existente sin confirmación." in first


def test_template_renders_world_binding_for_transversal(tmp_path: Path) -> None:
    materializer = CoCreationMaterializer(_library(tmp_path))
    source = materializer.render_source(_payload(world=None))
    assert "(transversal)" in source
    assert "(mundo:" not in source


def test_render_source_is_safe_with_braces_in_author_content(tmp_path: Path) -> None:
    materializer = CoCreationMaterializer(_library(tmp_path))
    source = materializer.render_source(_payload(purpose="El usuario quiere {algo} y $vars"))
    assert "{algo}" in source
    assert "$vars" in source
    assert "## Propósito" in source


def test_missing_fields_render_as_empty_sections(tmp_path: Path) -> None:
    materializer = CoCreationMaterializer(_library(tmp_path))
    source = materializer.render_source({"purpose": "Solo propósito."})
    assert "## Propósito" in source
    assert "Solo propósito." in source
    assert "## Alcance" in source
    assert "(transversal)" in source
    assert "## Flujo principal" in source
    assert "## Ramas y reglas" in source
    assert source.startswith("# ") and source.endswith("\n")


def test_materialize_creates_draft_with_correct_fields(tmp_path: Path) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    result = materializer.materialize(
        _payload(),
        skill_id="mi-skill",
        version="0.1.0",
        name="Mi skill de importación",
        description="Automatiza la importación de lore.",
        taller="narrativa",
        etiquetas=("importacion", "lore"),
        categoria_funcional="Análisis",
        language="es",
    )
    assert isinstance(result, MaterializationResult)
    assert result.ok is True
    assert result.issues == ()

    draft = library.get_draft(result.draft_id)
    assert draft is not None
    assert draft.skill_id == "mi-skill"
    assert draft.version == "0.1.0"
    assert draft.name == "Mi skill de importación"
    assert draft.taller == "narrativa"
    assert draft.etiquetas == ("importacion", "lore")
    assert draft.categoria_funcional == "Análisis"
    assert "## Propósito" in draft.source
    assert "Reducir el trabajo manual al importar mundos." in draft.source
    assert "(mundo: nec)" in draft.source


def test_compile_draft_issues_are_surfaced(tmp_path: Path) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    # Author content containing an authority-claim marker must be surfaced by
    # the compiler as an issue, never silently accepted.
    result = materializer.materialize(
        _payload(purpose="Esto requiere authorization: granted"),
        skill_id="mi-skill",
        version="0.1.0",
        name="Mi skill",
    )
    assert result.ok is False
    assert result.compile_issues == result.issues
    assert any(issue.code == "authority-claim" for issue in result.issues)
    assert result.draft_id


def test_materializer_never_publishes_without_approval(tmp_path: Path) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    result = materializer.materialize(
        _payload(),
        skill_id="mi-skill",
        version="0.1.0",
        name="Mi skill de importación",
    )
    assert result.ok is True
    # Zero compiler issues, still NO publish: publishing requires explicit
    # Author approval through the API layer in a later slice.
    assert library.list_published() == []
    assert library.get_published("mi-skill", "0.1.0") is None
    # The materializer surface never exposes a publish path.
    assert not hasattr(materializer, "publish")


def test_default_template_is_the_deterministic_kernel_template() -> None:
    assert "## Propósito" in DEFAULT_SOURCE_TEMPLATE
    assert "## Alcance" in DEFAULT_SOURCE_TEMPLATE
    assert "## Flujo principal" in DEFAULT_SOURCE_TEMPLATE
    assert "## Ramas y reglas" in DEFAULT_SOURCE_TEMPLATE
    assert "{world_binding}" in DEFAULT_SOURCE_TEMPLATE


# ---------------------------------------------------------------------------
# TW12 canvas validation — render + compile WITHOUT creating a draft
# ---------------------------------------------------------------------------

def test_validate_payload_renders_and_compiles_without_draft(tmp_path: Path) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    payload = {
        "name": "Mi skill de importación",
        "description": "Automatiza la importación de lore.",
        "purpose": "Reducir el trabajo manual al importar mundos.",
        "scope": "Importación de archivos OKF.",
        "main_flow": "1. Subir archivo 2. Validar 3. Importar.",
        "branches": ["Si el archivo es inválido, mostrar errores."],
        "rules": ["No sobrescribir lore existente sin confirmación."],
        "world": "nec",
    }
    result = materializer.validate_payload(payload)
    assert isinstance(result, ValidateResult)
    assert result.ok is True
    assert result.issues == ()
    assert result.compile_issues == result.issues
    assert "## Propósito" in result.source
    assert "- Si el archivo es inválido, mostrar errores." in result.source
    assert "(mundo: nec)" in result.source
    # REQ-CC-12: validation NEVER creates a library draft and never publishes.
    assert library.list_drafts() == []
    assert library.list_published() == []


def test_validate_payload_surfaces_compile_issues_without_draft(tmp_path: Path) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    result = materializer.validate_payload(
        _payload(purpose="Esto requiere authorization: granted"),
    )
    assert isinstance(result, ValidateResult)
    assert result.ok is False
    assert result.compile_issues == result.issues
    assert any(issue.code == "authority-claim" for issue in result.issues)
    assert library.list_drafts() == []
    assert library.list_published() == []


def test_render_source_joins_branch_and_rule_lists_deterministically(tmp_path: Path) -> None:
    materializer = CoCreationMaterializer(_library(tmp_path))
    payload = {
        "name": "Skill de ramas",
        "branches": ["rama A", "rama B", "rama C"],
        "rules": ["regla 1", "regla 2"],
    }
    first = materializer.render_source(payload)
    second = materializer.render_source(payload)
    assert first == second
    assert "- rama A\n- rama B\n- rama C" in first
    assert "- regla 1\n- regla 2" in first
    assert "['rama A'" not in first  # never the raw list repr


def test_render_source_keeps_string_lists_backward_compatible(tmp_path: Path) -> None:
    materializer = CoCreationMaterializer(_library(tmp_path))
    source = materializer.render_source(_payload())
    assert "Si el archivo es inválido, mostrar errores." in source
    assert "No sobrescribir lore existente sin confirmación." in source
    assert "- Si el archivo" not in source


# ---------------------------------------------------------------------------
# TW13/TW14 — adaptation seed + server-injected provenance (Phase 2 / PR 2)
# ---------------------------------------------------------------------------

def test_inject_derived_from_drops_client_supplied_provenance(tmp_path: Path) -> None:
    """REQ-CC-20: the client never supplies provenance — a client-supplied
    ``derived_from`` is dropped and replaced by the server identity."""
    materializer = CoCreationMaterializer(_library(tmp_path))
    forged = {
        "name": "Skill hackeada",
        "derived_from": {"skill_id": "evil-skill", "version": "9.9.9"},
    }
    payload, derived_from = materializer.inject_derived_from(
        forged, "real-skill", "1.0.0",
    )
    assert payload == {"name": "Skill hackeada"}
    assert "derived_from" not in payload
    assert derived_from.skill_id == "real-skill"
    assert derived_from.version == "1.0.0"


def test_inject_derived_from_preserves_the_rest_of_the_payload(tmp_path: Path) -> None:
    materializer = CoCreationMaterializer(_library(tmp_path))
    payload, derived_from = materializer.inject_derived_from(
        {"name": "A", "description": "B", "purpose": "C"}, "s", "1.2.0",
    )
    assert payload == {"name": "A", "description": "B", "purpose": "C"}
    assert (derived_from.skill_id, derived_from.version) == ("s", "1.2.0")


def test_inject_derived_from_preserves_adjuntos(tmp_path: Path) -> None:
    """DP-1: only ``derived_from`` is stripped — the seeded pins survive."""
    materializer = CoCreationMaterializer(_library(tmp_path))
    pin = _pin("ejemplo.md", b"# Ejemplo\n")
    payload, _ = materializer.inject_derived_from(
        {
            "name": "A",
            "adjuntos": [pin],
            "derived_from": {"skill_id": "evil", "version": "9.9.9"},
        },
        "s", "1.0.0",
    )
    assert payload["adjuntos"] == [pin]
    assert "derived_from" not in payload


def test_parse_rendered_source_roundtrips_template_output(tmp_path: Path) -> None:
    materializer = CoCreationMaterializer(_library(tmp_path))
    payload = {
        "name": "Mi skill de importación",
        "description": "Automatiza la importación de lore.",
        "purpose": "Reducir el trabajo manual.",
        "scope": "Importación de archivos OKF.",
        "world": "nec",
        "main_flow": "1. Subir 2. Validar 3. Importar.",
        "branches": ["Rama A", "Rama B"],
        "rules": ["Regla 1"],
    }
    source = materializer.render_source(payload)
    parsed = parse_rendered_source(source)
    assert parsed["name"] == "Mi skill de importación"
    assert parsed["description"] == "Automatiza la importación de lore."
    assert parsed["purpose"] == "Reducir el trabajo manual."
    assert parsed["scope"] == "Importación de archivos OKF."
    assert parsed["world"] == "nec"
    assert parsed["main_flow"] == "1. Subir 2. Validar 3. Importar."
    # Known lossiness: branches and rules render as adjacent bullet lists
    # with no separator, so ALL bullets seed into ``branches``.
    assert parsed["branches"] == ["Rama A", "Rama B", "Regla 1"]


def test_parse_rendered_source_handles_transversal_and_empty_sections(tmp_path: Path) -> None:
    source = CoCreationMaterializer(_library(tmp_path)).render_source({"name": "Solo nombre"})
    parsed = parse_rendered_source(source)
    assert parsed["name"] == "Solo nombre"
    assert parsed["scope"] == ""
    assert "world" not in parsed or parsed["world"] is None
    assert "purpose" not in parsed or parsed["purpose"] == ""


def test_parse_rendered_source_non_template_source_never_raises(tmp_path: Path) -> None:
    for weird in ("", "not markdown at all", "# Título\n\ncuerpo libre sin secciones\n", 42):
        parsed = parse_rendered_source(weird)  # type: ignore[arg-type]
        assert isinstance(parsed, dict)


def test_seed_payload_builds_adaptation_canvas_from_published_original(
    tmp_path: Path,
) -> None:
    materializer = CoCreationMaterializer(_library(tmp_path))
    payload = {
        "name": "Skill base",
        "description": "Descripción base.",
        "purpose": "Propósito base.",
        "scope": "Alcance base.",
        "main_flow": "Flujo base.",
        "branches": ["rama base"],
        "rules": ["regla base"],
        "world": "nec",
    }
    source = materializer.render_source(payload)
    seed = materializer.seed_payload(source, name="Skill base", description="Descripción base.")
    assert seed["name"] == "Skill base"
    assert seed["description"] == "Descripción base."
    assert seed["purpose"] == "Propósito base."
    assert seed["scope"] == "Alcance base."
    assert seed["main_flow"] == "Flujo base."
    assert seed["branches"] == ["rama base", "regla base"]
    # The session world binding overrides the parsed one.
    override = materializer.seed_payload(
        source, name="Skill base", description="Descripción base.", world="otro",
    )
    assert override["world"] == "otro"


def test_seed_payload_seeds_parent_exemplar_pins(tmp_path: Path) -> None:
    """EP-1/DP-1: a parent with N pins seeds the same N pins into the canvas."""
    materializer = CoCreationMaterializer(_library(tmp_path))
    data = b"# Ejemplar\n"
    pins = (
        AttachmentEntry(
            path="ejemplo.md", sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data), nivel="1º",
        ),
    )
    source = materializer.render_source(_payload())
    seed = materializer.seed_payload(
        source, name="Skill base", description="Descripción base.", adjuntos=pins,
    )
    assert seed["adjuntos"] == [_pin("ejemplo.md", data)]


def test_seed_payload_omits_adjuntos_key_when_empty(tmp_path: Path) -> None:
    """EP-1: a zero-exemplar seed stays byte-identical — no ``adjuntos`` key."""
    materializer = CoCreationMaterializer(_library(tmp_path))
    source = materializer.render_source(_payload())
    without = materializer.seed_payload(
        source, name="Skill base", description="Descripción base.",
    )
    with_empty = materializer.seed_payload(
        source, name="Skill base", description="Descripción base.", adjuntos=(),
    )
    assert "adjuntos" not in without
    assert without == with_empty


# ---------------------------------------------------------------------------
# S3 — exemplar pins thread through validate + materialize (REQ-CC-25 / AE-3)
# ---------------------------------------------------------------------------


def _pin(path: str, data: bytes, nivel: str = "1º") -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "nivel": nivel,
    }


def _staged(tmp_path: Path, files: list[tuple[str, bytes]]) -> Path:
    staging = tmp_path / "data" / "methodology" / "staging" / "s-1"
    staging.mkdir(parents=True, exist_ok=True)
    for name, data in files:
        (staging / name).write_bytes(data)
    return staging


def test_validate_payload_manifest_synthesizes_adjuntos_without_draft(
    tmp_path: Path,
) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    data = b"# Ejemplar\n"
    result = materializer.validate_payload(_payload(adjuntos=[_pin("ejemplo.md", data)]))
    assert isinstance(result, ValidateResult)
    assert result.ok is True
    assert result.issues == ()
    # REQ-CC-25: preview compiles the pins but never creates a draft.
    assert library.list_drafts() == []


def test_validate_payload_surfaces_bad_adjunto_issue_without_draft(
    tmp_path: Path,
) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    bad = {"path": "ejemplo.md", "sha256": "not-hex", "bytes": 4, "nivel": "1º"}
    result = materializer.validate_payload(_payload(adjuntos=[bad]))
    assert result.ok is False
    assert any(issue.field == "adjuntos" for issue in result.issues)
    assert library.list_drafts() == []


def test_materialize_moves_staged_bytes_and_pins_the_draft(tmp_path: Path) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    first = b"# Uno\n"
    second = b"# Dos\n"
    staging = _staged(tmp_path, [("uno.md", first), ("dos.md", second)])
    attachments = tmp_path / "data" / "methodology" / "attachments"

    result = materializer.materialize(
        _payload(adjuntos=[_pin("uno.md", first), _pin("dos.md", second, "2º")]),
        skill_id="mi-skill",
        version="0.1.0",
        name="Mi skill",
        staging_dir=staging,
        attachments_root=attachments,
    )

    assert result.ok is True
    assert not staging.exists()  # the consumed staging dir is removed
    dest = attachments / "mi-skill"
    assert (dest / "uno.md").read_bytes() == first
    assert (dest / "dos.md").read_bytes() == second
    draft = library.get_draft(result.draft_id)
    assert draft is not None
    assert [entry.as_dict() for entry in draft.adjuntos] == [
        _pin("uno.md", first), _pin("dos.md", second, "2º"),
    ]


def test_materialize_missing_staged_file_fails_closed_without_draft(
    tmp_path: Path,
) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    staging = _staged(tmp_path, [])  # declared pin, no staged bytes
    attachments = tmp_path / "data" / "methodology" / "attachments"

    with pytest.raises(AttachmentMaterializationError) as excinfo:
        materializer.materialize(
            _payload(adjuntos=[_pin("falta.md", b"# x\n")]),
            skill_id="mi-skill", version="0.1.0", name="Mi skill",
            staging_dir=staging, attachments_root=attachments,
        )

    assert excinfo.value.code == "attachment_unavailable"
    assert library.list_drafts() == []
    assert not (attachments / "mi-skill").exists()


def test_materialize_drifted_staged_file_fails_closed_without_draft(
    tmp_path: Path,
) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    staging = _staged(tmp_path, [("drift.md", b"# changed\n")])
    attachments = tmp_path / "data" / "methodology" / "attachments"
    pin = _pin("drift.md", b"# original\n")

    with pytest.raises(AttachmentMaterializationError) as excinfo:
        materializer.materialize(
            _payload(adjuntos=[pin]),
            skill_id="mi-skill", version="0.1.0", name="Mi skill",
            staging_dir=staging, attachments_root=attachments,
        )

    assert excinfo.value.code == "attachment_unavailable"
    assert library.list_drafts() == []
    assert not (attachments / "mi-skill").exists()


def test_materialize_rolls_back_moved_bytes_when_draft_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    data = b"# Uno\n"
    staging = _staged(tmp_path, [("uno.md", data)])
    attachments = tmp_path / "data" / "methodology" / "attachments"

    def _boom(**_kwargs: object) -> str:
        raise RuntimeError("draft store unavailable")

    monkeypatch.setattr(library, "create_draft", _boom)

    with pytest.raises(RuntimeError):
        materializer.materialize(
            _payload(adjuntos=[_pin("uno.md", data)]),
            skill_id="mi-skill", version="0.1.0", name="Mi skill",
            staging_dir=staging, attachments_root=attachments,
        )

    # No partial attachments tree and no draft; staged bytes survive for retry.
    assert not (attachments / "mi-skill").exists()
    assert (staging / "uno.md").read_bytes() == data
    assert library.list_drafts() == []


def test_materialize_with_pins_requires_staging_and_attachments_root(
    tmp_path: Path,
) -> None:
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    with pytest.raises(AttachmentMaterializationError):
        materializer.materialize(
            _payload(adjuntos=[_pin("uno.md", b"# Uno\n")]),
            skill_id="mi-skill", version="0.1.0", name="Mi skill",
        )
    assert library.list_drafts() == []


def test_materialize_without_adjuntos_creates_empty_pins(tmp_path: Path) -> None:
    """Backward compatible: a payload without adjuntos still materializes and
    the draft carries no pins."""
    library = _library(tmp_path)
    materializer = CoCreationMaterializer(library)
    result = materializer.materialize(
        _payload(), skill_id="mi-skill", version="0.1.0", name="Mi skill",
    )
    assert result.ok is True
    assert library.get_draft(result.draft_id).adjuntos == ()


# ---------------------------------------------------------------------------
# U2 — selective publish move: move_publish_pins (EP-3..EP-7 / DP-2)
# ---------------------------------------------------------------------------


def _entry(name: str, data: bytes, nivel: str = "1º") -> AttachmentEntry:
    return AttachmentEntry(
        path=name, sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data), nivel=nivel,
    )


def test_move_publish_pins_is_selective(tmp_path: Path) -> None:
    """EP-3/EP-4: a verifiable pin is skipped (no mutation) while a pending
    staged pin is validated and moved; no pending pin is a pure preserve."""
    published, new = b"# Publicado\n", b"# Nuevo\n"
    attachments = tmp_path / "data" / "methodology" / "attachments"
    dest = attachments / "mi-skill"
    dest.mkdir(parents=True)
    (dest / "viejo.md").write_bytes(published)
    staging = _staged(tmp_path, [("nuevo.md", new)])

    assert move_publish_pins(
        (_entry("viejo.md", published),), skill_id="mi-skill",
        staging_dir=staging, attachments_root=attachments, project_root=tmp_path,
    ) == []
    assert (staging / "nuevo.md").read_bytes() == new  # nothing was consumed

    moved = move_publish_pins(
        (_entry("viejo.md", published), _entry("nuevo.md", new)),
        skill_id="mi-skill", staging_dir=staging,
        attachments_root=attachments, project_root=tmp_path,
    )
    assert [path.name for path in moved] == ["nuevo.md"]
    assert (dest / "nuevo.md").read_bytes() == new
    assert (dest / "viejo.md").read_bytes() == published


def test_move_publish_pins_refuses_byte_drift_with_zero_mutation(tmp_path: Path) -> None:
    """EP-5: an existing destination with different bytes is refused 422 and
    the original carrier bytes survive (zero mutation)."""
    original, incoming = b"# Original\n", b"# Cambiado\n"
    attachments = tmp_path / "data" / "methodology" / "attachments"
    dest = attachments / "mi-skill"
    dest.mkdir(parents=True)
    (dest / "ejemplo.md").write_bytes(original)
    staging = _staged(tmp_path, [("ejemplo.md", incoming)])

    with pytest.raises(AttachmentMaterializationError) as excinfo:
        move_publish_pins(
            (_entry("ejemplo.md", incoming),), skill_id="mi-skill",
            staging_dir=staging, attachments_root=attachments, project_root=tmp_path,
        )

    assert (excinfo.value.status, excinfo.value.code) == (
        422, "attachment_overwrite_refused",
    )
    assert (dest / "ejemplo.md").read_bytes() == original


def test_move_publish_pins_refuses_a_seeded_skill(tmp_path: Path) -> None:
    """EP-6/D5: a seeded carrier refuses any pending pin (preserve-only)."""
    attachments = tmp_path / "data" / "methodology" / "attachments"
    (tmp_path / "data" / "methodology" / "seeds" / "mi-skill").mkdir(parents=True)
    staging = _staged(tmp_path, [("nuevo.md", b"# Nuevo\n")])

    with pytest.raises(AttachmentMaterializationError) as excinfo:
        move_publish_pins(
            (_entry("nuevo.md", b"# Nuevo\n"),), skill_id="mi-skill",
            staging_dir=staging, attachments_root=attachments, project_root=tmp_path,
        )

    assert (excinfo.value.status, excinfo.value.code) == (
        422, "attachment_seed_immutable",
    )
    assert not (attachments / "mi-skill").exists()


def test_move_publish_pins_missing_staged_bytes_leaves_no_partial_tree(
    tmp_path: Path,
) -> None:
    """EP-4: a pending pin without staged bytes fails closed before any move."""
    attachments = tmp_path / "data" / "methodology" / "attachments"
    staging = _staged(tmp_path, [("uno.md", b"# Uno\n")])  # dos.md is absent

    with pytest.raises(AttachmentMaterializationError) as excinfo:
        move_publish_pins(
            (_entry("uno.md", b"# Uno\n"), _entry("dos.md", b"# Dos\n")),
            skill_id="mi-skill", staging_dir=staging,
            attachments_root=attachments, project_root=tmp_path,
        )

    assert excinfo.value.code == "attachment_unavailable"
    assert not (attachments / "mi-skill").exists()
    assert (staging / "uno.md").read_bytes() == b"# Uno\n"  # staged bytes survive