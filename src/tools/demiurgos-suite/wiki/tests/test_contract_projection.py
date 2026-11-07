"""RED/unit tests for the compiled-contract Markdown projection.

Covers: the structured Markdown format for both a ``CompiledMethodology`` and a
``PublishedVersion``, token-budget enforcement (the variable description is
shortened so the output fits ``max_tokens``), and edge cases (empty source,
missing fields, ``None`` input, and ``CompileResult`` unwrapping).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import contract_projection  # noqa: E402
from contract_projection import project_contract_markdown  # noqa: E402
from methodology_compiler import CompiledMethodology, CompileResult  # noqa: E402
from methodology_library import PublishedVersion  # noqa: E402


def _compiled(**overrides) -> CompiledMethodology:
    fields = dict(
        skill_id="guided-character-v1",
        version="1.2.0",
        name="Guided character methodology",
        description="A safe construction methodology for guided characters.",
        phases=("conversation", "review", "complete"),
        language="es",
        source="## Construcción segura\n\nHaz preguntas de a una.\n",
        digest="abc123",
    )
    fields.update(overrides)
    return CompiledMethodology(**fields)


def _published(**overrides) -> PublishedVersion:
    fields = dict(
        skill_id="guided-character-v1",
        version="1.2.0",
        name="Guided character methodology",
        description="A safe construction methodology for guided characters.",
        phases=("conversation", "review", "complete"),
        language="es",
        source="## Construcción segura\n\nHaz preguntas de a una.\n",
        digest="abc123",
        published_at="2026-01-01T00:00:00+00:00",
    )
    fields.update(overrides)
    return PublishedVersion(**fields)


class TestFormat:
    def test_projects_compiled_methodology_markdown(self) -> None:
        out = project_contract_markdown(_compiled())
        assert "## Methodology: Guided character methodology (v1.2.0)" in out
        assert "**Identity**: A safe construction methodology for guided characters." in out
        assert "**Method (behavioral contract)**:" in out
        assert "Haz preguntas de a una." in out
        assert "**Phases (guide, not a rigid sequence)**: conversation → review → complete" in out
        assert "**Conversation contract**:" in out
        assert "- One focused question per turn." in out
        assert "- Before asking, synthesize in 1-3 lines" in out
        assert "- Options are a last resort: at most 3" in out
        assert "- Never ask for information the system can retrieve" in out
        assert "Current Phase" not in out
        assert "Next Action" not in out

    def test_projects_published_version_markdown(self) -> None:
        out = project_contract_markdown(_published())
        assert "## Methodology: Guided character methodology (v1.2.0)" in out
        assert "**Identity**: A safe construction methodology for guided characters." in out
        assert "**Phases (guide, not a rigid sequence)**: conversation → review → complete" in out

    def test_compiled_and_published_render_identically(self) -> None:
        assert project_contract_markdown(_compiled()) == project_contract_markdown(_published())

    def test_method_excerpt_reaches_the_projection(self) -> None:
        out = project_contract_markdown(_compiled(source="## Principio 40/60\n\nEl 40/60 es comportamiento, no cuestionario.\n"))
        assert "El 40/60 es comportamiento, no cuestionario." in out

    def test_frontmatter_and_h1_are_skipped_in_the_excerpt(self) -> None:
        source = "---\nname: x\n---\n\n# Titulo\n\n## Principio\n\nRefleja antes de preguntar.\n"
        out = project_contract_markdown(_compiled(source=source))
        assert "name: x" not in out
        assert "# Titulo" not in out
        assert "Refleja antes de preguntar." in out

    def test_operational_provenance_lines_never_reach_the_excerpt(self) -> None:
        source = "## Metodo\n\ndigest: " + "a" * 64 + "\npath: /secret/world.md\nRefleja antes de preguntar.\n"
        out = project_contract_markdown(_compiled(source=source))
        assert "digest:" not in out
        assert "/secret/world.md" not in out
        assert "Refleja antes de preguntar." in out


class TestTokenBudget:
    def test_typical_contract_fits_default_budget_unchanged(self) -> None:
        out = project_contract_markdown(_compiled())
        assert contract_projection._estimate_tokens(out) <= 1000  # noqa: SLF001
        assert "A safe construction methodology for guided characters." in out

    def test_oversized_description_is_truncated_to_budget(self) -> None:
        huge = _compiled(description="word " * 400)  # 2000 chars ≈ 500 tokens
        out = project_contract_markdown(huge, max_tokens=100)
        assert contract_projection._estimate_tokens(out) <= 100  # noqa: SLF001
        assert out.startswith("## Methodology:")
        # The variable identity content was shortened and marked truncated.
        assert "…" in out
        assert len(out) <= 100 * contract_projection._CHARS_PER_TOKEN  # noqa: SLF001

    def test_output_never_exceeds_budget_for_small_budget(self) -> None:
        out = project_contract_markdown(_compiled(), max_tokens=10)
        assert contract_projection._estimate_tokens(out) <= 10  # noqa: SLF001


class TestEdgeCases:
    def test_empty_source_still_projects(self) -> None:
        out = project_contract_markdown(_compiled(source=""))
        assert out.startswith("## Methodology: Guided character methodology")

    def test_missing_fields_use_safe_defaults(self) -> None:
        out = project_contract_markdown(
            _compiled(name="", version="", description="", phases=()),
        )
        assert "## Methodology: Untitled methodology" in out
        assert "**Identity**: (no description)" in out
        assert "**Phases (guide, not a rigid sequence)**: (none)" in out

    def test_none_returns_empty_string(self) -> None:
        assert project_contract_markdown(None) == ""

    def test_compileresult_is_unwrapped(self) -> None:
        compiled = _compiled()
        result = CompileResult(ok=True, issues=(), compiled=compiled)
        assert project_contract_markdown(result) == project_contract_markdown(compiled)

    def test_failed_compileresult_without_contract_returns_empty(self) -> None:
        from methodology_compiler import MethodologyIssue
        result = CompileResult(ok=False, issues=(MethodologyIssue("oversized", "too big"),), compiled=None)
        assert project_contract_markdown(result) == ""
