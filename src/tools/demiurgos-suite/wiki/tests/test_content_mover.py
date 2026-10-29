# -*- coding: utf-8 -*-
"""Moving the author's content to another folder or disk (step 5).

The contract: the plan validates before anything is written, the copy verifies
before the pointer moves, a cancelled or failed attempt leaves no half tree and
no pointer change, the source is never modified, and deleting the old copy is
bound to the record of a completed move plus an exact typed confirmation.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

import content_mover
from content_mover import MoveError, delete_source, execute_move, plan_move


def _content_root(tmp_path: Path) -> Path:
    """A content root shaped like a real one, including a code checkout."""
    root = tmp_path / "content"
    (root / "mundos" / "Avalor" / "lore").mkdir(parents=True)
    (root / "mundos" / "Avalor" / "lore" / "inicio.md").write_text(
        "# Inicio\n", encoding="utf-8"
    )
    (root / "ideas").mkdir()
    (root / "ideas" / "alpha.md").write_text("# Idea\n", encoding="utf-8")
    (root / "plantillas").mkdir()
    (root / "config").mkdir()
    (root / "config" / "backup.json").write_text("{}\n", encoding="utf-8")
    (root / "data" / "methodology").mkdir(parents=True)
    (root / "data" / "methodology" / "library.json").write_text(
        "{}", encoding="utf-8"
    )
    # Machine state that must never travel.
    (root / "data" / "idea-capture.sqlite3").write_bytes(b"SQLite format 3\x00")
    # A checkout: never content.
    (root / "src" / "tools").mkdir(parents=True)
    (root / "src" / "tools" / "api.py").write_text("x = 1\n", encoding="utf-8")
    (root / "frontend" / "src").mkdir(parents=True)
    (root / "frontend" / "src" / "main.tsx").write_text("export {}\n", encoding="utf-8")
    (root / ".env").write_text("DEMIURGOS_AUTH_MODE=local-dev\n", encoding="utf-8")
    return root


def _hashes(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def _empty(tmp_path: Path, name: str = "otro-disco") -> Path:
    target = tmp_path / name
    target.mkdir()
    return target


def test_the_plan_carries_the_author_content_and_the_env(tmp_path: Path) -> None:
    root = _content_root(tmp_path)
    plan = plan_move(root, _empty(tmp_path))

    assert plan.members == (".env", "config", "data", "ideas", "mundos", "plantillas")
    assert plan.total_files >= 4
    assert plan.total_bytes > 0
    skipped = dict(plan.skipped)
    assert skipped["src"].startswith("excluded:")
    assert skipped["frontend"].startswith("excluded:")


def test_a_move_copies_content_but_never_the_checkout_or_machine_state(
    tmp_path: Path,
) -> None:
    root = _content_root(tmp_path)
    target = _empty(tmp_path)
    plan = plan_move(root, target)

    outcome = execute_move(plan, publish=lambda path: None)

    assert outcome.published is True
    assert (target / "mundos" / "Avalor" / "lore" / "inicio.md").is_file()
    assert (target / ".env").is_file()
    assert (target / "config" / "backup.json").is_file()
    assert not (target / "src").exists()
    assert not (target / "frontend").exists()
    assert not (target / "data" / "idea-capture.sqlite3").exists()


def test_the_moved_folder_never_looks_like_it_holds_machine_state(
    tmp_path: Path,
) -> None:
    """A copied SQLite in the new root would make policy (ii) adopt stale state.

    This is the reason the copy honours per-FILE exclusions and not just the
    top-level names: an inert copy of the databases in the destination would be
    adopted on the next boot and the app would read the OLD data.
    """
    import state_paths

    root = _content_root(tmp_path)
    target = _empty(tmp_path)
    execute_move(plan_move(root, target), publish=lambda path: None)

    assert state_paths.holds_state(target / "data") is False


def test_the_pointer_is_published_only_after_the_copy_verified(
    tmp_path: Path,
) -> None:
    root = _content_root(tmp_path)
    target = _empty(tmp_path)
    before = _hashes(root)
    published: list[Path] = []

    execute_move(plan_move(root, target), publish=published.append)

    assert published == [target]
    # The source is untouched: no delete, no rename, no rewrite.
    assert _hashes(root) == before


def test_a_cancelled_move_publishes_nothing_and_leaves_no_half_tree(
    tmp_path: Path,
) -> None:
    root = _content_root(tmp_path)
    target = _empty(tmp_path)
    published: list[Path] = []

    outcome = execute_move(
        plan_move(root, target),
        publish=published.append,
        should_cancel=lambda: True,
    )

    assert outcome.cancelled is True
    assert published == []
    assert list(target.iterdir()) == []


def test_a_copy_that_does_not_verify_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _content_root(tmp_path)
    target = _empty(tmp_path)
    published: list[Path] = []
    real_copy = shutil.copy2

    def truncating_copy(source, destination, *args, **kwargs):
        result = real_copy(source, destination, *args, **kwargs)
        Path(destination).write_bytes(b"short")
        return result

    monkeypatch.setattr(content_mover.shutil, "copy2", truncating_copy)

    with pytest.raises(MoveError) as failure:
        execute_move(plan_move(root, target), publish=published.append)

    assert "did not verify" in str(failure.value)
    assert published == []
    assert list(target.iterdir()) == []


# ---------------------------------------------------------------------------
# The plan refuses before anything is written
# ---------------------------------------------------------------------------


def test_a_relative_destination_is_refused(tmp_path: Path) -> None:
    with pytest.raises(MoveError) as failure:
        plan_move(_content_root(tmp_path), "otro-disco")
    assert "absolute" in str(failure.value)


def test_a_missing_destination_is_refused(tmp_path: Path) -> None:
    with pytest.raises(MoveError) as failure:
        plan_move(_content_root(tmp_path), tmp_path / "no-existe")
    assert "existing directory" in str(failure.value)


def test_a_destination_that_holds_content_is_refused(tmp_path: Path) -> None:
    target = _empty(tmp_path)
    (target / "algo.md").write_text("x", encoding="utf-8")
    with pytest.raises(MoveError) as failure:
        plan_move(_content_root(tmp_path), target)
    assert "must be empty" in str(failure.value)


def test_a_destination_inside_the_content_root_is_refused(tmp_path: Path) -> None:
    root = _content_root(tmp_path)
    inside = root / "copia"
    inside.mkdir()
    with pytest.raises(MoveError) as failure:
        plan_move(root, inside)
    assert "overlaps" in str(failure.value)


def test_a_destination_overlapping_the_state_folder_is_refused(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state" / "data"
    state.mkdir(parents=True)
    with pytest.raises(MoveError) as failure:
        plan_move(_content_root(tmp_path), state, forbidden=[state])
    assert "overlaps" in str(failure.value)


def test_a_destination_without_room_is_refused(tmp_path: Path) -> None:
    root = _content_root(tmp_path)
    with pytest.raises(MoveError) as failure:
        plan_move(root, _empty(tmp_path), free_bytes=1)
    assert "no room" in str(failure.value)


def test_an_empty_content_root_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "vacio"
    empty.mkdir()
    with pytest.raises(MoveError) as failure:
        plan_move(empty, _empty(tmp_path))
    assert "no author content" in str(failure.value)


# ---------------------------------------------------------------------------
# Deleting the old copy: record-bound and doubly confirmed
# ---------------------------------------------------------------------------


def test_deleting_the_old_copy_needs_the_exact_typed_path(tmp_path: Path) -> None:
    old = _content_root(tmp_path)
    with pytest.raises(MoveError) as failure:
        delete_source(old, str(tmp_path), forbidden=[])
    assert "type the folder exactly" in str(failure.value)
    assert old.is_dir()

    removed = delete_source(old, str(old), forbidden=[])

    assert removed == str(old.resolve())
    assert not old.exists()


def test_deleting_is_refused_without_a_recorded_move(tmp_path: Path) -> None:
    with pytest.raises(MoveError) as failure:
        delete_source(None, str(tmp_path), forbidden=[])
    assert "no completed move" in str(failure.value)


def test_deleting_a_code_checkout_is_refused(tmp_path: Path) -> None:
    old = _content_root(tmp_path)
    (old / ".git").mkdir()
    with pytest.raises(MoveError) as failure:
        delete_source(old, str(old), forbidden=[])
    assert "code checkout" in str(failure.value)
    assert old.is_dir()


def test_deleting_the_folder_in_use_is_refused(tmp_path: Path) -> None:
    old = _content_root(tmp_path)
    current = old / "mundos"
    with pytest.raises(MoveError) as failure:
        delete_source(old, str(old), forbidden=[current])
    assert "overlaps" in str(failure.value)
    assert old.is_dir()


# ---------------------------------------------------------------------------
# Destination candidates: the web-native answer to "I cannot browse"
# ---------------------------------------------------------------------------


def test_candidates_offer_disks_home_and_siblings_but_never_the_current_root(
    tmp_path: Path,
) -> None:
    """A list of places a destination usually is — never the folder being moved."""
    from content_mover import destination_candidates

    current = _content_root(tmp_path)
    disk = tmp_path / "disco"
    disk.mkdir()
    (disk / "ya-hay.md").write_text("x\n", encoding="utf-8")  # not usable for a move
    empties = tmp_path / "vacia"
    empties.mkdir()

    items = destination_candidates(
        home=tmp_path,
        mounts=f"/dev/sdb1 {disk} ext4 rw 0 0\nproc /proc proc rw 0 0\n",
        current=current,
        extra=[empties, current / "mundos"],
    )

    paths = [item["path"] for item in items]
    assert str(disk.resolve()) in paths
    assert str(empties.resolve()) in paths
    assert str(current.resolve()) not in paths
    assert str((current / "mundos").resolve()) not in paths
    assert all(isinstance(item["free_bytes"], int) for item in items)
    # The empty folder a move can use comes before one that already has content.
    assert paths.index(str(empties.resolve())) < paths.index(str(disk.resolve()))
