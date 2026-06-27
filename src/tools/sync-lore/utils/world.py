"""
utils/world.py — World discovery for sync-lore.

Reuses the pattern from sync-ideas.py but WITHOUT sys.exit.
Returns None for generic mode (no world detected).
"""

import os
import sys
from pathlib import Path


def discover_world() -> str | None:
    """
    Discover the active narrative world.

    Priority:
    1. DEMIURGOS_WORLD environment variable
    2. First subdirectory of mundos/ (dynamic discovery)
    3. None — fall back to generic mode (no world association)

    Returns:
        World name string or None for generic mode.
    """
    # 1. Environment variable
    world = os.environ.get("DEMIURGOS_WORLD")
    if world:
        validate_world_structure(world)
        return world

    # 2. Scan mundos/ directory
    mundos_dir = Path("mundos")
    if mundos_dir.exists():
        subdirs = sorted([d.name for d in mundos_dir.iterdir() if d.is_dir()])
        if subdirs:
            world = subdirs[0]
            validate_world_structure(world)
            return world

    # 3. No world found — generic mode
    return None


def validate_world_structure(world: str) -> list[str]:
    """
    Soft-validate that a world has the expected narrative structure.

    Checks for mundos/{world}/Personajes/ and mundos/{world}/Lore/.
    Prints warnings for missing directories. Does NOT block execution.

    Returns:
        List of missing expected directories.
    """
    expected = ["Personajes", "Lore"]
    missing = []
    world_base = Path("mundos") / world
    for d in expected:
        if not (world_base / d).exists():
            missing.append(d)
    if missing:
        print(
            f"  \u26a0 El mundo '{world}' no tiene: {', '.join(missing)}.",
            file=sys.stderr,
        )
        print(
            f"     Estructura esperada: mundos/{world}/{{Personajes, Lore, ...}}",
            file=sys.stderr,
        )
    return missing
