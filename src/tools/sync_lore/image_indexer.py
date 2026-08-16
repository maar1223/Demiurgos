"""
image_indexer.py — Image extraction and vision analysis pipeline.

Extracts images from .md, .docx, and .pdf files, then processes them
asynchronously through the vision LLM.
"""

from __future__ import annotations

import asyncio
import re
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from .schemas import ImageEntry, ImageRef

if TYPE_CHECKING:
    from .providers.base import ProviderAdapter


# ---------------------------------------------------------------------------
# .md image extraction
# ---------------------------------------------------------------------------

def extract_images_from_md(
    text: str,
    md_dir: Path,
    chunk_ref: str = "",
) -> list[ImageEntry]:
    """
    Extract images referenced in markdown text.

    Matches ![alt](path) and ![alt][ref] patterns.
    Resolves relative paths against md_dir.
    Reads image bytes from disk.

    Args:
        text: Markdown content to scan.
        md_dir: Directory of the .md file (for relative path resolution).
        chunk_ref: Heading path of the associated chunk.

    Returns:
        List of ImageEntry with image_bytes populated.
    """
    entries: list[ImageEntry] = []

    # Pattern 1: ![alt](path)
    for m in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", text):
        alt = m.group(1)
        ref_path = m.group(2)
        image_path = _resolve_path(ref_path, md_dir)
        if image_path and image_path.exists() and image_path.is_file():
            try:
                img_bytes = image_path.read_bytes()
                entries.append(
                    ImageEntry(
                        id=str(uuid.uuid4()),
                        source_file=str(md_dir.name),
                        chunk_ref=chunk_ref,
                        context_text="",  # filled later
                        filename=image_path.name,
                        image_bytes=img_bytes,
                    )
                )
            except Exception as exc:
                print(
                    f"  \u26a0 Failed to read image {image_path}: {exc}",
                    file=sys.stderr,
                )

    # Pattern 2: ![alt][ref]
    for m in re.finditer(r"!\[([^\]]*)\]\[([^\]]*)\]", text):
        alt = m.group(1)
        ref_id = m.group(2)
        # Resolve reference-style: look for [ref_id]: path later in text
        ref_def = re.search(
            rf"^\[{re.escape(ref_id)}\]:\s*(\S+)", text, re.MULTILINE
        )
        if ref_def:
            ref_path = ref_def.group(1)
            image_path = _resolve_path(ref_path, md_dir)
            if image_path and image_path.exists() and image_path.is_file():
                try:
                    img_bytes = image_path.read_bytes()
                    entries.append(
                        ImageEntry(
                            id=str(uuid.uuid4()),
                            source_file=str(md_dir.name),
                            chunk_ref=chunk_ref,
                            context_text="",
                            filename=image_path.name,
                            image_bytes=img_bytes,
                        )
                    )
                except Exception as exc:
                    print(
                        f"  \u26a0 Failed to read image {image_path}: {exc}",
                        file=sys.stderr,
                    )

    return entries


# ---------------------------------------------------------------------------
# .docx image extraction (python-docx — optional)
# ---------------------------------------------------------------------------

def extract_images_from_docx(
    path: Path,
    chunk_ref: str = "",
) -> list[ImageEntry]:
    """
    Extract embedded images from a .docx file.

    Uses python-docx to iterate document relationships and
    extract image blobs. Graceful fallback if not installed.

    Args:
        path: Path to the .docx file.
        chunk_ref: Heading path of the associated chunk.

    Returns:
        List of ImageEntry with image_bytes populated.
    """
    try:
        from docx import Document
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
    except ImportError:
        print(
            "  \u26a0 python-docx not installed — skipping image extraction from .docx",
            file=sys.stderr,
        )
        return []

    entries: list[ImageEntry] = []

    try:
        doc = Document(str(path))
    except Exception as exc:
        print(
            f"  \u26a0 Failed to open .docx {path.name}: {exc}",
            file=sys.stderr,
        )
        return []

    # Iterate document part relationships to find images
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            try:
                image_part = rel.target_part
                img_bytes = image_part.blob
                filename = Path(rel.target_ref).name if rel.target_ref else f"image_{uuid.uuid4().hex[:8]}.png"
                entries.append(
                    ImageEntry(
                        id=str(uuid.uuid4()),
                        source_file=str(path.name),
                        chunk_ref=chunk_ref,
                        context_text="",
                        filename=filename,
                        image_bytes=img_bytes,
                    )
                )
            except Exception as exc:
                print(
                    f"  \u26a0 Failed to extract image from {path.name}: {exc}",
                    file=sys.stderr,
                )

    return entries


# ---------------------------------------------------------------------------
# PDF image extraction (PyMuPDF — optional)
# ---------------------------------------------------------------------------

def extract_images_from_pdf(
    path: Path,
    chunk_ref: str = "",
) -> list[ImageEntry]:
    """
    Extract images from a PDF file, one per page.

    Uses PyMuPDF (fitz) for image extraction.
    Graceful fallback if not installed.

    Args:
        path: Path to the .pdf file.
        chunk_ref: Heading path of the associated chunk.

    Returns:
        List of ImageEntry with image_bytes populated.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print(
            "  \u26a0 PyMuPDF not installed — skipping image extraction from .pdf",
            file=sys.stderr,
        )
        return []

    entries: list[ImageEntry] = []

    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        print(
            f"  \u26a0 Failed to open PDF {path.name}: {exc}",
            file=sys.stderr,
        )
        return []

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images(full=True)

            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    img_bytes = base_image["image"]
                    ext = base_image.get("ext", "png")
                    filename = f"pdf_{page_num+1}_{img_index+1}.{ext}"

                    # Get surrounding text as context (first 500 chars)
                    text_blocks = page.get_text("blocks")
                    context = ""
                    for block in text_blocks:
                        if block[6].strip():  # block[6] is the text
                            context += block[6].strip() + "\n"
                            if len(context) > 500:
                                break

                    entries.append(
                        ImageEntry(
                            id=str(uuid.uuid4()),
                            source_file=str(path.name),
                            page=page_num + 1,
                            chunk_ref=chunk_ref,
                            context_text=context.strip(),
                            filename=filename,
                            image_bytes=img_bytes,
                        )
                    )
                except Exception as exc:
                    print(
                        f"  \u26a0 Failed to extract image {img_index} from "
                        f"page {page_num+1} of {path.name}: {exc}",
                        file=sys.stderr,
                    )
    finally:
        doc.close()

    return entries


# ---------------------------------------------------------------------------
# Cached extraction wrappers (cache-per-file)
# ---------------------------------------------------------------------------

_docx_cache: dict[tuple[str, int], list[ImageEntry]] = {}
_pdf_cache: dict[tuple[str, int], list[ImageEntry]] = {}


def _extract_images_from_docx_cached(fpath: Path) -> list[ImageEntry]:
    """Cached wrapper around extract_images_from_docx.

    Cache key is (resolved_path, st_mtime_ns). Re-opens the ZIP only on
    first access per file, then serves cached ImageEntry objects.
    The image_bytes attribute is shared by reference across copies.
    """
    resolved = fpath.resolve()
    key = (str(resolved), resolved.stat().st_mtime_ns)
    if key not in _docx_cache:
        _docx_cache[key] = extract_images_from_docx(resolved)
    return _docx_cache[key]


def _extract_images_from_pdf_cached(fpath: Path) -> list[ImageEntry]:
    """Cached wrapper around extract_images_from_pdf.

    Same cache-per-file strategy as _extract_images_from_docx_cached.
    """
    resolved = fpath.resolve()
    key = (str(resolved), resolved.stat().st_mtime_ns)
    if key not in _pdf_cache:
        _pdf_cache[key] = extract_images_from_pdf(resolved)
    return _pdf_cache[key]


# ---------------------------------------------------------------------------
# Image processing orchestrator
# ---------------------------------------------------------------------------

def process_images(
    images: list[ImageEntry],
    provider: "ProviderAdapter",
    workers: int = 5,
) -> list[ImageEntry]:
    """
    Synchronous wrapper for async image processing.

    Each image is analyzed via provider.analyze_image() in parallel.

    Args:
        images: List of ImageEntry with image_bytes populated.
        provider: ProviderAdapter instance.
        workers: Max concurrent LLM calls.

    Returns:
        List of ImageEntry with analysis populated (or None on failure).
    """
    from .utils.parallel import process_images_async
    return asyncio.run(process_images_async(images, provider, workers))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_path(ref: str, base_dir: Path) -> Path | None:
    """Resolve a relative path against base_dir. Skip web URLs."""
    if ref.startswith(("http://", "https://", "data:")):
        return None
    candidate = base_dir / ref
    return candidate
