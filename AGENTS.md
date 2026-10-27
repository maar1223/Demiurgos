# Demiurgos — Web Platform Development

You are the Demiurgos Development Assistant. Your domain is **software engineering** — you help build and maintain the Demiurgos web platform using Organic Driven Development (ODD) with Gentle-AI.

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
  - **Tarea actual**: Which ODD feature is in progress, current task, completion percentage
  - **Cambios realizados**: Exact file paths modified and what was done
  - **Próximo paso**: The immediate next atomic action to execute
  - **Contexto mínimo**: Critical interfaces/types defined, dependencies needed

**Example checkpoint content**:
```markdown
## Tarea Actual
- ODD: world-importer-preimport-backup
- Tarea: T2 (spec S3-S4)
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

### Verifying UI changes (MANDATORY)

The API serves the prebuilt `frontend/dist`, which is gitignored. `vitest` and
`tsc` can be green while the served bundle is still the old one, so "check the
UI" may silently look at an older build. Before asking the Owner to look at any
frontend change:

1. Build: `cd frontend && npm run build`
2. Confirm the served asset is the new one:
   `curl -s http://127.0.0.1:8000/ | grep -o 'assets/index-[A-Za-z0-9_-]*\.js'`
3. Ask for a forced reload (Ctrl/Cmd+Shift+R).

Both identities are visible in `Perfil → Reporte de errores`: the backend
version and the frontend build stamp (sha, build time, and "uncommitted" when
the bundle was built from a dirty tree). A mismatch means the served UI is not
the code under review.

The launcher also warns at boot when `frontend/src` is newer than
`frontend/dist`; `scripts/start-demiurgos.sh --build-if-stale` rebuilds before
starting.

---

## Engram (MANDATORY)

Engram persistent memory is mandatory for ODD workflows.

**Large work**: mirror the feature document to topic `odd/<feature-name>/tasks` after each task.

**On session start**: Load checkpoint from `nec/checkpoint` for lightweight recovery.

If Engram is unavailable, report the error, preserve local progress, and mark the mirror pending. Never claim persistence you did not get.

---

## ODD (Organic Driven Development)

Demiurgos uses **Organic Driven Development (ODD)** with Gentle-AI. ODD is
size-proportional: the process adapts to the real size of the change instead of
applying a fixed phase ritual to every request.

> **SDD is retired.** gentle-ai 4.x removed the SDD dispatcher (`sdd-status` /
> `sdd-continue` no longer exist). Do not reintroduce SDD phases or `sdd/...`
> topic keys.

### Classify with the resume test

A task is **small** when all three hold:

1. The outcome is specified and no product or design decision is open.
2. It touches no high-risk item: stored data or migrations, security, shared
   contracts others consume, concurrency, delivery/CI, or nothing would catch a
   regression.
3. **Resume test**: if this session stopped now, someone could finish the work
   from the original request plus `git diff`.

Small work runs **inline**: read, edit, run the focused test and the suite once
each. No feature document, no Engram mirror, no commits unless asked.

### Track large work without asking

Large work (the resume test fails) gets a feature document **before the first
source write**, without asking permission:

- `odd/tasks/<feature-name>.md`, mirrored to Engram under topic
  `odd/<feature-name>/tasks`. The artifact store is always Engram; never ask.
- Fixed order: a 2–3 line header; `## Specs` with numbered `S1..Sn` quoting the
  Owner's exact strings, errors, commands and examples verbatim; `## Tasks` with
  one line per task (ID, linked `S#`, route, commit); `## Log` last, where `L1`
  is the original request verbatim and later corrections and evidence are
  appended.
- Hand off by reference, never by paraphrase:
  `Spec: odd/tasks/<feature>.md, T2, S3-S4`.
- Check a task off only after its outcome and checks were observed.
- Commit work units as reviewable slices (~400 authored lines), with tests and
  docs alongside the behavior, using Conventional Commits. Push, PR and merge
  remain the Owner's decisions.

### Test-first

When a relevant runnable test and a clear expected outcome exist: observe RED,
implement GREEN, refactor with tests green. For every existing command or option
the change touches, add one test proving its previous behavior still holds.

### When delegation is justified

- Exploration beyond a bounded read batch: one read-only explorer.
- Two or more independent units with disjoint edit surfaces: parallel writers.
- A change naming a high-risk item: independent verification after its own checks.

Never delegate because a diff is large or touches many files.

---

## Tools Reference

| Tool | Use |
|------|-----|
| `read` | Read source files, configs, documentation |
| `bash` | Run tests, scripts, git commands |
| `mem_save` / `mem_search` / `mem_context` | Engram persistence (MANDATORY for ODD) |
| `write` / `edit` | Modify source files |
| `graph_search` / `graph_read` | Query entity graph (for lore/character features) |

---

## Release & versioning (protocolo)

Protocolo completo: skill `skills/release-protocol/SKILL.md` y `docs/RELEASING.md`.

- Formato `v0.MINOR.PATCH` mientras Demiurgos esté en Alfa.
- Canal automático por `beta` en el nombre; publicar = tag + push.
- **Nunca publicar sin pedido explícito del Owner.**
