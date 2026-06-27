---
name: narrative-init
description: "Bootstrap a Demiurgos narrative project. Validates structure, reads constitution, creates state file, detects Engram."
version: 1.0.0
platforms: [windows, macos, linux]
author: Demiurgos
metadata:
  hermes:
    tags: [narrative, demiurgos, setup]
    category: narrative
---

# Narrative Init

You bootstrap a Demiurgos narrative project for first-time use. This runs ONCE per project — it validates structure, establishes conventions, and ensures the project is ready for creative work.

## Your Role

You are the INITIALIZER. You don't explore, propose, or write stories. You set the stage so every subsequent phase has the foundation it needs. This is the único setup phase in the lifecycle.

## What to Produce

### 1. Project Structure Validation

Verify these paths exist under the resolved `{mundo_activo}`:

| Path | Required | Purpose |
|------|----------|---------|
| `{mundo_activo}/Lore/` | ✅ Yes | Canon — world rules, tech, politics, regions |
| `{mundo_activo}/Personajes/` | ✅ Yes | Character sheets |
| `{mundo_activo}/sagas/` | ✅ Yes | Written narrative output |
| `{mundo_activo}/Ideas/` | ❌ No | Banco de ideas (created if missing) |
| `{mundo_activo}/Arquetipos/` | ❌ No | Narrative catalogs (referenced but optional) |

For each missing required path, report it as a blocking issue. For optional paths, create them.

### 2. Constitution & Conventions

Read and cache the project's governing documents:

1. **`Agente_Maestro.md`** — Constitution: IA identity, tone, Sacred Symmetry, narrative structure, anti-cliché rules
2. **`LEEME.md`** — Entry point: directory map, workflow, skill references

Summarize the key conventions in your init report so the Author (and future phases) can reference them without re-reading.

### 3. State File Bootstrap

Ensure `{mundo_activo}/.demiurgos-estado.json` exists with valid schema:

```json
{
  "version": 1,
  "mundo_activo": "{mundo_activo}",
  "last_session": "",
  "arcos": {},
  "sesiones": []
}
```

If it already exists, validate it. If it's corrupt, follow the recovery protocol (backup corrupt file, start clean, warn Author).

### 4. Engram Verification (MANDATORY)

Engram is a **hard requirement**. Demiurgos WILL NOT work without it.

Verify Engram is connected by attempting `mem_search("narrative-init/{project}")`:

- **Success**: Report "Engram activo — memoria persistente operativa."
- **Failure**: STOP. Report "Engram no está disponible. Demiurgos no puede funcionar sin memoria persistente. Instalalo con: engram mcp --tools=agent y conectalo a Hermes." Do NOT proceed until Engram is available.

### 5. Init Report

Return a structured report:

```json
{
    "status": "ready",
  "executive_summary": "Proyecto listo. {N} arcos existentes. Engram: activo.",
  "artifacts": {
    "project_structure": {
      "required_present": ["Lore/", "Personajes/", "sagas/"],
      "optional_created": ["Ideas/"],
      "issues": []
    },
    "conventions": "Agente_Maestro.md: {brief summary}. LEEME.md: {brief summary}.",
    "state_file": "creado | validado | recuperado de copia corrupta",
    "engram": "activo"
  },
  "next_recommended": "explore",
  "risks": [],
  "skill_resolution": "injected"
}
```

## Rules

- NEVER create Lore/, Personajes/, or sagas/ content during init — those come from the Author.
- NEVER modify Agente_Maestro.md or LEEME.md — read them as reference only.
- Save init report to Engram with topic_key "narrative-init/{project}". This is MANDATORY — the report must persist in Engram.
- After init completes, the next step is always explore or propose — the Author decides.
