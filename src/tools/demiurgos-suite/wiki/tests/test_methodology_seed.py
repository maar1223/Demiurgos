"""RED/unit tests for the methodology seed catalog loader.

Covers S1 (the real repo seed root loads exactly the MVP entry
``narrative-character-creation@1.3``, the seed is compiler-clean with zero
authority-claim issues, and the git state keeps the seeds tracked while the
runtime store stays ignored) and S3-load fail-closed behavior (corrupt
checksum, malformed manifest, and compiler-rejected manifest never produce a
partial catalog).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

REPO_ROOT = _WIKI.parents[3]
SEED_ROOT = REPO_ROOT / "data" / "methodology" / "seeds"

from methodology_compiler import compile_methodology  # noqa: E402
from methodology_library import MethodologyLibrary  # noqa: E402
from methodology_seed import SeedIntegrityError, install_seeds, load_seed_catalog  # noqa: E402


def _valid_manifest(skill_id: str) -> dict:
    return {
        "skill_id": skill_id,
        "version": "1.0",
        "name": "Skill de prueba",
        "description": "Metodología de prueba para el catálogo de seeds.",
        "phases": ["fase uno", "fase dos"],
        "language": "es",
    }


def _write_seed(
    root: Path,
    skill_id: str,
    *,
    manifest: dict | None = None,
    source: str = "## Metodología de prueba\n\nContenido de prueba.\n",
    adjuntos: list[dict] | None = None,
) -> Path:
    """Write a valid seed entry mirroring the trust-boundary canonical bytes.

    ``manifest.yaml`` is serialized with the same YAML dump the package
    builder uses and ``checksums.json`` holds the SHA-256 of the exact bundled
    bytes, so the fixture matches real seed semantics. When ``adjuntos`` is
    given, each entry's carrier file is written (deterministic bytes derived
    from the path) and a ``sha256`` left as ``None`` is filled from the actual
    carrier bytes; the carrier path joins ``checksums.json`` exactly like a
    real seed package would.
    """
    entry_dir = root / skill_id
    entry_dir.mkdir(parents=True, exist_ok=True)
    manifest_dict = dict(manifest or _valid_manifest(skill_id))
    carriers: dict[str, bytes] = {}
    for entry in (adjuntos or []):
        path = entry["path"]
        carrier = f"# {path}\n\nContenido de ejemplo.\n".encode("utf-8")
        if entry.get("sha256") is None:
            entry["sha256"] = hashlib.sha256(carrier).hexdigest()
        carriers[path] = carrier
    if adjuntos is not None:
        manifest_dict["adjuntos"] = adjuntos
    manifest_bytes = yaml.safe_dump(
        manifest_dict, sort_keys=False, allow_unicode=True,
    ).encode("utf-8")
    source_bytes = source.encode("utf-8")
    (entry_dir / "manifest.yaml").write_bytes(manifest_bytes)
    (entry_dir / "source.md").write_bytes(source_bytes)
    for path, carrier in carriers.items():
        (entry_dir / path).parent.mkdir(parents=True, exist_ok=True)
        (entry_dir / path).write_bytes(carrier)
    checksums = {
        "manifest.yaml": hashlib.sha256(manifest_bytes).hexdigest(),
        "source.md": hashlib.sha256(source_bytes).hexdigest(),
        **{path: hashlib.sha256(carrier).hexdigest() for path, carrier in carriers.items()},
    }
    (entry_dir / "checksums.json").write_text(
        json.dumps(checksums, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return entry_dir


class TestSeedCatalogS1:
    """S1: catalog present — the real repo seed root loads the MVP entry."""

    def test_real_repo_seed_root_loads_exactly_the_mvp_entry(self) -> None:
        catalog = load_seed_catalog(SEED_ROOT)
        assert len(catalog) == 3
        entry = catalog[0]
        assert entry.skill_id == "narrative-character-creation"
        assert entry.version == "1.3"
        assert entry.manifest["skill_id"] == "narrative-character-creation"
        assert entry.manifest["version"] == "1.3"
        # The seed manifest declares its operational home taller (S1): the
        # seeded skill renders in the Mundo tree, never in "Sin taller".
        assert entry.manifest["taller"] == "Mundo"

    def test_real_seed_is_compiler_clean(self) -> None:
        entry = load_seed_catalog(SEED_ROOT)[0]
        result = compile_methodology(entry.manifest, entry.source)
        assert result.ok, [issue.message for issue in result.issues]
        assert not any(issue.code == "authority-claim" for issue in result.issues)

    def test_real_seed_phases_respect_compiler_bounds(self) -> None:
        entry = load_seed_catalog(SEED_ROOT)[0]
        phases = entry.manifest["phases"]
        assert len(phases) <= 12
        assert all(len(phase.strip()) <= 64 for phase in phases)

    def test_absent_seed_root_is_an_empty_catalog(self, tmp_path: Path) -> None:
        assert load_seed_catalog(tmp_path / "no-such-seeds") == []


class TestSeedIntegrityFailClosed:
    """S3-load: invalid seeds fail closed — no partial catalog is returned."""

    def test_corrupt_checksum_raises(self, tmp_path: Path) -> None:
        entry = _write_seed(tmp_path, "demo-skill")
        (entry / "source.md").write_text(
            "## Metodología de prueba\n\nContenido modificado.\n", encoding="utf-8",
        )
        with pytest.raises(SeedIntegrityError):
            load_seed_catalog(tmp_path)

    def test_malformed_manifest_raises(self, tmp_path: Path) -> None:
        _write_seed(tmp_path, "demo-skill")
        (tmp_path / "demo-skill" / "manifest.yaml").write_text(
            "skill_id: [unclosed", encoding="utf-8",
        )
        with pytest.raises(SeedIntegrityError):
            load_seed_catalog(tmp_path)

    def test_missing_required_files_raises(self, tmp_path: Path) -> None:
        _write_seed(tmp_path, "demo-skill")
        (tmp_path / "demo-skill" / "checksums.json").unlink()
        with pytest.raises(SeedIntegrityError):
            load_seed_catalog(tmp_path)

    def test_dir_name_must_match_manifest_skill_id(self, tmp_path: Path) -> None:
        manifest = dict(_valid_manifest("other-skill"))
        _write_seed(tmp_path, "demo-skill", manifest=manifest)
        with pytest.raises(SeedIntegrityError):
            load_seed_catalog(tmp_path)

    def test_no_partial_catalog_on_corrupt_entry(self, tmp_path: Path) -> None:
        _write_seed(tmp_path, "good-skill")
        bad = _write_seed(tmp_path, "bad-skill")
        (bad / "source.md").write_bytes(b"tampered bytes")
        with pytest.raises(SeedIntegrityError):
            load_seed_catalog(tmp_path)

    def test_unknown_manifest_field_is_compiler_rejected(self, tmp_path: Path) -> None:
        # The loader is integrity-only and passes; the compiler gate rejects
        # the manifest field, proving a broken seed never compiles.
        manifest = dict(_valid_manifest("demo-skill"), clasificacion="Oficiales")
        _write_seed(tmp_path, "demo-skill", manifest=manifest)
        entry = load_seed_catalog(tmp_path)[0]
        result = compile_methodology(entry.manifest, entry.source)
        assert not result.ok
        assert any(issue.code == "unknown-field" for issue in result.issues)


class TestSeedGitTracking:
    """S1: the seed catalog is committed; the runtime store is not."""

    def test_seed_dir_is_tracked_and_runtime_store_ignored(self) -> None:
        git = shutil.which("git")
        if git is None:
            pytest.skip("git unavailable — cannot assert tracked state")
        tracked = subprocess.run(
            [git, "-C", str(REPO_ROOT), "ls-files", "data/methodology/seeds/"],
            capture_output=True, text=True, check=False,
        )
        assert tracked.returncode == 0, tracked.stderr
        assert tracked.stdout.splitlines(), "seed catalog must be committed"
        for path in ("data/methodology/library.json", "data/methodology/quarantine/"):
            ignored = subprocess.run(
                [git, "-C", str(REPO_ROOT), "check-ignore", "-q", "--", path],
                capture_output=True, text=True, check=False,
            )
            assert ignored.returncode == 0, f"{path} must be git-ignored"


class TestSeedAdjuntosVerification:
    """R3/R6 (S5/S9/S10): declared attachment carriers are verified against the
    manifest ``sha256`` AND ``checksums.json``; zero-attachment seeds behave
    byte-identically to pre-PR③ (same validation, same error texts).
    """

    def _adjunto(self, path: str = "ejemplos/Axill.md", sha256: str | None = None) -> dict:
        return {"path": path, "sha256": sha256, "bytes": 1024, "nivel": "1º"}

    def test_carrier_verified_and_manifest_compiler_clean(self, tmp_path: Path) -> None:
        """S5: in a two-entry root, the seed that declares an attachment loads
        and compiles clean; the sibling seed without attachments loads too."""
        _write_seed(tmp_path, "demo-skill", adjuntos=[self._adjunto()])
        _write_seed(tmp_path, "demo-skill-two")
        catalog = load_seed_catalog(tmp_path)
        assert len(catalog) == 2
        assert catalog[0].manifest["adjuntos"][0]["path"] == "ejemplos/Axill.md"
        result = compile_methodology(catalog[0].manifest, catalog[0].source)
        assert result.ok, [issue.message for issue in result.issues]

    def test_tampered_carrier_raises_with_no_partial_catalog(self, tmp_path: Path) -> None:
        """S9: modifying the carrier bytes fails the whole catalog load."""
        _write_seed(tmp_path, "good-skill")
        bad = _write_seed(tmp_path, "bad-skill", adjuntos=[self._adjunto()])
        (bad / "ejemplos" / "Axill.md").write_bytes(b"tampered bytes")
        with pytest.raises(SeedIntegrityError):
            load_seed_catalog(tmp_path)

    def test_absent_carrier_raises(self, tmp_path: Path) -> None:
        entry = _write_seed(tmp_path, "demo-skill", adjuntos=[self._adjunto()])
        (entry / "ejemplos" / "Axill.md").unlink()
        with pytest.raises(SeedIntegrityError):
            load_seed_catalog(tmp_path)

    def test_missing_checksums_entry_raises(self, tmp_path: Path) -> None:
        entry = _write_seed(tmp_path, "demo-skill", adjuntos=[self._adjunto()])
        checksums = json.loads((entry / "checksums.json").read_text(encoding="utf-8"))
        checksums.pop("ejemplos/Axill.md")
        (entry / "checksums.json").write_text(json.dumps(checksums), encoding="utf-8")
        with pytest.raises(SeedIntegrityError):
            load_seed_catalog(tmp_path)

    def test_declared_sha256_mismatch_raises(self, tmp_path: Path) -> None:
        """R3: manifest sha256 not matching observed carrier bytes fails closed."""
        _write_seed(tmp_path, "demo-skill", adjuntos=[self._adjunto(sha256="0" * 64)])
        with pytest.raises(SeedIntegrityError):
            load_seed_catalog(tmp_path)

    def test_zero_attachment_seed_is_byte_identical(self, tmp_path: Path) -> None:
        """S10/R6 + S8/R5: the canonical digest ``b484b581…`` is an identity
        lock that holds with or without attachment pins (the canonical excludes
        ``adjuntos``), and install never reports a conflict."""
        entry = load_seed_catalog(SEED_ROOT)[0]
        result = compile_methodology(entry.manifest, entry.source)
        assert result.ok, [issue.message for issue in result.issues]
        assert result.compiled is not None
        assert result.compiled.digest == (
            "b484b5810722bac198aff0a9174020a2fce32c79b7faddf7b086aea6b4faac82"
        )
        library = MethodologyLibrary(tmp_path / "library.json")
        report = install_seeds(library, SEED_ROOT)
        assert report.installed == 3 and report.conflict == 0

    def test_zero_attachment_corruption_error_text_is_unchanged(self, tmp_path: Path) -> None:
        """S10: a zero-attachment integrity failure keeps the exact pre-PR③
        error text — the extension adds no new code path for empty lists."""
        entry = _write_seed(tmp_path, "demo-skill")
        (entry / "source.md").write_text(
            "## Metodología de prueba\n\nContenido modificado.\n", encoding="utf-8",
        )
        with pytest.raises(SeedIntegrityError) as excinfo:
            load_seed_catalog(tmp_path)
        assert str(excinfo.value) == (
            "Seed entry 'demo-skill': integrity checksum mismatch — "
            "the bundled content was modified."
        )


class TestInstallSeeds:
    """PR3 install path — two-phase fail-closed, idempotent, insert-only."""

    def _real_entry_compiled(self) -> object:
        entry = load_seed_catalog(SEED_ROOT)[0]
        result = compile_methodology(entry.manifest, entry.source)
        assert result.ok
        return result.compiled

    def test_fresh_install_publishes_foundational_seed(self, tmp_path: Path) -> None:
        library = MethodologyLibrary(tmp_path / "library.json")
        report = install_seeds(library, SEED_ROOT)
        assert report.installed == 3
        published = library.get_published("narrative-character-creation", "1.3")
        assert published is not None
        assert published.clasificacion == "Oficiales"
        assert published.trust_attributes == ("fundacional",)
        assert published.digest == self._real_entry_compiled().digest

    def test_rerun_is_idempotent(self, tmp_path: Path) -> None:
        library = MethodologyLibrary(tmp_path / "library.json")
        first = install_seeds(library, SEED_ROOT)
        second = install_seeds(library, SEED_ROOT)
        assert first.installed == 3
        assert second.existing == 3 and second.installed == 0
        assert len(library.published_versions_for("narrative-character-creation")) == 1

    def test_compiler_invalid_seed_aborts_with_zero_records(self, tmp_path: Path) -> None:
        """S3: an authority-claiming source passes integrity (checksums match
        the bundled bytes) but fails compilation — the whole install aborts
        and ZERO records are inserted."""
        bad_root = tmp_path / "seeds"
        bad_root.mkdir()
        _write_seed(
            bad_root, "broken-skill",
            source="## Rota\n\n#!demiurgos-authority\nContenido que reclama autoridad.\n",
        )
        library = MethodologyLibrary(tmp_path / "library.json")
        with pytest.raises(SeedIntegrityError):
            install_seeds(library, bad_root)
        assert library.published_versions_for("broken-skill") == []
        assert not (tmp_path / "library.json").exists()

    def test_older_seed_than_stored_version_is_stale(self, tmp_path: Path) -> None:
        """Insert-only reconciliation: a seed shipping an older version than a
        stored version of the same skill is skipped, never downgraded."""
        library = MethodologyLibrary(tmp_path / "library.json")
        library.install_published_version(
            self._real_entry_compiled(),
            clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        older_root = tmp_path / "seeds-v09"
        older_root.mkdir()
        _write_seed(
            older_root, "narrative-character-creation",
            manifest=dict(_valid_manifest("narrative-character-creation"), version="0.9"),
        )
        report = install_seeds(library, older_root)
        assert report.stale == 1 and report.installed == 0
        assert [v["version"] for v in
                library.published_versions_for("narrative-character-creation")] == ["1.3"]

    def test_upgrade_inserts_v2_beside_active_v1_and_never_repoints(self, tmp_path: Path) -> None:
        """S5: seed v1 active in a world; boot with a v2 seed dir inserts v2
        immutably beside v1 — the activation still points to v1 and companion
        lists are untouched (TW15)."""
        library = MethodologyLibrary(tmp_path / "library.json")
        compiled_v1 = self._real_entry_compiled()
        library.install_published_version(
            compiled_v1, clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        library.activate("mundo-a", "narrative-character-creation", "1.3")
        library.add_companion("mundo-a", "narrative-character-creation", "1.3")

        v2_root = tmp_path / "seeds-v2"
        v2_root.mkdir()
        _write_seed(
            v2_root, "narrative-character-creation",
            manifest=dict(_valid_manifest("narrative-character-creation"), version="2.0"),
        )
        report = install_seeds(library, v2_root)
        assert report.installed == 1
        versions = library.published_versions_for("narrative-character-creation")
        assert [v["version"] for v in versions] == ["1.3", "2.0"]
        # Never re-point: activation and companion stay pinned to v1.
        assert library.active_for("mundo-a").version == "1.3"
        assert [c.version for c in library.list_companions("mundo-a")] == ["1.3"]

    def test_absent_seed_root_installs_nothing(self, tmp_path: Path) -> None:
        library = MethodologyLibrary(tmp_path / "library.json")
        report = install_seeds(library, tmp_path / "no-seeds")
        assert report.entries == 0 and report.installed == 0


class TestInstallUpsertR8:
    """R8 (④a): install upserts ``adjuntos`` pins onto the existing published
    record; identity stays immutable, zero-adjunto records stay byte-identical,
    and a digest-equal rerun never conflicts (D9)."""

    def _adjunto(self, path: str = "ejemplos/Axill.md", sha256: str | None = None) -> dict:
        return {"path": path, "sha256": sha256, "bytes": 1024, "nivel": "1º"}

    def _seed_roots(self, tmp_path: Path) -> tuple[Path, Path]:
        """Zero-adjunto and same-identity adjunto seed roots for one skill."""
        zero_root = tmp_path / "seeds-zero"
        _write_seed(zero_root, "demo-skill")
        adj_root = tmp_path / "seeds-adj"
        _write_seed(adj_root, "demo-skill", adjuntos=[self._adjunto()])
        return zero_root, adj_root

    def test_upsert_on_install_keeps_identity_fields(self, tmp_path: Path) -> None:
        """Scenario "upsert on install": metadata upserted, identity unchanged."""
        zero_root, adj_root = self._seed_roots(tmp_path)
        library = MethodologyLibrary(tmp_path / "library.json")
        install_seeds(library, zero_root)
        before = library.get_published("demo-skill", "1.0")
        assert before is not None and before.adjuntos == ()

        report = install_seeds(library, adj_root)
        assert report.existing == 1 and report.installed == 0 and report.conflict == 0

        after = library.get_published("demo-skill", "1.0")
        assert after is not None
        assert len(after.adjuntos) == 1
        assert after.adjuntos[0].path == "ejemplos/Axill.md"
        assert after.adjuntos[0].nivel == "1º"
        # Identity fields are immutable — only the pins moved.
        assert after.digest == before.digest
        assert after.skill_id == before.skill_id == "demo-skill"
        assert after.version == before.version == "1.0"
        assert after.name == before.name
        assert after.description == before.description
        assert after.phases == before.phases
        assert after.language == before.language
        assert after.source == before.source
        assert after.published_at == before.published_at

    def test_upsert_backfills_record_lacking_adjuntos_key(self, tmp_path: Path) -> None:
        """Scenario "upsert on install" (pre-PR③ record): a record without an
        ``adjuntos`` key decodes empty and gets the pins backfilled."""
        zero_root, adj_root = self._seed_roots(tmp_path)
        path = tmp_path / "library.json"
        library = MethodologyLibrary(path)
        install_seeds(library, zero_root)
        payload = json.loads(path.read_text(encoding="utf-8"))
        record = next(iter(payload["published"].values()))
        record.pop("adjuntos", None)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        library = MethodologyLibrary(path)
        report = install_seeds(library, adj_root)
        assert report.existing == 1 and report.conflict == 0
        published = library.get_published("demo-skill", "1.0")
        assert published is not None and len(published.adjuntos) == 1
        assert published.adjuntos[0].path == "ejemplos/Axill.md"

    def test_zero_adjunto_rerun_is_raw_json_byte_identical(self, tmp_path: Path) -> None:
        """D9: zero-adjunto records are never rewritten — raw JSON byte-identical."""
        path = tmp_path / "library.json"
        library = MethodologyLibrary(path)
        install_seeds(library, SEED_ROOT)
        first_bytes = path.read_bytes()
        assert b'"adjuntos"' in first_bytes  # PR③ record shape (empty list)
        rerun = MethodologyLibrary(path)
        report = install_seeds(rerun, SEED_ROOT)
        assert report.existing == 3 and report.conflict == 0
        assert path.read_bytes() == first_bytes

    def test_digest_lock_b484b581_unmoved_after_upsert(self, tmp_path: Path) -> None:
        """Scenario "digest lock": wiring adjuntos onto the real seed keeps the
        canonical digest ``b484b581…`` and never reports a conflict."""
        library = MethodologyLibrary(tmp_path / "library.json")
        install_seeds(library, SEED_ROOT)
        entry = load_seed_catalog(SEED_ROOT)[0]
        manifest = dict(entry.manifest)
        adj_root = tmp_path / "seeds-adj-real"
        adj_root.mkdir()
        _write_seed(
            adj_root, "narrative-character-creation",
            manifest=manifest, source=entry.source,
            adjuntos=[self._adjunto()],
        )
        report = install_seeds(library, adj_root)
        assert report.existing == 1 and report.conflict == 0 and report.installed == 0
        published = library.get_published("narrative-character-creation", "1.3")
        assert published is not None
        assert published.digest == (
            "b484b5810722bac198aff0a9174020a2fce32c79b7faddf7b086aea6b4faac82"
        )
        assert len(published.adjuntos) == 1
        assert published.adjuntos[0].nivel == "1º"


class TestSeedCarriersB2:
    """R6 MODIFIED (④b): the wired seed ships three pinned carriers; the
    existing ``_verify_entry`` path verifies them with ZERO seed-code change,
    tampering fails the whole catalog, and the canonical digest stays locked."""

    def test_carriers_green_three_pins_verified_by_existing_path(self) -> None:
        """Scenario "carriers green": the wired seed loads with 3 carriers +
        manifest entries + regenerated checksums; zero seed-code change."""
        catalog = load_seed_catalog(SEED_ROOT)
        assert len(catalog) == 3
        entry = catalog[0]
        adjuntos = entry.manifest.get("adjuntos") or []
        assert len(adjuntos) == 3
        assert {a["path"] for a in adjuntos} == {
            "adjunto-nivel-1-principal.md",
            "adjunto-nivel-2-secundario.md",
            "adjunto-nivel-3-relleno.md",
        }
        assert {a["nivel"] for a in adjuntos} == {"1º", "2º", "3º"}
        result = compile_methodology(entry.manifest, entry.source)
        assert result.ok, [issue.message for issue in result.issues]
        assert result.compiled is not None
        assert len(result.compiled.adjuntos) == 3
        assert result.compiled.adjuntos[0].path == "adjunto-nivel-1-principal.md"

    def test_disk_vs_checksums_parity_for_wired_seed(self) -> None:
        """Parity lock: every checksums.json entry matches the on-disk bytes."""
        seed_dir = SEED_ROOT / "narrative-character-creation"
        checksums = json.loads((seed_dir / "checksums.json").read_text(encoding="utf-8"))
        assert set(checksums) == {
            "manifest.yaml", "source.md",
            "adjunto-nivel-1-principal.md",
            "adjunto-nivel-2-secundario.md",
            "adjunto-nivel-3-relleno.md",
        }
        for name, digest in checksums.items():
            assert hashlib.sha256((seed_dir / name).read_bytes()).hexdigest() == digest

    def test_tampered_real_carrier_fails_whole_catalog(self, tmp_path: Path) -> None:
        """Scenario "tampered carrier": a modified carrier in the wired seed
        raises SeedIntegrityError; no partial catalog is returned."""
        seed_root = tmp_path / "seeds"
        shutil.copytree(SEED_ROOT, seed_root)
        (seed_root / "narrative-character-creation" / "adjunto-nivel-1-principal.md").write_bytes(
            b"tampered bytes"
        )
        with pytest.raises(SeedIntegrityError):
            load_seed_catalog(seed_root)

    def test_absent_real_carrier_fails_whole_catalog(self, tmp_path: Path) -> None:
        """Scenario "tampered carrier": an absent carrier fails the same way."""
        seed_root = tmp_path / "seeds"
        shutil.copytree(SEED_ROOT, seed_root)
        (seed_root / "narrative-character-creation" / "adjunto-nivel-2-secundario.md").unlink()
        with pytest.raises(SeedIntegrityError):
            load_seed_catalog(seed_root)

    def test_digest_lock_with_three_pins_installed(self, tmp_path: Path) -> None:
        """Scenario "digest lock": installing the wired seed keeps the
        canonical digest ``b484b581…`` and publishes all 3 pins."""
        library = MethodologyLibrary(tmp_path / "library.json")
        report = install_seeds(library, SEED_ROOT)
        assert report.installed == 3 and report.conflict == 0
        published = library.get_published("narrative-character-creation", "1.3")
        assert published is not None
        assert published.digest == (
            "b484b5810722bac198aff0a9174020a2fce32c79b7faddf7b086aea6b4faac82"
        )
        assert len(published.adjuntos) == 3
        assert {entry.nivel for entry in published.adjuntos} == {"1º", "2º", "3º"}
        assert {entry.path for entry in published.adjuntos} == {
            "adjunto-nivel-1-principal.md",
            "adjunto-nivel-2-secundario.md",
            "adjunto-nivel-3-relleno.md",
        }

    def test_install_upsert_moves_at12_pins_to_rewritten_carriers(self, tmp_path: Path) -> None:
        """R-CARRIER-2 pin-move coherence: an existing ``@1.3`` record still
        carrying pre-⑥ pins is upserted to the rewritten carriers on re-install
        (desired ≠ existing), keeping the canonical digest and never conflicting;
        the moved pins match the new on-disk bytes."""
        seed_dir = SEED_ROOT / "narrative-character-creation"
        library = MethodologyLibrary(tmp_path / "library.json")
        install_seeds(library, SEED_ROOT)
        path = tmp_path / "library.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        record = next(iter(payload["published"].values()))
        record["adjuntos"] = [
            {"path": e["path"], "sha256": "0" * 64, "bytes": 1, "nivel": e["nivel"]}
            for e in record["adjuntos"]
        ]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        library = MethodologyLibrary(path)
        report = install_seeds(library, SEED_ROOT)
        assert report.existing == 3 and report.conflict == 0 and report.installed == 0
        published = library.get_published("narrative-character-creation", "1.3")
        assert published is not None
        assert published.digest == (
            "b484b5810722bac198aff0a9174020a2fce32c79b7faddf7b086aea6b4faac82"
        )
        for entry in published.adjuntos:
            disk = (seed_dir / entry.path).read_bytes()
            assert entry.sha256 == hashlib.sha256(disk).hexdigest()
            assert entry.bytes == len(disk)


class TestDensityOnlyTaxonomy:
    """Density-only 1º taxonomy: the single 1º pin names the four narrative
    ROLE functions (never a moral label in its header), every character it
    shows stays morally AMBIGUOUS, and the legacy 1.0 principal carrier stays
    on disk byte-identical yet unlisted in the 1.2 seed."""

    _ROLE_TERMS = frozenset({
        "protagonista", "coprotagonista", "antagonista", "villano",
    })
    _ALIGNMENT_VALUE_TERMS = frozenset({
        "benigno", "virtuoso", "maligno", "vil", "moral", "mezquino",
        "legal", "social", "neutral", "rebelde", "caótico",
    })
    # The unambiguous moral poles: no listed exemplar may reveal one.
    _UNAMBIGUOUS_POLES = frozenset({"benigno", "virtuoso", "maligno", "vil"})
    _ALIGNMENT_FIELDS = ("**Alineamiento inicial:**", "**Alineamiento revelado:**")

    @staticmethod
    def _word_tokens(text: str) -> set[str]:
        """Word tokens only — ``vil`` is a substring of ``villano`` and ``moral``
        of ``moralidad``, so substring matching would false-positive."""
        return set(re.findall(r"\b\w+\b", text.lower()))

    @staticmethod
    def _alignment_value(text: str, field: str) -> str | None:
        """Extract the value declared after ``field`` on its own line."""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"- {field}"):
                return stripped.split(field, 1)[1].split("—", 1)[0].strip()
        return None

    def test_nivel_1_pin_names_roles_without_moral_label(self) -> None:
        """Scenario "role coverage without morality in the header": the 1º
        exemplar names all four principal roles — including ``villano`` — as
        ROLE vocabulary, and no alignment value appears in its header."""
        seed_dir = SEED_ROOT / "narrative-character-creation"
        entry = load_seed_catalog(SEED_ROOT)[0]
        pins_1 = [a for a in entry.manifest["adjuntos"] if a["nivel"] == "1º"]
        assert len(pins_1) == 1
        labels = {
            pin["path"].removeprefix("adjunto-nivel-1-").removesuffix(".md")
            for pin in pins_1
        }
        assert labels == {"principal"}
        for pin in pins_1:
            header_block = "\n".join(
                (seed_dir / pin["path"]).read_text(encoding="utf-8").splitlines()[2:10]
            ).lower()
            assert header_block.startswith("> **referencia de formato de salida")
            tokens = self._word_tokens(header_block)
            # Positive: the role-coverage note names every principal role.
            assert self._ROLE_TERMS <= tokens
            # Negative: role vocabulary only — never an alignment value.
            assert not (self._ALIGNMENT_VALUE_TERMS & tokens)

    def test_listed_exemplars_keep_every_character_morally_ambiguous(self) -> None:
        """Scenario "ambiguous morality throughout": every ``Alineamiento
        inicial`` / ``Alineamiento revelado`` value in a listed exemplar avoids
        the unambiguous poles ``{Benigno, Virtuoso, Maligno, Vil}``."""
        seed_dir = SEED_ROOT / "narrative-character-creation"
        entry = load_seed_catalog(SEED_ROOT)[0]
        checked = 0
        for pin in entry.manifest["adjuntos"]:
            text = (seed_dir / pin["path"]).read_text(encoding="utf-8")
            for field in self._ALIGNMENT_FIELDS:
                value = self._alignment_value(text, field)
                if value is None:
                    continue
                checked += 1
                assert not (self._UNAMBIGUOUS_POLES & self._word_tokens(value)), (
                    f"{pin['path']}: {field} reveals an unambiguous moral pole "
                    f"({value!r})"
                )
        # The 1º exemplar must demonstrate BOTH emergent-trajectory values.
        assert checked >= 2

    def test_legacy_1_0_principal_carrier_renamed_byte_identical_and_unlisted(self) -> None:
        """Scenario "1.0 pin retired": the read-only legacy 1º carrier of v1.0
        was renamed to ``adjunto-nivel-1-principal-v1.0.md``, keeps its exact
        bytes, and is NOT declared by the 1.2 manifest or checksums; the v1.0
        pin path ``adjunto-nivel-1-principal.md`` now resolves to the v1.2
        carrier and fails the sha-pin (accepted, documented degradation)."""
        seed_dir = SEED_ROOT / "narrative-character-creation"
        legacy = seed_dir / "adjunto-nivel-1-principal-v1.0.md"
        data = legacy.read_bytes()
        assert len(data) == 9852
        assert hashlib.sha256(data).hexdigest() == (
            "0963ccd4d4fffc76c46f05054de6f922766466c06b0e4fcb4435dd56b7b59f48"
        )
        entry = load_seed_catalog(SEED_ROOT)[0]
        assert "adjunto-nivel-1-principal-v1.0.md" not in {
            a["path"] for a in entry.manifest["adjuntos"]
        }
        checksums = json.loads(
            (seed_dir / "checksums.json").read_text(encoding="utf-8")
        )
        assert "adjunto-nivel-1-principal-v1.0.md" not in checksums


class TestSistemaSeedPublishesClean:
    """WU-1 (sistema-foundational-skill): the published ``Sistema`` seed joins
    the catalog and installs beside the character seed with zero conflicts —
    both ``Oficiales`` ``fundacional`` records."""

    def test_catalog_lists_both_foundational_seeds(self) -> None:
        catalog = load_seed_catalog(SEED_ROOT)
        assert len(catalog) == 3
        assert [entry.skill_id for entry in catalog] == [
            "narrative-character-creation",
            "narrative-chronology-creation",
            "narrative-system-creation",
        ]

    def test_sistema_seed_declares_the_guided_flow(self, tmp_path: Path) -> None:
        library = MethodologyLibrary(tmp_path / "library.json")
        install_seeds(library, SEED_ROOT)
        published = library.get_published("narrative-system-creation", "1.2")
        assert published is not None
        assert published.guided_flow is not None
        assert published.guided_flow.flow_id == "guided-system"
        assert published.guided_flow.entity_type == "sistema"
        assert library.is_method_for_flow(
            "guided-system", "narrative-system-creation",
        )
        assert not library.is_method_for_flow(
            "guided-character", "narrative-system-creation",
        )

    def test_both_seeds_install_clean_as_foundational(self, tmp_path: Path) -> None:
        library = MethodologyLibrary(tmp_path / "library.json")
        report = install_seeds(library, SEED_ROOT)
        assert report.entries == 3
        assert report.installed == 3 and report.conflict == 0
        for skill_id, version in (
            ("narrative-character-creation", "1.3"),
            ("narrative-chronology-creation", "1.2"),
            ("narrative-system-creation", "1.2"),
        ):
            published = library.get_published(skill_id, version)
            assert published is not None
            assert published.clasificacion == "Oficiales"
            assert published.trust_attributes == ("fundacional",)

class TestChronologySeedDeclaresTheFlow:
    """The Cronología seed joins the catalog and declares its guided flow.

    The kernel owns the destination (``lore/``), the ``Cronologia`` type label,
    the identity + ``evento`` minimums and the envelope field; the seed only
    names the shape and its chat vocabulary.
    """

    def test_chronology_seed_declares_the_guided_flow(self, tmp_path: Path) -> None:
        library = MethodologyLibrary(tmp_path / "library.json")
        install_seeds(library, SEED_ROOT)

        published = library.get_published("narrative-chronology-creation", "1.2")
        assert published is not None
        assert published.clasificacion == "Oficiales"
        assert published.trust_attributes == ("fundacional",)
        assert published.guided_flow is not None
        assert published.guided_flow.flow_id == "guided-chronology"
        assert published.guided_flow.entity_type == "cronologia"
        assert published.guided_flow.ui_copy_key == "chronology"
        assert library.is_method_for_flow(
            "guided-chronology", "narrative-chronology-creation",
        )
        assert not library.is_method_for_flow(
            "guided-character", "narrative-chronology-creation",
        )
        assert not library.is_method_for_flow(
            "guided-system", "narrative-chronology-creation",
        )

    def test_chronology_seed_compiles_clean(self) -> None:
        entry = next(
            item for item in load_seed_catalog(SEED_ROOT)
            if item.skill_id == "narrative-chronology-creation"
        )
        assert entry.version == "1.2"
        result = compile_methodology(entry.manifest, entry.source)
        assert result.ok, [issue.message for issue in result.issues]
        assert result.compiled is not None
        assert result.compiled.guided_flow is not None
        assert result.compiled.guided_flow.entity_type == "cronologia"


class TestFoundationalTriggers:
    """The index trigger is authored separately from the method description."""

    def test_every_seed_ships_a_bounded_trigger(self) -> None:
        from skill_renderer import _bound_description

        for entry in load_seed_catalog(SEED_ROOT):
            trigger = entry.manifest.get("trigger")
            assert trigger, entry.skill_id
            assert len(trigger) <= 57, entry.skill_id
            rendered, issues = _bound_description(trigger)
            assert not issues, entry.skill_id
            assert rendered == trigger

    def test_every_seed_keeps_the_method_description(self) -> None:
        for entry in load_seed_catalog(SEED_ROOT):
            description = entry.manifest.get("description") or ""
            trigger = entry.manifest.get("trigger") or ""
            # The method summary stays a separate surface: it is what the
            # transversal contract projects into chat, never the index label.
            assert description.strip(), entry.skill_id
            assert description != trigger, entry.skill_id
            assert entry.manifest["version"]

    def test_trigger_is_not_the_carrier_of_the_method_rails(self) -> None:
        entry = next(
            item for item in load_seed_catalog(SEED_ROOT)
            if item.skill_id == "narrative-system-creation"
        )
        assert entry.manifest["trigger"] == (
            "Co-crea sistemas: origen, qué exige y límite."
        )
        description = entry.manifest["description"]
        assert "(1)" in description and "(9)" in description
        assert "material/construido" in description
