# Demiurgos

**Hermes-powered narrative engine.** Create, index, and write stories with AI — while maintaining canon coherence and continuity across arcs.

> 🚧 **Status:** In active development. Public beta coming soon.

---

## What is Demiurgos?

Demiurgos is an open-source narrative engine that runs on **Hermes Agent**. It brings structured creative writing to AI-assisted storytelling:

- **13 narrative phases** — from world-building to final archive
- **Intent-driven** — speak naturally, the orchestrator routes to the right phase
- **Canon protection** — lore is sacred, contradictions are flagged before they reach the page
- **Persistent memory** — Engram ensures no idea or decision is lost between sessions
- **World-agnostic** — works with any fictional universe you create

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
DEMIURGOS_TEXT_MODEL=deepseek-v4-flash
DEMIURGOS_TEXT_API_KEY_ENV=OPENCODE_GO_API_KEY

# Vision (image analysis, generation)
DEMIURGOS_VISION_PROVIDER=opencode-go
DEMIURGOS_VISION_ENDPOINT=https://opencode.ai/zen/go/v1
DEMIURGOS_VISION_MODEL=qwen3.6-plus
DEMIURGOS_VISION_API_KEY_ENV=OPENCODE_GO_API_KEY
```

Add any provider: OpenAI, Google Gemini, Groq, etc. — just change the
endpoint, model, and API key env var name. All Demiurgos components
(sync_lore, drafts, image gen) read from the same convention.

---

## Architecture

```
Demiurgos/
├── AGENTS.md              ← Orchestrator system prompt
├── skills/                ← 13 Hermes-compatible SKILL.md
│   ├── narrative-init/
│   ├── narrative-explore/
│   ├── narrative-propose/
│   └── ...
├── mundos/arquetipos-narrativos/     ← Universal narrative catalogs
├── src/tools/sync_lore/     ← Lore indexing pipeline (35 tests)
├── src/tools/sync-ideas.py ← Idea bank sync (Telegram → Sheets)
├── scripts/               ← Utility scripts
└── install.sh             ← One-command installer
```

---

## Development

Demiurgos is built as a **Hermes skill tap** — skills are loaded via `skills.external_dirs` in Hermes' config. The orchestrator lives in `AGENTS.md` and is loaded as Hermes' system prompt when the user opens their world directory.

- **Stack:** Hermes Agent + Engram MCP + Python (sync tools)
- **License:** MIT
- **Built by:** [@maar1223](https://github.com/maar1223)

---

*"No asumir nada. Si tienes dudas, busca el contexto en el proyecto."*
