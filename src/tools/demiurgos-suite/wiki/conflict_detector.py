"""Deterministic world conflicts — S1 of the Conflictos section.

Pure and read-only. The detector takes the entity dicts the graph index already
caches (the filesystem is never read here) and returns the structural conflicts
the Author can act on. It never writes, never calls a model, and never decides
canon: the Author does.

Closed code set (S3):

* ``version`` — the ficha declares an unsupported OKF version.
* ``missing-minimum`` — the ficha lacks a required minimum for its shape/type.
* ``unresolved-reference`` — a body ``[[wikilink]]`` resolves to no entity.
* ``ambiguous-reference`` — a reference resolves to more than one entity.
* ``duplicate-id`` — two fichas share the same canonical id.
* ``dangling-relation`` — a ``relaciones`` entry points to no entity.
* ``self-relation`` — a ``relaciones`` entry points to the entity itself.
* ``canon-state-mismatch`` — ``status`` and ``canon_state`` claim opposite
  things about the same draft/canon axis.

Severity (S4): ``error`` when the graph cannot be trusted, ``warning`` when the
ficha is incomplete or internally incoherent but resolvable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from import_relations import relaciones_entry_key

ERROR = "error"
WARNING = "warning"

_SEVERITY_BY_CODE: dict[str, str] = {
    "version": ERROR,
    "unresolved-reference": ERROR,
    "ambiguous-reference": ERROR,
    "duplicate-id": ERROR,
    "dangling-relation": ERROR,
    "self-relation": ERROR,
    "missing-minimum": WARNING,
    "canon-state-mismatch": WARNING,
}

# The two hard contradictions of the same draft/canon axis. Other canon states
# (creencia, leyenda, hipotesis, perdido, prohibido) are orthogonal to
# draft/stable and are never flagged.
_CANON_STATE_CONTRADICTIONS = frozenset({
    ("draft", "canon"),
    ("stable", "propuesta"),
})

# Codes already surfaced by the graph index's own OKF pass.
_INDEX_ISSUE_CODES = frozenset({"version", "missing-minimum"})

_RE_BODY_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")

_RELATION_KEY_FIELDS = ("target_id", "target", "id", "name")


@dataclass(frozen=True)
class Conflict:
    """One deterministic conflict attached to a ficha."""

    id: str
    code: str
    severity: str
    path: str
    name: str
    message: str
    field: str | None = None
    reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "name": self.name,
            "message": self.message,
            "field": self.field,
            "reference": self.reference,
        }


def _make(
    code: str,
    path: str,
    name: str,
    message: str,
    *,
    field: str | None = None,
    reference: str | None = None,
) -> Conflict:
    return Conflict(
        id=f"{code}:{path}:{reference or field or ''}",
        code=code,
        severity=_SEVERITY_BY_CODE[code],
        path=path,
        name=name,
        message=message,
        field=field,
        reference=reference,
    )


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _relation_key(entry: Any) -> str:
    """Normalize one ``relaciones`` entry to the key the graph resolves.

    Frontmatter entries are usually bare canonical ids or ``[[Name]]``
    wikilinks, but a structured entry (``target_id``) is accepted too.
    """
    if isinstance(entry, dict):
        for field in _RELATION_KEY_FIELDS:
            value = entry.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    return relaciones_entry_key(str(entry))


def detect_conflicts(
    entities: Iterable[dict[str, Any]],
    *,
    resolve_candidates: Callable[[str], Iterable[str]],
) -> list[Conflict]:
    """Return every deterministic conflict in the world, sorted for the panel.

    ``resolve_candidates`` maps a wikilink/relation key to the entity paths it
    can match (the same resolver the graph index uses to surface ambiguous
    references). Ordering is stable: errors before warnings, then by ficha path,
    then by code and reference, so the panel never reshuffles between requests.
    """
    ordered = sorted(
        (entity for entity in entities if isinstance(entity, dict)),
        key=lambda entity: str(entity.get("path", "")),
    )

    paths_by_id: dict[str, list[str]] = {}
    for entity in ordered:
        entity_id = str(entity.get("id") or "")
        if entity_id:
            paths_by_id.setdefault(entity_id, []).append(str(entity.get("path", "")))

    conflicts: list[Conflict] = []
    for entity in ordered:
        path = str(entity.get("path", ""))
        name = str(entity.get("name", ""))
        entity_id = str(entity.get("id") or "")
        seen_references: set[str] = set()

        if entity_id and len(paths_by_id[entity_id]) > 1:
            others = [other for other in paths_by_id[entity_id] if other != path]
            conflicts.append(
                _make(
                    "duplicate-id",
                    path,
                    name,
                    f"Canonical id {entity_id!r} is shared with: {', '.join(others)}.",
                    reference=entity_id,
                )
            )

        status = str(entity.get("status") or "draft")
        canon_state = str(entity.get("canon_state") or "")
        if (status, canon_state) in _CANON_STATE_CONTRADICTIONS:
            conflicts.append(
                _make(
                    "canon-state-mismatch",
                    path,
                    name,
                    f"status {status!r} contradicts canon_state {canon_state!r}.",
                    field="canon_state",
                )
            )

        for issue in entity.get("okf_issues") or []:
            if not isinstance(issue, dict):
                continue
            code = str(issue.get("code") or "")
            if code not in _INDEX_ISSUE_CODES:
                continue
            field = issue.get("field")
            conflicts.append(
                _make(
                    code,
                    path,
                    name,
                    str(issue.get("message") or ""),
                    field=str(field) if field else None,
                )
            )

        for link in _unique(_RE_BODY_WIKILINK.findall(str(entity.get("content") or ""))):
            key = link.strip()
            if not key or key in seen_references:
                continue
            seen_references.add(key)
            candidates = list(resolve_candidates(key))
            if not candidates:
                conflicts.append(
                    _make(
                        "unresolved-reference",
                        path,
                        name,
                        f"Wikilink [[{key}]] does not resolve to any entity.",
                        reference=key,
                    )
                )
            elif len(candidates) > 1:
                conflicts.append(
                    _make(
                        "ambiguous-reference",
                        path,
                        name,
                        f"Wikilink [[{key}]] is ambiguous: it resolves to "
                        f"{len(candidates)} entities.",
                        reference=key,
                    )
                )

        for entry in entity.get("relaciones") or []:
            key = _relation_key(entry)
            if not key or key in seen_references:
                continue
            seen_references.add(key)
            candidates = list(resolve_candidates(key))
            if not candidates:
                conflicts.append(
                    _make(
                        "dangling-relation",
                        path,
                        name,
                        f"Relation target {key!r} does not resolve to any entity.",
                        reference=key,
                    )
                )
            elif len(candidates) == 1 and candidates[0] == path:
                conflicts.append(
                    _make(
                        "self-relation",
                        path,
                        name,
                        f"Ficha declares a relation to itself ({key!r}).",
                        reference=key,
                    )
                )
            elif len(candidates) > 1:
                conflicts.append(
                    _make(
                        "ambiguous-reference",
                        path,
                        name,
                        f"Relation target {key!r} is ambiguous: it resolves to "
                        f"{len(candidates)} entities.",
                        reference=key,
                    )
                )

    conflicts.sort(
        key=lambda conflict: (
            0 if conflict.severity == ERROR else 1,
            conflict.path,
            conflict.code,
            conflict.reference or "",
            conflict.field or "",
        )
    )
    return conflicts


def summarize(conflicts: Iterable[Conflict]) -> dict[str, Any]:
    """Counts the panel header shows: total, by severity, by code."""
    by_code: dict[str, int] = {}
    errors = 0
    warnings = 0
    total = 0
    for conflict in conflicts:
        total += 1
        by_code[conflict.code] = by_code.get(conflict.code, 0) + 1
        if conflict.severity == ERROR:
            errors += 1
        else:
            warnings += 1
    return {
        "total": total,
        "errors": errors,
        "warnings": warnings,
        "by_code": dict(sorted(by_code.items())),
    }
