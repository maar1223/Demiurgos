"""T-L tests for per-flow activation slots (SR1 — contract §2).

A world holds one activation slot per guided-flow type, keyed (world, flow).
World-keyed legacy records (the pre-SR1 shape — the live ``Vibrantes``
activation in ``data/methodology/library.json``) are coerced at load into the
``guided-character`` slot without loss and without rewriting the file (design
D1/D3). All fixtures are tmp — the on-disk ``data/methodology/library.json``
is never read or written by these tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from methodology_library import (  # noqa: E402
    CO_CREATION_FLOW,
    DEFAULT_FLOW_TYPE,
    GUIDED_CHARACTER_FLOW,
    SUPPORTED_FLOW_TYPES,
    MethodologyLibrary,
    ValidationError,
)

# The real on-disk legacy record (data/methodology/library.json, read-only):
# world-keyed, no ``flow_type`` field. Used as the fixture shape so the
# coercion test mirrors the live migration exactly (R4 scenario).
_LEGACY_RECORD = {
    "world": "Vibrantes",
    "skill_id": "narrative-character-creation",
    "version": "1.0",
    "digest": "2ae521a09bf014ccdefd7296f6ec94092aa6421703802f2d432d9eaf4f1bbe81",
    "activated_at": "2026-09-11T20:18:25.280907+00:00",
}

# The on-disk legacy history stack (older records, same shape).
_LEGACY_HISTORY = [
    {
        "world": "Vibrantes",
        "skill_id": "narrative-character-creation",
        "version": "1.0",
        "digest": "2ae521a09bf014ccdefd7296f6ec94092aa6421703802f2d432d9eaf4f1bbe81",
        "activated_at": "2026-09-11T20:17:44.280519+00:00",
    },
    {
        "world": "Vibrantes",
        "skill_id": "narrative-character-creation",
        "version": "1.0",
        "digest": "2ae521a09bf014ccdefd7296f6ec94092aa6421703802f2d432d9eaf4f1bbe81",
        "activated_at": "2026-09-11T20:18:14.774554+00:00",
    },
]


def _valid_source() -> str:
    return "## Construcción segura\n\nHaz preguntas de a una.\n"


def _publish(
    library: MethodologyLibrary,
    skill_id: str,
    version: str,
    name: str,
) -> None:
    draft_id = library.create_draft(
        skill_id=skill_id, version=version, name=name, source=_valid_source(),
        description="A test methodology.",
    )
    # Etapa 2 trigger gate: record the approval the review surface would capture
    # so the publish is not refused.
    library.approve_trigger(draft_id, "A test methodology.", "author")
    library.publish(draft_id)


def _library(tmp_path: Path) -> MethodologyLibrary:
    return MethodologyLibrary(tmp_path / "library.json")


def _legacy_store(
    tmp_path: Path,
    *,
    record: dict | None = None,
    history: list[dict] | None = None,
) -> tuple[Path, bytes]:
    """Write a world-keyed (legacy) library.json; returns (path, bytes)."""
    store = tmp_path / "library.json"
    payload = {
        "drafts": {},
        "published": {},
        "activations": {
            "Vibrantes": record if record is not None else dict(_LEGACY_RECORD),
        },
        "companions": {},
        "history": {"Vibrantes": history} if history is not None else {},
        "draft_history": {},
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    store.write_bytes(raw)
    return store, raw


class TestFlowConstants:
    def test_flow_constants_enumeration(self) -> None:
        """D2: one guided-character default; the set is the supported enum."""
        assert DEFAULT_FLOW_TYPE == GUIDED_CHARACTER_FLOW == "guided-character"
        assert CO_CREATION_FLOW == "co-creation"
        assert SUPPORTED_FLOW_TYPES == frozenset(
            {GUIDED_CHARACTER_FLOW, CO_CREATION_FLOW}
        )


class TestLegacyCoercion:
    def test_legacy_vibrantes_shape_loads_without_loss(self, tmp_path: Path) -> None:
        """R4: the live world-keyed record coerces into the guided-character
        slot with all fields preserved; the file is byte-identical post-load."""
        store, original = _legacy_store(tmp_path, history=list(_LEGACY_HISTORY))
        library = MethodologyLibrary(store)
        # Load is read-only: bytes unchanged right after construction.
        assert store.read_bytes() == original
        slot = library.active_for("Vibrantes", GUIDED_CHARACTER_FLOW)
        assert slot is not None
        assert slot.world == "Vibrantes"
        assert slot.skill_id == "narrative-character-creation"
        assert slot.version == "1.0"
        assert slot.digest == (
            "2ae521a09bf014ccdefd7296f6ec94092aa6421703802f2d432d9eaf4f1bbe81"
        )
        assert slot.activated_at == "2026-09-11T20:18:25.280907+00:00"
        # The other flow slot stays empty (coercion targets guided-character).
        assert library.active_for("Vibrantes", CO_CREATION_FLOW) is None
        # The legacy history stack coerced into the guided-character flow:
        # rollback restores the previous record (20:18:14 entry).
        restored = library.rollback("Vibrantes", GUIDED_CHARACTER_FLOW)
        assert restored is not None
        assert restored.activated_at == "2026-09-11T20:18:14.774554+00:00"

    def test_load_only_writes_nothing(self, tmp_path: Path) -> None:
        """R4/Rollback: load-time coercion never rewrites the file; reads too."""
        store, original = _legacy_store(tmp_path, history=list(_LEGACY_HISTORY))
        library = MethodologyLibrary(store)
        assert store.read_bytes() == original
        assert library.active_for("Vibrantes", GUIDED_CHARACTER_FLOW) is not None
        assert library.active_for("Vibrantes", CO_CREATION_FLOW) is None
        assert store.read_bytes() == original


class TestPerFlowSlots:
    def test_two_flow_slots_independent(self, tmp_path: Path) -> None:
        """R1: flow-A deactivation leaves flow B's slot, history, and the
        persisted shape untouched."""
        store = tmp_path / "library.json"
        library = MethodologyLibrary(store)
        _publish(library, "skill-a", "1.0.0", "Skill A")
        _publish(library, "skill-a", "1.1.0", "Skill A")
        _publish(library, "skill-b", "2.0.0", "Skill B")
        _publish(library, "skill-b", "2.1.0", "Skill B")
        library.activate("nec", "skill-a", "1.0.0", GUIDED_CHARACTER_FLOW)
        library.activate("nec", "skill-a", "1.1.0", GUIDED_CHARACTER_FLOW)
        library.activate("nec", "skill-b", "2.0.0", CO_CREATION_FLOW)
        library.activate("nec", "skill-b", "2.1.0", CO_CREATION_FLOW)
        assert library.active_for("nec", GUIDED_CHARACTER_FLOW).version == "1.1.0"
        assert library.active_for("nec", CO_CREATION_FLOW).version == "2.1.0"
        # Deactivate flow A only.
        library.deactivate("nec", GUIDED_CHARACTER_FLOW)
        assert library.active_for("nec", GUIDED_CHARACTER_FLOW) is None
        # Flow B's slot, history, and the persisted nested shape are untouched.
        assert library.active_for("nec", CO_CREATION_FLOW).version == "2.1.0"
        with open(store, encoding="utf-8") as handle:
            payload = json.load(handle)
        flows = payload["activations"]["nec"]
        assert list(flows.keys()) == [CO_CREATION_FLOW]
        assert flows[CO_CREATION_FLOW]["skill_id"] == "skill-b"
        assert flows[CO_CREATION_FLOW]["flow_type"] == CO_CREATION_FLOW
        history = payload["history"]["nec"]
        # Flow B's stack is intact; flow A's stack is NOT cleared by its own
        # deactivation (history is per-slot, append-only).
        assert [entry["version"] for entry in history[CO_CREATION_FLOW]] == ["2.0.0"]
        assert [entry["version"] for entry in history[GUIDED_CHARACTER_FLOW]] == [
            "1.0.0",
        ]

    def test_save_persists_nested_activations_key(self, tmp_path: Path) -> None:
        """R4: the first save writes the (world, flow) shape under the stable
        ``activations`` key; reload resolves the same per-flow slot."""
        store = tmp_path / "library.json"
        library = MethodologyLibrary(store)
        _publish(library, "skill-a", "1.0.0", "Skill A")
        _publish(library, "skill-a", "1.1.0", "Skill A")
        library.activate("nec", "skill-a", "1.0.0", CO_CREATION_FLOW)
        library.activate("nec", "skill-a", "1.1.0", CO_CREATION_FLOW)
        with open(store, encoding="utf-8") as handle:
            payload = json.load(handle)
        assert payload["activations"]["nec"][CO_CREATION_FLOW]["skill_id"] == "skill-a"
        assert payload["activations"]["nec"][CO_CREATION_FLOW][
            "flow_type"
        ] == CO_CREATION_FLOW
        assert [entry["version"] for entry in payload["history"]["nec"][CO_CREATION_FLOW]] == [
            "1.0.0",
        ]
        reloaded = MethodologyLibrary(store)
        slot = reloaded.active_for("nec", CO_CREATION_FLOW)
        assert slot is not None
        assert slot.skill_id == "skill-a"
        assert slot.version == "1.1.0"
        assert slot.flow_type == CO_CREATION_FLOW

    def test_activate_unsupported_flow_fails_closed(self, tmp_path: Path) -> None:
        """Task 1.7: activate rejects unsupported/empty flow types before any
        mutation (the library-side gate behind the API 422)."""
        library = _library(tmp_path)
        _publish(library, "skill-a", "1.0.0", "Skill A")
        with pytest.raises(ValidationError):
            library.activate("nec", "skill-a", "1.0.0", "bogus-flow")
        with pytest.raises(ValidationError):
            library.activate("nec", "skill-a", "1.0.0", "")
        # Zero mutation: no slot for any flow.
        assert library.active_for("nec", GUIDED_CHARACTER_FLOW) is None
        assert library.active_for("nec", CO_CREATION_FLOW) is None