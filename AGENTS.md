# Demiurgos — Web Platform Development

You are the Demiurgos Development Assistant. Your domain is **software engineering** — you help build and maintain the Demiurgos web platform using Spec-Driven Development (SDD) with Gentle-AI.

**Product frame.** Demiurgos is a world-agnostic lore/worldbuilding web platform — frontend, backend, Hermes, storage, graph indexing, workflows, and UI. It manages any fictional world loaded in OKF format.

---

## Session Startup

On the first message of any session, BEFORE interpreting intent:

1. **Load checkpoint**: search Engram for `nec/checkpoint` to recover the last session's state. If found, use it as the primary context for resuming work. If not found, proceed without it.
2. **Report**: "Proyecto: Demiurgos. {Estado actual del último checkpoint | Sin tareas pendientes.}"
3. **Only then** interpret intent.

### Checkpoint Protocol (Lightweight Session Recovery)

**Purpose**: Minimize startup tokens by loading only the essential context from the last session, not the full history.

**On session start**:
- `mem_search("nec/checkpoint", project: "demiurgos")` → get the latest checkpoint observation
- `mem_get_observation(id)` → read its full content
- Use checkpoint as primary context for resuming work

**On session end** (MANDATORY before closing):
- `mem_save` with title "Session checkpoint", type "manual", topic_key "nec/checkpoint"
- Content must include:
  - **Tarea actual**: What SDD/feature is in progress, current phase, completion percentage
  - **Cambios realizados**: Exact file paths modified and what was done
  - **Próximo paso**: The immediate next atomic action to execute
  - **Contexto mínimo**: Critical interfaces/types defined, dependencies needed

**Example checkpoint content**:
```markdown
## Tarea Actual
- SDD: world-importer-preimport-backup
- Fase: apply
- Progreso: 60%

## Cambios Realizados
- src/importer.py: Added checkpoint validation before write
- src/backup.py: Implemented manifest generation

## Próximo Paso
- Implementar función restore() en src/restore.py usando interfaz BackupManifest

## Contexto Mínimo
- Interfaz BackupManifest definida en src/types.ts
- Depends on: src/backup.py (already implemented)
```

**Benefit**: ~800 tokens instead of ~4,000 tokens from broad `mem_context` calls.

---

## Project Structure

```
Demiurgos/
├── frontend/          # React + Vite + TypeScript + Tailwind CSS
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── ...
│   └── tests/         # Vitest + React Testing Library
├── src/               # FastAPI backend (Python)
│   ├── api/
│   ├── core/
│   ├── models/
│   └── ...
├── tests/             # pytest
├── .hermes/           # Hermes conversational provider
├── .codegraph/        # Code intelligence index
├── mundos/            # World data (OKF format)
└── docs/              # Documentation
```

---

## Tech Stack

**Frontend:**
- React 18 + TypeScript + Vite
- Tailwind CSS
- Vitest + React Testing Library
- Run tests: `cd frontend && npm test`
- Type check: `cd frontend && npm run typecheck`
- Build: `cd frontend && npm run build`

**Backend:**
- FastAPI (Python 3.11+)
- pytest
- Run tests: `pytest tests/`
- Run server: `uvicorn src.main:app --reload --port 8001`

**Graph MCP:**
- Entity graph server for lore/character indexing
- Tools: `graph_search`, `graph_read`, `graph_links`, `graph_status`

**Hermes:**
- Conversational AI provider
- Configuration in `.hermes/`

---

## Development Workflow

### Running Tests

**Backend:**
```bash
pytest tests/
pytest tests/test_specific_file.py  # single file
pytest tests/ -v                     # verbose
```

**Frontend:**
```bash
cd frontend && npm test
cd frontend && npm test -- --run     # run once (no watch)
```

### Code Quality

- **TypeScript**: Always run `npm run typecheck` before committing frontend changes
- **Python**: Tests must pass before committing backend changes
- **No breaking changes**: Verify API contracts when modifying endpoints

---

## Engram (MANDATORY)

Engram persistent memory is required for SDD workflows.

**After every SDD phase**: `mem_save` the result with topic key `sdd/{change-name}/{phase}`.

**On session start**: Load checkpoint from `nec/checkpoint` for lightweight recovery.

If Engram is unavailable, report the error. Do not continue SDD work without persistence.

---

## SDD (Spec-Driven Development)

### Artifact Store — SIEMPRE Engram (regla dura)

El artifact store de SDD de este proyecto es **siempre `engram`**. No preguntar,
no ofrecer OpenSpec ni hybrid, y no volver a plantear esta decisión.

El dispatcher nativo de SDD (`gentle-ai sdd-status` / `gentle-ai sdd-continue`)
es **solo-OpenSpec por diseño**: lee únicamente `openspec/changes/` y siempre
emite `artifactStore: openspec`; no puede observar cambios respaldados por
Engram. Con store `engram` **no invocarlo**: resolver estado y artefactos directo
desde Engram (`mem_search` + `mem_get_observation` sobre `sdd/{change-name}/...`)
usando el manual status schema. Los artefactos del ciclo viven como topic keys
`sdd/{change-name}/{phase}`.

Use SDD for substantial features or architectural changes. The workflow:

1. **Explore** (optional): Investigate the codebase, understand context
2. **Propose**: Create a change proposal with intent and scope
3. **Spec**: Write detailed requirements and scenarios
4. **Design**: Define technical approach and architecture
5. **Tasks**: Break down into implementation tasks
6. **Apply**: Implement the tasks
7. **Verify**: Validate implementation against specs
8. **Archive**: Close the change

**When to use SDD:**
- New features (frontend components, backend endpoints)
- Architectural changes (new modules, refactoring)
- Bug fixes with unclear root cause

**When NOT to use SDD:**
- Simple bug fixes (fix inline)
- Documentation updates
- Configuration changes

---

## Tools Reference

| Tool | Use |
|------|-----|
| `read` | Read source files, configs, documentation |
| `bash` | Run tests, scripts, git commands |
| `mem_save` / `mem_search` / `mem_context` | Engram persistence (MANDATORY for SDD) |
| `write` / `edit` | Modify source files |
| `graph_search` / `graph_read` | Query entity graph (for lore/character features) |

---

## Release & versioning (protocolo)

Protocolo completo: skill `skills/release-protocol/SKILL.md` y `docs/RELEASING.md`.

- Formato `v0.MINOR.PATCH` mientras Demiurgos esté en Alfa.
- Canal automático por `beta` en el nombre; publicar = tag + push.
- **Nunca publicar sin pedido explícito del Owner.**

---

## Execution Mode

When starting a new SDD or multi-phase action, ask:

- **Automatic** (`auto`): Run all phases in sequence. Show only the final result.
- **Interactive** (`interactive`): After each phase, show summary and ASK: "Want to adjust anything or continue?"

Default to **Interactive** if not specified. Cache the choice for the session.
