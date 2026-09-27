"""Neutral Markdown heading helpers shared by the idea bank and materialization.

The server owns the leading H1 of every idea body and every materialized
ficha: the persisted ``title`` must always agree with the body's leading H1.
Both surfaces need the same imposition rule, so it lives here — a
dependency-free module — instead of in ``idea_materialization_domain``, which
``ideas_bank`` must not import (that would be the wrong dependency direction).
"""

from __future__ import annotations

import re

__all__ = ["impose_h1"]

# A standalone Markdown image line: ``![alt](url)`` or ``![alt](url "title")``.
# ``IdeasBank.attach_media`` PREPENDS such an embed to the body, so the heading
# may not be the literal first line; the scan must look past leading embeds.
_IMAGE_LINE = re.compile(r"^!\[[^\]]*\]\([^)]*\)\s*$")


def _is_leading_skippable(line: str) -> bool:
    """True for a blank line or a standalone Markdown image line."""
    return line.strip() == "" or bool(_IMAGE_LINE.match(line))


def impose_h1(body: str, title: str) -> str:
    """Make *title* the body's heading (FT-1 / FT-4).

    Scans from the top, skipping leading lines that are blank or a standalone
    Markdown image line (``![...](...)``, possibly with a title). At the first
    remaining line:

    - an H1 (``# `` prefix) is REPLACED in place with ``# {title}``, leaving
      every other line untouched;
    - otherwise no H1 exists before the first real content, so ``# {title}``
      is inserted at the VERY TOP of the body followed by exactly one blank
      line.

    Only the first H1 is affected; a later H1 is left untouched. When the
    found H1 already equals ``# {title}`` the body is returned byte-identical.
    An empty *body* yields just ``# {title}``.

    *body* is expected already stripped by the caller.
    """
    heading = f"# {title}"
    lines = body.split("\n")
    first_content = -1
    for i, line in enumerate(lines):
        if _is_leading_skippable(line):
            continue
        first_content = i
        break
    if first_content != -1 and lines[first_content].startswith("# "):
        lines[first_content] = heading
        return "\n".join(lines)
    if body:
        return f"{heading}\n\n{body}"
    return heading
