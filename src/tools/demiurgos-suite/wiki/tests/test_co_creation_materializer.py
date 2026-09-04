"""Focused tests for deterministic server-side draft materialization.

Covers: deterministic template rendering, ``create_draft`` called with the
correct fields, ``compile_draft`` issues surfaced, and the hard rule that the
materializer NEVER publishes without explicit Author approval.
"""

from __future__ import annotations

from pathlib import Path
import sys

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from methodology_library import MethodologyLibrary  # noqa: E402
from co_creation_materializer import (  # noqa: E402
    DEFAULT_SOURCE_TEMPLATE,
    CoCreationMaterializer,
    MaterializationResult,
    ValidateResult,
)


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