#!/usr/bin/env python3
"""Generate plantillas/_catalog.json from plantillas/_indice.md markdown table.

Reads the markdown table, parses rows, outputs a flat JSON array with schema:
  [{name, file, use_case, skill, tags}]

Exit 0 on success, exit 1 if _indice.md is missing or unparseable.
"""

import json
import re
import sys
from pathlib import Path


def derive_name(file_stem: str) -> str:
    """Derive a human-readable name from the filename stem.

    Removes the number prefix (e.g. '01_'), strips leading underscores,
    replaces underscores with spaces, and title-cases each word.
    """
    # Strip leading number prefix like '01_', '02_', or leading '_'
    stem = re.sub(r'^(\d{2}_|_)', '', file_stem)
    # Replace underscores with spaces and title-case
    name = stem.replace('_', ' ').strip().title()
    return name


def extract_tags(use_case: str) -> list[str]:
    """Extract simple keyword tags from the use_case description.

    Uses a mapping of Spanish/English taxonomy terms to normalized tag labels.
    Falls back to splitting on common delimiters and filtering stopwords.
    """
    text_lower = use_case.lower()

    # Direct keyword → tag mapping (order matters: more specific first)
    mappings = [
        # Snyder / beat sheet
        (['snyder', 'beat'], 'snyder'),
        (['beat sheet', 'beat'], 'beat-sheet'),
        # Archetypes
        (['arquetipo', 'archetype'], 'archetype'),
        # Story / plot
        (['trama', 'plot'], 'plot'),
        (['historia', 'story'], 'story'),
        # Personality / character
        (['personalidad', 'personality'], 'personality'),
        (['personaje', 'character'], 'character'),
        # Alignment / moral
        (['alineamiento', 'alignment', 'moral'], 'alignment'),
        # Conflict
        (['conflicto', 'conflict'], 'conflict'),
        # Group dynamics
        (['dinamica', 'dynamics', 'grupo', 'group'], 'group'),
        # Setting / location
        (['escenario', 'setting', 'locacion', 'location', 'fantasia', 'fantasy'], 'setting'),
        # Dilemma
        (['dilema', 'dilemma', 'filosofico', 'philosophical'], 'dilemma'),
        # Theme
        (['tema', 'theme', 'ficcion', 'fiction'], 'theme'),
        # Profession
        (['profesion', 'profession', 'rol', 'role'], 'profession'),
        # Fear
        (['miedo', 'fear', 'arquetipico', 'archetypal'], 'fear'),
        # Villain
        (['villano', 'villain', 'creacion', 'creation'], 'villain'),
        # Template
        (['plantilla', 'template'], 'template'),
    ]

    tags = []
    matched = set()
    for keywords, tag in mappings:
        if tag not in matched and any(kw in text_lower for kw in keywords):
            tags.append(tag)
            matched.add(tag)

    return sorted(tags)


def parse_indice(path: Path) -> list[dict]:
    """Parse _indice.md markdown table and return list of catalog entries."""
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    content = path.read_text(encoding='utf-8')
    lines = content.split('\n')

    entries = []
    in_table = False
    header_seen = False
    separator_seen = False

    for line in lines:
        stripped = line.strip()

        # Detect table start
        if stripped.startswith('|') and stripped.endswith('|'):
            if not header_seen:
                header_seen = True
                continue
            if not separator_seen:
                # Separator row: |---|---|
                if re.match(r'^\|[\s\-:|]+\|$', stripped):
                    separator_seen = True
                continue

            # Data row: split by pipe and clean cells
            cells = [c.strip() for c in stripped.split('|')]
            # Remove leading/trailing empty strings from split
            cells = [c for c in cells if c]

            if len(cells) < 3:
                continue  # skip malformed rows

            file_path = cells[0].strip('`')
            use_case = cells[1]
            skill_raw = cells[2]

            # Skill may contain multiple comma-separated backtick paths
            # Take the first one for the schema's singular 'skill' field
            first_skill = skill_raw.split(',')[0].strip().strip('`')

            # Derive name from file stem
            file_stem = Path(file_path).stem
            name = derive_name(file_stem)

            tags = extract_tags(use_case)

            entry = {
                'name': name,
                'file': file_path,
                'use_case': use_case,
                'skill': first_skill,
                'tags': tags,
            }
            entries.append(entry)

    if not entries:
        print(f"Error: No data rows found in {path}. Check table format.", file=sys.stderr)
        sys.exit(1)

    return entries


def main():
    """Main entry point."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    indice_path = repo_root / 'plantillas' / '_indice.md'
    output_path = repo_root / 'plantillas' / '_catalog.json'

    entries = parse_indice(indice_path)

    # Write JSON with sorted keys for deterministic output
    output_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )

    print(f"Generated {output_path} with {len(entries)} entries.")


if __name__ == '__main__':
    main()
