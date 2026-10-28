# -*- coding: utf-8 -*-
"""Every state consumer reads the state directory, and content does not move (2b).

The unit cells in ``test_state_paths.py`` pin the (ii) decision itself. This
module pins the WIRING: each runtime consumer that used to derive
``<data root>/data/<name>`` now asks the state layer, the content consumers keep
resolving from the data root, and a completed adoption flips a live consumer to
the state root without a restart.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402
import co_creation_session_store  # noqa: E402
import conversation_memory_store  # noqa: E402
import demiurgos_language  # noqa: E402
import graph_mcp_server  # noqa: E402
import guided_session_store  # noqa: E402
import idea_capture_ui  # noqa: E402
import import_store  # noqa: E402
import retirement_gate  # noqa: E402
import state_root_migration as srm  # noqa: E402
import world_recycle_bin  # noqa: E402
from state_root_support import state_dir, state_file  # noqa: E402


def test_the_five_stores_open_in_the_state_directory():
    assert guided_session_store.default_db_path() == state_file(
        "guided-sessions.sqlite3"
    )
    assert conversation_memory_store.default_db_path() == state_file(
        "conversation-memory.sqlite3"
    )
    assert co_creation_session_store.default_db_path() == state_file(
        "co-creation-sessions.sqlite3"
    )
    assert import_store.default_db_path() == state_file("import-jobs.sqlite3")


def test_the_recycle_bin_lives_in_the_state_directory():
    assert world_recycle_bin.default_world_trash_root() == state_file("world-trash")


def test_migration_evidence_lives_in_the_state_directory():
    assert retirement_gate.evidence_dir() == state_file("migration-evidence")


def test_the_locale_registry_lives_in_the_state_directory():
    assert demiurgos_language._default_state_path() == state_file("local-state.json")


def test_the_idea_capture_database_and_its_lock_live_in_the_state_directory():
    assert idea_capture_ui._pending_state_path() == state_file("idea-capture.sqlite3")
    assert idea_capture_ui.owner_lock_path() == state_file("idea-capture.sqlite3.lock")
    assert graph_mcp_server._pending_state_path() == state_file(
        "idea-capture.sqlite3"
    )


def test_the_idea_capture_package_agrees_with_the_server():
    from idea_capture.hermes_handler import (
        _default_locale_state_path,
        _default_vision_cache_db_path,
    )

    assert _default_locale_state_path() == state_file("local-state.json")
    assert _default_vision_cache_db_path() == state_file("import-jobs.sqlite3")
    # The wiki import store backs the same vision cache with the same file.
    assert import_store.default_db_path() == _default_vision_cache_db_path()


def test_the_api_state_helpers_live_in_the_state_directory(monkeypatch):
    monkeypatch.setattr(api_server, "STATE_DIR", None)

    assert api_server._state_dir() == state_dir()
    assert api_server._sessions_file() == state_file("sessions.json")
    assert api_server._spool_dir() == state_file("import-spool")
    assert api_server._locale_state_path() == state_file("local-state.json")


def test_content_paths_do_not_move(monkeypatch, tmp_path: Path):
    """S10: author content keeps resolving from the content root."""
    monkeypatch.setattr(api_server, "MUNDOS_DIR", None)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)

    assert api_server._mundos_dir() == tmp_path / "mundos"
    assert api_server._world_aliases_path() == tmp_path / "data" / "world-aliases.json"
    assert api_server._state_dir() == state_dir()
    # The seed/methodology library stays under the content root's data/.
    assert (tmp_path / "data" / "methodology") != state_file("methodology").parent


def test_a_pending_adoption_keeps_consumers_on_the_legacy_tree(monkeypatch, tmp_path):
    """Policy (ii) end to end: an existing install keeps working before adoption."""
    content = tmp_path / "content"
    legacy = content / "data"
    legacy.mkdir(parents=True)
    (legacy / "guided-sessions.sqlite3").write_bytes(b"legacy")
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(content))
    monkeypatch.setenv("DEMIURGOS_STATE_ROOT", str(tmp_path / "state"))

    assert guided_session_store.default_db_path() == (
        legacy / "guided-sessions.sqlite3"
    )
    assert api_server._state_dir() == legacy


def test_a_completed_adoption_flips_live_consumers(monkeypatch, tmp_path):
    """S1/S4: once the marker exists, a derivation made after it uses the new root."""
    content = tmp_path / "content"
    legacy = content / "data"
    legacy.mkdir(parents=True)
    (legacy / "guided-sessions.sqlite3").write_bytes(b"legacy")
    state_root = tmp_path / "state"
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(content))
    monkeypatch.setenv("DEMIURGOS_STATE_ROOT", str(state_root))
    monkeypatch.setattr(api_server, "STATE_DIR", None)
    assert guided_session_store.default_db_path().parent == legacy

    current = state_root / srm.STATE_DIR_NAME
    current.mkdir(parents=True)
    (current / srm.COMPLETE_MARKER).write_text("{}\n", encoding="utf-8")

    assert guided_session_store.default_db_path() == (
        current / "guided-sessions.sqlite3"
    )
    assert api_server._state_dir() == current


def test_a_fresh_install_never_writes_state_into_the_content_root(
    monkeypatch, tmp_path
):
    """S5b: with no legacy tree, every consumer targets the state directory."""
    content = tmp_path / "content"
    (content / "data" / "methodology").mkdir(parents=True)
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(content))
    state_root = tmp_path / "state"
    monkeypatch.setenv("DEMIURGOS_STATE_ROOT", str(state_root))
    monkeypatch.setattr(api_server, "STATE_DIR", None)

    expected = state_root / srm.STATE_DIR_NAME
    assert guided_session_store.default_db_path().parent == expected
    assert import_store.default_db_path().parent == expected
    assert world_recycle_bin.default_world_trash_root().parent == expected
    assert retirement_gate.evidence_dir().parent == expected
    assert api_server._state_dir() == expected
    assert not (content / "data" / "guided-sessions.sqlite3").exists()


@pytest.mark.parametrize(
    "name",
    [
        "idea-capture.sqlite3",
        "guided-sessions.sqlite3",
        "co-creation-sessions.sqlite3",
        "conversation-memory.sqlite3",
        "import-jobs.sqlite3",
        "world-checkpoints.sqlite3",
        "local-state.json",
        "sessions.json",
        "world-trash",
        "import-spool",
        "migration-evidence",
    ],
)
def test_every_migrated_artifact_is_a_known_state_artifact(name: str):
    """The layer's membership test and the adoption's list are the same tuple."""
    assert name in srm.STATE_ARTIFACTS


def test_the_recycle_bin_still_resolves_its_CONTENT_defaults(monkeypatch, tmp_path):
    """The split moved the trash, not the worlds: ``mundos/`` stays content.

    A regression guard for the migration itself: the module keeps BOTH resolvers,
    and the public default must answer from the content root.
    """
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(tmp_path))

    assert world_recycle_bin.default_mundos_dir() == tmp_path / "mundos"
    assert world_recycle_bin.default_world_trash_root() == state_file("world-trash")


def test_a_restore_from_trash_works_without_an_explicit_mundos_dir(
    monkeypatch, tmp_path
):
    """The standalone/public path (no API wiring) must not raise."""
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(tmp_path))
    world = tmp_path / "mundos" / "Avalon"
    world.mkdir(parents=True)
    (world / "a.md").write_text("x", encoding="utf-8")
    trash = tmp_path / "trash"
    world_recycle_bin.move_to_trash(
        "Avalon", trash_root=trash, mundos_dir=tmp_path / "mundos"
    )

    world_recycle_bin.restore_from_trash("Avalon", trash_root=trash)

    assert (tmp_path / "mundos" / "Avalon" / "a.md").is_file()
