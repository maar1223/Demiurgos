#!/usr/bin/env python3
"""
sync-ideas.py — Banco de Ideas Sync Tool

Pulls unprocessed rows from Google Sheets, transcribes voice notes via
faster-whisper (GPU/CPU fallback), and writes local Idea files as
YAML frontmatter + markdown body in `Ideas/{slug}.md`.

Usage:
    python sync-ideas.py [--dry-run]

Config (from .env file or environment variables):
    GOOGLE_SHEETS_ID            — Google Sheets spreadsheet ID
    GOOGLE_SERVICE_ACCOUNT_JSON — Path to service account JSON key file
    TELEGRAM_BOT_TOKEN          — Telegram bot token (for voice downloads)

Sheet row schema (columns A–J):
    id | timestamp | source | type | content | link_audio | link_imagen | drive_link | processed | status

Voice flow (Telegram → Pipedream → Sheets → sync-ideas.py):
    1. User sends voice note to Telegram bot
    2. Pipedream saves row with source=telegram_voice, link_audio=file_id
    3. sync-ideas.py reads file_id from link_audio column
    4. Downloads from Telegram API, faster-whisper transcribes → Ideas/{slug}.md

Slug format:
    {YYYY-MM-DD}-{first-4-meaningful-words-lowercase-hyphenated}
    Collision: append -2, -3, etc.

Engram persistence:
    Attempts `engram mem save` via CLI if available.
    Falls back to JSON report on stdout for the calling agent to handle.

Dependencies (pip install):
    gspread google-auth google-api-python-client faster-whisper requests
"""

import os
import re
import sys
import json
import uuid
import hashlib
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone
import requests  # for Telegram audio download


# ---------------------------------------------------------------------------
# World discovery
# ---------------------------------------------------------------------------

def discover_world() -> str:
    """
    Discover the active narrative world.
    
    Priority:
    1. DEMIURGOS_WORLD environment variable (from .env)
    2. First subdirectory of mundos/ (dynamic discovery)
    
    Raises SystemExit if no world found and DEMIURGOS_WORLD is not set.
    """
    # 1. Environment variable
    world = os.environ.get("DEMIURGOS_WORLD")
    if world:
        validate_world_structure(world)
        return world
    # 2. Scan mundos/ directory
    mundos_dir = Path("mundos")
    if mundos_dir.exists():
        subdirs = sorted([d.name for d in mundos_dir.iterdir() if d.is_dir()])
        if subdirs:
            world = subdirs[0]
            validate_world_structure(world)
            return world
    # 3. No world found — fatal configuration error
    print("ERROR: No se encontró ningún mundo en mundos/. Creá uno o definí DEMIURGOS_WORLD.", file=sys.stderr)
    sys.exit(1)


def validate_world_structure(world: str) -> list[str]:
    """
    Soft-validate that a world has the expected narrative structure.
    
    Checks for mundos/{world}/Personajes/ and mundos/{world}/Lore/.
    Prints warnings for missing directories. Does NOT block execution.
    Returns list of missing expected directories.
    """
    expected = ["Personajes", "Lore"]
    missing = []
    for d in expected:
        if not (Path("mundos") / world / d).exists():
            missing.append(d)
    if missing:
        print(f"  ⚠ El mundo '{world}' no tiene: {', '.join(missing)}.", file=sys.stderr)
        print(f"     Estructura esperada: mundos/{world}/{{Personajes, Lore, ...}}", file=sys.stderr)
    return missing


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENV_PATHS = [
    Path(".env"),
    Path(__file__).resolve().parent / ".env",
]

STOP_WORDS = frozenset({
    # Spanish
    "el", "la", "los", "las", "lo", "un", "una", "unos", "unas",
    "de", "del", "en", "con", "por", "para", "que", "es", "son",
    "y", "e", "o", "u", "a", "al", "se", "su", "sus", "mi", "mis",
    "tu", "tus", "no", "si", "ya", "me", "te", "nos", "os", "le", "les",
    "más", "muy", "tan", "como", "pero", "eso", "esa", "ese", "este",
    "esta", "esto", "entre", "hacia", "hasta", "desde", "sobre",
    "hay", "era", "fue", "ser", "hacer", "tener", "estar", "haber",
    "todo", "toda", "todos", "todas", "algo", "nada", "cada", "otro",
    "porque", "cuando", "donde", "también", "asi", "solo", "sólo",
    # English
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "from", "by", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can", "shall",
    "this", "that", "these", "those", "it", "its", "i", "you", "he",
    "she", "they", "we", "me", "him", "her", "us", "them", "my", "your",
    "his", "our", "their", "not", "just", "very", "really", "so", "if",
    "then", "than", "too", "also", "now", "here", "there", "all", "some",
    "any", "each", "every", "both", "few", "more", "most", "other",
})


# ---------------------------------------------------------------------------
# .env loader (manual — no python-dotenv dependency)
# ---------------------------------------------------------------------------

def load_env() -> None:
    """Load .env into os.environ, trying multiple paths."""
    for candidate in ENV_PATHS:
        if candidate.exists():
            _parse_env_file(candidate)
            break


def _parse_env_file(path: Path) -> None:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


# ---------------------------------------------------------------------------
# Google Sheets client
# ---------------------------------------------------------------------------

def get_clients():
    """Authenticate and return (sheets_service, drive_service)."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_path:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON no está configurado en .env"
        )

    creds = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    sheets = build("sheets", "v4", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return sheets, drive


# ---------------------------------------------------------------------------
# Sheet operations
# ---------------------------------------------------------------------------

COLUMN_HEADERS = [
    "id", "timestamp", "source", "type", "content",
    "link_audio", "link_imagen", "drive_link", "processed", "status",
]


def get_unprocessed_rows(sheets, spreadsheet_id: str):
    """
    Return list of (row_number, padded_row_data, col_map) for rows
    where processed is falsy.
    """
    result = sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="A:J",
    ).execute()

    values = result.get("values", [])
    if len(values) < 2:
        return [], values

    headers = [h.strip().lower() for h in values[0]]
    col_map = {h: i for i, h in enumerate(headers)}

    unprocessed = []
    for i, row in enumerate(values[1:], start=2):  # 1-indexed + header row
        padded = _pad_row(row, len(headers))
        processed_val = _safe_get(padded, col_map, "processed", "").strip().lower()
        if processed_val in ("false", "f", "0", "no", ""):
            unprocessed.append((i, padded, col_map))

    return unprocessed, values


def mark_row_processed(sheets, spreadsheet_id: str, row: int, status: str):
    """Write TRUE to processed column and status to status column."""
    processed_col = _col_letter(COLUMN_HEADERS.index("processed") + 1)
    status_col = _col_letter(COLUMN_HEADERS.index("status") + 1)
    range_ = f"{processed_col}{row}:{status_col}{row}"
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_,
        valueInputOption="RAW",
        body={"values": [[True, status]]},
    ).execute()


def _pad_row(row, width):
    return row + [""] * max(0, width - len(row))


def _safe_get(row, col_map, name, default=""):
    idx = col_map.get(name)
    if idx is None or idx >= len(row):
        return default
    return (row[idx] or "").strip()


def _col_letter(n: int) -> str:
    """1-indexed column number → letter (1→A, 2→B, ... 9→I)."""
    return chr(ord("A") + n - 1)


# ---------------------------------------------------------------------------
# Transcription (faster-whisper)
# ---------------------------------------------------------------------------

def download_from_telegram(file_id: str, dest: Path) -> Path:
    """Download a voice file from Telegram using file_id."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN no está configurado en .env")

    # Step 1: get file path from Telegram
    get_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
    resp = requests.get(get_url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    file_path = data["result"]["file_path"]

    # Step 2: download the file
    download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    audio_resp = requests.get(download_url, timeout=120)
    audio_resp.raise_for_status()
    dest.write_bytes(audio_resp.content)
    print(f"   📥 Descargado de Telegram: {file_path}", file=sys.stderr)
    return dest


def download_from_drive(drive, file_id: str, dest: Path) -> Path:
    """Download a file from Google Drive by file ID."""
    from googleapiclient.http import MediaIoBaseDownload
    import io

    request = drive.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    dest.write_bytes(fh.read())
    return dest


def transcribe_audio(audio_path: Path) -> str:
    """
    Transcribe Spanish audio with faster-whisper base model.
    GPU (CUDA) first, CPU fallback.
    """
    from faster_whisper import WhisperModel

    try:
        model = WhisperModel("base", device="cuda", compute_type="float16")
        print("   ℹ usando GPU (CUDA)", file=sys.stderr)
    except Exception:
        print("   ⚠ GPU no disponible — usando CPU", file=sys.stderr)
        model = WhisperModel("base", device="cpu", compute_type="int8")

    segments, _info = model.transcribe(str(audio_path), language="es")
    text = " ".join(seg.text.strip() for seg in segments)
    return text


# ---------------------------------------------------------------------------
# Image processing (Telegram download + Qwen vision + dedup)
# ---------------------------------------------------------------------------


# Known lore entities for image routing (extracted from mundos/{world}/Lore/ and mundos/{world}/Personajes/ dirs)
KNOWN_ENTITY_FILES = {}  # populated lazily by scan_known_entities()


def scan_known_entities(lore_root: Path, personajes_root: Path) -> dict:
    """
    Scan mundos/{world}/Lore/ and mundos/{world}/Personajes/ directory trees, extract "entity names"
    from filenames (stem, lowercase) for keyword matching during image routing.
    Returns dict: { normalized_stem: relative_path }
    """
    entities = {}
    for root_dir in [lore_root, personajes_root]:
        if not root_dir.exists():
            continue
        for fpath in sorted(root_dir.rglob("*.md")):
            stem = fpath.stem.lower()
            # Skip index/changelog/template files
            if stem.startswith("_") or stem in ("changelog", "indice_de_terminos", "plantilla"):
                continue
            # Extract meaningful name: remove leading numbers and underscores
            clean = re.sub(r"^[\d_]+", "", stem).replace("_", " ").strip()
            if clean and len(clean) > 2:
                entities[clean] = str(fpath.relative_to(fpath.parent.parent.parent))
                # Also add the raw stem for matching
                entities[stem] = str(fpath.relative_to(fpath.parent.parent.parent))
    return entities


def download_image_from_telegram(file_id: str, dest: Path) -> Path:
    """Download an image file from Telegram using file_id (reuses getFile pattern)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN no está configurado en .env")

    get_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
    resp = requests.get(get_url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    file_path = data["result"]["file_path"]
    file_size = data["result"].get("file_size", 0)

    # Check size before download (>10MB = reject)
    if file_size > 10 * 1024 * 1024:
        raise RuntimeError(f"image_too_large: {file_size} bytes excede 10MB")

    download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    img_resp = requests.get(download_url, timeout=120)
    img_resp.raise_for_status()
    dest.write_bytes(img_resp.content)
    print(f"   📥 Imagen descargada de Telegram: {file_path}", file=sys.stderr)
    return dest


def _get_image_format(image_bytes: bytes) -> str | None:
    """Detect image format from magic bytes. Returns ext ('.jpg', '.png', etc.) or None."""
    signatures = {
        b"\xff\xd8\xff": ".jpg",
        b"\x89PNG\r\n\x1a\n": ".png",
        b"GIF87a": ".gif",
        b"GIF89a": ".gif",
        b"RIFF": ".webp",  # WebP starts with RIFF
        b"BM": ".bmp",
    }
    for sig, ext in signatures.items():
        if image_bytes[:len(sig)] == sig:
            return ext
    return None


def compute_sha256(data: bytes) -> str:
    """Return hex SHA256 of bytes."""
    return hashlib.sha256(data).hexdigest()


def build_known_hashes(imagenes_dirs: list[Path]) -> set:
    """
    Scan existing images in given directories and return set of SHA256 hashes.
    Used for dedup before downloading.
    """
    known = set()
    for d in imagenes_dirs:
        if not d.exists():
            continue
        for fpath in d.iterdir():
            if fpath.is_file() and fpath.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
                try:
                    known.add(compute_sha256(fpath.read_bytes()))
                except Exception:
                    pass
    return known


def call_qwen_vision(image_bytes: bytes, text: str) -> dict | None:
    """
    Call Qwen 3.6 vision via OpenCode Go OpenAI-compatible endpoint.
    Returns parsed JSON dict or None on failure (connection/timeout/parse error).
    """
    import base64

    endpoint = os.environ.get("QWEN_ENDPOINT", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("QWEN_MODEL", "qwen3.6-plus")

    # API key: try QWEN_API_KEY first, fall back to OPENCODE_API_KEY
    api_key = os.environ.get("QWEN_API_KEY") or os.environ.get("OPENCODE_API_KEY")
    if not api_key:
        print("   ⚠ Qwen API key not set (QWEN_API_KEY or OPENCODE_API_KEY)", file=sys.stderr)
        return None

    b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Detect MIME from magic bytes for the data URI
    ext = _get_image_format(image_bytes) or ".jpg"
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}
    mime = mime_map.get(ext, "image/jpeg")

    user_content = [
        {"type": "image_url", "image_url": f"data:{mime};base64,{b64}"},
    ]
    if text and text != "[Image — pending Qwen analysis]":
        user_content.append({"type": "text", "text": text})

    system_prompt = (
        "Analizá esta imagen. Describí colores, composición, texturas, estilo, "
        "y atmósfera. Luego, evaluá si esta imagen coincide con el texto adjunto: "
        f"[{text}]. "
        "Respondé en español estrictamente en este formato JSON:\n\n"
        '{\n'
        '  "descripcion": "...",\n'
        '  "veredicto": "confirma|contradice|no_aplica",\n'
        '  "analisis": "...",\n'
        '  "tags": ["..."]\n'
        '}'
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            f"{endpoint}/chat/completions",
            json=payload,
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        parsed = json.loads(raw)

        # Validate expected keys
        if not isinstance(parsed, dict):
            return None
        parsed.setdefault("descripcion", "")
        parsed.setdefault("veredicto", "no_aplica")
        parsed.setdefault("analisis", "")
        parsed.setdefault("tags", [])
        return parsed
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        print("   ⚠ Qwen no disponible — connection error/timeout", file=sys.stderr)
        return None
    except (requests.exceptions.RequestException, json.JSONDecodeError) as exc:
        print(f"   ⚠ Error al llamar a Qwen: {exc}", file=sys.stderr)
        return None


def call_qwen_categorize(text: str) -> dict | None:
    """
    Call Qwen 3.6 via OpenCode Go endpoint to categorize an idea.
    Returns {"destino": "general"} or {"destino": "world", "world": "<name>"}
    or None on failure (connection/timeout/parse error).
    Replicates call_qwen_vision pattern: same endpoint, auth, and error handling.
    """
    endpoint = os.environ.get("QWEN_ENDPOINT", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("QWEN_MODEL", "qwen3.6-plus")

    # API key: try QWEN_API_KEY first, fall back to OPENCODE_API_KEY
    api_key = os.environ.get("QWEN_API_KEY") or os.environ.get("OPENCODE_API_KEY")
    if not api_key:
        print("   ⚠ Qwen API key not set (QWEN_API_KEY or OPENCODE_API_KEY)", file=sys.stderr)
        return None

    system_prompt = (
        "Categoriza esta idea como 'general' o 'world:{nombre}'. "
        "Devuelve JSON: {\"destino\": \"general\"|\"world\", \"world\": \"...\"}. "
        "Si el autor no especifica destino, usa 'general'."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            f"{endpoint}/chat/completions",
            json=payload,
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        parsed = json.loads(raw)

        # Validate expected keys
        if not isinstance(parsed, dict):
            return None
        destino = parsed.get("destino", "general")
        if destino not in ("general", "world"):
            return None
        result: dict = {"destino": destino}
        if destino == "world":
            result["world"] = parsed.get("world", "")
        return result
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        print("   ⚠ Qwen no disponible para categorización — connection error/timeout", file=sys.stderr)
        return None
    except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError) as exc:
        print(f"   ⚠ Error al categorizar con Qwen: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Visual reference writer
# ---------------------------------------------------------------------------


def write_referencia_visual(slug: str, row: list, col_map: dict,
                            referencias_dir: Path, imagenes_dir: Path,
                            image_rel_path: str,
                            qwen_data: dict | None = None,
                            references: list | None = None,
                            status: str = "synced") -> Path:
    """
    Write mundos/{world}/Referencias/Visuales/{slug}.md with EXACT schema:

    id, slug, timestamp, source, type, tags, status, references, imagen

    Body: Descripción visual, Veredicto, Análisis, Preguntas abiertas.
    """
    referencias_dir.mkdir(parents=True, exist_ok=True)

    idea_id   = _safe_get(row, col_map, "id", str(uuid.uuid4()))
    timestamp = _safe_get(row, col_map, "timestamp")
    source    = _safe_get(row, col_map, "source", "telegram_image")

    # Tags from Qwen
    tags = []
    if qwen_data and qwen_data.get("tags"):
        tags = qwen_data["tags"]
    tags_yaml = "[" + ", ".join(f'"{t}"' for t in tags) + "]" if tags else "[]"

    # References (relative paths to lore/personajes files)
    refs_yaml = ""
    if references:
        refs_list = "\n" + "\n".join(f'  - "{r}"' for r in references)
        refs_yaml = f"references:{refs_list}"

    frontmatter = (
        f"---\n"
        f'id: "{idea_id}"\n'
        f'slug: "{slug}"\n'
        f'timestamp: "{timestamp}"\n'
        f'source: "{source}"\n'
        f'type: "referencia_visual"\n'
        f"tags: {tags_yaml}\n"
        f'status: "{status}"\n'
        f'imagen: "{image_rel_path}"\n'
    )
    if refs_yaml:
        frontmatter += refs_yaml + "\n"
    frontmatter += "---\n"

    # Body
    body_parts = [f"\n# {slug}\n"]

    if qwen_data:
        body_parts.append(f"\n## Descripción visual (Qwen 3.6)\n")
        body_parts.append(qwen_data.get("descripcion", "Sin descripción."))
        body_parts.append(f"\n\n## Veredicto\n")
        body_parts.append(qwen_data.get("veredicto", "no_aplica"))
        body_parts.append(f"\n\n## Análisis\n")
        body_parts.append(qwen_data.get("analisis", "Sin análisis."))
        body_parts.append(f"\n\n## Preguntas abiertas\n")
        body_parts.append("- ¿Cómo se integra esta referencia visual con el lore existente?")
        body_parts.append("- ¿Qué emociones o atmósferas evoca?")
        body_parts.append("- ¿Hay contradicciones con descripciones existentes en el canon?")
    else:
        body_parts.append("\n## Estado\n")
        body_parts.append("Qwen no disponible — el análisis está pendiente para la próxima sincronización.\n")

    body = "".join(body_parts)

    filepath = referencias_dir / f"{slug}.md"
    filepath.write_text(frontmatter + body, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Visual index regeneration
# ---------------------------------------------------------------------------


def regenerate_visual_index(referencias_dir: Path) -> None:
    """
    Scan mundos/{world}/Referencias/Visuales/*.md (skip _indice.md and imagenes/),
    parse frontmatter, group by references path prefix, write _indice.md.
    """
    if not referencias_dir.exists():
        return

    groups = {}  # prefix -> list of (entity_name, slug)

    for fpath in sorted(referencias_dir.glob("*.md")):
        if fpath.name == "_indice.md":
            continue

        content = fpath.read_text(encoding="utf-8")
        # Quick frontmatter parse
        fm = _parse_frontmatter(content)
        if not fm:
            continue

        slug = fm.get("slug", fpath.stem)
        refs = fm.get("references", [])
        if isinstance(refs, str):
            refs = [refs]

        for ref in refs:
            # Determine group from path prefix
            parts = ref.replace("\\", "/").split("/")
            if len(parts) >= 2:
                prefix = parts[0]  # "Personajes", "Lore", etc.
            else:
                prefix = "General"

            # Extract entity name from the ref filename
            entity_name = Path(ref).stem.replace("_", " ").replace("-", " ").title()
            if prefix not in groups:
                groups[prefix] = []
            groups[prefix].append((entity_name, slug))

    # Write index
    if not groups:
        return

    lines = [
        "---",
        'title: "Índice de Referencias Visuales"',
        f'updated: "{datetime.now(timezone.utc).isoformat()}"',
        "---",
        "",
        "# Índice de Referencias Visuales",
        "",
    ]

    sorted_prefixes = sorted(groups.keys())
    for prefix in sorted_prefixes:
        display_name = prefix.replace("_", " ").title() if prefix != "General" else "Generales"
        lines.append(f"\n## {display_name}\n")
        entries = sorted(set(groups[prefix]))
        for entity_name, slug in entries:
            lines.append(f"- **{entity_name}** → [Referencias/Visuales/{slug}.md]({slug}.md)")

    lines.append("")  # trailing newline
    index_path = referencias_dir / "_indice.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"   📇 Índice visual regenerado: {index_path}", file=sys.stderr)


def _parse_frontmatter(content: str) -> dict | None:
    """Quick YAML-like frontmatter parser (no PyYAML dependency). Returns dict or None."""
    content = content.lstrip("\ufeff")  # strip BOM
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    fm_text = content[3:end].strip()
    result = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # Simple list parsing for references
            if val.startswith("["):
                # Inline list: ["a", "b"]
                items = [item.strip().strip('"').strip("'") for item in val.strip("[]").split(",") if item.strip()]
                result[key] = items
            elif val.startswith("-"):
                # Multi-line list (collected above)
                continue
            else:
                result[key] = val
        elif line.startswith("- ") and "references" in result:
            # Multi-line list continuation
            item = line[2:].strip().strip('"').strip("'")
            if isinstance(result.get("references"), list):
                result["references"].append(item)
    return result


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

def generate_slug(timestamp_str: str, content: str, ideas_dir: Path,
                  image_hash: str | None = None) -> str:
    """
    Generate a collision-free slug:

        {YYYY-MM-DD}-{word1-word2-word3-word4}

    Uses the first 4 meaningful words (non-stopword, length > 1) from
    the content. Appends -2, -3, etc. on collision.

    For images with no meaningful content, falls back to SHA256 hex prefix.
    """
    # Date prefix
    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        date_prefix = dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check if content is too short or meaningless (image fallback)
    meaningless_patterns = [
        "[image — pending qwen analysis]",
        "[voice — pending transcription]",
    ]
    is_image_placeholder = any(p in content.lower() for p in meaningless_patterns) or len(content.strip()) < 5

    if is_image_placeholder and image_hash:
        # Use SHA256 hex prefix for image-only slugs
        suffix = image_hash[:8]
        base_slug = f"{date_prefix}-img-{suffix}"
        slug = base_slug
        counter = 2
        while (ideas_dir / f"{slug}.md").exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug

    # Clean and tokenize
    cleaned = content.lower()
    cleaned = re.sub(r"[^\w\s-]", "", cleaned)
    cleaned = re.sub(r"[-_]+", " ", cleaned)
    words = cleaned.split()

    # Filter: skip stop words and single-character tokens
    meaningful = [w for w in words if w not in STOP_WORDS and len(w) > 1]

    slug_words = meaningful[:4] if len(meaningful) >= 2 else words[:4]

    if not slug_words:
        slug_words = [hashlib.md5(content.encode()).hexdigest()[:8]]

    base_slug = f"{date_prefix}-{'-'.join(slug_words)}"
    slug = base_slug
    counter = 2
    while (ideas_dir / f"{slug}.md").exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


# ---------------------------------------------------------------------------
# File writer
# ---------------------------------------------------------------------------

def write_idea_file(slug: str, row: list, col_map: dict, ideas_dir: Path,
                    actual_content: str = None, actual_status: str = None,
                    qwen_data: dict | None = None,
                    image_rel_path: str | None = None) -> Path:
    """
    Write mundos/{world}/Ideas/{slug}.md as YAML frontmatter + markdown body.

    Frontmatter schema (CLOSED — 7 fields ONLY):
        id, slug, timestamp, source, type, tags (YAML list), status

    actual_content: transcribed text for voice rows (overrides row's content)
    actual_status: "synced" for processed rows (overrides row's status)
    qwen_data: optional Qwen vision analysis dict — appends body sections
    image_rel_path: optional relative path for markdown image link
    """
    ideas_dir.mkdir(parents=True, exist_ok=True)

    idea_id    = _safe_get(row, col_map, "id", str(uuid.uuid4()))
    timestamp  = _safe_get(row, col_map, "timestamp")
    source     = _safe_get(row, col_map, "source", "unknown")
    idea_type  = _safe_get(row, col_map, "type", "idea_loose")
    content    = actual_content if actual_content is not None else _safe_get(row, col_map, "content")
    tags_raw   = _safe_get(row, col_map, "tags")
    # Legacy fallback: pre-tags-column rows used link_audio for tags, but NEVER for voice rows
    if not tags_raw and source != "telegram_voice":
        tags_raw = _safe_get(row, col_map, "link_audio")
    status     = actual_status if actual_status is not None else _safe_get(row, col_map, "status", "synced")

    tags_list = [t.strip() for t in tags_raw.split(",") if t.strip()]
    tags_yaml = "[" + ", ".join(f'"{t}"' for t in tags_list) + "]" if tags_list else "[]"

    # Build body
    body = content or ""

    # Append Qwen analysis sections if present (for image rows)
    if qwen_data:
        body += "\n\n## Descripción visual (Qwen 3.6)\n"
        body += qwen_data.get("descripcion", "Sin descripción.")
        body += "\n\n## Veredicto\n"
        body += qwen_data.get("veredicto", "no_aplica")
        body += "\n\n## Análisis\n"
        body += qwen_data.get("analisis", "Sin análisis.")
        if qwen_data.get("veredicto") == "contradice":
            body += "\n\n> ⚠ El análisis de Qwen contradice el texto proporcionado."
        body += "\n\n## Preguntas abiertas\n"
        body += "- ¿Cómo se relaciona esta imagen con el lore existente?\n"
        body += "- ¿Qué emociones o atmósferas evoca?\n"
        body += "- ¿Hay elementos que sugieran direcciones narrativas?\n"
    elif status == "analysis_pending":
        body += "\n\n## Estado\n"
        body += "Qwen no disponible — el análisis visual está pendiente para la próxima sincronización.\n"

    # Append image reference in markdown body (NOT in frontmatter — CLOSED schema)
    if image_rel_path:
        body += f"\n\n![Image]({image_rel_path})\n"

    frontmatter = (
        f"---\n"
        f'id: "{idea_id}"\n'
        f'slug: "{slug}"\n'
        f'timestamp: "{timestamp}"\n'
        f'source: "{source}"\n'
        f'type: "{idea_type}"\n'
        f"tags: {tags_yaml}\n"
        f'status: "{status}"\n'
        f"---\n"
        f"\n"
        f"{body}\n"
    )

    filepath = ideas_dir / f"{slug}.md"
    filepath.write_text(frontmatter, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Engram persistence (best-effort CLI call)
# ---------------------------------------------------------------------------

def try_engram_save(slug: str, content: str, world: str) -> bool:
    """
    Attempt `engram mem save` via subprocess.
    
    Args:
        slug: Idea slug (used as title and topic-key suffix).
        content: Idea content preview (first 200 chars sent to Engram).
        world: Active world name (used as --project for Engram).
    
    Returns True on success, False if CLI unavailable or fails.
    """
    try:
        body = (
            f"**What**: Idea synced from Banco de Ideas\\n"
            f"**Why**: Batch sync from Google Sheets\\n"
            f"**Where**: Ideas/{slug}.md\\n"
            f"**Content preview**: {content[:200]}"
        )
        result = subprocess.run(
            [
                "engram", "mem", "save",
                "--project", world,
                "--topic-key", f"nec/ideas/{slug}",
                "--title", slug,
                "--type", "discovery",
                "--content", body,
                "--capture-prompt", "false",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Banco de Ideas — Sync Tool (Google Sheets → local + Engram)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without writing files or modifying Sheets",
    )
    args = parser.parse_args()

    load_env()

    # Discover active world
    world = discover_world()
    print(f"🌍 Mundo activo: {world}", file=sys.stderr)

    spreadsheet_id = os.environ.get("GOOGLE_SHEETS_ID")
    if not spreadsheet_id:
        print("ERROR: GOOGLE_SHEETS_ID no está configurado en .env", file=sys.stderr)
        sys.exit(1)

    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        print("⚠ TELEGRAM_BOT_TOKEN no está configurado — los audios no se podrán descargar", file=sys.stderr)

    ideas_dir = Path(f"mundos/{world}/Ideas")

    # Connect
    print("Conectando a Google Sheets...", file=sys.stderr)
    sheets, drive = get_clients()

    # Fetch
    print("Leyendo filas no procesadas...", file=sys.stderr)
    unprocessed, _all = get_unprocessed_rows(sheets, spreadsheet_id)

    if not unprocessed:
        print("Banco de Ideas al día — sin novedades.", file=sys.stderr)
        print(json.dumps({"synced": [], "total": 0, "dry_run": args.dry_run}, ensure_ascii=False))
        return

    print(f"{len(unprocessed)} idea(s) pendiente(s) encontrada(s).", file=sys.stderr)

    results = []

    # Scan known entities for image routing (lazy, one-time)
    known_entities = scan_known_entities(
        Path(f"mundos/{world}/Lore"), Path(f"mundos/{world}/Personajes")
    ) if unprocessed else {}

    # Pre-build known hashes for image dedup
    known_hashes = build_known_hashes([
        Path(f"mundos/{world}/Ideas/imagenes"),
        Path(f"mundos/{world}/Referencias/Visuales/imagenes"),
    ])

    for row_number, row, col_map in unprocessed:
        idea_id    = _safe_get(row, col_map, "id")
        source     = _safe_get(row, col_map, "source", "unknown")
        content    = _safe_get(row, col_map, "content")
        file_id    = _safe_get(row, col_map, "link_audio")  # Telegram file_id stored in link_audio column
        link_imagen = _safe_get(row, col_map, "link_imagen")  # Telegram file_id or Drive URL for images
        drive_id   = _safe_get(row, col_map, "drive_link")
        timestamp  = _safe_get(row, col_map, "timestamp")
        short_id   = idea_id[:8] if idea_id else "????"

        tag = "[DRY RUN] " if args.dry_run else ""
        print(f"\n{tag}Fila {row_number} ({short_id}…) — source={source}", file=sys.stderr)

        # --- Voice transcription ---
        # Detect voice: either source=telegram_voice AND file_id exists (Pipedream path),
        # or source=telegram_voice AND drive_link exists (legacy Drive path)
        has_voice_file = bool(file_id.strip()) if file_id else False
        is_voice = has_voice_file or (source == "telegram_voice" and source != "telegram_text" and drive_id)

        # --- Image detection ---
        has_imagen = bool(link_imagen.strip()) if link_imagen else False
        is_image = (source == "telegram_image") or has_imagen

        # --- Processing flags ---
        row_status = "synced"
        qwen_data = None
        image_rel_path = None
        wrote_referencia = False
        imagen_ext = None

        # --- Image processing branch ---
        if is_image and has_imagen:
            print(f"  🖼 Procesando imagen ({link_imagen[:60]}…)", file=sys.stderr)
            try:
                if args.dry_run:
                    print(f"  🔍 Descargaría imagen de Telegram/Drive", file=sys.stderr)
                    print(f"  🔍 Llamaría a Qwen 3.6 vision para análisis", file=sys.stderr)
                    content_for_slug = content or "[Image — pending Qwen analysis]"
                    tmp_hash = "deadbeef"
                else:
                    # Download image — extract file_id from link_imagen if it's a Telegram URL
                    # link_imagen can be: Telegram file_id, Telegram download URL, or Drive URL
                    tmp_img = Path(f"tmp_img_{short_id}")
                    try:
                        if link_imagen.startswith("http"):
                            # Drive URL or Telegram URL — download directly
                            img_resp = requests.get(link_imagen, timeout=120)
                            img_resp.raise_for_status()
                            tmp_img.write_bytes(img_resp.content)
                        else:
                            # Telegram file_id — reuse download pattern
                            download_image_from_telegram(link_imagen, tmp_img)
                    except Exception as exc:
                        err_str = str(exc)
                        if "image_too_large" in err_str:
                            row_status = "image_too_large"
                        elif "format" in err_str.lower() or "unsupported" in err_str.lower():
                            row_status = "format_error"
                        else:
                            row_status = "download_failed"
                        print(f"  ❌ Falló descarga de imagen: {exc}", file=sys.stderr)
                        # Write minimal idea file with error status
                        content_for_write = content or "[Image — download failed]"
                        slug = generate_slug(timestamp, content_for_write, ideas_dir)
                        write_idea_file(slug, row, col_map, ideas_dir,
                                        actual_content=content_for_write,
                                        actual_status=row_status)
                        mark_row_processed(sheets, spreadsheet_id, row_number, row_status)
                        results.append({
                            "id": idea_id, "slug": slug,
                            "filepath": f"mundos/{world}/Ideas/{slug}.md",
                            "source": source,
                            "type": _safe_get(row, col_map, "type", "idea_loose"),
                            "status": row_status,
                            "content_preview": content_for_write[:200],
                            "engram_topic": f"nec/ideas/{slug}",
                        })
                        continue

                    # Detect format
                    img_bytes = tmp_img.read_bytes()
                    imagen_ext = _get_image_format(img_bytes)
                    if not imagen_ext:
                        row_status = "format_error"
                        print(f"  ❌ Formato de imagen no soportado", file=sys.stderr)
                        content_for_write = content or "[Image — unsupported format]"
                        slug = generate_slug(timestamp, content_for_write, ideas_dir)
                        write_idea_file(slug, row, col_map, ideas_dir,
                                        actual_content=content_for_write,
                                        actual_status=row_status)
                        tmp_img.unlink(missing_ok=True)
                        mark_row_processed(sheets, spreadsheet_id, row_number, row_status)
                        results.append({
                            "id": idea_id, "slug": slug,
                            "filepath": f"mundos/{world}/Ideas/{slug}.md",
                            "source": source,
                            "type": _safe_get(row, col_map, "type", "idea_loose"),
                            "status": row_status,
                            "content_preview": content_for_write[:200],
                            "engram_topic": f"nec/ideas/{slug}",
                        })
                        continue

                    # SHA256 dedup
                    img_hash = compute_sha256(img_bytes)
                    if img_hash in known_hashes:
                        print(f"  🔁 Imagen duplicada (SHA256: {img_hash[:12]}…) — saltando", file=sys.stderr)
                        row_status = "duplicate"
                        content_for_write = content or "[Image — duplicate]"
                        slug = generate_slug(timestamp, content_for_write, ideas_dir)
                        mark_row_processed(sheets, spreadsheet_id, row_number, row_status)
                        results.append({
                            "id": idea_id, "slug": slug,
                            "filepath": None,
                            "source": source,
                            "type": _safe_get(row, col_map, "type", "idea_loose"),
                            "status": row_status,
                            "content_preview": content_for_write[:200],
                            "engram_topic": None,
                        })
                        tmp_img.unlink(missing_ok=True)
                        continue
                    known_hashes.add(img_hash)

                    # Call Qwen vision
                    qwen_data = call_qwen_vision(img_bytes, content)
                    if qwen_data is None:
                        row_status = "analysis_pending"
                        print(f"  ⚠ Qwen no disponible — se escribe con analysis_pending", file=sys.stderr)

                    # Determine content for slug
                    content_for_slug = content or "[Image — pending Qwen analysis]"

                    # Entity detection: scan content for known lore entities
                    matched_entity = None
                    matched_ref = None
                    if content and known_entities:
                        content_lower = content.lower()
                        for entity_name, rel_path in known_entities.items():
                            if entity_name.lower() in content_lower and len(entity_name) > 3:
                                matched_entity = entity_name
                                matched_ref = rel_path
                                print(f"   🔍 Entidad detectada: {entity_name} → {rel_path}", file=sys.stderr)
                                break

                    # Decision tree: route to Referencias/Visuales/ or Ideas/
                    veredicto = (qwen_data or {}).get("veredicto", "no_aplica")
                    should_route_to_referencias = (
                        matched_entity
                        and veredicto == "confirma"
                        and qwen_data is not None
                    )

                    # Generate slug with image hash fallback
                    slug = generate_slug(timestamp, content_for_slug, ideas_dir,
                                         image_hash=img_hash)

                    if should_route_to_referencias:
                        # Route to mundos/{world}/Referencias/Visuales/
                        referencias_dir = Path(f"mundos/{world}/Referencias/Visuales")
                        img_dir = Path(f"mundos/{world}/Referencias/Visuales/imagenes")
                        img_dir.mkdir(parents=True, exist_ok=True)
                        img_filename = f"{slug}{imagen_ext}"
                        img_dest = img_dir / img_filename
                        img_rel = f"mundos/{world}/Referencias/Visuales/imagenes/{img_filename}"

                        # Save image file
                        img_dest.write_bytes(img_bytes)
                        print(f"   🖼 Imagen guardada: {img_dest}", file=sys.stderr)

                        filepath = write_referencia_visual(
                            slug, row, col_map, referencias_dir, img_dir,
                            image_rel_path=img_rel,
                            qwen_data=qwen_data,
                            references=[matched_ref] if matched_ref else None,
                            status=row_status,
                        )
                        print(f"  📄 Referencia visual: {filepath}", file=sys.stderr)
                        wrote_referencia = True
                    else:
                        # Route to mundos/{world}/Ideas/
                        img_dir = Path(f"mundos/{world}/Ideas/imagenes")
                        img_dir.mkdir(parents=True, exist_ok=True)
                        img_filename = f"{slug}{imagen_ext}"
                        img_dest = img_dir / img_filename
                        img_rel = f"mundos/{world}/Ideas/imagenes/{img_filename}"

                        # Save image file
                        img_dest.write_bytes(img_bytes)
                        print(f"   🖼 Imagen guardada: {img_dest}", file=sys.stderr)

                        image_rel_path = img_rel

                    # Cleanup temp
                    tmp_img.unlink(missing_ok=True)

                # Determine effective content for file writing
                content_for_write = content_for_slug if args.dry_run else (content or "[Image — pending Qwen analysis]")

                if not args.dry_run and not wrote_referencia:
                    filepath = write_idea_file(
                        slug, row, col_map, ideas_dir,
                        actual_content=content_for_write,
                        actual_status=row_status,
                        qwen_data=qwen_data,
                        image_rel_path=image_rel_path,
                    )
                    print(f"  📄 {filepath}", file=sys.stderr)

                    mark_row_processed(sheets, spreadsheet_id, row_number, row_status)
                    print(f"  ✅ Sheets: fila {row_number} → processed=TRUE, status={row_status}", file=sys.stderr)

                    engram_ok = try_engram_save(slug, content_for_write, world)
                    if engram_ok:
                        print(f"  🧠 Engram: nec/ideas/{slug}", file=sys.stderr)
                    else:
                        print(f"  ⚠ Engram CLI no disponible — el agente debe persistir manualmente", file=sys.stderr)
                elif not args.dry_run and wrote_referencia:
                    # Referencias/Visuales/ already written; just mark sheet and optionally save to Engram
                    mark_row_processed(sheets, spreadsheet_id, row_number, row_status)
                    print(f"  ✅ Sheets: fila {row_number} → processed=TRUE, status={row_status}", file=sys.stderr)
                else:
                    print(f"  🔍 Escribiría → {'Referencias/Visuales' if should_route_to_referencias else 'Ideas'}/{slug}.md", file=sys.stderr)
                    print(f"  🔍 Sheets → fila {row_number} processed=TRUE status={row_status}", file=sys.stderr)

                filepath_result = f"mundos/{world}/{'Referencias/Visuales' if wrote_referencia else 'Ideas'}/{slug}.md"
                results.append({
                    "id": idea_id,
                    "slug": slug,
                    "filepath": filepath_result,
                    "source": source,
                    "type": "referencia_visual" if wrote_referencia else _safe_get(row, col_map, "type", "idea_loose"),
                    "status": row_status,
                    "content_preview": (qwen_data or {}).get("descripcion", content_for_write)[:200],
                    "engram_topic": f"nec/ideas/{slug}",
                })
                continue  # Image row done — skip voice/text processing below

            except Exception as exc:
                print(f"  ❌ Error inesperado procesando imagen: {exc}", file=sys.stderr)
                row_status = "download_failed"
                # Fall through to regular text processing as a text idea

        # --- Voice transcription (unchanged) ---
        if is_voice:
            source_id = file_id or drive_id
            print(f"  🎤 Descargando audio ({'Telegram' if file_id else 'Drive'}: {source_id})...", file=sys.stderr)
            try:
                if not args.dry_run:
                    tmp = Path(f"tmp_voice_{short_id}.ogg")
                    if file_id:
                        download_from_telegram(file_id, tmp)
                    else:
                        download_from_drive(drive, drive_id, tmp)
                    content = transcribe_audio(tmp)
                    tmp.unlink(missing_ok=True)
                else:
                    content = "[DRY RUN — se descargaría y transcribiría el audio]"
                print(f"  ✅ Transcripción: {content[:100]}{'…' if len(content) > 100 else ''}", file=sys.stderr)
                row_status = "synced"
            except Exception as exc:
                print(f"  ❌ Falló transcripción: {exc}", file=sys.stderr)
                row_status = "transcription_failed"
        # else: row_status already "synced" for text rows

        # --- Slug (text/voice only — images already handled above) ---
        if not is_image:
            # Categorize destination via LLM
            categoria = call_qwen_categorize(content)
            if categoria is None:
                dest_dir = Path("mundos/Ideas")
                print("   ⚠ LLM no disponible, usando Ideas compartidas", file=sys.stderr)
            elif categoria.get("destino") == "general":
                dest_dir = Path("mundos/Ideas")
            elif categoria.get("destino") == "world":
                w = (categoria.get("world") or "").strip()
                if w and Path(f"mundos/{w}").exists():
                    dest_dir = Path(f"mundos/{w}/Ideas")
                else:
                    print(f"   ⚠ mundo '{w}' no encontrado, usando Ideas compartidas", file=sys.stderr)
                    dest_dir = Path("mundos/Ideas")
            else:
                dest_dir = Path("mundos/Ideas")

            dest_dir.mkdir(parents=True, exist_ok=True)

            slug = generate_slug(timestamp, content, dest_dir)
            print(f"  📝 slug: {slug}", file=sys.stderr)

            # --- Write file + mark processed ---
            if not args.dry_run:
                filepath = write_idea_file(slug, row, col_map, dest_dir,
                                           actual_content=content, actual_status=row_status)
                print(f"  📄 {filepath}", file=sys.stderr)

                mark_row_processed(sheets, spreadsheet_id, row_number, row_status)
                print(f"  ✅ Sheets: fila {row_number} → processed=TRUE, status={row_status}", file=sys.stderr)

                engram_ok = try_engram_save(slug, content, world)
                if engram_ok:
                    print(f"  🧠 Engram: nec/ideas/{slug}", file=sys.stderr)
                else:
                    print(f"  ⚠ Engram CLI no disponible — el agente debe persistir manualmente", file=sys.stderr)
            else:
                dest_dir_display = str(dest_dir).replace("\\", "/")
                print(f"  🔍 Escribiría → {dest_dir_display}/{slug}.md", file=sys.stderr)
                print(f"  🔍 Sheets → fila {row_number} processed=TRUE status={row_status}", file=sys.stderr)
                print(f"  🔍 Engram → nec/ideas/{slug}", file=sys.stderr)

            filepath = str(dest_dir / f"{slug}.md").replace("\\", "/")
            results.append({
                "id": idea_id,
                "slug": slug,
                "filepath": filepath,
                "source": source,
                "type": _safe_get(row, col_map, "type", "idea_loose"),
                "status": row_status,
                "content_preview": content[:200] if content else "",
                "engram_topic": f"nec/ideas/{slug}",
            })

    # --- Regenerate visual index after all rows processed ---
    if not args.dry_run:
        try:
            regenerate_visual_index(Path(f"mundos/{world}/Referencias/Visuales"))
        except Exception as exc:
            print(f"  ⚠ Error al regenerar índice visual: {exc}", file=sys.stderr)

    # --- Summary JSON → stdout (for agent consumption) ---
    print(f"\n{'=' * 50}", file=sys.stderr)
    tag = "[DRY RUN] " if args.dry_run else ""
    print(f"{tag}Sincronización completa: {len(results)} idea(s)", file=sys.stderr)
    for r in results:
        icon = "✅" if r["status"] == "synced" else "❌"
        print(f"  {icon} {r['slug']}  ({r['source']})", file=sys.stderr)

    print(json.dumps(
        {"synced": results, "total": len(results), "dry_run": args.dry_run},
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
