"""
MCP launcher — resolves the active world at startup and delegates to the
graph MCP server.

Why this exists: on a fresh Demiurgos install there is no world yet, and the
world name is chosen by the user during onboarding. Hardcoding `--mundo=X`
in the Hermes profile config would break when the user names their world
something else. This launcher:

1. Reads DEMIURGOS_WORLD from the project .env (canonical source), OR
2. Falls back to the first world directory found under mundos/, OR
3. Uses an empty world name (server still starts; index is empty).

Usage (as configured in the Hermes profile)::

    python mcp_launcher.py

The launcher re-executes graph_mcp_server.py with the resolved --mundo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Project root: wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> project/
_SCRIPT_DIR = Path(__file__).resolve().parent
_SUITE_DIR = _SCRIPT_DIR.parent
_PROJECT_ROOT = _SCRIPT_DIR.parents[3]  # wiki -> demiurgos-suite -> tools -> src -> root


def _resolve_mundo() -> str:
    """Resolve the active world name.

    Priority:
      1. DEMIURGOS_WORLD env var
      2. DEMIURGOS_WORLD=... line in project .env
      3. First subdirectory of mundos/ (excluding hidden / Ideas)
      4. "" (no world yet — server starts with an empty index)
    """
    env_val = os.getenv("DEMIURGOS_WORLD", "").strip()
    if env_val:
        return env_val

    env_file = _PROJECT_ROOT / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DEMIURGOS_WORLD="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
        except OSError:
            pass

    mundos_dir = _PROJECT_ROOT / "mundos"
    if mundos_dir.is_dir():
        candidates = [
            d.name
            for d in sorted(mundos_dir.iterdir())
            if d.is_dir()
            and not d.name.startswith("_")
            and d.name.lower() not in ("ideas",)
        ]
        if candidates:
            return candidates[0]

    return ""


def main() -> int:
    """Resolve the active world and run the graph MCP server in-process."""
    import runpy

    mundo = _resolve_mundo()
    server = _SCRIPT_DIR / "graph_mcp_server.py"
    if mundo:
        os.environ["DEMIURGOS_WORLD"] = mundo

    # Run the server in the SAME process (same interpreter, same stdio pipes)
    # with simulated argv — avoids execv path-resolution issues on Windows
    # and keeps the MCP stdio transport intact.
    sys.argv = [
        str(server),
        f"--mundo={mundo}",
        f"--mundos-path={_PROJECT_ROOT / 'mundos'}",
    ]
    runpy.run_path(str(server), run_name="__main__")
    return 0  # unreachable — server runs until shutdown


if __name__ == "__main__":
    sys.exit(main())
