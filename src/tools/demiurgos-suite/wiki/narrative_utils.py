"""
Narrative utilities — shared helpers for lore search, conflict detection,
auto-tagging, idea linking, and lore formatting.

All functions are deterministic, pure Python, no network/LLM calls.
Engram integration uses subprocess CLI (same pattern as sync-ideas.py).
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import yaml

# Eager import: rank_bm25 pulls in numpy, whose Windows DLL load can stall
# ~120s when executed lazily inside the MCP event loop (first tool call).
# Loading at module import time keeps first-call latency ~0s.
from rank_bm25 import BM25Okapi  # noqa: E402

# ---------------------------------------------------------------------------
# Constants — theme map, claim patterns, conflict taxonomy
# ---------------------------------------------------------------------------

THEME_MAP: dict[str, list[str]] = {
    "entrenamiento": [
        "entrenar", "entrenó", "adiestrar", "entrenamiento", "maestro",
        "discípulo", "aprendiz", "practice", "train", "training",
    ],
    "batalla": [
        "batalla", "lucha", "combate", "combatir", "enfrentamiento",
        "duelo", "battle", "fight", "combat", "duel",
    ],
    "viaje": [
        "viaje", "viajar", "viajó", "trayecto", "recorrido", "jornada",
        "travesía", "travel", "journey", "voyage",
    ],
    "ritual": [
        "ritual", "ceremonia", "invocación", "rito", "sacrificio",
        "ritual", "ceremony", "invocation",
    ],
    "traicion": [
        "traicionar", "traición", "traidor", "engaño", "traidora",
        "betray", "betrayal", "treachery",
    ],
    "alianza": [
        "alianza", "aliado", "aliarse", "pacto", "tratado", "coalición",
        "alliance", "ally", "pact", "treaty",
    ],
    "descubrimiento": [
        "descubrir", "descubrimiento", "hallazgo", "encontrar", "revelar",
        "discover", "discovery", "finding",
    ],
    "perdida": [
        "perder", "pérdida", "perdido", "desaparecer", "ausencia",
        "loss", "lost", "missing",
    ],
    "ascenso": [
        "ascender", "ascenso", "elevar", "promover", "subir",
        "rise", "ascend", "ascent", "promotion",
    ],
    "caida": [
        "caer", "caída", "declive", "derrumbar", "ruina",
        "fall", "downfall", "collapse", "decline",
    ],
    "creacion": [
        "crear", "creación", "forjar", "construir", "fundar",
        "create", "creation", "forge", "build",
    ],
    "destruccion": [
        "destruir", "destrucción", "aniquilar", "devastar", "arrasar",
        "destroy", "destruction", "annihilate",
    ],
    "profecia": [
        "profecía", "profeta", "vaticinio", "predicción", "augurio",
        "prophecy", "prophet", "prediction",
    ],
    "legado": [
        "legado", "herencia", "linaje", "descendencia", "sucesión",
        "legacy", "heritage", "lineage", "inheritance",
    ],
    "exilio": [
        "exiliar", "exilio", "desterrar", "destierro", "expatriado",
        "exile", "banish", "banishment",
    ],
    "regreso": [
        "regresar", "regreso", "volver", "retornar", "retorno",
        "return", "comeback", "homecoming",
    ],
    "sacrificio": [
        "sacrificar", "sacrificio", "inmolar", "ofrenda", "entregar",
        "sacrifice", "offering",
    ],
    "redencion": [
        "redimir", "redención", "perdonar", "absolver", "salvar",
        "redeem", "redemption", "forgive", "absolve",
    ],
    "corrupcion": [
        "corromper", "corrupción", "corrupto", "pervertir", "degenerar",
        "corrupt", "corruption", "depravity",
    ],
    "poder": [
        "poder", "poderoso", "dominio", "control", "autoridad",
        "power", "powerful", "dominion", "authority",
    ],
    "conocimiento": [
        "conocer", "conocimiento", "saber", "sabiduría", "erudito",
        "knowledge", "wisdom", "lore", "scholar",
    ],
    "naturaleza": [
        "naturaleza", "natural", "bosque", "selva", "montaña",
        "nature", "natural", "forest", "wilderness",
    ],
    "tecnologia": [
        "tecnología", "artefacto", "máquina", "ingenio", "dispositivo",
        "technology", "artifact", "machine", "device",
    ],
    "magia": [
        "magia", "mágico", "hechizo", "conjuro", "encantamiento",
        "magic", "spell", "enchantment", "sorcery",
    ],
    "politica": [
        "política", "gobierno", "reino", "imperio", "consejo",
        "política", "politics", "government", "kingdom", "council",
    ],
    "guerra": [
        "guerra", "invasión", "asedio", "conquista", "ejército",
        "war", "invasion", "siege", "conquest", "army",
    ],
    "paz": [
        "paz", "tregua", "armisticio", "reconciliación", "armonía",
        "peace", "truce", "armistice", "harmony",
    ],
    "amor": [
        "amar", "amor", "enamorar", "pasión", "romance",
        "love", "passion", "romance", "affection",
    ],
    "venganza": [
        "vengar", "venganza", "vendetta", "retribución", "represalia",
        "revenge", "vengeance", "retribution",
    ],
    "misterio": [
        "misterio", "enigma", "secreto", "oculto", "desconocido",
        "mystery", "enigma", "secret", "hidden",
    ],
}

# Regex patterns for claim extraction from frontmatter + body
CLAIM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Date patterns — Spanish and English year mentions
    ("date", re.compile(
        r"(?:murió|nació|falleció|fundado|creado|destruido|desapareció|"
        r"died|born|founded|created|destroyed|vanished)"
        r".*?(?:en\s+(?:el\s+(?:año\s+)?)?|in\s+(?:the\s+(?:year\s+)?)?)"
        r"(\d{3,4}(?:\s*AR)?)",
        re.IGNORECASE,
    )),
    # Status fields in frontmatter
    ("status", re.compile(
        r"^(?:estado|status)\s*:\s*(.+?)$",
        re.MULTILINE | re.IGNORECASE,
    )),
    # Name/alias fields
    ("name", re.compile(
        r"^(?:nombre_real|alias|title|nombre)\s*:\s*(.+?)$",
        re.MULTILINE | re.IGNORECASE,
    )),
    # Relationship descriptions with names
    ("relationship", re.compile(
        r"(?:espos[oa]|hij[oa]|padre|madre|herman[oa]|mentor|discípulo|aliado|enemigo)"
        r"\s+(?:de\s+)?"
        r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,3})",
        re.IGNORECASE,
    )),
]

# Conflict type taxonomy
CONFLICT_TYPES: set[str] = {
    "date_contradiction",
    "status_contradiction",
    "name_mismatch",
    "relationship_conflict",
    "unknown",
}


# ---------------------------------------------------------------------------
# Shell argument sanitization
# ---------------------------------------------------------------------------

def sanitize_shell_arg(arg: str) -> str:
    """Quote a string for safe shell usage. Defense-in-depth for subprocess args.

    Uses shlex.quote(). Callers using subprocess.run() with a list (no shell=True)
    are already safe, but this provides additional protection if the calling pattern
    changes.
    """
    return shlex.quote(arg)


# ---------------------------------------------------------------------------
# Engram CLI helpers
# ---------------------------------------------------------------------------

def engram_search(
    query: str,
    project: str,
    engram_cmd: str = "engram",
    limit: int = 10,
    timeout: int = 15,
) -> list[dict[str, Any]]:
    """Search Engram persistent memory via CLI subprocess.

    Executes ``engram mem search --project <project> --query <query>``.
    Returns parsed list of match dicts with keys: id, title, preview.
    Gracefully returns empty list on any error (CLI not found, timeout, etc.).

    Args:
        query: Search query string.
        project: Engram project name (e.g. "vibrantes").
        engram_cmd: Path or name of the Engram CLI binary.
        limit: Max results (default 10).
        timeout: Subprocess timeout in seconds.
    """
    try:
        result = subprocess.run(
            [
                engram_cmd, "mem", "search",
                "--project", project,
                "--query", query,
                "--limit", str(limit),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return []

        data = json.loads(result.stdout)

        # Engram returns {"result": [{"id": N, "title": "...", ...}, ...]}
        raw_results: list[dict[str, Any]] = data.get("result", [])
        if not isinstance(raw_results, list):
            return []

        return [
            {
                "id": item.get("id", 0),
                "title": str(item.get("title", "")),
                "preview": str(item.get("content", ""))[:300],
            }
            for item in raw_results
            if isinstance(item, dict)
        ]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        return []


def engram_get_observation(
    obs_id: int,
    engram_cmd: str = "engram",
    timeout: int = 15,
) -> str:
    """Retrieve the full content of an Engram observation by ID.

    Executes ``engram mem get-observation --id <obs_id>``.
    Returns the observation content string. Returns empty string on error.

    Args:
        obs_id: Numeric observation ID.
        engram_cmd: Path or name of the Engram CLI binary.
        timeout: Subprocess timeout in seconds.
    """
    try:
        result = subprocess.run(
            [engram_cmd, "mem", "get-observation", "--id", str(obs_id)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return ""

        data = json.loads(result.stdout)
        return str(data.get("content", "") or data.get("observation", ""))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        return ""


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def parse_frontmatter(content: str) -> dict[str, Any]:
    """Extract YAML frontmatter block from a .md file.

    Returns parsed dict or empty dict if no frontmatter found / parse error.
    """
    m = _FM_RE.search(content)
    if not m:
        return {}
    try:
        parsed = yaml.safe_load(m.group(1))
        if isinstance(parsed, dict):
            return parsed
    except yaml.YAMLError:
        pass
    return {}


# ---------------------------------------------------------------------------
# Claim extraction and conflict detection
# ---------------------------------------------------------------------------

def extract_claims(content: str, entity_path: str) -> list[dict[str, str]]:
    """Extract structured claims from entity content using regex patterns.

    Scans frontmatter and body text for date mentions, status fields,
    entity names, and relationship descriptors.

    Returns list of ``{field, value, pattern}`` dicts.
    """
    claims: list[dict[str, str]] = []

    # Parse frontmatter for structured fields
    fm = parse_frontmatter(content)

    # Status from frontmatter
    for fm_key in ("estado", "status"):
        if fm_key in fm:
            claims.append({
                "field": fm_key,
                "value": str(fm[fm_key]).strip(),
                "pattern": "status",
                "source": entity_path,
            })

    # Names from frontmatter
    for fm_key in ("nombre_real", "alias", "title", "nombre"):
        if fm_key in fm:
            claims.append({
                "field": fm_key,
                "value": str(fm[fm_key]).strip(),
                "pattern": "name",
                "source": entity_path,
            })

    # Date fields from frontmatter
    for fm_key in ("año_nacimiento", "año_muerte", "año", "fecha", "year", "founded", "destroyed"):
        if fm_key in fm:
            claims.append({
                "field": fm_key,
                "value": str(fm[fm_key]).strip(),
                "pattern": "date",
                "source": entity_path,
            })

    # Scan body text with regex patterns
    for pattern_name, pattern_re in CLAIM_PATTERNS:
        for match in pattern_re.finditer(content):
            value = match.group(1).strip() if match.lastindex else match.group(0).strip()
            claims.append({
                "field": pattern_name,
                "value": value,
                "pattern": pattern_name,
                "source": entity_path,
            })

    return claims


def _value_similarity(a: str, b: str) -> float:
    """Simple similarity: case-insensitive normalized comparison.

    Returns 1.0 for exact match, 0.0 for completely different.
    """
    a_norm = a.strip().lower()
    b_norm = b.strip().lower()
    if a_norm == b_norm:
        return 1.0
    # Partial match — one is substring of the other
    if a_norm and b_norm:
        shorter = min(a_norm, b_norm, key=len)
        longer = max(a_norm, b_norm, key=len)
        if shorter in longer:
            return 0.5
    return 0.0


def compare_claims(
    entity_claims: list[dict[str, str]],
    engram_claims: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Compare entity claims against Engram claims, returning conflicts.

    Matches claims by field and pattern type. When values differ, assigns
    a conflict_type from the taxonomy: date_contradiction, status_contradiction,
    name_mismatch, relationship_conflict, or unknown.

    Returns list of ``{claim_a, source_a, claim_b, source_b, conflict_type}``.
    """
    conflicts: list[dict[str, str]] = []

    # Index engram claims by field for fast lookup
    engram_by_field: dict[str, list[dict[str, str]]] = {}
    for ec in engram_claims:
        field = ec.get("field", "")
        engram_by_field.setdefault(field, []).append(ec)

    for entity in entity_claims:
        field = entity.get("field", "")
        candidates = engram_by_field.get(field, [])

        for eng in candidates:
            # Skip if values are similar enough
            sim = _value_similarity(entity.get("value", ""), eng.get("value", ""))
            if sim >= 0.8:
                continue

            pattern = entity.get("pattern", "")
            # Map pattern to conflict_type
            conflict_type_map = {
                "date": "date_contradiction",
                "status": "status_contradiction",
                "name": "name_mismatch",
                "relationship": "relationship_conflict",
            }

            conflicts.append({
                "claim_a": entity.get("value", ""),
                "source_a": entity.get("source", ""),
                "claim_b": eng.get("value", ""),
                "source_b": eng.get("source", f"engram#{eng.get('id', '?')}"),
                "conflict_type": conflict_type_map.get(pattern, "unknown"),
            })

    return conflicts


# ---------------------------------------------------------------------------
# Entity and theme extraction
# ---------------------------------------------------------------------------

def extract_entities(text: str, known_names: set[str]) -> list[str]:
    """Find known entity names mentioned in text.

    Case-insensitive substring matching. Returns canonical entity names
    in the order they first appear in text.

    Args:
        text: Free text to scan.
        known_names: Set of known entity names (canonical form).

    Returns:
        List of matched entity names (canonical form, deduplicated).
    """
    if not text or not known_names:
        return []

    text_lower = text.lower()
    found: list[str] = []

    for name in sorted(known_names, key=lambda n: -len(n)):
        name_lower = name.lower()
        # Use word boundaries for multi-word names, substring for single-word
        if " " in name_lower:
            # For multi-word names, use a broader match (flexible ordering)
            words = name_lower.split()
            # Check if all words appear in reasonable proximity
            # Simple approach: all words present somewhere in text
            if all(word in text_lower for word in words):
                if name not in found:
                    found.append(name)
        else:
            # Single-word — substring match
            if name_lower in text_lower and name not in found:
                found.append(name)

    return found


def extract_themes(
    text: str,
    theme_map: dict[str, list[str]] | None = None,
) -> list[str]:
    """Extract themes from text using keyword matching.

    Tokenizes text and checks each theme's keywords. Returns lowercase
    theme names matching at least one keyword.

    Args:
        text: Free text to analyze.
        theme_map: Dict of theme_name → list of keywords. Uses THEME_MAP if None.

    Returns:
        List of matched theme names (lowercase, deterministic order).
    """
    if theme_map is None:
        theme_map = THEME_MAP

    if not text or not theme_map:
        return []

    text_lower = text.lower()
    matched: list[str] = []

    for theme, keywords in theme_map.items():
        for keyword in keywords:
            if keyword in text_lower:
                matched.append(theme)
                break

    return matched


# ---------------------------------------------------------------------------
# Idea Bank — scanning and BM25 search
# ---------------------------------------------------------------------------

def scan_ideas_dir(mundo: str, mundos_path: str) -> list[dict[str, Any]]:
    """Scan mundos/{mundo}/Ideas/ directory, parsing frontmatter + body.

    Returns list of ``{path, frontmatter, body, slug}`` dicts.
    Returns empty list if Ideas/ doesn't exist or is empty.
    """
    ideas_dir = Path(mundos_path) / mundo / "Ideas"
    if not ideas_dir.is_dir():
        return []

    ideas: list[dict[str, Any]] = []
    for md_file in sorted(ideas_dir.glob("*.md")):
        # Skip hidden/index files
        if md_file.name.startswith("_") or md_file.name.startswith("."):
            continue

        try:
            raw = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        fm = parse_frontmatter(raw)

        # Body is everything after the second '---'
        body = raw
        parts = _FM_RE.split(raw, maxsplit=1)
        if len(parts) >= 3:
            body = parts[2]

        slug = fm.get("slug", md_file.stem)

        ideas.append({
            "path": str(md_file.relative_to(Path(mundos_path) / mundo)),
            "frontmatter": fm,
            "body": body.strip(),
            "slug": slug,
        })

    return ideas


def search_ideas_bm25(
    content: str,
    ideas: list[dict[str, Any]],
    threshold: float = 0.3,
) -> list[dict[str, Any]]:
    """Search ideas using BM25Okapi scoring over frontmatter + body.

    Args:
        content: Query text.
        ideas: List from ``scan_ideas_dir()``.
        threshold: Minimum score to include (default 0.3).

    Returns:
        List of ``{slug, score, preview_80chars}`` sorted by score descending.
    """
    if not ideas or not content:
        return []

    # Build corpus: tokenized frontmatter + body
    corpus: list[list[str]] = []
    for idea in ideas:
        fm_text = " ".join(
            str(v) for v in idea["frontmatter"].values()
            if isinstance(v, (str, int, float))
        )
        doc = (fm_text + " " + idea["body"]).lower().split()
        corpus.append(doc)

    if not corpus:
        return []

    # rank_bm25 is imported eagerly at module top (numpy DLL load stalls the
    # MCP event loop if done lazily on first call).
    try:
        tokenized_query = content.lower().split()
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(tokenized_query)
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for idea, score in zip(ideas, scores):
        if score >= threshold:
            body = idea["body"]
            preview = body[:80].replace("\n", " ") + ("…" if len(body) > 80 else "")
            results.append({
                "slug": idea["slug"],
                "score": round(float(score), 4),
                "preview_80chars": preview,
            })

    results.sort(key=lambda r: -r["score"])
    return results


# ---------------------------------------------------------------------------
# Lore formatting — deterministic string template
# ---------------------------------------------------------------------------

def format_lore(data: dict[str, Any]) -> str:
    """Format lore into a deterministic markdown string with [[wikilinks]].

    Sections:
    - Entity summary (name, type, description, content preview)
    - Engram context (observations)
    - Conflicts (if any)

    Empty sections are omitted. ZERO LLM calls.

    Args:
        data: Dict with optional keys: entity, engram, conflicts.

    Returns:
        Formatted markdown string, or empty string if all sections empty.
    """
    sections: list[str] = []
    entity = data.get("entity")
    engram_items = data.get("engram", [])
    conflicts = data.get("conflicts", [])

    # Entity section
    if entity and isinstance(entity, dict) and entity.get("name"):
        lines: list[str] = []
        lines.append(f"## Entity: [[{entity['name']}]]")
        lines.append("")
        etype = entity.get("type", "")
        if etype:
            lines.append(f"**Type**: {etype}")
        desc = entity.get("description", "")
        if desc:
            lines.append(f"**Description**: {desc}")
        tags = entity.get("tags", [])
        if isinstance(tags, list) and tags:
            lines.append(f"**Tags**: {', '.join(str(t) for t in tags)}")
        path = entity.get("path", "")
        if path:
            lines.append(f"**Path**: `{path}`")
        content = entity.get("content", "")
        if content:
            preview = content[:200].replace("\n", " ")
            lines.append(f"\n{preview}…" if len(content) > 200 else f"\n{preview}")
        lines.append("")
        sections.append("\n".join(lines))

    # Engram section
    if engram_items and isinstance(engram_items, list):
        lines = []
        lines.append("## Engram Context")
        lines.append("")
        for i, obs in enumerate(engram_items, 1):
            if isinstance(obs, dict):
                title = obs.get("title", f"Observation {i}")
                preview = obs.get("preview", obs.get("content", ""))
                if isinstance(preview, str) and len(preview) > 200:
                    preview = preview[:200] + "…"
                lines.append(f"{i}. **{title}**")
                if preview:
                    lines.append(f"   {preview}")
                lines.append("")
        sections.append("\n".join(lines))

    # Conflicts section
    if conflicts and isinstance(conflicts, list):
        lines = []
        lines.append("## Conflicts")
        lines.append("")
        for conflict in conflicts:
            if isinstance(conflict, dict):
                ctype = conflict.get("conflict_type", "unknown")
                claim_a = conflict.get("claim_a", "?")
                claim_b = conflict.get("claim_b", "?")
                lines.append(f"- **[{ctype}]** `{claim_a}` vs `{claim_b}`")
        lines.append("")
        sections.append("\n".join(lines))

    return "\n".join(sections).strip()
