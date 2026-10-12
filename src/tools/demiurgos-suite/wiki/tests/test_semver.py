"""Focused tests for the hand-rolled SemVer 2.0.0 comparator (``semver``).

Covers the canonical precedence table from the change design plus a source guard
proving the module neither imports ``packaging`` nor references
``methodology_library._version_key`` (both forbidden by the change spec).
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from semver import SemVerError, compare, is_prerelease, parse_version  # noqa: E402

_MODULE_PATH = _WIKI / "semver.py"


def _assert_less(lower: str, higher: str) -> None:
    """Assert strict ordering in both directions."""
    assert compare(lower, higher) == -1, f"expected {lower!r} < {higher!r}"
    assert compare(higher, lower) == 1, f"expected {higher!r} > {lower!r}"


def _assert_equal(left: str, right: str) -> None:
    """Assert equal precedence in both directions."""
    assert compare(left, right) == 0, f"expected {left!r} == {right!r}"
    assert compare(right, left) == 0, f"expected {right!r} == {left!r}"


@pytest.mark.parametrize("lower,higher", [
    ("0.2.0-beta.1", "0.2.0"),
    ("0.2.0-beta.1", "0.2.0-beta.2"),
    ("1.0.0-alpha", "1.0.0-alpha.1"),
    ("1.0.0-1", "1.0.0-alpha"),
    ("1.0.0", "1.0.1"),
    ("1.0.1", "1.1.0"),
    ("1.1.0", "2.0.0"),
])
def test_less_than(lower: str, higher: str) -> None:
    _assert_less(lower, higher)


@pytest.mark.parametrize("left,right", [
    ("1.0.0+build.5", "1.0.0"),
    ("1.0.0+foo", "1.0.0+bar"),
    ("v0.1.1", "0.1.1"),
    ("0.2.0", "0.2.0"),
])
def test_equal_precedence(left: str, right: str) -> None:
    _assert_equal(left, right)


def test_canonical_prerelease_chain() -> None:
    """The canonical SemVer §11 chain is strictly increasing."""
    chain = [
        "1.0.0-alpha",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
    ]
    for lower, higher in zip(chain, chain[1:]):
        _assert_less(lower, higher)


def test_numeric_identifier_sorts_below_alphanumeric() -> None:
    _assert_less("1.0.0-1", "1.0.0-alpha")


def test_build_metadata_is_ignored_for_precedence() -> None:
    _assert_equal("1.0.0+build.5", "1.0.0")
    _assert_equal("1.0.0+foo", "1.0.0+bar")


def test_parse_version_shape() -> None:
    assert parse_version("v0.1.1") == (0, 1, 1, ())
    assert parse_version("0.2.0+build.5") == (0, 2, 0, ())
    assert parse_version("1.0.0-alpha.1") == (1, 0, 0, ("alpha", "1"))


@pytest.mark.parametrize("value,expected", [
    ("0.2.0-beta.1", True),
    ("v1.0.0-rc.1", True),
    ("0.2.0", False),
    ("1.0.0+build.5", False),
])
def test_is_prerelease(value: str, expected: bool) -> None:
    assert is_prerelease(value) is expected


@pytest.mark.parametrize("value", [
    "not-a-version",
    "",
    "1.0",
    "1.0.0.0",
    "1.0.0-",
    "1.x.0",
])
def test_malformed_values_raise(value: str) -> None:
    with pytest.raises(SemVerError):
        parse_version(value)
    with pytest.raises(SemVerError):
        compare(value, "1.0.0")
    with pytest.raises(SemVerError):
        compare("1.0.0", value)


def _module_tree() -> ast.Module:
    return ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))


def test_semver_module_does_not_import_packaging() -> None:
    """The module must not import ``packaging`` (no new dependency allowed)."""
    imported: set[str] = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert "packaging" not in imported, f"semver imports packaging: {sorted(imported)}"
    assert not any(name == "packaging" or name.startswith("packaging.")
                   for name in imported)


def test_semver_module_never_references_version_key() -> None:
    """The module must not reference ``methodology_library._version_key``."""
    referenced: set[str] = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            referenced.add(node.attr)
        elif isinstance(node, ast.alias):
            referenced.add(node.name.rsplit(".", 1)[-1])
    assert "_version_key" not in referenced, "semver references _version_key"
