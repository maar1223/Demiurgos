"""Pure domain helpers for materializing an idea into a world ficha.

This module performs no writes and no routing. The folder probe receives the
world directory and reads only ``*.md`` frontmatter blocks (bounded probe);
grounding candidates receive an injected graph-reader object (the same
diskless seam the guided flow uses); relation validation is pure set
membership. Every helper mirrors an established convention instead of
inventing one:

- ``slugify_title`` / ``suggest_free_slug`` — AD5, mirroring
  ``guided_character_domain._SLUG`` (:22) and ``api_server._next_duplicate_name``
  (:4060-4073) minus the ``-copia`` first step (narrative-idea ``-2`` rule).
- ``probe_folder_convention`` / ``build_ficha_skeleton`` — AD4: server-owned
  frontmatter, probe order ``_Plantilla_Ficha.md`` -> folder index -> first
  sibling -> section-level -> hardcoded default; ``type`` presence is
  mandatory for indexing (``graph_indexer._entity_from_file``, :190-196).
- ``build_grounding_candidates`` / ``validate_relations`` — AD6 + binding
  clarification: only canonical-``id`` entities are advertised; a relation is
  kept only when its target exists AND its ``rel_type`` is in the vocabulary,
  anything else is dropped and reported (never a stub, never an envelope
  failure).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from idea_materialization_protocol import (
    MAX_CANDIDATE_PAYLOAD_CHARS,
    MAX_CANDIDATE_SUMMARY_CHARS,
    MAX_CANDIDATES,
    MAX_SLUG_LEN,
    Relation,
)
from import_enrichment import _REL_VOCAB_DEFAULT
from okf_contract import is_canonical_id

# Indexer exclusion set (mirrors ``graph_indexer._EXCLUDE_FILES``,
# graph_indexer.py:36-41): template/auxiliary files that never become
# entities. ``_Plantilla_Ficha.md`` is still probed as a template because it
# defines the folder's frontmatter convention (graph_indexer.py:39).
_EXCLUDE_FILES: frozenset[str] = frozenset({
    "_README.md",
    "CHANGELOG.md",
    "_Plantilla_Ficha.md",
    "00_Catalogo_Personajes.md",
})

# OKF ficha statuses (mirrors ``api_server.VALID_FICHA_STATUSES``,
# api_server.py:4978): ``synced`` exists only in idea-bank files and is never
# a ficha status. A probed status outside this set degrades to ``draft``
# (canon-safe; never the guided-session ``proposed``).
VALID_FICHA_STATUSES: frozenset[str] = frozenset({"draft", "stable"})

# Hardcoded section defaults (AD4 steps 2e/4): personajes mirrors
# ``serialize_ficha``; lore/referencias use the canonical convention with a
# title-cased folder parent.
_SECTION_DEFAULT_TYPE: dict[str, str] = {
    "personajes": "Personaje",
    "lore": "concepto",
    "referencias": "referencia",
}

__all__ = [
    "FolderConvention",
    "VALID_FICHA_STATUSES",
    "build_ficha_skeleton",
    "build_grounding_candidates",
    "probe_folder_convention",
    "slugify_title",
    "suggest_free_slug",
    "validate_relations",
]


@dataclass(frozen=True)
class FolderConvention:
    """Resolved frontmatter convention for a target folder (AD4).

    ``convention`` is one of:

    - ``"personajes"`` — slug ``id``, ``type: Personaje``, ``schema_version: 1``
      (mirrors ``serialize_ficha``, guided_character_domain.py:484-512).
    - ``"canonical"`` — ``"Parent::Title"`` ids; the probed ficha already
      carries a ``::``-qualified ``id``.
    - ``"canonical-single"`` — the folder index keeps a single-segment ``id``;
      children still use ``"Parent::Title"``.

    ``parent`` is the index-ficha title used as the canonical id prefix
    (empty for personajes). ``status`` is the probed OKF status when valid,
    else ``draft``. ``source`` names the probed file (``None`` for the
    hardcoded section fallback).
    """

    convention: str
    parent: str
    type: str
    status: str
    source: str | None


def slugify_title(title: str) -> str:
    """ASCII-transliterate *title* into a ``_SLUG``-shaped slug (AD5).

    Lowercases, maps Spanish diacritics to ASCII (``ñ -> n``, ``á -> a``,
    ``é -> e``, ``í -> i``, ``ó -> o``, ``ú -> u``, ``ü -> u``), collapses
    every other character run into single hyphens, and truncates to
    ``MAX_SLUG_LEN`` on a token boundary so the result always matches
    ``guided_character_domain._SLUG`` (:22). A title with no ASCII
    alphanumerics yields ``""``.
    """
    ascii_lower = (
        unicodedata.normalize("NFKD", title)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_lower).strip("-")
    if len(slug) > MAX_SLUG_LEN:
        slug = slug[:MAX_SLUG_LEN].rstrip("-")
    return slug


def suggest_free_slug(full_path: Path) -> Path:
    """Next free duplicate path: ``{stem}-2{ext}``, ``{stem}-3{ext}``, ...

    Mirrors ``_next_duplicate_name`` (api_server.py:4060-4073) minus the
    ``-copia`` first step, per the narrative-idea ``-2`` collision rule
    (skills/narrative-idea/SKILL.md:225).
    """
    stem = full_path.stem
    ext = full_path.suffix
    n = 2
    candidate = full_path.with_name(f"{stem}-{n}{ext}")
    while candidate.exists():
        n += 1
        candidate = full_path.with_name(f"{stem}-{n}{ext}")
    return candidate


def probe_folder_convention(world_dir: Path, section: str, folder: str) -> FolderConvention:
    """Probe *world_dir/section/folder* for the convention the new ficha follows.

    Probe order (AD4): ``_Plantilla_Ficha.md`` template -> folder index ficha
    (``folder/<folder-name>.md``) -> first sibling by sort -> section-level
    index/first ficha -> hardcoded section default. Only non-excluded, non
    ``_``-prefixed ``*.md`` files count as siblings; the template is probed
    even though indexing excludes it. An empty or absent folder falls back to
    the section default (real case: ``mundos/Vibrantes/personajes/`` is
    empty and ``referencias/`` is absent).
    """
    folder_dir = (world_dir / section / folder) if folder else (world_dir / section)
    if not folder_dir.is_dir():
        return _section_default(section, folder)
    for candidate in _probe_candidates(folder_dir, section):
        if not candidate.is_file():
            continue
        fm = _parse_frontmatter(candidate.read_text(encoding="utf-8"))
        if not fm:
            continue
        classified = _classify_frontmatter(fm, candidate, folder_dir, section)
        if classified is not None:
            return classified
    return _section_default(section, folder)


def build_ficha_skeleton(
    *,
    world_dir: Path,
    section: str,
    folder: str,
    slug: str,
    title: str,
    body: str,
    relations: Sequence[Relation],
    convention: FolderConvention | None = None,
) -> str:
    """Assemble the server-owned ficha content: frontmatter + AI body (AD4).

    Always emits ``id``, ``title``, ``type``, ``status``, ``relaciones`` and
    ``based_on: ideas/{slug}``; ``type`` presence is mandatory for graph
    indexing (``graph_indexer._entity_from_file``, :190-196). ``status`` is
    the probed OKF status when valid, else ``draft``. personajes fichas
    additionally carry ``schema_version: 1`` (mirrors ``serialize_ficha``).
    Relations are serialized as ``[[target_id]]`` wikilinks, the form the
    graph indexer resolves (``graph_indexer._entity_from_file``, :216-233).
    """
    if convention is None:
        convention = probe_folder_convention(world_dir, section, folder)
    values: dict[str, Any] = {
        "id": _ficha_id(convention, section, folder, slug, title),
        "title": title,
        "type": convention.type,
        "status": convention.status,
        "relaciones": [f"[[{rel.target_id}]]" for rel in relations],
        "based_on": f"ideas/{slug}",
    }
    if convention.convention == "personajes":
        values["schema_version"] = 1
    block = yaml.safe_dump(
        values,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    return f"---\n{block}\n---\n\n{body.strip()}\n"


def build_grounding_candidates(
    reader: object,
    *,
    section_filter: str | None = None,
) -> list[dict[str, str]]:
    """Bounded, ranked grounding candidates from an injected graph reader.

    The reader must expose ``search(query)`` returning ranked hits and
    ``read(path)`` returning a full entity mapping, like
    ``_GuidedGraphReader`` (api_server.py:5263-5277). When the reader exposes
    the ``entities()`` enumeration seam (real index, R-IM-03/06), it is used
    directly — ``search("*")`` returns ``[]`` against the real index by
    design, so the search/read pair would silently see an empty world. Only
    entities with a non-empty canonical ``id`` are advertised
    (``graph_indexer._entity_from_file`` sets ``id`` only when
    ``is_canonical_id``, :212-215); legacy entities with empty ids are never
    advertised. Rank order (the reader's enumeration / ``search("*")``
    order) is preserved; gathering stops at ``MAX_CANDIDATES`` or
    ``MAX_CANDIDATE_PAYLOAD_CHARS`` serialized chars, whichever comes first,
    dropping the lowest-ranked remainder. An empty world yields an empty list
    — still a valid ficha (R-IM-03 scenario).
    """
    candidates: list[dict[str, str]] = []
    payload_chars = 0
    for entity in _iter_entity_mappings(reader):
        if not isinstance(entity, Mapping):
            continue
        canonical_id = entity.get("id")
        if not isinstance(canonical_id, str) or not canonical_id.strip():
            continue
        if section_filter is not None and not str(entity.get("path", "")).startswith(f"{section_filter}/"):
            continue
        title = entity.get("title") or entity.get("name") or ""
        summary = str(entity.get("description") or "")[:MAX_CANDIDATE_SUMMARY_CHARS]
        candidate = {
            "id": canonical_id,
            "title": str(title),
            "type": str(entity.get("type", "")),
            "summary": summary,
        }
        serialized = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
        if len(candidates) >= MAX_CANDIDATES or payload_chars + len(serialized) > MAX_CANDIDATE_PAYLOAD_CHARS:
            break
        candidates.append(candidate)
        payload_chars += len(serialized)
    return candidates


def validate_relations(
    proposed: Iterable[Relation],
    existing_ids: Iterable[str],
    vocab: frozenset[str] = _REL_VOCAB_DEFAULT,
) -> tuple[list[Relation], list[dict[str, str]]]:
    """Keep only grounded relations and report the discarded ones (R-IM-03).

    A relation is kept when its ``target_id`` is an existing canonical entity
    id AND its ``rel_type`` belongs to *vocab* (``_REL_VOCAB_DEFAULT`` by
    default, import_enrichment.py:96-102). Anything else is dropped and
    reported as ``{target_id, reason}`` with reason ``target_not_found`` or
    ``rel_type_out_of_vocabulary``. Never creates a stub and never writes an
    ungrounded relation; an out-of-vocabulary ``rel_type`` is a per-relation
    drop, never an envelope failure (binding clarification).
    """
    known = set(existing_ids)
    kept: list[Relation] = []
    discarded: list[dict[str, str]] = []
    for relation in proposed:
        if relation.target_id not in known:
            discarded.append({"target_id": relation.target_id, "reason": "target_not_found"})
        elif relation.rel_type not in vocab:
            discarded.append({"target_id": relation.target_id, "reason": "rel_type_out_of_vocabulary"})
        else:
            kept.append(relation)
    return kept, discarded


# ---------------------------------------------------------------------------
# Probe internals (AD4)
# ---------------------------------------------------------------------------


def _probe_candidates(folder_dir: Path, section: str) -> list[Path]:
    """Ordered probe targets for *folder_dir* (AD4 steps 2a-2d)."""
    candidates: list[Path] = []
    template = folder_dir / "_Plantilla_Ficha.md"
    index = folder_dir / f"{folder_dir.name}.md"
    siblings = sorted(
        p for p in folder_dir.glob("*.md")
        if p.name not in _EXCLUDE_FILES and not p.name.startswith("_")
    )
    if template.is_file():
        candidates.append(template)
    candidates.append(index)
    candidates.extend(p for p in siblings if p != index)
    section_dir = folder_dir.parent
    if section_dir != folder_dir:
        section_index = section_dir / f"{section}.md"
        section_siblings = sorted(
            p for p in section_dir.glob("*.md")
            if p.name not in _EXCLUDE_FILES and not p.name.startswith("_")
        )
        candidates.append(section_index)
        candidates.extend(p for p in section_siblings if p != section_index)
    return candidates


def _classify_frontmatter(
    fm: Mapping[str, Any],
    probed_path: Path,
    folder_dir: Path,
    section: str,
) -> FolderConvention | None:
    """Classify a probed frontmatter block into a convention (AD4 step 3)."""
    probed_type = str(fm.get("type", "")).strip()
    status = _probed_status(fm)
    if "schema_version" in fm or probed_type.casefold() == "personaje":
        return FolderConvention("personajes", "", "Personaje", status, probed_path.stem)
    raw_id = fm.get("id")
    if isinstance(raw_id, str) and is_canonical_id(raw_id):
        entity_type = probed_type or _SECTION_DEFAULT_TYPE.get(section, "concepto")
        parent = _index_title_for(fm, probed_path, folder_dir, section)
        if "::" in raw_id:
            return FolderConvention(
                "canonical", parent or raw_id.rsplit("::", 1)[0], entity_type, status, probed_path.stem,
            )
        return FolderConvention(
            "canonical-single", parent or _title_case_folder(folder_dir.name), entity_type, status, probed_path.stem,
        )
    return None


def _ficha_id(convention: FolderConvention, section: str, folder: str, slug: str, title: str) -> str:
    """Canonical ``id`` for the new ficha given its convention (AD4 step 3/4)."""
    if convention.convention == "personajes":
        return slug
    normalized_title = re.sub(r"\s{2,}", " ", title).strip()
    if convention.convention == "canonical-single" and slug == (folder or section):
        return normalized_title
    return f"{convention.parent}::{normalized_title}"


def _section_default(section: str, folder: str) -> FolderConvention:
    """Hardcoded fallback when the folder has nothing to probe (AD4 step 4)."""
    if section == "personajes":
        return FolderConvention("personajes", "", "Personaje", "draft", None)
    parent = _title_case_folder(folder) or section.capitalize()
    return FolderConvention(
        "canonical",
        parent,
        _SECTION_DEFAULT_TYPE.get(section, "concepto"),
        "draft",
        None,
    )


def _title_case_folder(folder_slug: str) -> str:
    """Title-case a folder slug: ``sistema-stal-poderes`` -> ``Sistema Stal Poderes``."""
    return " ".join(part.capitalize() for part in folder_slug.split("-") if part)


def _index_title_for(
    fm: Mapping[str, Any],
    probed_path: Path,
    folder_dir: Path,
    section: str,
) -> str:
    """Title of the probed file when it is an index ficha (folder or section).

    The canonical parent is the index-ficha title (AD4 step 3): when the
    probed file IS the folder index (``folder/<folder-name>.md``) or the
    section index (``section/<section>.md``), its own title is the parent;
    otherwise the folder index title is used, falling back to ``""`` so the
    caller can substitute the ``::`` id prefix or a title-cased folder name.
    """
    if probed_path.parent == folder_dir and probed_path.stem == folder_dir.name:
        return _fm_title(fm)
    if probed_path.parent == folder_dir.parent and probed_path.stem == section:
        return _fm_title(fm)
    return _folder_index_title(folder_dir)


def _fm_title(fm: Mapping[str, Any]) -> str:
    title = fm.get("title")
    return str(title).strip() if isinstance(title, str) else ""


def _folder_index_title(folder_dir: Path) -> str:
    """Title of the folder index ficha (``folder/<folder-name>.md``), if any."""
    index = folder_dir / f"{folder_dir.name}.md"
    if not index.is_file():
        return ""
    fm = _parse_frontmatter(index.read_text(encoding="utf-8"))
    return _fm_title(fm)


def _probed_status(fm: Mapping[str, Any]) -> str:
    """Probed OKF status when valid, else ``draft`` (canon-safe, AD4 step 5)."""
    value = fm.get("status")
    if isinstance(value, str) and value in VALID_FICHA_STATUSES:
        return value
    return "draft"


def _parse_frontmatter(content: str) -> dict[str, Any]:
    """Extract the YAML frontmatter block; ``{}`` when absent or malformed.

    Mirrors ``EntityGraphIndex._parse_frontmatter`` (graph_indexer.py:124-151).
    """
    lines = content.split("\n")
    if not lines or not lines[0].strip() == "---":
        return {}
    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}
    yaml_block = "\n".join(lines[1:end_idx])
    try:
        parsed = yaml.safe_load(yaml_block)
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Reader seam (AD6) — the reader is the caller's injected seam
# ---------------------------------------------------------------------------


def _reader_entities(reader: object) -> list[Any] | None:
    """Full entity mappings from the injected reader's ``entities()`` seam.

    The reader is the caller's seam; ``_GuidedGraphReader`` exposes the real
    index enumeration (R-IM-03/06 grounding). Returns None when the reader
    does not expose the method so callers fall back to the legacy
    ``search("*")`` + ``read(path)`` pattern (readers without the seam keep
    their exact previous behavior).
    """
    entities = getattr(reader, "entities", None)
    if not callable(entities):
        return None
    items = entities()
    return list(items) if isinstance(items, (list, tuple)) else None


def _iter_entity_mappings(reader: object) -> Iterable[Any]:
    """Yield full entity mappings from the reader, enumeration-first.

    Prefers the real ``entities()`` seam (full entities in index insertion
    order); falls back to the legacy ``search("*")`` + ``read(path)`` pair so
    readers without the new method behave exactly as before. Failures
    propagate so a broken graph is never silently mistaken for an empty world
    (fail loud, not empty).
    """
    enumerated = _reader_entities(reader)
    if enumerated is not None:
        for entity in enumerated:
            yield entity
        return
    for hit in _reader_search(reader):
        path = hit.get("path") if isinstance(hit, Mapping) else None
        if not isinstance(path, str) or not path:
            continue
        entity = _reader_read(reader, path)
        if entity is not None:
            yield entity


def _reader_search(reader: object) -> list[Any]:
    """Ranked hits from the injected reader (``search("*")`` order).

    The reader is the caller's seam; failures propagate so a broken graph is
    never silently mistaken for an empty world (fail loud, not empty).
    """
    search = getattr(reader, "search", None)
    if search is None:
        return []
    hits = search("*")
    return list(hits) if isinstance(hits, (list, tuple)) else []


def _reader_read(reader: object, path: str) -> Any:
    """Full entity mapping for *path* from the injected reader."""
    read = getattr(reader, "read", None)
    if read is None:
        return None
    return read(path)