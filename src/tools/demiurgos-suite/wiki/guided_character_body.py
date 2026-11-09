# -*- coding: utf-8 -*-
"""The guided character field plan and the sheet body renderer.

The pinned carriers under ``data/methodology/seeds/narrative-character-creation``
(``adjunto-nivel-{1,2,3}-*.md``) are the format authority. This module copies
their STRUCTURE and LABELS only: the illustrative prose in the carriers is never
read as content. The manifest SHA-256 pins guard the bytes, and
``test_guided_character_body.py`` asserts every label used here still exists in
its pinned carrier, so carrier drift is caught instead of silently tolerated.

One :class:`FieldPlan` per narrative level is the single source of truth for:

- the sheet body (:func:`render_character_body`),
- the field-by-field questionnaire and its progress (the same ordered specs),
- the coverage state (which labels already have a value).

The body is Markdown, never a YAML dump. Only labels with a value are rendered;
the missing ones are a compact ``## Pendientes`` footer. Provider observations
are internal notes: they may fill a canonical label, but they are never dumped
as ficha content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

PENDING_MARKER = "_(pendiente)_"
"""Rendered only when a caller explicitly asks for a gap (kept for compatibility)."""

_FALLBACK_HEADING = "Otros datos"
_PENDING_HEADING = "Pendientes"
_RELATIONS_HEADING = "Relaciones"
_UNRESOLVED_HEADING = "Referencias sin resolver"

#: Internal session metadata keys that must never become ficha content.
_META_KEYS = frozenset({
    "intencion", "intent", "mundo", "world", "estado", "status",
    "fase", "phase", "modo", "mode", "nivel", "nivel_narrativo",
    "rol_narrativo", "rol narrativo", "nivel narrativo",
    # Provider bookkeeping proposals, never ficha content.
    "tipo", "pendientes",
    # Container records already flattened into canonical labels.
    "identidad", "identity",
})


@dataclass(frozen=True)
class Field:
    """One canonical label: its candidate probes and its questionnaire brief."""

    key: str
    label: str
    probes: tuple[str, ...]
    prose: bool = False
    optional: bool = False
    hint: str = ""
    examples: tuple[str, ...] = ()
    #: Whether the questionnaire asks this label. Renderer-only additions keep
    #: the sheet faithful to facts the provider already produced without
    #: widening the questionnaire beyond the level's specimen.
    ask: bool = True


@dataclass(frozen=True)
class Section:
    """A specimen section: an optional heading plus its ordered fields."""

    heading: str | None
    fields: tuple[Field, ...]
    bullet: bool = False
    intro: str | None = None


@dataclass(frozen=True)
class FieldPlan:
    """The ordered fields of one narrative level."""

    nivel: str
    sections: tuple[Section, ...]

    def fields(self) -> tuple[Field, ...]:
        return tuple(field for section in self.sections for field in section.fields)

    def field(self, key: str) -> Field | None:
        return next((field for field in self.fields() if field.key == key), None)


# ---------------------------------------------------------------------------
# Specimens (structure + labels only, derived from the pinned carriers)
# ---------------------------------------------------------------------------

_LEVEL_1 = FieldPlan("1º", (
    Section("Identidad Base", (
        Field("nombre", "Nombre", ("nombre", "name", "title"),
              hint="El nombre con el que se lo conoce en el mundo.",
              examples=("Nara Veless", "Denin el Serio")),
        Field("apodo", "Apodo", ("apodo", "apodos", "nickname", "alias"),
              hint="Un sobrenombre que diga algo de cómo lo ve el mundo.",
              examples=("\"Dos Llaves\"", "El que no paga")),
        Field("edad", "Edad", ("edad", "age")),
        Field("raza", "Raza/Especie", ("raza", "raza_especie", "especie", "race", "species")),
        Field("lugar_origen", "Lugar de origen", ("lugar_origen", "lugar de origen", "origen", "origin", "procedencia"),
              hint="De dónde viene, sin nombrar un lugar que el mundo no tenga.",
              examples=("Un distrito minero de la frontera", "Chaart, Vibral")),
        Field("genero", "Género", ("genero", "género", "gender")),
        Field("sexualidad", "Sexualidad", ("sexualidad", "sexuality"), optional=True),
        Field("familia", "Familia", ("familia", "family"),
              hint="Vínculos de sangre o de crianza que todavía pesan."),
        Field("estudios", "Estudios", ("estudios", "formacion", "formación", "education")),
        Field("trabajo", "Trabajo", ("trabajo", "oficio", "ocupacion", "ocupación", "profesion", "profesión", "job", "profession"),
              hint="Qué hace para vivir y qué revela eso de su mundo.",
              examples=("Repara Dvins y Dvexs desde un bajo perfil",)),
        Field("religion", "Religión", ("religion", "religión")),
        Field("posesiones", "Posesiones valiosas", ("posesiones", "posesiones_valiosas", "possessions"), optional=True),
        Field("metas", "Metas", ("metas", "meta", "objetivo", "goal"),
              hint="Lo que persigue, aunque no lo diga en voz alta."),
        Field("condicion", "Condición", ("condicion", "condición", "condition"),
              hint="Un estado o marca que lo define y no eligió.",
              examples=("Inerte de nacimiento, no curable",), ask=False),
        Field("vinculos", "Vínculos", ("vinculos", "vínculos", "relaciones", "relaciones_clave", "relacion", "relación"),
              hint="Personas o fuerzas a las que está atado; nombrá el vínculo, no solo el nombre.", ask=False),
    ), bullet=True),
    Section("Aspecto Físico", (
        Field("aspecto_fisico", "Aspecto Físico", ("aspecto_fisico", "aspecto físico", "aspecto", "apariencia", "fisico", "físico", "appearance"),
              prose=True,
              hint="Rasgos que se recuerden sin ver al personaje; incluí un defecto o una marca.",
              examples=("Alto y encorvado, con una cicatriz que le cruza la ceja",
                        "Menuda, siempre con las manos manchadas de grasa")),
    ),),
    Section("Psicología y Carácter", (
        Field("virtudes", "Virtudes", ("virtudes", "virtues"),
              hint="Dos o tres virtudes que se vean en la acción, no adjetivos sueltos."),
        Field("defectos", "Defectos", ("defectos", "defects", "flaws"),
              hint="Dos o tres defectos que le cuesten algo real."),
        Field("adora", "Adora", ("adora", "loves")),
        Field("odia", "Odia", ("odia", "hates")),
        Field("teme", "Teme", ("teme", "temor", "miedo", "miedo_central", "miedo central", "miedo verdadero", "miedo_verdadero", "fear"),
              hint="El miedo que lo haría actuar en contra de sí mismo.",
              examples=("Ser una carga, quedar convertido en el que hay que levantar",)),
        Field("fortalezas", "Fortalezas", ("fortalezas", "strengths")),
        Field("debilidades", "Debilidades", ("debilidades", "debilidad", "weaknesses")),
        Field("caracter", "Carácter", ("caracter", "carácter", "personality"), prose=True,
              hint="Un párrafo que sintetice cómo se comporta cuando lo presionan.", ask=False),
    ), bullet=True),
    Section("Psique (sistema)", (
        Field("eneatipo", "Eneatipo", ("eneatipo", "enneatype", "eneagrama")),
        Field("subtipo", "Subtipo", ("subtipo", "subtype")),
        Field("arquetipo", "Arquetipo", ("arquetipo", "archetype")),
        Field("alineamiento_inicial", "Alineamiento inicial", ("alineamiento_inicial", "alineamiento inicial")),
        Field("alineamiento_revelado", "Alineamiento revelado", ("alineamiento_revelado", "alineamiento revelado"), optional=True),
        Field("alineamiento", "Alineamiento", ("alineamiento", "alignment"), prose=True,
              hint="Cómo lee el mundo en términos morales; si solo hay uno, describilo acá.", ask=False),
    ), bullet=True),
    Section("Motivaciones", (
        Field("deseo", "Deseo", ("deseo", "desire", "deseo_definidor"),
              hint="Lo que quiere conseguir o evitar; no la meta externa, sino lo que lo mueve.",
              examples=("Salir del sistema con la posición intacta", "Que no lo vuelvan a levantar")),
        Field("conflicto", "Conflicto", ("conflicto", "conflict", "conflicto_central"), prose=True,
              hint="La tensión que lo parte; podés contarla como una escena.", ask=False),
        Field("conflicto_interno", "Conflicto interno", ("conflicto_interno", "conflicto interno", "tension a resolver", "tensión a resolver", "tension_a_resolver")),
        Field("conflicto_externo", "Conflicto externo", ("conflicto_externo", "conflicto externo")),
        Field("detonante", "Detonante", ("detonante", "trigger", "inciting_incident"), prose=True,
              hint="El hecho concreto que lo pone en movimiento.", ask=False),
        Field("rol_historia", "Rol en la historia", ("rol_historia", "rol en la historia", "rol_en_la_historia", "rol", "funcion", "función", "role", "function")),
    ), bullet=True),
    Section("Trasfondo", (
        Field("trasfondo", "Trasfondo", ("trasfondo", "background", "pasado"), prose=True,
              hint="La historia que explica cómo llegó a ser quien es; dos o tres momentos, no una biografía."),
    ),),
    Section("Arco de Personaje", (
        Field("arco", "Arco", ("arco", "arc", "arco_personaje", "arco de personaje", "arco propuesto", "arco_propuesto")),
        Field("acto_i", "Acto I", ("acto_i", "acto i", "acto_1", "acto 1")),
        Field("acto_ii1", "Acto II1", ("acto_ii1", "acto ii1", "acto_2_1")),
        Field("acto_ii2", "Acto II2", ("acto_ii2", "acto ii2", "acto_2_2")),
        Field("acto_iii", "Acto III", ("acto_iii", "acto iii", "acto_3", "acto 3")),
    ), bullet=True),
))

_LEVEL_2 = FieldPlan("2º", (
    Section(None, (
        Field("nombre", "Nombre", ("nombre", "name", "title")),
        Field("rol_narrativo", "Rol narrativo", ("rol_narrativo", "rol narrativo")),
        Field("deseo", "Deseo", ("deseo", "desire", "deseo_definidor")),
        Field("edad", "Edad", ("edad", "age")),
        Field("raza", "Raza", ("raza", "raza_especie", "especie", "race", "species")),
        Field("lugar_origen", "Lugar de origen", ("lugar_origen", "lugar de origen", "origen", "origin", "procedencia")),
        Field("genero", "Género", ("genero", "género", "gender")),
        Field("estudios", "Estudios", ("estudios", "formacion", "formación", "education")),
        Field("trabajo", "Trabajo", ("trabajo", "oficio", "ocupacion", "ocupación", "profesion", "profesión", "job", "profession")),
        Field("religion", "Religión", ("religion", "religión")),
        Field("relacion_protagonista", "Relación con el protagonista", ("relacion_protagonista", "relación con el protagonista", "relacion_con_el_protagonista", "relacion", "relación", "vinculo", "vínculo"),
              hint="Cómo lo apoya o lo contrasta; qué le debe o le reprocha."),
        Field("aspecto_fisico", "Aspecto físico (con algún defecto)", ("aspecto_fisico", "aspecto físico", "aspecto", "apariencia", "fisico", "físico", "appearance")),
        Field("virtudes", "Virtudes", ("virtudes", "virtues")),
        Field("defectos", "Defectos", ("defectos", "defects", "flaws")),
        Field("caracter", "Carácter", ("caracter", "carácter", "personality"), ask=False),
        Field("adora", "Adora", ("adora", "loves")),
        Field("odia", "Odia", ("odia", "hates")),
        Field("teme", "Teme", ("teme", "temor", "miedo", "miedo_central", "fear")),
        Field("arquetipo", "Arquetipo", ("arquetipo", "archetype")),
        Field("rol_historia", "Rol en la historia (función)", ("rol_historia", "rol en la historia", "rol_en_la_historia", "rol", "funcion", "función", "role", "function")),
        Field("mini_arc", "Mini-arc", ("mini_arc", "mini-arc", "miniarc"), optional=True),
        Field("trasfondo", "Trasfondo", ("trasfondo", "background", "pasado")),
    ), intro="Ficha de personaje:"),
))

_LEVEL_3 = FieldPlan("3º", (
    Section(None, (
        Field("nombre", "Nombre", ("nombre", "name", "title")),
        Field("funcion_escena", "Función (rol en la escena)", ("funcion_escena", "función en la escena", "rol en la escena", "rol_escena", "funcion", "función", "function")),
        Field("rasgo_distintivo", "Rasgo distintivo", ("rasgo_distintivo", "rasgo distintivo", "rasgo", "distinctive_trait")),
        Field("arquetipo", "Arquetipo", ("arquetipo", "archetype")),
        Field("aparicion", "Aparición / vínculo", ("aparicion", "aparición", "aparicion_vinculo", "vinculo", "vínculo")),
    ), intro="Ficha de personaje:"),
))

PLANS: dict[str, FieldPlan] = {
    "1º": _LEVEL_1,
    "2º": _LEVEL_2,
    "3º": _LEVEL_3,
}

#: Labels added on top of the pinned carriers (documented in the feature doc).
ADDITIVE_LABELS = frozenset({"Deseo", "Carácter", "Alineamiento", "Conflicto", "Detonante", "Vínculos", "Condición"})


def plan_for(nivel: str) -> FieldPlan:
    """The field plan for ``nivel``; an unknown level uses the 1º plan (R11)."""
    return PLANS.get(nivel, _LEVEL_1)


def labels_for(nivel: str) -> tuple[str, ...]:
    """Every canonical label the renderer can write for ``nivel`` (S6 drift check)."""
    return tuple(field.label for field in plan_for(nivel).fields())


def field_for(nivel: str, key: str) -> Field | None:
    """The field spec for ``key`` under ``nivel`` (questionnaire lookup)."""
    return plan_for(nivel).field(key)


def field_value(field: Field, known: Mapping[str, Any]) -> str:
    """The candidate value already collected for ``field`` (empty when missing)."""
    return _value_for(known, field.probes)


def questionnaire_fields(nivel: str) -> tuple[Field, ...]:
    """The fields the questionnaire asks: exactly the level's specimen labels.

    Renderer-only additions (``ask=False``) keep mapping facts the provider
    already produced without widening the questionnaire past the specimen.
    """
    return tuple(field for field in plan_for(nivel).fields() if field.ask)


def current_field(
    candidate: Any, skipped: tuple[str, ...] | list[str] = (),
) -> tuple[Field | None, dict[str, Any]]:
    """Resolve the questionnaire cursor: the first asked field neither covered nor skipped.

    Returns ``(field, progress)``. ``progress`` is the public shape used by the
    API/UI: 1-based questionnaire position, total asked fields, the current
    field brief, and whether every asked field was visited (covered or skipped).
    """
    # Imported lazily: same cycle-avoidance as the renderer.
    from guided_character_domain import _candidate_known_fields, resolve_candidate_nivel

    nivel = resolve_candidate_nivel(candidate)
    known = _candidate_known_fields(candidate)
    skipped_set = {str(key) for key in skipped}
    fields = questionnaire_fields(nivel)
    covered: list[str] = []
    for index, field in enumerate(fields, start=1):
        if field_value(field, known):
            covered.append(field.key)
            continue
        if field.key in skipped_set:
            continue
        return field, _progress(nivel, index, len(fields), field, covered, skipped_set, complete=False)
    return None, _progress(nivel, 0, len(fields), None, covered, skipped_set, complete=True)


def _progress(
    nivel: str, index: int, total: int, field: Field | None,
    covered: list[str], skipped: set[str], *, complete: bool,
) -> dict[str, Any]:
    return {
        "nivel": nivel,
        "index": index,
        "total": total,
        "key": field.key if field is not None else None,
        "label": field.label if field is not None else None,
        "hint": field.hint if field is not None else None,
        "examples": list(field.examples) if field is not None else [],
        "optional": bool(field.optional) if field is not None else False,
        "covered": covered,
        "skipped": sorted(skipped),
        "complete": complete,
    }


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
    folded = {str(key).casefold(): value for key, value in known.items()}
    for probe in probes:
        if probe.casefold() in folded:
            text = _plain(folded[probe.casefold()])
            if text:
                return text
    return ""


def _unwrap_records(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value.get("value", value) if isinstance(value, Mapping) else value
            for key, value in mapping.items()}


def _extra_fields(candidate: Any, consumed: set[str]) -> list[tuple[str, str]]:
    """Unmapped AUTHOR facts, rendered instead of dropped (S5).

    Only accepted canon and proposals are user-facing facts. Observations are
    the provider's internal notes: they may fill a canonical label, but dumping
    them into the ficha is noise (the real Ganic sheet had 64 such entries).
    """
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
    """Render the sheet body for the candidate's resolved narrative level."""
    # Imported lazily: ``guided_character_domain`` imports this module at module
    # level to wire the serializer, so the reverse import must stay local.
    from guided_character_domain import _candidate_known_fields, resolve_candidate_nivel

    nivel = resolve_candidate_nivel(candidate)
    plan = plan_for(nivel)
    known = _candidate_known_fields(candidate)
    consumed: set[str] = set()
    pending: list[str] = []
    blocks: list[str] = []

    for section in plan.sections:
        if section.intro:
            blocks.append(section.intro)
        lines: list[str] = []
        for field in section.fields:
            consumed.update(probe.casefold() for probe in field.probes)
            text = _value_for(known, field.probes)
            if not text:
                pending.append(field.label)
                continue
            if field.prose:
                lines.append(text if not section.bullet else f"- **{field.label}:** {text}")
            elif section.bullet:
                lines.append(f"- **{field.label}:** {text}")
            else:
                lines.append(f"**{field.label}:** {text}")
        if not lines:
            continue
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

    if pending:
        blocks.append(f"## {_PENDING_HEADING}\n\n" + " · ".join(pending))

    return "\n\n".join(block.strip() for block in blocks if block.strip()) + "\n"
