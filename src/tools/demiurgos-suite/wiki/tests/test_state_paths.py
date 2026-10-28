# -*- coding: utf-8 -*-
"""State-directory resolution — policy (ii) over the two roots.

Covers ``state_paths.resolve_state_dir``: the legacy ``<data root>/data`` wins
only while it holds our state AND the adoption has not completed, a fresh
install goes straight to ``<state root>/data``, a missing content root is not an
error, and the function never writes or caches.

Every test uses ``tmp_path`` for both roots and injects the seams
(``environ``/``state_dir``/``config_dir``), so nothing touches the developer's
real data root, state root or config dir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import data_root  # noqa: E402
import state_paths  # noqa: E402
import state_root_migration as srm  # noqa: E402


class Roots:
    """The two injected bases plus the seams that make the decision hermetic."""

    def __init__(self, tmp_path: Path) -> None:
        self.content = tmp_path / "content"
        self.state = tmp_path / "state"
        self.config = tmp_path / "config"
        self.content.mkdir()
        self.state.mkdir()
        self.config.mkdir()
        self.environ = {"DEMIURGOS_DATA_ROOT": str(self.content)}

    @property
    def legacy(self) -> Path:
        return self.content / srm.STATE_DIR_NAME

    @property
    def current(self) -> Path:
        return self.state / srm.STATE_DIR_NAME

    def resolve(self, **overrides) -> Path:
        kwargs = {
            "environ": self.environ,
            "state_dir": self.state,
            "config_dir": self.config,
        }
        kwargs.update(overrides)
        return state_paths.resolve_state_dir(**kwargs)

    def seed_legacy(self, *names: str) -> Path:
        self.legacy.mkdir(parents=True, exist_ok=True)
        for name in names:
            target = self.legacy / name
            if target.suffix in {".sqlite3", ".json"}:
                target.write_bytes(b"{}\n")
            else:
                target.mkdir(parents=True, exist_ok=True)
        return self.legacy

    def mark_adopted(self) -> None:
        self.current.mkdir(parents=True, exist_ok=True)
        (self.current / srm.COMPLETE_MARKER).write_text("{}\n", encoding="utf-8")


def test_a_fresh_install_uses_the_state_root(tmp_path: Path):
    roots = Roots(tmp_path)

    assert roots.resolve() == roots.current
    assert not roots.legacy.exists()


def test_a_legacy_state_tree_is_preferred_until_adoption_completes(tmp_path: Path):
    roots = Roots(tmp_path)
    roots.seed_legacy("idea-capture.sqlite3")

    assert roots.resolve() == roots.legacy


def test_the_auth_session_registry_alone_marks_a_legacy_tree(tmp_path: Path):
    """S7: ``sessions.json`` is machine state, so it must be adopted too."""
    roots = Roots(tmp_path)
    roots.seed_legacy("sessions.json")

    assert roots.resolve() == roots.legacy


def test_the_import_spool_alone_marks_a_legacy_tree(tmp_path: Path):
    """S7: an in-flight upload spool must not stay in the synced folder."""
    roots = Roots(tmp_path)
    roots.seed_legacy("import-spool")

    assert roots.resolve() == roots.legacy


def test_author_content_under_data_is_not_a_legacy_state_tree(tmp_path: Path):
    """``methodology/`` and ``world-aliases.json`` are content, never state."""
    roots = Roots(tmp_path)
    roots.seed_legacy("methodology", "world-aliases.json")

    assert roots.resolve() == roots.current


def test_the_adoption_marker_switches_everything_to_the_state_root(tmp_path: Path):
    roots = Roots(tmp_path)
    roots.seed_legacy("idea-capture.sqlite3")
    roots.mark_adopted()

    assert roots.resolve() == roots.current


def test_a_marker_without_a_legacy_tree_is_still_the_state_root(tmp_path: Path):
    roots = Roots(tmp_path)
    roots.mark_adopted()

    assert roots.resolve() == roots.current


def test_no_configured_content_root_falls_back_to_the_state_root(tmp_path: Path):
    """State is machine-local: a missing content root is not an error here."""
    roots = Roots(tmp_path)

    resolved = roots.resolve(environ={})

    assert resolved == roots.current


def test_the_state_env_override_wins_for_the_new_side(tmp_path: Path):
    roots = Roots(tmp_path)
    alternate = tmp_path / "alternate-state"
    roots.environ["DEMIURGOS_STATE_ROOT"] = str(alternate)

    assert roots.resolve() == alternate / srm.STATE_DIR_NAME


def test_the_decision_is_not_cached_within_one_process(tmp_path: Path):
    """The boot-time adoption must flip the answer for later calls (S4)."""
    roots = Roots(tmp_path)
    roots.seed_legacy("guided-sessions.sqlite3")
    assert roots.resolve() == roots.legacy

    roots.mark_adopted()

    assert roots.resolve() == roots.current


def test_resolution_writes_nothing(tmp_path: Path):
    roots = Roots(tmp_path)
    roots.seed_legacy("local-state.json")
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    roots.resolve()
    roots.resolve(environ={})

    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert after == before


def test_the_result_is_always_a_data_directory(tmp_path: Path):
    roots = Roots(tmp_path)
    roots.seed_legacy("world-trash")

    for resolved in (roots.resolve(), roots.resolve(environ={})):
        assert resolved.name == srm.STATE_DIR_NAME


def test_the_layer_and_the_adoption_agree_on_what_state_is(tmp_path: Path):
    """One tuple decides both, so a legacy tree is never 'not ours' for one side."""
    roots = Roots(tmp_path)
    roots.seed_legacy("conversation-memory.sqlite3")

    assert state_paths.holds_state(roots.legacy) is True
    result = srm.adopt_existing_state(
        data_root=roots.content, state_root=roots.state
    )

    assert result.reason != "no_source"
    assert (roots.current / srm.COMPLETE_MARKER).is_file()
    assert roots.resolve() == roots.current


def test_the_pure_resolvers_keep_their_contract(tmp_path: Path):
    """The layer combines the resolvers; neither of them may start guessing."""
    roots = Roots(tmp_path)
    roots.seed_legacy("idea-capture.sqlite3")

    # resolve_state_root still ignores the filesystem and never reads the pointer.
    assert data_root.resolve_state_root(
        environ={}, state_dir=roots.state
    ) == roots.state
    with pytest.raises(data_root.DataRootNotConfigured):
        data_root.resolve_data_root(environ={}, config_dir=roots.config)


def test_the_base_is_the_state_directorys_parent_in_both_branches(tmp_path: Path):
    """Consumers that resolve their own layout (the SQLite cut) need the BASE."""
    roots = Roots(tmp_path)
    roots.seed_legacy("idea-capture.sqlite3")

    assert state_paths.resolve_state_base(
        environ=roots.environ, state_dir=roots.state, config_dir=roots.config
    ) == roots.legacy.parent

    roots.mark_adopted()

    assert state_paths.resolve_state_base(
        environ=roots.environ, state_dir=roots.state, config_dir=roots.config
    ) == roots.current.parent


def test_the_base_honours_the_same_seams(tmp_path: Path):
    roots = Roots(tmp_path)
    alternate = tmp_path / "alternate-state"
    roots.environ["DEMIURGOS_STATE_ROOT"] = str(alternate)

    assert state_paths.resolve_state_base(
        environ=roots.environ, config_dir=roots.config
    ) == alternate


def test_a_content_root_that_is_the_state_base_is_safe(tmp_path: Path):
    """Windows today: the default install root IS the platform data dir.

    Both sides then resolve to the same directory, so the split is inert until
    the content root moves: the layer must return it (never invent a second
    location) and the adoption must be a no-op — no copy, no marker, no damage.
    """
    shared = tmp_path / "Demiurgos"
    legacy = shared / srm.STATE_DIR_NAME
    legacy.mkdir(parents=True)
    (legacy / "idea-capture.sqlite3").write_bytes(b"live")

    resolved = state_paths.resolve_state_dir(
        environ={"DEMIURGOS_DATA_ROOT": str(legacy)},
        state_dir=shared,
        config_dir=tmp_path / "config",
    )

    assert resolved == legacy
    result = srm.adopt_existing_state(data_root=legacy, state_root=shared)
    assert (result.adopted, result.reason) == (False, "already_present")
    assert (legacy / "idea-capture.sqlite3").read_bytes() == b"live"
    assert not (legacy / srm.COMPLETE_MARKER).exists()


def test_a_content_root_named_like_the_state_root_is_still_one_tree(tmp_path: Path):
    """Same shape as the case-insensitive Windows path, spelled identically."""
    shared = tmp_path / "Demiurgos"
    (shared / srm.STATE_DIR_NAME).mkdir(parents=True)
    (shared / srm.STATE_DIR_NAME / "sessions.json").write_text("{}", encoding="utf-8")

    assert state_paths.resolve_state_dir(
        environ={"DEMIURGOS_DATA_ROOT": str(shared)},
        state_dir=shared,
        config_dir=tmp_path / "config",
    ) == shared / srm.STATE_DIR_NAME
