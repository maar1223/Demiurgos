# -*- coding: utf-8 -*-
"""AUD-06: PDF image extraction must be a declared, locked dependency.

``src/tools/sync_lore/image_indexer.py::extract_images_from_pdf`` imports
PyMuPDF (``fitz``) for embedded images. It was undeclared, so a clean install
silently skipped PDF images even though ``docs/install/SUPPORT_MATRIX.md``
promises complete ``.docx``/``.pdf`` import on every supported target.

The fix is the mandatory, hash-locked ``pymupdf`` dependency (the 2.x LLM
plugin subtree is excluded with an upper bound), so the wheel-only closure is
proven for every declared cell by ``scripts/closure_proof.sh`` in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

REQUIREMENTS = _REPO_ROOT / "src" / "tools" / "demiurgos-suite" / "requirements.txt"
OPTIONAL = _REPO_ROOT / "requirements-optional.txt"
LOCK = _REPO_ROOT / "requirements.lock"
INDEXER = _REPO_ROOT / "src" / "tools" / "sync_lore" / "image_indexer.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lock_block() -> str:
    text = _text(LOCK)
    match = re.search(r"^pymupdf==[^\n]*\n(?:    [^\n]*\n)+", text, re.MULTILINE)
    assert match is not None, "requirements.lock has no pymupdf entry"
    return match.group(0)


def test_pymupdf_is_a_mandatory_requirement():
    text = _text(REQUIREMENTS).lower()
    assert "pymupdf" in text
    # The upper bound avoids the 2.x LLM plugin subtree (pymupdf4llm/onnxruntime).
    assert "<1.27" in text


def test_lock_pins_pymupdf_and_carries_hashes():
    block = _lock_block()
    assert "pymupdf==1.26.7" in block
    assert block.count("--hash=sha256:") >= 4
    assert "# via -r src/tools/demiurgos-suite/requirements.txt" in block


def test_pdf_images_are_not_left_to_the_optional_extras():
    # The optional file may mention PyMuPDF only in its explanatory comment;
    # it must not be the installation source for the image dependency.
    optional_lines = [
        line.strip()
        for line in _text(OPTIONAL).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert all("pymupdf" not in line.lower() for line in optional_lines)


def test_indexer_documents_the_mandatory_dependency():
    text = _text(INDEXER)
    assert "PyMuPDF" in text
    assert "mandatory runtime dependency" in text
    assert "import fitz" in text
