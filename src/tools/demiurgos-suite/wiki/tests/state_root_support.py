# -*- coding: utf-8 -*-
"""Test support: where machine STATE lives while a test runs (2b).

Machine state (``local-state.json``, ``sessions.json``, the SQLite stores, the
recycle bin, migration evidence, the import spool) no longer lives under the
data root: it resolves through ``state_paths.resolve_state_dir``, and the
autouse ``isolated_state_root`` fixture in ``conftest.py`` points
``DEMIURGOS_STATE_ROOT`` at a per-test throwaway directory.

Tests that need to seed or inspect a state file ask here instead of hardcoding
the layout, so the migration's single source of truth stays in ``state_paths``
and the fixture stays free to change where it parks the directory.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_ENV_VAR = "DEMIURGOS_STATE_ROOT"

#: Directory name the state layer appends to whichever base wins (policy (ii)).
STATE_DIR_NAME = "data"


def state_dir() -> Path:
    """``<state root>/data`` for the running test."""
    return Path(os.environ[STATE_ENV_VAR]) / STATE_DIR_NAME


def state_file(name: str) -> Path:
    """A named state artifact inside the running test's state directory."""
    return state_dir() / name
