#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Derive the runtime payload manifest from real import/resolve sites (S0-D).

Walks the app entrypoints (``api_server.py``, ``idea_capture_ui.py``,
``telegram_settings.py``, ``assistant_settings.py``) with ``ast``, extracts
every import and every ``_CODE_ROOT``-relative resource resolution, maps each
to a repo path, and emits ``payload_manifest.json`` — the file-level allow-list
that the release audit (S5b) treats as default-DENY.

Rules (design v2 S0-D + tasks-v2 errata D4, applied literally):

- Imports inside ``if TYPE_CHECKING:`` blocks are **type-only**: they never
  force a runtime payload entry. They are recorded separately for audit.
- A top-level module name resolves to a repo path only when a matching file or
  directory exists under ``src/tools/`` or ``src/tools/demiurgos-suite/``;
  anything else (stdlib, third-party) is external, satisfied by
  ``requirements.txt``, and recorded for traceability.
- The walk is transitive over resolved repo modules, so ``sync_lore`` is
  included because of the *runtime* sites (``import_vision.py:226``,
  ``import_analysis.py:430/486/491/494``, ``import_enrichment.py:112``), not
  the type-only ``TYPE_CHECKING`` blocks — the evidence is emitted per
  top-level external package so the D4 justification is derivable, not
  hand-maintained.
- ``data/methodology/seeds/**`` is mandated runtime data (Skill Madre,
  10 tracked files); ``plantillas/**`` is author data (``data_root.py:4-5``)
  and is denied, as are tests and bytecode.
- The payload lists concrete files (no bare directory globs): the audit ships
  exactly what the manifest names.

Run: ``python scripts/derive_payload_manifest.py`` from the repo root.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

WIKI_DIR = REPO_ROOT / "src" / "tools" / "demiurgos-suite" / "wiki"
SUITE_DIR = WIKI_DIR.parent
TOOLS_DIR = SUITE_DIR.parent

ENTRYPOINTS = [
    WIKI_DIR / "api_server.py",
    WIKI_DIR / "idea_capture_ui.py",
    WIKI_DIR / "telegram_settings.py",
    WIKI_DIR / "assistant_settings.py",
]

# Anchors the runtime puts on sys.path (api_server.py:27-33 inserts the suite
# and tools dirs; the launcher/tests add the wiki dir). A top-level name is
# resolved against every anchor and EVERY existing candidate is shipped, so a
# sys.path order difference can never silently drop a runtime module.
_ANCHORS = (WIKI_DIR, SUITE_DIR, TOOLS_DIR)

# Denied at emit: author data, tests, bytecode. `plantillas/` is the S0-D
# required removal; the rest keeps the runtime allow-list free of dead weight.
_DENIED = ("plantillas/**", "**/tests/**", "**/__pycache__/**", "**/*.pyc")

# Mandated runtime data (Skill Madre, 10 tracked files) — not reachable via
# imports because it is data, not code.
MANDATED = ("data/methodology/seeds/**",)

# The app package itself: the entrypoints live in it and boot requires the
# package to be complete (dynamic/importlib loads are invisible to ``ast``).
APP_PACKAGE = "src/tools/demiurgos-suite/wiki/**"
SUITE_REFERENCE = "src/tools/demiurgos-suite/requirements.txt"


class _ImportSite:
    __slots__ = ("file", "line", "module", "type_only")

    def __init__(self, file: Path, line: int, module: str, type_only: bool):
        self.file = file
        self.line = line
        self.module = module
        self.type_only = type_only

    def as_dict(self) -> dict:
        return {
            "file": str(self.file.relative_to(REPO_ROOT)),
            "line": self.line,
            "module": self.module,
            "type_only": self.type_only,
        }


def _top_level(module: str) -> str:
    return module.split(".")[0]


def _resolve_candidates(top: str) -> list[Path]:
    """Every repo location a top-level name may resolve to."""
    if top == "wiki":
        return [WIKI_DIR]
    found: list[Path] = []
    for anchor in _ANCHORS:
        file_candidate = anchor / f"{top}.py"
        dir_candidate = anchor / top
        if file_candidate.is_file():
            found.append(file_candidate)
        if dir_candidate.is_dir():
            found.append(dir_candidate)
    return found


def _is_repo_module(top: str) -> bool:
    return bool(_resolve_candidates(top)) or top == "wiki"


def _is_denied(rel: Path) -> bool:
    text = "/".join(rel.parts)
    return any(text == p or text.endswith(p.lstrip("*")) for p in ("plantillas",)) or (
        "/tests/" in text
        or text.endswith("/tests")
        or "/__pycache__/" in text
        or text.endswith("/__pycache__")
        or text.endswith(".pyc")
    )


def _iter_py_files(target: Path) -> list[Path]:
    """Python files under a resolved target, skipping denied subtrees."""
    if target.is_file() and target.suffix == ".py":
        if _is_denied(target.relative_to(REPO_ROOT)):
            return []
        return [target]
    if target.is_dir():
        return [
            p
            for p in sorted(target.rglob("*.py"))
            if not _is_denied(p.relative_to(REPO_ROOT))
        ]
    return []


def _collect_imports(tree: ast.AST, source_path: Path) -> list[_ImportSite]:
    """All import sites with their TYPE_CHECKING context (D4)."""
    sites: list[_ImportSite] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._type_checking = 0

        def visit_If(self, node: ast.If) -> None:
            is_tc = isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
            if is_tc:
                self._type_checking += 1
            self.generic_visit(node)
            if is_tc:
                self._type_checking -= 1

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                sites.append(
                    _ImportSite(source_path, node.lineno, alias.name, self._type_checking > 0)
                )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module and not node.level:  # skip relative imports (same package)
                sites.append(
                    _ImportSite(source_path, node.lineno, node.module, self._type_checking > 0)
                )

    _Visitor().visit(tree)
    return sites


def _collect_code_root_resources(tree: ast.AST, source_path: Path) -> list[Path]:
    """``_CODE_ROOT / "a" / "b"`` chains -> repo-relative resource paths.

    Only the OUTERMOST chain is accepted: the inner ``_CODE_ROOT / "a"``
    sub-chain of ``_CODE_ROOT / "a" / "b"`` is a partial resolution that would
    drag in the whole directory instead of the exact resource.
    """
    resources: list[Path] = []

    def _chain(node: ast.AST) -> Path | None:
        parts: list[str] = []
        current = node
        while isinstance(current, ast.BinOp) and isinstance(current.op, ast.Div):
            if isinstance(current.right, ast.Constant) and isinstance(current.right.value, str):
                parts.append(current.right.value)
            else:
                return None
            current = current.left
        if isinstance(current, ast.Name) and current.id == "_CODE_ROOT":
            return Path(*reversed(parts))
        return None

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Div):
            continue  # inner node of a larger chain — the outer one owns it
        resolved = _chain(node)
        if resolved is not None and not resolved.is_absolute() and ".." not in resolved.parts:
            resources.append(resolved)
    return resources


def _expand_to_files(rel_dir: Path) -> set[str]:
    """Concrete repo-relative files under a directory, minus denied."""
    return {
        str(p.relative_to(REPO_ROOT))
        for p in REPO_ROOT.joinpath(rel_dir).rglob("*")
        if p.is_file() and not _is_denied(p.relative_to(REPO_ROOT))
    }


def main() -> int:
    runtime_sites: list[_ImportSite] = []
    type_only_sites: list[_ImportSite] = []
    external: set[str] = set()
    resources: list[Path] = []

    worklist: list[Path] = [ep for ep in ENTRYPOINTS if ep.is_file()]
    seen_files: set[Path] = set()
    resolved_tops: set[str] = set()

    while worklist:
        source = worklist.pop(0)
        if source in seen_files:
            continue
        seen_files.add(source)
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, SyntaxError):
            continue

        for site in _collect_imports(tree, source):
            top = _top_level(site.module)
            if site.type_only:
                type_only_sites.append(site)
            else:
                runtime_sites.append(site)
            if _is_repo_module(top):
                if top not in resolved_tops:
                    resolved_tops.add(top)
                for candidate in _resolve_candidates(top):
                    if candidate not in seen_files:
                        worklist.extend(_iter_py_files(candidate))
            else:
                external.add(top)

        for resource in _collect_code_root_resources(tree, source):
            resources.append(resource)

    # File-level allow-list: app package + suite reference + resolved external
    # packages + _CODE_ROOT resources + mandated seeds, minus denied.
    payload: set[str] = {SUITE_REFERENCE}
    payload |= _expand_to_files(Path("src/tools/demiurgos-suite/wiki"))
    for top in sorted(resolved_tops):
        for candidate in _resolve_candidates(top):
            rel = candidate.relative_to(REPO_ROOT)
            if _is_denied(rel):
                continue
            if candidate.is_dir():
                payload |= _expand_to_files(rel)
            else:
                payload.add(str(rel))
    for resource in resources:
        rel = resource
        target = REPO_ROOT / rel
        if target.is_file() and not _is_denied(rel):
            payload.add(str(rel))
        elif target.is_dir():
            payload |= _expand_to_files(rel)
    for mandated in MANDATED:
        payload |= _expand_to_files(Path(mandated.rstrip("/**")))

    # D4 evidence: runtime sites per TOP-LEVEL external package (resolved
    # outside the app package) — the derivation of why a package ships.
    evidence: dict[str, list[dict]] = {}
    for site in runtime_sites:
        if site.type_only:
            continue
        top = _top_level(site.module)
        if top not in resolved_tops:
            continue
        if not any(
            str(c.relative_to(REPO_ROOT)).startswith("src/tools/demiurgos-suite/wiki")
            for c in _resolve_candidates(top)
        ):
            evidence.setdefault(top, []).append(
                {"file": site.as_dict()["file"], "line": site.line}
            )

    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — best-effort provenance
        head = "unknown"

    manifest = {
        "schema_version": 1,
        "generated_by": "scripts/derive_payload_manifest.py",
        "source_commit": head,
        "entrypoints": [str(ep.relative_to(REPO_ROOT)) for ep in ENTRYPOINTS],
        "payload": sorted(payload),
        "mandated": list(MANDATED),
        "denied": list(_DENIED),
        "external_modules": sorted(external),
        "type_only_import_sites": sorted(
            (s.as_dict() for s in type_only_sites),
            key=lambda d: (d["file"], d["line"]),
        ),
        "runtime_import_evidence": {
            module: sorted(sites, key=lambda d: (d["file"], d["line"]))
            for module, sites in sorted(evidence.items())
        },
    }

    out = REPO_ROOT / "payload_manifest.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(REPO_ROOT)} ({len(payload)} payload files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())