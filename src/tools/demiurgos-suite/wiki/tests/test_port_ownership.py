# -*- coding: utf-8 -*-
"""ONB-4.6/ONB-5.3 — Port 8000 ownership audit (WU-4d) + retirement (WU-5b).

The audit and its documented resolution live in
`docs/architecture/onboarding-and-configuration.md` (section 13.1): the wiki
API is the canonical owner of port 8000. WU-4d kept the legacy wizard
reference intact; WU-5b (retirement slice) REMOVED it from install.sh. RED
first — these assertions fail until the document records the audit, its
resolution, and the removal.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402  (imported for its side effects: wiki/ on sys.path)

# The audited files are CODE artifacts of the checkout, not author data, so they
# are located from this file — NOT from ``api_server.PROJECT_ROOT``, which is the
# data root since WU-2 (portable-data-root-drive-backup).
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

DOC = REPO_ROOT / "docs" / "architecture" / "onboarding-and-configuration.md"


def test_port_8000_ownership_audit_and_resolution_are_documented():
    text = DOC.read_text(encoding="utf-8")
    # Both servers that can bind 8000 are named in the audit (the conflict).
    assert "api_server.py" in text
    assert "web-config-ui" in text
    assert "8000" in text
    # The resolution names the wiki API as the canonical owner.
    assert "Wiki API" in text
    assert "dueño canónico del puerto 8000" in text


def test_legacy_wizard_reference_removed_at_retirement_slice():
    text = DOC.read_text(encoding="utf-8")
    # The retirement slice (WU-5b) removed the legacy wizard reference from
    # install.sh; the docs record the removal and the wiki API remains the
    # canonical owner of port 8000.
    assert "WU-5" in text
    assert "eliminado en WU-5b" in text
    install = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    assert "web-config-ui" not in install
    assert "uvicorn main:app" not in install
