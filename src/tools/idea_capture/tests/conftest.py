# -*- coding: utf-8 -*-
"""Hermetic data root for the whole idea-capture suite (WU-3, portable-data-root-drive-backup).

Every migrated module resolves author data (``mundos``, ``ideas``, ``data``,
``config``) through :func:`data_root.resolve_data_root`. Without a configured
root that resolver fails loudly BY DESIGN, so the suite exports
``DEMIURGOS_DATA_ROOT`` before any idea-capture module is imported: pytest
loads this ``conftest.py`` ahead of this directory's test modules, so no test
ever resolves against the developer's real data root or against a pointer in
the real user config dir.

Tests that need a specific root (the plugin's yaml capture mode, the smoke
default config) still override ``DEMIURGOS_DATA_ROOT`` per test with
``monkeypatch``; this file is the suite-wide floor, not a replacement for those
seams. ``DEMIURGOS_ROOT`` is no longer read anywhere in the sources, so it
grants nothing here.

The env override is exported at IMPORT time rather than inside the fixture
because pytest imports test modules before fixtures run. The autouse session
fixture owns the directory's lifetime and restores the previous environment
when the session ends.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_TOOLS = _TESTS.parents[1]  # tests/ -> idea_capture/ -> tools/
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

_ENV_VAR = "DEMIURGOS_DATA_ROOT"
_SUBDIRS = ("mundos", "ideas", "data", "config")

_HERMETIC_ROOT = Path(tempfile.mkdtemp(prefix="demiurgos-idea-capture-data-root-"))
for _sub in _SUBDIRS:
    (_HERMETIC_ROOT / _sub).mkdir()
_PREVIOUS_ENV = os.environ.get(_ENV_VAR)
os.environ[_ENV_VAR] = str(_HERMETIC_ROOT)


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
