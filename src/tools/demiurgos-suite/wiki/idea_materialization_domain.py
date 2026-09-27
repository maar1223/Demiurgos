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
  failure). Grounding is GRAPH-AWARE (materialize-graph-grounding): the idea
  title seeds a graph search, the near-best seeds are expanded one hop, and the
  payload budget is only a guard — never a target to fill.
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
from markdown_heading import impose_h1
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

# Seed selection bounds (materialize-graph-grounding, MG-1). The candidate set
# is the GRAPH NEIGHBOURHOOD of the idea, so these are deliberately small: the
# best score sets the relative bar, a handful of near-best hits seed the
# expansion, and the payload bound only guards the tail.
#
# SEED_RATIO is 0.95, not 0.90 (measured tuning against the user's real world).
# On "Silpah — Lince Relámpago de Chaae" the real scores were 15.06, 13.97,
# 11.76, 11.69: 13.97/15.06 = 0.928 slipped a noisy second seed ("Eneagrama")
# past a 0.90 bar, and that seed's one-hop expansion dragged in its 8-entity
# family (10 candidates, 8 of them noise). At 0.95 the bar is 14.31, so only
# Chaae seeds and the result is exactly [Region::Chaae, Region::Pannj]. A sweep
# of the 12 real idea titles showed 0.95 costs no coverage (1 seed for 10, 3 for
# one genuinely flat cluster, never 0 — the best always enters). Crucially, a
# strong second candidate that is genuinely related to the top seed still
# arrives through the 1-hop EXPANSION (that is exactly how Pannj arrives), so
# seeds only need to be confident anchors — a strict bar is safer than it looks.
SEED_RATIO = 0.95
SEED_LIMIT = 5
# The body is only a fallback broadening signal; a bounded excerpt keeps the
# query sharp and prevents the idea's full prose from re-introducing noise.
BODY_EXCERPT_CHARS = 400

__all__ = [
    "BODY_EXCERPT_CHARS",
    "FolderConvention",
    "SEED_LIMIT",
    "SEED_RATIO",
    "VALID_FICHA_STATUSES",
    "build_ficha_skeleton",
    "build_grounding_candidates",
    "probe_folder_convention",
    "resolve_file_slug",
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


def resolve_file_slug(
    ficha_title: str,
    idea_slug: str,
    client_slug: str | None,
) -> str:
    """Resolve the on-disk ficha filename slug (WU-6, iteration 2; FT-1).

    The caller resolves the visible ficha title (client title > idea title >
    idea slug) and passes it as *ficha_title*; this helper only turns a title
    into a filename. The filename derives from *ficha_title* via
    ``slugify_title`` and falls back to *idea_slug* when the title has no ASCII
    alphanumerics. An explicit ``client_slug`` (the editable filename in the
    instant destination step) overrides the derived name, normalized through
    ``slugify_title``; an empty or empty-normalizing client slug falls back to
    the derived default. Because ``slugify_title`` strips everything outside
    ``[a-z0-9-]``, client input is traversal-safe by construction — normalize,
    never reject.
    """
    default_file_slug = slugify_title(ficha_title) or idea_slug
    if client_slug:
        normalized = slugify_title(client_slug)
        return normalized or default_file_slug
    return default_file_slug


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
    idea_slug: str,
    title: str,
    body: str,
    relations: Sequence[Relation],
    convention: FolderConvention | None = None,
    image_rel: str | None = None,
) -> str:
    """Assemble the server-owned ficha content: frontmatter + AI body (AD4).

    Always emits ``id``, ``title``, ``type``, ``status``, ``relaciones`` and
    ``based_on: ideas/{idea_slug}``; ``type`` presence is mandatory for graph
    indexing (``graph_indexer._entity_from_file``, :190-196). ``status`` is
    the probed OKF status when valid, else ``draft``. personajes fichas
    additionally carry ``schema_version: 1`` (mirrors ``serialize_ficha``).
    Relations are serialized as ``[[target_id]]`` wikilinks, the form the
    graph indexer resolves (``graph_indexer._entity_from_file``, :216-233).

    ``slug`` drives ``_ficha_id`` (the file-derived identity); ``idea_slug``
    drives ``based_on`` (the idea link) and stays the idea's own slug even when
    the filename derives from the title — the two are deliberately separate.

    ``title`` is the server-owned ficha title and it owns the body's leading H1
    (FT-1): after the AI body is stripped and before the image injection, an
    existing leading H1 is REPLACED with ``# {title}``, or ``# {title}`` is
    prepended as its own line followed by one blank line when the body has no
    leading H1. Any later H1 is left untouched. The frontmatter ``title`` and
    the H1 therefore always agree.

    ``image_rel`` is an optional world-relative media reference (``media/x.jpg``).
    When set, a Markdown image ``![{title}]({image_rel})`` is injected into the
    body: immediately after the leading H1 (which the title imposition
    guarantees exists). Exactly one blank line separates the image line from
    the following text. When ``image_rel`` is ``None`` and the leading H1
    already equals ``# {title}`` the emitted content is byte-identical to the
    image-less output.
    """
    if convention is None:
        convention = probe_folder_convention(world_dir, section, folder)
    values: dict[str, Any] = {
        "id": _ficha_id(convention, section, folder, slug, title),
        "title": title,
        "type": convention.type,
        "status": convention.status,
        "relaciones": [f"[[{rel.target_id}]]" for rel in relations],
        "based_on": f"ideas/{idea_slug}",
    }
    if convention.convention == "personajes":
        values["schema_version"] = 1
    block = yaml.safe_dump(
        values,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    stripped_body = _impose_h1(body.strip(), title)
    if image_rel is not None:
        stripped_body = _inject_image_line(stripped_body, title, image_rel)
    return f"---\n{block}\n---\n\n{stripped_body}\n"


def _impose_h1(body: str, title: str) -> str:
    """Make the server-owned *title* the body's leading H1 (FT-1).

    Thin delegation to the neutral ``markdown_heading.impose_h1`` so the idea
    bank and this materialization domain share exactly one rule (FT-4). The
    behaviour is unchanged: the AI body may open with its own H1 (which drifts
    from the title shown above the ficha) or with no heading at all. When the
    first line is an H1 (``# `` prefix) it is REPLACED with ``# {title}``;
    otherwise ``# {title}`` is prepended as its own line followed by exactly
    one blank line. Any later H1 is left untouched. *body* is expected already
    stripped, so a body that already opens with ``# {title}`` is returned
    byte-identical.
    """
    return impose_h1(body, title)


def _inject_image_line(body: str, title: str, image_rel: str) -> str:
    """Inject a Markdown image line into an already-stripped body (AD4 extension).

    After an H1 first line when the body opens with one (``# ``), else at the
    very start. The image line and any following text are separated by exactly
    one blank line; a body with no following text keeps just the image line
    (the caller appends the single trailing newline).
    """
    # The alt text is free-form (idea title or typed hint); a raw ``[``/``]``
    # or newline would break the Markdown image syntax and silently kill the
    # image, so the alt is flattened and bracket-escaped.
    alt = (
        title.replace("\r", " ").replace("\n", " ")
        .replace("[", r"\[").replace("]", r"\]")
    )
    image_line = f"![{alt}]({image_rel})"
    if body.startswith("# "):
        first_line, _, rest = body.partition("\n")
        rest = rest.lstrip("\n")
        return f"{first_line}\n{image_line}\n\n{rest}" if rest else f"{first_line}\n{image_line}"
    if body:
        return f"{image_line}\n\n{body}"
    return image_line


def build_grounding_candidates(
    reader: object,
    *,
    idea_title: str,
    idea_body: str = "",
) -> list[dict[str, str]]:
    """Graph-aware grounding candidates from an injected graph reader.

    WHY the graph is consulted at all: the model can only propose relations to
    entities it can see. Sending an arbitrary slice of the world (the previous
    file-order prefix) plainly failed — the entities that mattered were never
    advertised, so the model correctly proposed nothing. The graph is the
    authority for "what exists" and "what is related"; the idea title is the
    sharpest signal for "which" of those entities the idea is about.

    Selection is deterministic and staged:

    1. precise: ``reader.search(idea_title)``;
    2. broaden (only when stage 1 matched nothing): search the title plus a
       BOUNDED body excerpt;
    3. blind map (only when nothing matched): ``reader.hubs()``;
    4. hybrid seed pick: the best score sets a relative bar
       (``score >= SEED_RATIO * best``), the best always enters, a small
       ceiling (``SEED_LIMIT``) caps the seeds, ties break by ``id`` asc;
    5. one-hop expansion: forward links + backlinks per seed, deduped by id,
       neighbours ranked by how many seeds connect to them;
    6. the payload budget is ONLY A GUARD, never a target: we emit the natural
       neighbourhood and stop at ``MAX_CANDIDATES`` / the byte bound from the
       TAIL. Because seeds precede neighbours, a neighbour is dropped before a
       seed — filling the budget must never crowd out a seed again.

    A bad seed is dangerous precisely because the expansion multiplies it: one
    off-topic entity drags in its whole neighbourhood, so seed selection stays
    conservative (near-best only) while the budget never drives the choice.
    Only entities with a non-empty canonical ``id`` are advertised
    (``graph_indexer._entity_from_file`` sets ``id`` only when
    ``is_canonical_id``); legacy entities with empty ids are never advertised.
    An empty world yields an empty list (R-IM-03 scenario).
    """
    title = str(idea_title or "").strip()
    body_excerpt = _bounded_body_excerpt(idea_body)

    # Stage 1 — the title is about WHAT the idea is; search it directly.
    hits: list[Any] = []
    if title:
        hits = _usable_search_hits(_reader_search(reader, title))
    # Stage 2 — only when the title matched nothing: the bounded body excerpt
    # adds context without dragging in the idea's whole prose. Skipped when it
    # would merely repeat the title (empty body), which also keeps the query
    # log deterministic.
    if not hits:
        combined = f"{title} {body_excerpt}".strip()
        if combined and combined != title:
            hits = _usable_search_hits(_reader_search(reader, combined))
    if not hits:
        # Stage 3 — nothing matched: fall back to the world's hubs rather than
        # the file-order prefix that caused the original defect.
        return _bounded_candidates(_reader_hubs(reader))

    lookup = _reader_entity_lookup(reader)
    seeds = _select_seed_hits(hits)
    seed_entities: list[Mapping[str, Any]] = []
    seed_paths: list[str] = []
    for hit in seeds:
        entity = _resolve_seed_entity(reader, hit, lookup)
        if entity is None or not _canonical_entity_id(entity):
            continue
        seed_entities.append(entity)
        path = hit.get("path")
        if isinstance(path, str) and path:
            seed_paths.append(path)

    # One-hop expansion. A neighbour reached by several seeds is stronger
    # evidence than one reached by a single seed, so it ranks first; id breaks
    # ties for a stable, deterministic order.
    connections: dict[str, int] = {}
    neighbours: dict[str, Mapping[str, Any]] = {}
    for path in seed_paths:
        for neighbour in _reader_neighbors(reader, path):
            if not isinstance(neighbour, Mapping):
                continue
            neighbour_id = _canonical_entity_id(neighbour)
            if not neighbour_id:
                continue
            connections[neighbour_id] = connections.get(neighbour_id, 0) + 1
            neighbours.setdefault(neighbour_id, neighbour)
    ordered_neighbours = sorted(
        neighbours.values(),
        key=lambda entity: (
            -connections.get(_canonical_entity_id(entity), 0),
            _canonical_entity_id(entity),
        ),
    )

    # Dedupe by canonical id across seeds and neighbours (seeds keep priority).
    ordered: list[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    for entity in [*seed_entities, *ordered_neighbours]:
        canonical_id = _canonical_entity_id(entity)
        if not canonical_id or canonical_id in seen_ids:
            continue
        seen_ids.add(canonical_id)
        ordered.append(entity)
    return _bounded_candidates(ordered)


def _bounded_candidates(entities: Iterable[Any]) -> list[dict[str, str]]:
    """Serialize ordered entities into the bounded candidate shape.

    The budget is a GUARD, not a target. Candidates are emitted in the order
    given (seeds first, then neighbours) and gathering stops only when
    ``MAX_CANDIDATES`` or ``MAX_CANDIDATE_PAYLOAD_CHARS`` would be exceeded,
    dropping the TAIL. Callers order seeds before neighbours, so truncation can
    only ever drop a neighbour — never crowd out a seed.
    """
    candidates: list[dict[str, str]] = []
    payload_chars = 0
    for entity in entities:
        if not isinstance(entity, Mapping):
            continue
        canonical_id = _canonical_entity_id(entity)
        if not canonical_id:
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


def _select_seed_hits(hits: Sequence[Any]) -> list[Mapping[str, Any]]:
    """Hybrid seed pick from ordered search hits (the "what" of the idea).

    Readers whose hits carry a numeric ``score`` are ranked by it: the best
    score sets a relative bar (``SEED_RATIO * best``) so only near-best hits
    become seeds, ordered score desc with ``id`` asc ties, capped at
    ``SEED_LIMIT``; the best is always kept even if the bar would exclude it.
    Readers whose hits carry no score (test fakes) fall back to the returned
    order and treat that order as the ranking. Pathless/duplicate hits are
    dropped before scoring.
    """
    unique: list[Mapping[str, Any]] = []
    seen_paths: set[str] = set()
    for hit in _usable_search_hits(hits):
        path = hit.get("path")
        if path in seen_paths:
            continue
        seen_paths.add(path)
        unique.append(hit)
    if not unique:
        return []

    def _score(hit: Mapping[str, Any]) -> float:
        return float(hit["score"])

    def _tie_id(hit: Mapping[str, Any]) -> str:
        identifier = hit.get("id")
        if isinstance(identifier, str) and identifier:
            return identifier
        return str(hit.get("path") or "")

    scored = all(
        isinstance(hit.get("score"), (int, float)) and not isinstance(hit.get("score"), bool)
        for hit in unique
    )
    if not scored:
        # Scoreless seam: the returned order IS the ranking.
        return unique[:SEED_LIMIT]

    best = max(_score(hit) for hit in unique)
    threshold = SEED_RATIO * best
    kept = [hit for hit in unique if _score(hit) >= threshold]
    if not kept:
        # Defensive: the best always enters, whatever the scores are.
        kept = [min(unique, key=lambda hit: (-_score(hit), _tie_id(hit)))]
    kept.sort(key=lambda hit: (-_score(hit), _tie_id(hit)))
    return kept[:SEED_LIMIT]


def _usable_search_hits(hits: Iterable[Any]) -> list[Mapping[str, Any]]:
    """Keep only search hits that name a real path (required for expansion)."""
    return [
        hit
        for hit in hits
        if isinstance(hit, Mapping)
        and isinstance(hit.get("path"), str)
        and bool(hit.get("path"))
    ]


def _resolve_seed_entity(
    reader: object,
    hit: Mapping[str, Any],
    lookup: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Resolve a search hit to its full entity mapping.

    The real seam (``graph_models.EntityHit``) carries display fields but NOT
    the canonical ``id``, so the entity is looked up by path — first in the
    reader's ``entities()`` enumeration, then via ``read(path)``. A hit that
    already carries its canonical id (fake readers) is used as-is.
    """
    if _canonical_entity_id(hit):
        return hit
    path = hit.get("path")
    if not isinstance(path, str) or not path:
        return None
    entity = lookup.get(path)
    if isinstance(entity, Mapping):
        return entity
    resolved = _reader_read(reader, path)
    return resolved if isinstance(resolved, Mapping) else None



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
    does not expose the method; callers then resolve individual seeds through
    ``read(path)``.
    """
    entities = getattr(reader, "entities", None)
    if not callable(entities):
        return None
    items = entities()
    return list(items) if isinstance(items, (list, tuple)) else None


def _reader_entity_lookup(reader: object) -> dict[str, Mapping[str, Any]]:
    """Index the reader's full entities by ``path`` for seed resolution.

    Uses the ``entities()`` enumeration seam (the real index, R-IM-03/06) so a
    scoreless search hit can be upgraded to its full mapping; readers without
    the seam fall back to ``read(path)`` in ``_resolve_seed_entity``.
    """
    lookup: dict[str, Mapping[str, Any]] = {}
    enumerated = _reader_entities(reader)
    if enumerated is None:
        return lookup
    for entity in enumerated:
        if not isinstance(entity, Mapping):
            continue
        path = entity.get("path")
        if isinstance(path, str) and path and path not in lookup:
            lookup[path] = entity
    return lookup


def _reader_search(reader: object, query: str) -> list[Any]:
    """Ranked hits for *query* from the injected reader.

    The reader is the caller's seam; failures propagate so a broken graph is
    never silently mistaken for an empty world (fail loud, not empty).
    """
    search = getattr(reader, "search", None)
    if not callable(search):
        return []
    hits = search(query)
    return list(hits) if isinstance(hits, (list, tuple)) else []


def _reader_read(reader: object, path: str) -> Any:
    """Full entity mapping for *path* from the injected reader."""
    read = getattr(reader, "read", None)
    if not callable(read):
        return None
    return read(path)


def _reader_neighbors(reader: object, path: str) -> list[Any]:
    """One-hop neighbours of *path* from the injected reader."""
    neighbors = getattr(reader, "neighbors", None)
    if not callable(neighbors):
        return []
    items = neighbors(path)
    return list(items) if isinstance(items, (list, tuple)) else []


def _reader_hubs(reader: object) -> list[Any]:
    """Most connected entities from the injected reader (blind-map fallback)."""
    hubs = getattr(reader, "hubs", None)
    if not callable(hubs):
        return []
    items = hubs()
    return list(items) if isinstance(items, (list, tuple)) else []


def _canonical_entity_id(entity: object) -> str:
    """Non-empty canonical ``id`` of an entity mapping, else ``""``."""
    canonical_id = entity.get("id") if isinstance(entity, Mapping) else None
    return canonical_id if isinstance(canonical_id, str) and canonical_id.strip() else ""


def _bounded_body_excerpt(body: str) -> str:
    """First ``BODY_EXCERPT_CHARS`` chars of *body*, whitespace-collapsed."""
    return " ".join(str(body or "").split())[:BODY_EXCERPT_CHARS]