"""Hermes-native idea capture handler.

This module consumes Hermes' normalized ``MessageEvent`` and media-cache paths.
It deliberately has no Telegram SDK, Bot API, token, or polling dependency.

Intake happens through ``IdeaCaptureHandler._update_from_event_with_voice_probe``
called by the project plugin's ``pre_gateway_dispatch`` hook. The legacy
``handle_message`` / ``handle_interaction`` methods (which called the fictional
``send_interaction_message`` / ``interaction.answer|send|edit`` APIs that do not
exist in Hermes v0.20) were retired; callback confirm/deny now lives in the
``CaptureTelegramAdapter`` subclass.
"""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import os
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .config import CaptureConfig, image_vision_enabled, load_active_world, load_policy
from .enrich import DEFAULT_TYPE, MediaEnrichProvider, TYPE_TAXONOMY
from .models import MediaInput, MediaKind, TelegramUpdate
from .runtime import IdeaCaptureRuntime

log = logging.getLogger(__name__)


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def read_hermes_media_cache(path: str) -> bytes:
    """Read only files from Hermes-managed media cache roots."""
    candidate = Path(path).expanduser().resolve(strict=True)
    home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser().resolve()
    roots = [
        home / "cache",
        home / "image_cache",
        home / "audio_cache",
        home / "video_cache",
        home / "document_cache",
    ]
    if not any(_within(candidate, root.resolve()) for root in roots):
        raise ValueError("media path is outside Hermes cache")
    if not candidate.is_file():
        raise ValueError("media path is not a regular file")
    return candidate.read_bytes()


def _hermes_agent_root() -> Path:
    """Resolve the Hermes agent source root (parent of the ``plugins`` package).

    Mirrors ``capture_adapter.hermes_agent_root()``: an explicit
    ``HERMES_AGENT_ROOT`` override wins, then ``HERMES_HOME`` (default
    ``~/.hermes``) + ``hermes-agent``. Inside a running gateway the agent root
    is already importable, so this is only a fallback for standalone/test
    processes.
    """
    override = os.environ.get("HERMES_AGENT_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
    return (home / "hermes-agent").resolve()


def _probe_voice_duration(path: str) -> float | None:
    """Best-effort voice duration via the bundled Hermes probe (fail closed).

    Reuses the TelegramAdapter's module-level ``_probe_voice_duration_seconds``
    (mutagen -> ffprobe, adapter.py:335) instead of duplicating that logic.
    Capability-checked: a Hermes upgrade that renames or breaks the helper
    yields ``None`` here, so the voice note is rejected by ``validate_media``
    (S-10.5) instead of crashing dispatch. Never raises.
    """
    try:
        from plugins.platforms.telegram.adapter import _probe_voice_duration_seconds
    except ImportError:
        root = _hermes_agent_root()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from plugins.platforms.telegram.adapter import _probe_voice_duration_seconds
        except Exception:
            return None
    try:
        duration = _probe_voice_duration_seconds(path)
    except Exception:
        return None
    return None if duration is None else float(duration)


# ---------------------------------------------------------------------------
# Media enrichment builders (PR idea-capture-ai-gate Phase 3, R-5)
# ---------------------------------------------------------------------------


def build_single_image_vision(
    settings_path: str | Path | None = None,
    generate_thumbnail: Callable[[bytes, int], bytes] | None = None,
    cache_lookup: Callable[[str], Any] | None = None,
    cache_store: Callable[[str, Any], None] | None = None,
) -> Callable[[bytes, str], dict | None] | None:
    """Wrap ``import_vision.build_vision_callable`` for ONE image (fail-open).

    ``build_vision_callable`` is BATCH: it analyzes ``ImageEntry`` values.
    This adapter builds a single entry from the raw image bytes, injects the
    thumbnail generator and the sha256 content cache, and returns
    ``results[0]`` translated to the provider payload contract
    ``{descripcion, veredicto, analisis, tags}``.

    Returns ``None`` when the assistant settings are missing/text-only/invalid
    or the vision modules are not importable in the caller's process; returns
    ``None`` per call when the model yields no result (e.g. no thumbnail
    generator). Vision never crashes the capture. The callable runs
    ``asyncio.run`` internally, so it must only be invoked off the event-loop
    thread — the ``CaptureWorker`` thread is safe.
    """
    try:
        from import_vision import build_vision_callable
        from sync_lore.schemas import ImageEntry
    except Exception as exc:  # noqa: BLE001 — fail-open: vision is advisory
        log.warning("idea-capture vision imports unavailable: %s", exc)
        return None
    analyze_images = build_vision_callable(
        settings_path=settings_path,
        generate_thumbnail=generate_thumbnail,
        vision_cache_lookup=cache_lookup,
        vision_cache_store=cache_store,
    )
    if analyze_images is None:
        return None

    def analyze_one(image_bytes: bytes, context: str = "") -> dict | None:
        if not image_bytes:
            return None
        try:
            entry = ImageEntry(
                id=str(uuid.uuid4()),
                source_file="idea-capture",
                filename="idea-capture-image",
                context_text=context or "",
                image_bytes=image_bytes,
            )
            results = analyze_images([entry], context or "")
        except Exception as exc:  # noqa: BLE001 — fail-open per image
            log.warning("idea-capture vision analysis failed; failing open: %s", exc)
            return None
        if not results:
            return None
        result = results[0]
        return {
            "descripcion": result.description,
            "veredicto": result.verdict,
            "analisis": result.analysis,
            "tags": list(result.tags),
        }

    return analyze_one


def _ensure_wiki_on_path() -> None:
    """Make ``src/tools/demiurgos-suite/wiki`` importable for vision/locale helpers.

    The plugin process adds ``src/tools`` to ``sys.path``, but the wiki
    package (``import_vision``, ``demiurgos_language``, ``local_state``)
    lives one level deeper and is not importable from that entry alone.
    Inserting it from the module's own location keeps the helper
    self-contained: ``idea_capture/ -> tools/ -> src/ -> repo root``.
    """
    wiki = (Path(__file__).resolve().parents[3]
            / "src" / "tools" / "demiurgos-suite" / "wiki")
    if str(wiki) not in sys.path:
        sys.path.insert(0, str(wiki))


def _hermes_home() -> Path:
    """Hermes install root: ``$HERMES_HOME`` or ``~/.hermes``."""
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")
                ).expanduser().resolve()


def load_transcription_tools(
    module_path: str | Path | None = None,
) -> Callable[[str, str | None], dict] | None:
    """Load Hermes' ``transcribe_audio`` robustly; ``None`` when unavailable.

    The repo ships its own top-level ``tools`` package (``src/tools``), which
    collides with Hermes' top-level ``tools`` package on ``sys.path``. Loading
    the module by explicit file path via ``importlib`` avoids the collision:
    the module is registered under a private name, Hermes' install root is
    placed ahead of the repo entries only while it executes (so its internal
    ``tools.*``/``utils``/``hermes_cli`` imports resolve to the Hermes
    install), and every name the exec introduces is removed afterwards.

    Returns the ``transcribe_audio`` callable, or ``None`` when the module is
    missing or cannot be loaded in the caller's process — the provider then
    fails open to ``sin_clasificar``. Import succeeds in the Hermes gateway
    (plugin) process and fails gracefully anywhere else.
    """
    if module_path is None:
        module_path = _hermes_home() / "hermes-agent" / "tools" / "transcription_tools.py"
    path = Path(module_path).expanduser()
    if not path.is_file():
        log.warning("hermes transcription_tools not found at %s; audio fails open", path)
        return None
    hermes_root = path.parents[1]  # tools/ -> hermes-agent/ (parent of tools/)
    name = "demiurgos_transcription_tools"
    before = set(sys.modules)
    inserted = False
    root_str = str(hermes_root)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            log.warning("hermes transcription_tools %s has no loader; audio fails open", path)
            return None
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
            inserted = True
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — fail-open: transcription is advisory
        log.warning("failed to load hermes transcription_tools: %s", exc)
        return None
    finally:
        if inserted and root_str in sys.path:
            sys.path.remove(root_str)
        # Do not leave the Hermes exec's names behind in a repo process; the
        # returned callable keeps its own module alive via its globals.
        for key in list(sys.modules):
            if key not in before and key != name:
                sys.modules.pop(key, None)
        sys.modules.pop(name, None)
    transcribe = getattr(module, "transcribe_audio", None)
    if not callable(transcribe):
        log.warning("hermes transcription_tools has no transcribe_audio; audio fails open")
        return None
    return transcribe


def build_audio_transcriber(
    module_path: str | Path | None = None,
) -> Callable[[str, str], str] | None:
    """Wrap Hermes ``transcribe_audio`` for idea capture (path -> transcript).

    Returns a callable ``(media_path, language) -> transcript`` that resolves
    the STT language through ``HERMES_LOCAL_STT_LANGUAGE`` (read at call time
    by Hermes' ``_resolve_stt_language`` — ``transcribe_audio`` has no
    ``language`` parameter), calls ``transcribe_audio``, and extracts
    ``transcript`` from its ``{success, transcript, provider, error}`` dict.
    A failed or empty transcription returns ``""`` (the provider fails open).

    Returns ``None`` when the Hermes module cannot be loaded in the caller's
    process — the provider then fails open to ``sin_clasificar``.
    """
    transcribe = load_transcription_tools(module_path)
    if transcribe is None:
        return None

    def transcribe_one(media_path: str, language: str) -> str:
        previous = os.environ.get("HERMES_LOCAL_STT_LANGUAGE")
        if language:
            os.environ["HERMES_LOCAL_STT_LANGUAGE"] = language
        try:
            result = transcribe(media_path)
        finally:
            if previous is None:
                os.environ.pop("HERMES_LOCAL_STT_LANGUAGE", None)
            else:
                os.environ["HERMES_LOCAL_STT_LANGUAGE"] = previous
        if not isinstance(result, dict):
            log.warning("hermes transcribe_audio returned %s; failing open",
                        type(result).__name__)
            return ""
        if not result.get("success"):
            log.warning("hermes transcription failed: %s",
                        result.get("error") or "unknown error")
            return ""
        transcript = result.get("transcript")
        return transcript if isinstance(transcript, str) else ""

    return transcribe_one


def _default_locale_state_path() -> Path:
    """Project local-state registry: ``$DEMIURGOS_ROOT/data/local-state.json``.

    The plugin resolves its repo root from ``DEMIURGOS_ROOT``; honoring it
    here keeps the locale source consistent with the production root while
    falling back to the module-derived repo root for direct callers.
    """
    env_root = os.environ.get("DEMIURGOS_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve() / "data" / "local-state.json"
    return Path(__file__).resolve().parents[3] / "data" / "local-state.json"


def build_language_resolver(
    locale_state_path: str | Path | None = None,
) -> Callable[[], str]:
    """Resolve the STT language from ``LocaleSettings.conversation``.

    The locale is read at CALL time from the project local-state registry
    (never cached at startup) and any unreadable/invalid locale fails closed
    to ``es`` (R-ME-03). Returns ``es`` or ``en``.
    """
    _ensure_wiki_on_path()

    def resolve() -> str:
        try:
            from demiurgos_language import LocaleSettings
            from local_state import LocalState
        except Exception as exc:  # noqa: BLE001 — fail-closed: locale is advisory
            log.warning("locale modules unavailable; failing closed to es: %s", exc)
            return "es"
        try:
            path = (Path(locale_state_path) if locale_state_path is not None
                    else _default_locale_state_path())
            raw = LocalState(path).snapshot().get("locale")
            settings = (LocaleSettings.from_dict(raw) if isinstance(raw, dict)
                        else LocaleSettings())
        except Exception as exc:  # noqa: BLE001 — fail-closed: locale is advisory
            log.warning("locale unreadable; failing closed to es: %s", exc)
            return "es"
        return settings.conversation if settings.conversation in ("es", "en") else "es"

    return resolve


def _default_vision_cache_db_path() -> Path:
    """Shared SHA-256 vision cache database: ``$DEMIURGOS_ROOT/data/import-jobs.sqlite3``.

    The wiki import router backs its vision content cache with the SAME file
    (``api_server._import_store``), so an image analyzed once — by an import
    or by idea capture — is never analyzed twice. ``DEMIURGOS_ROOT`` keeps
    the cache consistent with the production root, falling back to the
    module-derived repo root for direct callers.
    """
    env_root = os.environ.get("DEMIURGOS_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve() / "data" / "import-jobs.sqlite3"
    return Path(__file__).resolve().parents[3] / "data" / "import-jobs.sqlite3"


def _build_thumbnail_generator() -> Callable[[bytes, int], bytes] | None:
    """Return a PIL 300px JPEG thumbnailer; ``None`` when PIL is unavailable.

    Mirrors the proven ``api_server.generate_thumbnail`` (300px default,
    RGBA/P converted to RGB, LANCZOS resize, JPEG output) so the vision
    provider receives the same payload shape as the wiki import path. PIL is
    a wiki dependency; when it is absent the thumbnailer stays ``None`` and
    image vision fails open to ``sin_clasificar`` (raw retained).
    """
    try:
        from PIL import Image  # noqa: PLC0415 — lazy: PIL is a wiki dep
    except Exception as exc:  # noqa: BLE001 — fail-open: vision is advisory
        log.warning("PIL unavailable; image vision fails open: %s", exc)
        return None

    def generate_thumbnail(image_bytes: bytes, width: int = 300) -> bytes:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        ratio = width / img.width
        height = int(img.height * ratio)
        img = img.resize((width, height), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        return buf.getvalue()

    return generate_thumbnail


def _resolve_vision_dependencies(
    *,
    settings_path: str | Path | None,
    generate_thumbnail: Callable[[bytes, int], bytes] | None,
    cache_lookup: Callable[[str], Any] | None,
    cache_store: Callable[[str, Any], None] | None,
    cache_db_path: str | Path | None,
) -> tuple[
    str | Path | None,
    Callable[[bytes, int], bytes] | None,
    Callable[[str], Any] | None,
    Callable[[str, Any], None] | None,
]:
    """Resolve the production vision components; ``None`` per component on failure.

    Mirrors the proven ``api_server._make_vision_callable`` wiring: the
    active Hermes profile's ``config.yaml`` becomes the vision settings
    path, the PIL thumbnailer produces the 300px JPEG the provider analyzes,
    and the wiki ``ImportJobStore`` provides the shared SHA-256 vision
    content cache. Any component that cannot be resolved stays ``None`` so
    the caller skips the vision callable and the IMAGE path fails open to
    ``sin_clasificar`` (raw retained) — vision never crashes the capture.
    """
    if settings_path is None:
        try:
            from assistant_settings import _resolve_profile_paths
            settings_path = _resolve_profile_paths().config
        except Exception as exc:  # noqa: BLE001 — fail-open gate
            log.warning("idea-capture vision profile unavailable; failing open: %s", exc)
    if generate_thumbnail is None:
        generate_thumbnail = _build_thumbnail_generator()
    if cache_lookup is None or cache_store is None:
        try:
            from import_store import ImportJobStore
            db_path = (Path(cache_db_path).expanduser().resolve()
                       if cache_db_path is not None else _default_vision_cache_db_path())
            store = ImportJobStore(db_path)
            if cache_lookup is None:
                cache_lookup = store.vision_cache_lookup
            if cache_store is None:
                cache_store = store.vision_cache_store
        except Exception as exc:  # noqa: BLE001 — cache is advisory, never fatal
            log.warning("idea-capture vision cache unavailable; failing open: %s", exc)
    return settings_path, generate_thumbnail, cache_lookup, cache_store


# ---------------------------------------------------------------------------
# Hermes gateway idea classifier (TEXT/AUDIO taxonomy labeling)
# ---------------------------------------------------------------------------

CLASSIFY_PROMPT = (
    "Clasifica la idea del usuario en EXACTAMENTE UNA de estas categorías: "
    "personaje, relacion, ambientacion, trama, concepto, sin_clasificar. "
    "Responde únicamente con un objeto JSON con cuatro campos: \"label\" (la "
    "etiqueta elegida, sin puntuación), \"title\" (un título corto de la "
    "idea, máximo 5 palabras, en el idioma de la idea), \"body\" (el cuerpo "
    "de la idea con estructura markdown: \"## Descripción\" con el contenido "
    "principal y \"## Detalles\" con 2-5 viñetas \"- \" con los puntos "
    "clave) y \"details\" (la misma lista de viñetas de \"## Detalles\" como "
    "array de strings). Si hay algo que señalar (p. ej. \"a desarrollar\", "
    "\"pendiente de clasificar\"), añade una sección opcional \"## Notas\". "
    "Sin explicación fuera del JSON."
)


def _project_root() -> Path:
    """Repo root: ``$DEMIURGOS_ROOT`` when set, else the module-derived root."""
    env_root = os.environ.get("DEMIURGOS_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def _project_env(name: str) -> str:
    """Read a value from the project .env (gitignored); ``""`` when absent.

    Mirrors ``api_server._load_project_env``: secrets never live in code,
    and the gateway key may be configured in the project ``.env`` instead of
    the environment.
    """
    env_file = _project_root() / ".env"
    if not env_file.is_file():
        return ""
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _gateway_config() -> tuple[str, str, float]:
    """Resolve the Hermes gateway config at CALL time (env, then project .env).

    Reading at call time (never at build) keeps provider construction
    offline and honors runtime config changes per classification.
    """
    url = os.getenv(
        "HERMES_GATEWAY_URL", "http://127.0.0.1:8642/v1/chat/completions",
    ).strip()
    key = os.getenv("HERMES_GATEWAY_KEY", "").strip() or _project_env("HERMES_GATEWAY_KEY")
    try:
        timeout = float(os.getenv("HERMES_GATEWAY_TIMEOUT", "10"))
    except ValueError:
        timeout = 10.0
    return url, key, timeout


def _gateway_post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    """POST JSON to the gateway; return the parsed dict or raise.

    ``httpx`` is imported lazily so an unavailable client degrades to
    fail-open (the classifier never raises out of its callable). The call is
    synchronous and timeout-bounded; it runs on the ``CaptureWorker`` thread,
    never the event loop.
    """
    try:
        import httpx  # noqa: PLC0415 — lazy: gateway client is optional
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("httpx unavailable for the hermes classifier") from exc
    response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("hermes gateway returned a non-object response")
    return data


def _classify_via_gateway(raw: object) -> str:
    """POST the raw text to the gateway; return the raw label or raise.

    Never called at build time — the classifier reads the gateway config at
    call time. Raises on unconfigured gateway, transport errors, timeouts,
    or malformed responses; ``build_hermes_classifier`` fails open to
    ``sin_clasificar``.
    """
    url, key, timeout = _gateway_config()
    if not url or not key:
        raise RuntimeError("hermes gateway not configured "
                           "(HERMES_GATEWAY_URL / HERMES_GATEWAY_KEY)")
    data = _gateway_post(
        url,
        {
            "model": "hermes-agent",
            "messages": [
                {"role": "system", "content": CLASSIFY_PROMPT},
                {"role": "user", "content": str(raw)},
            ],
        },
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout,
    )
    return data["choices"][0]["message"]["content"]


def _normalize_classified_label(content: object) -> str:
    """Map a raw gateway label into the taxonomy; unrecognized/empty -> sin_clasificar."""
    if not isinstance(content, str):
        return DEFAULT_TYPE
    label = content.strip().lower()
    return label if label in TYPE_TAXONOMY else DEFAULT_TYPE


def _parse_classification(content: object) -> tuple[str, str, str, list[str]]:
    """Parse the gateway JSON ``{"label", "title", "body", "details"}`` into a
    ``(taxonomy label, title, structured body, details)`` tuple.

    Non-JSON, non-dict, or empty responses fail open: label ->
    ``sin_clasificar``, title/body -> ``""``, details -> ``[]``. The taxonomy
    label keeps its exact prior semantics through
    ``_normalize_classified_label``; the title/body/details are additive — a
    valid JSON payload keeps them even when the label is unrecognized (the
    processor still shows the idea under a fallback).
    """
    label, title, body = DEFAULT_TYPE, "", ""
    details: list[str] = []
    if isinstance(content, str) and content.strip():
        try:
            data = json.loads(content.strip())
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            label = _normalize_classified_label(data.get("label"))
            raw_title = data.get("title")
            if isinstance(raw_title, str):
                title = raw_title.strip()
            raw_body = data.get("body")
            if isinstance(raw_body, str):
                body = raw_body.strip()
            raw_details = data.get("details")
            if isinstance(raw_details, list):
                details = [d.strip() for d in raw_details
                           if isinstance(d, str) and d.strip()]
    return label, title, body, details


def build_hermes_classifier() -> Callable[[object], tuple[str, str, str, list[str]]]:
    """Build a Hermes-gateway idea classifier; fail-open NO-OP when unavailable.

    The returned callable labels a raw text/transcript with exactly one
    ``TYPE_TAXONOMY`` type, derives a short human-readable title from the
    same Hermes call, AND produces the idea's structured markdown body
    (``## Descripción`` + ``## Detalles``) — it returns a
    ``(label, title, body, details)`` tuple. The gateway chat-completions
    endpoint is asked for a single JSON object ``{"label", "title", "body",
    "details"}`` (the same pattern ``api_server`` uses). Building the
    classifier is cheap and offline: the closure reads ``HERMES_GATEWAY_URL``
    / ``HERMES_GATEWAY_KEY`` (env, then project ``.env``) at CALL time, so
    runtime config is honored and provider construction never touches the
    network. When the gateway is unconfigured, unreachable, times out,
    returns an unrecognized label, or returns non-JSON, the callable returns
    ``(sin_clasificar, "", "", [])`` and never raises — the enrich provider
    stays fail-open and structures the raw text locally. Runs synchronously
    on the ``CaptureWorker`` thread (enrichment is already off the event
    loop).
    """

    def classify(raw: object) -> tuple[str, str, str, list[str]]:
        try:
            content = _classify_via_gateway(raw)
        except Exception as exc:  # noqa: BLE001 — fail-open: classification is advisory
            log.warning("hermes classification failed; failing open to %s: %s",
                        DEFAULT_TYPE, exc)
            return DEFAULT_TYPE, "", "", []
        return _parse_classification(content)

    return classify


def build_media_enrich_provider(
    *,
    hermes: Callable[[object], str] | None = None,
    settings_path: str | Path | None = None,
    generate_thumbnail: Callable[[bytes, int], bytes] | None = None,
    cache_lookup: Callable[[str], Any] | None = None,
    cache_store: Callable[[str, Any], None] | None = None,
    vision_enabled: bool | None = None,
    transcribe_module_path: str | Path | None = None,
    transcribe_fn: Callable[[str, str], str] | None = None,
    language_resolver: Callable[[], str] | None = None,
    locale_state_path: str | Path | None = None,
    vision_cache_db_path: str | Path | None = None,
    timeout_seconds: float = 30.0,
) -> MediaEnrichProvider:
    """Compose the full media-aware enrich provider for idea capture.

    Wires the single-image vision wrapper (gated by
    ``DEMIURGOS_IDEA_CAPTURE_IMAGE_VISION``), the Hermes ``transcribe_audio``
    wrapper, and the locale-driven language resolver into
    ``MediaEnrichProvider``. When the vision flag is off (opt-out) no vision
    callable is built and image messages fail open to ``sin_clasificar`` with
    the raw bytes retained. When the Hermes transcription module cannot be
    loaded in the caller's process, ``transcribe_fn`` stays ``None`` and
    voice messages fail open the same way. AUDIO is implicitly enabled when
    the dependencies are present — there is no separate env flag.

    Production classifier wiring (R-ME-02): when the caller injects no
    ``hermes`` callable, a REAL gateway classifier is built
    (``build_hermes_classifier``) so TEXT messages and AUDIO transcripts are
    labeled with real taxonomy types. It reads the Hermes gateway config at
    call time and fails open to ``sin_clasificar`` when the gateway is
    unconfigured or unreachable — capture is never blocked by classification.

    Production vision wiring (R-ME-01): when the caller injects nothing, the
    REAL components are resolved — the active Hermes profile's
    ``config.yaml`` as the vision settings path, the PIL 300px thumbnailer,
    and the shared wiki ``ImportJobStore`` SHA-256 cache — matching the
    proven ``api_server._make_vision_callable`` pattern. Every resolution is
    fail-open: an unresolvable profile, PIL, or cache database leaves the
    vision callable unbuilt and the IMAGE path degrades to
    ``sin_clasificar`` with the raw bytes retained.
    """
    _ensure_wiki_on_path()
    if hermes is None:
        hermes = build_hermes_classifier()
    if vision_enabled is None:
        vision_enabled = image_vision_enabled()
    vision_fn = None
    if vision_enabled:
        (settings_path, generate_thumbnail, cache_lookup, cache_store) = (
            _resolve_vision_dependencies(
                settings_path=settings_path,
                generate_thumbnail=generate_thumbnail,
                cache_lookup=cache_lookup,
                cache_store=cache_store,
                cache_db_path=vision_cache_db_path,
            )
        )
        if generate_thumbnail is None:
            log.warning("no thumbnail generator resolved; image vision fails open")
        else:
            vision_fn = build_single_image_vision(
                settings_path=settings_path,
                generate_thumbnail=generate_thumbnail,
                cache_lookup=cache_lookup,
                cache_store=cache_store,
            )
    if transcribe_fn is None:
        transcribe_fn = build_audio_transcriber(transcribe_module_path)
    if language_resolver is None:
        language_resolver = build_language_resolver(locale_state_path)
    return MediaEnrichProvider(
        hermes=hermes,
        vision_fn=vision_fn,
        transcribe_fn=transcribe_fn,
        language_resolver=language_resolver,
        vision_enabled=vision_enabled,
        timeout_seconds=timeout_seconds,
    )


class IdeaCaptureHandler:
    """Authorized Hermes handler for one deterministic native capture owner."""

    def __init__(
        self,
        *,
        repo_root: str | Path,
        config_path: str | Path | None = None,
        state_path: str | Path | None = None,
        mundos_root: str | Path | None = None,
        active_world: str = "",
        media_reader: Callable[[str], bytes] = read_hermes_media_cache,
        runtime: IdeaCaptureRuntime | None = None,
        enrich: Callable[..., tuple[str, str]] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.config_path = Path(config_path or self.repo_root / "config" / "idea-capture.yaml")
        self.mundos_root = Path(mundos_root or self.repo_root / "mundos")
        self.media_reader = media_reader
        loaded = load_policy(self.config_path)
        # Native ingress never falls back to the old chat-only policy.  The
        # compatibility poller may continue using that policy until retirement.
        native_policy = replace(loaded.policy, require_binding=True)
        native_config = CaptureConfig(native_policy, loaded.limits)
        world = active_world.strip() or load_active_world(
            self.config_path,
            os.environ.get("DEMIURGOS_WORLD", ""),
        )
        self.runtime = runtime or IdeaCaptureRuntime(
            config=native_config,
            state_path=state_path or self.repo_root / "data" / "idea-capture.sqlite3",
            mundos_root=self.mundos_root,
            active_world=world,
            global_ideas_root=self.repo_root / "ideas",
            enrich=enrich,
        )
        effective_policy = runtime.config.policy if runtime is not None else native_policy
        # Capture always lands in the global Taller de Ideas, so no world is
        # required to enable the handler: authorized bindings are enough.
        self.enabled = bool(effective_policy.authorized_bindings)

    @property
    def policy(self):
        return self.runtime.config.policy

    def _binding_key(self, source) -> str:
        platform = str(getattr(getattr(source, "platform", None), "value", ""))
        return ":".join((
            platform,
            str(getattr(source, "chat_id", "")),
            str(getattr(source, "user_id", "")),
            str(getattr(source, "profile", None) or "default"),
        ))

    def _binding_allowed(self, source) -> bool:
        return self._binding_key(source) in self.policy.authorized_bindings

    def _update_from_event(self, event) -> TelegramUpdate:
        source = event.source
        try:
            update_id = int(event.platform_update_id)
            chat_id = int(source.chat_id)
            sender_id = int(source.user_id)
        except (TypeError, ValueError):
            raise ValueError("Hermes event has no valid Telegram identity")

        text = getattr(event, "text", "") or ""
        paths = list(getattr(event, "media_urls", None) or [])
        if not paths:
            if not text:
                raise ValueError("Hermes event has no capturable text or media")
            media = MediaInput(MediaKind.TEXT, text=text)
        else:
            types = list(getattr(event, "media_types", None) or [])
            path = str(paths[0])
            mime = str(types[0]) if types else ""
            data = self.media_reader(path)
            message_type = getattr(getattr(event, "message_type", None), "value", "")
            if mime.startswith("image/") or message_type in {"photo", "image"}:
                media = MediaInput(
                    MediaKind.IMAGE, data=data, mime=mime or "image/jpeg",
                    text=text, path=path,
                )
            elif mime.startswith("audio/") or message_type in {"voice", "audio"}:
                durations = getattr(event, "media_durations", None) or []
                duration = durations[0] if durations else None
                media = MediaInput(
                    MediaKind.VOICE, data=data, mime=mime or "audio/ogg",
                    duration_seconds=duration, text=text, path=path,
                )
            else:
                raise ValueError("Hermes media type is not capturable")
        return TelegramUpdate(
            update_id, chat_id, sender_id,
            str(getattr(source, "chat_type", "")) in {"group", "forum"},
            media,
            platform=str(getattr(getattr(source, "platform", None), "value", "telegram")),
            profile=str(getattr(source, "profile", None) or "default"),
        )

    def _update_from_event_with_voice_probe(self, event, gateway=None) -> TelegramUpdate:
        """Like ``_update_from_event``, but probes VOICE duration from the cache.

        Hermes v0.20's ``MessageEvent`` has no ``media_durations`` field, so a
        voice note arrives with ``duration_seconds=None`` and ``validate_media``
        would reject it (media.py requires a duration <= 300s). The bundled
        TelegramAdapter exposes ``_probe_voice_duration_seconds`` (mutagen ->
        ffprobe); we reuse it on the cached path and rebuild the ``MediaInput``
        with the probed duration so voice notes pass validation (R-2 / S-2.3).

        ``gateway`` is part of the intake-hook contract (the design's hook
        passes it); the probe needs no gateway state today.

        Fail closed (S-10.5): when the probe is unavailable or raises, the
        update keeps ``duration_seconds=None`` and ``validate_media`` rejects
        the capture — the hook maps that to ``skip-rejected``, never a leak.
        """
        update = self._update_from_event(event)
        if (
            update.media.kind is not MediaKind.VOICE
            or update.media.duration_seconds is not None
        ):
            return update
        try:
            duration = _probe_voice_duration(update.media.path)
        except Exception:  # noqa: BLE001 — fail closed, never crash dispatch
            duration = None
        if duration is None:
            return update
        return replace(
            update,
            media=replace(update.media, duration_seconds=float(duration)),
        )
