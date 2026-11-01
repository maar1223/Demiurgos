"""Grounded relation extraction for imported fichas.

The importer must not ask a model to invent ``relaciones`` from a batch of
summaries. That produced complete graphs for batch mates (every ficha of a
family linked to every other one) and an empty list for documents that
produced a single ficha. See ``odd/tasks/importer-relaciones-grounding.md``.

Relations are therefore extracted from the ficha BODY, deterministically, and
every returned relation carries the evidence that justifies it. The model may
still classify relationship *type*; it no longer decides *which* pairs exist.

Evidence kinds, strongest first:

* ``full-name`` — the target's title appears in the body.
* ``alias`` — the segment after a dash in the title (``X – Enlace``).
* ``stem`` — a distinctive token of the target's filename stem.
* ``ordinal`` — ``Stal N`` against ``1er/2do/3ro/...`` phrasings.
* ``folder-index`` — the folder's index file (``<folder>/<folder>.md``): the
  belonging relation, derived from the path and never authored by the model.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

#: Hard cap per ficha. Keeps an index page readable and the response small.
MAX_RELATIONS = 12

#: Structural words that never count as distinctive evidence on their own (a
#: stem token or an alias made only of these proves nothing). Family words are
#: NOT listed here: they are derived from the source's own filename/folder, so
#: the module stays world-agnostic.
GENERIC_WORDS: frozenset[str] = frozenset(
    {
        "del",
        "los",
        "las",
        "una",
        "uno",
        "que",
        "con",
        "por",
        "para",
        "como",
        "sobre",
        "sus",
        "este",
        "esta",
        "mundo",
        "lore",
        "personajes",
        "referencias",
    }
)

#: Evidence priorities; lower wins when a target matches several ways.
_EVIDENCE_PRIORITY = {
    "full-name": 0,
    "alias": 1,
    "stem": 2,
    "ordinal": 3,
    "folder-index": 4,
}

_ORDINALS = {
    "1": ("1er", "1ro", "primer"),
    "2": ("2do", "segundo"),
    "3": ("3er", "3ro", "tercer"),
    "4": ("4to", "cuarto"),
    "5": ("5to", "quinto"),
    "6": ("6to", "sexto"),
    "7": ("7mo", "septimo"),
    "8": ("8vo", "octavo"),
    "9": ("9no", "noveno"),
}


@dataclass(frozen=True)
class RelationTarget:
    """One entity the extraction may link to."""

    canonical_id: str
    name: str
    path: str = ""


@dataclass(frozen=True)
class GroundedRelation:
    """A relation plus the evidence that justifies it."""

    canonical_id: str
    evidence: str


def build_relation_targets(candidates: Iterable[object]) -> list[RelationTarget]:
    """Project import candidates (or entity dicts) into relation targets.

    Accepts anything with ``canonical_id``/``normalized_identity``,
    ``display_title``/``name``/``title`` and ``materialized_path``/``path`` so
    the funnel, the repair script and the tests share one projection.
    """

    targets: list[RelationTarget] = []
    for candidate in candidates:
        canonical_id = (
            getattr(candidate, "canonical_id", "")
            or getattr(candidate, "normalized_identity", "")
            or _dict_get(candidate, "canonical_id")
            or _dict_get(candidate, "id")
        )
        name = (
            getattr(candidate, "display_title", "")
            or getattr(candidate, "name", "")
            or getattr(candidate, "normalized_identity", "")
            or _dict_get(candidate, "display_title")
            or _dict_get(candidate, "name")
            or _dict_get(candidate, "title")
        )
        path = (
            getattr(candidate, "materialized_path", "")
            or _dict_get(candidate, "materialized_path")
            or getattr(candidate, "path", "")
            or _dict_get(candidate, "path")
        )
        if not canonical_id or not name:
            continue
        targets.append(
            RelationTarget(
                canonical_id=str(canonical_id),
                name=str(name),
                path=str(path or ""),
            )
        )
    return targets


def grounded_relations(
    *,
    body: str,
    source_id: str,
    source_path: str,
    targets: Sequence[RelationTarget],
    max_relations: int = MAX_RELATIONS,
    structural_uncapped: bool = False,
) -> list[GroundedRelation]:
    """Return the relations the body itself justifies.

    Deterministic: the same body, source and targets always produce the same
    list (evidence priority, then canonical id). No relation is invented from
    batch membership, and a ficha never links to itself.

    ``structural_uncapped`` keeps every ``folder-index`` relation (the folder's
    own index and each member's belonging edge) outside ``max_relations``. The
    cap exists to keep an LLM response small and an index page readable; folder
    membership is exact truth bounded by the folder itself, and truncating it
    silently loses part of the map.
    """

    body_norm = _normalize(body or "")
    generic = _generic_tokens(source_path)
    ambiguous = _ambiguous_identity_keys(targets)
    structural = structural_relations(
        source_id=source_id, source_path=source_path, targets=targets
    )

    best: dict[str, tuple[int, str]] = {}
    for target in targets:
        if not target.canonical_id or target.canonical_id == source_id:
            continue
        if target.path and source_path and target.path == source_path:
            continue

        evidence = _match_target(target, body_norm, generic, ambiguous)
        if evidence is not None:
            _keep(best, target.canonical_id, evidence)
        if target.canonical_id in structural:
            _keep(best, target.canonical_id, "folder-index")

    ordered = sorted(
        best.items(),
        key=lambda item: (_EVIDENCE_PRIORITY[item[1][1]], item[0]),
    )
    if structural_uncapped:
        # Membership is filed by its own set, not by the evidence string that
        # won: an index page that lists its members in the body matches them by
        # full name too, and they must still stay outside the textual cap.
        textual = [item for item in ordered if item[0] not in structural]
        structural_items = [item for item in ordered if item[0] in structural]
        selected = textual[:max_relations] + structural_items
    else:
        selected = ordered[:max_relations]
    return [
        GroundedRelation(canonical_id=canonical_id, evidence=evidence)
        for canonical_id, (_priority, evidence) in selected
    ]


def structural_relations(
    *,
    source_id: str,
    source_path: str,
    targets: Sequence[RelationTarget],
) -> frozenset[str]:
    """Ids connected to the source by folder membership alone.

    Derived from the path, never from the body: the folder's own index and each
    member's belonging edge. Kept separate from the evidence kind because a
    member named in the index body matches by full name as well — the cap must
    not treat that as an inferred relation.
    """

    folder = _folder(source_path)
    index_path = _folder_index_path(folder)
    source_is_index = bool(source_path) and source_path == index_path
    ids: set[str] = set()
    for target in targets:
        if not target.canonical_id or target.canonical_id == source_id:
            continue
        if target.path and source_path and target.path == source_path:
            continue
        if index_path and target.path == index_path:
            ids.add(target.canonical_id)
        elif source_is_index and target.path and _folder(target.path) == folder:
            ids.add(target.canonical_id)
    return frozenset(ids)


def _ambiguous_identity_keys(
    targets: Sequence[RelationTarget],
) -> frozenset[tuple[str, str]]:
    """Identity keys (evidence kind, value) claimed by more than one entity.

    Two fichas that share a normalized title, alias or filename stem make that
    key unusable as proof: the body names *one* of them, not necessarily the
    other. Such keys are dropped instead of linking both.
    """

    owners: dict[tuple[str, str], set[str]] = {}
    for target in targets:
        if not target.canonical_id:
            continue
        name = _normalize(target.name)
        if name:
            owners.setdefault(("name", name), set()).add(target.canonical_id)
        for segment in _alias_segments(target.name):
            owners.setdefault(("alias", segment), set()).add(target.canonical_id)
        # A word that NAMES more than one ficha identifies a family, not a
        # ficha. Counting only filenames missed the real case: a long
        # descriptive filename is unique among filenames while its words
        # ("naturaleza", "cultura", "vibral") appear in many TITLES, so a
        # prose common noun linked unrelated fichas. Titles and folder names
        # count too, and the same key space feeds the ordinal noun below.
        for token in _name_tokens(target):
            owners.setdefault(("stem", token), set()).add(target.canonical_id)
    return frozenset(key for key, ids in owners.items() if len(ids) > 1)


def _name_tokens(target: RelationTarget) -> set[str]:
    """Words that name one ficha: its title, its filename and its folder."""
    folder = _folder(target.path)
    parts = (
        target.name or "",
        target.path.rsplit("/", 1)[-1],
        folder.rsplit("/", 1)[-1],
    )
    tokens: set[str] = set()
    for part in parts:
        for token in re.split(r"[-_.\s]+", _normalize(part)):
            if len(token) >= 4 and token not in GENERIC_WORDS:
                tokens.add(token)
    return tokens


def _keep(best: dict[str, tuple[int, str]], canonical_id: str, evidence: str) -> None:
    priority = _EVIDENCE_PRIORITY[evidence]
    current = best.get(canonical_id)
    if current is None or priority < current[0]:
        best[canonical_id] = (priority, evidence)


def _match_target(
    target: RelationTarget,
    body_norm: str,
    generic: set[str],
    ambiguous: frozenset[tuple[str, str]] = frozenset(),
) -> str | None:
    name_norm = _normalize(target.name)
    # A title made only of words shared with the source's own identity/folder
    # names the family, not the ficha; the folder index carries that belonging.
    if (
        name_norm
        and ("name", name_norm) not in ambiguous
        and not _is_generic_phrase(name_norm, generic)
    ):
        if _phrase_in(name_norm, body_norm):
            return "full-name"

    for segment in _alias_segments(target.name):
        if (
            segment
            and ("alias", segment) not in ambiguous
            and _phrase_in(segment, body_norm)
        ):
            return "alias"

    for token in _stem_tokens(target.path):
        if token in generic or token in GENERIC_WORDS:
            continue
        if ("stem", token) in ambiguous:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", body_norm):
            return "stem"

    if ("name", name_norm) in ambiguous:
        return None
    # An ordinal names a POSITION inside a family ("1er Stal", "3er Nivel").
    # When the family word itself names many fichas, the ordinal does not say
    # which family: "1er Stal" exists in two unrelated families in one world.
    noun = _ordinal_noun(name_norm)
    if noun and ("stem", noun) in ambiguous:
        return None
    if _has_ordinal_evidence(name_norm, body_norm):
        return "ordinal"
    return None


def _ordinal_noun(name_norm: str) -> str | None:
    """The family word an ordinal position belongs to, in either word order."""
    match = re.search(
        r"(?<![a-z0-9])(\d)(?:er|ro|do|to|mo|vo|no)\s+([a-z]{3,})", name_norm
    )
    if match:
        return match.group(2)
    match = re.search(r"(?<![a-z0-9])([a-z]{3,})\s+(\d)(?!\d)", name_norm)
    if match:
        return match.group(1)
    return None


def _has_ordinal_evidence(name_norm: str, body_norm: str) -> bool:
    """Match an ordered family in either direction ("3er Nivel" / "Nivel 3")."""

    match = re.search(
        r"(?<![a-z0-9])(\d)(?:er|ro|do|to|mo|vo|no)\s+([a-z]{3,})", name_norm
    )
    if match:
        for ordinal in _ORDINALS.get(match.group(1), ()):
            if re.search(
                rf"(?<![a-z0-9]){re.escape(ordinal)}\s+{re.escape(match.group(2))}"
                rf"(?![a-z0-9])",
                body_norm,
            ):
                return True
    match = re.search(r"(?<![a-z0-9])([a-z]{3,})\s+(\d)(?!\d)", name_norm)
    if match:
        if re.search(
            rf"(?<![a-z0-9]){re.escape(match.group(1))}\s+{match.group(2)}"
            rf"(?![a-z0-9])",
            body_norm,
        ):
            return True
    return False


def _is_generic_phrase(phrase: str, generic: set[str]) -> bool:
    words = [word for word in phrase.split() if word]
    return bool(words) and all(
        word in GENERIC_WORDS or word in generic for word in words
    )


def _alias_segments(name: str) -> list[str]:
    """Distinctive segments after a dash (``Elemento … – Enlace``).

    Pipes are deliberately excluded: ``Política | Distribución …`` would make
    the generic word "política" link every ficha that mentions politics.
    """

    parts = re.split(r"\s+[–—]\s+", name)
    if len(parts) < 2:
        return []
    segments: list[str] = []
    for part in parts[1:]:
        normalized = _normalize(part)
        if normalized and not all(
            word in GENERIC_WORDS for word in normalized.split()
        ):
            segments.append(normalized)
    return segments


def _stem_tokens(path: str) -> list[str]:
    if not path:
        return []
    stem = path.rsplit("/", 1)[-1]
    if stem.lower().endswith(".md"):
        stem = stem[:-3]
    return [
        token
        for token in re.split(r"[-_.\s]+", _normalize(stem))
        if len(token) >= 4
    ]


def _generic_tokens(source_path: str) -> set[str]:
    """Words shared with the source's own filename or folder: no evidence."""

    tokens: set[str] = set()
    if not source_path:
        return tokens
    for part in (source_path.rsplit("/", 1)[-1], _folder(source_path)):
        for token in re.split(r"[-_./\s]+", _normalize(part)):
            if len(token) >= 4:
                tokens.add(token)
    return tokens


def _folder_index_path(folder: str) -> str:
    if not folder:
        return ""
    basename = folder.rsplit("/", 1)[-1]
    return f"{folder}/{basename}.md"


def _folder(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


_RE_WIKILINK_ENTRY = re.compile(r"\[\[([^\]]+)\]\]")


def relaciones_entry_key(raw: str) -> str:
    """Normalize one ``relaciones:`` entry to its dedupe key.

    ``[[Name]]`` entries yield the inner wikilink text; anything else yields the
    bare scalar with quotes and brackets stripped. One implementation shared by
    the frontmatter writer, the plan applier and candidate detection.
    """
    cleaned = raw.strip().strip('"').strip("'").strip()
    match = _RE_WIKILINK_ENTRY.search(cleaned)
    if match:
        return match.group(1).strip()
    return cleaned.strip("[]").strip()


def normalize_mention(text: str) -> str:
    """Public form of the mention normalization used by every matcher."""
    return _normalize(text)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text or "")
    stripped = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    # Dashes, pipes, colons and punctuation become spaces so a title matches
    # the same wording with different punctuation.
    cleaned = re.sub(r"[^a-z0-9]+", " ", stripped.lower())
    return " ".join(cleaned.split())


def _phrase_in(needle: str, haystack: str) -> bool:
    if not needle:
        return False
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack
        )
    )


def _dict_get(candidate: object, key: str) -> str:
    if isinstance(candidate, dict):
        value = candidate.get(key)
        return str(value) if value else ""
    return ""


#: Report tags (S8). ``false-orphan`` is a safety net: after grounding, a
#: ficha with no relation should not name another ficha of the same job.
QUALITY_FALSE_ORPHAN = "false-orphan"
QUALITY_STANDALONE = "standalone"
QUALITY_NON_ENTITY = "non-entity"


def ficha_quality(
    *,
    body: str,
    relaciones: Iterable[str],
    graph: bool,
    source_id: str,
    source_path: str,
    targets: Sequence[RelationTarget],
) -> list[str]:
    """Relation-health tags for ONE saved ficha (P5).

    Same tags the importer review shows, computed against the whole world:

    * ``non-entity`` — the document opted out of the graph (``graph: false``);
    * ``false-orphan`` — no declared relation, yet the body names another ficha;
    * ``standalone`` — no declared relation and no mention at all.

    A ficha with at least one declared relation is healthy and returns ``[]``.
    """

    if graph is False:
        return [QUALITY_NON_ENTITY]
    if any(isinstance(entry, str) and entry.strip() for entry in relaciones):
        return []
    grounded = grounded_relations(
        body=body or "",
        source_id=source_id,
        source_path=source_path,
        targets=targets,
    )
    mentions = [
        relation for relation in grounded if relation.evidence != "folder-index"
    ]
    return [QUALITY_FALSE_ORPHAN if mentions else QUALITY_STANDALONE]


def relation_quality(candidates: Iterable[object]) -> dict[str, list[str]]:
    """Classify every candidate's relation health for the review screen.

    * ``non-entity`` — the document opted out of the graph (``graph: false``).
    * ``false-orphan`` — no relation, yet the body names another ficha of the
      same import (the extraction should have linked it; this catches a miss).
    * ``standalone`` — no relation and no mention: nothing in the text connects
      it, so the author decides.

    Job-local on purpose: the cross-world targets already participate in the
    extraction, so this report only audits the generated result.
    """

    candidate_list = list(candidates)
    targets = build_relation_targets(candidate_list)
    report: dict[str, list[str]] = {}
    for candidate in candidate_list:
        candidate_id = str(
            getattr(candidate, "candidate_id", "")
            or _dict_get(candidate, "candidate_id")
        )
        if not candidate_id:
            continue
        frontmatter = getattr(candidate, "frontmatter", None) or _dict_get(
            candidate, "frontmatter"
        )
        graph = True
        relations: list[str] = []
        if frontmatter is not None:
            graph = getattr(frontmatter, "graph", True)
            relations = list(getattr(frontmatter, "relaciones", []) or [])
            if isinstance(frontmatter, dict):
                graph = bool(frontmatter.get("graph", True))
                relations = list(frontmatter.get("relaciones") or [])
        if graph is False:
            report[candidate_id] = [QUALITY_NON_ENTITY]
            continue
        if relations:
            report[candidate_id] = []
            continue
        body = str(
            getattr(candidate, "content_preview", "")
            or _dict_get(candidate, "content_preview")
        )
        named = _names_another(candidate, body, targets)
        report[candidate_id] = [QUALITY_FALSE_ORPHAN if named else QUALITY_STANDALONE]
    return report


def _names_another(
    candidate: object, body: str, targets: Sequence[RelationTarget]
) -> bool:
    source_id = str(
        getattr(candidate, "canonical_id", "")
        or getattr(candidate, "normalized_identity", "")
        or _dict_get(candidate, "canonical_id")
        or _dict_get(candidate, "id")
    )
    source_path = str(
        getattr(candidate, "materialized_path", "")
        or _dict_get(candidate, "materialized_path")
        or getattr(candidate, "path", "")
        or _dict_get(candidate, "path")
    )
    body_norm = _normalize(body or "")
    generic = _generic_tokens(source_path)
    ambiguous = _ambiguous_identity_keys(targets)
    for target in targets:
        if target.canonical_id == source_id:
            continue
        if _match_target(target, body_norm, generic, ambiguous) is not None:
            return True
    return False
