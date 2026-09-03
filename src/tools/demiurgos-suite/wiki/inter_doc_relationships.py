"""Inter-document relationship post-process for imported worlds.

Creates semantic relationships between fichas that live in DIFFERENT documents
(first path segment of the entity ``path``) after the importer's graph
reconciliation completes. The post-process is:

* **Additive** — it only appends new ``relaciones`` entries to fichas that lack
  them; existing relationships are never touched.
* **Idempotent** — a side is skipped when its target is already present
  (compared by the resolved canonical id, not the display name), so re-runs
  write nothing.
* **Fail-open** — ``run_post_process`` never raises: a missing/raising Hermes
  runner, a malformed LLM reply, or an unexpected error yields an empty
  ``PostProcessResult`` instead of breaking the import job.
* **Token-cheap** — candidate generation is pure logic (no LLM); only the top
  ``max_pairs`` candidate pairs reach the compact prompt (~200 tokens/pair).

Pipeline: ``_candidate_pairs`` (canonical id / normalized name / shared
tags+type, cross-document only, sorted by signal strength and capped at
``max_pairs``) → ``_build_pair_prompt`` (compact JSON payload reusing the
importer's ``_REL_VOCAB_DEFAULT`` vocabulary) → ``hermes_runner`` →
``_write_relationship`` (atomic read→patch frontmatter ``relaciones``→write on
BOTH fichas) → ``graph.update_many`` (recompute backlinks for the written
fichas).

The on-disk OKF ``relaciones`` format stores bare ``[[canonical_id]]``
wikilinks (matching ``render_frontmatter_document``); relationship TYPE and
DIRECTION are logical metadata from the LLM that gate the write and select the
mirrored labels via ``_direction_pair``, but are not persisted in the current
corpus format.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from import_enrichment import _REL_VOCAB_DEFAULT

logger = logging.getLogger("demiurgos-inter-doc-relationships")

# Wikilink inside a ``relaciones`` entry: ``[[target]]``
_RE_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")

# Mirrored labels per the design's direction mapping. Symmetric types map to
# themselves; directed types map to their inverse within the vocabulary.
_REL_MIRROR: dict[str, str] = {
    "aliado-de": "aliado-de",
    "enemigo-de": "enemigo-de",
    "amigo-de": "amigo-de",
    "rival-de": "rival-de",
    "hermano-de": "hermano-de",
    "esposo-de": "esposo-de",
    "aparece-en": "aparece-en",
    "participa-en": "participa-en",
    "relacionado-con": "relacionado-con",
    "crea": "creado-por",
    "creado-por": "crea",
    "padre-de": "hijo-de",
    "madre-de": "hijo-de",
    "hijo-de": "padre-de",
    "mentor-de": "alumno-de",
    "alumno-de": "mentor-de",
    "lidera": "miembro-de",
    "miembro-de": "lidera",
    "habita-en": "ubicado-en",
    "ubicado-en": "habita-en",
    "sirve-a": "lidera",
    "deriva-de": "deriva-de",
}

_VALID_DIRECTIONS = ("a_to_b", "b_to_a", "bidirectional")

# Prompt payload limits
_DESCRIPTION_CHAR_BUDGET = 200


@dataclass(frozen=True)
class PostProcessResult:
    """Outcome of one inter-document relationship post-process run.

    ``pairs_evaluated`` counts candidate pairs actually sent to the Hermes
    runner (attempted). ``relationships_written`` counts individual
    ``relaciones`` entries appended across all modified fichas (one per side,
    so a fresh bidirectional write on a pair reports 2 and an idempotent
    re-run reports 0). ``fichas_modified`` lists the mundo-relative paths of
    fichas whose content changed.
    """

    pairs_evaluated: int
    relationships_written: int
    fichas_modified: list[str] = field(default_factory=list)


def run_post_process(
    mundo: str,
    graph: Any,
    hermes_runner: Callable[[str, str], str] | None = None,
    *,
    max_pairs: int = 50,
) -> PostProcessResult:
    """Top-level entry point. Idempotent. Fail-open (never raises).

    ``graph`` is the world's ``EntityGraphIndex`` (its ``_cache["entities"]``
    supplies the entity dicts). ``hermes_runner`` is the injected sync
    ``Callable[[prompt, session_id], str]`` — the same seam the importer
    enricher uses. With ``hermes_runner=None`` no pair can be evaluated, so
    the run returns an empty result.
    """
    try:
        cache = getattr(graph, "_cache", None) or {}
        entities = cache.get("entities") or {}
        if not entities or hermes_runner is None:
            return PostProcessResult(pairs_evaluated=0, relationships_written=0)

        pairs = _candidate_pairs(entities, max_pairs=max_pairs)
        mundo_root = Path(getattr(graph, "_mundos_path", ".")) / mundo

        changed_abs: list[str] = []
        relationships_written = 0
        for idx, (entity_a, entity_b, _signal) in enumerate(pairs):
            try:
                payload = _build_pair_prompt(entity_a, entity_b)
                prompt_text = json.dumps(payload, ensure_ascii=False)
                raw = hermes_runner(prompt_text, f"inter-doc:{mundo}:{idx}")
                rel_type, direction = _parse_relationship_response(raw)
                if rel_type is None or rel_type not in _REL_VOCAB_DEFAULT:
                    # Null / out-of-vocabulary result -> skip this pair.
                    continue
                id_a = _target_id(entity_a)
                id_b = _target_id(entity_b)
                path_a = mundo_root / entity_a["path"]
                path_b = mundo_root / entity_b["path"]
                written = _write_relationship(
                    path_a, path_b, rel_type, direction, id_a, id_b
                )
                relationships_written += len(written)
                changed_abs.extend(written)
            except Exception as exc:  # noqa: BLE001 — per-pair fail-open
                logger.warning(
                    "inter-doc pair %d failed for %s: %s",
                    idx, mundo, type(exc).__name__, exc_info=True,
                )
                continue

        fichas_modified = [
            _mundo_relative(graph, abs_path, mundo) for abs_path in changed_abs
        ]
        if changed_abs:
            try:
                graph.update_many(changed_abs, mundo)
            except Exception as exc:  # noqa: BLE001 — graph is a side effect
                logger.warning(
                    "inter-doc graph reconcile failed for %s: %s",
                    mundo, type(exc).__name__, exc_info=True,
                )
        return PostProcessResult(
            pairs_evaluated=len(pairs),
            relationships_written=relationships_written,
            fichas_modified=fichas_modified,
        )
    except Exception as exc:  # noqa: BLE001 — top-level fail-open
        logger.warning(
            "inter-doc post-process failed for %s: %s",
            mundo, type(exc).__name__, exc_info=True,
        )
        return PostProcessResult(pairs_evaluated=0, relationships_written=0)


def _candidate_pairs(
    entities: dict[str, dict],
    *,
    max_pairs: int = 50,
) -> list[tuple[dict, dict, str]]:
    """Return ``(entity_a, entity_b, signal)`` triples. Cross-document only.

    Entities are grouped by (1) exact canonical ``id``, (2) normalized name
    (case-insensitive, underscores→spaces), (3) shared tags AND same type.
    Only pairs whose first path segment differs are kept, sorted by signal
    strength (id > name > tags+type), deduplicated, and capped at
    ``max_pairs``.
    """
    groups_id: dict[str, list[dict]] = {}
    groups_name: dict[str, list[dict]] = {}
    for ent in entities.values():
        cid = str(ent.get("id") or "").strip()
        if cid:
            groups_id.setdefault(cid, []).append(ent)
        name = _normalize_name(ent.get("name") or "")
        if name:
            groups_name.setdefault(name, []).append(ent)

    candidates: list[tuple[dict, dict, str]] = []
    for group in groups_id.values():
        candidates.extend(_pairs_in_group(group, "id"))
    for group in groups_name.values():
        candidates.extend(_pairs_in_group(group, "name"))

    # Shared tags + same type: O(n²) over the cache entities, but pure string
    # ops — cheap at world scale, and the result is capped downstream by
    # ``max_pairs`` after the signal sort.
    ents = list(entities.values())
    for i in range(len(ents)):
        a = ents[i]
        a_tags = {str(t).lower() for t in (a.get("tags") or [])}
        for b in ents[i + 1:]:
            if not _different_docs(a, b):
                continue
            if a.get("type") != b.get("type"):
                continue
            b_tags = {str(t).lower() for t in (b.get("tags") or [])}
            if a_tags and b_tags and a_tags & b_tags:
                candidates.append((a, b, "tags+type"))

    signal_rank = {"id": 3, "name": 2, "tags+type": 1}
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[dict, dict, str]] = []
    for a, b, signal in sorted(
        candidates, key=lambda triple: -signal_rank[triple[2]]
    ):
        key = (a["path"], b["path"]) if a["path"] <= b["path"] else (b["path"], a["path"])
        if key in seen:
            continue
        seen.add(key)
        ordered.append((a, b, signal))
    return ordered[:max_pairs]


def _pairs_in_group(
    group: list[dict], signal: str
) -> list[tuple[dict, dict, str]]:
    """All cross-document pairs inside one id/name group."""
    pairs: list[tuple[dict, dict, str]] = []
    for i in range(len(group)):
        for j in range(i + 1, len(group)):
            a, b = group[i], group[j]
            if _different_docs(a, b):
                pairs.append((a, b, signal))
    return pairs


def _different_docs(a: dict, b: dict) -> bool:
    """True when the two entities live under different first path segments."""
    return a.get("path", "").split("/", 1)[0] != b.get("path", "").split("/", 1)[0]


def _normalize_name(name: str) -> str:
    """Case-insensitive, underscore→space name normalization (graph rules)."""
    return str(name).lower().replace("_", " ").strip()


def _build_pair_prompt(
    entity_a: dict,
    entity_b: dict,
    rel_vocab: frozenset[str] = _REL_VOCAB_DEFAULT,
) -> dict[str, Any]:
    """Compact JSON prompt payload for one candidate pair.

    Includes both entities' ``id``/``name``/``type``/``description`` (bounded
    to 200 chars)/``tags`` plus the sorted relationship vocabulary and the
    reply contract. The LLM MUST return
    ``{"relationship_type": "<vocab member>" | null, "direction": "a_to_b" |
    "b_to_a" | "bidirectional"}``; ``null`` means "no relationship".
    """
    return {
        "entity_a": _entity_payload(entity_a),
        "entity_b": _entity_payload(entity_b),
        "rel_vocab": sorted(rel_vocab),
        "instructions": (
            "Return JSON only: "
            '{"relationship_type": "<one of rel_vocab>" | null, '
            '"direction": "a_to_b" | "b_to_a" | "bidirectional"}. '
            "Use null when the two fichas have no semantic relationship."
        ),
    }


def _entity_payload(entity: dict) -> dict[str, str]:
    """Slice one entity dict into the prompt-safe payload shape."""
    return {
        "id": str(entity.get("id") or ""),
        "name": str(entity.get("name") or ""),
        "type": str(entity.get("type") or ""),
        "description": str(entity.get("description") or "")[:_DESCRIPTION_CHAR_BUDGET],
        "tags": [str(t) for t in (entity.get("tags") or [])],
    }


def _parse_relationship_response(raw: str) -> tuple[str | None, str | None]:
    """Tolerant JSON parse of the Hermes reply → (relationship_type, direction).

    Accepts one optional code fence, coerces ``null``/``none``/missing to
    ``None``, and defaults an invalid/missing direction to ``"a_to_b"``.
    Unparseable replies yield ``(None, None)`` (skip the pair, fail-open).
    """
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None, None
    if not isinstance(data, dict):
        return None, None

    rel_type = data.get("relationship_type")
    rel_type = str(rel_type).strip() if rel_type is not None else None
    if rel_type and rel_type.lower() in ("null", "none", ""):
        rel_type = None

    direction = data.get("direction")
    direction = str(direction).strip() if direction is not None else ""
    if direction not in _VALID_DIRECTIONS:
        direction = "a_to_b"
    return rel_type, direction


def _direction_pair(rel_type: str, direction: str) -> tuple[str, str]:
    """Map ``(rel_type, direction)`` → ``(label_on_a, label_on_b)``.

    ``a_to_b`` + ``crea`` → A gets ``crea``, B gets ``creado-por`` (mirrored
    via ``_REL_MIRROR``); ``bidirectional`` → both ``relacionado-con``;
    ``b_to_a`` swaps the pair. The labels are logical metadata (the on-disk
    format stores bare ``[[target]]`` wikilinks) but they document the
    intended semantics of every written link.
    """
    if direction == "bidirectional":
        return "relacionado-con", "relacionado-con"
    mirror = _REL_MIRROR.get(rel_type, rel_type)
    if direction == "b_to_a":
        return mirror, rel_type
    return rel_type, mirror


def _target_id(entity: dict) -> str:
    """Resolve the wikilink target for an entity: canonical id, else name."""
    cid = str(entity.get("id") or "").strip()
    return cid if cid else str(entity.get("name") or "").strip()


def _write_relationship(
    ficha_a_path: Path,
    ficha_b_path: Path,
    rel_type: str,
    direction: str,
    id_a: str,
    id_b: str,
) -> list[str]:
    """Atomically patch both fichas' ``relaciones`` with ``[[target]]`` links.

    Idempotent: a side whose target is already present (matched by the
    resolved canonical id) is skipped. Returns the list of absolute file
    paths (strings) whose content actually changed.
    """
    label_a, label_b = _direction_pair(rel_type, direction)
    changed: list[str] = []
    if _patch_ficha(ficha_a_path, id_b, label_a):
        changed.append(str(ficha_a_path))
    if _patch_ficha(ficha_b_path, id_a, label_b):
        changed.append(str(ficha_b_path))
    return changed


def _patch_ficha(path: Path, target_id: str, label: str) -> bool:
    """Append ``- "[[target_id]]"`` to one ficha's ``relaciones`` if missing.

    Reads the file, patches ONLY the ``relaciones`` section of the frontmatter
    (``_split_ficha`` + ``_append_relaciones``), and rewrites it atomically.
    The body is preserved verbatim. Returns True when the file changed.
    ``label`` is the logical relationship label (``_direction_pair``); the
    current OKF corpus format stores only the wikilink, so the label is used
    for the debug trace below.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    block, body = _split_ficha(content)
    existing = _extract_relaciones(block)
    if target_id in existing:
        return False
    patched = _append_relaciones(block, [target_id])
    logger.debug(
        "inter-doc write %s -> [[%s]] (%s)", path, target_id, label
    )
    new_content = f"---\n{patched}\n---{body}"
    try:
        _atomic_replace(path, new_content)
    except OSError:
        logger.warning("inter-doc atomic write failed for %s", path, exc_info=True)
        return False
    return True


def _split_ficha(content: str) -> tuple[str, str]:
    """Split a ficha into (frontmatter_block, body), delimiters excluded.

    The body is returned VERBATIM (no stripping) so reassembly
    ``---\n{block}\n---{body}`` reproduces the original byte-for-byte apart
    from the patched frontmatter. Returns ``("", content)`` when the content
    has no frontmatter block.
    """
    if not content.startswith("---"):
        return "", content
    end = content.find("\n---", 3)
    if end < 0:
        return "", content
    block = content[3:end].strip("\n")
    body = content[end + 4:]
    return block, body


def _extract_relaciones(frontmatter_block: str) -> list[str]:
    """Extract existing relationship targets from a frontmatter block.

    Handles both the block form written by ``render_frontmatter_document``
    (``- "[[target]]"``) and the flow form written by
    ``import_enrichment._serialize_frontmatter`` (``relaciones: [a, b]``),
    plus bare canonical-id entries. Targets are the INNER wikilink text (or
    the bare id), i.e. the dedupe key.
    """
    links: list[str] = []
    in_relaciones = False
    for line in frontmatter_block.splitlines():
        stripped = line.strip()
        if not in_relaciones:
            if re.match(r"^relaciones\s*:", line):
                in_relaciones = True
                rest = line.split(":", 1)[1].strip()
                if rest:
                    # Flow form: ``relaciones: ["[[A]]", "[[B]]"]`` or a bare
                    # list of canonical ids ``relaciones: [a, b]``. Split on
                    # commas FIRST so wikilink brackets never fragment entries.
                    for part in rest.split(","):
                        part = part.strip().strip('"').strip("'").strip()
                        m = _RE_WIKILINK.search(part)
                        if m:
                            links.append(m.group(1).strip())
                        else:
                            bare = part.strip("[]").strip()
                            if bare:
                                links.append(bare)
            continue
        if stripped.startswith("-"):
            m = _RE_WIKILINK.search(stripped)
            if m:
                links.append(m.group(1).strip())
            else:
                bare = stripped.lstrip("-").strip().strip('"').strip("'").strip()
                if bare:
                    links.append(bare)
        elif re.match(r"^[A-Za-z_][\w\-]*\s*:", line):
            # Next frontmatter key ends the relaciones block.
            break
        elif stripped:
            break
    return links


def _append_relaciones(frontmatter_block: str, targets: list[str]) -> str:
    """Return the block with ``targets`` appended to ``relaciones``.

    Normalizes an existing flow-form ``relaciones`` line to the block form
    matching ``render_frontmatter_document`` (``  - "[[target]]"``). When the
    header is missing, ``relaciones:`` + entries are appended at the end of
    the block.
    """
    lines = frontmatter_block.splitlines()
    rel_idx: int | None = None
    for i, line in enumerate(lines):
        if re.match(r"^relaciones\s*:", line):
            rel_idx = i
            break

    new_entries = [f'  - "[[{t}]]"' for t in targets]

    if rel_idx is None:
        block_lines = lines[:]
        block_lines.append("relaciones:")
        block_lines.extend(new_entries)
        return "\n".join(block_lines)

    # Find the end of the current relaciones section (block entries follow the
    # header; the next ``key:`` line or end-of-block terminates it).
    section_end = rel_idx + 1
    for i in range(rel_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("-"):
            break
        section_end = i + 1

    block_lines = lines[:rel_idx]
    block_lines.append("relaciones:")
    # Preserve existing entries (both flow-form residue on the header line and
    # block-form lines), then append the new targets.
    rest = lines[rel_idx].split(":", 1)[1].strip()
    if rest:
        for m in _RE_WIKILINK.finditer(rest):
            if f'  - "[[{m.group(1).strip()}]]"' not in block_lines:
                block_lines.append(f'  - "[[{m.group(1).strip()}]]"')
    for line in lines[rel_idx + 1:section_end]:
        if line.strip().startswith("-"):
            block_lines.append(line)
    for entry in new_entries:
        if entry not in block_lines:
            block_lines.append(entry)
    block_lines.extend(lines[section_end:])
    return "\n".join(block_lines)


def _atomic_replace(path: Path, content: str) -> None:
    """Same-directory atomic replace (crash-safe, no partial ficha)."""
    import uuid

    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _mundo_relative(graph: Any, abs_path: str, mundo: str) -> str:
    """Convert an absolute written path to a mundo-relative cache key."""
    try:
        rel = graph._path_from_absolute(abs_path, mundo)  # type: ignore[attr-defined]
        if rel:
            return rel
    except Exception:  # noqa: BLE001 — best-effort fallback
        pass
    return str(abs_path)