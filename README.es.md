# Demiurgos

**Plataforma web de lore y worldbuilding, freeware propietario y agnóstica de mundo.** Demiurgos es una aplicación web full-stack — frontend React, backend FastAPI, grafo de entidades, memoria persistente y asistente de IA — que gestiona cualquier mundo ficticio que cargues en **formato OKF** (Markdown + frontmatter YAML). Nunca se acopla a un único universo: **Vibrantes** es un mundo de ejemplo, no un requisito.

> 🚧 **Estado:** En desarrollo activo (beta). El Core es gratuito; los talleres de pago son opcionales y de compra única. El código fuente **no** se distribuye públicamente por defecto.

---

## Inicio rápido

### 1. Requisitos previos

| Componente | Propósito |
|-----------|-----------|
| Python 3.11+ | API backend (`uvicorn api_server:app`) |
| Node.js 18+ y npm | Frontend (Vite) |
| CLI de [Hermes Agent](https://hermes-agent.nousresearch.com) | Proveedor conversacional (asistente y gateway en el puerto 8642) |
| `git` | Clonar el repositorio |

> `install.sh` es el **bootstrap de la app web** en un solo comando: sin flags instala la aplicación web de Demiurgos (delegando en `scripts/install-demiurgos.sh`, descargado del canal de releases). El stack **CLI de desarrollo** opcional (Hermes Agent, [Engram](https://github.com/Gentleman-Programming/engram) como memoria persistente y las skills narrativas) es opt-in: `bash install.sh --with-cli-stack` (o `DEMIURGOS_WITH_CLI_STACK=1`). No es necesario para usar la app web.

### 2. Instalación

**Instalación en un solo comando** — el canal público de releases firmado ya está activo. Linux / macOS:

```bash
curl -fsSL https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.sh | bash
```

Windows (PowerShell):

```powershell
irm https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.ps1 | iex
```

Instala la app web en `~/.demiurgos` (`%LOCALAPPDATA%\Demiurgos` en Windows); arráncala con `~/.demiurgos/current/scripts/start-demiurgos.sh start` (ver [docs/install/ONE_SCREEN_GUIDE.md](docs/install/ONE_SCREEN_GUIDE.md)). El instalador verifica una firma minisign y los checksums SHA256; no hay actualización automática ni firma de código paga, así que es esperable una advertencia de seguridad la primera vez.

**Desde el código fuente (contribuidores):** clonar, `venv`, `npm install` y lanzar con los launchers de abajo.

```bash
git clone https://github.com/maar1223/Demiurgos.git
cd Demiurgos

# Backend
python3 -m venv .venv
.venv/bin/pip install -r src/tools/demiurgos-suite/requirements.txt

# Frontend
cd frontend && npm install && cd ..
```

### 3. Arranque

| Plataforma | Comando | Inicia |
|----------|---------|--------|
| **Linux / macOS** | `./scripts/start-demiurgos-linux.sh start` | Gateway de Hermes (8642), API de la wiki (8000), Frontend (5173) |
| **Windows** | `powershell -ExecutionPolicy Bypass -File start-demiurgos.ps1` | El mismo stack + warm-up del grafo |

El launcher abre la app en **http://127.0.0.1:5173** (health de la API: `http://127.0.0.1:8000/health`). Es idempotente: ejecutarlo dos veces nunca duplica procesos. Otras acciones: `restart`, `stop` e `install` (acceso de escritorio en Linux). En Windows también puedes arrancar solo la API con `start-api.ps1`.

**VPS:** el mismo stack funciona en un servidor. La cookie de sesión es **scheme-aware**: las peticiones HTTPS reciben una cookie `Secure`; HTTP plano (un VPS sin TLS) no — el inicio de sesión funciona en cualquier plataforma sin configuración.

### 4. Primer arranque

La primera ejecución muestra el flujo de **onboarding**: elige el idioma de la UI, configura los proveedores LLM y **crea un mundo nuevo o importa uno existente**. Las instalaciones existentes nunca vuelven a pasar por el onboarding.

---

## Cómo funciona

```
┌─────────────────────────────────────────────────────────────────┐
│                      PLATAFORMA DEMIURGOS                        │
│                                                                 │
│  ┌──────────────┐   ┌──────────────────────────┐   ┌─────────┐  │
│  │  FRONTEND    │──▶│     BACKEND API          │──▶│ALMACEN. │  │
│  │  React/Vite  │   │  FastAPI api_server.py   │   │mundos/  │  │
│  │  wiki,       │◀──│  auth · wiki · asistente │◀──│ + .pa-  │  │
│  │  editor,     │   │  guiado · grafo · ideas  │   │ pelera  │  │
│  │  talleres    │   └───────────┬──────────────┘   └─────────┘  │
│  └──────────────┘               │                               │
│        ▲                        ▼                               │
│        │               ┌──────────────────┐                     │
│        │               │  GRAFO ENTIDADES │                     │
│        │               │  graph_indexer   │                     │
│        │               │  servidor MCP    │                     │
│        │               │  (15 tools)      │                     │
│        │               └────────┬─────────┘                     │
│        │                        ▼                               │
│        └───────────  HERMES (proveedor conversacional) ──► ENGRAM│
│   UI ◀── SSE ◀────   gate semántico · runs adapter   (memoria   │
│   (asistente)                                             persistente)│
└─────────────────────────────────────────────────────────────────┘
```

- **Los mundos son datos, no código.** Cada mundo vive bajo `mundos/{mundo}/` en OKF (`lore/`, `personajes/`, `sagas/`, …). Ningún código de la plataforma se acopla a un universo concreto.
- **El grafo es la fuente de verdad para leer** entidades; el filesystem solo se escribe a través de rutas de API con compuertas.
- **Nada persiste sin tu aprobación.** Las propuestas de IA son diskless hasta que confirmas un diff (digest SHA-256 + token de un solo uso) — canon-safety por construcción.
- **Engram** es la capa de memoria persistente obligatoria; **Hermes** es un proveedor conversacional intercambiable, no la plataforma.

---

## Funcionalidades

| Función | Qué hace | Dónde |
|---------|----------|-------|
| **Wiki y editor** | CRUD con compuertas (`create`/`save`/`restore`), vista de diff dividida, snapshots de historial, estados OKF (`draft`/`stable`), árbol de archivos drag-and-drop, edición de frontmatter | `/wiki/:mundo`, `/wiki/:mundo/:section/*` |
| **Grafo de entidades** | Entidades, enlaces y backlinks derivados de OKF; búsqueda BM25; resolución de referencias | `/wiki/:mundo/entity/*`, `RelacionesCanon` |
| **Importador de mundos** | `.md` / `.docx` / `.pdf` y **exportaciones de Notion** → Markdown limpio, frontmatter OKF automático, clasificador de secciones, ciclo revisar → aprobar → ejecutar, rollback | `/wiki/:mundo/importer` |
| **Asistente de IA** | Chat + streaming SSE (`ai/ask`), gate de intención semántica, sugerencias de edición (`ai/edit-suggest`); nombre visible: **Asistente de Demiurgos** | Barra lateral del asistente |
| **Creación guiada de personajes** | Protocolo `guided-character-v1` (confirmación → conversación → revisión → finalización), propuestas diskless, sesiones durables | Taller de Mundo |
| **Ideas (Taller de Ideas)** | Banco de ideas agnóstico de mundo con versiones y media; captura de ideas por Telegram | `/ideas`, Integraciones → Captura de ideas |
| **Biblioteca de metodologías y talleres** | Metodologías creativas editables por el Autor (compilar, confianza, cuarentena), skills que se añaden al chat y método del asistente elegido al iniciar la sesión, talleres del Core | `/taller-herramientas`, `/taller-mundo` |
| **Bóveda de cuenta** | Cuenta local única, contraseña opcional, palabras de recuperación EFF — **100 % offline**, sin secretos en `.env` | `/perfil` → Seguridad / Bóveda |
| **Papelera** | `.papelera` por ficha **y** papelera a nivel de mundo, ambas con retención TTL de **30 días** | Editor, Perfil → Mundos |

### Importador de mundos

La importación corre como pipeline de trabajos: **subir → stream → analizar → revisar → aprobar → ejecutar** (con `cancel` / `resume` / `rollback`). Fuentes: Markdown, Word (`.docx`), PDF y exportaciones de Notion (páginas Markdown + bases CSV planas con renombrado UUID, reescritura de wikilinks y deduplicación de media). Antes de sobrescribir un ficha existente, sus bytes previos se guardan como snapshot en `.papelera` para recuperación a 30 días. Los trabajos de importación se persisten en SQLite (`data/import-jobs.sqlite3`).

### Bóveda de cuenta (nueva — reemplaza a Google sign-in)

Demiurgos ya no depende de Google OAuth. La bóveda es una **cuenta local única**:

- **Nombre de usuario** + **contraseña opcional** (almacenada solo como hash **Argon2id**).
- **Palabras de recuperación EFF** (8–10 palabras de la wordlist larga de EFF, ≈104–130 bits de entropía) como **llave de propiedad y recuperación** — también almacenadas solo como hash.
- La verificación es **100 % offline** (cero imports HTTP), con rate limiting en memoria y backoff exponencial; la wordlist se rota de forma atómica.
- La cuenta vive en un registro de estado local, **no** en `.env` — no se necesita un archivo de secretos para la bóveda.

Actívala con `DEMIURGOS_AUTH_MODE=credentials` (ver Configuración). Sesión: cookie HttpOnly, mismo origen, flag `Secure` scheme-aware, **recordatorio suave de re-autenticación a los 14 días** (por defecto), TTL de sesión de 8 h y "recordarme" opcional por 30 días. Sin bóveda, el modo ligero `local-dev` ofrece una sesión de un clic para desarrollo en loopback.

---

## Requisitos

| Capa | Stack |
|-------|-------|
| Frontend | React 18, Vite 5, TypeScript 5, Tailwind CSS 3, Vitest 2 + Testing Library, SWR, react-router-dom, react-markdown, @xyflow/react |
| Backend | Python 3.11+ (probado en 3.12), FastAPI, uvicorn, `mcp`, `rank_bm25`, `watchdog`, `Pillow`, `markitdown[docx]` + `lxml`, `argon2-cffi` |
| Almacenamiento | Archivos OKF en `mundos/{mundo}/`; SQLite en `data/` (sesiones guiadas, memoria de conversación, ideas, trabajos de importación); papelera `.papelera` (TTL 30 días) |
| Memoria | Engram (MCP) — obligatoria para la co-creación; worker `engram_sync` |
| Proveedor de IA | Hermes (gateway en el puerto 8642) vía runs adapter + gate semántico; agnóstico de proveedor (`DEMIURGOS_TEXT_*` / `DEMIURGOS_VISION_*`) |

---

## Configuración

La configuración es opcional y por variables de entorno — **la bóveda no requiere `.env`**. Copia `.env.example` a `.env` y descomenta lo que necesites:

| Variable | Por defecto | Propósito |
|----------|---------|-----------|
| `DEMIURGOS_AUTH_MODE` | *(desactivado)* | `local-dev` (sesión de un clic) o `credentials` (bóveda de cuenta) |
| `DEMIURGOS_REAUTH_INTERVAL_D` | `14` | Intervalo del recordatorio de re-autenticación (días) |
| `DEMIURGOS_SESSION_TTL_H` / `DEMIURGOS_REMEMBER_ME_TTL_D` | `8` / `30` | TTL de sesión y duración de "recordarme" |
| `DEMIURGOS_TEXT_PROVIDER/ENDPOINT/MODEL` | opencode-go | LLM de texto (asistente, enriquecimiento de importación) |
| `DEMIURGOS_VISION_PROVIDER/ENDPOINT/MODEL` | opencode-go | LLM de visión (análisis de imágenes) |
| `DEMIURGOS_LANGUAGE` | `es` | Idioma de la UI |
| `TELEGRAM_BOT_TOKEN` / `GOOGLE_SHEETS_ID` | — | Captura de ideas por Telegram / sync opcionales |
| `GOOGLE_API_KEY` | — | Generación de imágenes opcional |

---

## Desarrollo

```bash
# Tests del backend
pytest tests/                    # o un archivo: pytest tests/test_x.py

# Frontend
cd frontend
npm test                         # vitest (ejecución única)
npm run typecheck                # tsc --noEmit
npm run build                    # tsc + vite build
```

Servidores de desarrollo (ya gestionados por los launchers): Vite hace proxy de `/api` a `http://localhost:8000`.

Módulos de backend útiles (bajo `src/tools/demiurgos-suite/wiki/`): `api_server.py` (rutas), `account.py` / `emergency_key.py` (bóveda), `graph_indexer.py` / `graph_mcp_server.py` (grafo), `import_*.py` (importador de mundos), `world_recycle_bin.py` (papelera), `guided_character_*.py` (creación guiada), `semantic_intent.py` (gate del asistente). Las decisiones de producto viven en `docs/architecture/demiurgos-platform.md` (la constitución de la plataforma).

---

## Modelo de producto

- **Freeware propietario** — el Core es gratuito; los talleres opcionales son de **compra única** (activación por plataforma: 1 Windows + 1 macOS + 1 Linux + 1 servidor/VPS, con transferencia).
- **La versión instalada nunca se bloquea** — la caducidad de la ventana de actualizaciones nunca desactiva ni degrada lo que ya tienes.
- **Los mundos son privados** — el contenido bajo `mundos/` está en `.gitignore` y nunca se distribuye con el repositorio.
- Creado por [@maar1223](https://github.com/maar1223).

---

*"No asumir nada. Si tienes dudas, busca el contexto en el proyecto."*