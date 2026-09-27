"""tests/test_markdown_heading.py — Unit tests for markdown_heading.impose_h1.

The neutral helper is shared by ``ideas_bank`` (FT-4) and
``idea_materialization_domain`` (FT-1); these tests pin its exact behaviour so
both surfaces delegate to one rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from markdown_heading import impose_h1  # noqa: E402


def test_replaces_existing_leading_h1() -> None:
    assert (
        impose_h1("# Old Title\n\nBody text.", "New Title")
        == "# New Title\n\nBody text."
    )


def test_replaces_existing_leading_h1_only_first_line() -> None:
    body = "# Old Title\n\nBody.\n"
    assert impose_h1(body, "New Title") == "# New Title\n\nBody.\n"


def test_prepends_h1_when_body_has_none() -> None:
    assert (
        impose_h1("Body without a heading.", "New Title")
        == "# New Title\n\nBody without a heading."
    )


def test_leaves_later_h1_untouched() -> None:
    body = "# Old\n\nText.\n\n# Later Heading\n\nMore."
    result = impose_h1(body, "New")
    assert result.startswith("# New\n\nText.")
    assert "# Later Heading\n\nMore." in result
    assert "# Old" not in result


def test_empty_body_yields_only_h1() -> None:
    assert impose_h1("", "New Title") == "# New Title"


def test_body_already_matching_title_is_byte_identical() -> None:
    body = "# New Title\n\nBody."
    assert impose_h1(body, "New Title") == body


def test_hash_without_space_is_not_an_h1() -> None:
    """Detection is ``# `` only (mirrors the materialization rule): ``#Foo``
    is not a leading H1, so the title is prepended and the line survives."""
    result = impose_h1("#Foo\n\nBody.", "New Title")
    assert result == "# New Title\n\n#Foo\n\nBody."


# ---------------------------------------------------------------------------
# Leading media embed (``attach_media`` prepends it) — the user's real shape
# ---------------------------------------------------------------------------


def test_replaces_h1_that_sits_after_a_leading_image_line() -> None:
    """The embed is first, so the H1 is found and replaced IN PLACE (no second
    H1 is introduced and the image stays first)."""
    body = (
        "![idea image](/api/ideas/media/2026-08-28-524e8b9c9770.jpg)\n\n"
        "# Silpah — félido relámpago de Chaae\n\n"
        "## Nombre\n"
    )
    result = impose_h1(body, "Silpah — Lince de Chaae")
    assert result == (
        "![idea image](/api/ideas/media/2026-08-28-524e8b9c9770.jpg)\n\n"
        "# Silpah — Lince de Chaae\n\n"
        "## Nombre\n"
    )
    assert result.count("\n# ") + (1 if result.startswith("# ") else 0) == 1
    assert "félido relámpago" not in result


def test_skips_multiple_leading_image_lines() -> None:
    body = "![a](/x.png)\n![b](/y.png \"title\")\n\n# Old\n\nText."
    result = impose_h1(body, "New")
    assert result == "![a](/x.png)\n![b](/y.png \"title\")\n\n# New\n\nText."


def test_leading_blank_lines_are_skipped_before_the_h1() -> None:
    body = "\n\n# Old\n\nText."
    assert impose_h1(body, "New") == "\n\n# New\n\nText."


def test_byte_identical_when_h1_after_image_already_matches() -> None:
    body = "![img](/i.png)\n\n# New Title\n\nText."
    assert impose_h1(body, "New Title") == body


def test_inserts_at_top_when_only_leading_images_and_no_h1() -> None:
    body = "![img](/i.png)\n\nText."
    assert impose_h1(body, "New Title") == "# New Title\n\n![img](/i.png)\n\nText."

