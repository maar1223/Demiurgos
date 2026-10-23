"""Kernel tests for guided-flow declarations and resolved profiles.

The declaration names the shape; the kernel owns persistence, minimums, the
entity type label, the question plan and the copy key. These tests pin that
boundary and the fail-closed validation used by the compiler.
"""

from __future__ import annotations

import sys
from pathlib import Path

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import guided_flow  # noqa: E402
from guided_flow import (  # noqa: E402
    GUIDED_CHARACTER_FLOW,
    GUIDED_SYSTEM_FLOW,
    GuidedFlowDeclaration,
    builtin_profile,
    guided_flow_issues,
    resolve_profile,
)


def _declaration(**overrides) -> dict:
    value = {
        "flow_id": GUIDED_SYSTEM_FLOW,
        "entity_type": "sistema",
        "ui_copy_key": "system",
        "index": True,
        "intent": {"terms": ["sistema"], "verbs": ["crear"]},
    }
    value.update(overrides)
    return value


def _codes(value) -> set[str]:
    return {code for code, _, _ in guided_flow_issues(value)}


class TestDeclarationValidation:
    def test_valid_declaration_has_no_issues(self) -> None:
        assert guided_flow_issues(_declaration()) == []

    def test_target_section_is_kernel_owned_and_rejected(self) -> None:
        codes = _codes(_declaration(target_section="personajes"))
        assert codes == {"unknown-field"}

    def test_persistence_and_minimums_claims_are_rejected(self) -> None:
        for key in ("minimums", "persistence", "allowlisted_targets"):
            assert "unknown-field" in _codes(_declaration(**{key: []}))

    def test_missing_field_is_rejected(self) -> None:
        for key in ("flow_id", "entity_type", "ui_copy_key", "index", "intent"):
            value = _declaration()
            value.pop(key)
            assert "missing-field" in _codes(value), key

    def test_unknown_entity_type_is_rejected(self) -> None:
        assert "invalid-value" in _codes(_declaration(entity_type="planeta"))

    def test_unknown_copy_key_is_rejected(self) -> None:
        assert "invalid-value" in _codes(_declaration(ui_copy_key="wizard"))

    def test_non_boolean_index_is_rejected(self) -> None:
        assert "invalid-value" in _codes(_declaration(index="yes"))

    def test_empty_intent_list_is_rejected(self) -> None:
        assert "invalid-value" in _codes(
            _declaration(intent={"terms": [], "verbs": ["crear"]})
        )

    def test_oversized_intent_is_rejected(self) -> None:
        codes = _codes(
            _declaration(
                intent={"terms": [f"t{i}" for i in range(21)], "verbs": ["crear"]}
            )
        )
        assert "oversized" in codes

    def test_non_mapping_declaration_is_rejected(self) -> None:
        assert _codes("guided-system") == {"invalid-value"}


class TestProfileResolution:
    def test_system_profile_uses_the_kernel_section_and_minimums(self) -> None:
        profile = resolve_profile(
            GuidedFlowDeclaration.from_mapping(_declaration())
        )
        assert profile is not None
        assert profile.flow_id == GUIDED_SYSTEM_FLOW
        assert profile.entity_type == "sistema"
        assert profile.target_section == "lore"
        assert profile.index_target == "lore"
        assert profile.type_label == "Sistema"
        assert profile.ui_copy_key == "system"
        assert profile.question_keys == ("identity", "origin", "limit")
        fields = [group for group in profile.minimum_groups]
        assert any("origen" in group for group in fields)
        assert any("limite" in group for group in fields)
        assert not profile.builtin

    def test_chronology_profile_uses_the_kernel_section_and_minimums(self) -> None:
        declaration = _declaration(
            flow_id="guided-chronology",
            entity_type="cronologia",
            ui_copy_key="chronology",
            intent={"terms": ["cronologia"], "verbs": ["crear"]},
        )
        assert guided_flow_issues(declaration) == []
        profile = resolve_profile(GuidedFlowDeclaration.from_mapping(declaration))
        assert profile is not None
        assert profile.flow_id == "guided-chronology"
        assert profile.entity_type == "cronologia"
        assert profile.target_section == "lore"
        assert profile.index_target == "lore"
        assert profile.type_label == "Cronologia"
        assert profile.ui_copy_key == "chronology"
        assert profile.question_keys == ("identity", "event")
        assert profile.frontmatter_fields == ("evento",)
        assert any("evento" in group for group in profile.minimum_groups)
        assert not profile.builtin

    def test_entity_profile_uses_the_kernel_section_and_minimums(self) -> None:
        declaration = _declaration(
            flow_id="guided-entity",
            entity_type="entidad",
            ui_copy_key="entity",
            intent={"terms": ["entidad", "lugar", "facción"], "verbs": ["crear"]},
        )
        assert guided_flow_issues(declaration) == []
        profile = resolve_profile(GuidedFlowDeclaration.from_mapping(declaration))
        assert profile is not None
        assert profile.flow_id == "guided-entity"
        assert profile.entity_type == "entidad"
        assert profile.target_section == "lore"
        assert profile.index_target == "lore"
        assert profile.type_label == "Entidad"
        assert profile.ui_copy_key == "entity"
        assert profile.question_keys == ("identity", "entity_class")
        assert profile.frontmatter_fields == ("clase",)
        assert profile.provenance_default == "guided-entidad-v1"
        class_groups = [
            group for group in profile.minimum_groups if "clase" in group
        ]
        assert class_groups, "the entity class is a kernel-owned minimum"
        assert len(profile.minimum_groups) == len(profile.question_keys) == 2
        assert not profile.builtin

    def test_character_builtin_profile_is_server_owned(self) -> None:
        profile = builtin_profile(GUIDED_CHARACTER_FLOW)
        assert profile is not None
        assert profile.target_section == "personajes"
        assert profile.type_label == "Personaje"
        assert profile.builtin is True
        assert builtin_profile(GUIDED_SYSTEM_FLOW) is None

    def test_profile_round_trips_through_the_snapshot_shape(self) -> None:
        profile = resolve_profile(GuidedFlowDeclaration.from_mapping(_declaration()))
        assert profile is not None
        restored = guided_flow.GuidedFlowProfile.from_dict(profile.as_dict())
        assert restored == profile

    def test_unknown_entity_in_snapshot_fails_closed(self) -> None:
        assert guided_flow.GuidedFlowProfile.from_dict({
            "flow_id": GUIDED_SYSTEM_FLOW,
            "entity_type": "planeta",
            "ui_copy_key": "system",
        }) is None


def test_flow_id_must_match_the_declared_entity_shape() -> None:
    """A flow id is bound to one kernel entity shape (S7)."""
    codes = _codes(_declaration(flow_id=GUIDED_CHARACTER_FLOW, entity_type="sistema"))
    assert codes == {"invalid-value"}


def test_the_generic_entity_type_is_only_persistible_as_the_explicit_type() -> None:
    """S1/S3: the entity flow writes ``type: Entidad``; the class is a field.

    The relaxation is exact: ``entidad`` becomes a kernel-known persistible
    type, while every other entity-shaped label still has no kernel section and
    stays rejected (a world type never widens persistence).
    """
    assert guided_flow.entity_type_is_persistible("entidad")
    assert guided_flow.entity_type_is_persistible("Personaje")
    assert not guided_flow.entity_type_is_persistible("lugar")
    assert not guided_flow.entity_type_is_persistible("planeta")

    for entity_type in ("lugar", "planeta"):
        codes = _codes(_declaration(
            flow_id="guided-entity", entity_type=entity_type,
            ui_copy_key="entity",
        ))
        assert codes == {"invalid-value"}, entity_type

    mismatched = _codes(_declaration(
        flow_id="guided-entity", entity_type="personaje", ui_copy_key="entity",
    ))
    assert mismatched == {"invalid-value"}
