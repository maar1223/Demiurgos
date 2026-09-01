# -*- coding: utf-8 -*-
"""World recycle bin module tests — move/restore/list/purge and meta.json.

Covers W-1 of the world-delete-trash change: ``world_recycle_bin`` functions
with a ``tmp_path`` trash/mundos pair, plus ``GuidedSessionStore`` cleanup.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import world_recycle_bin as wrb  # noqa: E402
from world_authority import rename_world  # noqa: E402
from guided_character_protocol import GuidedSessionStore  # noqa: E402


@pytest.fixture()
def env(tmp_path: Path):
    """tmp mundos/ + world-trash/ with a populated world "Avalor"."""
    mundos = tmp_path / "mundos"
    trash = tmp_path / "world-trash"
    avalor = mundos / "Avalor"
    (avalor / "lore").mkdir(parents=True)
    (avalor / "lore" / "a.md").write_text("# A\n", encoding="utf-8")
    (avalor / "lore" / "b.md").write_text("# B\n", encoding="utf-8")
    (avalor / "personajes").mkdir()
    (avalor / "personajes" / "p.md").write_text("# P\n", encoding="utf-8")
    return {"mundos": mundos, "trash": trash}


def _meta(entry_dir: Path) -> dict:
    return json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))


def _write_old_entry(trash: Path, world: str, deleted_at: datetime) -> Path:
    """Seed a trash entry with a crafted (possibly expired) deleted_at."""
    stamp = deleted_at.isoformat(timespec="microseconds").replace(":", "-").replace("+00:00", "Z")
    entry = trash / world / stamp
    (entry / "lore").mkdir(parents=True)
    (entry / "lore" / "old.md").write_text("# Old\n", encoding="utf-8")
    (entry / "meta.json").write_text(
        json.dumps(
            {
                "world_name": world,
                "deleted_at": deleted_at.astimezone(timezone.utc)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z"),
                "size_bytes": 12,
                "lore_count": 1,
                "character_count": 0,
                "note": "associated data hidden; cleaned on purge",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return entry


class TestMoveToTrash:
    def test_creates_entry_dir_and_meta(self, env):
        entry = wrb.move_to_trash("Avalor", trash_root=env["trash"], mundos_dir=env["mundos"])
        assert entry.world_name == "Avalor"
        assert entry.lore_count == 2
        assert entry.character_count == 1
        assert entry.size_bytes > 0
        assert entry.days_remaining == wrb.RETENTION_DAYS
        assert not (env["mundos"] / "Avalor").exists()

        world_root = env["trash"] / "Avalor"
        entries = [p for p in world_root.iterdir() if p.is_dir()]
        assert len(entries) == 1
        meta = _meta(entries[0])
        assert meta["world_name"] == "Avalor"
        assert meta["lore_count"] == 2
        assert meta["character_count"] == 1
        assert meta["size_bytes"] == entry.size_bytes
        assert meta["deleted_at"].endswith("Z")
        assert (entries[0] / "lore" / "a.md").is_file()

    def test_missing_world_raises(self, env):
        with pytest.raises(ValueError):
            wrb.move_to_trash("Fantasia", trash_root=env["trash"], mundos_dir=env["mundos"])

    def test_invalid_name_raises(self, env):
        for bad in ("", "..", "a/b"):
            with pytest.raises(ValueError):
                wrb.move_to_trash(bad, trash_root=env["trash"], mundos_dir=env["mundos"])

    def test_meta_is_iso_utc_and_note_present(self, env):
        entry = wrb.move_to_trash("Avalor", trash_root=env["trash"], mundos_dir=env["mundos"])
        meta = _meta(env["trash"] / "Avalor" / next(
            p.name for p in (env["trash"] / "Avalor").iterdir() if p.is_dir()
        ))
        parsed = datetime.fromisoformat(meta["deleted_at"].replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert meta["note"] == "associated data hidden; cleaned on purge"
        assert entry.deleted_at.tzinfo is not None


class TestRestoreFromTrash:
    def test_round_trip(self, env):
        wrb.move_to_trash("Avalor", trash_root=env["trash"], mundos_dir=env["mundos"])
        wrb.restore_from_trash("Avalor", trash_root=env["trash"], mundos_dir=env["mundos"])
        assert (env["mundos"] / "Avalor" / "lore" / "a.md").is_file()
        assert not (env["trash"] / "Avalor").exists()

    def test_not_in_trash_raises(self, env):
        with pytest.raises(FileNotFoundError):
            wrb.restore_from_trash("Fantasia", trash_root=env["trash"], mundos_dir=env["mundos"])

    def test_name_conflict_auto_renames(self, env):
        wrb.move_to_trash("Avalor", trash_root=env["trash"], mundos_dir=env["mundos"])
        # An active world (recreated) owns the name -> restore auto-names.
        (env["mundos"] / "Avalor").mkdir()
        restored = wrb.restore_from_trash("Avalor", trash_root=env["trash"], mundos_dir=env["mundos"])
        assert restored == "Avalor (restaurado)"
        assert (env["mundos"] / "Avalor (restaurado)" / "lore" / "a.md").is_file()
        assert not (env["trash"] / "Avalor").exists()

    def test_restores_most_recent_entry(self, env):
        old = _write_old_entry(
            env["trash"], "Kaelia",
            datetime.now(timezone.utc) - timedelta(days=5),
        )
        newest = env["trash"] / "Kaelia" / "z-newest"
        newest.mkdir(parents=True)
        (newest / "lore").mkdir()
        wrb.restore_from_trash("Kaelia", trash_root=env["trash"], mundos_dir=env["mundos"])
        assert (env["mundos"] / "Kaelia" / "lore").is_dir()
        assert old.exists()  # the older entry remains in trash

    def test_restore_as_explicit_new_name(self, env):
        wrb.move_to_trash("Avalor", trash_root=env["trash"], mundos_dir=env["mundos"])
        (env["mundos"] / "Avalor").mkdir()
        restored = wrb.restore_from_trash(
            "Avalor", new_name="Avalor2",
            trash_root=env["trash"], mundos_dir=env["mundos"])
        assert restored == "Avalor2"
        assert (env["mundos"] / "Avalor2" / "lore" / "a.md").is_file()

    def test_explicit_new_name_conflict_raises(self, env):
        wrb.move_to_trash("Avalor", trash_root=env["trash"], mundos_dir=env["mundos"])
        (env["mundos"] / "Avalor").mkdir()
        (env["mundos"] / "Avalor2").mkdir()
        with pytest.raises(ValueError):
            wrb.restore_from_trash(
                "Avalor", new_name="Avalor2",
                trash_root=env["trash"], mundos_dir=env["mundos"])


class TestRenameWorld:
    def test_renames_and_preserves_content(self, env):
        result = rename_world(env["mundos"], "Avalor", "Avalor2")
        assert result.kind.value == "created"
        assert not (env["mundos"] / "Avalor").exists()
        assert (env["mundos"] / "Avalor2" / "lore" / "a.md").is_file()
        assert (env["mundos"] / "Avalor2" / "personajes" / "p.md").is_file()

    def test_collision_rejected(self, env):
        (env["mundos"] / "Avalor2").mkdir()
        result = rename_world(env["mundos"], "Avalor", "Avalor2")
        assert result.kind.value == "collision"

    def test_missing_source_rejected(self, env):
        result = rename_world(env["mundos"], "NoExiste", "Nuevo")
        assert result.kind.value == "not_found"

    def test_invalid_new_name_rejected(self, env):
        result = rename_world(env["mundos"], "Avalor", "../escape")
        assert result.kind.value == "invalid_name"


class TestListTrash:
    def test_empty_trash(self, env):
        assert wrb.list_trash(trash_root=env["trash"]) == []

    def test_sorted_desc_with_days_remaining(self, env):
        older = datetime.now(timezone.utc) - timedelta(days=10)
        newest = datetime.now(timezone.utc) - timedelta(days=2)
        _write_old_entry(env["trash"], "Kaelia", older)
        _write_old_entry(env["trash"], "Avalor", newest)
        entries = wrb.list_trash(trash_root=env["trash"])
        assert [e.world_name for e in entries] == ["Avalor", "Kaelia"]
        assert entries[0].days_remaining == wrb.RETENTION_DAYS - 2
        assert entries[1].days_remaining == wrb.RETENTION_DAYS - 10

    def test_corrupt_meta_is_skipped_and_kept(self, env):
        _write_old_entry(env["trash"], "Avalor", datetime.now(timezone.utc) - timedelta(days=1))
        bad = env["trash"] / "Kaelia" / "bad"
        bad.mkdir(parents=True)
        (bad / "meta.json").write_text("{not json", encoding="utf-8")
        entries = wrb.list_trash(trash_root=env["trash"])
        assert [e.world_name for e in entries] == ["Avalor"]
        assert bad.exists()


class TestPurgeExpired:
    def test_removes_old_skips_recent_and_corrupt(self, env):
        _write_old_entry(
            env["trash"], "OldWorld",
            datetime.now(timezone.utc) - timedelta(days=31),
        )
        _write_old_entry(
            env["trash"], "RecentWorld",
            datetime.now(timezone.utc) - timedelta(days=10),
        )
        corrupt = env["trash"] / "Corrupt" / "bad"
        corrupt.mkdir(parents=True)
        (corrupt / "meta.json").write_text("{bad", encoding="utf-8")

        purged = wrb.purge_expired(trash_root=env["trash"])

        assert purged == 1
        assert not (env["trash"] / "OldWorld").exists()
        assert (env["trash"] / "RecentWorld").exists()
        assert corrupt.exists()

    def test_empty_trash(self, env):
        assert wrb.purge_expired(trash_root=env["trash"]) == 0

    def test_on_purge_callback_invoked_per_world(self, env):
        _write_old_entry(
            env["trash"], "OldWorld",
            datetime.now(timezone.utc) - timedelta(days=31),
        )
        _write_old_entry(
            env["trash"], "RecentWorld",
            datetime.now(timezone.utc) - timedelta(days=10),
        )
        purged_worlds = []
        purged = wrb.purge_expired(
            trash_root=env["trash"],
            on_purge=purged_worlds.append,
        )
        assert purged == 1
        assert purged_worlds == ["OldWorld"]


class TestPurgeWorld:
    def test_removes_all_entries(self, env):
        _write_old_entry(env["trash"], "Avalor", datetime.now(timezone.utc) - timedelta(days=1))
        _write_old_entry(env["trash"], "Avalor", datetime.now(timezone.utc) - timedelta(days=2))
        wrb.purge_world("Avalor", trash_root=env["trash"])
        assert not (env["trash"] / "Avalor").exists()

    def test_unknown_world_raises(self, env):
        with pytest.raises(FileNotFoundError):
            wrb.purge_world("Fantasia", trash_root=env["trash"])


class TestGuidedSessionStoreDeleteForWorld:
    def test_drops_only_sessions_of_that_world(self):
        store = GuidedSessionStore()
        store.create("s1", "Avalor", "auth")
        store.create("s2", "Avalor", "auth")
        store.create("s3", "Kaelia", "auth")
        removed = store.delete_for_world("Avalor")
        assert removed == 2
        assert store.recover("s1", "auth") is None
        assert store.recover("s2", "auth") is None
        assert store.recover("s3", "auth") is not None

    def test_unknown_world_removes_nothing(self):
        store = GuidedSessionStore()
        store.create("s1", "Avalor", "auth")
        assert store.delete_for_world("Kaelia") == 0
        assert store.recover("s1", "auth") is not None