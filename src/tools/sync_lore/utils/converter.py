"""
utils/converter.py — Format converter wrapper for .docx and .pdf.

Uses markitdown (optional dependency) to convert .docx/.pdf to
Markdown intermediate format. Graceful fallback if not installed.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def convert_to_markdown(file_path: Path) -> str | None:
    """
    Convert a .docx or .pdf file to Markdown text using markitdown.

    Args:
        file_path: Path to a .docx or .pdf file.

    Returns:
        Markdown string, or None if conversion is not possible
        (markitdown not installed, or conversion error).

    Raises:
        SystemExit(1): if the file is .docx/.pdf but markitdown is not
                       installed — the user must install it.
    """
    suffix = file_path.suffix.lower()

    if suffix == ".md":
        return file_path.read_text(encoding="utf-8")

    if suffix in (".docx", ".pdf"):
        try:
            from markitdown import MarkItDown
        except ImportError:
            print(
                f"ERROR: markitdown is required to process {suffix} files. "
                f"Install with: pip install markitdown",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            md = MarkItDown()
            result = md.convert(str(file_path))
            return result.text_content
        except Exception as exc:
            logger.warning(
                "Failed to convert %s: %s", file_path.name, exc, exc_info=True)
            return None

    print(
        f"  \u26a0 Unsupported format: {suffix} — skipping {file_path.name}",
        file=sys.stderr,
    )
    return None
