# -*- coding: utf-8 -*-
"""Hermetic data and state roots for the whole wiki suite (WU-2).

Every migrated module resolves author data (``mundos``, ``ideas``, ``data``,
``config``) through :func:`data_root.resolve_data_root` and machine state (the
SQLite stores, the recycle bin, migration evidence, ``local-state.json``) through
:func:`state_paths.resolve_state_dir`. Without a configured root the data
resolver fails loudly BY DESIGN, so the suite exports ``DEMIURGOS_DATA_ROOT``
before any wiki module is imported: pytest loads this ``conftest.py`` ahead of
the test modules of this directory, so no module is ever collected against the
developer's real data root or against a pointer in the real user config dir.

``DEMIURGOS_STATE_ROOT`` is exported for the same reason: the state resolver
never raises and defaults to the real ``platformdirs`` user data dir, so without
the override a test that opens a store with no explicit ``db_path`` would write
into the developer's real state directory. The state root is exported EMPTY (no
``data/`` inside) so a fresh-install test sees exactly what a new installation
sees.

Both env overrides are exported at IMPORT time rather than inside a fixture
because a few pre-existing module-level bindings resolve their default path
while their module is imported (the durable session stores in ``api_server``).
The autouse session fixtures own the directories' lifetime and restore the
previous environment when the session ends.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parent.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

# The shared live-probe helper lives in this tests/ dir (not a package, no
# __init__.py). Insert the dir explicitly so ``import hermes_probe_support`` is
# stable regardless of pytest rootdir/import-mode (WU-2, REQ-LPH-5).
_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

_ENV_VAR = "DEMIURGOS_DATA_ROOT"
_SUBDIRS = ("mundos", "ideas", "data", "config")

_HERMETIC_ROOT = Path(tempfile.mkdtemp(prefix="demiurgos-test-data-root-"))
for _sub in _SUBDIRS:
    (_HERMETIC_ROOT / _sub).mkdir()
_PREVIOUS_ENV = os.environ.get(_ENV_VAR)
os.environ[_ENV_VAR] = str(_HERMETIC_ROOT)

# State root isolation (2b): empty on purpose — no ``data/`` inside, so the
# default state decision is exactly the one a fresh installation makes.
_STATE_ENV_VAR = "DEMIURGOS_STATE_ROOT"
_HERMETIC_STATE_ROOT = Path(tempfile.mkdtemp(prefix="demiurgos-test-state-root-"))
_PREVIOUS_STATE_ENV = os.environ.get(_STATE_ENV_VAR)
os.environ[_STATE_ENV_VAR] = str(_HERMETIC_STATE_ROOT)

# S1 static serving isolation (S1-4): the working tree contains a gitignored
# ``frontend/dist`` that would make the catch-all serve a stale bundle during
# unrelated tests. Point ``DEMIURGOS_FRONTEND_DIST`` at a NONEXISTENT path so
# the catch-all stays inert (503) for the general suite; static-serving tests
# override the env per test with their own ``tmp_path`` fixture.
_DIST_ENV_VAR = "DEMIURGOS_FRONTEND_DIST"
_HERMETIC_DIST = Path(tempfile.mkdtemp(prefix="demiurgos-test-dist-")) / "dist"
_PREVIOUS_DIST_ENV = os.environ.get(_DIST_ENV_VAR)
os.environ[_DIST_ENV_VAR] = str(_HERMETIC_DIST)


@pytest.fixture(scope="session", autouse=True)
def hermetic_data_root() -> Path:
    """The suite's data root: throwaway, never the developer's.

    Asserted rather than merely yielded so a test that mutates the variable
    mid-session fails loudly instead of silently falling back to the real root.
    """
    assert os.environ.get(_ENV_VAR) == str(_HERMETIC_ROOT)
    yield _HERMETIC_ROOT
    shutil.rmtree(_HERMETIC_ROOT, ignore_errors=True)
    if _PREVIOUS_ENV is None:
        os.environ.pop(_ENV_VAR, None)
    else:
        os.environ[_ENV_VAR] = _PREVIOUS_ENV


@pytest.fixture(scope="session", autouse=True)
def hermetic_state_root() -> Path:
    """The suite's state root: throwaway, empty, never the developer's.

    Asserted rather than merely yielded, for the same reason as the data root:
    a test that mutates the variable mid-session must fail loudly instead of
    silently opening the developer's real machine-state directory.
    """
    assert os.environ.get(_STATE_ENV_VAR) == str(_HERMETIC_STATE_ROOT)
    yield _HERMETIC_STATE_ROOT
    shutil.rmtree(_HERMETIC_STATE_ROOT, ignore_errors=True)
    if _PREVIOUS_STATE_ENV is None:
        os.environ.pop(_STATE_ENV_VAR, None)
    else:
        os.environ[_STATE_ENV_VAR] = _PREVIOUS_STATE_ENV


@pytest.fixture(scope="session", autouse=True)
def hermetic_frontend_dist() -> Path:
    """The suite's frontend dist pointer: nonexistent, never the working tree's.

    ``api_server._frontend_dist()`` reads the env at request time, so this
    single session-scoped pointer keeps the S1 catch-all inert for every test
    that does not opt into a real dist fixture.
    """
    assert os.environ.get(_DIST_ENV_VAR) == str(_HERMETIC_DIST)
    yield _HERMETIC_DIST
    shutil.rmtree(_HERMETIC_DIST.parent, ignore_errors=True)
    if _PREVIOUS_DIST_ENV is None:
        os.environ.pop(_DIST_ENV_VAR, None)
    else:
        os.environ[_DIST_ENV_VAR] = _PREVIOUS_DIST_ENV
