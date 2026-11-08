# -*- coding: utf-8 -*-
"""Character body renderer: specimen structure/labels, never example prose (S1-S3, S6)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parent.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from guided_character_body import labels_for, render_character_body  # noqa: E402
from guided_character_protocol import CandidateState  # noqa: E402

_REPO = Path(__file__).resolve().parents[5]
_SEEDS = _REPO / "data" / "methodology" / "seeds" / "narrative-character-creation"
_CARRIERS = {
    "1º": "adjunto-nivel-1-principal.md",
    "2º": "adjunto-nivel-2-secundario.md",
    "3º": "adjunto-nivel-3-relleno.md",
}


def _candidate(**proposals):
    return CandidateState(
        accepted_canon={key: {"value": value} for key, value in proposals.items()},
    )


def test_level_one_renders_sectioned_bullets_with_specimen_labels() -> None:
    body = render_character_body(_candidate(
        nombre="Nara Veless",
        apodo="Dos Llaves",
        edad="34 años",
        oficio="Gestora de permisos",
        deseo="Salir del sistema con la posición intacta",
        virtudes=["Precisión", "Templanza"],
        conflicto_interno="Pertenece al orden que empieza a parecerle injusto",
        trasfondo="Nació dentro de la estructura.",
    ))

    for heading in (
        "## Identidad Base",
        "## Aspecto Físico",
        "## Psicología y Carácter",
        "## Psique (sistema)",
        "## Motivaciones",
        "## Trasfondo",
        "## Arco de Personaje",
    ):
        assert heading in body
    assert "- **Nombre:** Nara Veless" in body
    assert "- **Apodo:** Dos Llaves" in body
    assert "- **Edad:** 34 años" in body
    assert "- **Trabajo:** Gestora de permisos" in body
    assert "- **Deseo:** Salir del sistema con la posición intacta" in body
    assert "- **Virtudes:** Precisión; Templanza" in body
    assert "- **Conflicto interno:** Pertenece al orden que empieza a parecerle injusto" in body
    assert "Nació dentro de la estructura." in body
    # A label with no value is a visible gap, never a silent omission.
    assert "- **Familia:** _(pendiente)_" in body
    assert "- **Eneatipo:** _(pendiente)_" in body


def test_level_two_renders_flat_bold_labels() -> None:
    body = render_character_body(CandidateState(proposals={
        "nivel": "2",
        "nombre": {"value": "Denin Vael"},
        "rol_narrativo": {"value": "Secundario"},
        "relacion_protagonista": {"value": "Mentor a regañadientes"},
    }))

    assert body.startswith("Ficha de personaje:")
    assert "**Nombre:** Denin Vael" in body
    assert "**Rol narrativo:** Secundario" in body
    assert "**Relación con el protagonista:** Mentor a regañadientes" in body
    # 2º omits the 1º-only sectioned skeleton.
    assert "## Identidad Base" not in body
    assert "**Edad:** _(pendiente)_" in body


def test_level_three_renders_only_its_minimal_card() -> None:
    body = render_character_body(CandidateState(proposals={
        "nivel": "3",
        "nombre": {"value": "Nira"},
        "funcion_escena": {"value": "Vendedora del puesto de galletas"},
        "rasgo_distintivo": {"value": "Guarda la mejor galleta bajo el mostrador"},
    }))

    assert body.startswith("Ficha de personaje:")
    assert "**Nombre:** Nira" in body
    assert "**Función (rol en la escena):** Vendedora del puesto de galletas" in body
    assert "**Rasgo distintivo:** Guarda la mejor galleta bajo el mostrador" in body
    # The filler card must not grow the full sheet.
    assert "**Edad:**" not in body
    assert "## Psicología y Carácter" not in body


def test_unknown_level_still_renders_the_principal_specimen() -> None:
    body = render_character_body(_candidate(nombre="Nara"))
    assert "## Identidad Base" in body
    assert "- **Nombre:** Nara" in body


def test_body_is_markdown_only_and_never_duplicates_the_old_yaml_sections() -> None:
    body = render_character_body(_candidate(nombre="Nara", edad="34 años"))

    assert "```yaml" not in body
    assert "## Identity" not in body
    assert "## Canon Anchors" not in body


def test_accents_survive() -> None:
    body = render_character_body(_candidate(nombre="Ñandú Pérez", religion="Gnóstico"))
    assert "Ñandú Pérez" in body
    assert "Gnóstico" in body
    assert "\\u00d1" not in body


def test_unmapped_fields_fall_back_instead_of_disappearing() -> None:
    body = render_character_body(_candidate(
        nombre="Nara",
        color_favorito="azul profundo",
    ))
    assert "## Otros datos" in body
    assert "- **Color favorito:** azul profundo" in body


def test_observations_fill_canonical_labels_but_never_the_fallback_block() -> None:
    candidate = CandidateState(
        proposals={"nombre": {"value": "Nara"}},
        observations={"lugar_origen": "Ekkor", "intencion": "crear un personaje"},
    )
    body = render_character_body(candidate)
    assert "- **Lugar de origen:** Ekkor" in body
    # Internal session notes are not ficha content.
    assert "crear un personaje" not in body
    assert "## Otros datos" not in body


def test_conflicts_and_unresolved_references_are_preserved() -> None:
    candidate = CandidateState(
        proposals={"nombre": {"value": "Nara"}},
        conflicts=[{"value": "dos orígenes", "certainty": "conflicted"}],
        unresolved_references=[{"value": "Orden Desconocida", "certainty": "unknown"}],
    )
    body = render_character_body(candidate)
    assert "## Relaciones" in body
    assert "dos orígenes" in body
    assert "## Referencias sin resolver" in body
    assert "Orden Desconocida" in body


def test_mapping_accepts_english_and_spanish_aliases() -> None:
    body = render_character_body(_candidate(name="Aria", age="27", job="Pilot"))
    assert "- **Nombre:** Aria" in body
    assert "- **Edad:** 27" in body
    assert "- **Trabajo:** Pilot" in body


@pytest.mark.parametrize("nivel", ["1º", "2º", "3º"])
def test_every_rendered_label_still_exists_in_the_pinned_carrier(nivel: str) -> None:
    """S6: carrier drift must be caught, not silently tolerated."""
    carrier = (_SEEDS / _CARRIERS[nivel]).read_text(encoding="utf-8")
    for label in labels_for(nivel):
        if label == "Deseo":  # documented additive label (platform minimum)
            continue
        assert label in carrier, f"{nivel}: label {label!r} is missing from the pinned specimen"


def test_generic_flows_keep_the_yaml_body_unchanged() -> None:
    """S5: only the character body changes; sistema keeps its YAML body."""
    from guided_character_domain import serialize_entity

    candidate = CandidateState(accepted_canon={"identity": {"value": "X"}})
    proposal = serialize_entity(
        candidate, world="w", slug="s", title="T",
        entity_type="sistema", target_section="lore", type_label="Sistema",
    )
    _, body = proposal.content.split("---\n", 2)[1:]
    assert body.startswith("## Identity\n\n```yaml\n")
    assert "## Canon Anchors" in body
    assert "## Identidad Base" not in body
