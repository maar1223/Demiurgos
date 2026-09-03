"""RED/unit tests for the methodology library.

Covers the managed methodology lifecycle: editable drafts, compiler
validation, immutable published versions, per-world activation,
deactivation/rollback, and recoverable soft deletion. The library must never
touch the kernel, canon files, or any path outside its own root.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from methodology_library import (  # noqa: E402
    AlreadyPublishedError,
    MethodologyLibrary,
    NotPublishedError,
    ValidationError,
)


def _valid_manifest() -> dict:
    return {
        "skill_id": "guided-character-v1",
        "version": "1.2.0",
        "name": "Guided character methodology",
        "description": "A safe construction methodology for guided characters.",
        "phases": ["conversation", "review", "complete"],
        "language": "es",
    }


def _valid_source() -> str:
    return "## Construcción segura\n\nHaz preguntas de a una.\n"


def _library(tmp_path: Path) -> MethodologyLibrary:
    return MethodologyLibrary(tmp_path / "library.json")


def _draft(library: MethodologyLibrary) -> str:
    return library.create_draft(
        skill_id=_valid_manifest()["skill_id"],
        version=_valid_manifest()["version"],
        name=_valid_manifest()["name"],
        source=_valid_source(),
        description=_valid_manifest()["description"],
    )


class TestDrafts:
    def test_draft_is_editable(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = _draft(library)
        library.update_draft(draft_id, source=_valid_source() + "# more\n")
        draft = library.get_draft(draft_id)
        assert draft is not None
        assert "# more" in draft.source

    def test_draft_missing_is_none(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        assert library.get_draft("missing") is None

    def test_drafts_list(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        _draft(library)
        assert len(library.list_drafts()) == 1


class TestCompilerGate:
    def test_compile_rejects_authority_claim(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = _draft(library)
        library.update_draft(draft_id, source=_valid_source() + "\n#!demiurgos-authority\n")
        result = library.compile_draft(draft_id)
        assert not result.ok
        assert any(issue.code == "authority-claim" for issue in result.issues)

    def test_publish_rejects_invalid_draft(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = _draft(library)
        library.update_draft(draft_id, source=_valid_source() + "\npermissions: all\n")
        with pytest.raises(ValidationError):
            library.publish(draft_id)


class TestImmutablePublish:
    def test_publish_creates_immutable_version(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = _draft(library)
        published = library.publish(draft_id)
        assert published.version == "1.2.0"
        assert library.get_published("guided-character-v1", "1.2.0") == published
        assert library.list_published()[0].skill_id == "guided-character-v1"

    def test_republish_with_different_digest_is_rejected(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        library.publish(_draft(library))
        other = library.create_draft(
            skill_id="guided-character-v1", version="1.2.0",
            name="Different", source="Diferente.\n",
        )
        with pytest.raises(AlreadyPublishedError):
            library.publish(other)

    def test_published_version_is_immutable(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        published = library.publish(_draft(library))
        with pytest.raises(Exception):
            published.name = "changed"  # type: ignore[misc]


class TestActivation:
    def test_activate_by_world(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        library.publish(_draft(library))
        activation = library.activate("nec", "guided-character-v1", "1.2.0")
        assert activation.world == "nec"
        assert library.active_for("nec") == activation
        assert library.active_for("other-world") is None

    def test_activate_unpublished_raises(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        with pytest.raises(NotPublishedError):
            library.activate("nec", "guided-character-v1", "9.9.9")

    def test_deactivate_clears_world(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        library.publish(_draft(library))
        library.activate("nec", "guided-character-v1", "1.2.0")
        library.deactivate("nec")
        assert library.active_for("nec") is None

    def test_rollback_restores_previous_version(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        library.publish(_draft(library))
        v2 = library.create_draft(
            skill_id="guided-character-v1", version="1.3.0",
            name="v2", source="Nueva.\n",
        )
        library.publish(v2)
        library.activate("nec", "guided-character-v1", "1.3.0")
        library.activate("nec", "guided-character-v1", "1.2.0")
        library.rollback("nec")
        assert library.active_for("nec") is not None
        assert library.active_for("nec").version == "1.3.0"


class TestSoftDelete:
    def test_soft_delete_is_recoverable(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        library.publish(_draft(library))
        library.soft_delete("guided-character-v1", "1.2.0")
        assert library.list_published() == []
        library.restore("guided-character-v1", "1.2.0")
        assert len(library.list_published()) == 1

    def test_deleted_cannot_be_activated(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        library.publish(_draft(library))
        library.soft_delete("guided-character-v1", "1.2.0")
        with pytest.raises(NotPublishedError):
            library.activate("nec", "guided-character-v1", "1.2.0")


class TestNoKernelAccess:
    def test_library_never_writes_outside_its_root(self, tmp_path: Path) -> None:
        root = tmp_path / "library.json"
        library = MethodologyLibrary(root)
        library.publish(_draft(library))
        # Nothing else may have been created next to the store file.
        assert sorted(p.name for p in tmp_path.iterdir()) == ["library.json"]


class TestInventoryRecords:
    """Taller de Herramientas Fase 1: record extensions + backward compat.

    Inventory fields and system-derived classification/trust attributes are
    optional with defaults; old JSON records deserialize safely.
    """

    def test_create_draft_with_inventory_fields_is_stored(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = library.create_draft(
            skill_id="guided-character-v1", version="1.2.0",
            name="Guided character methodology", source=_valid_source(),
            taller="Creación",
            talleres_compatibles=("Investigación", "Diseño"),
            categoria_funcional="Análisis",
            etiquetas=("lore", "npc"),
            clasificacion="Personalizadas",
            trust_attributes=("quarantined",),
        )
        draft = library.get_draft(draft_id)
        assert draft is not None
        assert draft.taller == "Creación"
        assert draft.talleres_compatibles == ("Investigación", "Diseño")
        assert draft.categoria_funcional == "Análisis"
        assert draft.etiquetas == ("lore", "npc")
        assert draft.clasificacion == "Personalizadas"
        assert draft.trust_attributes == ("quarantined",)

    def test_create_draft_without_inventory_fields_applies_defaults(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = _draft(library)
        draft = library.get_draft(draft_id)
        assert draft is not None
        assert draft.taller is None
        assert draft.talleres_compatibles == ()
        assert draft.categoria_funcional is None
        assert draft.etiquetas == ()
        assert draft.clasificacion is None
        assert draft.trust_attributes == ()

    def test_publish_threads_inventory_fields_from_draft(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = library.create_draft(
            skill_id="guided-character-v1", version="1.2.0",
            name="Guided character methodology", source=_valid_source(),
            taller="Creación",
            talleres_compatibles=("Investigación",),
            categoria_funcional="Análisis",
            etiquetas=("lore",),
            clasificacion="Oficiales",
            trust_attributes=("verified",),
        )
        published = library.publish(draft_id)
        assert published.taller == "Creación"
        assert published.talleres_compatibles == ("Investigación",)
        assert published.categoria_funcional == "Análisis"
        assert published.etiquetas == ("lore",)
        assert published.clasificacion == "Oficiales"
        assert published.trust_attributes == ("verified",)

    def test_publish_digest_unaffected_by_inventory_fields(self, tmp_path: Path) -> None:
        """Same content with/without inventory metadata → identical digest, so
        an idempotent republish is recognized (stored version returned, no
        ``AlreadyPublishedError``)."""
        library = _library(tmp_path)
        plain = library.publish(_draft(library))
        with_inventory = library.create_draft(
            skill_id="guided-character-v1", version="1.2.0",
            name="Guided character methodology", source=_valid_source(),
            description=_valid_manifest()["description"],
            taller="Creación",
            talleres_compatibles=("Investigación",),
            categoria_funcional="Análisis",
            etiquetas=("lore",),
        )
        republished = library.publish(with_inventory)
        assert republished.digest == plain.digest
        assert republished == plain  # idempotent: stored version returned

    def test_old_json_records_deserialize_with_defaults(self, tmp_path: Path) -> None:
        """A pre-inventory library.json loads without the new fields."""
        store = tmp_path / "library.json"
        old_payload = {
            "drafts": {
                "d1": {
                    "draft_id": "d1", "skill_id": "guided-character-v1",
                    "version": "1.2.0", "name": "Old draft", "source": "x\n",
                    "description": "", "phases": [], "language": "es",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
            },
            "published": {
                "guided-character-v1@1.2.0": {
                    "skill_id": "guided-character-v1", "version": "1.2.0",
                    "name": "Old published", "description": "", "phases": [],
                    "language": "es", "source": "x\n", "digest": "a" * 64,
                    "published_at": "2026-01-01T00:00:00+00:00", "deleted_at": None,
                },
            },
            "activations": {},
            "history": {},
        }
        store.write_text(json.dumps(old_payload), encoding="utf-8")
        library = MethodologyLibrary(store)
        draft = library.get_draft("d1")
        assert draft is not None
        assert draft.taller is None
        assert draft.etiquetas == ()
        assert draft.clasificacion is None
        assert draft.trust_attributes == ()
        published = library.get_published("guided-character-v1", "1.2.0")
        assert published is not None
        assert published.taller is None
        assert published.etiquetas == ()
        assert published.clasificacion is None
        assert published.trust_attributes == ()

    def test_inventory_fields_survive_reload_from_disk(self, tmp_path: Path) -> None:
        store = tmp_path / "library.json"
        library = MethodologyLibrary(store)
        draft_id = library.create_draft(
            skill_id="guided-character-v1", version="1.2.0",
            name="Guided character methodology", source=_valid_source(),
            taller="Creación",
            etiquetas=("lore",),
            clasificacion="Comunitarias",
        )
        library.publish(draft_id)
        reloaded = MethodologyLibrary(store)
        published = reloaded.get_published("guided-character-v1", "1.2.0")
        assert published is not None
        assert published.taller == "Creación"
        assert published.etiquetas == ("lore",)
        assert published.clasificacion == "Comunitarias"
        assert published.trust_attributes == ()
