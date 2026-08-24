"""World importer — Notion Markdown & CSV ZIP adapter (read-only).

Phase 1 recognizes a Notion export from an already-extracted archive root by
scanning for Markdown pages (``.md``) and flat CSV databases (``.csv``) — the
two content shapes a real Notion export contains.

Phase 2 adds the deterministic conversion layer on top of that recognition:

- ``_build_rename_map`` gives UUID-like pages readable, deterministic names
  derived from their first ``#`` heading (via Unicode slugification) and
  produces an old-to-new path map; missing/empty headings or slug collisions
  fall back to a safe filename or a deterministic suffix with a warning.
- ``_rewrite_references`` rewrites unambiguous relative ``.md`` links and
  ``[[wikilinks]]`` using that map, preserving unresolved references with a
  warning (never silently breaking them).
- ``_hash_media_streaming`` hashes every referenced media file with a 64 KiB
  streaming SHA-256 and deduplicates equal bytes into one ``MediaAsset``
  while keeping every source path in ``references``.
- ``convert_csv_to_fichas`` streams flat CSV databases row by row
  (``utf-8-sig``), maps ``Name``/``Tags``/``Status`` to OKF frontmatter,
  retains unmapped columns under ``properties``, and diagnoses
  malformed/nameless rows with warnings instead of silently losing them.
- ``analyze_export`` orchestrates all of the above and delegates each
  Markdown/CSV body to ``import_analysis.analyze_markdown`` so candidates
  reuse the shared analysis contract.

Nothing here writes to canon; analysis is read-only and fail-open (warnings
rather than silent loss).
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from import_analysis import AnalysisReport, analyze_markdown
from import_models import MediaAsset, NotionAnalysis

# Suffixes identifying a Notion export's content shapes.
_MARKDOWN_SUFFIX = ".md"
_CSV_SUFFIX = ".csv"

# Streaming chunk size for hashing media (64 KiB matches the intake posture,
# so 100 MB+ workspaces never enter a single in-memory buffer).
_HASH_CHUNK = 64 * 1024

_RE_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_RE_IMAGE_REF = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_RE_MD_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")
_RE_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# CSV columns that map to OKF frontmatter. The first present header wins.
_NAME_COLUMNS = ("name", "nombre", "title")
_TAGS_COLUMNS = ("tags", "etiquetas")
_STATUS_COLUMNS = ("status", "estado")
_TYPE_COLUMNS = ("type", "tipo")

# Unsupported Notion export formats / artifacts that the importer deliberately
# does NOT interpret. HTML exports and Notion API/JSON export metadata are not
# OKF content; OS/Notion sync artifacts are not part of eligible flat content.
# Detecting these lets the adapter report them as out of scope instead of
# silently ignoring complex database behavior (per spec requirement 4).
_OUT_OF_SCOPE_HTML_SUFFIXES = (".html", ".htm")
_OUT_OF_SCOPE_API_SUFFIXES = (".json",)
_OUT_OF_SCOPE_SYNC_NAMES = {".DS_Store", "Thumbs.db", ".notion", "Icon\r"}


@dataclass(frozen=True)
class NotionManifest:
    """Recognition result for a Notion Markdown & CSV export.

    ``root`` is the extracted archive directory; ``markdown_files`` and
    ``csv_files`` are the POSIX-relative paths (sorted, deterministic) of
    every page/database found under it.
    """

    root: Path
    markdown_files: tuple[str, ...] = ()
    csv_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class CsvFicha:
    """A flat CSV row converted to a virtual OKF Markdown source.

    ``identity`` is the new POSIX-relative ``.md`` path; ``markdown`` is the
    generated frontmatter + body that ``analyze_export`` feeds through
    ``analyze_markdown`` exactly like a real page.
    """

    identity: str
    markdown: str


def recognize_notion_zip(root: Path) -> NotionManifest | None:
    """Recognize a Notion Markdown & CSV ZIP export inside *root*.

    Scans *root* recursively in deterministic sorted order for ``.md`` pages
    and ``.csv`` databases. Returns a ``NotionManifest`` when at least one
    such file exists, otherwise ``None``. Never mutates *root*.
    """
    root = Path(root)
    if not root.is_dir():
        return None

    markdown_files: list[str] = []
    csv_files: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue  # not expressible relative to root — skip defensively
        suffix = path.suffix.lower()
        if suffix == _MARKDOWN_SUFFIX:
            markdown_files.append(relative)
        elif suffix == _CSV_SUFFIX:
            csv_files.append(relative)

    if not markdown_files and not csv_files:
        return None
    return NotionManifest(
        root=root,
        markdown_files=tuple(markdown_files),
        csv_files=tuple(csv_files),
    )


def detect_out_of_scope_features(root: Path,
                                 manifest: NotionManifest) -> list[str]:
    """Report complex/unsupported Notion features as explicitly out of scope.

    Scans the extracted export tree (plus the recognized manifest) for
    artifacts that indicate Notion features the importer deliberately does NOT
    interpret — HTML exports, Notion API/JSON export metadata, and OS/Notion
    sync artifacts. Each is reported as a deterministic out-of-scope diagnostic
    naming the unsupported feature. Eligible flat content (``.md`` pages and
    ``.csv`` databases in *manifest*) is never affected: this function only
    *reports*, it never guesses OKF semantics for complex database behavior.

    Returns a list of explicit ``... is out of scope ...`` diagnostics.
    """
    root = Path(root)
    out_of_scope: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue  # not expressible relative to root — skip defensively
        suffix = path.suffix.lower()
        name = path.name
        if suffix in _OUT_OF_SCOPE_HTML_SUFFIXES:
            out_of_scope.append(
                f"HTML export {rel!r} is out of scope: HTML/API exports are "
                f"not interpreted (only Markdown & CSV are supported)"
            )
        elif suffix in _OUT_OF_SCOPE_API_SUFFIXES:
            out_of_scope.append(
                f"Notion API/JSON export metadata {rel!r} is out of scope: "
                f"API export is not interpreted (only Markdown & CSV are "
                f"supported)"
            )
        elif name in _OUT_OF_SCOPE_SYNC_NAMES:
            out_of_scope.append(
                f"sync/OS artifact {rel!r} is out of scope: not part of "
                f"eligible flat content"
            )
    return out_of_scope


# ---------------------------------------------------------------------------
# Phase 2 — identity & reference rewriting
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Deterministic Unicode slugification.

    Decomposes Unicode (NFKD), drops combining marks, maps every run of
    non-alphanumeric characters to a single hyphen, and lowercases. Safe for
    filenames and stable across runs — no randomness, no locale dependence.
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower()


def _is_uuid_like(filename: str) -> bool:
    """True when *filename*'s stem looks like a Notion page UUID.

    Only UUID-like names are renamed from their first ``#`` heading; readable
    names keep their identity (per design: no silent renaming of meaningful
    files).
    """
    return bool(_UUID_RE.match(Path(filename).stem))


def _first_h1(path: Path) -> str | None:
    """Return the first level-1 ``#`` heading of *path*, or ``None``."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _RE_H1.search(text)
    return match.group(1).strip() if match else None


def _build_rename_map(root: Path,
                      markdown_files: tuple[str, ...]) -> tuple[dict[str, str], list[str]]:
    """Compute a deterministic old-to-new POSIX path map for Notion pages.

    In sorted source order, UUID-like page filenames are renamed to the slug
    of their first ``#`` heading, keeping the folder. Missing/empty headings
    fall back to the original safe stem; slug collisions (with an existing
    source path or an earlier generated slug) append a deterministic numeric
    suffix. Every fallback emits a warning rather than losing or overwriting
    content. Non-UUID filenames map to themselves (identity preserved).

    Returns ``(rename_map, warnings)`` where ``rename_map`` is
    ``old_relative_path -> new_relative_path``.
    """
    root = Path(root)
    rename_map: dict[str, str] = {}
    warnings: list[str] = []
    used: set[str] = set()

    for rel in sorted(markdown_files):
        rel = rel.replace("\\", "/")
        parts = rel.split("/")
        filename = parts[-1]
        folder = "/".join(parts[:-1]) if len(parts) > 1 else ""
        # The original path is always occupied so a generated slug can never
        # silently overwrite another source file.
        used.add(rel)

        if not _is_uuid_like(filename):
            rename_map[rel] = rel
            continue

        heading = _first_h1(root / rel)
        stem = _slugify(heading) if heading else ""
        if not stem:
            stem = Path(filename).stem
            warnings.append(
                f"page {rel!r} has no usable first H1 heading; "
                f"keeping safe filename {filename!r}"
            )

        new_filename = f"{stem}.md"
        new_rel = f"{folder}/{new_filename}" if folder else new_filename
        # Identity fallback: the safe stem equals the original name, so the
        # page keeps its own filename (already warned) — no suffix needed.
        if new_rel == rel:
            rename_map[rel] = rel
            continue
        counter = 2
        collided = False
        while new_rel in used:
            collided = True
            new_filename = f"{stem}-{counter}.md"
            new_rel = f"{folder}/{new_filename}" if folder else new_filename
            counter += 1
            if counter > 1000:  # defensive; practically unreachable
                new_rel = rel
                new_filename = filename
                break
        if collided and new_rel != rel:
            warnings.append(
                f"slug collision for {rel!r}; using deterministic suffix "
                f"{new_filename!r}"
            )

        used.add(new_rel)
        rename_map[rel] = new_rel

    return rename_map, warnings


def _build_page_name_map(root: Path,
                         rename_map: dict[str, str]) -> dict[str, str]:
    """Map readable page names -> new identity stem for wikilink resolution.

    Keys are both the original filename stem and the first ``#`` heading text
    (case as written) so ``[[Elara's Journal]]`` and ``[[9f8e7d6c-...]]`` both
    resolve to the new identity ``elara-s-journal``.
    """
    names: dict[str, str] = {}
    for old_rel, new_rel in rename_map.items():
        new_stem = Path(new_rel).stem
        names[Path(old_rel).stem] = new_stem
        heading = _first_h1(root / old_rel)
        if heading:
            names[heading] = new_stem
    return names


def _rewrite_references(text: str, source_rel: str,
                        rename_map: dict[str, str],
                        page_name_map: dict[str, str]) -> tuple[str, list[str]]:
    """Rewrite internal Notion references using *rename_map* / *page_name_map*.

    Only unambiguous references are rewritten: relative Markdown links
    (``[text](relative/page.md)``) resolved against the source folder, and
    ``[[wikilinks]]`` that match a known page name. Unresolved links are kept
    verbatim and reported as warnings (never silently broken). Images
    (``![...]``) are never touched here.

    Returns ``(rewritten_text, warnings)``.
    """
    warnings: list[str] = []
    folder = Path(source_rel).parent

    def _md_repl(match: re.Match) -> str:
        alt, target = match.group(1), match.group(2).strip()
        if (target.startswith(("http://", "https://", "data:", "#"))
                or not target.lower().endswith(_MARKDOWN_SUFFIX)):
            return match.group(0)
        resolved = os.path.normpath(folder / target).replace("\\", "/")
        if resolved in rename_map:
            new_rel = rename_map[resolved]
            relative = os.path.relpath(new_rel, folder).replace("\\", "/")
            return f"[{alt}]({relative})"
        warnings.append(
            f"unresolved markdown link {target!r} in {source_rel!r}"
        )
        return match.group(0)

    def _wiki_repl(match: re.Match) -> str:
        target = match.group(1).strip()
        if target in page_name_map:
            return f"[[{page_name_map[target]}]]"
        warnings.append(f"unresolved wikilink {target!r} in {source_rel!r}")
        return match.group(0)

    rewritten = _RE_MD_LINK.sub(_md_repl, text)
    rewritten = _RE_WIKILINK.sub(_wiki_repl, rewritten)
    return rewritten, warnings


# ---------------------------------------------------------------------------
# Phase 2 — media hashing & deduplication
# ---------------------------------------------------------------------------


def _sha256_stream(path: Path, chunk_size: int = _HASH_CHUNK) -> str:
    """Streaming SHA-256 of *path* in bounded chunks (never whole-file)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _collect_media_files(root: Path,
                         markdown_files: tuple[str, ...]) -> list[str]:
    """Collect POSIX-relative media files referenced by the Markdown pages.

    Every ``![alt](path)`` reference that resolves to a real file inside
    *root* (and is not a remote/data/anchored reference) is included.
    Deterministically sorted; returned paths are POSIX-relative.
    """
    root = Path(root)
    media: set[str] = set()
    for rel in sorted(markdown_files):
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        folder = Path(rel).parent
        for match in _RE_IMAGE_REF.finditer(text):
            ref = match.group(1).strip()
            if ref.startswith(("http://", "https://", "data:", "#")):
                continue
            norm = os.path.normpath(folder / ref).replace("\\", "/")
            if (root / norm).is_file():
                media.add(norm)
    return sorted(media)


def _hash_media_streaming(root: Path,
                          media_rel_paths: list[str]) -> list[MediaAsset]:
    """Hash media files streaming and deduplicate by SHA-256.

    Equal bytes collapse into one ``MediaAsset`` (first source path becomes
    ``canonical_path``); every original source path is preserved in
    ``references`` so no reference is lost. Deterministic order by hash.
    """
    root = Path(root)
    by_hash: dict[str, MediaAsset] = {}
    for rel in sorted(media_rel_paths):
        path = root / rel
        digest = _sha256_stream(path)
        size = path.stat().st_size
        existing = by_hash.get(digest)
        if existing is not None:
            existing.references.append(rel)
        else:
            by_hash[digest] = MediaAsset(
                sha256=digest, canonical_path=rel, size_bytes=size,
                references=[rel],
            )
    return [by_hash[key] for key in sorted(by_hash)]


# ---------------------------------------------------------------------------
# Phase 2 — CSV database -> OKF fichas
# ---------------------------------------------------------------------------


def _find_column(header: list[str], candidates: tuple[str, ...]) -> int | None:
    """Return the index of the first *candidates* header (case-insensitive)."""
    lowered = [h.strip().lower() for h in header]
    for cand in candidates:
        if cand in lowered:
            return lowered.index(cand)
    return None


def _serialize_csv_ficha(fields: dict[str, object],
                         properties: dict[str, str], name: str) -> str:
    """Serialize a CSV row into minimal OKF frontmatter + ``# Name`` body."""
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            items = ", ".join(str(v) for v in value)
            lines.append(f"{key}: [{items}]")
        else:
            lines.append(f"{key}: {value}")
    if properties:
        lines.append("properties:")
        for key, value in properties.items():
            lines.append(f"  {key}: {value}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")
    return "\n".join(lines)


def convert_csv_to_fichas(csv_path: Path, csv_rel: str) -> tuple[list[CsvFicha], list[str]]:
    """Convert a flat CSV database into OKF Markdown fichas (streaming).

    Rows are streamed with ``utf-8-sig`` so a leading BOM is stripped. Maps
    ``Name``->``name``, ``Tags``->``tags``, ``Status``->``status`` (and a
    ``Type`` column when present); every unmapped column is retained under
    ``properties`` for review. Malformed/nameless rows are diagnosed with a
    warning and deterministically named (or skipped when structurally
    invalid) — never silently lost.

    Returns ``(fichas, warnings)``.
    """
    warnings: list[str] = []
    fichas: list[CsvFicha] = []
    csv_path = Path(csv_path)
    csv_rel = csv_rel.replace("\\", "/")
    parts = csv_rel.split("/")
    folder = "/".join(parts[:-1]) if len(parts) > 1 else ""

    try:
        handle = open(csv_path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        return [], [f"cannot open CSV {csv_rel!r}: {exc}"]

    used_names: set[str] = set()
    with handle as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader, None)
        except csv.Error as exc:
            return [], [f"malformed CSV header in {csv_rel!r}: {exc}"]
        if header is None:
            return [], [f"empty CSV {csv_rel!r}: no header row"]

        header = [h.strip() for h in header]
        col_name = _find_column(header, _NAME_COLUMNS)
        col_tags = _find_column(header, _TAGS_COLUMNS)
        col_status = _find_column(header, _STATUS_COLUMNS)
        col_type = _find_column(header, _TYPE_COLUMNS)
        mapped = {col_name, col_tags, col_status, col_type}
        unmapped_idx = [i for i in range(len(header)) if i not in mapped]

        for row_no, row in enumerate(reader, start=2):
            # A row with more fields than the header is structurally invalid.
            if len(row) > len(header):
                warnings.append(
                    f"{csv_rel}: row {row_no} has {len(row)} fields but header "
                    f"has {len(header)}; skipped"
                )
                continue
            if not row:
                warnings.append(f"{csv_rel}: row {row_no} is empty; skipped")
                continue
            # Pad short rows so column indexing is safe.
            row = list(row) + [""] * (len(header) - len(row))

            name = row[col_name].strip() if col_name is not None else ""
            if not name:
                name = f"row-{row_no}"
                warnings.append(
                    f"{csv_rel}: row {row_no} has no name; "
                    f"deterministically named {name!r}"
                )

            stem = _slugify(name) or f"row-{row_no}"
            new_filename = f"{stem}.md"
            counter = 2
            while new_filename in used_names:
                new_filename = f"{stem}-{counter}.md"
                counter += 1
            used_names.add(new_filename)
            identity = f"{folder}/{new_filename}" if folder else new_filename

            fields: dict[str, object] = {"okf_version": "1"}
            if col_type is not None and row[col_type].strip():
                fields["type"] = row[col_type].strip()
            fields["name"] = name
            if col_tags is not None and row[col_tags].strip():
                tags = [t.strip() for t in row[col_tags].split(",") if t.strip()]
                if tags:
                    fields["tags"] = tags
            if col_status is not None and row[col_status].strip():
                fields["status"] = row[col_status].strip()

            properties: dict[str, str] = {}
            for i in unmapped_idx:
                value = row[i].strip() if i < len(row) else ""
                if value:
                    properties[header[i]] = value

            markdown = _serialize_csv_ficha(fields, properties, name)
            fichas.append(CsvFicha(identity=identity, markdown=markdown))

    return fichas, warnings


# ---------------------------------------------------------------------------
# Phase 2 — orchestrator
# ---------------------------------------------------------------------------


def analyze_export(root: Path, manifest: NotionManifest) -> NotionAnalysis:
    """Analyze a recognized Notion export into a shared ``NotionAnalysis``.

    Orchestrates deterministic rename + reference rewriting, streaming media
    hashing/deduplication, and CSV->ficha conversion, then delegates every
    Markdown body (real pages and generated fichas alike) to
    ``import_analysis.analyze_markdown`` so candidates share the analysis
    contract. Read-only and fail-open: all issues surface as diagnostics.
    """
    root = Path(root)
    diagnostics: list[str] = []
    report = AnalysisReport()

    # Explicitly report complex/unsupported Notion features (HTML/API export,
    # sync artifacts) as out of scope rather than guessing OKF semantics. The
    # dedicated list is also merged into ``diagnostics`` so the report rides
    # the same fail-open ``notion_diagnostics`` event path as other warnings.
    out_of_scope = detect_out_of_scope_features(root, manifest)
    diagnostics.extend(out_of_scope)

    rename_map, rename_warnings = _build_rename_map(root, manifest.markdown_files)
    diagnostics.extend(rename_warnings)
    page_name_map = _build_page_name_map(root, rename_map)

    media_files = _collect_media_files(root, manifest.markdown_files)
    media = _hash_media_streaming(root, media_files)

    # Markdown pages (in deterministic source order).
    for rel in sorted(manifest.markdown_files):
        source = root / rel
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            diagnostics.append(f"cannot read page {rel!r}: {exc}")
            continue
        rewritten, link_warnings = _rewrite_references(
            text, rel, rename_map, page_name_map)
        diagnostics.extend(link_warnings)
        new_rel = rename_map.get(rel, rel)
        analyzed = analyze_markdown(
            rewritten, new_rel, _sha256_stream(source), source.stat().st_size)
        report.files.append(analyzed)

    # CSV databases (deterministic source order).
    for csv_rel in sorted(manifest.csv_files):
        fichas, csv_warnings = convert_csv_to_fichas(root / csv_rel, csv_rel)
        diagnostics.extend(csv_warnings)
        for ficha in fichas:
            data = ficha.markdown.encode("utf-8")
            digest = hashlib.sha256(data).hexdigest()
            analyzed = analyze_markdown(ficha.markdown, ficha.identity, digest, len(data))
            report.files.append(analyzed)

    return NotionAnalysis(report=report, media=media, diagnostics=diagnostics,
                          out_of_scope=out_of_scope)
