"""
Entity Graph Index â€” in-memory OKF entity graph with search and file-watch.

Tasks 2.3â€“2.13: EntityGraphIndex class scanning mundos/{mundo}/ for OKF
files, building an entity cache, and exposing search / entity / links queries.

Thread-safe via RLock. Deterministic â€” regex + logic only, no AI.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# Eager import: rank_bm25 pulls in numpy, whose Windows DLL load can stall
# ~120s when executed lazily inside the MCP event loop (first tool call).
# Loading it at module import time (startup, before the loop/stdio reader
# exist) makes first-call latency ~0s. See mcp-tool-call-hang investigation.
from rank_bm25 import BM25Okapi  # noqa: E402

from .graph_models import EntityDetail, EntityHit

# ---------------------------------------------------------------------------
# Constants (mirror migrate_okf.py exclusions)
# ---------------------------------------------------------------------------

_EXCLUDE_FILES: set[str] = {
    "_README.md",
    "CHANGELOG.md",
    "_Plantilla_Ficha.md",
    "00_Catalogo_Personajes.md",
}

_EXCLUDE_DIRS: set[str] = {
    "_context",
    "arquetipos",
    "ideas",
    "referencias",
    "wiki",
    ".history",
    ".tmp",
    ".papelera",
}

_SKIP_PREFIXES: tuple[str, ...] = ("_",)

_SCAN_SECTIONS: tuple[str, ...] = ("lore", "personajes", "sagas")

# Wikilink regex: [[Name]]
_RE_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")

# Frontmatter delimiter detection
_RE_FRONTMATTER_START = re.compile(r"^---\s*$")
_RE_HAS_TYPE = re.compile(r"^type:", re.MULTILINE)


# ---------------------------------------------------------------------------
# EntityGraphIndex
# ---------------------------------------------------------------------------


class EntityGraphIndex:
    """Thread-safe in-memory entity graph. Read-heavy, write on build/update.

    Usage::

        index = EntityGraphIndex()             # auto-detect mundos/ path
        index = EntityGraphIndex(mundos_path)  # explicit path

        n = index.build("vibrantes")           # returns entity count
        hits = index.search("Rhyz")            # â†’ list[EntityHit]
        detail = index.get_entity("personajes/Rhyz_El_Resonante.md")
        index.start_watch("vibrantes")         # live file watching
        index.stop_watch()                     # stop observing
    """

    def __init__(self, mundos_path: Path | None = None) -> None:
        if mundos_path is None:
            # Auto-detect from file location:
            # graph_indexer.py â†’ wiki/ â†’ demiurgos-suite/ â†’ tools/ â†’ src/ â†’ project/
            _project_root = Path(__file__).resolve().parents[5]
            mundos_path = _project_root / "mundos"

        self._mundos_path: Path = mundos_path
        self._lock: threading.RLock = threading.RLock()
        self._cache: dict[str, Any] = {
            "entities": {},
            "dirty": False,
            "last_build": None,
        }
        self._observer: Any = None  # watchdog Observer, set by start_watch()
        self._watch_timestamps: dict[str, float] = {}  # debounce tracking
        self._active_mundo: str | None = None

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _parse_frontmatter(content: str) -> dict[str, Any]:
        """Extract YAML frontmatter block. Returns empty dict if none found.

        Task 2.4.
        """
        lines = content.split("\n")
        if not lines or not _RE_FRONTMATTER_START.match(lines[0]):
            return {}

        # Find closing `---`
        end_idx: int | None = None
        for i in range(1, len(lines)):
            if _RE_FRONTMATTER_START.match(lines[i]):
                end_idx = i
                break

        if end_idx is None:
            return {}

        yaml_block = "\n".join(lines[1:end_idx])
        try:
            parsed = yaml.safe_load(yaml_block)
            if isinstance(parsed, dict):
                return parsed
            return {}
        except yaml.YAMLError:
            return {}

    @staticmethod
    def _has_okf_frontmatter(content: str) -> bool:
        """Quick check: does content have YAML frontmatter with ``type`` field?"""
        if not content.startswith("---\n") and not content.startswith("---\r\n"):
            return False
        # Find closing ---
        end_match = re.search(r"\n---(\n|$)", content[4:])
        if end_match is None:
            return False
        end_pos = 4 + end_match.start()
        frontmatter = content[4:end_pos]
        return bool(_RE_HAS_TYPE.search(frontmatter))

    @staticmethod
    def _sync_updated_at_in_file(content: str, filepath: Path) -> str | None:
        """Update ``updated_at`` in frontmatter to match file mtime.

        Returns new content string if the timestamp changed, or ``None`` if
        no update was needed (already in sync or not an OKF file).
        """
        if not content.startswith("---\n"):
            return None

        end_match = re.search(r"\n---(\n|$)", content[4:])
        if end_match is None:
            return None

        end_pos = 4 + end_match.start()
        fm_text = content[4:end_pos]

        parsed = yaml.safe_load(fm_text)
        if not isinstance(parsed, dict) or "type" not in parsed:
            return None

        try:
            mtime = filepath.stat().st_mtime
        except OSError:
            return None
        mtime_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

        current = parsed.get("updated_at")
        if current == mtime_iso:
            return None

        body = content[end_pos + 4:]
        new_line = f"updated_at: {mtime_iso}"

        if "updated_at" in parsed:
            new_fm = re.sub(
                r"^updated_at:.*$", new_line, fm_text, count=1, flags=re.MULTILINE
            )
        else:
            # Insert before ``generated:`` or at end of frontmatter
            lines = fm_text.split("\n")
            insert_at = len(lines)
            for i, line in enumerate(lines):
                if line.strip() == "generated:":
                    insert_at = i
                    break
            lines.insert(insert_at, new_line)
            new_fm = "\n".join(lines)

        return "---\n" + new_fm + "\n---\n" + body

    @staticmethod
    def _extract_wikilinks(body: str) -> list[str]:
        """Extract [[Name]] links from body text."""
        return [m.group(1).strip() for m in _RE_WIKILINK.finditer(body)]

    def _should_skip(self, filepath: Path, section_path: Path) -> bool:
        """Check if a file should be excluded from indexing."""
        if filepath.name in _EXCLUDE_FILES:
            return True
        if filepath.name.startswith(_SKIP_PREFIXES):
            return True

        try:
            relative = filepath.relative_to(section_path)
        except ValueError:
            return True

        for part in relative.parts[:-1]:
            if part in _EXCLUDE_DIRS:
                return True
            if part.startswith(_SKIP_PREFIXES):
                return True
        return False

    def _entity_from_file(
        self, filepath: Path, content: str, rel_path: str
    ) -> dict[str, Any] | None:
        """Parse a single OKF .md file into an entity dict. Returns None if not OKF."""
        fm = self._parse_frontmatter(content)
        if not fm or "type" not in fm:
            return None

        # Split body text (everything after frontmatter)
        body_start = content.find("---\n", 4)
        if body_start == -1:
            body_start = content.find("---\r\n", 4)
        if body_start == -1:
            body = content
        else:
            body = content[body_start + 4:]

        name = fm.get("title") or filepath.stem.replace("_", " ")
        forward_links = self._extract_wikilinks(body)
        # Also extract from relaciones frontmatter field
        relaciones_raw = fm.get("relaciones", [])
        if isinstance(relaciones_raw, list):
            for rel in relaciones_raw:
                if isinstance(rel, str):
                    m = _RE_WIKILINK.search(rel)
                    if m:
                        link = m.group(1).strip()
                        if link not in forward_links:
                            forward_links.append(link)

        entity: dict[str, Any] = {
            "name": name,
            "type": fm.get("type", "Ficha"),
            "path": rel_path,
            "title": fm.get("title", ""),
            "description": fm.get("description", ""),
            "tags": fm.get("tags", []) if isinstance(fm.get("tags"), list) else [],
            "forward_links": forward_links,
            "backlinks": [],
            "relaciones": relaciones_raw if isinstance(relaciones_raw, list) else [],
            "content": body,
            "word_count": len(body.split()),
        }
        return entity

    def _scan_mundo(self, mundo: str) -> list[dict[str, Any]]:
        """Walk lore/, personajes/, sagas/ and parse all OKF .md files.

        Returns list of entity dicts. Skips non-OKF, _-prefixed, excluded dirs.

        Task 2.5.
        """
        mundo_path = self._mundos_path / mundo
        if not mundo_path.is_dir():
            return []

        entities: list[dict[str, Any]] = []

        for section in _SCAN_SECTIONS:
            section_path = mundo_path / section
            if not section_path.is_dir():
                continue

            for md_file in sorted(section_path.rglob("*.md")):
                if self._should_skip(md_file, section_path):
                    continue

                try:
                    rel_path = str(md_file.relative_to(mundo_path)).replace("\\", "/")
                except ValueError:
                    continue

                try:
                    content = md_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue

                entity = self._entity_from_file(md_file, content, rel_path)
                if entity is not None:
                    entities.append(entity)

        return entities

    def _recompute_backlinks(self) -> None:
        """Rebuild backlinks for all entities. O(n) over all entities.

        Task 2.7.
        Must be called with _lock held.
        """
        # Clear all backlinks
        for entity in self._cache["entities"].values():
            entity["backlinks"] = []

        # Rebuild: for each entity, for each forward_link,
        # add this entity's path to the target's backlinks.
        for source_path, source_entity in self._cache["entities"].items():
            for link_name in source_entity["forward_links"]:
                # Resolve link name â†’ entity path
                target_path = self._resolve_link(link_name)
                if target_path and target_path in self._cache["entities"]:
                    target = self._cache["entities"][target_path]
                    if source_path not in target["backlinks"]:
                        target["backlinks"].append(source_path)

    def _resolve_link(self, link_name: str) -> str | None:
        """Resolve a wikilink name to an entity cache key path.

        The link name comes from [[Name]] syntax â€” it's a display name.
        We match against entity names in the cache (case-insensitive, ignoring underscores).

        Returns the entity path (cache key) or None if unresolved.
        """
        name_lower = link_name.lower().replace("_", " ").strip()
        for path, entity in self._cache["entities"].items():
            entity_name_lower = entity["name"].lower().replace("_", " ").strip()
            if entity_name_lower == name_lower:
                return path

            # Also try matching the filename stem
            file_stem = Path(path).stem.lower().replace("_", " ").strip()
            if file_stem == name_lower:
                return path

        return None

    def _path_from_absolute(self, abs_path: str, mundo: str) -> str | None:
        """Convert an absolute filesystem path to a relative path from mundo root."""
        try:
            mundo_path = self._mundos_path / mundo
            rel = Path(abs_path).relative_to(mundo_path)
            return str(rel).replace("\\", "/")
        except ValueError:
            return None

    def _watch_callback(self, abs_path: str, mundo: str, event_type: str) -> None:
        """Called by watchdog on file events. Debounced with simple time check.

        Task 2.12 internal.
        """
        now = time.time()
        last = self._watch_timestamps.get(abs_path, 0)
        if now - last < 0.5:  # 500 ms debounce
            return
        self._watch_timestamps[abs_path] = now

        # Note: update() and cache mutations acquire _lock internally
        if event_type == "deleted":
            rel_path = self._path_from_absolute(abs_path, mundo)
            if rel_path is None:
                return
            with self._lock:
                if rel_path in self._cache["entities"]:
                    del self._cache["entities"][rel_path]
                    self._recompute_backlinks()
                    self._cache["dirty"] = True
        else:
            # created or modified
            self.update(abs_path, mundo)

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    def build(self, mundo: str) -> int:
        """Full scan â†’ populate cache â†’ recompute backlinks. Returns entity count.

        Task 2.6.
        """
        entities = self._scan_mundo(mundo)

        with self._lock:
            self._cache["entities"] = {}
            for entity in entities:
                self._cache["entities"][entity["path"]] = entity
            self._recompute_backlinks()
            self._cache["dirty"] = False
            self._cache["last_build"] = datetime.now(timezone.utc).isoformat()
            self._active_mundo = mundo

        return len(entities)

    def update(self, file_path: str, mundo: str) -> None:
        """Re-read a single file and update its cache entry. Recomputes backlinks.

        Also syncs ``updated_at`` in the file's YAML frontmatter to match
        the filesystem mtime, so the index always reflects real edits.

        Task 2.8.
        """
        path = Path(file_path)

        if path.suffix.lower() != ".md":
            return

        mundo_path = self._mundos_path / mundo
        try:
            rel_path = str(path.relative_to(mundo_path)).replace("\\", "/")
        except ValueError:
            return

        # Read and parse
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return

        entity = self._entity_from_file(path, content, rel_path)

        with self._lock:
            if entity is not None:
                # Preserve backlinks from previous entry if it existed
                prev = self._cache["entities"].get(rel_path)
                if prev:
                    entity["backlinks"] = prev.get("backlinks", [])
                self._cache["entities"][rel_path] = entity
            else:
                # Not OKF â€” remove if previously cached
                if rel_path in self._cache["entities"]:
                    del self._cache["entities"][rel_path]

            self._recompute_backlinks()
            self._cache["dirty"] = True

        # Sync updated_at in the file's YAML frontmatter
        try:
            new_content = self._sync_updated_at_in_file(content, path)
            if new_content is not None:
                path.write_text(new_content, encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass  # Non-critical â€” cache is updated either way

    def start_watch(self, mundo: str) -> None:
        """Start watchdog observer on mundos/{mundo}/{lore,personajes,sagas}.

        Debounce 500ms. On create/modify â†’ update(). On delete â†’ remove entity.

        Task 2.12.
        """
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            raise ImportError(
                "watchdog is required for file watching. "
                "Install with: pip install watchdog"
            )

        mundo_path = self._mundos_path / mundo
        if not mundo_path.is_dir():
            return

        # Build handler as a closure to avoid extra class
        indexer_ref = self  # noqa: F841 â€” captured by closure below

        class _WorldFileHandler(FileSystemEventHandler):
            def on_created(inner_self, event):  # noqa: N805
                if not event.is_directory:
                    indexer_ref._watch_callback(
                        event.src_path, mundo, "created"
                    )

            def on_modified(inner_self, event):  # noqa: N805
                if not event.is_directory:
                    indexer_ref._watch_callback(
                        event.src_path, mundo, "modified"
                    )

            def on_deleted(inner_self, event):  # noqa: N805
                if not event.is_directory:
                    indexer_ref._watch_callback(
                        event.src_path, mundo, "deleted"
                    )

        observer = Observer()
        watched = False
        for section in _SCAN_SECTIONS:
            section_path = mundo_path / section
            if section_path.is_dir():
                observer.schedule(
                    _WorldFileHandler(), str(section_path), recursive=True
                )
                watched = True

        if watched:
            observer.start()
            self._observer = observer
            self._active_mundo = mundo

    def stop_watch(self) -> None:
        """Stop the watchdog observer. Safe to call multiple times.

        Task 2.13.
        """
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None

    # -------------------------------------------------------------------
    # Query
    # -------------------------------------------------------------------

    def search(
        self, query: str, filters: dict[str, Any] | None = None
    ) -> list[EntityHit]:
        """Search the entity graph by prefix + BM25.

        1. Tokenize query â†’ prefix match on entity name (score +10 per token).
        2. BM25Okapi over (title + description + tags) corpus.
        3. Merge scores, apply filters, sort desc, limit 20.

        Thread-safe.

        Task 2.9.
        """
        filters = filters or {}
        tokens = query.lower().split()
        has_tokens = bool(tokens)

        # Empty query with no filters â†’ fast return
        if not has_tokens and not filters:
            return []

        with self._lock:
            entities = list(self._cache["entities"].values())
            if not entities:
                return []

            # --- Build corpus for BM25 ---
            corpus: list[list[str]] = []
            entity_paths: list[str] = []
            for ent in entities:
                tags_raw = ent.get("tags", [])
                tags_str = [t for t in tags_raw if isinstance(t, str)]
                doc = (
                    f"{ent['title']} {ent['description']} "
                    + " ".join(tags_str)
                )
                corpus.append(doc.lower().split())
                entity_paths.append(ent["path"])

            # Build BM25 index (only if we have search tokens)
            # rank_bm25 is imported eagerly at module top — loading numpy
            # lazily here would stall the MCP event loop on first call.
            if has_tokens:
                if any(corpus):
                    try:
                        bm25 = BM25Okapi(corpus)
                        bm25_scores: list[float] = bm25.get_scores(tokens)
                    except ImportError:
                        bm25_scores = [0.0] * len(entities)
                else:
                    # Degenerate corpus: every entity lacks indexable
                    # title/description/tags → BM25Okapi raises
                    # ZeroDivisionError (empty term frequency dict). Skip BM25
                    # and keep name-prefix matching (score +10 per token).
                    bm25_scores = [0.0] * len(entities)
            else:
                bm25_scores = [0.0] * len(entities)

            # --- Compute final scores ---
            hits: list[EntityHit] = []
            for ent, bm25_score in zip(entities, bm25_scores):
                # Prefix match: each query token as prefix of entity name
                prefix_score = 0.0
                name_lower = ent["name"].lower()
                for token in tokens:
                    if name_lower.startswith(token):
                        prefix_score += 10.0
                    else:
                        # Also check individual words in the name
                        for word in name_lower.split():
                            if word.startswith(token):
                                prefix_score += 10.0
                                break

                total_score = prefix_score + bm25_score

                # Skip entities with zero relevance when there are search tokens
                if has_tokens and total_score <= 0:
                    continue

                # Apply filters
                if not self._apply_filters(ent, filters):
                    continue

                hits.append(
                    EntityHit(
                        name=ent["name"],
                        type=ent["type"],
                        path=ent["path"],
                        title=ent["title"],
                        description=ent["description"],
                        tags=ent.get("tags", []),
                        link_count=len(ent.get("forward_links", []))
                        + len(ent.get("backlinks", [])),
                        score=total_score,
                    )
                )

            # Sort by score descending, then by name ascending as tiebreaker
            hits.sort(key=lambda h: (-h.score, h.name.lower()))
            return hits[:20]

    @staticmethod
    def _apply_filters(entity: dict[str, Any], filters: dict[str, Any]) -> bool:
        """Check if entity matches the given filters."""
        # Type filter
        if "type" in filters and filters["type"]:
            if entity.get("type", "").lower() != filters["type"].lower():
                return False

        # Tag filter (single tag)
        if "tag" in filters and filters["tag"]:
            entity_tags = [t.lower() for t in entity.get("tags", [])]
            if filters["tag"].lower() not in entity_tags:
                return False

        # Tags filter (list)
        if "tags" in filters and filters["tags"]:
            required = [t.lower() for t in filters["tags"]]
            entity_tags = [t.lower() for t in entity.get("tags", [])]
            if not all(t in entity_tags for t in required):
                return False

        return True

    def get_entity(self, path: str) -> EntityDetail | None:
        """Return full entity with backlinks and forward links.

        Task 2.10.
        """
        with self._lock:
            ent = self._cache["entities"].get(path)
            if ent is None:
                return None

            return EntityDetail(
                name=ent["name"],
                type=ent["type"],
                path=ent["path"],
                title=ent["title"],
                description=ent["description"],
                tags=ent.get("tags", []),
                content=ent.get("content", ""),
                forward_links=ent.get("forward_links", []),
                backlinks=ent.get("backlinks", []),
                relaciones=ent.get("relaciones", []),
                word_count=ent.get("word_count", 0),
            )

    def get_links(
        self,
        entity_path: str | None = None,
        kind: str = "forward",
    ) -> list[dict[str, Any]]:
        """Query the link graph.

        Kind variants:

        - ``"backlinks"`` â€” entities that link TO entity_path. Requires entity_path.
        - ``"forward"`` â€” entities that entity_path links TO. Requires entity_path.
        - ``"dead"`` â€” wikilinks that don't resolve to any entity. Returns
          ``[{source: entity_path, target: link_name}]``.
        - ``"orphans"`` â€” entities with no incoming AND no outgoing links.
        - ``"hubs"`` â€” top 20 entities with most total links.
        - ``"suggest"`` â€” entities sharing tags with entity_path but NOT linked.
          Requires entity_path.

        Task 2.11.
        """
        kind = kind.lower()

        with self._lock:
            if kind == "backlinks":
                return self._get_backlinks(entity_path)
            elif kind == "forward":
                return self._get_forward_links(entity_path)
            elif kind == "dead":
                return self._get_dead_links()
            elif kind == "orphans":
                return self._get_orphans()
            elif kind == "hubs":
                return self._get_hubs()
            elif kind == "suggest":
                return self._get_suggestions(entity_path)
            else:
                raise ValueError(
                    f"Unknown link kind: {kind!r}. "
                    f"Expected: backlinks, forward, dead, orphans, hubs, suggest"
                )

    def _get_backlinks(self, entity_path: str | None) -> list[dict[str, Any]]:
        """Entities that link TO entity_path."""
        if entity_path is None:
            raise ValueError("entity_path is required for backlinks")
        ent = self._cache["entities"].get(entity_path)
        if ent is None:
            return []
        result: list[dict[str, Any]] = []
        for backlink_path in ent.get("backlinks", []):
            linked = self._cache["entities"].get(backlink_path)
            if linked:
                result.append(
                    {
                        "name": linked["name"],
                        "type": linked["type"],
                        "path": linked["path"],
                    }
                )
        return result

    def _get_forward_links(self, entity_path: str | None) -> list[dict[str, Any]]:
        """Entities that entity_path links TO."""
        if entity_path is None:
            raise ValueError("entity_path is required for forward links")
        ent = self._cache["entities"].get(entity_path)
        if ent is None:
            return []
        result: list[dict[str, Any]] = []
        for link_name in ent.get("forward_links", []):
            target_path = self._resolve_link(link_name)
            if target_path and target_path in self._cache["entities"]:
                target = self._cache["entities"][target_path]
                result.append(
                    {
                        "name": target["name"],
                        "type": target["type"],
                        "path": target["path"],
                    }
                )
            else:
                result.append(
                    {
                        "name": link_name,
                        "type": "?",
                        "path": None,
                    }
                )
        return result

    def _get_dead_links(self) -> list[dict[str, Any]]:
        """Wikilinks that don't resolve to any entity in the index."""
        result: list[dict[str, Any]] = []
        for ent in self._cache["entities"].values():
            for link_name in ent.get("forward_links", []):
                target_path = self._resolve_link(link_name)
                if target_path is None or target_path not in self._cache["entities"]:
                    result.append(
                        {
                            "source": ent["path"],
                            "source_name": ent["name"],
                            "target": link_name,
                        }
                    )
        return result

    def _get_orphans(self) -> list[dict[str, Any]]:
        """Entities with no incoming AND no outgoing links."""
        result: list[dict[str, Any]] = []
        for ent in self._cache["entities"].values():
            if not ent.get("forward_links") and not ent.get("backlinks"):
                result.append(
                    {
                        "name": ent["name"],
                        "type": ent["type"],
                        "path": ent["path"],
                    }
                )
        return result

    def _get_hubs(self, n: int = 20) -> list[dict[str, Any]]:
        """Top N entities with most total links (forward + backlinks)."""
        scored: list[tuple[dict[str, Any], int]] = [
            (
                {
                    "name": ent["name"],
                    "type": ent["type"],
                    "path": ent["path"],
                },
                len(ent.get("forward_links", [])) + len(ent.get("backlinks", [])),
            )
            for ent in self._cache["entities"].values()
        ]
        scored.sort(key=lambda x: -x[1])
        return [s[0] for s in scored[:n]]

    def _get_suggestions(self, entity_path: str | None) -> list[dict[str, Any]]:
        """Entities sharing tags with entity_path but NOT already linked."""
        if entity_path is None:
            raise ValueError("entity_path is required for suggestions")

        ent = self._cache["entities"].get(entity_path)
        if ent is None:
            return []

        my_tags = set(t.lower() for t in ent.get("tags", []))
        if not my_tags:
            return []

        my_forward = set(ent.get("forward_links", []))
        # Also check who I'm linked FROM (backlinks)
        my_backlink_entities: set[str] = set()
        for other_ent in self._cache["entities"].values():
            if entity_path in other_ent.get("forward_links", []):
                my_backlink_entities.add(other_ent["path"])

        result: list[dict[str, Any]] = []
        for other_ent in self._cache["entities"].values():
            if other_ent["path"] == entity_path:
                continue

            # Already linked (outgoing or incoming)?
            other_name = other_ent["name"]
            if other_name in my_forward:
                continue
            if other_ent["path"] in my_backlink_entities:
                continue
            # Also check if I appear in their forward links
            my_name = ent["name"]
            if my_name in other_ent.get("forward_links", []):
                continue

            # Share tags?
            other_tags = set(t.lower() for t in other_ent.get("tags", []))
            shared = my_tags & other_tags
            if shared:
                result.append(
                    {
                        "name": other_ent["name"],
                        "type": other_ent["type"],
                        "path": other_ent["path"],
                        "shared_tags": sorted(shared),
                    }
                )

        # Sort by number of shared tags descending
        result.sort(key=lambda r: -len(r.get("shared_tags", [])))
        return result[:20]

    # -------------------------------------------------------------------
    # Status / introspection
    # -------------------------------------------------------------------

    def get_entity_names(self) -> set[str]:
        """Return the set of all canonical entity names currently in the cache.

        Thread-safe snapshot for auto-tag entity resolution.
        """
        with self._lock:
            return {ent["name"] for ent in self._cache["entities"].values()}

    @property
    def entity_count(self) -> int:
        """Number of entities currently in cache."""
        with self._lock:
            return len(self._cache["entities"])

    @property
    def dirty(self) -> bool:
        """Has the cache been modified since last build?"""
        with self._lock:
            return self._cache["dirty"]

    @property
    def last_build(self) -> str | None:
        """ISO 8601 timestamp of last full build."""
        with self._lock:
            return self._cache["last_build"]
