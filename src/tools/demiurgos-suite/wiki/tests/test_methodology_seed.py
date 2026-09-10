"""RED/unit tests for the methodology seed catalog loader.

Covers S1 (the real repo seed root loads exactly the MVP entry
``narrative-character-creation@1.0``, the seed is compiler-clean with zero
authority-claim issues, and the git state keeps the seeds tracked while the
runtime store stays ignored) and S3-load fail-closed behavior (corrupt
checksum, malformed manifest, and compiler-rejected manifest never produce a
partial catalog).
"""

from __future__ import annotations

import hashlib
import json
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
) -> Path:
    """Write a valid seed entry mirroring the trust-boundary canonical bytes.

    ``manifest.yaml`` is serialized with the same YAML dump the package
    builder uses and ``checksums.json`` holds the SHA-256 of the exact bundled
    bytes, so the fixture matches real seed semantics.
    """
    entry_dir = root / skill_id
    entry_dir.mkdir(parents=True, exist_ok=True)
    manifest_bytes = yaml.safe_dump(
        dict(manifest or _valid_manifest(skill_id)),
        sort_keys=False, allow_unicode=True,
    ).encode("utf-8")
    source_bytes = source.encode("utf-8")
    (entry_dir / "manifest.yaml").write_bytes(manifest_bytes)
    (entry_dir / "source.md").write_bytes(source_bytes)
    checksums = {
        "manifest.yaml": hashlib.sha256(manifest_bytes).hexdigest(),
        "source.md": hashlib.sha256(source_bytes).hexdigest(),
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
        assert len(catalog) == 1
        entry = catalog[0]
        assert entry.skill_id == "narrative-character-creation"
        assert entry.version == "1.0"
        assert entry.manifest["skill_id"] == "narrative-character-creation"
        assert entry.manifest["version"] == "1.0"

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
        assert report.installed == 1
        published = library.get_published("narrative-character-creation", "1.0")
        assert published is not None
        assert published.clasificacion == "Oficiales"
        assert published.trust_attributes == ("fundacional",)
        assert published.digest == self._real_entry_compiled().digest

    def test_rerun_is_idempotent(self, tmp_path: Path) -> None:
        library = MethodologyLibrary(tmp_path / "library.json")
        first = install_seeds(library, SEED_ROOT)
        second = install_seeds(library, SEED_ROOT)
        assert first.installed == 1
        assert second.existing == 1 and second.installed == 0
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
                library.published_versions_for("narrative-character-creation")] == ["1.0"]

    def test_upgrade_inserts_v2_beside_active_v1_and_never_repoints(self, tmp_path: Path) -> None:
        """S5: seed v1 active in a world; boot with a v2 seed dir inserts v2
        immutably beside v1 — the activation still points to v1 and companion
        lists are untouched (TW15)."""
        library = MethodologyLibrary(tmp_path / "library.json")
        compiled_v1 = self._real_entry_compiled()
        library.install_published_version(
            compiled_v1, clasificacion="Oficiales", trust_attributes=("fundacional",),
        )
        library.activate("mundo-a", "narrative-character-creation", "1.0")
        library.add_companion("mundo-a", "narrative-character-creation", "1.0")

        v2_root = tmp_path / "seeds-v2"
        v2_root.mkdir()
        _write_seed(
            v2_root, "narrative-character-creation",
            manifest=dict(_valid_manifest("narrative-character-creation"), version="2.0"),
        )
        report = install_seeds(library, v2_root)
        assert report.installed == 1
        versions = library.published_versions_for("narrative-character-creation")
        assert [v["version"] for v in versions] == ["1.0", "2.0"]
        # Never re-point: activation and companion stay pinned to v1.
        assert library.active_for("mundo-a").version == "1.0"
        assert [c.version for c in library.list_companions("mundo-a")] == ["1.0"]

    def test_absent_seed_root_installs_nothing(self, tmp_path: Path) -> None:
        library = MethodologyLibrary(tmp_path / "library.json")
        report = install_seeds(library, tmp_path / "no-seeds")
        assert report.entries == 0 and report.installed == 0