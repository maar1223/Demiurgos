"""
web-config-ui FastAPI application.

Single-file server with 3 routes, htmx partial page swaps, and no external CDN.
All user-facing text in Spanish. API keys are masked in all log output.
"""

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# --- Ensure config.py is importable from this directory ---
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import config  # noqa: E402

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("web-config-ui")

# --- Paths relative to project root ---
_PROJECT_ROOT = _HERE.parents[3]  # src/tools/web-config-ui -> project root
ENV_PATH = str(_PROJECT_ROOT / ".env")
JSON_CONFIG_PATH = str(_PROJECT_ROOT / "config" / "default-config.json")

# --- FastAPI app ---
app = FastAPI(title="Demiurgos Web Config UI", version="0.1.0")

# --- Static files ---
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

# --- Templates ---
templates = Jinja2Templates(directory=str(_HERE / "templates"))


@app.on_event("startup")
async def startup() -> None:
    port = os.environ.get("PORT", "8000")
    if "PORT" not in os.environ:
        port = None
    if port:
        logger.info("Demiurgos Web Config UI started on http://localhost:%s", port)
    else:
        logger.info("Demiurgos Web Config UI started (port set by uvicorn)")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main config form pre-filled with current .env values."""
    env_data = config.read_env(ENV_PATH)
    return templates.TemplateResponse(
        request,
        "index.html",
        context={
            "providers": config.KNOWN_PROVIDERS,
            "env": env_data,
            "current_text_model": env_data.get("text_model", ""),
            "current_vision_model": env_data.get("vision_model", ""),
        },
    )


@app.post("/test-connection", response_class=HTMLResponse)
async def test_connection(request: Request) -> HTMLResponse:
    """Accept form data, call ``config.test_connection()``, return HTML fragment.

    On success: renders ``_model_select.html`` with discovered models.
    On error: renders ``_errors.html`` with user-friendly Spanish message.
    """
    # --- parse form data ---
    try:
        form_data = await request.form()
    except Exception:
        return _error_fragment(request, "Datos inválidos: se esperaba un formulario")

    endpoint = (form_data.get("text_endpoint") or "").strip()
    api_key = (form_data.get("text_api_key") or "").strip()
    provider_id = (form_data.get("text_provider") or "").strip()

    # --- validation ---
    if not endpoint:
        return _error_fragment(request, "El endpoint es obligatorio")
    if not api_key:
        return _error_fragment(request, "La API key es obligatoria")

    masked = config.mask_api_key(api_key)
    logger.info(
        "Testing connection: endpoint=%s key=%s provider=%s",
        endpoint,
        masked,
        provider_id or "(none)",
    )

    # --- run test ---
    models, error = config.test_connection(endpoint, api_key)

    if error:
        return _error_fragment(request, error)

    # --- check vision support from known provider registry ---
    provider_info = config._find_provider_by_id(provider_id)
    supports_vision = provider_info["supports_vision"] if provider_info else False

    logger.info(
        "Connection test succeeded: %d models, supports_vision=%s",
        len(models),
        supports_vision,
    )
    # Read current models from .env so we can pre-select them in the fragment
    current_env = config.read_env(ENV_PATH)
    return templates.TemplateResponse(
        request,
        "_model_select.html",
        context={
            "models": models,
            "supports_vision": supports_vision,
            "current_text_model": current_env.get("text_model", ""),
            "current_vision_model": current_env.get("vision_model", ""),
        },
    )


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
        return _error_fragment(request, "Seleccioná un proveedor de texto")
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


# ---------------------------------------------------------------------------
# Fragment helpers
# ---------------------------------------------------------------------------


def _error_fragment(request: Request, message: str) -> HTMLResponse:
    """Render ``_errors.html`` with *message*."""
    return templates.TemplateResponse(
        request,
        "_errors.html",
        context={"error": message},
    )
