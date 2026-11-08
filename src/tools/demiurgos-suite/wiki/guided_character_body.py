# -*- coding: utf-8 -*-
"""Render a guided character sheet body from its narrative-level specimen.

The pinned carriers under ``data/methodology/seeds/narrative-character-creation``
(``adjunto-nivel-{1,2,3}-*.md``) are the format authority for the body. This
module copies their STRUCTURE and LABELS only: the illustrative prose in the
carriers is never read as content. The manifest SHA-256 pins guard the bytes,
and ``test_guided_character_body.py`` asserts every label used here still exists
in its pinned carrier, so carrier drift is caught instead of silently tolerated.

The body is Markdown, never a YAML dump: the sheet reads like the specimen and
provenance stays in the frontmatter (``guided_character_domain.serialize_entity``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

PENDING = "_(pendiente)_"
"""Visible gap marker for a canonical label the session has not collected yet."""

_FALLBACK_HEADING = "Otros datos"
_RELATIONS_HEADING = "Relaciones"
_UNRESOLVED_HEADING = "Referencias sin resolver"

#: Internal session metadata keys that must never become ficha content.
_META_KEYS = frozenset({
    "intencion", "intent", "mundo", "world", "estado", "status",
    "fase", "phase", "modo", "mode", "nivel", "nivel_narrativo",
    "rol_narrativo", "rol narrativo", "nivel narrativo",
})


@dataclass(frozen=True)
class Field:
    """One canonical label and the candidate keys that can fill it."""

    label: str
    probes: tuple[str, ...]
    prose: bool = False


@dataclass(frozen=True)
class Section:
    """A specimen section: an optional heading plus its ordered fields."""

    heading: str | None
    fields: tuple[Field, ...]
    bullet: bool = False
    intro: str | None = None


# ---------------------------------------------------------------------------
# Specimens (structure + labels only, derived from the pinned carriers)
# ---------------------------------------------------------------------------

_LEVEL_1: tuple[Section, ...] = (
    Section("Identidad Base", (
        Field("Nombre", ("nombre", "name", "title")),
        Field("Apodo", ("apodo", "apodos", "nickname", "alias")),
        Field("Edad", ("edad", "age")),
        Field("Raza/Especie", ("raza", "raza_especie", "especie", "race", "species")),
        Field("Lugar de origen", ("lugar_origen", "lugar de origen", "origen", "origin", "procedencia")),
        Field("Género", ("genero", "género", "gender")),
        Field("Sexualidad", ("sexualidad", "sexuality")),
        Field("Familia", ("familia", "family")),
        Field("Estudios", ("estudios", "formacion", "formación", "education")),
        Field("Trabajo", ("trabajo", "oficio", "ocupacion", "ocupación", "profesion", "profesión", "job", "profession")),
        Field("Religión", ("religion", "religión")),
        Field("Posesiones valiosas", ("posesiones", "posesiones_valiosas", "possessions")),
        Field("Metas", ("metas", "meta", "objetivo", "goal")),
    ), bullet=True),
    Section("Aspecto Físico", (
        Field("Aspecto Físico", ("aspecto_fisico", "aspecto físico", "aspecto", "apariencia", "fisico", "físico", "appearance"), prose=True),
    ),),
    Section("Psicología y Carácter", (
        Field("Virtudes", ("virtudes", "virtues")),
        Field("Defectos", ("defectos", "defects", "flaws")),
        Field("Adora", ("adora", "loves")),
        Field("Odia", ("odia", "hates")),
        Field("Teme", ("teme", "temor", "miedo", "fear")),
        Field("Fortalezas", ("fortalezas", "strengths")),
        Field("Debilidades", ("debilidades", "debilidad", "weaknesses")),
    ), bullet=True),
    Section("Psique (sistema)", (
        Field("Eneatipo", ("eneatipo", "enneatype", "eneagrama")),
        Field("Subtipo", ("subtipo", "subtype")),
        Field("Arquetipo", ("arquetipo", "archetype")),
        Field("Alineamiento inicial", ("alineamiento_inicial", "alineamiento inicial")),
        Field("Alineamiento revelado", ("alineamiento_revelado", "alineamiento revelado")),
    ), bullet=True),
    Section("Motivaciones", (
        Field("Deseo", ("deseo", "desire", "deseo_definidor")),
        Field("Conflicto interno", ("conflicto_interno", "conflicto interno")),
        Field("Conflicto externo", ("conflicto_externo", "conflicto externo")),
        Field("Rol en la historia", ("rol_historia", "rol en la historia", "rol_en_la_historia", "rol", "funcion", "función", "role", "function")),
    ), bullet=True),
    Section("Trasfondo", (
        Field("Trasfondo", ("trasfondo", "background", "pasado"), prose=True),
    ),),
    Section("Arco de Personaje", (
        Field("Arco", ("arco", "arc", "arco_personaje", "arco de personaje")),
        Field("Acto I", ("acto_i", "acto i", "acto_1", "acto 1")),
        Field("Acto II1", ("acto_ii1", "acto ii1", "acto_2_1")),
        Field("Acto II2", ("acto_ii2", "acto ii2", "acto_2_2")),
        Field("Acto III", ("acto_iii", "acto iii", "acto_3", "acto 3")),
    ), bullet=True),
)

_LEVEL_2: tuple[Section, ...] = (
    Section(None, (
        Field("Nombre", ("nombre", "name", "title")),
        Field("Rol narrativo", ("rol_narrativo", "rol narrativo")),
        Field("Deseo", ("deseo", "desire", "deseo_definidor")),
        Field("Edad", ("edad", "age")),
        Field("Raza", ("raza", "raza_especie", "especie", "race", "species")),
        Field("Lugar de origen", ("lugar_origen", "lugar de origen", "origen", "origin", "procedencia")),
        Field("Género", ("genero", "género", "gender")),
        Field("Estudios", ("estudios", "formacion", "formación", "education")),
        Field("Trabajo", ("trabajo", "oficio", "ocupacion", "ocupación", "profesion", "profesión", "job", "profession")),
        Field("Religión", ("religion", "religión")),
        Field("Relación con el protagonista", ("relacion_protagonista", "relación con el protagonista", "relacion_con_el_protagonista", "relacion", "relación", "vinculo", "vínculo")),
        Field("Aspecto físico (con algún defecto)", ("aspecto_fisico", "aspecto físico", "aspecto", "apariencia", "fisico", "físico", "appearance")),
        Field("Virtudes", ("virtudes", "virtues")),
        Field("Defectos", ("defectos", "defects", "flaws")),
        Field("Adora", ("adora", "loves")),
        Field("Odia", ("odia", "hates")),
        Field("Teme", ("teme", "temor", "miedo", "fear")),
        Field("Arquetipo", ("arquetipo", "archetype")),
        Field("Rol en la historia (función)", ("rol_historia", "rol en la historia", "rol_en_la_historia", "rol", "funcion", "función", "role", "function")),
        Field("Mini-arc", ("mini_arc", "mini-arc", "miniarc")),
        Field("Trasfondo", ("trasfondo", "background", "pasado")),
    ), intro="Ficha de personaje:"),
)

_LEVEL_3: tuple[Section, ...] = (
    Section(None, (
        Field("Nombre", ("nombre", "name", "title")),
        Field("Función (rol en la escena)", ("funcion_escena", "función en la escena", "rol en la escena", "rol_escena", "funcion", "función", "function")),
        Field("Rasgo distintivo", ("rasgo_distintivo", "rasgo distintivo", "rasgo", "distinctive_trait")),
        Field("Arquetipo", ("arquetipo", "archetype")),
        Field("Aparición / vínculo", ("aparicion", "aparición", "aparicion_vinculo", "vinculo", "vínculo")),
    ), intro="Ficha de personaje:"),
)

_LEVELS: dict[str, tuple[Section, ...]] = {
    "1º": _LEVEL_1,
    "2º": _LEVEL_2,
    "3º": _LEVEL_3,
}


def labels_for(nivel: str) -> tuple[str, ...]:
    """Every canonical label the renderer writes for ``nivel`` (S6 drift check)."""
    return tuple(field.label for section in _LEVELS.get(nivel, _LEVEL_1) for field in section.fields)


# ---------------------------------------------------------------------------
# Candidate value helpers
# ---------------------------------------------------------------------------


def _plain(value: Any) -> str:
    """Unwrap a candidate record and render it as readable text."""
    if value is None:
        return ""
    if isinstance(value, Mapping):
        if "value" in value:
            return _plain(value["value"])
        return "; ".join(
            f"{key}: {_plain(item)}" for key, item in value.items() if _plain(item)
        )
    if isinstance(value, (list, tuple)):
        return "; ".join(_plain(item) for item in value if _plain(item))
    return str(value).strip()


def _value_for(known: Mapping[str, Any], probes: tuple[str, ...]) -> str:
    for probe in probes:
        if probe in known:
            text = _plain(known[probe])
            if text:
                return text
    return ""


def _unwrap_records(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value.get("value", value) if isinstance(value, Mapping) else value
            for key, value in mapping.items()}


def _extra_fields(candidate: Any, consumed: set[str]) -> list[tuple[str, str]]:
    """Unmapped accepted-canon/proposal fields, rendered instead of dropped (S2)."""
    extras: list[tuple[str, str]] = []
    for source in (candidate.accepted_canon, candidate.proposals):
        for key, raw in _unwrap_records(source).items():
            normalized = str(key).strip()
            if not normalized or normalized.casefold() in consumed or normalized.casefold() in _META_KEYS:
                continue
            value = _plain(raw)
            if not value:
                continue
            extras.append((normalized.replace("_", " ").capitalize(), value))
            consumed.add(normalized.casefold())
    return extras


def _evidence(records: list[Any]) -> str:
    lines = []
    for record in records:
        value = record.get("value", record) if isinstance(record, Mapping) else record
        text = _plain(value)
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def render_character_body(candidate: Any) -> str:
    """Render the sheet body for the candidate's resolved narrative level (S1)."""
    # Imported lazily: ``guided_character_domain`` imports this module at module
    # level to wire the serializer, so the reverse import must stay local.
    from guided_character_domain import _candidate_known_fields, resolve_candidate_nivel

    nivel = resolve_candidate_nivel(candidate)
    sections = _LEVELS.get(nivel, _LEVEL_1)
    known = _candidate_known_fields(candidate)
    consumed: set[str] = set()
    blocks: list[str] = []

    for section in sections:
        if section.intro:
            blocks.append(section.intro)
        lines: list[str] = []
        for field in section.fields:
            consumed.update(probe.casefold() for probe in field.probes)
            text = _value_for(known, field.probes) or PENDING
            if field.prose:
                lines.append(text)
            elif section.bullet:
                lines.append(f"- **{field.label}:** {text}")
            else:
                lines.append(f"**{field.label}:** {text}")
        body = "\n".join(lines)
        if section.heading:
            blocks.append(f"## {section.heading}\n\n{body}")
        else:
            blocks.append(body)

    extras = _extra_fields(candidate, consumed)
    if extras:
        blocks.append("## " + _FALLBACK_HEADING + "\n\n" + "\n".join(
            f"- **{label}:** {value}" for label, value in extras
        ))

    conflicts = _evidence(candidate.conflicts)
    if conflicts:
        blocks.append(f"## {_RELATIONS_HEADING}\n\n{conflicts}")
    unresolved = _evidence(candidate.unresolved_references)
    if unresolved:
        blocks.append(f"## {_UNRESOLVED_HEADING}\n\n{unresolved}")

    return "\n\n".join(block.strip() for block in blocks if block.strip()) + "\n"
