#!/usr/bin/env python3
"""Generate a flat JSON catalog from a directory of OKF-frontmattered .md files.

Scans .md files recursively under --input-dir, extracts YAML frontmatter
between ``---`` delimiters, and outputs a JSON array. Every frontmatter key
becomes a top-level JSON key. The script always adds ``file`` (relative path
from input-dir root) and ``category`` (parent directory name, only for files
inside subdirectories).

Exclusion rules:
    - Files whose names start with ``_`` or ``00_``
    - Files named ``CHANGELOG.md``
    - Non-``.md`` files

Exit 0 on success (including empty ``[]``), exit 1 on fatal error
(e.g. missing --input-dir).

Usage:
    python src/tools/generate_content_catalog.py \
        --input-dir mundos/vibrantes/lore \
        --output mundos/vibrantes/lore/_lore_catalog.json
"""

import argparse
import json
import sys
from datetime import date, datetime, time
from pathlib import Path

# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------

EXCLUDED_PREFIXES: tuple[str, ...] = ("_", "00_")
EXCLUDED_NAMES: tuple[str, ...] = ("CHANGELOG.md",)


def _is_excluded(path: Path) -> bool:
    """Return True if the file should be excluded by name/prefix rules."""
    name = path.name
    if name in EXCLUDED_NAMES:
        return True
    if name.startswith(EXCLUDED_PREFIXES):
        return True
    return False


# ---------------------------------------------------------------------------
# Frontmatter extraction
# ---------------------------------------------------------------------------


def _extract_frontmatter(text: str) -> dict[str, object]:
    """Locate the first ``---`` … ``---`` block and return parsed YAML.

    Uses PyYAML when available; falls back to a simple line-by-line
    key:value parser that handles flat scalar fields only.
    """
    content = text.lstrip("\ufeff")  # strip BOM

    # Must start with ---
    if not content.startswith("---"):
        return {}

    # Find closing ---
    end = content.find("\n---", 3)
    if end == -1:
        # Handle files where --- is at position 3 with no preceding newline
        if content.startswith("---\n", 3) or content[3:].strip() == "":
            return {}
        # Try finding --- on its own line after position 3
        end = content.find("---", 3)
        if end == -1:
            return {}

    fm_text = content[3:end].strip()
    if not fm_text:
        return {}

    # Attempt PyYAML
    try:
        import yaml

        parsed = yaml.safe_load(fm_text)
        if isinstance(parsed, dict):
            return parsed
        return {}
    except ImportError:
        pass
    except Exception:
        # yaml.safe_load may raise on malformed input — fall through to
        # the manual parser
        pass

    # Fallback: line-by-line key: value parser (flat scalars only)
    return _parse_frontmatter_flat(fm_text)


def _parse_frontmatter_flat(text: str) -> dict[str, object]:
    """Line-by-line key:value parser — handles flat scalar fields only.

    Multi-line lists and nested objects are NOT supported by this fallback;
    they will be silently omitted.
    """
    result: dict[str, object] = {}
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if val:  # omit empty values
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Category derivation
# ---------------------------------------------------------------------------


def _derive_category(rel_path: Path) -> str | None:
    """Return the top-level directory name of *rel_path*, or None if at root.

    For ``ayagars/Dvex_por_Stal/Dvex_01_Director.md`` returns ``"ayagars"``.
    For ``Cultura.md`` returns ``None``.
    """
    parts = rel_path.parts
    if len(parts) < 2:
        return None
    return parts[0]  # top-level category only


# ---------------------------------------------------------------------------
# JSON serialization helper
# ---------------------------------------------------------------------------


def _json_default(obj: object) -> str:
    """Convert non-serializable types (datetime) to ISO strings."""
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------


def scan_directory(input_dir: Path) -> list[dict[str, object]]:
    """Recursively scan *input_dir* for .md files and build catalog entries.

    Returns a list of dicts, one per valid .md file that contains frontmatter.
    """
    if not input_dir.is_dir():
        print(f"Error: --input-dir '{input_dir}' does not exist or is not a directory.",
              file=sys.stderr)
        sys.exit(1)

    entries: list[dict[str, object]] = []

    for fpath in sorted(input_dir.rglob("*.md")):
        if _is_excluded(fpath):
            continue

        # Read file
        try:
            text = fpath.read_text(encoding="utf-8")
        except Exception:
            continue  # unreadable file → skip silently

        # Extract frontmatter
        fm = _extract_frontmatter(text)
        if not fm:
            continue  # no frontmatter → skip silently

        # Build entry
        entry: dict[str, object] = dict(fm)

        # Add computed fields
        rel_path = fpath.relative_to(input_dir)
        entry["file"] = str(rel_path).replace("\\", "/")

        category = _derive_category(rel_path)
        if category is not None:
            entry["category"] = category

        entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a machine-readable JSON catalog from "
                    "OKF-frontmattered .md files."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        type=Path,
        help="Root directory to scan recursively for .md files.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path where the JSON catalog will be written.",
    )
    args = parser.parse_args()

    input_dir: Path = args.input_dir.resolve()
    output_path: Path = args.output.resolve()

    entries = scan_directory(input_dir)

    # Write JSON
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True,
                       default=_json_default) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"Error: failed to write output: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Generated {output_path} with {len(entries)} entries.")


if __name__ == "__main__":
    main()
