# -*- coding: utf-8 -*-
"""Server-side DOCX export: GFM markdown -> .docx bytes via a pandoc subprocess.

The WikiEditor PDF flow is browser-side (print dialog); DOCX has no browser
equivalent, so the conversion runs on the server: pandoc (``pandoc -f gfm -t
docx``) turns the ficha/idea body into a real OOXML document with embedded
images.

Pipeline contract (ficha-export-pdf-docx):
- The YAML frontmatter is stripped before conversion (body only, mirroring
  the frontend ``splitFrontmatter`` semantics).
- Every inline image is resolved through a caller-supplied ``resolve_image``
  callback. A resolvable image is rewritten to its absolute disk path so
  pandoc embeds it; an unresolvable one is replaced by the spec-mandated
  placeholder ``[imagen no disponible]``.
- MarkdownImage alignment/size suffixes (``#left``, ``#right``, ``#center``,
  ``#sm``, ``#lg`` and combinations) are stripped; the literal suffix never
  leaks into the document.
- Wikilinks (``[[text]]``, ``wiki://slug``) degrade to plain link text.
- pandoc is invoked through ``subprocess.run`` with an args LIST (never
  ``shell=True``), pre-checked with ``shutil.which``, with a 30s timeout.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

#: Spec-mandated placeholder for images that cannot be resolved on disk.
#: Conceptual only — deliberately NOT the frontend ``MarkdownImage`` literal.
IMAGE_PLACEHOLDER = "[imagen no disponible]"

#: pandoc timeout — a stuck conversion must never hang a request forever.
PANDOC_TIMEOUT_SECONDS = 30

# Suffixes parsed by the frontend ``MarkdownImage`` component.
_ALIGN_SUFFIXES = frozenset({"left", "right", "center"})
_SIZE_SUFFIXES = frozenset({"sm", "lg"})

# ``#left`` / ``#right`` / ``#center`` / ``#sm`` / ``#lg`` / ``#sm-lg`` ...
_IMAGE_SUFFIX_RE = re.compile(r"#(?P<suffix>[a-z]+(?:-[a-z]+)*)$")

# Inline image: ![alt](src) — src may be plain (no spaces) or angle-wrapped
# (<path with spaces.png>).
_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?:<(?P<angle>[^>]+)>|(?P<plain>[^)\s]+))\)"
)

# Wikilinks degrade to plain link text (no hyperlink in the DOCX).
_LINKED_WIKI_RE = re.compile(r"\[([^\]]+)\]\((wiki://[^)]+)\)")
_BARE_WIKI_RE = re.compile(r"wiki://([^\s)\]>]+)")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _strip_frontmatter(content: str) -> str:
    """Return *content* with a LEADING YAML frontmatter block removed.

    Mirrors the frontend ``splitFrontmatter`` contract: only a ``---``
    delimited block at position 0 is stripped; the closing delimiter and its
    trailing newline belong to the block, so the body starts on the first
    post-frontmatter line. Content without a leading block is returned as-is.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return content
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            return "".join(lines[i + 1:])
    return content


def _strip_image_suffixes(src: str) -> str:
    """Strip MarkdownImage alignment/size suffixes from an image src.

    ``media/foto.png#left`` -> ``media/foto.png``; ``foto.png#sm-lg`` ->
    ``foto.png``. A trailing ``#``-token that is not a known suffix is left
    untouched. The suffix is always removed, never mapped into the path.
    """
    match = _IMAGE_SUFFIX_RE.search(src)
    if match is None:
        return src
    tokens = match.group("suffix").split("-")
    if not all(t in _ALIGN_SUFFIXES or t in _SIZE_SUFFIXES for t in tokens):
        return src
    return src[: match.start()]


def _degrade_wikilinks(markdown: str) -> str:
    """Degrade ``[[text]]`` and ``wiki://`` links to plain link text."""
    out = _LINKED_WIKI_RE.sub(lambda m: m.group(1), markdown)
    out = _BARE_WIKI_RE.sub(lambda m: m.group(1), out)
    out = _WIKILINK_RE.sub(lambda m: m.group(1), out)
    return out


def _preprocess_markdown(
    markdown: str,
    resolve_image: Callable[[str], Path | None],
) -> str:
    """Rewrite images and degrade wikilinks before pandoc conversion.

    Every inline image is passed through ``resolve_image`` (after suffix
    stripping). A resolved image is rewritten to its absolute disk path —
    angle-wrapped so spaces/unicode survive GFM parsing — and an unresolved
    one is replaced by the ``[imagen no disponible]`` placeholder.
    """

    def _replace_image(match: re.Match[str]) -> str:
        alt = match.group("alt")
        src = match.group("angle") or match.group("plain")
        resolved = resolve_image(_strip_image_suffixes(src))
        if resolved is None:
            return IMAGE_PLACEHOLDER
        return f"![{alt}](<{resolved}>)"

    return _degrade_wikilinks(_IMAGE_RE.sub(_replace_image, markdown))


def _convert_markdown_to_docx(
    markdown: str,
    *,
    resolve_image: Callable[[str], Path | None],
    resource_paths: list[Path] | None = None,
) -> bytes:
    """Convert GFM markdown to DOCX bytes via a pandoc subprocess.

    Image preprocessing contract:
    - For each image in the markdown, call ``resolve_image(src)`` (after
      stripping alignment/size suffixes) to get the disk path.
    - If ``resolve_image`` returns None (unresolvable/missing image), the
      image reference is replaced with the placeholder text
      ``[imagen no disponible]``.
    - Wikilinks (``[[x]]``, ``wiki://``) degrade to plain link text.
    - ``resource_paths`` are passed to pandoc as ``--resource-path`` dirs so
      any remaining relative references still resolve.

    Invokes ``pandoc -f gfm -t docx`` with an args list (never ``shell=True``)
    after a ``shutil.which`` pre-check, with a 30s timeout.

    Raises RuntimeError when pandoc is not installed or the conversion fails.
    """
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc not installed: DOCX conversion unavailable")
    preprocessed = _preprocess_markdown(markdown, resolve_image)
    cmd = ["pandoc", "-f", "gfm", "-t", "docx"]
    for rp in resource_paths or []:
        cmd += ["--resource-path", str(rp)]
    cmd += ["-o", "-"]
    try:
        proc = subprocess.run(
            cmd,
            input=preprocessed.encode("utf-8"),
            capture_output=True,
            timeout=PANDOC_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"pandoc conversion timed out after {PANDOC_TIMEOUT_SECONDS}s"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"pandoc conversion failed to start: {exc}") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"pandoc conversion failed: {stderr or 'unknown error'}"
        )
    return proc.stdout


__all__ = [
    "IMAGE_PLACEHOLDER",
    "PANDOC_TIMEOUT_SECONDS",
    "_convert_markdown_to_docx",
    "_preprocess_markdown",
    "_strip_frontmatter",
    "_strip_image_suffixes",
]