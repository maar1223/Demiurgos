# -*- coding: utf-8 -*-
"""World importer — Notion recognition + intake hardening tests (Phase 1).

Covers the PR 1 work unit:
- a valid Notion Markdown & CSV export ZIP is recognized and yields a
  ``NotionManifest`` with the discovered pages/databases;
- a non-Notion ZIP (no ``.md`` / ``.csv`` files) returns ``None``;
- traversal and symlink ZIP entries are rejected by ``extract_zip_bounded``
  with an actionable diagnostic and no extraction.
"""

import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_intake import UnsafePathError, extract_zip_bounded  # noqa: E402
from import_notion import (  # noqa: E402
    CsvFicha,
    MediaAsset,
    NotionManifest,
    _build_page_name_map,
    _build_rename_map,
    _collect_media_files,
    _hash_media_streaming,
    _rewrite_references,
    analyze_export,
    convert_csv_to_fichas,
    detect_out_of_scope_features,
    recognize_notion_zip,
)

FIXTURES = _HERE / "fixtures" / "notion"
EXPORT = FIXTURES / "export"
OTHER = FIXTURES / "other"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zip_dir(src: Path, zip_path: Path) -> Path:
    """Deterministic ZIP of a directory (sorted entries, root-relative)."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            relative = path.relative_to(src)
            if path.is_dir():
                zf.writestr(zipfile.ZipInfo(f"{relative}/"), b"")
            else:
                zf.write(path, arcname=str(relative))
    return zip_path


def _extract(archive: Path, tmp_path: Path) -> Path:
    """Extract *archive* through the bounded intake path; return the root."""
    dest = tmp_path / "extracted"
    extract_zip_bounded(archive, dest)
    return dest


def _symlink_zip(archive: Path, *, entry: str = "assets/evil-link",
                 target: str = "/etc/passwd") -> Path:
    """Build a ZIP containing one Unix symlink entry (header attributes only)."""
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo(entry)
        info.create_system = 3  # Unix
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, target)
    return archive


def _zip_from_dict(tmp_path: Path, name: str,
                   entries: dict[str, bytes | str]) -> Path:
    """Deterministic ZIP from a {relative_path: content} map (strings = UTF-8)."""
    archive = tmp_path / name
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(entries):
            content = entries[rel]
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(rel, content)
    return archive


def _write_big(tmp_path: Path, name: str, size: int,
               chunk: bytes = b"A" * (1024 * 1024)) -> Path:
    """Write *size* bytes in bounded chunks (keeps the test heap small)."""
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    remaining = size
    with target.open("wb") as fh:
        while remaining > 0:
            piece = chunk if remaining >= len(chunk) else chunk[:remaining]
            fh.write(piece)
            remaining -= len(piece)
    return target


# ---------------------------------------------------------------------------
# Recognition (task 1.3 / 1.5)
# ---------------------------------------------------------------------------

class TestRecognizeNotionZip:
    def test_valid_notion_export_recognized(self, tmp_path):
        archive = _zip_dir(EXPORT, tmp_path / "export.zip")
        root = _extract(archive, tmp_path)

        manifest = recognize_notion_zip(root)

        assert manifest is not None
        assert isinstance(manifest, NotionManifest)
        assert manifest.root == root
        # Both content shapes are discovered, relative and deterministically sorted.
        assert manifest.markdown_files == (
            "9f8e7d6c-5b4a-3210-fedc-ba9876543210.md",
            "World Overview.md",
        )
        assert manifest.csv_files == ("Database/Characters.csv",)

    def test_page_only_export_recognized(self, tmp_path):
        """A Notion export with pages but no databases is still recognized."""
        src = tmp_path / "pages"
        src.mkdir()
        (src / "Página.md").write_text("# Page\nbody", encoding="utf-8")
        archive = _zip_dir(src, tmp_path / "pages.zip")
        root = _extract(archive, tmp_path)

        manifest = recognize_notion_zip(root)

        assert manifest is not None
        assert manifest.markdown_files == ("Página.md",)
        assert manifest.csv_files == ()

    def test_database_only_export_recognized(self, tmp_path):
        """A flat CSV database alone is Notion-shaped (no Markdown pages)."""
        src = tmp_path / "db"
        src.mkdir()
        (src / "Characters.csv").write_text("Name\nElara", encoding="utf-8")
        archive = _zip_dir(src, tmp_path / "db.zip")
        root = _extract(archive, tmp_path)

        manifest = recognize_notion_zip(root)

        assert manifest is not None
        assert manifest.markdown_files == ()
        assert manifest.csv_files == ("Characters.csv",)

    def test_non_notion_zip_returns_none(self, tmp_path):
        archive = _zip_dir(OTHER, tmp_path / "other.zip")
        root = _extract(archive, tmp_path)

        assert recognize_notion_zip(root) is None

    def test_missing_root_returns_none(self, tmp_path):
        assert recognize_notion_zip(tmp_path / "does-not-exist") is None

    def test_recognition_is_read_only(self, tmp_path):
        """Recognition never mutates the extracted root."""
        archive = _zip_dir(EXPORT, tmp_path / "export.zip")
        root = _extract(archive, tmp_path)
        before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

        recognize_notion_zip(root)

        after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        assert after == before


# ---------------------------------------------------------------------------
# Intake hardening (task 1.2)
# ---------------------------------------------------------------------------

class TestIntakeHardening:
    def test_traversal_entry_rejected(self, tmp_path):
        archive = tmp_path / "traversal.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escape.md", "# nope")

        with pytest.raises(UnsafePathError, match="traversal"):
            extract_zip_bounded(archive, tmp_path / "out")

        # Fail closed: nothing was extracted.
        assert not (tmp_path / "out").exists() or not any(
            (tmp_path / "out").rglob("*")
        )

    def test_symlink_entry_rejected(self, tmp_path):
        archive = _symlink_zip(tmp_path / "symlink.zip")
        dest = tmp_path / "out"

        with pytest.raises(UnsafePathError, match="symlink"):
            extract_zip_bounded(archive, dest)

        # Fail closed: the symlink target was never materialized.
        assert not (dest / "assets" / "evil-link").exists()
        assert not any(dest.rglob("*")) if dest.exists() else True

    def test_symlink_entry_rejected_before_regular_entries(self, tmp_path):
        """A symlink entry is rejected even when a regular entry precedes it."""
        archive = tmp_path / "mixed.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("safe.md", "# ok")
            info = zipfile.ZipInfo("assets/evil-link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")

        dest = tmp_path / "out"
        with pytest.raises(UnsafePathError, match="symlink"):
            extract_zip_bounded(archive, dest)

        assert not (dest / "assets" / "evil-link").exists()


# ---------------------------------------------------------------------------
# Phase 2 — rename map (task 2.1)
# ---------------------------------------------------------------------------

class TestBuildRenameMap:
    def test_uuid_page_renamed_from_first_h1(self, tmp_path):
        """A UUID-named page is renamed to the slug of its first H1."""
        archive = _zip_from_dict(tmp_path, "p.zip", {
            "9f8e7d6c-5b4a-3210-fedc-ba9876543210.md":
                "# Elara's Journal\n\nbody\n",
            "World Overview.md": "# World Overview\n\nbody\n",
        })
        root = _extract(archive, tmp_path)

        rename_map, warnings = _build_rename_map(root, ("9f8e7d6c-5b4a-3210-fedc-ba9876543210.md", "World Overview.md"))

        assert rename_map == {
            "9f8e7d6c-5b4a-3210-fedc-ba9876543210.md": "elara-s-journal.md",
            "World Overview.md": "World Overview.md",
        }
        assert warnings == []

    def test_missing_heading_falls_back_to_safe_stem(self, tmp_path):
        """A UUID page without an H1 keeps its safe filename and warns."""
        archive = _zip_from_dict(tmp_path, "p.zip", {
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.md": "just body, no heading\n",
        })
        root = _extract(archive, tmp_path)

        rename_map, warnings = _build_rename_map(
            root, ("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.md",))

        assert rename_map["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.md"] == \
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.md"
        assert any("no usable first H1" in w for w in warnings)

    def test_colliding_slugs_get_deterministic_suffix(self, tmp_path):
        """Two pages whose slugs collide get a deterministic numeric suffix."""
        archive = _zip_from_dict(tmp_path, "p.zip", {
            "11111111-1111-1111-1111-111111111111.md": "# Same Title\n\none\n",
            "22222222-2222-2222-2222-222222222222.md": "# Same Title\n\ntwo\n",
        })
        root = _extract(archive, tmp_path)
        files = ("11111111-1111-1111-1111-111111111111.md",
                 "22222222-2222-2222-2222-222222222222.md")

        rename_map, warnings = _build_rename_map(root, files)

        targets = set(rename_map.values())
        assert "same-title.md" in targets
        assert "same-title-2.md" in targets
        assert any("collision" in w for w in warnings)


# ---------------------------------------------------------------------------
# Phase 2 — reference rewriting (task 2.2)
# ---------------------------------------------------------------------------

class TestRewriteReferences:
    def test_relative_markdown_link_rewritten(self, tmp_path):
        archive = _zip_from_dict(tmp_path, "p.zip", {
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md":
                "# Alpha\n\nSee [beta](bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.md).\n",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.md": "# Beta\n\nbody\n",
        })
        root = _extract(archive, tmp_path)
        files = ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md",
                 "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.md")
        rename_map, _ = _build_rename_map(root, files)
        text = (root / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md").read_text(
            encoding="utf-8")

        rewritten, warnings = _rewrite_references(
            text, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md", rename_map, {})

        assert "[beta](beta.md)" in rewritten
        assert warnings == []

    def test_wikilink_rewritten_to_new_identity(self, tmp_path):
        archive = _zip_from_dict(tmp_path, "p.zip", {
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md":
                "# Alpha\n\nLink to [[Beta]].\n",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.md": "# Beta\n\nbody\n",
        })
        root = _extract(archive, tmp_path)
        files = ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md",
                 "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.md")
        rename_map, _ = _build_rename_map(root, files)
        page_name_map = _build_page_name_map(root, rename_map)
        text = (root / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md").read_text(
            encoding="utf-8")

        rewritten, _ = _rewrite_references(
            text, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md",
            rename_map, page_name_map)

        assert "[[beta]]" in rewritten

    def test_unresolved_link_preserved_with_warning(self, tmp_path):
        archive = _zip_from_dict(tmp_path, "p.zip", {
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md":
                "# Alpha\n\nSee [ghost](ghost.md).\n",
        })
        root = _extract(archive, tmp_path)
        rename_map, _ = _build_rename_map(
            root, ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md",))
        text = (root / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md").read_text(
            encoding="utf-8")

        rewritten, warnings = _rewrite_references(
            text, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md", rename_map, {})

        assert "[ghost](ghost.md)" in rewritten  # preserved, not destroyed
        assert any("unresolved markdown link" in w for w in warnings)

    def test_unresolved_wikilink_preserved_with_warning(self, tmp_path):
        archive = _zip_from_dict(tmp_path, "p.zip", {
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md":
                "# Alpha\n\nLink to [[Missing Page]].\n",
        })
        root = _extract(archive, tmp_path)
        text = (root / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md").read_text(
            encoding="utf-8")

        rewritten, warnings = _rewrite_references(
            text, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md", {}, {})

        assert "[[Missing Page]]" in rewritten
        assert any("unresolved wikilink" in w for w in warnings)

    def test_images_are_never_rewritten(self, tmp_path):
        archive = _zip_from_dict(tmp_path, "p.zip", {
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md":
                "# Alpha\n\n![pic](assets/hero.png)\n",
        })
        root = _extract(archive, tmp_path)
        text = (root / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md").read_text(
            encoding="utf-8")

        rewritten, _ = _rewrite_references(
            text, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.md", {}, {})

        assert "![pic](assets/hero.png)" in rewritten


# ---------------------------------------------------------------------------
# Phase 2 — media hashing & deduplication (task 2.3)
# ---------------------------------------------------------------------------

class TestHashMediaStreaming:
    def test_duplicate_bytes_deduped_into_one_asset(self, tmp_path):
        archive = _zip_from_dict(tmp_path, "m.zip", {
            "page.md": "# Page\n\n"
                       "![a](assets/one.png)\n\n"
                       "![b](assets/two.png)\n",
            "assets/one.png": b"\x89PNG same-bytes",
            "assets/two.png": b"\x89PNG same-bytes",
        })
        root = _extract(archive, tmp_path)
        media_files = _collect_media_files(root, ("page.md",))

        assets = _hash_media_streaming(root, media_files)

        assert len(assets) == 1
        asset = assets[0]
        assert isinstance(asset, MediaAsset)
        assert len(asset.sha256) == 64
        assert set(asset.references) == {"assets/one.png", "assets/two.png"}
        assert asset.canonical_path in asset.references
        assert asset.size_bytes == len(b"\x89PNG same-bytes")

    def test_distinct_bytes_stay_separate(self, tmp_path):
        archive = _zip_from_dict(tmp_path, "m.zip", {
            "page.md": "# Page\n\n![a](a.png)\n\n![b](b.png)\n",
            "a.png": b"aaaa",
            "b.png": b"bbbb",
        })
        root = _extract(archive, tmp_path)
        media_files = _collect_media_files(root, ("page.md",))

        assets = _hash_media_streaming(root, media_files)

        assert len(assets) == 2


# ---------------------------------------------------------------------------
# Phase 2 — CSV -> fichas (task 2.4)
# ---------------------------------------------------------------------------

class TestConvertCsvToFichas:
    def test_valid_rows_map_name_tags_status_and_properties(self, tmp_path):
        csv_path = tmp_path / "Characters.csv"
        csv_path.write_text(
            "Name,Tags,Status,Age,Notes\n"
            "Elara,protagonist,active,25,\"Lives in Valdris\"\n",
            encoding="utf-8-sig")

        fichas, warnings = convert_csv_to_fichas(csv_path, "Database/Characters.csv")

        assert warnings == []
        assert len(fichas) == 1
        ficha = fichas[0]
        assert isinstance(ficha, CsvFicha)
        assert ficha.identity == "Database/elara.md"
        assert "okf_version: 1" in ficha.markdown
        assert "name: Elara" in ficha.markdown
        assert "tags: [protagonist]" in ficha.markdown
        assert "status: active" in ficha.markdown
        assert "properties:" in ficha.markdown
        assert "  Age: 25" in ficha.markdown
        assert "  Notes: Lives in Valdris" in ficha.markdown

    def test_incomplete_row_still_converted(self, tmp_path):
        csv_path = tmp_path / "C.csv"
        csv_path.write_text("Name,Tags,Status\nKael,antagonist\n", encoding="utf-8-sig")

        fichas, warnings = convert_csv_to_fichas(csv_path, "C.csv")

        assert len(fichas) == 1
        assert "name: Kael" in fichas[0].markdown
        assert "status:" not in fichas[0].markdown  # missing -> omitted

    def test_nameless_row_deterministically_named_with_warning(self, tmp_path):
        csv_path = tmp_path / "C.csv"
        csv_path.write_text("Name,Status\n,active\n", encoding="utf-8-sig")

        fichas, warnings = convert_csv_to_fichas(csv_path, "C.csv")

        assert len(fichas) == 1
        assert any("no name" in w and "deterministically named" in w
                   for w in warnings)
        assert "row-2" in fichas[0].identity

    def test_malformed_row_skipped_with_warning(self, tmp_path):
        csv_path = tmp_path / "C.csv"
        csv_path.write_text(
            "Name,Status\nElara,active\nDorin,ally,EXTRA,EXTRA2\n",
            encoding="utf-8-sig")

        fichas, warnings = convert_csv_to_fichas(csv_path, "C.csv")

        assert len(fichas) == 1  # only the well-formed row
        assert any("row 3" in w and "skipped" in w for w in warnings)

    def test_utf8_bom_stripped(self, tmp_path):
        csv_path = tmp_path / "C.csv"
        csv_path.write_bytes(
            b"\xef\xbb\xbfName,Status\nElara,active\n")

        fichas, warnings = convert_csv_to_fichas(csv_path, "C.csv")

        assert len(fichas) == 1
        assert "name: Elara" in fichas[0].markdown


# ---------------------------------------------------------------------------
# Phase 2 — orchestrator + bounded streaming (tasks 2.5, 2.6)
# ---------------------------------------------------------------------------

class TestAnalyzeExport:
    def test_export_analysis_orchestrates_all_phases(self, tmp_path):
        archive = _zip_from_dict(tmp_path, "e.zip", {
            "9f8e7d6c-5b4a-3210-fedc-ba9876543210.md":
                "# Elara's Journal\n\n![tower](assets/hero.png)\n\n"
                "See [overview](World Overview.md).\n",
            "World Overview.md": "# World Overview\n\nbody\n",
            "Database/Characters.csv": "Name,Tags,Status\nElara,protagonist,active\n",
            "assets/hero.png": b"\x89PNG hero",
        })
        root = _extract(archive, tmp_path)
        manifest = recognize_notion_zip(root)

        analysis = analyze_export(root, manifest)

        identities = [f.source_path for f in analysis.report.files]
        assert "elara-s-journal.md" in identities
        assert "World Overview.md" in identities
        assert "Database/elara.md" in identities
        assert len(analysis.media) == 1
        assert analysis.media[0].canonical_path == "assets/hero.png"

    def test_analyze_export_is_read_only(self, tmp_path):
        archive = _zip_from_dict(tmp_path, "e.zip", {
            "9f8e7d6c-5b4a-3210-fedc-ba9876543210.md":
                "# Elara's Journal\n\nbody\n",
            "assets/hero.png": b"\x89PNG hero",
        })
        root = _extract(archive, tmp_path)
        manifest = recognize_notion_zip(root)
        before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

        analyze_export(root, manifest)

        after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        assert after == before

    def test_100mb_plus_media_hashed_streaming(self, tmp_path):
        """A 100 MB+ media file is hashed in bounded chunks, not buffered."""
        src = tmp_path / "src"
        src.mkdir()
        big = _write_big(src, "assets/big.png", size=100 * 1024 * 1024)
        (src / "page.md").write_text(
            "# Page\n\n![big](assets/big.png)\n", encoding="utf-8")

        media_files = _collect_media_files(src, ("page.md",))
        assets = _hash_media_streaming(src, media_files)

        assert len(assets) == 1
        asset = assets[0]
        assert asset.size_bytes == big.stat().st_size
        assert asset.size_bytes >= 100 * 1024 * 1024
        assert len(asset.sha256) == 64
        assert asset.references == ["assets/big.png"]


# ---------------------------------------------------------------------------
# Spec requirement 4 / scenario S6 — complex DB behavior out of scope (C1)
# ---------------------------------------------------------------------------

class TestOutOfScopeReporting:
    """Complex/unsupported Notion features are reported, not guessed (R4/S6)."""

    def test_html_export_out_of_scope_while_flat_content_analyzed(self, tmp_path):
        """S6: HTML export is reported unsupported, eligible flat content remains."""
        archive = _zip_from_dict(tmp_path, "s6.zip", {
            "9f8e7d6c-5b4a-3210-fedc-ba9876543210.md":
                "# Elara's Journal\n\nbody\n",
            "Database/Characters.csv": "Name,Status\nElara,active\n",
            "index.html": "<html><body>exported</body></html>",
        })
        root = _extract(archive, tmp_path)
        manifest = recognize_notion_zip(root)

        analysis = analyze_export(root, manifest)

        # The unsupported HTML export is explicitly out of scope...
        assert analysis.out_of_scope
        assert any("HTML" in o and "out of scope" in o
                   for o in analysis.out_of_scope)
        # ...and also surfaces as a fail-open diagnostic (notion_diagnostics).
        assert any("HTML" in d and "out of scope" in d for d in analysis.diagnostics)
        # ...while eligible flat content remains analyzable (never guessed).
        identities = [f.source_path for f in analysis.report.files]
        assert "elara-s-journal.md" in identities
        assert "Database/elara.md" in identities

    def test_api_json_export_metadata_out_of_scope(self, tmp_path):
        """API/JSON export metadata is reported unsupported, not guessed."""
        archive = _zip_from_dict(tmp_path, "api.zip", {
            "page.md": "# Page\n\nbody\n",
            "export-data.json": '{"view":{"filter":{}}}',
        })
        root = _extract(archive, tmp_path)
        manifest = recognize_notion_zip(root)

        analysis = analyze_export(root, manifest)

        assert any("API" in o and "out of scope" in o
                   for o in analysis.out_of_scope)
        # Flat page still analyzed.
        identities = [f.source_path for f in analysis.report.files]
        assert "page.md" in identities

    def test_sync_artifact_out_of_scope(self, tmp_path):
        """OS/Notion sync artifacts are reported out of scope.

        Hidden path segments are already rejected at intake by
        ``extract_zip_bounded`` (fail closed), so this defense-in-depth
        detection is exercised directly on an extracted root.
        """
        root = tmp_path / "root"
        root.mkdir()
        (root / "page.md").write_text("# Page\n\nbody\n", encoding="utf-8")
        (root / ".DS_Store").write_bytes(b"\x00\x01")
        manifest = NotionManifest(root=root, markdown_files=("page.md",))

        reported = detect_out_of_scope_features(root, manifest)

        assert any("sync/OS artifact" in o and "out of scope" in o
                   for o in reported)

    def test_clean_flat_export_reports_nothing_out_of_scope(self, tmp_path):
        """A flat export with only eligible content has no out-of-scope report."""
        archive = _zip_from_dict(tmp_path, "clean.zip", {
            "page.md": "# Page\n\nbody\n",
            "Database/Characters.csv": "Name,Status\nElara,active\n",
        })
        root = _extract(archive, tmp_path)
        manifest = recognize_notion_zip(root)

        analysis = analyze_export(root, manifest)

        assert analysis.out_of_scope == []
        assert "page.md" in [f.source_path for f in analysis.report.files]
