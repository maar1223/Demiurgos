"""Unit tests for the co-creation attachment staging module (S2).

Covers AE-1 (validated staging upload), AE-2 (fail-closed staging
abandonment) and AE-3 (atomic move + rollback): resolver shape, atomic
writes, the full guard order with zero mutation on rejection, the rollback
of a mid-move failure (no partial ``attachments/`` tree), and the
best-effort sweep that never touches ``attachments/``.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from co_creation_attachments import (  # noqa: E402
    ATTACHMENTS_SUBDIR,
    STAGING_SUBDIR,
    AttachmentUploadError,
    move_staged,
    staging_dir_for,
    store_staged,
    validate_staged_upload,
)
from methodology_compiler import (  # noqa: E402
    MAX_ADJUNTO_BYTES,
    MAX_ADJUNTOS,
    MAX_NIVEL_LEN,
    AttachmentEntry,
)


def _pin(name: str, data: bytes, nivel: str = "1º") -> AttachmentEntry:
    return AttachmentEntry(
        path=name, sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data), nivel=nivel,
    )


def _stage(staging_dir: Path, name: str, data: bytes = b"# ejemplar\n") -> None:
    store_staged(staging_dir, name, data)


# ---------------------------------------------------------------------------
# Resolver + atomic store
# ---------------------------------------------------------------------------


def test_staging_dir_is_session_scoped(tmp_path: Path) -> None:
    assert staging_dir_for(tmp_path, "co-creation-abc") == (
        tmp_path / STAGING_SUBDIR / "co-creation-abc"
    )
    # Pure resolver: no filesystem side effect.
    assert not staging_dir_for(tmp_path, "co-creation-abc").exists()


def test_store_staged_writes_atomically_without_tmp_leftover(tmp_path: Path) -> None:
    staging = staging_dir_for(tmp_path, "s-1")
    store_staged(staging, "a.md", b"# a\n")
    assert (staging / "a.md").read_bytes() == b"# a\n"
    assert sorted(p.name for p in staging.iterdir()) == ["a.md"]


def test_store_staged_replaces_existing_bytes(tmp_path: Path) -> None:
    staging = staging_dir_for(tmp_path, "s-1")
    store_staged(staging, "a.md", b"# old\n")
    store_staged(staging, "a.md", b"# new\n")
    assert (staging / "a.md").read_bytes() == b"# new\n"
    assert sorted(p.name for p in staging.iterdir()) == ["a.md"]


# ---------------------------------------------------------------------------
# Guard order (3–8) with zero mutation on rejection
# ---------------------------------------------------------------------------


def _reject(staging: Path, filename: str, data: bytes, nivel: str) -> AttachmentUploadError:
    with pytest.raises(AttachmentUploadError) as excinfo:
        validate_staged_upload(staging, filename, data, nivel)
    return excinfo.value


def test_empty_file_is_400_invalid_input(tmp_path: Path) -> None:
    error = _reject(staging_dir_for(tmp_path, "s-1"), "a.md", b"", "1º")
    assert (error.status, error.code) == (400, "invalid_input")


@pytest.mark.parametrize("filename", [
    "../escape.md",
    "/absolute/x.md",
    "mundos/x.md",
    "referencias/x.md",
    "notes.txt",
    "sub/dir.md",
    "win\\path.md",
    "",
])
def test_unsafe_filename_is_422_invalid_input(tmp_path: Path, filename: str) -> None:
    error = _reject(staging_dir_for(tmp_path, "s-1"), filename, b"# x\n", "1º")
    assert (error.status, error.code) == (422, "invalid_input")


def test_bad_nivel_is_422_invalid_input(tmp_path: Path) -> None:
    staging = staging_dir_for(tmp_path, "s-1")
    assert _reject(staging, "a.md", b"# x\n", "   ").status == 422
    assert _reject(staging, "a.md", b"# x\n", "x" * (MAX_NIVEL_LEN + 1)).status == 422


def test_oversize_is_422_attachment_limit_reached(tmp_path: Path) -> None:
    staging = staging_dir_for(tmp_path, "s-1")
    error = _reject(staging, "a.md", b"x" * (MAX_ADJUNTO_BYTES + 1), "1º")
    assert (error.status, error.code) == (422, "attachment_limit_reached")
    # Nothing was written: zero mutation on rejection.
    assert not staging.exists()


def test_too_many_is_422_attachment_limit_reached(tmp_path: Path) -> None:
    staging = staging_dir_for(tmp_path, "s-1")
    for index in range(MAX_ADJUNTOS):
        _stage(staging, f"f{index}.md")
    error = _reject(staging, "one-more.md", b"# x\n", "1º")
    assert (error.status, error.code) == (422, "attachment_limit_reached")
    assert len(list(staging.glob("*.md"))) == MAX_ADJUNTOS


def test_duplicate_basename_is_409_attachment_conflict(tmp_path: Path) -> None:
    staging = staging_dir_for(tmp_path, "s-1")
    _stage(staging, "a.md", b"# original\n")
    error = _reject(staging, "a.md", b"# other\n", "2º")
    assert (error.status, error.code) == (409, "attachment_conflict")
    # The prior pin/bytes are unchanged.
    assert (staging / "a.md").read_bytes() == b"# original\n"


def test_valid_upload_returns_normalized_basename(tmp_path: Path) -> None:
    staging = staging_dir_for(tmp_path, "s-1")
    assert validate_staged_upload(staging, "a.md", b"# x\n", "1º") == "a.md"


def test_rejected_upload_never_writes(tmp_path: Path) -> None:
    staging = staging_dir_for(tmp_path, "s-1")
    with pytest.raises(AttachmentUploadError):
        validate_staged_upload(staging, "bad.txt", b"# x\n", "1º")
    with pytest.raises(AttachmentUploadError):
        validate_staged_upload(staging, "ok.md", b"", "1º")
    assert not staging.exists()


# ---------------------------------------------------------------------------
# Atomic move + rollback (AE-3)
# ---------------------------------------------------------------------------


def test_move_staged_moves_all_pins(tmp_path: Path) -> None:
    staging = staging_dir_for(tmp_path, "s-1")
    attachments = tmp_path / ATTACHMENTS_SUBDIR
    first, second = _pin("a.md", b"# a\n"), _pin("b.md", b"# b\n")
    store_staged(staging, first.path, b"# a\n")
    store_staged(staging, second.path, b"# b\n")

    moved = move_staged(staging, attachments, "demo-skill", (first, second))

    assert [path.name for path in moved] == ["a.md", "b.md"]
    assert (attachments / "demo-skill" / "a.md").read_bytes() == b"# a\n"
    assert (attachments / "demo-skill" / "b.md").read_bytes() == b"# b\n"
    assert sorted(p.name for p in (attachments / "demo-skill").iterdir()) == [
        "a.md", "b.md",
    ]


def test_move_staged_failure_rolls_back_and_leaves_no_partial_tree(tmp_path: Path) -> None:
    """A failing second move removes the first file and the empty skill dir."""
    staging = staging_dir_for(tmp_path, "s-1")
    attachments = tmp_path / ATTACHMENTS_SUBDIR
    good = _pin("a.md", b"# a\n")
    missing = _pin("b.md", b"# b\n")
    store_staged(staging, good.path, b"# a\n")  # b.md intentionally absent

    with pytest.raises(OSError):
        move_staged(staging, attachments, "demo-skill", (good, missing))

    assert not (attachments / "demo-skill").exists()
    assert not attachments.exists() or list(attachments.iterdir()) == []


def test_move_staged_rollback_preserves_preexisting_files(tmp_path: Path) -> None:
    """Rollback never touches files the materialize did not move itself."""
    staging = staging_dir_for(tmp_path, "s-1")
    attachments = tmp_path / ATTACHMENTS_SUBDIR
    dest_dir = attachments / "demo-skill"
    dest_dir.mkdir(parents=True)
    (dest_dir / "existing.md").write_bytes(b"# keep\n")
    good = _pin("a.md", b"# a\n")
    missing = _pin("b.md", b"# b\n")
    store_staged(staging, good.path, b"# a\n")

    with pytest.raises(OSError):
        move_staged(staging, attachments, "demo-skill", (good, missing))

    assert (dest_dir / "existing.md").read_bytes() == b"# keep\n"
    assert not (dest_dir / "a.md").exists()
    # The skill dir survives because it was not empty.
    assert dest_dir.is_dir()


# ---------------------------------------------------------------------------
# Best-effort sweep (AE-2)
# ---------------------------------------------------------------------------


def test_sweep_staging_removes_only_old_dirs_and_never_attachments(tmp_path: Path) -> None:
    staging_root = tmp_path / STAGING_SUBDIR
    old = staging_root / "abandoned"
    fresh = staging_root / "active"
    _stage(old, "a.md")
    _stage(fresh, "b.md")
    attachments = tmp_path / ATTACHMENTS_SUBDIR / "demo-skill"
    attachments.mkdir(parents=True)
    (attachments / "a.md").write_bytes(b"# carrier\n")

    stale_ts = time.time() - 10 * 86_400
    os.utime(old, (stale_ts, stale_ts))
    os.utime(old / "a.md", (stale_ts, stale_ts))

    from co_creation_attachments import sweep_staging  # noqa: E402

    assert sweep_staging(tmp_path, older_than_days=1) == 1
    assert not old.exists()
    assert (fresh / "b.md").read_bytes() == b"# ejemplar\n"
    # attachments/ is never touched by the sweep.
    assert (attachments / "a.md").read_bytes() == b"# carrier\n"


def test_sweep_staging_no_root_is_noop(tmp_path: Path) -> None:
    from co_creation_attachments import sweep_staging  # noqa: E402

    assert sweep_staging(tmp_path, older_than_days=0) == 0


# ---------------------------------------------------------------------------
# U2 — publish move overwrite guard (EP-5) with zero mutation
# ---------------------------------------------------------------------------


def test_move_publish_pins_refuses_byte_drift_with_zero_mutation(tmp_path: Path) -> None:
    """A same-basename pin with different bytes is refused 422; the carrier
    and the staged bytes are both left untouched (fail closed)."""
    from co_creation_materializer import (  # noqa: E402
        AttachmentMaterializationError,
        move_publish_pins,
    )

    staging = staging_dir_for(tmp_path, "s-1")
    attachments = tmp_path / ATTACHMENTS_SUBDIR
    dest = attachments / "demo-skill"
    dest.mkdir(parents=True)
    (dest / "a.md").write_bytes(b"# carrier\n")
    store_staged(staging, "a.md", b"# replacement\n")
    incoming = _pin("a.md", b"# replacement\n")

    with pytest.raises(AttachmentMaterializationError) as excinfo:
        move_publish_pins(
            (incoming,), skill_id="demo-skill", staging_dir=staging,
            attachments_root=attachments, project_root=tmp_path,
        )

    assert (excinfo.value.status, excinfo.value.code) == (
        422, "attachment_overwrite_refused",
    )
    assert (dest / "a.md").read_bytes() == b"# carrier\n"
    assert (staging / "a.md").read_bytes() == b"# replacement\n"
