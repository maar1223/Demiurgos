"""
web-config-ui FastAPI application.

Single-file server with 7-screen wizard, htmx partial page swaps, and no
external CDN.  All user-facing text routed through i18n.  API keys are
masked in all log output.
"""

import logging
import os
import re
import shutil
import sys
import uuid
from collections import defaultdict
from contextvars import ContextVar
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# --- Ensure config.py is importable from this directory --------------------
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import config  # noqa: E402
from i18n import get_language_name, register_with_jinja, t  # noqa: E402

# --- Logging ---------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("web-config-ui")

# --- Session management ----------------------------------------------------
# In-memory session store.  Sessions are keyed by a UUID stored in a
# ``demiurgos_session`` cookie (httponly, 1-hour TTL).

sessions: dict[str, dict] = defaultdict(dict)

# Step-name i18n keys for the 7-step progress indicator.
_STEP_KEYS = [
    "welcome_title",
    "world_title",
    "ai_title",
    "images_title",
    "chats_title",
    "backup_title",
    "summary_title",
]


def _steps_list(lang: str) -> list[str]:
    """Return translated step labels for the progress indicator."""
    return [t(lang, key) for key in _STEP_KEYS]


# --- Path resolution -------------------------------------------------------
_PROJECT_ROOT = Path(
    os.environ.get(
        "DEMIURGOS_WORLD_DIR",
        str(_HERE.parents[3]),  # fallback: project root
    )
)
ENV_PATH = str(_PROJECT_ROOT / ".env")
JSON_CONFIG_PATH = str(_PROJECT_ROOT / "config" / "default-config.json")
AGENTS_PATH = _PROJECT_ROOT / "AGENTS.md"

# --- FastAPI app -----------------------------------------------------------
app = FastAPI(title="Demiurgos Web Config UI", version="0.2.0")

# --- Static files & templates ----------------------------------------------
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")
templates = Jinja2Templates(directory=str(_HERE / "templates"))

# --- i18n ------------------------------------------------------------------
_current_language: ContextVar[str] = ContextVar("current_language", default="en")
register_with_jinja(templates, _current_language.get)


# ===========================================================================
# Middleware
# ===========================================================================


@app.middleware("http")
async def language_middleware(request: Request, call_next):
    """Read language from cookie, query param, or default to English.

    Sets the ContextVar so ``t(key)`` in templates resolves to the
    correct language at render time.
    """
    lang = (
        request.cookies.get("demiurgos_lang")
        or request.query_params.get("lang")
        or "en"
    )
    _current_language.set(lang)
    response = await call_next(request)
    return response


@app.on_event("startup")
async def startup() -> None:
    port = os.environ.get("PORT", "8000")
    if "PORT" not in os.environ:
        port = None
    if port:
        logger.info("Demiurgos Web Config UI started on http://localhost:%s", port)
    else:
        logger.info("Demiurgos Web Config UI started (port set by uvicorn)")


# ===========================================================================
# Helpers
# ===========================================================================


def _get_session_id(request: Request) -> str:
    """Get existing session ID from cookie, or mint a fresh one."""
    session_id = request.cookies.get("demiurgos_session")
    if not session_id or session_id not in sessions:
        session_id = str(uuid.uuid4())
    return session_id


def _attach_session(response: HTMLResponse, session_id: str) -> None:
    """Attach session cookie to *response*."""
    response.set_cookie(
        key="demiurgos_session",
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=3600,
    )


def _wizard_ctx(session: dict) -> dict:
    """Return common template context for wizard screens."""
    lang = session.get("language", "en")
    return {
        "lang": lang,
        "steps": _steps_list(lang),
    }


def _error_fragment(request: Request, message: str) -> HTMLResponse:
    """Render ``_errors.html`` with *message*."""
    return templates.TemplateResponse(
        request,
        "_errors.html",
        context={"error": message},
    )


def _provider_display(provider_id: str) -> str:
    """Return the human-readable name for *provider_id*, or the id itself."""
    info = config._find_provider_by_id(provider_id)
    return info["name"] if info else provider_id


# ===========================================================================
# Routes — index
# ===========================================================================


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the full wizard shell or already-configured page."""
    lang = _current_language.get()

    # Check if Demiurgos is already configured
    current_env = config.read_env(ENV_PATH)
    if current_env.get("text_provider"):
        return templates.TemplateResponse(
            request,
            "already_configured.html",
            context={
                "lang": lang,
                "text_provider": _provider_display(current_env["text_provider"]),
                "text_model": current_env.get("text_model", ""),
            },
        )

    return templates.TemplateResponse(
        request,
        "index.html",
        context={
            "lang": lang,
            "current_step": 0,
            "steps": _steps_list(lang),
        },
    )


# ===========================================================================
# Routes — connection tests (modified: T-C4 vision tags)
# ===========================================================================


@app.post("/test-connection", response_class=HTMLResponse)
async def test_connection(request: Request) -> HTMLResponse:
    """Accept form data, call ``config.test_connection()``, return a fragment
    with vision-tagged models (T-C4)."""
    try:
        form_data = await request.form()
    except Exception:
        return _error_fragment(request, "Datos inválidos: se esperaba un formulario")

    endpoint = (form_data.get("text_endpoint") or "").strip()
    api_key = (form_data.get("text_api_key") or "").strip()
    provider_id = (form_data.get("text_provider") or "").strip()

    if not endpoint:
        return _error_fragment(request, "El endpoint es obligatorio")
    if not api_key:
        return _error_fragment(request, "La API key es obligatoria")

    masked = config.mask_api_key(api_key)
    logger.info(
        "Testing connection: endpoint=%s key=%s provider=%s",
        endpoint, masked, provider_id or "(none)",
    )

    models, error_code, error_params = config.test_connection(endpoint, api_key)

    if error_code:
        lang = request.cookies.get("demiurgos_lang", "en")
        error_key = f"error_{error_code}"
        error_msg = t(lang, error_key)
        # Fall back to generic error if specific key is not translated
        if error_msg == error_key:
            error_msg = t(lang, "error_generic")
        if error_params:
            try:
                error_msg = error_msg.format(**error_params)
            except (KeyError, ValueError):
                pass
        return _error_fragment(request, error_msg)

    # --- tag every model with its vision capability (T-C4) ---
    tagged_models = (
        config.get_vision_models(provider_id, models)
        if provider_id
        else [{"id": m, "tag": "❓", "confidence": "unknown"} for m in models]
    )

    provider_info = config._find_provider_by_id(provider_id)
    supports_vision = provider_info["supports_vision"] if provider_info else False

    logger.info(
        "Connection test succeeded: %d models, supports_vision=%s",
        len(models), supports_vision,
    )

    current_env = config.read_env(ENV_PATH)
    return templates.TemplateResponse(
        request,
        "_model_select.html",
        context={
            "models": tagged_models,
            "supports_vision": supports_vision,
            "current_text_model": current_env.get("text_model", ""),
            "current_vision_model": current_env.get("vision_model", ""),
        },
    )


@app.post("/test-vision-connection", response_class=HTMLResponse)
async def test_vision_connection(request: Request) -> HTMLResponse:
    """Same as test-connection but reads vision fields and tags models."""
    try:
        form_data = await request.form()
    except Exception:
        return _error_fragment(request, "Datos inválidos")

    endpoint = (form_data.get("vision_endpoint") or "").strip()
    api_key = (form_data.get("vision_api_key") or "").strip()
    provider_id = (form_data.get("vision_provider") or "").strip()

    if not endpoint:
        return _error_fragment(request, "El endpoint de visión es obligatorio")
    if not api_key:
        return _error_fragment(request, "La API key de visión es obligatoria")

    masked = config.mask_api_key(api_key)
    logger.info("Testing vision connection: endpoint=%s key=%s", endpoint, masked)

    models, error_code, error_params = config.test_connection(endpoint, api_key)

    if error_code:
        lang = request.cookies.get("demiurgos_lang", "en")
        error_key = f"error_{error_code}"
        error_msg = t(lang, error_key)
        # Fall back to generic error if specific key is not translated
        if error_msg == error_key:
            error_msg = t(lang, "error_generic")
        if error_params:
            try:
                error_msg = error_msg.format(**error_params)
            except (KeyError, ValueError):
                pass
        return _error_fragment(request, error_msg)

    tagged_models = (
        config.get_vision_models(provider_id, models)
        if provider_id
        else [{"id": m, "tag": "❓", "confidence": "unknown"} for m in models]
    )

    logger.info("Vision connection test succeeded: %d models", len(models))
    return templates.TemplateResponse(
        request,
        "_vision_model_select.html",
        context={"models": tagged_models},
    )


# ===========================================================================
# Routes — config dashboard
# ===========================================================================


@app.get("/config", response_class=HTMLResponse)
async def config_dashboard(request: Request) -> HTMLResponse:
    """Render the configuration dashboard with status for all 6 sections."""
    lang = _current_language.get()
    raw_env = config.read_env(ENV_PATH)

    # --- Gather data for each section ---
    language_code = (
        os.environ.get("DEMIURGOS_LANGUAGE", "")
        or request.cookies.get("demiurgos_lang", "")
    )
    world_name = os.environ.get("DEMIURGOS_WORLD", "")
    text_provider = raw_env.get("text_provider", "")
    image_provider = os.environ.get("DEMIURGOS_IMAGE_PROVIDER", "")
    chat_providers = os.environ.get("DEMIURGOS_CHAT_PROVIDERS", "")
    backup_enabled = os.environ.get("DEMIURGOS_BACKUP_ENABLED", "")

    sections = [
        {
            "id": "language",
            "icon": "🌐",
            "title_key": "config_language",
            "configured": bool(language_code),
            "value": get_language_name(language_code) if language_code else "",
            "badge": "configured" if language_code else "not_configured",
            "edit_url": "/wizard/0",
        },
        {
            "id": "world",
            "icon": "🌍",
            "title_key": "config_world",
            "configured": bool(world_name),
            "value": world_name,
            "badge": "configured" if world_name else "not_configured",
            "edit_url": "/wizard/1",
        },
        {
            "id": "ai",
            "icon": "🤖",
            "title_key": "config_ai",
            "configured": bool(text_provider),
            "value": _provider_display(text_provider) if text_provider else "",
            "badge": "configured" if text_provider else "not_configured",
            "edit_url": "/wizard/2",
        },
        {
            "id": "images",
            "icon": "🎨",
            "title_key": "config_images",
            "configured": bool(image_provider),
            "value": image_provider,
            "badge": "skipped" if not image_provider and os.environ.get("DEMIURGOS_IMAGE_PROVIDER") is not None else (
                "configured" if image_provider else "not_configured"
            ),
            "edit_url": "/wizard/3",
        },
        {
            "id": "chats",
            "icon": "💬",
            "title_key": "config_chats",
            "configured": bool(chat_providers),
            "value": chat_providers,
            "badge": "configured" if chat_providers else "not_configured",
            "edit_url": "/wizard/4",
        },
        {
            "id": "backup",
            "icon": "☁️",
            "title_key": "config_backup",
            "configured": backup_enabled == "true",
            "value": backup_enabled,
            "badge": (
                "skipped" if backup_enabled == "false"
                else "configured" if backup_enabled == "true"
                else "not_configured"
            ),
            "edit_url": "/wizard/5",
        },
    ]

    return templates.TemplateResponse(
        request,
        "config_dashboard.html",
        context={
            "lang": lang,
            "sections": sections,
        },
    )


@app.get("/restart")
async def restart_wizard(request: Request) -> RedirectResponse:
    """Clear session and restart the wizard."""
    session_id = request.cookies.get("demiurgos_session")
    if session_id and session_id in sessions:
        del sessions[session_id]
    return RedirectResponse(url="/", status_code=303)


# ===========================================================================
# Routes — wizard back navigation (GET /wizard/{screen})
# ===========================================================================


@app.get("/wizard/0", response_class=HTMLResponse)
async def wizard_back_0(request: Request) -> HTMLResponse:
    """Back to language selection (screen 0)."""
    sid = _get_session_id(request)
    sess = sessions[sid]
    ctx = _wizard_ctx(sess)
    ctx["current_step"] = 0
    response = templates.TemplateResponse(request, "screen_lang.html", ctx)
    _attach_session(response, sid)
    return response


@app.get("/wizard/1", response_class=HTMLResponse)
async def wizard_back_1(request: Request) -> HTMLResponse:
    """Back to world selection (screen 1). Pre-fill from .env."""
    sid = _get_session_id(request)
    sess = sessions[sid]
    ctx = _wizard_ctx(sess)
    ctx["current_step"] = 1
    ctx["world_name"] = os.environ.get("DEMIURGOS_WORLD", "")
    response = templates.TemplateResponse(request, "screen_world.html", ctx)
    _attach_session(response, sid)
    return response


@app.get("/wizard/2", response_class=HTMLResponse)
async def wizard_back_2(request: Request) -> HTMLResponse:
    """Back to AI config (screen 2) with session/.env data pre-filled."""
    sid = _get_session_id(request)
    sess = sessions[sid]
    ai = sess.get("ai", {})
    # Fall back to .env when session has no AI data
    env = {} if ai else config.read_env(ENV_PATH)
    ctx = _wizard_ctx(sess)
    ctx.update({
        "current_step": 2,
        "providers": config.KNOWN_PROVIDERS,
        "current_text_provider": ai.get("text_provider") or env.get("text_provider", ""),
        "current_text_endpoint": ai.get("text_endpoint") or env.get("text_endpoint", ""),
        "current_text_api_key": ai.get("text_api_key") or env.get("text_api_key", ""),
        "current_text_model": ai.get("text_model") or env.get("text_model", ""),
        "text_models": [],
        "current_vision_provider": ai.get("vision_provider") or env.get("vision_provider", ""),
        "current_vision_endpoint": ai.get("vision_endpoint") or env.get("vision_endpoint", ""),
        "current_vision_api_key": ai.get("vision_api_key") or env.get("vision_api_key", ""),
        "current_vision_model": ai.get("vision_model") or env.get("vision_model", ""),
        "vision_models": [],
        "same_as_text": True,
    })
    response = templates.TemplateResponse(request, "screen_ai.html", ctx)
    _attach_session(response, sid)
    return response


@app.get("/wizard/3", response_class=HTMLResponse)
async def wizard_back_3(request: Request) -> HTMLResponse:
    """Back to image generation (screen 3). Pre-fill from session or .env."""
    sid = _get_session_id(request)
    sess = sessions[sid]
    ctx = _wizard_ctx(sess)
    ctx["current_step"] = 3
    # Pre-fill from .env if session has no image data (dashboard re-entry)
    img = sess.get("images", {})
    if not img:
        ctx["img_provider"] = os.environ.get("DEMIURGOS_IMAGE_PROVIDER", "")
        ctx["img_endpoint"] = os.environ.get("DEMIURGOS_IMAGE_ENDPOINT", "")
        ctx["img_model"] = os.environ.get("DEMIURGOS_IMAGE_MODEL", "")
        ctx["img_api_key"] = os.environ.get("DEMIURGOS_IMAGE_API_KEY", "")
    response = templates.TemplateResponse(request, "screen_img.html", ctx)
    _attach_session(response, sid)
    return response


@app.get("/wizard/4", response_class=HTMLResponse)
async def wizard_back_4(request: Request) -> HTMLResponse:
    """Back to chat platforms (screen 4)."""
    sid = _get_session_id(request)
    sess = sessions[sid]
    chats = sess.get("chats", {})
    providers = chats.get("providers", [])
    ctx = _wizard_ctx(sess)
    ctx.update({
        "current_step": 4,
        "chat_telegram_enabled": "telegram" in providers,
        "chat_discord_enabled": "discord" in providers,
        "telegram_token": chats.get("telegram_token", ""),
        "discord_token": chats.get("discord_token", ""),
    })
    response = templates.TemplateResponse(request, "screen_chat.html", ctx)
    _attach_session(response, sid)
    return response


@app.get("/wizard/5", response_class=HTMLResponse)
async def wizard_back_5(request: Request) -> HTMLResponse:
    """Back to backup/sync (screen 5)."""
    sid = _get_session_id(request)
    sess = sessions[sid]
    backup = sess.get("backup", {})
    ctx = _wizard_ctx(sess)
    ctx.update({
        "current_step": 5,
        "backup_enabled": backup.get("enabled", False),
        "rclone_detected": shutil.which("rclone") is not None,
    })
    response = templates.TemplateResponse(request, "screen_backup.html", ctx)
    _attach_session(response, sid)
    return response


# ===========================================================================
# Routes — wizard form submissions (POST /wizard/{screen})
# ===========================================================================


@app.post("/wizard/0", response_class=HTMLResponse)
async def wizard_post_lang(request: Request) -> HTMLResponse:
    """Screen 0 → 1: save language, advance to world config."""
    sid = _get_session_id(request)
    sess = sessions[sid]

    try:
        form_data = await request.form()
    except Exception:
        return _error_fragment(request, "Datos inválidos")

    lang = (form_data.get("lang") or "en").strip()
    sess["language"] = lang
    _current_language.set(lang)

    ctx = _wizard_ctx(sess)
    ctx["current_step"] = 1

    response = templates.TemplateResponse(request, "screen_world.html", ctx)
    response.set_cookie(
        key="demiurgos_lang", value=lang, samesite="lax", max_age=31536000,
    )
    _attach_session(response, sid)
    logger.info("Wizard: language set to '%s'", lang)
    return response


@app.post("/wizard/1", response_class=HTMLResponse)
async def wizard_post_world(request: Request) -> HTMLResponse:
    """Screen 1 → 2: save world config, advance to AI config.

    Pre-fills AI form from current ``.env`` values (T-C3).
    """
    sid = _get_session_id(request)
    sess = sessions[sid]

    try:
        form_data = await request.form()
    except Exception:
        return _error_fragment(request, "Datos inválidos")

    world_name_raw = (form_data.get("world_name") or "").strip()
    world_folder = (form_data.get("world_folder") or "").strip()

    if world_name_raw:
        # Create new world — sanitize name
        world_name = world_name_raw.lower().replace(" ", "-")
        world_name = re.sub(r"[^a-z0-9-]", "", world_name)
        sess["world"] = {"type": "create", "name": world_name, "path": ""}
        logger.info("Wizard: creating new world '%s'", world_name)
    elif world_folder:
        sess["world"] = {
            "type": "load",
            "name": os.path.basename(world_folder.rstrip("/\\")) or world_folder,
            "path": world_folder,
        }
        logger.info("Wizard: loading existing world from '%s'", world_folder)
    else:
        ctx = _wizard_ctx(sess)
        ctx["current_step"] = 1
        response = templates.TemplateResponse(request, "screen_world.html", ctx)
        _attach_session(response, sid)
        return response

    # Pre-fill AI form from current .env (T-C3)
    current_env = config.read_env(ENV_PATH)
    ctx = _wizard_ctx(sess)
    ctx.update({
        "current_step": 2,
        "providers": config.KNOWN_PROVIDERS,
        "current_text_provider": current_env.get("text_provider", ""),
        "current_text_endpoint": current_env.get("text_endpoint", ""),
        "current_text_api_key": current_env.get("text_api_key", ""),
        "current_text_model": current_env.get("text_model", ""),
        "text_models": [],
        "current_vision_provider": current_env.get("vision_provider", ""),
        "current_vision_endpoint": current_env.get("vision_endpoint", ""),
        "current_vision_api_key": current_env.get("vision_api_key", ""),
        "current_vision_model": current_env.get("vision_model", ""),
        "vision_models": [],
        "same_as_text": True,
    })

    response = templates.TemplateResponse(request, "screen_ai.html", ctx)
    _attach_session(response, sid)
    return response


@app.post("/wizard/2", response_class=HTMLResponse)
async def wizard_post_ai(request: Request) -> HTMLResponse:
    """Screen 2 → 3: save AI config (session only), advance to images.

    Validates vision compatibility when ``same_as_text`` is used.
    """
    sid = _get_session_id(request)
    sess = sessions[sid]

    try:
        form_data = await request.form()
    except Exception:
        return _error_fragment(request, "Datos inválidos")

    text_provider = (form_data.get("text_provider") or "").strip()
    text_endpoint = (form_data.get("text_endpoint") or "").strip()
    text_api_key = (form_data.get("text_api_key") or "").strip()
    text_model_raw = (form_data.get("text_model") or "").strip()
    if text_model_raw == "__other__":
        text_model_raw = (form_data.get("text_model_custom") or "").strip()
    text_model = text_model_raw

    same_as_text = form_data.get("same_as_text") == "on"

    if same_as_text:
        vision_provider = text_provider
        vision_endpoint = text_endpoint
        vision_api_key = text_api_key
        vision_model = text_model

        # Vision-compatibility gate: if text model can't do vision
        # and user chose "same as text", bounce back with warning.
        if text_provider and text_model:
            tag = config.get_vision_tag(text_provider, text_model)
            if tag["tag"] != "👁️+✍️":
                ctx = _wizard_ctx(sess)
                ctx.update({
                    "current_step": 2,
                    "providers": config.KNOWN_PROVIDERS,
                    "current_text_provider": text_provider,
                    "current_text_endpoint": text_endpoint,
                    "current_text_api_key": text_api_key,
                    "current_text_model": text_model,
                    "text_models": [],
                    "same_as_text": True,
                    "text_model_has_vision": False,
                })
                response = templates.TemplateResponse(
                    request, "screen_ai.html", ctx,
                )
                _attach_session(response, sid)
                logger.warning(
                    "Vision gate: model '%s' from provider '%s' lacks vision",
                    text_model, text_provider,
                )
                return response
    else:
        vision_provider = (form_data.get("vision_provider") or "").strip()
        vision_endpoint = (form_data.get("vision_endpoint") or "").strip()
        vision_api_key = (form_data.get("vision_api_key") or "").strip()
        vision_model_raw = (form_data.get("vision_model") or "").strip()
        if vision_model_raw == "__other__":
            vision_model_raw = (form_data.get("vision_model_custom") or "").strip()
        vision_model = vision_model_raw

    sess["ai"] = {
        "text_provider": text_provider,
        "text_endpoint": text_endpoint,
        "text_api_key": text_api_key,
        "text_model": text_model,
        "vision_provider": vision_provider,
        "vision_endpoint": vision_endpoint,
        "vision_api_key": vision_api_key,
        "vision_model": vision_model,
        "same_as_text": same_as_text,
    }

    logger.info(
        "Wizard AI: text_provider=%s text_model=%s same_as_text=%s",
        text_provider, text_model, same_as_text,
    )

    ctx = _wizard_ctx(sess)
    ctx["current_step"] = 3
    response = templates.TemplateResponse(request, "screen_img.html", ctx)
    _attach_session(response, sid)
    return response


@app.post("/wizard/3", response_class=HTMLResponse)
async def wizard_post_images(request: Request) -> HTMLResponse:
    """Screen 3 → 4: process image-gen config, advance to chats."""
    sid = _get_session_id(request)
    sess = sessions[sid]

    try:
        form_data = await request.form()
    except Exception:
        return _error_fragment(request, "Datos inválidos")

    action = (form_data.get("action") or "save").strip()

    if action == "skip":
        sess["images"] = {"skipped": True}
        logger.info("Wizard: image generation skipped")
    else:
        sess["images"] = {
            "skipped": False,
            "provider": (form_data.get("img_provider") or "").strip(),
            "endpoint": (form_data.get("img_endpoint") or "").strip(),
            "api_key": (form_data.get("img_api_key") or "").strip(),
            "model": (form_data.get("img_model") or "").strip(),
        }

    ctx = _wizard_ctx(sess)
    ctx["current_step"] = 4
    response = templates.TemplateResponse(request, "screen_chat.html", ctx)
    _attach_session(response, sid)
    return response


@app.post("/wizard/4", response_class=HTMLResponse)
async def wizard_post_chats(request: Request) -> HTMLResponse:
    """Screen 4 → 5: process chat-platform config, advance to backup."""
    sid = _get_session_id(request)
    sess = sessions[sid]

    try:
        form_data = await request.form()
    except Exception:
        return _error_fragment(request, "Datos inválidos")

    action = (form_data.get("action") or "save").strip()

    if action == "skip":
        sess["chats"] = {"skipped": True, "providers": []}
        logger.info("Wizard: chat platforms skipped")
    else:
        providers = []
        if form_data.get("chat_telegram") == "on":
            providers.append("telegram")
        if form_data.get("chat_discord") == "on":
            providers.append("discord")

        sess["chats"] = {
            "skipped": False,
            "providers": providers,
            "telegram_token": (form_data.get("telegram_token") or "").strip(),
            "discord_token": (form_data.get("discord_token") or "").strip(),
        }

    ctx = _wizard_ctx(sess)
    ctx["current_step"] = 5
    response = templates.TemplateResponse(request, "screen_backup.html", ctx)
    _attach_session(response, sid)
    return response


@app.post("/wizard/5", response_class=HTMLResponse)
async def wizard_post_backup(request: Request) -> HTMLResponse:
    """Screen 5 → 6: process backup config, advance to summary."""
    sid = _get_session_id(request)
    sess = sessions[sid]

    try:
        form_data = await request.form()
    except Exception:
        return _error_fragment(request, "Datos inválidos")

    action = (form_data.get("action") or "save").strip()

    if action == "skip":
        sess["backup"] = {"skipped": True, "enabled": False}
        logger.info("Wizard: backup skipped")
    else:
        sess["backup"] = {
            "skipped": False,
            "enabled": form_data.get("backup_enabled") == "on",
            "interval": (form_data.get("backup_interval") or "daily").strip(),
        }

    # --- Build summary context from session ---
    lang_code = sess.get("language", "en")
    world = sess.get("world", {})
    ai = sess.get("ai", {})
    img = sess.get("images", {})
    chats = sess.get("chats", {})
    backup = sess.get("backup", {})

    ctx = _wizard_ctx(sess)
    ctx.update({
        "current_step": 6,
        "language_name": get_language_name(lang_code),
        "world_name": world.get("name", ""),
        "text_provider": _provider_display(ai.get("text_provider", "")),
        "text_model": ai.get("text_model", ""),
        "same_as_text_model": ai.get("same_as_text", True),
        "vision_provider": (
            "" if ai.get("same_as_text", True)
            else _provider_display(ai.get("vision_provider", ""))
        ),
        "vision_model": "" if ai.get("same_as_text", True) else ai.get("vision_model", ""),
        "img_provider": "" if img.get("skipped", False) else img.get("provider", ""),
        "img_model": "" if img.get("skipped", False) else img.get("model", ""),
        "chat_providers": chats.get("providers", []),
        "backup_enabled": (
            not backup.get("skipped", False) and backup.get("enabled", False)
        ),
    })

    response = templates.TemplateResponse(request, "screen_summary.html", ctx)
    _attach_session(response, sid)
    return response


@app.post("/wizard/finish", response_class=HTMLResponse)
async def wizard_finish(request: Request) -> HTMLResponse:
    """Finalize wizard: persist config to .env, create world dir, copy AGENTS.md."""
    sid = _get_session_id(request)
    sess = sessions[sid]

    lang = sess.get("language", "en")
    world = sess.get("world", {})
    ai = sess.get("ai", {})

    errors: list[str] = []

    # --- 1. Create world directory (if creating new) ---
    if world.get("type") == "create":
        world_name = world.get("name", "")
        if world_name:
            world_dir = _PROJECT_ROOT / "mundos" / world_name
            try:
                world_dir.mkdir(parents=True, exist_ok=True)
                (world_dir / "Lore").mkdir(exist_ok=True)
                (world_dir / "Personajes").mkdir(exist_ok=True)
                (world_dir / "sagas").mkdir(exist_ok=True)
                (world_dir / "Ideas").mkdir(exist_ok=True)
                logger.info("Created world directory: %s", world_dir)

                if AGENTS_PATH.exists():
                    shutil.copy2(AGENTS_PATH, world_dir / "AGENTS.md")
                    logger.info("Copied AGENTS.md to %s", world_dir)
            except OSError as exc:
                errors.append(f"Error al crear el mundo: {exc}")
                logger.error("Failed to create world directory: %s", exc)

    # --- 2. Persist AI config to .env ---
    env_data = {
        "text_provider": ai.get("text_provider", ""),
        "text_endpoint": ai.get("text_endpoint", ""),
        "text_model": ai.get("text_model", ""),
        "text_api_key": ai.get("text_api_key", ""),
        "vision_provider": ai.get("vision_provider", ""),
        "vision_endpoint": ai.get("vision_endpoint", ""),
        "vision_model": ai.get("vision_model", ""),
        "vision_api_key": ai.get("vision_api_key", ""),
    }

    if not env_data["text_provider"]:
        errors.append("Falta configurar el proveedor de texto")

    if not errors and env_data["text_provider"]:
        env_ok = config.write_env(ENV_PATH, env_data)
        if not env_ok:
            errors.append("Error al escribir el archivo .env")

    # --- 3. Persist JSON config ---
    json_data: dict = {
        "text": {
            "provider": env_data["text_provider"],
            "endpoint": env_data["text_endpoint"],
            "model": env_data["text_model"],
            "api_key": env_data["text_api_key"],
        }
    }
    if env_data["vision_provider"]:
        json_data["vision"] = {
            "provider": env_data["vision_provider"],
            "endpoint": env_data["vision_endpoint"],
            "model": env_data["vision_model"],
            "api_key": env_data["vision_api_key"],
        }

    if not errors:
        json_ok = config.write_json_config(JSON_CONFIG_PATH, json_data)
        if not json_ok:
            errors.append("Error al escribir default-config.json")

    # --- 4. Persist optional configs (images, chats, backup) ---
    if not errors:
        img = sess.get("images", {})
        chat = sess.get("chats", {})
        backup = sess.get("backup", {})

        optional_lines: list[str] = []
        if not img.get("skipped") and img.get("api_key"):
            optional_lines.append(f"DEMIURGOS_IMAGE_PROVIDER={img.get('provider', '')}")
            optional_lines.append(f"DEMIURGOS_IMAGE_ENDPOINT={img.get('endpoint', '')}")
            optional_lines.append(f"DEMIURGOS_IMAGE_MODEL={img.get('model', '')}")
            optional_lines.append(f"DEMIURGOS_IMAGE_API_KEY={img['api_key']}")

        if not chat.get("skipped") and chat.get("providers"):
            providers_str = ",".join(chat["providers"])
            optional_lines.append(f"DEMIURGOS_CHAT_PROVIDERS={providers_str}")

        if not backup.get("skipped"):
            optional_lines.append(
                f"DEMIURGOS_BACKUP_ENABLED={'true' if backup.get('enabled') else 'false'}"
            )

        if optional_lines:
            try:
                with open(ENV_PATH, "a", encoding="utf-8") as f:
                    f.write("\n# Optional Demiurgos config\n")
                    for line in optional_lines:
                        f.write(line + "\n")
                logger.info("Optional config persisted to .env: %d vars", len(optional_lines))
            except OSError as exc:
                logger.error("Failed to write optional config to .env: %s", exc)

    # --- Render result ---
    if errors:
        # Re-render summary with errors
        ctx = _wizard_ctx(sess)
        ctx["current_step"] = 6
        ctx["errors"] = errors
        response = templates.TemplateResponse(request, "screen_summary.html", ctx)
        _attach_session(response, sid)
        return response

    logger.info("Wizard finished — world='%s' lang='%s'", world.get("name", ""), lang)

    ctx = _wizard_ctx(sess)
    ctx["world_name"] = world.get("name", "")

    response = templates.TemplateResponse(request, "wizard_done.html", ctx)
    response.set_cookie(
        key="demiurgos_lang", value=lang, samesite="lax", max_age=31536000,
    )
    _attach_session(response, sid)
    return response


# ===========================================================================
# Routes — AI screen htmx sub-routes
# ===========================================================================


@app.get("/wizard/2/provider-defaults", response_class=HTMLResponse)
async def wizard_provider_defaults(request: Request) -> HTMLResponse:
    """Return endpoint + API-key fields pre-filled for the selected provider."""
    provider_id = request.query_params.get("text_provider", "").strip()
    provider_info = config._find_provider_by_id(provider_id)

    endpoint = provider_info.get("default_endpoint", "") if provider_info else ""

    # Try session-stored API key, then .env
    sid = _get_session_id(request)
    ai = sessions[sid].get("ai", {})
    api_key_hint = ""
    if ai.get("text_provider") == provider_id:
        api_key_hint = ai.get("text_api_key", "")
    if not api_key_hint:
        env = config.read_env(ENV_PATH)
        if env.get("text_provider") == provider_id:
            api_key_hint = env.get("text_api_key", "")

    return templates.TemplateResponse(
        request,
        "_provider_defaults.html",
        context={
            "current_text_endpoint": endpoint,
            "current_text_api_key": api_key_hint,
        },
    )


@app.get("/wizard/2/vision-toggle", response_class=HTMLResponse)
async def wizard_vision_toggle(request: Request) -> HTMLResponse:
    """Return vision-fields fragment based on ``same_as_text`` checkbox state."""
    sid = _get_session_id(request)
    ai = sessions[sid].get("ai", {})

    same_as_text = request.query_params.get("same_as_text") is not None

    text_provider = ai.get("text_provider", "")
    text_model = ai.get("text_model", "")

    # Check if current text model supports vision
    text_model_has_vision = True
    if text_provider and text_model:
        tag = config.get_vision_tag(text_provider, text_model)
        text_model_has_vision = tag["tag"] == "👁️+✍️"

    return templates.TemplateResponse(
        request,
        "_vision_fields.html",
        context={
            "same_as_text": same_as_text,
            "current_text_provider": text_provider,
            "current_text_endpoint": ai.get("text_endpoint", ""),
            "current_text_api_key": ai.get("text_api_key", ""),
            "current_text_model": text_model,
            "text_model_has_vision": text_model_has_vision,
            "providers": config.KNOWN_PROVIDERS,
            "current_vision_provider": ai.get("vision_provider", ""),
            "current_vision_endpoint": ai.get("vision_endpoint", ""),
            "current_vision_api_key": ai.get("vision_api_key", ""),
            "current_vision_model": ai.get("vision_model", ""),
            "vision_models": [],
        },
    )


# ===========================================================================
# Routes — save (post-wizard editing panel)
# ===========================================================================


@app.post("/save", response_class=HTMLResponse)
async def save_config(request: Request) -> HTMLResponse:
    """Accept form data, validate, persist to .env and default-config.json."""
    try:
        form_data = await request.form()
    except Exception:
        return _error_fragment(request, "Error al procesar el formulario")

    # --- extract fields ---
    text_model_raw = (form_data.get("text_model") or "").strip()
    vision_model_raw = (form_data.get("vision_model") or "").strip()

    # If user selected "Otro", use the custom typed value
    if text_model_raw == "__other__":
        text_model_raw = (form_data.get("text_model_custom") or "").strip()
    if vision_model_raw == "__other__":
        vision_model_raw = (form_data.get("vision_model_custom") or "").strip()

    env_data = {
        "text_provider": (form_data.get("text_provider") or "").strip(),
        "text_endpoint": (form_data.get("text_endpoint") or "").strip(),
        "text_model": text_model_raw,
        "text_api_key": (form_data.get("text_api_key") or "").strip(),
        "vision_provider": (form_data.get("vision_provider") or "").strip(),
        "vision_endpoint": (form_data.get("vision_endpoint") or "").strip(),
        "vision_model": vision_model_raw,
        "vision_api_key": (form_data.get("vision_api_key") or "").strip(),
    }

    # --- validate ---
    if not env_data["text_provider"]:
        return _error_fragment(request, "Selecciona un proveedor de texto")
    if not env_data["text_endpoint"]:
        return _error_fragment(request, "El endpoint de texto es obligatorio")
    if not env_data["text_api_key"]:
        return _error_fragment(request, "La API key es obligatoria")

    logger.info(
        "Saving config: text_provider=%s text_model=%s text_key=%s",
        env_data["text_provider"],
        env_data["text_model"] or "(none)",
        config.mask_api_key(env_data["text_api_key"]),
    )

    # --- persist .env ---
    env_ok = config.write_env(ENV_PATH, env_data)

    # --- persist JSON config ---
    json_data: dict = {
        "text": {
            "provider": env_data["text_provider"],
            "endpoint": env_data["text_endpoint"],
            "model": env_data["text_model"],
            "api_key": env_data["text_api_key"],
        }
    }
    if env_data["vision_provider"]:
        json_data["vision"] = {
            "provider": env_data["vision_provider"],
            "endpoint": env_data["vision_endpoint"],
            "model": env_data["vision_model"],
            "api_key": env_data["vision_api_key"],
        }

    json_ok = config.write_json_config(JSON_CONFIG_PATH, json_data)

    # --- build response ---
    if env_ok and json_ok:
        return HTMLResponse(
            '<div role="status" id="save-status" aria-live="polite">'
            "✅ Configuración guardada correctamente"
            '<script>setTimeout(function(){var e=document.getElementById("save-status");'
            "if(e){e.style.opacity='0';setTimeout(function(){if(e.parentNode)e.remove()},500)}},5000)</script>"
            "</div>"
        )
    else:
        failed = []
        if not env_ok:
            failed.append(".env")
        if not json_ok:
            failed.append("default-config.json")
        return _error_fragment(
            request,
            f"Error al escribir: {', '.join(failed)}",
        )
