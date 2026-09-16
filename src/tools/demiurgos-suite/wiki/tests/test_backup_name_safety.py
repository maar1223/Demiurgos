# -*- coding: utf-8 -*-
"""Name-safety tests for ``FolderTransport`` (WU-6b).

Covers REQ-BE-9 and its two scenarios: SC-BE-9.1 (two source names that
collapse to one path after NFC normalization abort the run naming BOTH
sources) and SC-BE-9.2 (unsafe names — Windows reserved names, trailing
dot/space, over-long component/path, and path traversal — are rejected BEFORE
publishing, leaving no partial tree).

The traversal case is an explicit regression guard: ``publish_current`` used to
accept ``"../x"`` and write outside ``current/``. The rejection is asserted
before anything is written, so the target tree stays byte-identical.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.transport.base import TransportError  # noqa: E402
from backup.transport.folder import FolderTransport  # noqa: E402

# The SAME name in its precomposed (NFC) and decomposed (NFD) forms. NFC
# normalization maps the second onto the first, so staging both is a collision.
_NFC_NAME = "caf\u00e9.md"
_NFD_NAME = "cafe\u0301.md"


def _folder(tmp_path: Path) -> FolderTransport:
    """A transport whose retry backoff never actually sleeps."""
    return FolderTransport(tmp_path, sleep=lambda _seconds: None)


def _tree_state(root: Path) -> dict[str, bytes | None]:
    """Every path under *root* (directories as ``None``) plus file bytes."""
    state: dict[str, bytes | None] = {}
    for path in sorted(root.rglob("*")):
        state[str(path.relative_to(root))] = (
            path.read_bytes() if path.is_file() else None
        )
    return state


def test_nfc_collision_fails_loudly_naming_both_sources(tmp_path: Path) -> None:
    """Two distinct sources collapsing to one NFC path abort and name both."""
    transport = _folder(tmp_path)
    transport.ensure_layout()
    before = _tree_state(tmp_path / "Demiurgos")
    with pytest.raises(TransportError) as excinfo:
        transport.publish_current({_NFC_NAME: b"a", _NFD_NAME: b"b"}, manifest={})
    message = str(excinfo.value)
    assert _NFC_NAME in message  # both original sources are named
    assert _NFD_NAME in message
    assert "collide" in message
    assert _tree_state(tmp_path / "Demiurgos") == before  # collision wrote nothing


def test_staged_paths_are_nfc_normalized_before_publish(tmp_path: Path) -> None:
    """A lone decomposed path is published under its NFC name."""
    transport = _folder(tmp_path)
    transport.ensure_layout()
    assert transport.publish_current({_NFD_NAME: b"x"}, manifest={}).published == 1
    current = tmp_path / "Demiurgos" / "current"
    assert (current / _NFC_NAME).read_bytes() == b"x"
    assert not (current / _NFD_NAME).exists()


@pytest.mark.parametrize(
    "name",
    ["CON", "con", "con.txt", "aux", "nul.json", "COM1", "com9.md", "LPT9", "prn.log"],
)
def test_windows_reserved_names_are_rejected_with_or_without_extension(
    tmp_path: Path, name: str
) -> None:
    """``CON``/``con.txt``/``COM1`` are reserved, case-insensitively, with extension."""
    transport = _folder(tmp_path)
    transport.ensure_layout()
    with pytest.raises(TransportError) as excinfo:
        transport.publish_current({name: b"x"}, manifest={})
    assert "reserved name" in str(excinfo.value)


@pytest.mark.parametrize("name", ["aux.", "aux ", "nested/aux.", "trailing /x.md"])
def test_trailing_dot_or_space_is_rejected(tmp_path: Path, name: str) -> None:
    """A component ending in ``.`` or a space is rejected (``aux.``/``aux ``)."""
    transport = _folder(tmp_path)
    transport.ensure_layout()
    with pytest.raises(TransportError) as excinfo:
        transport.publish_current({name: b"x"}, manifest={})
    assert "ending in a dot or space" in str(excinfo.value)


def test_component_longer_than_200_chars_is_rejected(tmp_path: Path) -> None:
    """A single component over the 200-character budget is rejected."""
    transport = _folder(tmp_path)
    transport.ensure_layout()
    with pytest.raises(TransportError) as excinfo:
        transport.publish_current({"x" * 201: b"x"}, manifest={})
    assert "component longer than 200" in str(excinfo.value)
    assert transport.publish_current({"y" * 200: b"ok"}, manifest={}).published == 1


def test_relative_path_longer_than_240_chars_is_rejected(tmp_path: Path) -> None:
    """A full path over the 240-character budget is rejected even when each part fits."""
    transport = _folder(tmp_path)
    transport.ensure_layout()
    long_path = "a" * 150 + "/" + "b" * 150  # 301 chars; both components under 200
    with pytest.raises(TransportError) as excinfo:
        transport.publish_current({long_path: b"x"}, manifest={})
    assert "longer than 240" in str(excinfo.value)


def test_publish_current_rejects_parent_traversal(tmp_path: Path) -> None:
    """The closed hole: ``../x`` must not write outside ``current/``."""
    transport = _folder(tmp_path)
    transport.ensure_layout()
    before = _tree_state(tmp_path / "Demiurgos")
    with pytest.raises(TransportError) as excinfo:
        transport.publish_current({"../escape.md": b"x"}, manifest={})
    assert "unsafe path component" in str(excinfo.value)
    assert _tree_state(tmp_path / "Demiurgos") == before
    assert not (tmp_path / "escape.md").exists()
    assert not (tmp_path / "Demiurgos" / "escape.md").exists()


@pytest.mark.parametrize(
    "name",
    ["nested/../../escape.md", "/absolute/escape.md", "C:\\escape.md", "\\\\share\\x.md"],
)
def test_escaping_and_absolute_paths_are_rejected(tmp_path: Path, name: str) -> None:
    """Embedded traversal and absolute/drive-qualified paths are all rejected."""
    transport = _folder(tmp_path)
    transport.ensure_layout()
    with pytest.raises(TransportError):
        transport.publish_current({name: b"x"}, manifest={})
    assert not (tmp_path / "escape.md").exists()
    assert not (tmp_path / "Demiurgos" / "escape.md").exists()


def test_no_partial_tree_is_published_on_rejection(tmp_path: Path) -> None:
    """A batch with an unsafe name publishes NOTHING — not even its safe entries."""
    transport = _folder(tmp_path)
    transport.ensure_layout()
    transport.publish_current({"keep/existing.md": b"original"}, manifest={})
    backup_root = tmp_path / "Demiurgos"
    before = _tree_state(backup_root)
    with pytest.raises(TransportError):
        transport.publish_current(
            {"first-safe.md": b"new", "CON": b"bad", "../escape.md": b"escape"},
            manifest={},
        )
    assert _tree_state(backup_root) == before  # byte-identical, no half-tree
    assert not (backup_root / "current" / "first-safe.md").exists()


def test_publish_snapshot_rejects_an_unsafe_id_and_unsafe_entry(tmp_path: Path) -> None:
    """The snapshot id and every staged entry pass the same gate before any write."""
    transport = _folder(tmp_path)
    transport.ensure_layout()
    with pytest.raises(TransportError):
        transport.publish_snapshot("../escape", {"entry.md": b"x"})
    with pytest.raises(TransportError):
        transport.publish_snapshot("2026-09-16T120530Z", {"../escape.md": b"x"})
    snapshots = tmp_path / "Demiurgos" / "snapshots"
    assert list(snapshots.iterdir()) == []  # no partial snapshot dir was left


def test_meta_names_are_validated(tmp_path: Path) -> None:
    """Caller-supplied ``meta/`` names are gated, and safe names still round-trip."""
    transport = _folder(tmp_path)
    transport.ensure_layout()
    with pytest.raises(TransportError):
        transport.write_meta("../escape.json", {"x": 1})
    with pytest.raises(TransportError):
        transport.read_meta("../escape.json")
    with pytest.raises(TransportError):
        transport.write_meta("CON", {"x": 1})
    assert transport.read_meta("manifest.json") is None
    transport.write_meta("manifest.json", {"schema_version": 1})
    assert transport.read_meta("manifest.json") == {"schema_version": 1}
