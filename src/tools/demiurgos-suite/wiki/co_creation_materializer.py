"""Deterministic server-side draft materialization for co-created skills.

At ``borrador_listo`` (Author-confirmed) the backend assembles the source
Markdown from the session's structured ``draft_payload`` through a fixed
server-side template — Hermes never generates source, which eliminates the
authority-claim risk in compiled source (REQ-CC-5 / REQ-CC-7). This module
calls ``create_draft`` + ``compile_draft`` only, and NEVER calls ``publish``:
publishing happens exclusively through explicit Author approval via the API
layer in a later slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from methodology_compiler import MethodologyIssue, compile_methodology
from methodology_library import MethodologyLibrary


# Deterministic kernel template: fixed shape, plain-string substitution.
DEFAULT_SOURCE_TEMPLATE = """# {name}
{description}

## Propósito
{purpose}

## Alcance
{scope} {world_binding}

## Flujo principal
{main_flow}

## Ramas y reglas
{branches}
{rules}"""

_TEMPLATE_KEYS = (
    "name",
    "description",
    "purpose",
    "scope",
    "main_flow",
    "branches",
    "rules",
    "world_binding",
)


def _render_value(value: object) -> str:
    """Render one template value deterministically.

    Lists (``branches``/``rules`` in the TW12 canvas shape) render as a
    Markdown bullet join — deterministic by construction. Plain strings render
    verbatim (Fase 4 backward compatibility); ``None`` renders empty.
    """
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value)
    return str(value) if value is not None else ""


@dataclass(frozen=True)
class MaterializationResult:
    draft_id: str
    issues: tuple[MethodologyIssue, ...]
    ok: bool

    @property
    def compile_issues(self) -> tuple[MethodologyIssue, ...]:
        """Alias used by the validation panel (REQ-CC-5)."""
        return self.issues


@dataclass(frozen=True)
class ValidateResult:
    """Pre-materialization validation: render + compile, NO draft created."""

    source: str
    issues: tuple[MethodologyIssue, ...]
    ok: bool

    @property
    def compile_issues(self) -> tuple[MethodologyIssue, ...]:
        """Alias used by the validation panel (REQ-CC-13)."""
        return self.issues


class CoCreationMaterializer:
    """Assemble a library draft from structured co-creation answers."""

    def __init__(
        self,
        library: MethodologyLibrary,
        template: str = DEFAULT_SOURCE_TEMPLATE,
    ) -> None:
        self._library = library
        self._template = template

    def render_source(self, payload: Mapping[str, Any]) -> str:
        """Render the deterministic source Markdown for a structured payload.

        Uses sequential plain-string substitution (never ``str.format``) so
        arbitrary author content containing braces or ``$`` cannot break or
        alter the template. Missing fields render as empty sections; list
        fields (``branches``/``rules``) render as a deterministic bullet join.
        """
        values = {key: _render_value(payload.get(key)) for key in _TEMPLATE_KEYS}
        world = payload.get("world")
        values["world_binding"] = f"(mundo: {world})" if world else "(transversal)"
        source = self._template
        for key in _TEMPLATE_KEYS:
            source = source.replace("{" + key + "}", values[key])
        return source.strip() + "\n"

    def validate_payload(self, payload: Mapping[str, Any]) -> ValidateResult:
        """Render + compile a payload WITHOUT creating a library draft.

        REQ-CC-5 / REQ-CC-7 / REQ-CC-12: canvas edits run through the SAME
        deterministic template and compiler as materialization, so validation
        and materialization can never disagree. The manifest is synthesized
        from the payload with the same defaults the materialize route applies;
        nothing is created and nothing is published here.
        """
        source = self.render_source(payload)
        manifest = {
            "skill_id": payload.get("skill_id") or "co-created-skill",
            "version": payload.get("version") or "0.1.0",
            "name": payload.get("name") or "Co-created skill",
            "description": payload.get("description") or "",
            "phases": list(payload.get("phases") or ()),
            "language": payload.get("language"),
            "taller": payload.get("taller"),
            "talleres_compatibles": list(payload.get("talleres_compatibles") or ()),
            "categoria_funcional": payload.get("categoria_funcional"),
            "etiquetas": list(payload.get("etiquetas") or ()),
        }
        compiled = compile_methodology(manifest, source)
        return ValidateResult(
            source=source,
            issues=tuple(compiled.issues),
            ok=compiled.ok,
        )

    def materialize(
        self,
        payload: Mapping[str, Any],
        *,
        skill_id: str,
        version: str,
        name: str,
        description: str = "",
        taller: str | None = None,
        etiquetas: tuple[str, ...] = (),
        categoria_funcional: str | None = None,
        language: str | None = None,
    ) -> MaterializationResult:
        """Create the draft and surface compiler issues.

        Returns the ``draft_id`` plus ``CompileResult.issues`` so the
        validation panel can list each code+message (REQ-CC-5). The draft is
        stored but never published or activated here.
        """
        source = self.render_source(payload)
        draft_id = self._library.create_draft(
            skill_id=skill_id,
            version=version,
            name=name,
            source=source,
            description=description,
            taller=taller,
            etiquetas=tuple(etiquetas),
            categoria_funcional=categoria_funcional,
            language=language,
        )
        compiled = self._library.compile_draft(draft_id)
        return MaterializationResult(
            draft_id=draft_id,
            issues=tuple(compiled.issues),
            ok=compiled.ok,
        )