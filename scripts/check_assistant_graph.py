#!/usr/bin/env python3
"""Read-only wiring check for the assistant's world-reading graph.

Contract: docs/architecture/ASSISTANT_WORLD_READING.md

The assistant reads the author's world through a *separate* MCP process whose
``--mundos-path`` comes from the Hermes profile. The API builds its own index on
the data root, so ``/api/{mundo}/graph/status`` can be healthy while the
assistant is blind. This script checks the MCP side only — the side that cannot
see itself.

Exit code 0 = PASS, 1 = FAIL. It never writes: it reads the data-root pointer,
the Hermes profile and the filesystem.

Usage::

    python3 scripts/check_assistant_graph.py
    python3 scripts/check_assistant_graph.py --api http://127.0.0.1:8000

Run it from the checkout (a dev tool; it is not part of the install payload).
When an installed layout exists it resolves and checks that runtime — the app
root Hermes will actually launch — never the checkout.
"""

from __future__ import annotations

import sys

# Importing the product's resolver must not leave a __pycache__ behind: this
# gate is read-only in the literal sense, including the checkout it runs from.
sys.dont_write_bytecode = True

import argparse
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

# Mirror of graph_indexer.py (_SCAN_SECTIONS / _EXCLUDE_DIRS / _EXCLUDE_FILES /
# _SKIP_PREFIXES). Deliberately duplicated: importing the indexer would make this
# check depend on the graph package's own import chain, and a wiring check must
# keep working while that package is broken.
SCAN_SECTIONS = ("lore", "personajes", "referencias")
EXCLUDE_DIRS = {
    "_context",
    "arquetipos",
    "ideas",
    "referencias",
    "wiki",
    ".history",
    ".tmp",
    ".papelera",
}
EXCLUDE_FILES = {
    "INDEX.md",
    "README.md",
    "CHANGELOG.md",
    "_Plantilla_Ficha.md",
    "00_Catalogo_Personajes.md",
}

FAILURES: list[str] = []
WARNINGS: list[str] = []


def ok(message: str) -> None:
    print(f"  PASS  {message}")


def fail(message: str, remedy: str = "") -> None:
    FAILURES.append(message)
    print(f"  FAIL  {message}")
    if remedy:
        print(f"        -> {remedy}")


def warn(message: str) -> None:
    WARNINGS.append(message)
    print(f"  WARN  {message}")


def info(message: str) -> None:
    print(f"        {message}")


def code_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_data_root(root: Path) -> Path | None:
    """Use the product's single resolver; never a code-relative fallback."""
    wiki = root / "src" / "tools" / "demiurgos-suite" / "wiki"
    if str(wiki) not in sys.path:
        sys.path.insert(0, str(wiki))
    try:
        from data_root import resolve_data_root as product_resolver

        return Path(product_resolver())
    except Exception as exc:  # noqa: BLE001 - report, never crash the check
        fail(f"no data root resolvable: {exc}", "set DEMIURGOS_DATA_ROOT or run the installer")
        return None


def resolve_installed_root(root: Path) -> Path | None:
    """The app root the Hermes profile will actually run under.

    A dev shell has no launcher env, and the checkout may hold its own stale
    ``mundos/`` copy that would mask a broken wiring. When an installed layout
    exists, that is the runtime to check — never the checkout.
    """
    env_home = os.environ.get("DEMIURGOS_HOME", "").strip()
    candidates: list[Path] = []
    if env_home:
        candidates.append(Path(env_home) / "current")
    candidates.append(Path.home() / ".demiurgos" / "current")
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    if root.name == "current":
        return root
    return None


def resolve_hermes_home(root: Path) -> Path | None:
    env = os.environ.get("HERMES_HOME", "").strip()
    if env:
        candidate = Path(env)
        return candidate if candidate.is_dir() else None
    if root.name == "current":
        candidate = root.parent / "hermes"
        if candidate.is_dir():
            return candidate
    for candidate in (Path.home() / ".demiurgos" / "hermes", Path.home() / ".hermes"):
        if candidate.is_dir():
            return candidate
    return None


def load_profile(hermes_home: Path) -> dict:
    config = hermes_home / "config.yaml"
    if not config.is_file():
        fail(f"no Hermes profile at {config}", "provision the profile or set HERMES_HOME")
        return {}
    try:
        import yaml
    except ImportError:
        fail("PyYAML is missing in this interpreter", "run with the app venv python")
        return {}
    try:
        loaded = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:  # type: ignore[attr-defined]
        fail(f"unreadable profile {config}: {exc}")
        return {}
    return loaded if isinstance(loaded, dict) else {}


_ENV_PATTERN = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def expand(value: str, inferred: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """Expand ``${env:NAME}`` placeholders.

    The two layout variables are inferred from where this script runs when the
    launcher is not in the environment (a plain dev shell), and reported as
    ``inferred`` instead of unresolved. Everything else must be exported.
    """
    missing: list[str] = []
    used_inferred: list[str] = []

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        found = os.environ.get(name, "") or inferred.get(name, "")
        if not found:
            missing.append(name)
        elif name not in os.environ:
            used_inferred.append(name)
        return found

    return _ENV_PATTERN.sub(repl, value), missing, used_inferred


def arg_value(args: list[str], flag: str) -> str:
    for index, item in enumerate(args):
        if item == flag and index + 1 < len(args):
            return args[index + 1]
        if item.startswith(flag + "="):
            return item.split("=", 1)[1]
    return ""


def read_env_world(data_root: Path) -> str:
    """``DEMIURGOS_WORLD`` from the data-root ``.env`` — same source mcp_launcher reads."""
    env_file = data_root / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("DEMIURGOS_WORLD="):
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def count_candidates(world_dir: Path) -> int:
    total = 0
    for section in SCAN_SECTIONS:
        base = world_dir / section
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            rel_parts = path.relative_to(world_dir).parts[:-1]
            if any(part in EXCLUDE_DIRS for part in rel_parts):
                continue
            if path.name in EXCLUDE_FILES or path.name.startswith("_"):
                continue
            total += 1
    return total


def api_node_count(base_url: str, world: str) -> int | None:
    url = f"{base_url.rstrip('/')}/api/{world}/graph/status"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - local URL
            import json

            payload = json.loads(response.read().decode("utf-8"))
            return int(payload.get("node_count", 0))
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API base URL for the contrast check")
    options = parser.parse_args()

    root = code_root()
    print("Assistant world-reading wiring check")
    print(f"  code root: {root}")

    data_root = resolve_data_root(root)
    if data_root is None:
        print("\nVERDICT: FAIL")
        return 1
    info(f"data root: {data_root}")
    installed = resolve_installed_root(root)
    runtime_root = installed or root
    info(
        "runtime app root (DEMIURGOS_ROOT): "
        f"{runtime_root}" + (" (installed layout)" if installed else " (dev checkout, no install detected)")
    )
    if not installed and (root / "mundos").is_dir():
        warn(
            "this checkout carries its own mundos/ copy; author data must come from the data root "
            "(contract I3) — a checkout copy can mask a broken wiring"
        )
    default_mundos = data_root / "mundos"
    if not default_mundos.is_dir():
        fail(f"data root has no mundos/: {default_mundos}")
    else:
        ok(f"data root mundos/ exists ({default_mundos})")

    hermes_home = resolve_hermes_home(root)
    if hermes_home is None:
        fail("Hermes profile directory not found", "set HERMES_HOME to the dedicated profile")
        print("\nVERDICT: FAIL")
        return 1
    info(f"hermes home: {hermes_home}")

    profile = load_profile(hermes_home)
    servers = profile.get("mcp_servers") or {}
    server = servers.get("demiurgos-graph") if isinstance(servers, dict) else None

    if not isinstance(server, dict):
        fail(
            "mcp_servers.demiurgos-graph is not registered in the profile",
            "the product must provision it (see contract §7); the assistant has no world-reading tools",
        )
        print("\nVERDICT: FAIL")
        return 1
    ok("mcp_servers.demiurgos-graph is registered")

    raw_args = server.get("args") or []
    if isinstance(raw_args, str):
        raw_args = raw_args.split()
    inferred = {
        "DEMIURGOS_ROOT": str(runtime_root),
        "DEMIURGOS_DATA_ROOT": str(data_root),
    }
    args: list[str] = []
    missing_vars: list[str] = []
    inferred_vars: list[str] = []
    for item in raw_args:
        expanded, missing, used_inferred = expand(str(item), inferred)
        missing_vars.extend(missing)
        inferred_vars.extend(used_inferred)
        args.append(expanded)

    raw_cwd = str(server.get("cwd") or "")
    cwd_expanded, cwd_missing, cwd_inferred = expand(raw_cwd, inferred) if raw_cwd else ("", [], [])
    missing_vars.extend(cwd_missing)
    inferred_vars.extend(cwd_inferred)

    if inferred_vars:
        warn(
            f"launcher variables not in this shell, inferred from the layout: "
            f"{', '.join(sorted(set(inferred_vars)))}"
        )
    if missing_vars:
        fail(
            f"unresolved profile variables: {', '.join(sorted(set(missing_vars)))}",
            "the launcher must export those variables before starting Hermes",
        )

    target = next((item for item in args if item.endswith(".py")), "")
    if not target:
        fail("the MCP server command has no python entry point")
    elif Path(target).is_file():
        ok(f"server entry exists: {target}")
    else:
        fail(
            f"server entry does not exist: {target}",
            "the profile points at code that is not installed (stale app root?)",
        )

    uses_launcher = Path(target).name == "mcp_launcher.py" if target else False
    mundo = arg_value(args, "--mundo")
    mundos_path = arg_value(args, "--mundos-path")

    if uses_launcher:
        ok("entry point is mcp_launcher.py (resolves the data root at runtime)")
        effective_mundos = default_mundos
    elif mundos_path:
        effective_mundos = Path(mundos_path)
        if not effective_mundos.is_absolute():
            # Hermes spawns the server with the profile's cwd; a relative
            # --mundos-path resolves against THAT, never against this script's
            # cwd. Joining it to our own cwd false-PASSes a blind wiring.
            base = Path(cwd_expanded) if cwd_expanded else runtime_root
            effective_mundos = (base / effective_mundos).resolve()
            info(f"relative --mundos-path resolved against the MCP cwd: {base}")
    else:
        fail("no --mundos-path in the MCP args")
        effective_mundos = Path("")

    env_world = os.environ.get("DEMIURGOS_WORLD", "").strip()
    if not mundo:
        warn("no --mundo in the MCP args; the active world is resolved at runtime")
    elif env_world and mundo != env_world:
        warn(f"--mundo '{mundo}' differs from DEMIURGOS_WORLD '{env_world}'")

    world = mundo or env_world
    if not world and effective_mundos.is_dir():
        world = read_env_world(data_root)
    if not world and effective_mundos.is_dir():
        candidates = sorted(
            entry.name
            for entry in effective_mundos.iterdir()
            if entry.is_dir() and not entry.name.startswith(("_", ".")) and entry.name.lower() != "ideas"
        )
        world = candidates[0] if candidates else ""

    if effective_mundos and str(effective_mundos):
        info(f"MCP mundos path: {effective_mundos}")
        if effective_mundos.is_dir():
            ok("MCP mundos path exists")
        else:
            fail(
                f"MCP mundos path does not exist: {effective_mundos}",
                "point it at ${env:DEMIURGOS_DATA_ROOT}/mundos or at mcp_launcher.py (contract I1)",
            )

    if not world:
        fail("no world to verify: neither --mundo nor DEMIURGOS_WORLD resolved one")
    else:
        info(f"world: {world}")
        world_dir = effective_mundos / world if str(effective_mundos) else Path("")
        if str(world_dir) and world_dir.is_dir():
            ok(f"world directory exists: {world_dir}")
            total = count_candidates(world_dir)
            if total > 0:
                ok(f"{total} candidate .md fichas under lore/, personajes/, referencias/")
            else:
                fail(f"world directory has no indexable fichas: {world_dir}")
        elif str(world_dir):
            fail(
                f"world directory missing under the MCP path: {world_dir}",
                "the MCP and the API disagree on the world; check --mundo and the data root",
            )

    # Contrast check: the API index is a different index and must not be read as
    # proof about the assistant (contract I4). A healthy API with an empty MCP is
    # exactly the incident signature.
    if world:
        api_count = api_node_count(options.api, world)
        if api_count is None:
            info(f"API not reachable at {options.api}; contrast check skipped")
        elif api_count > 0 and FAILURES:
            warn(
                f"API index reports {api_count} entities while the MCP wiring fails — "
                "this is the 2026-11-18 incident signature: the UI looks right and the assistant is blind"
            )
        elif api_count > 0:
            ok(f"API index reports {api_count} entities (context only, not proof — see I4)")

    print()
    if FAILURES:
        print(f"VERDICT: FAIL ({len(FAILURES)} problem(s), {len(WARNINGS)} warning(s))")
        print("See docs/architecture/ASSISTANT_WORLD_READING.md §5 for the mandatory gate.")
        return 1
    print(f"VERDICT: PASS ({len(WARNINGS)} warning(s))")
    print("Still complete levels B and C: a live request and one world-only question.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
