# Demiurgos

**Proprietary freeware, world-agnostic lore & worldbuilding web platform.** Demiurgos is a full-stack web app — React frontend, FastAPI backend, entity graph, persistent memory, and an AI assistant — that manages any fictional world you load in **OKF format** (Markdown + YAML frontmatter). It never couples to a single universe: **Vibrantes** is an example world, not a requirement.

> 🚧 **Status:** In active development (beta). The Core is free; paid workshops are an optional, one-time purchase. Source code is **not** distributed publicly by default.

---

## Quick start

### 1. Prerequisites

| Component | Purpose |
|-----------|---------|
| Python 3.11+ | Backend API (`uvicorn api_server:app`) |
| Node.js 18+ & npm | Frontend (Vite) |
| [Hermes Agent](https://hermes-agent.nousresearch.com) CLI | Conversational provider (assistant + gateway on port 8642) |
| `git` | Cloning the repository |

> `install.sh` is the one-command **web-app bootstrap**: with no flags it installs the Demiurgos web app (delegating to `scripts/install-demiurgos.sh`, fetched from the release channel). The optional **dev-CLI stack** (Hermes Agent, [Engram](https://github.com/Gentleman-Programming/engram) persistent memory, and the narrative skills) is opt-in: `bash install.sh --with-cli-stack` (or `DEMIURGOS_WITH_CLI_STACK=1`). It is not required to run the web app.

### 2. Install

**One-command install** — the signed public release channel is live. Linux / macOS:

```bash
curl -fsSL https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.sh | bash
```

Windows (PowerShell):

```powershell
irm https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.ps1 | iex
```

This installs the web app under `~/.demiurgos` (`%LOCALAPPDATA%\Demiurgos` on Windows); launch it with `~/.demiurgos/current/scripts/start-demiurgos.sh start` (see [docs/install/ONE_SCREEN_GUIDE.md](docs/install/ONE_SCREEN_GUIDE.md)). The installer verifies a minisign signature and SHA256 checksums; there is no auto-update and no paid code signing, so a first-run security warning is expected.

**From source (contributors):** clone, `venv`, `npm install`, and launch with the launchers below.

```bash
git clone https://github.com/maar1223/Demiurgos.git
cd Demiurgos

# Backend
python3 -m venv .venv
.venv/bin/pip install -r src/tools/demiurgos-suite/requirements.txt

# Frontend
cd frontend && npm install && cd ..
```

### 3. Launch

| Platform | Command | Starts |
|----------|---------|--------|
| **Linux / macOS** | `./scripts/start-demiurgos.sh start` | Hermes Gateway (8642), API + SPA (8000) |
| **Windows** | `powershell -ExecutionPolicy Bypass -File start-demiurgos.ps1` | Same stack + graph warm-up |

The launcher opens the app at **http://127.0.0.1:8000** (health check: `http://127.0.0.1:8000/health`). It is idempotent — running it twice never spawns duplicate processes. Other actions: `restart`, `stop`, and `install`. On Linux the installer already adds Demiurgos to the applications menu and `install` rewrites that entry; `install --desktop` also drops a launcher icon in your desktop folder. On Windows you can also start just the API with `start-api.ps1`.

**VPS:** the same stack runs on a server. The session cookie is **scheme-aware**: HTTPS requests get a `Secure` cookie, plain HTTP (a VPS without TLS) does not — login works on any platform with zero configuration.

### 4. First run

The first launch shows the **onboarding** flow: pick your UI language, configure the LLM providers, and **create a new world or import an existing one**. Existing installations are never forced back into onboarding.

---

## How it works

```
┌─────────────────────────────────────────────────────────────────┐
│                        DEMIURGOS PLATFORM                        │
│                                                                 │
│  ┌──────────────┐   ┌──────────────────────────┐   ┌─────────┐  │
│  │  FRONTEND    │──▶│     BACKEND API          │──▶│ STORAGE │  │
│  │  React/Vite  │   │  FastAPI api_server.py   │   │mundos/  │  │
│  │  wiki,       │◀──│  auth · wiki · assistant │◀──│ + .pa-  │  │
│  │  editor,     │   │  guided · graph · ideas  │   │ pelera  │  │
│  │  workshops   │   └───────────┬──────────────┘   └─────────┘  │
│  └──────────────┘               │                               │
│        ▲                        ▼                               │
│        │               ┌──────────────────┐                     │
│        │               │  ENTITY GRAPH    │                     │
│        │               │  graph_indexer   │                     │
│        │               │  MCP server      │                     │
│        │               │  (15 tools)      │                     │
│        │               └────────┬─────────┘                     │
│        │                        ▼                               │
│        └───────────  HERMES (conversational provider) ──► ENGRAM│
│   UI ◀── SSE ◀────   semantic gate · runs adapter   (persistent │
│   (assistant)                                            memory)│
└─────────────────────────────────────────────────────────────────┘
```

- **Worlds are data, not code.** Every world lives under `mundos/{mundo}/` in OKF (`lore/`, `personajes/`, `sagas/`, …). No platform code is coupled to a specific universe.
- **The graph is the read source of truth** for entities; the filesystem is only written through gated API routes.
- **Nothing persists without your approval.** AI proposals are diskless until you confirm a diff (SHA-256 digest + one-time token) — canon-safety by construction.
- **Engram** is the mandatory persistent memory layer; **Hermes** is one interchangeable conversational provider, not the platform.

---

## Features

| Feature | What it does | Where |
|---------|--------------|-------|
| **Wiki & editor** | Gated CRUD (`create`/`save`/`restore`), split diff preview, history snapshots, OKF states (`draft`/`stable`), drag-and-drop file tree, frontmatter editing | `/wiki/:mundo`, `/wiki/:mundo/:section/*` |
| **Entity graph** | Entities, links and backlinks derived from OKF; BM25 search; reference resolution | `/wiki/:mundo/entity/*`, `RelacionesCanon` |
| **World importer** | `.md` / `.docx` / `.pdf` and **Notion exports** → clean Markdown, automatic OKF frontmatter, section classifier, review → approve → execute lifecycle, rollback | `/wiki/:mundo/importer` |
| **AI assistant** | Chat + SSE streaming (`ai/ask`), semantic-intent gate, edit suggestions (`ai/edit-suggest`); visible name: **Asistente de Demiurgos** | Assistant sidebar |
| **Guided character creation** | Protocol `guided-character-v1` (confirmation → conversation → review → complete), diskless proposals, durable sessions | Taller de Mundo |
| **Ideas (Taller de Ideas)** | World-agnostic idea bank with versions and media; Telegram idea capture | `/ideas`, Integraciones → Captura de ideas |
| **Methodology library & workshops** | Author-editable creative methodologies (compile, trust, quarantine), Core workshops | `/taller-herramientas`, `/taller-mundo` |
| **Account vault** | Single local account, optional password, EFF recovery words — **100% offline**, no `.env` secrets | `/perfil` → Seguridad / Bóveda |
| **Trash (papelera)** | Per-file `.papelera` **and** world-level recycle bin, both with a **30-day** retention TTL | Editor, Profile → Mundos |

### World importer

Import runs as a job pipeline: **upload → stream → analyze → review → approve → execute** (with `cancel` / `resume` / `rollback`). Sources: Markdown, Word (`.docx`), PDF, and Notion exports (Markdown pages + flat CSV databases with UUID renaming, wikilink rewriting and media deduplication). Before overwriting an existing file, the prior bytes are snapshotted into `.papelera` for 30-day recovery. Import jobs are persisted in SQLite (`data/import-jobs.sqlite3`).

### Account vault (new — replaces Google sign-in)

Demiurgos no longer depends on Google OAuth. The vault is a **single local account**:

- **Username** + **optional password** (stored only as an **Argon2id** hash).
- **EFF recovery words** (8–10 words from the EFF long wordlist, ≈104–130 bits of entropy) are the **ownership & recovery key** — also stored only as a hash.
- Verification is **100% offline** (zero HTTP imports), with in-memory rate limiting and exponential backoff; the word list is rotated atomically.
- The account lives in a local state registry, **not** in `.env` — no secrets file required for the vault.

Enable it with `DEMIURGOS_AUTH_MODE=credentials` (see Configuration). Session: HttpOnly cookie, same-origin, scheme-aware `Secure` flag, **soft re-auth reminder after 14 days** (default), session TTL 8 h, optional "remember me" for 30 days. Without a vault, the lighter `local-dev` mode provides a one-click session cookie for loopback development.

---

## Requirements

| Layer | Stack |
|-------|-------|
| Frontend | React 18, Vite 5, TypeScript 5, Tailwind CSS 3, Vitest 2 + Testing Library, SWR, react-router-dom, react-markdown, @xyflow/react |
| Backend | Python 3.11+ (tested on 3.12), FastAPI, uvicorn, `mcp`, `rank_bm25`, `watchdog`, `Pillow`, `markitdown[docx]` + `lxml`, `argon2-cffi` |
| Storage | OKF files in `mundos/{mundo}/`; SQLite in `data/` (guided sessions, conversation memory, ideas, import jobs); `.papelera` trash (30-day TTL) |
| Memory | Engram (MCP) — mandatory for co-creation; `engram_sync` worker |
| AI provider | Hermes (gateway port 8642) via runs adapter + semantic gate; provider-agnostic (`DEMIURGOS_TEXT_*` / `DEMIURGOS_VISION_*`) |

---

## Configuration

Configuration is optional and environment-based — **no `.env` is required for the vault**. Copy `.env.example` to `.env` and uncomment what you need:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEMIURGOS_AUTH_MODE` | *(disabled)* | `local-dev` (one-click session) or `credentials` (account vault) |
| `DEMIURGOS_REAUTH_INTERVAL_D` | `14` | Soft re-auth reminder interval (days) |
| `DEMIURGOS_SESSION_TTL_H` / `DEMIURGOS_REMEMBER_ME_TTL_D` | `8` / `30` | Session TTL and "remember me" duration |
| `DEMIURGOS_TEXT_PROVIDER/ENDPOINT/MODEL` | opencode-go | Text LLM (assistant, import enrichment) |
| `DEMIURGOS_VISION_PROVIDER/ENDPOINT/MODEL` | opencode-go | Vision LLM (image analysis) |
| `DEMIURGOS_LANGUAGE` | `es` | UI language |
| `TELEGRAM_BOT_TOKEN` / `GOOGLE_SHEETS_ID` | — | Optional Telegram idea capture / sync |
| `GOOGLE_API_KEY` | — | Optional image generation |

---

## Development

```bash
# Backend tests
pytest tests/                    # or a single file: pytest tests/test_x.py

# Frontend
cd frontend
npm test                         # vitest (single run)
npm run typecheck                # tsc --noEmit
npm run build                    # tsc + vite build
```

Dev servers (already handled by the launchers): Vite proxies `/api` to `http://localhost:8000`.

Useful backend modules (under `src/tools/demiurgos-suite/wiki/`): `api_server.py` (routes), `account.py` / `emergency_key.py` (vault), `graph_indexer.py` / `graph_mcp_server.py` (graph), `import_*.py` (world importer), `world_recycle_bin.py` (trash), `guided_character_*.py` (guided creation), `semantic_intent.py` (assistant gate). Product decisions live in `docs/architecture/demiurgos-platform.md` (the platform constitution).

---

## Product model

- **Proprietary freeware** — the Core is free; optional workshops are a **one-time purchase** (per-platform activation: 1 Windows + 1 macOS + 1 Linux + 1 server/VPS, transferable).
- **The installed version never gets blocked** — an expired update window never disables or degrades what you already have.
- **Worlds are private** — world content under `mundos/` is gitignored and never shipped with the repo.
- Built by [@maar1223](https://github.com/maar1223).

---

*"No asumir nada. Si tienes dudas, busca el contexto en el proyecto."*