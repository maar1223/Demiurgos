# Demiurgos — Guía de Comandos

Comandos reales de la plataforma web Demiurgos, verificados contra el repositorio (`scripts/`, `frontend/package.json`, `src/tools/demiurgos-suite/`).

> ✅ **La instalación oficial (Windows, Linux) ya está disponible con un solo comando**, desde el canal público firmado. Linux / macOS: `curl -fsSL https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.sh | bash`; Windows (PowerShell): `irm https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.ps1 | iex`. También puedes arrancar Demiurgos desde el repositorio con los launchers.

---

## Arranque (launchers)

| Plataforma | Comando | Inicia |
|-----------|---------|--------|
| **Linux / macOS** | `./scripts/start-demiurgos.sh start` | Gateway de Hermes (8642), API + SPA (8000) |
| **Windows** | `powershell -ExecutionPolicy Bypass -File start-demiurgos.ps1` | El mismo stack + warm-up del grafo |

- Acciones del launcher Linux: `start`, `restart`, `stop`, `install`. En Linux el instalador ya añade la entrada al menú de aplicaciones; `install` la reescribe e `install --desktop` añade además el icono en la carpeta del escritorio.
- App y health de la API: `http://127.0.0.1:8000` · `/health`
- Acciones del launcher Windows: `start`, `restart`, `stop`, `install`. El instalador
  añade el acceso al menú Inicio; `start-demiurgos.ps1 install -Desktop` añade además
  el icono del escritorio.
- En Windows puedes arrancar solo la API con `start-api.ps1`.

---

## Frontend (`frontend/`)

| Comando | Qué hace |
|---------|----------|
| `npm install` | Instala las dependencias |
| `npm test` | Vitest (ejecución única) |
| `npm run typecheck` | TypeScript sin emitir (`tsc --noEmit`) |
| `npm run build` | Typecheck + build de producción (`tsc --noEmit && vite build`) |
| `npm run dev` | Servidor de desarrollo Vite |

---

## Backend (`src/tools/demiurgos-suite/wiki/`)

| Comando | Qué hace |
|---------|----------|
| `python3 -m venv .venv` | Crea el entorno virtual |
| `.venv/bin/pip install -r src/tools/demiurgos-suite/requirements.txt` | Instala las dependencias del backend |
| `pytest tests/` | Suite de tests (o `pytest tests/test_x.py` para un archivo) |
| `.venv/bin/python -m uvicorn api_server:app --reload --port 8001` | API en desarrollo |

---

## Endpoints principales

| Endpoint | Qué hace |
|----------|----------|
| `GET /health` | Health check de la API |
| `GET /api/worlds` | Lista los mundos cargados |
| `GET /api/{mundo}/graph/search` | Búsqueda en el grafo de entidades |
| `GET /api/{mundo}/graph/entity` | Entidad y sus relaciones |
| `POST /api/{mundo}/ai/ask` | Asistente de IA (streaming SSE) |
| `POST /api/{mundo}/ai/edit-suggest` | Sugerencias de edición |
| `GET /api/{mundo}/{section}/tree` | Árbol de archivos de una sección |
| `POST /api/{mundo}/{section}/save` | Guardar una ficha (con compuerta de confirmación) |

---

## Subsistema narrativo CLI (Hermes)

Las 13 fases narrativas (`/narrative-init`, `/narrative-explore`, `/narrative-propose`, `/narrative-world-spec`, `/narrative-character-spec`, `/narrative-design`, `/narrative-tasks`, `/narrative-outline`, `/narrative-draft`, `/narrative-revise`, `/narrative-verify`, `/narrative-archive`, `/narrative-idea`) siguen existiendo como subsistema CLI del stack de desarrollo, gestionado por Hermes Agent (skills en `src/skills/narrative-*` y `skills/`). No requieren instalación adicional: `bash install.sh --with-cli-stack` prepara ese stack opcional. Se usan desde Hermes, no desde la app web.