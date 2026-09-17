# -*- coding: utf-8 -*-
"""Sync-folder discovery + classification tests (WU-12, task 12.7).

Covers REQ-SF-1 (no hardcoded destination; the picker is always offered), REQ-SF-2
(per-platform discovery, registry fallback on a reparse point) and REQ-SF-3
(verified streaming/mirroring detection with warn/block, ``unknown`` otherwise).

**Hermetic by construction.** Every OS touchpoint is injected — ``environ``,
``registry_reader``, ``drive_type``, ``platform`` and ``home`` — and every walk
is a fake entry list, so no test reads a real registry, a real drive type or a
real streaming mount. Paths used are ``tmp_path`` fixtures.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.sync_folder import (  # noqa: E402
    CONFIDENCE_HEURISTIC,
    CONFIDENCE_VERIFIED,
    DRIVE_FIXED,
    DRIVE_REMOTE,
    MIRRORING_REMEDY,
    MODE_MIRRORED,
    MODE_STREAMING,
    MODE_UNKNOWN,
    MODE_UNKNOWN_NOTE,
    PICKER_ALWAYS_OFFERED,
    PROVIDER_GOOGLE_DRIVE,
    PROVIDER_ICLOUD,
    PROVIDER_ONEDRIVE,
    REASON_NOT_A_DIRECTORY,
    SOURCE_ENV,
    SOURCE_HEURISTIC,
    SOURCE_REGISTRY,
    SOURCE_USER,
    bounded_walk,
    classify_target,
    discover_candidates,
    evaluate_target,
    find_forbidden_vocabulary,
    is_auto_selectable,
    manual_candidate,
    requires_confirmation,
)

MODULE_PATH = _WIKI / "backup" / "sync_folder.py"

#: Filesystem-attribute value for a OneDrive Files On-Demand placeholder. It is
#: UNVERIFIED and MUST NOT be implemented as a streaming signal (REQ-SF-3).
RECALL_ON_DATA_ACCESS = 0x400000


class FakeEntry:
    """Duck-typed stand-in for an ``os.DirEntry`` in an injected walk."""

    def __init__(
        self,
        name: str,
        *,
        is_dir: bool = False,
        stat_error: bool = False,
        st_file_attributes: int = 0,
    ) -> None:
        self.name = name
        self._is_dir = is_dir
        self._stat_error = stat_error
        self._st_file_attributes = st_file_attributes

    def is_dir(self) -> bool:
        return self._is_dir

    def stat(self) -> SimpleNamespace:
        if self._stat_error:
            raise OSError("placeholder is not materialized")
        return SimpleNamespace(
            st_size=1, st_file_attributes=self._st_file_attributes
        )


def walk_over(mapping: dict[Path, list[FakeEntry]]):
    """A walk seam that returns the entries keyed by the exact root it is given."""

    def walk(root: Path, limit: int) -> list[FakeEntry]:
        return list(mapping.get(Path(root), []))

    return walk


def _no_drive(path: Path) -> None:
    return None


# --------------------------------------------------------------------------
# REQ-SF-1 / REQ-SF-2 — discovery
# --------------------------------------------------------------------------
def test_onedrive_env_value_is_a_verified_candidate(tmp_path: Path) -> None:
    onedrive = tmp_path / "OneDrive"
    onedrive.mkdir()
    registry_calls: list[int] = []
    candidates = discover_candidates(
        environ={"OneDrive": str(onedrive)},
        platform="windows",
        home=tmp_path,
        drive_type=_no_drive,
        registry_reader=lambda: (registry_calls.append(1), [str(tmp_path / "reg")])[1],
    )
    assert len(candidates) == 1
    assert candidates[0].path == onedrive
    assert candidates[0].provider == PROVIDER_ONEDRIVE
    assert candidates[0].source == SOURCE_ENV
    assert candidates[0].confidence == CONFIDENCE_VERIFIED
    assert registry_calls == []  # a usable env value short-circuits the registry


def test_absent_env_reads_registry_userfolder(tmp_path: Path) -> None:
    registry = tmp_path / "OneDrive - Contoso"
    registry.mkdir()
    candidates = discover_candidates(
        environ={},
        platform="windows",
        home=tmp_path,
        drive_type=_no_drive,
        registry_reader=lambda: [str(registry)],
    )
    assert [(c.path, c.source, c.confidence) for c in candidates] == [
        (registry, SOURCE_REGISTRY, CONFIDENCE_VERIFIED)
    ]


def test_reparse_point_env_falls_back_to_registry_userfolder(tmp_path: Path) -> None:
    """SC-SF-2.1 — env is a reparse point, so the registry ``UserFolder`` wins."""
    real = tmp_path / "real-onedrive"
    real.mkdir()
    link = tmp_path / "linked-onedrive"
    try:
        os.symlink(real, link, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
        pytest.skip("this platform cannot create symlinks")
    registry = tmp_path / "resolved-by-registry"
    registry.mkdir()
    candidates = discover_candidates(
        environ={"OneDrive": str(link)},
        platform="windows",
        home=tmp_path,
        drive_type=_no_drive,
        registry_reader=lambda: [str(registry)],
    )
    assert [c.path for c in candidates] == [registry]
    assert candidates[0].source == SOURCE_REGISTRY


def test_non_directory_env_falls_back_to_registry(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "notes.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    registry = tmp_path / "resolved"
    registry.mkdir()
    candidates = discover_candidates(
        environ={"OneDrive": str(not_a_dir)},
        platform="windows",
        home=tmp_path,
        drive_type=_no_drive,
        registry_reader=lambda: [str(registry)],
    )
    assert [c.path for c in candidates] == [registry]


def test_duplicate_env_values_are_deduplicated(tmp_path: Path) -> None:
    onedrive = tmp_path / "OneDrive"
    onedrive.mkdir()
    candidates = discover_candidates(
        environ={
            "OneDrive": str(onedrive),
            "OneDriveConsumer": str(onedrive),
        },
        platform="windows",
        home=tmp_path,
        drive_type=_no_drive,
    )
    assert [c.path for c in candidates] == [onedrive]


def test_windows_google_drive_is_heuristic_and_never_auto_selected(
    tmp_path: Path,
) -> None:
    (tmp_path / "My Drive").mkdir()
    candidates = discover_candidates(
        environ={}, platform="windows", home=tmp_path, drive_type=_no_drive
    )
    google = [c for c in candidates if c.provider == PROVIDER_GOOGLE_DRIVE]
    assert google, "the My Drive heuristic must be suggested"
    assert all(c.source == SOURCE_HEURISTIC for c in google)
    assert all(c.confidence == CONFIDENCE_HEURISTIC for c in google)
    assert all(not is_auto_selectable(c) for c in google)


def test_dropbox_and_nextcloud_are_picker_only(tmp_path: Path) -> None:
    (tmp_path / "Dropbox").mkdir()
    (tmp_path / "Nextcloud").mkdir()
    candidates = discover_candidates(
        environ={"Dropbox": str(tmp_path / "Dropbox")},
        platform="windows",
        home=tmp_path,
        drive_type=_no_drive,
    )
    assert candidates == []


def test_macos_heuristics_are_heuristic(tmp_path: Path) -> None:
    (tmp_path / "Library" / "Mobile Documents" / "com~apple~CloudDocs").mkdir(
        parents=True
    )
    (tmp_path / "My Drive").mkdir()
    candidates = discover_candidates(
        environ={}, platform="darwin", home=tmp_path, drive_type=_no_drive
    )
    providers = {c.provider: c for c in candidates}
    assert providers[PROVIDER_ICLOUD].source == SOURCE_HEURISTIC
    assert providers[PROVIDER_ICLOUD].confidence == CONFIDENCE_HEURISTIC
    assert providers[PROVIDER_GOOGLE_DRIVE].source == SOURCE_HEURISTIC
    assert all(not is_auto_selectable(c) for c in candidates)


def test_linux_is_picker_only(tmp_path: Path) -> None:
    (tmp_path / "My Drive").mkdir()
    assert (
        discover_candidates(
            environ={}, platform="linux", home=tmp_path, drive_type=_no_drive
        )
        == []
    )


@pytest.mark.parametrize("system", ["windows", "macos", "linux", "freebsd"])
def test_picker_is_always_offered_on_every_os(
    system: str, tmp_path: Path
) -> None:
    """REQ-SF-1 — discovery is advisory; the picker is a universal guarantee."""
    candidates = discover_candidates(
        environ={}, platform=system, home=tmp_path, drive_type=_no_drive
    )
    assert isinstance(candidates, list)
    assert PICKER_ALWAYS_OFFERED is True
    assert all(requires_confirmation(c) for c in candidates)
    assert all(not is_auto_selectable(c) for c in candidates)


def test_manual_pick_records_unknown_user_heuristic(tmp_path: Path) -> None:
    candidate = manual_candidate(tmp_path)
    assert candidate.to_dict() == {
        "path": str(tmp_path),
        "provider": "unknown",
        "source": SOURCE_USER,
        "confidence": CONFIDENCE_HEURISTIC,
    }
    assert requires_confirmation(candidate)
    assert not is_auto_selectable(candidate)


# --------------------------------------------------------------------------
# REQ-SF-3 — streaming vs mirroring
# --------------------------------------------------------------------------
def test_remote_drive_marker_is_verified_streaming_and_blocked(
    tmp_path: Path,
) -> None:
    """SC-SF-3.1 — a verified streaming target is blocked, nothing is written."""
    target = tmp_path / "google-drive"
    target.mkdir()
    walk = walk_over({Path(target.anchor): [FakeEntry("My Drive", is_dir=True)]})

    capabilities = classify_target(
        target, drive_type=lambda path: DRIVE_REMOTE, walk=walk
    )
    assert capabilities.mode_hint == MODE_STREAMING
    assert capabilities.writable is False

    decision = evaluate_target(
        target, drive_type=lambda path: DRIVE_REMOTE, walk=walk
    )
    assert decision.accepted is False
    assert decision.remedy == MIRRORING_REMEDY
    assert decision.reason == "verified streaming/virtual target"


def test_unstattable_entry_is_verified_streaming(tmp_path: Path) -> None:
    target = tmp_path / "virtual"
    target.mkdir()
    walk = walk_over({target: [FakeEntry("placeholder.txt", stat_error=True)]})
    capabilities = classify_target(
        target, drive_type=lambda path: DRIVE_FIXED, walk=walk
    )
    assert capabilities.mode_hint == MODE_STREAMING
    assert capabilities.writable is False


def test_fixed_drive_with_readable_walk_is_mirrored_and_accepted(
    tmp_path: Path,
) -> None:
    """SC-SF-3.2 — a mirrored local copy is accepted without a warning."""
    target = tmp_path / "local-copy"
    target.mkdir()
    walk = walk_over({target: [FakeEntry("a.md"), FakeEntry("b.md")]})
    capabilities = classify_target(
        target, drive_type=lambda path: DRIVE_FIXED, walk=walk
    )
    assert capabilities.mode_hint == MODE_MIRRORED
    assert capabilities.writable is True

    decision = evaluate_target(
        target, drive_type=lambda path: DRIVE_FIXED, walk=walk
    )
    assert decision.accepted is True
    assert decision.remedy is None
    assert decision.note is None


def test_remote_drive_without_markers_is_unknown(tmp_path: Path) -> None:
    target = tmp_path / "remote-other"
    target.mkdir()
    walk = walk_over({target: [FakeEntry("a.md")]})
    capabilities = classify_target(
        target, drive_type=lambda path: DRIVE_REMOTE, walk=walk
    )
    assert capabilities.mode_hint == MODE_UNKNOWN


def test_no_verified_signal_is_unknown_and_accepted_with_a_note(
    tmp_path: Path,
) -> None:
    """SC-SF-3.3 — a heuristic guess never blocks and never says streaming."""
    target = tmp_path / "heuristic"
    target.mkdir()
    walk = walk_over({target: [FakeEntry("a.md")]})
    capabilities = classify_target(target, drive_type=None, walk=walk)
    assert capabilities.mode_hint == MODE_UNKNOWN

    decision = evaluate_target(target, drive_type=None, walk=walk)
    assert decision.accepted is True
    assert decision.note == MODE_UNKNOWN_NOTE
    assert decision.remedy is None


def test_recall_on_data_attribute_is_not_a_verified_signal(tmp_path: Path) -> None:
    """The OneDrive placeholder attribute is UNVERIFIED, so it cannot block."""
    target = tmp_path / "onedrive"
    target.mkdir()
    entry = FakeEntry("placeholder.bin", st_file_attributes=RECALL_ON_DATA_ACCESS)
    walk = walk_over({target: [entry]})
    capabilities = classify_target(
        target, drive_type=lambda path: DRIVE_FIXED, walk=walk
    )
    assert capabilities.mode_hint != MODE_STREAMING
    assert capabilities.mode_hint == MODE_MIRRORED


def test_unverified_drive_type_value_never_reports_streaming(
    tmp_path: Path,
) -> None:
    """If the Drive virtual drive reports FIXED, the marker pair does not fire."""
    target = tmp_path / "drive-unverified"
    target.mkdir()
    walk = walk_over({Path(target.anchor): [FakeEntry("My Drive", is_dir=True)]})
    capabilities = classify_target(
        target, drive_type=lambda path: DRIVE_FIXED, walk=walk
    )
    assert capabilities.mode_hint != MODE_STREAMING


def test_missing_target_is_rejected_with_a_reason(tmp_path: Path) -> None:
    decision = evaluate_target(
        tmp_path / "missing", drive_type=None, walk=walk_over({})
    )
    assert decision.accepted is False
    assert decision.reason == REASON_NOT_A_DIRECTORY


def test_file_target_is_rejected(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "not-a-directory.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    decision = evaluate_target(not_a_dir, drive_type=None, walk=walk_over({}))
    assert decision.accepted is False
    assert decision.reason == REASON_NOT_A_DIRECTORY


def test_bounded_walk_respects_its_limit(tmp_path: Path) -> None:
    for index in range(6):
        (tmp_path / f"f{index}.md").write_text("x", encoding="utf-8")
    assert len(list(bounded_walk(tmp_path, 3))) == 3


# --------------------------------------------------------------------------
# REQ-SF-1 — no hardcoded destination; UNVERIFIED signal stays unimplemented
# --------------------------------------------------------------------------
def _callee(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_module_hardcodes_no_destination_path_or_drive_letter() -> None:
    """SC-SF-1.2 — a scanned destination literal or drive letter cannot exist."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert re.search(r"[A-Za-z]:[\\/]", source) is None, "drive-letter literal found"

    tree = ast.parse(source)
    candidate_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee(node) == "Candidate"
    ]
    assert candidate_calls, "expected Candidate(...) construction sites"
    for node in candidate_calls:
        first = node.args[0]
        assert not (
            isinstance(first, ast.Constant) and isinstance(first.value, str)
        ), "a Candidate path must never be a string literal"
        if isinstance(first, ast.Call) and _callee(first) == "Path":
            assert not (
                first.args
                and isinstance(first.args[0], ast.Constant)
                and isinstance(first.args[0].value, str)
            ), "a Candidate path must never be Path(<literal>)"


def test_module_does_not_implement_recall_on_data_access() -> None:
    """The UNVERIFIED placeholder attribute must not appear as a runtime value."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and node.value == RECALL_ON_DATA_ACCESS
    ]
    assert offenders == [], f"RECALL_ON_DATA_ACCESS used at lines {offenders}"

