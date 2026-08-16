# Demiurgos

**Proprietary freeware lore & worldbuilding platform.** A complete, world-agnostic web app for any world in OKF format — lore storage, graph, indexing, workflows, and UI — with AI-assisted, canon-safe storytelling built in.

> 🚧 **Status:** In active development. Public beta coming soon.

---

## What is Demiurgos?

Demiurgos is a complete, proprietary freeware lore/worldbuilding **web platform**. It owns the full stack — frontend, backend, Hermes, storage, graph, indexing, workflows, and UI — and manages any world you load in **OKF format**, independent of any single fictional universe. AI-assisted narrative writing is a managed capability of the platform, not the whole product. The Core is completely free; additional workshops are purchased once, with community discounts distributed manually or through future automation. Source code and official release artifacts are not public by default:

- **13 narrative phases** — a managed skill subsystem from world-building to final archive
- **Intent-driven** — speak naturally, the orchestrator routes to the right phase
- **Canon protection** — lore is sacred, contradictions are flagged before they reach the page
- **Persistent memory** — Engram ensures no idea or decision is lost between sessions
- **World-agnostic (OKF)** — works with any fictional universe you load
- **Hermes is one component** — the conversational provider, not the platform itself

---

## Quick Install

```bash
curl -fsSL https://get.demiurgos.dev | bash
```

The installer handles everything: Hermes Agent, Engram memory, Demiurgos skills, and world setup. Two flows available:

- **[1] Create a new world** — from scratch, with narrative catalogs included
- **[2] Load an existing world** — scan your lore files, index with AI, ready to write

---

## How It Works

The narrative skill subsystem runs inside the platform — the web UI, backend API, entity graph, and indexing services provide the world context it reads from. The narrative flow looks like this:

```
You speak naturally
        │
        ▼
┌─────────────────────┐
│  AGENTS.md           │  ← Orchestrator (system prompt)
│  Intent recognition  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  /narrative-explore  │  ← Hermes skills (progressive disclosure)
│  /narrative-propose  │
│  /narrative-design   │
│  /narrative-draft    │
│  ... (13 phases)     │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Engram MCP          │  ← Persistent memory
│  mem_save/search     │
└─────────────────────┘
```

The full platform also includes the web UI, backend API, entity graph, and lore indexing — the diagram above shows the managed narrative subsystem inside it, with Hermes acting as one conversational provider.

---

## Requirements

| Component | Purpose | Auto-installed? |
|-----------|---------|----------------|
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | AI runtime | ✅ Yes |
| [Engram](https://github.com/Gentleman-Programming/engram) | Persistent memory | ✅ Yes |
| Python 3.11+ | Lore indexing (optional) | ❌ Manual |

## Provider Configuration

Demiurgos uses a unified provider system. Two independent configurations
for text and vision, each with their own model, endpoint, and API key:

```env
# Text (entity extraction, story writing)
DEMIURGOS_TEXT_PROVIDER=opencode-go
DEMIURGOS_TEXT_ENDPOINT=https://opencode.ai/zen/go/v1
DEMIURGOS_TEXT_MODEL=gpt-5.6-luna
DEMIURGOS_TEXT_API_KEY_ENV=OPENCODE_GO_API_KEY

# Vision (image analysis, generation)
DEMIURGOS_VISION_PROVIDER=opencode-go
DEMIURGOS_VISION_ENDPOINT=https://opencode.ai/zen/go/v1
DEMIURGOS_VISION_MODEL=gpt-5.6-luna
DEMIURGOS_VISION_API_KEY_ENV=OPENCODE_GO_API_KEY
```

Add any provider: OpenAI, Google Gemini, Groq, etc. — just change the
endpoint, model, and API key env var name. All Demiurgos components
(sync_lore, drafts, image gen) read from the same convention.

---

## Architecture

```
Demiurgos/
├── frontend/                    ← Web UI (wiki, editor, guided creation, assistant)
├── src/tools/demiurgos-suite/   ← Backend API: graph, sessions, gates, indexing
├── AGENTS.md              ← Orchestrator system prompt (narrative role)
├── skills/                ← Managed narrative skill subsystem (14 SKILL.md)
│   ├── narrative-init/
│   ├── narrative-explore/
│   ├── narrative-propose/
│   └── ...
├── plantillas/                       ← Universal narrative catalogs
├── src/tools/sync_lore/     ← Lore indexing pipeline (35 tests)
├── src/tools/idea_capture/ ← Native Hermes idea capture (legacy sync is archived/retired)
├── scripts/               ← Utility scripts
└── install.sh             ← One-command installer
```

---

## Development

The **narrative subsystem** is delivered as a **Hermes skill tap** — skills are loaded via `skills.external_dirs` in Hermes' config. The orchestrator lives in `AGENTS.md` and is loaded as Hermes' system prompt when the user opens their world directory. Hermes is one component/provider of the platform, not the platform itself.

- **Stack:** Web frontend + backend API + Hermes Agent + Engram MCP + Python (sync/index tools)
- **Product model:** Proprietary freeware with free and paid tiers
- **Built by:** [@maar1223](https://github.com/maar1223)

---

*"No asumir nada. Si tienes dudas, busca el contexto en el proyecto."*
