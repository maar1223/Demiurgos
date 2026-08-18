# -*- coding: utf-8 -*-
"""ONB-4.6 — Port 8000 ownership audit (WU-4d).

The audit and its documented resolution live in
`docs/architecture/onboarding-and-configuration.md` (section 13.1): the wiki
API is the canonical owner of port 8000, and the legacy wizard keeps its
current reference until the retirement slice (WU-5). RED first — these
assertions fail until the document records the audit and its resolution.

No scripts or ownership are changed in this slice; this module only inspects
the documentation (the audit is `[ACTUAL]`, the resolution is a documented
decision, and removal is out of scope for WU-4d).
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

import api_server  # noqa: E402

DOC = api_server.PROJECT_ROOT / "docs" / "architecture" / "onboarding-and-configuration.md"


def test_port_8000_ownership_audit_and_resolution_are_documented():
    text = DOC.read_text(encoding="utf-8")
    # Both servers that can bind 8000 are named in the audit (the conflict).
    assert "api_server.py" in text
    assert "web-config-ui" in text
    assert "8000" in text
    # The resolution names the wiki API as the canonical owner.
    assert "Wiki API" in text
    assert "dueño canónico del puerto 8000" in text


def test_legacy_wizard_reference_stays_until_retirement_slice():
    text = DOC.read_text(encoding="utf-8")
    # The legacy wizard reference is documented as retained: removal belongs
    # to the retirement slice (WU-5) and no ownership/script change happened
    # in this slice.
    assert "WU-5" in text
    assert "sin cambios de propiedad" in text