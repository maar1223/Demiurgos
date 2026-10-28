# -*- coding: utf-8 -*-
"""State-root adoption tests — the one-time move of ``<data root>/data``.

Covers ``state_root_migration.adopt_existing_state``: a dry no-op when there is
nothing to adopt or the target already exists, a copy that is proven
byte-identical before it is published, a failure that leaves the source
untouched and no partial ``data`` behind, and the evidence record.

Every test uses ``tmp_path`` for both roots, so nothing touches the real data
root, the real state root or the real user directories.
"""

import json
import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import state_root_migration as srm  # noqa: E402


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    data_root = tmp_path / "content"
    state_root = tmp_path / "state"
    data_root.mkdir()
    return data_root, state_root


def _seed_state(data_root: Path) -> Path:
    """A realistic legacy ``<data root>/data`` (SQLite + WAL siblings + trash)."""
    legacy = data_root / srm.STATE_DIR_NAME
    (legacy / "world-trash" / "vibrantes").mkdir(parents=True)
    (legacy / "world-trash" / "vibrantes" / "world.yaml").write_text(
        "title: Vibrantes\n", encoding="utf-8"
    )
    (legacy / "idea-capture.sqlite3").write_bytes(b"SQLite format 3\x00fake-db")
    (legacy / "idea-capture.sqlite3-wal").write_bytes(b"fake-wal")
    (legacy / "idea-capture.sqlite3-shm").write_bytes(b"fake-shm")
    (legacy / "local-state.json").write_text("{}\n", encoding="utf-8")
    return legacy


def _orphan_stages(state_root: Path) -> list[Path]:
    if not state_root.is_dir():
        return []
    return sorted(p for p in state_root.glob(f"{srm.STATE_DIR_NAME}.tmp-*"))


# ---------------------------------------------------------------------------
# Dry no-ops
# ---------------------------------------------------------------------------


def test_no_state_in_the_data_root_is_a_noop(tmp_path: Path):
    data_root, state_root = _roots(tmp_path)
    (data_root / srm.STATE_DIR_NAME).mkdir()
    (data_root / srm.STATE_DIR_NAME / "unrelated.txt").write_text("x", encoding="utf-8")

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert result.adopted is False
    assert result.reason == "no_source"
    assert not (state_root / srm.STATE_DIR_NAME).exists()


def test_missing_data_directory_is_a_noop(tmp_path: Path):
    data_root, state_root = _roots(tmp_path)

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert (result.adopted, result.reason) == (False, "no_source")


def test_existing_target_is_never_overwritten(tmp_path: Path):
    data_root, state_root = _roots(tmp_path)
    _seed_state(data_root)
    target = state_root / srm.STATE_DIR_NAME
    target.mkdir(parents=True)
    keeper = target / "already-here.txt"
    keeper.write_text("keep me", encoding="utf-8")

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert (result.adopted, result.reason) == (False, "already_present")
    assert keeper.read_text(encoding="utf-8") == "keep me"
    assert not (target / srm.COMPLETE_MARKER).exists()


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_adoption_copies_the_state_and_proves_content_intact(tmp_path: Path):
    data_root, state_root = _roots(tmp_path)
    legacy = _seed_state(data_root)

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert (result.adopted, result.reason) == (True, "adopted")
    assert result.source_hash == result.target_hash != ""
    target = state_root / srm.STATE_DIR_NAME
    assert (target / "idea-capture.sqlite3").read_bytes() == (
        legacy / "idea-capture.sqlite3"
    ).read_bytes()
    # The WAL and SHM siblings travel with the database, so SQLite can replay.
    assert (target / "idea-capture.sqlite3-wal").exists()
    assert (target / "idea-capture.sqlite3-shm").exists()
    assert (target / "world-trash" / "vibrantes" / "world.yaml").exists()
    assert (target / srm.COMPLETE_MARKER).is_file()


def test_the_source_is_left_in_place_and_inert(tmp_path: Path):
    """Nothing is deleted: a later cleanup step may offer to remove it."""
    data_root, state_root = _roots(tmp_path)
    legacy = _seed_state(data_root)

    srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert legacy.is_dir()
    assert (legacy / "idea-capture.sqlite3").exists()


def test_second_run_is_a_noop_and_keeps_the_first_copy(tmp_path: Path):
    data_root, state_root = _roots(tmp_path)
    _seed_state(data_root)
    first = srm.adopt_existing_state(data_root=data_root, state_root=state_root)
    target = state_root / srm.STATE_DIR_NAME
    before = (target / "idea-capture.sqlite3").read_bytes()

    second = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert first.adopted is True
    assert (second.adopted, second.reason) == (False, "already_present")
    assert (target / "idea-capture.sqlite3").read_bytes() == before


def test_no_stage_directory_survives_a_successful_run(tmp_path: Path):
    data_root, state_root = _roots(tmp_path)
    _seed_state(data_root)

    srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert _orphan_stages(state_root) == []


# ---------------------------------------------------------------------------
# Failure paths — the source is never damaged and the target never partial
# ---------------------------------------------------------------------------


def test_a_failed_copy_removes_the_stage_and_keeps_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    data_root, state_root = _roots(tmp_path)
    legacy = _seed_state(data_root)
    before = sorted(p.name for p in legacy.rglob("*"))

    def boom(src, dst, **_kwargs):
        # Fail MID-copy: a partial stage must be cleaned up, not published.
        Path(dst).mkdir(parents=True)
        (Path(dst) / "half-copied.bin").write_bytes(b"half")
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(srm.shutil, "copytree", boom)

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert (result.adopted, result.reason) == (False, "failed")
    assert "disk full" in result.detail
    assert not (state_root / srm.STATE_DIR_NAME).exists()
    assert _orphan_stages(state_root) == []
    assert sorted(p.name for p in legacy.rglob("*")) == before


def test_a_changed_source_fails_the_content_intact_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A source that moved under us must abort, not publish a mixed copy."""
    data_root, state_root = _roots(tmp_path)
    _seed_state(data_root)
    digests = iter(["source-digest", "different-digest"])
    monkeypatch.setattr(srm, "_tree_sha256", lambda *_a, **_k: next(digests))

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert (result.adopted, result.reason) == (False, "failed")
    assert "content-intact" in result.detail
    assert not (state_root / srm.STATE_DIR_NAME).exists()
    assert _orphan_stages(state_root) == []


def test_a_crash_before_publish_leaves_the_target_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Complete-or-absent: the publish is one atomic rename, so a reader never
    observes a partial ``data``."""
    data_root, state_root = _roots(tmp_path)
    _seed_state(data_root)

    def boom(*_args, **_kwargs):
        raise OSError("publish interrupted (simulated)")

    monkeypatch.setattr(srm.os, "replace", boom)

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert (result.adopted, result.reason) == (False, "failed")
    assert not (state_root / srm.STATE_DIR_NAME).exists()
    assert _orphan_stages(state_root) == []


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_evidence_records_the_adoption(tmp_path: Path):
    data_root, state_root = _roots(tmp_path)
    _seed_state(data_root)

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert result.evidence_path is not None
    record = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert record["kind"] == "state-root-adoption"
    assert record["outcome"] == "adopted"
    assert record["transaction_id"] == result.transaction_id
    assert record["source"] == str(data_root / srm.STATE_DIR_NAME)
    assert record["target"] == str(state_root / srm.STATE_DIR_NAME)
    assert record["source_hash"] == record["target_hash"] == result.source_hash
    assert record["files"] >= 4
    assert record["recorded_at"].endswith("Z")


def test_evidence_records_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    data_root, state_root = _roots(tmp_path)
    _seed_state(data_root)

    def boom(*_args, **_kwargs):
        raise OSError("copy exploded (simulated)")

    monkeypatch.setattr(srm.shutil, "copytree", boom)

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert result.evidence_path is not None
    record = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert record["outcome"] == "failed"
    assert "copy exploded" in record["detail"]


# ---------------------------------------------------------------------------
# Hardening cells from the independent verification pass (a251009d)
# ---------------------------------------------------------------------------


def test_evidence_directory_failure_does_not_raise_after_publish(tmp_path: Path):
    """Evidence must never turn a published adoption into an exception."""
    data_root, state_root = _roots(tmp_path)
    _seed_state(data_root)
    state_root.mkdir()
    (state_root / srm.EVIDENCE_DIR).write_text("not a directory", encoding="utf-8")

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert (result.adopted, result.reason) == (True, "adopted")
    assert (state_root / srm.STATE_DIR_NAME / srm.COMPLETE_MARKER).is_file()
    assert result.evidence_path is None


def test_non_utf8_source_entry_is_adopted(tmp_path: Path):
    """A filename that is not valid UTF-8 must not crash the tree hash."""
    data_root, state_root = _roots(tmp_path)
    legacy = _seed_state(data_root)
    raw = os.fsencode(str(legacy)) + b"/odd-\xff-name"
    handle = os.open(raw, os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(handle, b"x")
    finally:
        os.close(handle)

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert (result.adopted, result.reason) == (True, "adopted")
    assert result.source_hash == result.target_hash
    names = os.listdir(os.fsencode(str(state_root / srm.STATE_DIR_NAME)))
    assert b"odd-\xff-name" in names


def test_tree_hash_distinguishes_entry_boundaries(tmp_path: Path):
    """The digest must be injective: no collision by concatenation ambiguity."""
    first = tmp_path / "first"
    first.mkdir()
    (first / "one").write_bytes(b"alpha")
    (first / "two").write_bytes(b"beta")

    second = tmp_path / "second"
    second.mkdir()
    (second / "one").write_bytes(b"alpha\n" + b"two\x00file\x00" + b"beta")

    assert srm._tree_sha256(first) != srm._tree_sha256(second)


def test_source_with_a_stale_marker_is_still_adopted(tmp_path: Path):
    """A source restored from another state root must not be unadoptable."""
    data_root, state_root = _roots(tmp_path)
    legacy = _seed_state(data_root)
    (legacy / srm.COMPLETE_MARKER).write_text("stale\n", encoding="utf-8")

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert (result.adopted, result.reason) == (True, "adopted")
    assert result.source_hash == result.target_hash


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges")
def test_symlinked_directory_entry_is_preserved_not_followed(tmp_path: Path):
    data_root, state_root = _roots(tmp_path)
    legacy = _seed_state(data_root)
    (legacy / "real").mkdir()
    (legacy / "real" / "f.txt").write_text("x", encoding="utf-8")
    (legacy / "linkdir").symlink_to("real")

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    target = state_root / srm.STATE_DIR_NAME
    assert result.reason == "adopted"
    assert os.path.islink(target / "linkdir")
    assert (target / "real" / "f.txt").read_text(encoding="utf-8") == "x"
    assert result.source_hash == result.target_hash


def test_source_tree_is_byte_identical_after_a_successful_adoption(tmp_path: Path):
    data_root, state_root = _roots(tmp_path)
    legacy = _seed_state(data_root)
    before = srm._tree_sha256(legacy)

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert result.reason == "adopted"
    assert srm._tree_sha256(legacy) == before


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX-only")
def test_a_special_file_fails_fast_instead_of_hanging(tmp_path: Path):
    """shutil would block opening a FIFO; refuse the tree before copying."""
    data_root, state_root = _roots(tmp_path)
    legacy = _seed_state(data_root)
    os.mkfifo(legacy / "a-fifo")
    before = sorted(p.name for p in legacy.rglob("*"))

    result = srm.adopt_existing_state(data_root=data_root, state_root=state_root)

    assert (result.adopted, result.reason) == (False, "failed")
    assert "unsupported special file" in result.detail
    assert not (state_root / srm.STATE_DIR_NAME).exists()
    assert _orphan_stages(state_root) == []
    assert sorted(p.name for p in legacy.rglob("*")) == before


def test_a_state_root_inside_the_source_is_refused(tmp_path: Path):
    """It would write into the very tree it is adopting."""
    data_root, _state_root = _roots(tmp_path)
    legacy = _seed_state(data_root)
    nested = legacy / "state"

    result = srm.adopt_existing_state(data_root=data_root, state_root=nested)

    assert (result.adopted, result.reason) == (False, "failed")
    assert "must not live inside" in result.detail
    assert not (legacy / "state" / srm.STATE_DIR_NAME).exists()
