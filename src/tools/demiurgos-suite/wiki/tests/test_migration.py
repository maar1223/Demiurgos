"""
tests/test_migration.py — ONB-4.3 RED/unit tests for wiki.migration.

Covers the transactional legacy-layout migration engine contract
(design: "migration records plan, source/destination hashes, transaction id
and rollback evidence, then atomically moves only approved folders; failure
restores originals"):

- plan: source hashes + transaction id before any mutation
- approval scope: ONLY the explicitly approved folders move; unapproved
  folders (legacy or not) are never touched
- atomic move + hash evidence: destination hash equals source hash, content
  preserved, evidence persisted with the transaction id
- failure restore: a mid-transaction failure rolls every already-moved folder
  back to its original location and re-verifies the source hash; the rollback
  evidence is persisted

The engine is pure and filesystem-scoped: it never writes outside the given
``mundos_dir`` and ``evidence_dir``. Approval is explicit at call time; the
engine NEVER renames automatically (approval arrives as the folder list).

Uses unittest so ``python -m unittest discover`` keeps working.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SRC_DIR = Path(__file__).resolve().parent.parent.parent  # demiurgos-suite/
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from wiki.migration import (  # noqa: E402
    MigrationError,
    MigrationErrorKind,
    MigrationEvidence,
    MigrationOutcome,
    MigrationPlan,
    MigrationStep,
    build_migration_plan,
    execute_migration,
)


def _tree_sha256(root: Path) -> str:
    """Independent content hash used ONLY by tests to cross-check evidence.

    Mirrors the canonical tree-hash contract the engine documents (so the
    cross-check is meaningful): every entry is recorded as
    ``rel + "\\0" + kind + "\\0" + payload + "\\n"`` with directories using a
    trailing ``/`` and a lexicographic global sort; payload is file bytes, the
    symlink target, or empty for directories.
    """
    h = hashlib.sha256()
    entries: list[tuple[str, str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in dirnames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix() + "/"
            entries.append((rel, "dir", path))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            entries.append((rel, "file", path))
    for rel, kind, path in sorted(entries, key=lambda entry: entry[0]):
        h.update(rel.encode("utf-8", "surrogateescape"))
        h.update(b"\0")
        h.update(kind.encode("ascii"))
        h.update(b"\0")
        if path.is_symlink():
            h.update(os.readlink(path).encode("utf-8", "surrogateescape"))
        elif kind == "file":
            h.update(path.read_bytes())
        h.update(b"\n")
    return h.hexdigest()


class _MigrationTestCase(unittest.TestCase):
    def _mundos(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "mundos"

    def _evidence_dir(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "evidence"

    def _legacy_world(
        self,
        mundos: Path,
        name: str = "legacy-x",
        *,
        extra_dir: str | None = None,
    ) -> Path:
        """A legacy world: uppercase Lore + Personajes + lowercase sagas.

        Mirrors the runtime harness layout from the WU-4b forecast:
        ``mundos/legacy-x/{Lore,Personajes,sagas}``.
        """
        world = mundos / name
        (world / "Lore" / "reglas").mkdir(parents=True)
        (world / "Lore" / "reglas" / "magia.md").write_text(
            "# Magia\n\nReglas de magia.\n", encoding="utf-8"
        )
        (world / "Personajes").mkdir()
        (world / "Personajes" / "anisa.md").write_text(
            "---\ntype: Personaje\nname: Anisa\n---\n", encoding="utf-8"
        )
        (world / "sagas").mkdir()
        (world / "sagas" / "arco.md").write_text("# Arco\n", encoding="utf-8")
        if extra_dir:
            (world / extra_dir).mkdir()
            (world / extra_dir / "nota.md").write_text("nota\n", encoding="utf-8")
        return world


class TestMigrationPlan(_MigrationTestCase):
    """ONB-4.3 — plan records source hashes + transaction id, rejects unsafe
    or unapproved input without mutating anything."""

    def test_plan_records_source_hashes_and_transaction_id(self) -> None:
        mundos = self._mundos()
        world = self._legacy_world(mundos)
        plan = build_migration_plan(mundos, "legacy-x", ["Lore", "Personajes"])
        self.assertIsInstance(plan, MigrationPlan)
        self.assertTrue(plan.transaction_id.startswith("mig-"))
        self.assertEqual(plan.world, "legacy-x")
        self.assertEqual([step.folder for step in plan.steps], ["Lore", "Personajes"])
        for step in plan.steps:
            self.assertRegex(step.source_hash, r"^[0-9a-f]{64}$")
            self.assertEqual(step.source, world / step.folder)
            self.assertEqual(step.destination, world / step.folder.lower())
        # Plan-time hash equals an independent hash of the same tree.
        self.assertEqual(
            plan.steps[0].source_hash,
            _tree_sha256(world / "Lore"),
            "plan source hash must match the source tree content",
        )

    def test_plan_rejects_empty_approval_without_mutation(self) -> None:
        mundos = self._mundos()
        world = self._legacy_world(mundos)
        with self.assertRaises(MigrationError) as ctx:
            build_migration_plan(mundos, "legacy-x", [])
        self.assertEqual(ctx.exception.kind, MigrationErrorKind.EMPTY_APPROVAL)
        self.assertTrue((world / "Lore").is_dir(), "nothing may move without approval")

    def test_plan_rejects_unknown_or_missing_folder(self) -> None:
        mundos = self._mundos()
        world = self._legacy_world(mundos)
        with self.assertRaises(MigrationError) as ctx:
            build_migration_plan(mundos, "legacy-x", ["Lore", "NoExiste"])
        self.assertEqual(ctx.exception.kind, MigrationErrorKind.UNKNOWN_FOLDER)
        self.assertTrue((world / "Lore").is_dir())

    def test_plan_rejects_missing_world(self) -> None:
        mundos = self._mundos()
        with self.assertRaises(MigrationError) as ctx:
            build_migration_plan(mundos, "no-existe", ["Lore"])
        self.assertEqual(ctx.exception.kind, MigrationErrorKind.INVALID_WORLD)

    def test_plan_rejects_nonempty_destination_collision(self) -> None:
        mundos = self._mundos()
        world = self._legacy_world(mundos)
        (world / "lore").mkdir()
        (world / "lore" / "existente.md").write_text("x\n", encoding="utf-8")
        with self.assertRaises(MigrationError) as ctx:
            build_migration_plan(mundos, "legacy-x", ["Lore"])
        self.assertEqual(ctx.exception.kind, MigrationErrorKind.COLLISION)
        self.assertTrue((world / "Lore").is_dir(), "collision must not mutate")

    def test_plan_allows_empty_destination_dir(self) -> None:
        mundos = self._mundos()
        world = self._legacy_world(mundos)
        (world / "lore").mkdir()  # empty lowercase dir: safe to replace
        plan = build_migration_plan(mundos, "legacy-x", ["Lore"])
        self.assertIsInstance(plan, MigrationPlan)

    def test_plan_rejects_symlink_source_escape(self) -> None:
        mundos = self._mundos()
        mundos.mkdir(parents=True)
        world = mundos / "legacy-x"
        world.mkdir()
        outside = Path(mundos).parent / "outside"
        outside.mkdir()
        (outside / "datos.md").write_text("fuera\n", encoding="utf-8")
        (world / "Lore").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(MigrationError) as ctx:
            build_migration_plan(mundos, "legacy-x", ["Lore"])
        self.assertEqual(ctx.exception.kind, MigrationErrorKind.SYMLINK_ESCAPE)
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ["datos.md"],
                         "symlink target must never be touched")


class TestMigrationExecute(_MigrationTestCase):
    """ONB-4.3 — atomic move of approved folders only; hash evidence; failure
    restores originals and persists rollback evidence."""

    def test_completed_migration_moves_only_approved_folders(self) -> None:
        mundos = self._mundos()
        world = self._legacy_world(mundos, extra_dir="Notas")
        plan = build_migration_plan(mundos, "legacy-x", ["Lore"])
        evidence = execute_migration(plan, self._evidence_dir())
        self.assertEqual(evidence.outcome, MigrationOutcome.COMPLETED)
        # Approved folder moved to lowercase; content preserved.
        self.assertTrue((world / "lore").is_dir())
        self.assertFalse((world / "Lore").exists(), "approved folder must move")
        self.assertTrue((world / "lore" / "reglas" / "magia.md").exists())
        # Unapproved legacy folder + unapproved extra dir + sagas untouched.
        self.assertTrue((world / "Personajes").is_dir(), "unapproved legacy folder untouched")
        self.assertFalse((world / "personajes").exists())
        self.assertTrue((world / "Personajes" / "anisa.md").exists())
        self.assertTrue((world / "Notas").is_dir())
        self.assertTrue((world / "sagas").is_dir())
        self.assertEqual([step.folder for step in evidence.steps], ["Lore"])

    def test_completed_migration_preserves_content_and_hash_evidence(self) -> None:
        mundos = self._mundos()
        world = self._legacy_world(mundos)
        plan = build_migration_plan(mundos, "legacy-x", ["Lore", "Personajes"])
        evidence = execute_migration(plan, self._evidence_dir())
        self.assertEqual(evidence.outcome, MigrationOutcome.COMPLETED)
        self.assertEqual(
            (world / "lore" / "reglas" / "magia.md").read_text(encoding="utf-8"),
            "# Magia\n\nReglas de magia.\n",
        )
        self.assertEqual(
            (world / "personajes" / "anisa.md").read_text(encoding="utf-8"),
            "---\ntype: Personaje\nname: Anisa\n---\n",
        )
        for step in evidence.steps:
            self.assertIsNotNone(step.destination_hash)
            self.assertRegex(step.destination_hash, r"^[0-9a-f]{64}$")
            self.assertEqual(
                step.destination_hash,
                step.source_hash,
                "destination hash must equal the source hash (content intact)",
            )
            self.assertEqual(
                step.destination_hash,
                _tree_sha256(step.destination),
                "evidence destination hash must match the moved tree",
            )

    def test_evidence_file_persisted_with_transaction_id(self) -> None:
        mundos = self._mundos()
        world = self._legacy_world(mundos)
        plan = build_migration_plan(mundos, "legacy-x", ["Lore", "Personajes"])
        evidence_dir = self._evidence_dir()
        evidence = execute_migration(plan, evidence_dir)
        target = evidence_dir / f"{evidence.transaction_id}.json"
        self.assertTrue(target.is_file(), "rollback/completion evidence must persist")
        record = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(record["transaction_id"], evidence.transaction_id)
        self.assertEqual(record["world"], "legacy-x")
        self.assertEqual(record["outcome"], "completed")
        self.assertEqual(len(record["steps"]), 2)
        self.assertEqual(record["steps"][0]["folder"], "Lore")
        self.assertEqual(record["steps"][0]["destination_hash"], record["steps"][0]["source_hash"])
        # The plan's transaction id is the same one recorded in evidence.
        self.assertEqual(record["transaction_id"], plan.transaction_id)

    def test_failure_restores_originals_and_records_rollback_evidence(self) -> None:
        mundos = self._mundos()
        world = self._legacy_world(mundos)
        plan = build_migration_plan(mundos, "legacy-x", ["Lore", "Personajes"])
        real_move = __import__("wiki.migration", fromlist=["_atomic_move"])._atomic_move

        def flaky(src: Path, dst: Path) -> None:
            if Path(dst).name == "personajes":
                raise OSError("simulated mid-transaction failure")
            real_move(src, dst)

        with mock.patch("wiki.migration._atomic_move", side_effect=flaky):
            evidence = execute_migration(plan, self._evidence_dir())
        self.assertEqual(evidence.outcome, MigrationOutcome.ROLLED_BACK)
        self.assertTrue(evidence.restore_verified, "rollback must re-verify source hashes")
        self.assertIn("simulated mid-transaction failure", evidence.error)
        # Both original uppercase folders restored; no lowercase leftovers.
        self.assertTrue((world / "Lore").is_dir())
        self.assertTrue((world / "Personajes").is_dir())
        self.assertFalse((world / "lore").exists())
        self.assertFalse((world / "personajes").exists())
        # Content restored byte-identical (hash-verified by the engine).
        self.assertEqual(
            (world / "Lore" / "reglas" / "magia.md").read_text(encoding="utf-8"),
            "# Magia\n\nReglas de magia.\n",
        )
        self.assertEqual(
            (world / "Personajes" / "anisa.md").read_text(encoding="utf-8"),
            "---\ntype: Personaje\nname: Anisa\n---\n",
        )
        for step in evidence.steps:
            self.assertTrue(step.restored)

    def test_unapproved_folders_untouched_when_others_move(self) -> None:
        mundos = self._mundos()
        world = self._legacy_world(mundos, extra_dir="Notas")
        plan = build_migration_plan(mundos, "legacy-x", ["Lore", "Personajes"])
        execute_migration(plan, self._evidence_dir())
        # Only the two approved legacy folders moved; everything else intact.
        self.assertTrue((world / "lore").is_dir())
        self.assertTrue((world / "personajes").is_dir())
        self.assertTrue((world / "sagas").is_dir())
        self.assertTrue((world / "sagas" / "arco.md").exists())
        self.assertTrue((world / "Notas").is_dir())
        self.assertTrue((world / "Notas" / "nota.md").exists())

    def test_execute_rejects_collision_before_any_move(self) -> None:
        mundos = self._mundos()
        world = self._legacy_world(mundos)
        plan = build_migration_plan(mundos, "legacy-x", ["Lore"])
        # Destination becomes occupied AFTER the plan was built (TOCTOU guard).
        (world / "lore").mkdir()
        (world / "lore" / "ajeno.md").write_text("ajeno\n", encoding="utf-8")
        with self.assertRaises(MigrationError) as ctx:
            execute_migration(plan, self._evidence_dir())
        self.assertEqual(ctx.exception.kind, MigrationErrorKind.COLLISION)
        self.assertEqual(ctx.exception.transaction_id, plan.transaction_id)
        self.assertTrue((world / "Lore").is_dir(), "nothing may move on collision")
        self.assertTrue((world / "lore" / "ajeno.md").exists())


if __name__ == "__main__":
    unittest.main()
