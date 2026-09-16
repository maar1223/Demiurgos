# -*- coding: utf-8 -*-
"""Guard: no NEW code-relative DATA paths in the runtime sources (WU-2).

Author data (``mundos``, ``ideas``, ``data``, ``config``, ``plantillas``,
``skills``, ``taller``, ``estado``) must be resolved through
``data_root.resolve_data_root()`` instead of being derived from ``__file__``.
The guard parses each runtime source with :mod:`ast` (so comments and
docstrings can never trip it) and applies two rules:

**Rule A — any ``parents[3..6]`` literal.** This is the historical depth. It
catches the ``parents[4]`` modules AND the ``parents[3]`` siblings
(``mcp_launcher``/``warmup_gateway``) that a ``parents[4]``-only scan would
miss, plus the ``parents[5]`` off-by-one fixed in ``graph_indexer``.

**Rule B — a data-name literal combined with a file-relative parent
expression.** Catches a regression written as ``Path(__file__).resolve()
.parent.parent / "mundos"`` (no ``parents[N]`` subscript at all) or through a
module symbol defined that way in the same file.

``CODE_PATH_ALLOWLIST`` records the sites that legitimately derive from
``__file__`` because they locate CODE, not author data: ``sys.path`` bootstraps
for sibling packages, the MCP server file locator, and the retirement gate's
checkout root. Each entry carries its reason so a reviewer sees every exemption
instead of an unexplained skip. The rule that would fire is consulted against
this map, so the known code paths cannot false-positive.

Scope: every ``*.py`` file under ``src/tools/demiurgos-suite/``, plus (WU-3)
``src/tools/idea_capture/`` and ``.hermes/plugins/``, except ``data_root.py``
(the resolver itself) and ``tests/`` (tests may legitimately name the
repository). Each scanned tree keeps its own code locator — the ``sys.path``
bootstraps that make sibling packages importable — and those entries sit in the
allowlist below with their reason.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_WIKI = Path(__file__).resolve().parent.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

SUITE_ROOT = _WIKI.parent
REPO_ROOT = _WIKI.parents[3]
IDEA_CAPTURE_ROOT = REPO_ROOT / "src" / "tools" / "idea_capture"
HERMES_PLUGINS_ROOT = REPO_ROOT / ".hermes" / "plugins"
SCAN_ROOTS = (SUITE_ROOT, IDEA_CAPTURE_ROOT, HERMES_PLUGINS_ROOT)
DATA_NAME_LITERALS = frozenset(
    {"mundos", "ideas", "data", "config", "plantillas", "skills", "taller", "estado"}
)
MIN_PARENTS_DEPTH = 3
MAX_PARENTS_DEPTH = 6

# (source file, symbol) -> why this file-relative path is CODE, not author data.
# The guard keys the allowlist on the ASSIGNMENT TARGET it reports, which is the
# local variable inside a sys.path bootstrap function, not that function's name.
CODE_PATH_ALLOWLIST: dict[tuple[str, str], str] = {
    ("api_server.py", "_HERE"): "sys.path bootstrap — locates sibling code modules",
    ("api_server.py", "_CODE_ROOT"): "locates the launcher script, a checkout artifact",
    ("assistant_settings.py", "_TOOLS_ROOT"): "sys.path bootstrap for the capability_probes package",
    ("graph_mcp_server.py", "_SCRIPT_DIR"): "sys.path bootstrap for the wiki code package",
    ("mcp_launcher.py", "_SCRIPT_DIR"): "locates the sibling graph_mcp_server.py code file",
    ("retirement_gate.py", "_WIKI"): "sys.path bootstrap for local_state/readiness modules",
    ("retirement_gate.py", "PROJECT_ROOT"): "the gate inspects install.sh/docs/src of the checkout",
    ("hermes_handler.py", "wiki"): "sys.path bootstrap in _ensure_wiki_on_path — locates the wiki code package",
    ("runtime.py", "wiki"): "sys.path bootstrap in _ensure_wiki_on_path — locates the wiki code package",
    ("__init__.py", "_CODE_ROOT"): "demiurgos-idea-capture plugin checkout root for its sys.path bootstrap",
}


class Violation:
    """One offending site: ``file:line`` plus the rule and the symbol, if any."""

    def __init__(self, path: str, line: int, rule: str, symbol: str | None) -> None:
        self.path = path
        self.line = line
        self.rule = rule
        self.symbol = symbol

    def __str__(self) -> str:  # pragma: no cover - diagnostics only
        where = f"{self.path}:{self.line}"
        symbol = f" ({self.symbol})" if self.symbol else ""
        return f"{where} [{self.rule}]{symbol}"


def _names_of(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names.extend(
                elt.id for elt in target.elts if isinstance(elt, ast.Name)
            )
    return names


def _contains_path_file(node: ast.AST) -> bool:
    """True when the expression calls ``Path(__file__)`` somewhere."""
    return any(
        isinstance(inner, ast.Call)
        and bool(inner.args)
        and isinstance(inner.args[0], ast.Name)
        and inner.args[0].id == "__file__"
        for inner in ast.walk(node)
    )


def _referenced_names(node: ast.AST) -> set[str]:
    return {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)}


def _data_literals(node: ast.AST) -> set[str]:
    return {
        inner.value
        for inner in ast.walk(node)
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
    } & DATA_NAME_LITERALS


def _enclosing_symbol(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    """The assignment target that binds *node*, when there is one."""
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.Assign, ast.AnnAssign)):
            names = _names_of(current)
            return names[0] if names else None
        current = parents.get(current)
    return None


def scan_source(
    source: str,
    relpath: str,
    *,
    allowlist: dict[tuple[str, str], str] = CODE_PATH_ALLOWLIST,
) -> list[Violation]:
    """Return every code-relative DATA path in one source file."""
    basename = Path(relpath).name
    tree = ast.parse(source)

    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
    ]
    # A symbol is file-relative when its value derives from __file__, directly or
    # through another file-relative symbol (fixpoint over a handful of levels).
    file_relative: set[str] = set()
    for _ in range(len(assignments) + 1):
        before = len(file_relative)
        for node in assignments:
            assert node.value is not None
            derives = _contains_path_file(node.value) or bool(
                _referenced_names(node.value) & file_relative
            )
            if derives:
                file_relative.update(_names_of(node))
        if len(file_relative) == before:
            break

    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    violations: list[Violation] = []
    seen: set[tuple[int, str | None, str]] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "parents"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)
            and MIN_PARENTS_DEPTH <= node.slice.value <= MAX_PARENTS_DEPTH
        ):
            symbol = _enclosing_symbol(node, parents)
            key = (node.lineno, symbol, "parents-depth")
            if (basename, symbol) not in allowlist and key not in seen:
                seen.add(key)
                violations.append(Violation(relpath, node.lineno, "parents-depth", symbol))

    # Rule B: only a single path-join (``/``) expresses "this data literal lives
    # under this file-relative parent". A list literal that merely contains both
    # an unrelated file-relative value and a data name is not an offence.
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            continue
        if not _data_literals(node):
            continue
        if not (_contains_path_file(node)
                or _referenced_names(node) & file_relative):
            continue
        symbol = _enclosing_symbol(node, parents)
        key = (node.lineno, symbol, "data-adjacent")
        if (basename, symbol) not in allowlist and key not in seen:
            seen.add(key)
            violations.append(Violation(relpath, node.lineno, "data-adjacent", symbol))
    return violations


def scan_tree(
    root: Path,
    *,
    allowlist: dict[tuple[str, str], str] = CODE_PATH_ALLOWLIST,
) -> list[Violation]:
    """Scan every runtime source under *root*, skipping tests and the resolver."""
    violations: list[Violation] = []
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts
        if "tests" in parts or path.name == "data_root.py" or "__pycache__" in parts:
            continue
        violations.extend(
            scan_source(path.read_text(encoding="utf-8"), str(path.relative_to(root)),
                        allowlist=allowlist)
        )
    return violations


def test_runtime_sources_have_no_code_relative_data_paths() -> None:
    """The real tree is clean: every author-data path goes through the resolver."""
    violations = [v for root in SCAN_ROOTS for v in scan_tree(root)]
    assert violations == [], "code-relative data paths: " + "; ".join(
        str(v) for v in violations
    )


def _scan_tmp(tmp_path: Path, name: str, source: str) -> list[Violation]:
    (tmp_path / name).write_text(source, encoding="utf-8")
    return scan_tree(tmp_path, allowlist=CODE_PATH_ALLOWLIST)


def test_catches_parents4_data_path_regression(tmp_path: Path) -> None:
    """Rule A catches the ``parents[4]`` form the migration removed."""
    source = 'ROOT = Path(__file__).resolve().parents[4]\nMUNDOS = ROOT / "mundos"\n'
    violations = _scan_tmp(tmp_path, "regressed.py", source)
    assert {v.rule for v in violations} == {"parents-depth", "data-adjacent"}
    assert all(v.symbol in {"ROOT", "MUNDOS"} for v in violations)


def test_catches_parents3_data_path_regression(tmp_path: Path) -> None:
    """Rule A also catches ``parents[3]`` — a ``parents[4]``-only grep misses it."""
    source = 'ROOT = Path(__file__).resolve().parents[3]\nMUNDOS = ROOT / "mundos"\n'
    violations = _scan_tmp(tmp_path, "regressed.py", source)
    assert {v.rule for v in violations} == {"parents-depth", "data-adjacent"}


def test_catches_file_relative_parent_without_a_parents_subscript(tmp_path: Path) -> None:
    """Rule B catches ``.parent.parent / "mundos"``: no ``parents[N]`` to grep."""
    source = 'MUNDOS = Path(__file__).resolve().parent.parent / "mundos"\n'
    violations = _scan_tmp(tmp_path, "regressed.py", source)
    assert [v.rule for v in violations] == ["data-adjacent"]


def test_ignores_a_code_path_allowlisted_symbol(tmp_path: Path) -> None:
    """An allowlisted code-path symbol is exempt, by symbol, with a reason."""
    source = 'PROJECT_ROOT = Path(__file__).resolve().parents[4]\n'
    violations = _scan_tmp(tmp_path, "retirement_gate.py", source)
    assert violations == []
    assert ("retirement_gate.py", "PROJECT_ROOT") in CODE_PATH_ALLOWLIST


def test_ignores_data_literals_that_are_not_file_relative(tmp_path: Path) -> None:
    """A plain relative data literal is not a code-relative data path."""
    source = 'LOCK = Path("data") / "idea-capture.sqlite3.lock"\n'
    assert _scan_tmp(tmp_path, "not_relative.py", source) == []


def test_ignores_mentions_inside_comments_and_docstrings(tmp_path: Path) -> None:
    """Comments/docstrings may document the removed literals — AST never sees them."""
    source = '"""Old form: parents[4] and _HERE.parents[3] are gone."""\n# parents[5]\n'
    assert _scan_tmp(tmp_path, "documented.py", source) == []
