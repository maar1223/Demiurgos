# -*- coding: utf-8 -*-
"""Hermetic data root for the whole wiki suite (WU-2, portable-data-root-drive-backup).

Every migrated module resolves author data (``mundos``, ``ideas``, ``data``,
``config``) through :func:`data_root.resolve_data_root`. Without a configured
root that resolver fails loudly BY DESIGN, so the suite exports
``DEMIURGOS_DATA_ROOT`` before any wiki module is imported: pytest loads this
``conftest.py`` ahead of the test modules of this directory, so no module is
ever collected against the developer's real data root or against a pointer in
the real user config dir.

The env override is exported at IMPORT time rather than inside the fixture
because a few pre-existing module-level bindings resolve their default path
while their module is imported (the durable session stores in
``api_server``). The autouse session fixture owns the directory's lifetime and
restores the previous environment when the session ends.
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

_ENV_VAR = "DEMIURGOS_DATA_ROOT"
_SUBDIRS = ("mundos", "ideas", "data", "config")

_HERMETIC_ROOT = Path(tempfile.mkdtemp(prefix="demiurgos-test-data-root-"))
for _sub in _SUBDIRS:
    (_HERMETIC_ROOT / _sub).mkdir()
_PREVIOUS_ENV = os.environ.get(_ENV_VAR)
os.environ[_ENV_VAR] = str(_HERMETIC_ROOT)

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
