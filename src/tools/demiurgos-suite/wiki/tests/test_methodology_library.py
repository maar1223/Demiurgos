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
    CO_CREATION_FLOW,
    CompanionLimitError,
    MAX_COMPANIONS_PER_WORLD,
    MethodologyLibrary,
    MethodologyLibraryError,
    NotPublishedError,
    FOUNDATIONAL_CHARACTER_SKILL_ID,
    FoundationalImmutableError,
    ValidationError,
    _bump_version,
    _version_key,
)
from methodology_compiler import AttachmentEntry, compile_methodology  # noqa: E402
from methodology_trust import OFFICIAL, PERSONALIZADAS  # noqa: E402


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


class TestFoundationalImmutability:
    """S10/S11: records carrying the ``fundacional`` trust attribute are
    immutable — soft_delete raises before ANY mutation. The guard keys on
    the attribute, not the category: a signed non-``fundacional`` Oficiales
    record stays deletable. White-box: no DELETE route exists."""

    def _publish_foundational(self, library: MethodologyLibrary, *,
                              skill_id: str = "foundational-skill",
                              version: str = "1.0.0") -> None:
        draft_id = library.create_draft(
            skill_id=skill_id, version=version,
            name="Foundational skill", source=_valid_source(),
            description="A server-installed foundational skill.",
            clasificacion="Oficiales",
            trust_attributes=("fundacional", "verified"),
        )
        library.publish(draft_id)

    def test_soft_delete_foundational_raises_and_preserves_state(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        self._publish_foundational(library)
        library.activate("nec", "foundational-skill", "1.0.0")
        library.add_companion("nec", "foundational-skill", "1.0.0")
        with pytest.raises(FoundationalImmutableError):
            library.soft_delete("foundational-skill", "1.0.0")
        # Nothing mutated: record still published, activation + companion intact.
        assert library.get_published("foundational-skill", "1.0.0") is not None
        assert library.list_published()
        assert library.active_for("nec") is not None
        assert [c.skill_id for c in library.list_companions("nec")] == ["foundational-skill"]

    def test_soft_delete_unknown_foundational_still_not_published(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        with pytest.raises(NotPublishedError):
            library.soft_delete("foundational-skill", "9.9.9")

    def test_soft_delete_non_fundacional_oficiales_is_allowed(self, tmp_path: Path) -> None:
        """S11: the guard keys on the attribute — a hypothetical signed
        (verified) non-fundacional Oficiales record IS deletable."""
        library = _library(tmp_path)
        draft_id = library.create_draft(
            skill_id="signed-official", version="1.0.0",
            name="Signed official skill", source=_valid_source(),
            description="Officially signed, NOT foundational.",
            clasificacion="Oficiales",
            trust_attributes=("verified",),
        )
        library.publish(draft_id)
        library.soft_delete("signed-official", "1.0.0")
        assert library.get_published("signed-official", "1.0.0") is None
        assert library.list_published() == []


def _compiled(*, version: str = "1.0", skill_id: str = "seeded-skill") -> object:
    """Compile a valid methodology bound to ``skill_id@version``."""
    manifest = dict(_valid_manifest(), skill_id=skill_id, version=version)
    result = compile_methodology(manifest, _valid_source())
    assert result.ok, [issue.message for issue in result.issues]
    return result.compiled


class TestInstallPublishedVersion:
    """3.1: server-side install path — immutable, idempotent, insert-only.

    Covers the two-axis invariant (``fundacional`` ⇒ ``Oficiales``), the
    digest-equal rerun skip, the same-version different-digest permanent
    conflict skip (immutability over auto-heal), and the stored-newer stale
    skip. Install never touches activations or companions (TW15).
    """

    def test_installs_foundational_record_with_server_trust(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        outcome = library.install_published_version(
            _compiled(), clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        assert outcome == "installed"
        published = library.get_published("seeded-skill", "1.0")
        assert published is not None
        assert published.clasificacion == "Oficiales"
        assert published.trust_attributes == ("fundacional",)
        assert published.digest == _compiled().digest
        assert published.parent_skill_id is None

    def test_digest_equal_rerun_is_existing_and_never_duplicates(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        compiled = _compiled()
        assert library.install_published_version(
            compiled, clasificacion="Oficiales", trust_attributes=("fundacional",),
        ) == "installed"
        assert library.install_published_version(
            compiled, clasificacion="Oficiales", trust_attributes=("fundacional",),
        ) == "existing"
        assert len(library.published_versions_for("seeded-skill")) == 1

    def test_same_version_different_digest_conflicts_and_skips_never_heals(
        self, tmp_path: Path,
    ) -> None:
        """A same-version digest mismatch is a PERMANENT skip — the stored
        bytes win; the conflict is never auto-healed (by design)."""
        library = _library(tmp_path)
        original = _compiled()
        library.install_published_version(
            original, clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        tampered = _compiled()
        # A different source yields a different digest at the same version.
        tampered_manifest = dict(_valid_manifest(), skill_id="seeded-skill", version="1.0")
        result = compile_methodology(tampered_manifest, _valid_source() + "\n## extra\n")
        assert result.ok and result.compiled.digest != original.digest
        assert library.install_published_version(
            result.compiled, clasificacion="Oficiales", trust_attributes=("fundacional",),
        ) == "conflict"
        # Skip, not heal: the original digest is untouched and only one record exists.
        versions = library.published_versions_for("seeded-skill")
        assert len(versions) == 1
        assert versions[0]["digest"] == original.digest
        assert library.get_published("seeded-skill", "1.0").digest == original.digest

    def test_older_seed_than_stored_version_is_stale(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        library.install_published_version(
            _compiled(version="1.0"), clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        library.install_published_version(
            _compiled(version="2.0"), clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        # A seed shipping 1.5 (absent key, but older than the stored 2.0) is stale.
        assert library.install_published_version(
            _compiled(version="1.5"), clasificacion="Oficiales", trust_attributes=("fundacional",),
        ) == "stale"
        assert [v["version"] for v in library.published_versions_for("seeded-skill")] == ["1.0", "2.0"]

    def test_newer_seed_installs_beside_older_versions(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        library.install_published_version(
            _compiled(version="1.0"), clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        assert library.install_published_version(
            _compiled(version="2.0"), clasificacion="Oficiales", trust_attributes=("fundacional",),
        ) == "installed"
        assert [v["version"] for v in library.published_versions_for("seeded-skill")] == ["1.0", "2.0"]

    def test_fundacional_requires_oficiales_two_axis_invariant(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        with pytest.raises(AssertionError):
            library.install_published_version(
                _compiled(), clasificacion="Personalizadas", trust_attributes=("fundacional",),
            )

    def test_non_fundacional_install_can_be_soft_deleted(self, tmp_path: Path) -> None:
        """The guard keys on the attribute: a signed (verified) non-fundacional
        Oficiales install stays deletable (S11 parity for the install path)."""
        library = _library(tmp_path)
        library.install_published_version(
            _compiled(), clasificacion="Oficiales", trust_attributes=("verified",),
        )
        library.soft_delete("seeded-skill", "1.0")
        assert library.published_versions_for("seeded-skill") == []

    def test_install_record_persists_and_reloads(self, tmp_path: Path) -> None:
        path = tmp_path / "library.json"
        library = MethodologyLibrary(path)
        library.install_published_version(
            _compiled(), clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        reloaded = MethodologyLibrary(path)
        published = reloaded.get_published("seeded-skill", "1.0")
        assert published is not None
        assert published.clasificacion == "Oficiales"
        assert published.trust_attributes == ("fundacional",)

    def test_install_never_touches_activations_or_companions(self, tmp_path: Path) -> None:
        """TW15: the install path is insert-only — activation slots and
        companion lists for the skill stay exactly as they were."""
        library = _library(tmp_path)
        library.install_published_version(
            _compiled(version="1.0"), clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        library.activate("nec", "seeded-skill", "1.0")
        library.add_companion("nec", "seeded-skill", "1.0")
        library.install_published_version(
            _compiled(version="2.0"), clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        assert library.active_for("nec").version == "1.0"
        assert [c.version for c in library.list_companions("nec")] == ["1.0"]


class TestPublishedVersionsFor:
    """3.1: reconciliation input — live published versions only, sorted."""

    def test_excludes_soft_deleted_versions(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        library.install_published_version(
            _compiled(version="1.0"), clasificacion="Oficiales", trust_attributes=("verified",),
        )
        library.soft_delete("seeded-skill", "1.0")
        assert library.published_versions_for("seeded-skill") == []

    def test_other_skills_are_not_included(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        library.install_published_version(
            _compiled(skill_id="seeded-skill", version="1.0"),
            clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        library.install_published_version(
            _compiled(skill_id="other-skill", version="1.0"),
            clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        assert [v["version"] for v in library.published_versions_for("seeded-skill")] == ["1.0"]


class TestVersionKey:
    """Dependency-free dot-split version comparison (design decision)."""

    def test_numeric_segments_compare_numerically(self) -> None:
        assert _version_key("1.10.0") > _version_key("1.9.0")
        assert _version_key("2.0") > _version_key("1.99.99")

    def test_missing_segments_sort_before_present(self) -> None:
        assert _version_key("1.0") < _version_key("1.0.1")

    def test_non_numeric_segments_sort_after_numeric(self) -> None:
        assert _version_key("1.0") < _version_key("1.v1")
        assert _version_key("1.a") == _version_key("1.a")


class TestCompanions:
    """skill-runtime-bridge WU1 (R-ACT): per-world companion skills.

    Companion state is an independent per-world list — one slot per skill_id,
    capped at 8 (``MAX_COMPANIONS_PER_WORLD``, design DD2/DD4), persisted
    under the additive ``companions`` JSON key, scrubbed by ``soft_delete``,
    and never touching the activation slot.
    """

    def _published_skill(self, library: MethodologyLibrary, *,
                         skill_id: str = "guided-character-v1",
                         version: str = "1.2.0") -> None:
        draft_id = library.create_draft(
            skill_id=skill_id, version=version,
            name="Skill", source=_valid_source(),
            description="A companion skill.",
        )
        library.publish(draft_id)

    def test_companions_persist_and_reload(self, tmp_path: Path) -> None:
        store = tmp_path / "library.json"
        library = MethodologyLibrary(store)
        self._published_skill(library)
        library.add_companion("nec", "guided-character-v1", "1.2.0")
        # Persisted under the additive ``companions`` JSON key.
        payload = json.loads(store.read_text(encoding="utf-8"))
        assert payload["companions"]["nec"][0]["version"] == "1.2.0"
        reloaded = MethodologyLibrary(store)
        companions = reloaded.list_companions("nec")
        assert len(companions) == 1
        assert companions[0].world == "nec"
        assert companions[0].skill_id == "guided-character-v1"
        assert companions[0].version == "1.2.0"

    def test_legacy_file_without_companions_key_loads_empty(self, tmp_path: Path) -> None:
        store = tmp_path / "library.json"
        legacy = {"drafts": {}, "published": {}, "activations": {}, "history": {}}
        store.write_text(json.dumps(legacy), encoding="utf-8")
        library = MethodologyLibrary(store)
        assert library.list_companions("nec") == []
        assert library.remove_companion("nec", "guided-character-v1") is False

    def test_add_companion_rejects_not_published(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        with pytest.raises(NotPublishedError):
            library.add_companion("nec", "guided-character-v1", "9.9.9")
        # A soft-deleted version is not published either.
        self._published_skill(library)
        library.soft_delete("guided-character-v1", "1.2.0")
        with pytest.raises(NotPublishedError):
            library.add_companion("nec", "guided-character-v1", "1.2.0")

    def test_add_companion_enforces_limit(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        for index in range(MAX_COMPANIONS_PER_WORLD):
            self._published_skill(library, skill_id=f"skill-{index}", version="1.0.0")
            library.add_companion("nec", f"skill-{index}", "1.0.0")
        with pytest.raises(CompanionLimitError):
            self._published_skill(library, skill_id="overflow", version="1.0.0")
            library.add_companion("nec", "overflow", "1.0.0")
        # Re-adding an EXISTING skill at a new version replaces it (no growth).
        self._published_skill(library, skill_id="skill-0", version="1.1.0")
        replaced = library.add_companion("nec", "skill-0", "1.1.0")
        assert replaced.version == "1.1.0"
        assert len(library.list_companions("nec")) == MAX_COMPANIONS_PER_WORLD

    def test_companion_ops_never_touch_slot(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        self._published_skill(library, skill_id="slot-skill", version="1.0.0")
        self._published_skill(library, skill_id="companion-skill", version="1.0.0")
        library.activate("nec", "slot-skill", "1.0.0")
        library.activate("nec", "slot-skill", "1.0.0", CO_CREATION_FLOW)
        slot = library.active_for("nec")
        slot_cc = library.active_for("nec", CO_CREATION_FLOW)
        assert slot is not None and slot.skill_id == "slot-skill"
        assert slot_cc is not None and slot_cc.skill_id == "slot-skill"
        library.add_companion("nec", "companion-skill", "1.0.0")
        assert library.active_for("nec") == slot
        assert library.active_for("nec", CO_CREATION_FLOW) == slot_cc
        assert library.list_companions("nec")[0].skill_id == "companion-skill"
        assert library.remove_companion("nec", "companion-skill") is True
        assert library.remove_companion("nec", "companion-skill") is False
        assert library.active_for("nec") == slot
        assert library.active_for("nec", CO_CREATION_FLOW) == slot_cc
        assert library._history == {}

    def test_soft_delete_scrubs_companions_all_worlds(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        self._published_skill(library, skill_id="victim", version="1.0.0")
        self._published_skill(library, skill_id="survivor", version="1.0.0")
        library.add_companion("w1", "victim", "1.0.0")
        library.add_companion("w1", "survivor", "1.0.0")
        library.add_companion("w2", "victim", "1.0.0")
        library.soft_delete("victim", "1.0.0")
        assert [c.skill_id for c in library.list_companions("w1")] == ["survivor"]
        assert library.list_companions("w2") == []
        assert "w2" not in library._companions


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


class TestAdjuntosRegistry:
    """Contract §4 (SR4): the published record carries ``adjuntos`` additively.

    R4: ``_published_record`` always writes the field and ``_published_from``
    decodes it with a ``.get()`` default, so pre-PR③ records (no ``adjuntos``)
    load unchanged with an empty tuple and a publish with entries round-trips
    every entry and field intact (S6/S7).
    """

    def _entries(self) -> tuple[AttachmentEntry, ...]:
        return (
            AttachmentEntry(
                path="ejemplos/Axill_Garner.md", sha256="a" * 64,
                bytes=6115, nivel="1º",
            ),
            AttachmentEntry(
                path="ejemplos/Villano_Korrane.md", sha256="b" * 64,
                bytes=9802, nivel="3º",
            ),
        )

    def test_publish_with_entries_round_trips_every_field(self, tmp_path: Path) -> None:
        """S7: publish with two entries — every entry and field survives."""
        store = tmp_path / "library.json"
        library = MethodologyLibrary(store)
        draft_id = library.create_draft(
            skill_id=_valid_manifest()["skill_id"],
            version=_valid_manifest()["version"],
            name=_valid_manifest()["name"],
            source=_valid_source(),
            description=_valid_manifest()["description"],
            adjuntos=self._entries(),
        )
        published = library.publish(draft_id)
        assert [e.as_dict() for e in published.adjuntos] == [
            e.as_dict() for e in self._entries()
        ]
        read_back = library.get_published(
            _valid_manifest()["skill_id"], _valid_manifest()["version"],
        )
        assert read_back is not None
        assert [e.as_dict() for e in read_back.adjuntos] == [
            e.as_dict() for e in self._entries()
        ]
        reloaded = MethodologyLibrary(store)
        persisted = reloaded.get_published(
            _valid_manifest()["skill_id"], _valid_manifest()["version"],
        )
        assert persisted is not None
        assert persisted.adjuntos == self._entries()

    def test_publish_without_adjuntos_defaults_empty(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        published = library.publish(_draft(library))
        assert published.adjuntos == ()

    def test_pre_pr3_record_without_adjuntos_decodes_empty(self, tmp_path: Path) -> None:
        """S6: a hand-written pre-PR③ record (no ``adjuntos``) decodes with
        an empty default — additive back-compat, nothing dropped."""
        store = tmp_path / "library.json"
        legacy_payload = {
            "drafts": {},
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
        store.write_text(json.dumps(legacy_payload), encoding="utf-8")
        library = MethodologyLibrary(store)
        published = library.get_published("guided-character-v1", "1.2.0")
        assert published is not None
        assert published.adjuntos == ()


# ---------------------------------------------------------------------------
# TW13/TW14 — derived drafts + server-injected provenance (Phase 2 / PR 2)
# ---------------------------------------------------------------------------


class TestDerivedDrafts:
    """REQ-CC-16/19/20: derived drafts read identity from the PUBLISHED
    record, inject provenance server-side, auto-version +1, and never touch
    the original."""

    def _published_original(self, library: MethodologyLibrary, *, version: str = "1.2.0",
                            clasificacion: str | None = "Oficiales") -> None:
        draft_id = library.create_draft(
            skill_id="guided-character-v1", version=version,
            name="Guided character methodology", source=_valid_source(),
            description=_valid_manifest()["description"],
            clasificacion=clasificacion,
            trust_attributes=("verified",),
        )
        library.publish(draft_id)

    def test_create_derived_draft_injects_provenance_from_published_record(
        self, tmp_path: Path,
    ) -> None:
        library = _library(tmp_path)
        self._published_original(library)
        derived_id = library.create_derived_draft(
            "guided-character-v1", "1.2.0",
            seed_source=_valid_source() + "\n# adaptado\n",
            name="Guided character methodology (adaptada)",
        )
        derived = library.get_draft(derived_id)
        assert derived is not None
        # Server-injected identity read from the PUBLISHED record.
        assert derived.parent_skill_id == "guided-character-v1"
        assert derived.parent_version == "1.2.0"
        # version+1 policy (REQ-CC-19).
        assert derived.version == "1.2.1"
        # Seed source + inherited metadata from the original.
        assert derived.source.endswith("# adaptado\n")
        assert derived.description == _valid_manifest()["description"]
        # S9: a derived fork is local authorship — classification is forced
        # to Personalizadas (deliberate flip from the pre-change inheritance
        # of the original's Oficiales), trust keeps verified.
        assert derived.clasificacion == "Personalizadas"
        assert derived.trust_attributes == ("verified",)

    def test_derived_draft_scrubs_foundational_keeps_provenance(self, tmp_path: Path) -> None:
        """S9: deriving from a fundacional original demotes the fork —
        Personalizadas, no ``fundacional`` marker, other attributes kept,
        TW14 provenance intact."""
        library = _library(tmp_path)
        original_id = library.create_draft(
            skill_id="guided-character-v1", version="1.2.0",
            name="Guided character methodology", source=_valid_source(),
            description=_valid_manifest()["description"],
            clasificacion="Oficiales",
            trust_attributes=("fundacional", "verified"),
        )
        library.publish(original_id)
        derived_id = library.create_derived_draft(
            "guided-character-v1", "1.2.0",
            seed_source=_valid_source() + "\n# adaptado\n",
            name="Guided character methodology (adaptada)",
        )
        derived = library.get_draft(derived_id)
        assert derived is not None
        assert derived.clasificacion == "Personalizadas"
        assert "fundacional" not in derived.trust_attributes
        assert derived.trust_attributes == ("verified",)
        assert derived.parent_skill_id == "guided-character-v1"
        assert derived.parent_version == "1.2.0"

    def test_create_derived_draft_requires_published_original(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        with pytest.raises(NotPublishedError):
            library.create_derived_draft(
                "guided-character-v1", "9.9.9",
                seed_source="x\n", name="Ghost",
            )

    def test_create_derived_draft_rejects_wrong_caller_version(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        self._published_original(library)
        with pytest.raises(ValidationError):
            library.create_derived_draft(
                "guided-character-v1", "1.2.0",
                seed_source="x\n", name="Bad", version="1.2.0",
            )
        # The matching version+1 value is accepted.
        derived_id = library.create_derived_draft(
            "guided-character-v1", "1.2.0",
            seed_source="x\n", name="Good", version="1.2.1",
        )
        assert library.get_draft(derived_id).version == "1.2.1"

    def test_derived_draft_has_no_public_identity_params(self, tmp_path: Path) -> None:
        """REQ-CC-20: the client can never supply provenance — the method
        signature accepts no parent/derived_from parameters."""
        library = _library(tmp_path)
        self._published_original(library)
        import inspect
        signature = inspect.signature(library.create_derived_draft)
        names = set(signature.parameters)
        assert "parent_skill_id" not in names
        assert "parent_version" not in names
        assert "derived_from" not in names

    def test_publish_copies_parent_fields_and_auto_versions(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        self._published_original(library)
        derived_id = library.create_derived_draft(
            "guided-character-v1", "1.2.0",
            seed_source=_valid_source(), name="Adaptada",
        )
        published = library.publish(derived_id)
        # REQ-CC-19: S@1.2.1 with provenance pointing to S@1.2.0.
        assert published.version == "1.2.1"
        assert published.parent_skill_id == "guided-character-v1"
        assert published.parent_version == "1.2.0"
        # REQ-CC-21: provenance visible on the published record.
        stored = library.get_published("guided-character-v1", "1.2.1")
        assert stored is not None
        assert stored.parent_skill_id == "guided-character-v1"
        assert stored.parent_version == "1.2.0"
        # Original untouched (REQ-CC-19): same source and digest.
        original = library.get_published("guided-character-v1", "1.2.0")
        assert original is not None
        assert original.source == _valid_source()
        assert original.parent_skill_id is None

    def test_derived_publish_version_mismatch_fails_closed(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        self._published_original(library)
        derived_id = library.create_derived_draft(
            "guided-character-v1", "1.2.0",
            seed_source=_valid_source(), name="Adaptada",
        )
        # Tamper the draft record's version (white-box): a derived draft must
        # publish as parent+1, never at the parent's own version.
        with library._lock:
            library._drafts[derived_id]["version"] = "1.2.0"
        with pytest.raises(ValidationError):
            library.publish(derived_id)
        assert library.get_published("guided-character-v1", "1.2.0") is not None
        assert library.get_published("guided-character-v1", "1.2.1") is None

    def test_derived_publish_leaves_original_immutable_under_edits(self, tmp_path: Path) -> None:
        """REQ-CC-19: editing the derived draft never changes S@V."""
        library = _library(tmp_path)
        self._published_original(library)
        original = library.get_published("guided-character-v1", "1.2.0")
        assert original is not None
        derived_id = library.create_derived_draft(
            "guided-character-v1", "1.2.0",
            seed_source=_valid_source(), name="Adaptada",
        )
        library.update_draft(derived_id, source=_valid_source() + "# cambiado\n")
        after = library.get_published("guided-character-v1", "1.2.0")
        assert after is not None
        assert after.source == original.source
        assert after.digest == original.digest

    def test_bump_version_policy(self) -> None:
        assert _bump_version("1.2.0") == "1.2.1"
        assert _bump_version("1.0") == "1.1"
        assert _bump_version("9") == "10"
        assert _bump_version("v1") == "v1.1"


class TestReservedSkillId:
    """REQ-IMP-6: the foundational character-skill id is reserved — it can
    never be published from an import-derived draft, while direct workshop
    authorship stays valid."""

    def test_constant_value_is_pinned(self) -> None:
        assert FOUNDATIONAL_CHARACTER_SKILL_ID == "narrative-character-creation"

    def test_publish_foundational_original_is_allowed(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = library.create_draft(
            skill_id=FOUNDATIONAL_CHARACTER_SKILL_ID, version="1.0.0",
            name="Skill Madre", source=_valid_source(),
            description="La skill madre del taller.",
        )
        published = library.publish(draft_id)
        assert published.skill_id == FOUNDATIONAL_CHARACTER_SKILL_ID
        assert published.version == "1.0.0"

    def test_publish_import_derived_foundational_is_rejected(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        foundational = library.create_draft(
            skill_id=FOUNDATIONAL_CHARACTER_SKILL_ID, version="1.0.0",
            name="Skill Madre", source=_valid_source(),
            description="La skill madre del taller.",
        )
        library.publish(foundational)
        # An import-derived draft carries server-injected parent_skill_id;
        # publishing it must fail closed before any record is written.
        derived = library.create_derived_draft(
            FOUNDATIONAL_CHARACTER_SKILL_ID, "1.0.0",
            seed_source=_valid_source(), name="Skill Madre importada",
        )
        with pytest.raises(MethodologyLibraryError) as excinfo:
            library.publish(derived)
        assert str(excinfo.value) == "reserved_skill_id"
        assert library.get_published(FOUNDATIONAL_CHARACTER_SKILL_ID, "1.0.1") is None


class TestDraftHistory:
    """TW13: snapshot-on-update history for post-materialize edits."""

    def test_update_draft_snapshots_previous_state(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = _draft(library)
        library.update_draft(draft_id, source=_valid_source() + "# v2\n")
        library.update_draft(draft_id, source=_valid_source() + "# v3\n")
        history = library.list_draft_history(draft_id)
        assert len(history) == 2
        # Each entry records the PRE-update record; oldest first.
        assert history[0]["record"]["source"] == _valid_source()
        assert history[1]["record"]["source"] == _valid_source() + "# v2\n"
        assert library.get_draft(draft_id).source == _valid_source() + "# v3\n"

    def test_draft_history_survives_reload(self, tmp_path: Path) -> None:
        store = tmp_path / "library.json"
        library = MethodologyLibrary(store)
        draft_id = _draft(library)
        library.update_draft(draft_id, source=_valid_source() + "# v2\n")
        reloaded = MethodologyLibrary(store)
        history = reloaded.list_draft_history(draft_id)
        assert len(history) == 1
        assert history[0]["record"]["source"] == _valid_source()

    def test_update_draft_accepts_inventory_fields(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = _draft(library)
        updated = library.update_draft(
            draft_id,
            taller="Creación",
            talleres_compatibles=("Diseño",),
            categoria_funcional="Análisis",
            etiquetas=("lore",),
            clasificacion="Personalizadas",
            trust_attributes=("verified",),
        )
        assert updated.taller == "Creación"
        assert updated.talleres_compatibles == ("Diseño",)
        assert updated.categoria_funcional == "Análisis"
        assert updated.etiquetas == ("lore",)
        assert updated.clasificacion == "Personalizadas"
        assert updated.trust_attributes == ("verified",)

    def test_update_draft_never_touches_provenance(self, tmp_path: Path) -> None:
        """Ordinary edits preserve the server-injected parent identity."""
        library = _library(tmp_path)
        original = library.create_draft(
            skill_id="guided-character-v1", version="1.2.0",
            name="Original", source=_valid_source(),
        )
        library.publish(original)
        derived_id = library.create_derived_draft(
            "guided-character-v1", "1.2.0",
            seed_source=_valid_source(), name="Adaptada",
        )
        library.update_draft(derived_id, source=_valid_source() + "# v2\n")
        draft = library.get_draft(derived_id)
        assert draft is not None
        assert draft.parent_skill_id == "guided-character-v1"
        assert draft.parent_version == "1.2.0"


class TestProvenanceManifestExclusion:
    """REQ-CC-22: provenance stays OUT of the manifest and the digest."""

    def test_compiler_rejects_provenance_keys_in_manifest(self) -> None:
        from methodology_compiler import compile_methodology
        for key in ("parent_skill_id", "parent_version", "derived_from"):
            manifest = dict(_valid_manifest())
            manifest[key] = "x"
            result = compile_methodology(manifest, _valid_source())
            assert not result.ok, key
            assert any(issue.code == "unknown-field" for issue in result.issues), key

    def test_manifest_for_never_includes_provenance(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        library.publish(_draft(library))
        derived_id = library.create_derived_draft(
            "guided-character-v1", "1.2.0",
            seed_source=_valid_source(), name="Adaptada",
        )
        derived = library.get_draft(derived_id)
        assert derived is not None
        manifest = library.manifest_for(derived)
        assert "parent_skill_id" not in manifest
        assert "parent_version" not in manifest
        assert "derived_from" not in manifest

    def test_digest_stable_across_provenance_variants(self, tmp_path: Path) -> None:
        """Two drafts identical in content/version but different provenance
        compile to the SAME digest (metadata, not identity)."""
        library = _library(tmp_path)
        library.publish(_draft(library))  # guided-character-v1@1.2.0 (Oficiales-free)
        derived_id = library.create_derived_draft(
            "guided-character-v1", "1.2.0",
            seed_source=_valid_source(), name="Adaptada",
        )
        # The plain twin carries the same content the derived draft inherited
        # from the original, at the same version+1 — only provenance differs.
        plain_id = library.create_draft(
            skill_id="guided-character-v1", version="1.2.1",
            name="Adaptada", source=_valid_source(),
            description=_valid_manifest()["description"],
        )
        derived_result = library.compile_draft(derived_id)
        plain_result = library.compile_draft(plain_id)
        assert derived_result.ok and plain_result.ok
        assert derived_result.compiled is not None and plain_result.compiled is not None
        assert derived_result.compiled.digest == plain_result.compiled.digest

    def test_provenance_survives_reload_from_disk(self, tmp_path: Path) -> None:
        store = tmp_path / "library.json"
        library = MethodologyLibrary(store)
        library.publish(_draft(library))
        derived_id = library.create_derived_draft(
            "guided-character-v1", "1.2.0",
            seed_source=_valid_source(), name="Adaptada",
        )
        library.publish(derived_id)
        reloaded = MethodologyLibrary(store)
        draft = reloaded.get_draft(derived_id)
        assert draft is not None
        assert draft.parent_skill_id == "guided-character-v1"
        assert draft.parent_version == "1.2.0"
        published = reloaded.get_published("guided-character-v1", "1.2.1")
        assert published is not None
        assert published.parent_skill_id == "guided-character-v1"
        assert published.parent_version == "1.2.0"
