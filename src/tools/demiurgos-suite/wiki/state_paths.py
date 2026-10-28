# -*- coding: utf-8 -*-
"""State directory — WHERE machine state lives, decided by policy (ii).

:mod:`data_root` owns two *pure* resolvers and neither of them may guess from the
filesystem: ``resolve_data_root`` names the author CONTENT folder, and
``resolve_state_root`` names the machine-local base for state. This module is the
one place that combines them into the decision every state consumer makes, so no
consumer re-implements it and the resolvers stay honest.

**Policy (ii)**, the approved product decision: a consumer keeps using the
legacy ``<data root>/data`` while that tree still holds our state AND the
adoption has not completed; once the adoption has completed, everything goes to
``<state root>/data``. In one table, where *legacy* is ``<data root>/data`` and
*current* is ``<state root>/data``:

===========================================  ===========================
situation                                    :func:`resolve_state_dir`
===========================================  ===========================
``current/.adoption-complete`` exists        ``current`` (adopted)
no marker, ``legacy`` holds a state artifact ``legacy`` (adoption pending)
no marker, ``legacy`` has no state artifact  ``current`` (fresh install)
no data root configured                      ``current``
===========================================  ===========================

Why the marker and not "the target exists": :func:`state_root_migration.
adopt_existing_state` publishes the copy with ONE ``os.replace`` of a staged
tree that carries the marker, so the marker's presence is the proof that
``current`` is a complete copy. Two processes booting at once may both stage,
but only one publishes; the loser then sees the winner's marker and follows it,
so both end up on the same tree instead of writing two.

Why ``legacy`` must still hold an artifact: a content root whose ``data/`` holds
only author content (``methodology/``, ``world-aliases.json``) is not a legacy
state tree, and treating it as one would point state at the author's synced
folder forever on a fresh install.

**Nothing is cached and nothing is created.** The answer is derived on every
call: a boot-time adoption in this same process must flip it, and a test that
relocates either root must win immediately. The function performs no write, no
``mkdir`` and no cleanup — a caller that needs a directory creates it, exactly as
the stores already do.

**A data root that cannot be resolved is not an error here.** Machine state is
machine-local; when no content root is configured there is no legacy tree to
prefer, so the state base is used. That is a behaviour change from a consumer
calling ``resolve_data_root()`` directly (which raises): state no longer depends
on the author having configured a content folder.

Content does NOT move: ``mundos``, ``ideas``, ``plantillas``, ``config``, ``.env``,
``methodology/`` (including ``methodology/attachments``) and
``world-aliases.json`` keep resolving from :func:`data_root.resolve_data_root`.
Only the state artifacts that need locks, WAL or secrets (the SQLite stores,
``world-trash``, ``migration-evidence``, ``local-state.json``, ``sessions.json``
and ``import-spool``) come from here.

**Injection seams**: ``environ``, ``state_dir`` and ``config_dir`` are forwarded
to the two resolvers, so tests are hermetic without touching the real process
environment, the real user config dir or the real user state dir.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

try:  # imported as ``wiki.state_paths`` (package) …
    from . import data_root, state_root_migration
except ImportError:  # … or as a top-level module (the suite puts the wiki dir on sys.path)
    import data_root
    import state_root_migration

#: Directory name under whichever base wins the decision (``data`` on both
#: sides). Kept as an alias of the migration's name so a change lands in one place.
STATE_DIR_NAME = state_root_migration.STATE_DIR_NAME


def _content_root(
    *, environ: Mapping[str, str] | None, config_dir: Path | None
) -> Path | None:
    """The content root, or ``None`` when the author has not configured one."""
    try:
        return data_root.resolve_data_root(environ=environ, config_dir=config_dir)
    except data_root.DataRootNotConfigured:
        return None


def _adoption_completed(current: Path) -> bool:
    """Whether *current* is a published, complete adoption target."""
    return (current / state_root_migration.COMPLETE_MARKER).is_file()


def holds_state(legacy: Path) -> bool:
    """Whether *legacy* is a Demiurgos state tree (any known artifact inside).

    The same membership test :func:`state_root_migration.adopt_existing_state`
    uses to decide that a source is ours, so the layer and the adoption can
    never disagree about whether an existing tree still needs migrating.
    """
    directory = Path(legacy)
    if not directory.is_dir():
        return False
    return any(
        (directory / name).exists()
        for name in state_root_migration.STATE_ARTIFACTS
    )


def resolve_state_dir(
    *,
    environ: Mapping[str, str] | None = None,
    state_dir: Path | None = None,
    config_dir: Path | None = None,
) -> Path:
    """The directory that holds machine state, per policy (ii).

    ``environ`` defaults to ``os.environ``; ``state_dir`` and ``config_dir`` are
    the injection seams of the two resolvers. Read the module docstring for the
    full decision table. This function never raises for a missing content root,
    never writes and never guesses beyond that table.
    """
    current = (
        data_root.resolve_state_root(environ=environ, state_dir=state_dir)
        / STATE_DIR_NAME
    )
    content_root = _content_root(environ=environ, config_dir=config_dir)
    if content_root is None:
        return current
    legacy = content_root / STATE_DIR_NAME
    if _adoption_completed(current):
        return current
    if holds_state(legacy):
        return legacy
    return current
