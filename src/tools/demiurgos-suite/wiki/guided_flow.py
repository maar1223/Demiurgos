"""Server-owned guided-flow declarations and resolved profiles.

A published methodology may declare that it produces a persistible OKF entity
and therefore drives a guided flow. The declaration is deliberately narrow: it
names the *shape* (``entity_type``), the flow id, a bounded intent vocabulary
and a UI copy key. Where the entity lands, what its minimums are, and whether
it is indexed are **kernel-owned** and resolved here from ``okf_contract``.

This keeps the guided engine agnostic: character and system flows differ only
by their resolved ``GuidedFlowProfile``. A new flow costs one kernel entity ->
section entry (plus its UI copy), never a new branch in the engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from okf_contract import (
    normalize_type,
    prompt_minimums_for,
    shape_for_type,
)

GUIDED_CHARACTER_FLOW = "guided-character"
GUIDED_SYSTEM_FLOW = "guided-system"
GUIDED_CHRONOLOGY_FLOW = "guided-chronology"
GUIDED_ENTITY_FLOW = "guided-entity"

# A declared flow id is bound to exactly one kernel entity shape. A
# declaration pairing them inconsistently (e.g. the character flow writing a
# system) fails at publish.
ENTITY_TYPE_BY_FLOW: dict[str, str] = {
    "guided-character": "personaje",
    "guided-system": "sistema",
    "guided-chronology": "cronologia",
    "guided-entity": "entidad",
}

# Deterministic default for a flow that has no builtin contract: the
# foundational method of the family. The chat imperative path uses it when the
# Author did not pick a method, mirroring the character factory fallback.
FOUNDATIONAL_METHOD_BY_FLOW: dict[str, str] = {
    "guided-system": "narrative-system-creation",
    "guided-chronology": "narrative-chronology-creation",
    "guided-entity": "narrative-entity-creation",
}

# Flow ids the server currently accepts as activation slots. A genuinely new
# flow id requires one entry here plus its kernel entity mapping below.
GUIDED_FLOW_IDS: frozenset[str] = frozenset({
    GUIDED_CHARACTER_FLOW,
    GUIDED_SYSTEM_FLOW,
    GUIDED_CHRONOLOGY_FLOW,
    GUIDED_ENTITY_FLOW,
})

# Kernel-owned persistence authority: an entity type may only land in one of
# these sections. A methodology can never claim or widen this mapping.
TARGET_SECTION_BY_ENTITY_TYPE: dict[str, str] = {
    "personaje": "personajes",
    "sistema": "lore",
    "cronologia": "lore",
    "entidad": "lore",
}

# Frontmatter ``type`` label written by the guided serializer per entity type.
TYPE_LABEL_BY_ENTITY_TYPE: dict[str, str] = {
    "personaje": "Personaje",
    "sistema": "Sistema",
    "cronologia": "Cronologia",
    "entidad": "Entidad",
}

# Canonical provenance fallback when a candidate carries no provenance, keyed by
# entity type so the character serializer keeps its historical value verbatim.
# Envelope fields the serializer promotes from accepted canon into the ficha
# frontmatter so the persisted entity passes the OKF minimums. Empty for the
# character flow: its bytes stay exactly as before.
FRONTMATTER_FIELDS_BY_ENTITY_TYPE: dict[str, tuple[str, ...]] = {
    "personaje": (),
    "sistema": ("origen", "limite"),
    "cronologia": ("evento",),
    "entidad": ("clase",),
}

DEFAULT_TITLE_BY_ENTITY_TYPE: dict[str, str] = {
    "personaje": "Guided Character",
    "sistema": "Guided System",
    "cronologia": "Guided Chronology",
    "entidad": "Guided Entity",
}

PROVENANCE_DEFAULT_BY_ENTITY_TYPE: dict[str, str] = {
    "personaje": "guided-character-v1",
    "sistema": "guided-sistema-v1",
    "cronologia": "guided-cronologia-v1",
    "entidad": "guided-entidad-v1",
}

# Server-owned question keys per entity type, aligned with the kernel minimum
# groups (``okf_contract.prompt_minimums_for``). The engine asks one question per
# missing group; the copy for each key lives in the domain layer.
QUESTION_KEYS_BY_ENTITY_TYPE: dict[str, tuple[str, ...]] = {
    "personaje": ("identity", "desire"),
    "sistema": ("identity", "origin", "limit"),
    "cronologia": ("identity", "event"),
    "entidad": ("identity", "entity_class"),
}

# UI copy the client may render for a flow. The client never supplies copy,
# only selects a key the server validates.
UI_COPY_KEYS: frozenset[str] = frozenset({
    "character", "system", "chronology", "entity",
})

DECLARATION_FIELDS: frozenset[str] = frozenset({
    "flow_id", "entity_type", "ui_copy_key", "index", "intent",
})
INTENT_FIELDS: frozenset[str] = frozenset({"terms", "verbs"})

MAX_FLOW_ID_CHARS = 64
MAX_INTENT_ITEMS = 20
MAX_INTENT_ITEM_CHARS = 48

_FLOW_ID = re.compile(r"^[a-z][a-z0-9-]*$")


def entity_type_is_persistible(entity_type: str) -> bool:
    """True when the kernel knows where this entity type may be written.

    Requires a canonical type label, a known shape (so it is not silently
    defaulted to ``entidad``) and a kernel-owned target section.

    The generic type ``entidad`` is the one entity-shaped label the kernel
    authorizes as a persisted ``type``: the entity flow writes ``type: Entidad``
    and the class travels as a field. Every other entity-shaped label (``lugar``,
    ``criatura``, ...) still has no kernel section, so a world type can never
    widen persistence.
    """
    normalized = normalize_type(entity_type)
    if not normalized or normalized not in TARGET_SECTION_BY_ENTITY_TYPE:
        return False
    # A type that is not in the kernel shape map would default to ``entidad``;
    # reject it explicitly instead of writing an unexpected shape.
    if (
        shape_for_type(normalized) == "entidad"
        and normalized not in {"personaje", "entidad"}
    ):
        return False
    return True


@dataclass(frozen=True)
class GuidedFlowDeclaration:
    """A validated ``guided_flow`` manifest block."""

    flow_id: str
    entity_type: str
    ui_copy_key: str
    index: bool
    intent_terms: tuple[str, ...]
    intent_verbs: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "entity_type": self.entity_type,
            "ui_copy_key": self.ui_copy_key,
            "index": self.index,
            "intent": {
                "terms": list(self.intent_terms),
                "verbs": list(self.intent_verbs),
            },
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GuidedFlowDeclaration":
        intent = value["intent"]
        return cls(
            flow_id=str(value["flow_id"]).strip(),
            entity_type=normalize_type(str(value["entity_type"]).strip()),
            ui_copy_key=str(value["ui_copy_key"]).strip(),
            index=bool(value["index"]),
            intent_terms=tuple(str(item).strip() for item in intent["terms"]),
            intent_verbs=tuple(str(item).strip() for item in intent["verbs"]),
        )


@dataclass(frozen=True)
class GuidedFlowProfile:
    """The resolved contract one guided session runs under."""

    flow_id: str
    entity_type: str
    target_section: str
    type_label: str
    minimum_groups: tuple[frozenset[str], ...]
    question_keys: tuple[str, ...]
    provenance_default: str
    default_title: str
    frontmatter_fields: tuple[str, ...]
    index: bool
    ui_copy_key: str
    intent_terms: tuple[str, ...]
    intent_verbs: tuple[str, ...]
    # Compatibility strategy for intent detection, kernel-owned. Currently
    # ``legacy-character`` (the historical matcher, byte-identical) or
    # ``declarative`` (the declared terms/verbs).
    intent_matcher: str
    builtin: bool = False

    @property
    def index_target(self) -> str:
        """The graph section the persisted entity is indexed from."""
        return self.target_section

    def as_dict(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "entity_type": self.entity_type,
            "target_section": self.target_section,
            "type_label": self.type_label,
            "ui_copy_key": self.ui_copy_key,
            "index": self.index,
            "intent_terms": list(self.intent_terms),
            "intent_verbs": list(self.intent_verbs),
            "builtin": self.builtin,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "GuidedFlowProfile | None":
        if not isinstance(value, Mapping):
            return None
        entity_type = normalize_type(str(value.get("entity_type") or ""))
        if not entity_type_is_persistible(entity_type):
            return None
        flow_id = str(value.get("flow_id") or "").strip()
        ui_copy_key = str(value.get("ui_copy_key") or "").strip()
        if not _FLOW_ID.match(flow_id) or ui_copy_key not in UI_COPY_KEYS:
            return None
        return resolve_profile(
            GuidedFlowDeclaration(
                flow_id=flow_id,
                entity_type=entity_type,
                ui_copy_key=ui_copy_key,
                index=bool(value.get("index", True)),
                intent_terms=tuple(str(item) for item in (value.get("intent_terms") or ())),
                intent_verbs=tuple(str(item) for item in (value.get("intent_verbs") or ())),
            ),
            builtin=bool(value.get("builtin", False)),
        )


def guided_flow_issues(value: Any) -> list[tuple[str, str, str]]:
    """Validate a ``guided_flow`` manifest block, fail closed.

    Returns ``(code, message, field)`` tuples shaped like the compiler's
    ``MethodologyIssue``. Any extra key is rejected, so a methodology can never
    smuggle kernel-owned persistence, minimums or target fields.
    """
    issues: list[tuple[str, str, str]] = []

    def issue(code: str, message: str, field: str) -> None:
        issues.append((code, message, field))

    if not isinstance(value, Mapping):
        issue("invalid-value", "guided_flow must be a mapping.", "guided_flow")
        return issues

    for key in sorted(set(value) - DECLARATION_FIELDS):
        issue(
            "unknown-field",
            f"Unknown guided_flow field {key!r}; the kernel owns persistence, "
            "minimums and target sections.",
            f"guided_flow.{key}",
        )
    for key in sorted(DECLARATION_FIELDS - set(value)):
        issue(
            "missing-field",
            f"Required guided_flow field {key!r} is missing.",
            f"guided_flow.{key}",
        )

    flow_id = value.get("flow_id")
    if flow_id is not None:
        if not isinstance(flow_id, str) or not _FLOW_ID.match(flow_id.strip()):
            issue(
                "invalid-value",
                "guided_flow.flow_id must be a lowercase identifier.",
                "guided_flow.flow_id",
            )
        elif len(flow_id.strip()) > MAX_FLOW_ID_CHARS:
            issue(
                "oversized",
                f"guided_flow.flow_id exceeds {MAX_FLOW_ID_CHARS} characters.",
                "guided_flow.flow_id",
            )

    entity_type = value.get("entity_type")
    if entity_type is not None:
        if not isinstance(entity_type, str) or not entity_type_is_persistible(entity_type):
            issue(
                "invalid-value",
                "guided_flow.entity_type must be a kernel-known persistible "
                f"entity type (one of {sorted(TARGET_SECTION_BY_ENTITY_TYPE)}).",
                "guided_flow.entity_type",
            )

    if (
        isinstance(flow_id, str)
        and isinstance(entity_type, str)
        and _FLOW_ID.match(flow_id.strip())
        and entity_type_is_persistible(entity_type)
    ):
        expected_entity = ENTITY_TYPE_BY_FLOW.get(flow_id.strip())
        if expected_entity is not None and expected_entity != normalize_type(entity_type):
            issue(
                "invalid-value",
                f"guided_flow.flow_id {flow_id!r} is bound to entity_type "
                f"{expected_entity!r}.",
                "guided_flow.entity_type",
            )

    ui_copy_key = value.get("ui_copy_key")
    if ui_copy_key is not None:
        if not isinstance(ui_copy_key, str) or ui_copy_key.strip() not in UI_COPY_KEYS:
            issue(
                "invalid-value",
                f"guided_flow.ui_copy_key must be one of {sorted(UI_COPY_KEYS)}.",
                "guided_flow.ui_copy_key",
            )

    index = value.get("index")
    if index is not None and not isinstance(index, bool):
        issue(
            "invalid-value",
            "guided_flow.index must be a boolean.",
            "guided_flow.index",
        )

    intent = value.get("intent")
    if intent is not None:
        if not isinstance(intent, Mapping):
            issue(
                "invalid-value",
                "guided_flow.intent must be a mapping with terms and verbs.",
                "guided_flow.intent",
            )
        else:
            for key in sorted(set(intent) - INTENT_FIELDS):
                issue(
                    "unknown-field",
                    f"Unknown guided_flow.intent field {key!r}.",
                    f"guided_flow.intent.{key}",
                )
            for key in sorted(INTENT_FIELDS - set(intent)):
                issue(
                    "missing-field",
                    f"Required guided_flow.intent field {key!r} is missing.",
                    f"guided_flow.intent.{key}",
                )
            for key in ("terms", "verbs"):
                items = intent.get(key)
                if items is None:
                    continue
                if not isinstance(items, list) or not items:
                    issue(
                        "invalid-value",
                        f"guided_flow.intent.{key} must be a non-empty list of strings.",
                        f"guided_flow.intent.{key}",
                    )
                    continue
                if len(items) > MAX_INTENT_ITEMS:
                    issue(
                        "oversized",
                        f"guided_flow.intent.{key} exceeds {MAX_INTENT_ITEMS} items.",
                        f"guided_flow.intent.{key}",
                    )
                for item in items:
                    if not isinstance(item, str) or not item.strip():
                        issue(
                            "invalid-value",
                            f"guided_flow.intent.{key} items must be non-empty strings.",
                            f"guided_flow.intent.{key}",
                        )
                    elif len(item.strip()) > MAX_INTENT_ITEM_CHARS:
                        issue(
                            "oversized",
                            f"guided_flow.intent.{key} item exceeds "
                            f"{MAX_INTENT_ITEM_CHARS} characters.",
                            f"guided_flow.intent.{key}",
                        )

    return issues


def resolve_profile(
    declaration: GuidedFlowDeclaration, *, builtin: bool = False,
) -> GuidedFlowProfile | None:
    """Resolve the kernel-owned profile for a validated declaration."""
    entity_type = normalize_type(declaration.entity_type)
    if not entity_type_is_persistible(entity_type):
        return None
    expected_entity = ENTITY_TYPE_BY_FLOW.get(declaration.flow_id)
    if expected_entity is not None and expected_entity != entity_type:
        return None
    if declaration.ui_copy_key not in UI_COPY_KEYS:
        return None
    question_keys = QUESTION_KEYS_BY_ENTITY_TYPE.get(entity_type)
    if question_keys is None:
        return None
    return GuidedFlowProfile(
        flow_id=declaration.flow_id,
        entity_type=entity_type,
        target_section=TARGET_SECTION_BY_ENTITY_TYPE[entity_type],
        type_label=TYPE_LABEL_BY_ENTITY_TYPE[entity_type],
        minimum_groups=prompt_minimums_for(entity_type),
        question_keys=question_keys,
        provenance_default=PROVENANCE_DEFAULT_BY_ENTITY_TYPE[entity_type],
        default_title=DEFAULT_TITLE_BY_ENTITY_TYPE[entity_type],
        frontmatter_fields=FRONTMATTER_FIELDS_BY_ENTITY_TYPE[entity_type],
        index=declaration.index,
        ui_copy_key=declaration.ui_copy_key,
        intent_terms=declaration.intent_terms,
        intent_verbs=declaration.intent_verbs,
        intent_matcher=(
            "legacy-character"
            if declaration.flow_id == GUIDED_CHARACTER_FLOW
            else "declarative"
        ),
        builtin=builtin,
    )


def builtin_profile(flow_id: str) -> GuidedFlowProfile | None:
    """The server-embedded profile for the shipped character contract."""
    if flow_id != GUIDED_CHARACTER_FLOW:
        return None
    return resolve_profile(
        GuidedFlowDeclaration(
            flow_id=GUIDED_CHARACTER_FLOW,
            entity_type="personaje",
            ui_copy_key="character",
            index=True,
            intent_terms=(),
            intent_verbs=(),
        ),
        builtin=True,
    )


def profile_for_declaration(
    declaration: GuidedFlowDeclaration | None,
) -> GuidedFlowProfile | None:
    if declaration is None:
        return None
    return resolve_profile(declaration)
