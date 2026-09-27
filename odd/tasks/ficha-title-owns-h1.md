# Feature: ficha-title-owns-h1

## Status
- Route: delegated direct (ODD) — no SDD selected.
- TDD: OFF (no project TDD config; not requested).
- Delivery strategy: `single-pr` (inferred).
- Review (RDD): OFF (`clone_local`). No native review lifecycle.
- Base: `feat/materialize-preview-ux` @ `026e1af` (predecessors committed; clean tree).

## Objective
In every materialized ficha, **the title shown at the top and the H1 inside the body must be the same value**, always. Today the H1 is authored by the AI, so it can drift from the title the server records. The server must impose it.

## Problem (user-reported)
The user materialized an idea and the ficha's body title did not match the title shown above it. Cause: the body is AI-authored and the prompt merely asks for markdown; the H1 is whatever the model writes. The frontmatter `title` and the H1 therefore come from two different authors.

User's decision: the destination step exposes TWO fields — `Título de la ficha` (drives the H1 and the frontmatter `title`) and `Nombre del archivo` (drives the file name only). Changing the file name must NOT change the H1; the H1 follows the title.

## Authorized scope
- `src/tools/demiurgos-suite/wiki/idea_materialization_domain.py`
- `src/tools/demiurgos-suite/wiki/api_server.py` (materialize target + preview)
- `src/tools/demiurgos-suite/wiki/ideas_bank_router.py` (request models)
- their tests under `src/tools/demiurgos-suite/wiki/tests/`
- `frontend/src/pages/IdeasWorkshop.tsx`, `frontend/src/api/ideas.ts`, `frontend/src/i18n/messages.ts`
- `frontend/src/__tests__/IdeasWorkshop.test.tsx`, `frontend/src/__tests__/ideas-api.test.ts`
- `odd/tasks/ficha-title-owns-h1.md` (this document)

## Out of scope
- Editing the H1 of an EXISTING ficha through the world editor (a different surface; recorded as an open follow-up).
- The AI prompt, the model, and the envelope validation — untouched.
- Removing `title_hint` from the API (kept for compatibility; the UI no longer sends it).

## Contract

### Title resolution (single source)
- `ficha_title = (client_title or "").strip() or (idea.title or "").strip() or idea.slug`, with internal whitespace runs collapsed to one space.
- `default_file_slug = slugify_title(ficha_title) or idea.slug`.
- `file_slug = slugify_title(client_slug) if client_slug else default_file_slug` (unchanged from the previous feature).
- Both endpoints (`materialize-target`, `materialize-preview`) accept the optional `title` and `slug`; the response reports the RESOLVED `title` and the resolved `target.slug`/`target.path`, so the UI shows exactly what will be written.

### The server owns the body H1 (the core fix)
In `build_ficha_skeleton`, after the AI body is stripped and BEFORE the image injection:
1. If the body's first non-empty line is an H1 (`# ...`), REPLACE that line with `# {ficha_title}`.
2. Otherwise PREPEND `# {ficha_title}` as its own line followed by one blank line.
3. The image injection then places the image directly after the H1, as today.
The AI's own H1 is discarded; any later H1 in the body is left alone.

### Prompt and quality
`MaterializationRequest` and `_build_prompt` must stay byte-identical (the model still receives the title and may still emit an H1 — the server simply overrides it). `ficha_title` replaces the value that used to be passed as the title; `title_hint` keeps its current (now unused from the UI) role.

### `resolve_file_slug`
Rename its first parameter to reflect the resolved title: `resolve_file_slug(ficha_title, idea_slug, client_slug)`; the precedence now lives in the caller. Update its tests.

## Tasks

- [x] **FT-1 — Backend: the title owns the H1** (delegated writer)
  - `build_ficha_skeleton`: add the H1 normalisation described above (keyword-only, derived from its existing `title` argument so no new parameter is needed).
  - `resolve_file_slug`: rename/simplify as above.
  - `api_server.py`: both materialize endpoints accept `title`; compute `ficha_title`; pass it as the skeleton `title`; return the resolved `title` in the responses; keep the `MaterializationRequest` arguments byte-identical.
  - `ideas_bank_router.py`: add `title: str | None = None` to both materialize request models.
  - Tests: the H1 is imposed when the AI body has a different H1; an H1 is inserted when the body has none; the H1 equals the frontmatter `title`; a client `title` wins and is normalised (whitespace collapsed); the file name derives from the title and a client `slug` overrides it WITHOUT changing the H1; `MaterializationRequest` values unchanged; `image_rel=None` still byte-identical when no title override is involved.
- [x] **FT-2 — Frontend: two fields in the destination step** (delegated writer)
  - Add a `Título de la ficha` field to the destination step, prefilled from the resolved title (which defaults to the idea title), i18n in both locales.
  - Keep the existing `Nombre del archivo` field. Editing the TITLE re-derives the file name (unless the user has manually edited the file name — track that); editing the FILE NAME only re-resolves the path/collision and never changes the title.
  - Both values ride the target resolve, the debounced re-resolve and the generate payload.
  - Tests: the title field is prefilled; editing the title updates the file name; editing the file name does NOT change the title; the generate payload carries both.
- [x] **FT-3 — Verify, build, restart, commit** (parent, bounded actions)

## Constraints
- Neutral/professional Spanish for UI copy; technical artifacts in English.
- No new dependency; reuse the existing design tokens.
- The AI prompt, model and envelope validation stay untouched.

## Progress log
- 2026-09-27: Document created after the user clarified the requirement and chose the two-field model.

## Verification evidence
- Backend: `pytest tests/ -q` → 1 failed, 3202 passed, 1 skipped. Sole failure is the known pre-existing live E2E. Focused (domain+api+router) → 608 passed.
- Frontend: `npx vitest run` → 114 files / 1408 passed (i18n guards included); `npm run typecheck` clean; `npm run build` OK.
- Observed FLAKE (unrelated, pre-existing): `src/__tests__/GraphView.test.tsx > does not select a node when the click starts on a connection handle` failed once with `ResizeObserver is not defined` during a full-suite run; it passes 32/32 alone and the full suite re-ran 1405/1405. Our diff does not touch GraphView, the shared setup, or ResizeObserver; `setup.ts` has no ResizeObserver stub (it stubs `print` and `DataTransfer`). Recommended separate hardening: add a ResizeObserver stub to `src/__tests__/setup.ts`.
- Runtime: backend restarted (the materialize endpoints changed); `/api/config` 200, both materialize routes answer 401 (exist).
- Risk assessment: `gentle-ai review assess` → `medium`, 11 paths / 1224 changed lines, `review_due: true`. RDD OFF → no native review.
- Independent verifier (fresh context, read-only): status `ok`; all six checks PASS; no BLOCKER/CRITICAL.
  - Confirmed: the frontmatter `title` and the emitted leading H1 are built from the SAME `title` value, so they cannot diverge; the `MaterializationRequest` construction and the provider are byte-identical to HEAD; the file-name path never reaches the title/H1; the two-field logic (dirty flag, debounce, stale guard, focus, blur snap, reset) is correct; the earlier features (instant destination, progress/cancel, in-dialog errors, image carry, collision + `-2`) are intact.
  - Verifier edge cases empirically checked: `#Titulo` (no space), empty body, an H1 that is not the first line, and a later H1 — the leading H1 always equals the title.
  - MINOR accepted: detection is `"# "` only, so a setext/`#Titulo` heading is not replaced (the title is prepended and the model's heading survives later) — allowed by the contract; no test reads `_build_prompt` bytes (the file is provably unmodified); some byte-identity tests pass regardless of the imposition (the discriminating tests exist separately).
- Could NOT verify offline: the real rendered result in a browser and the live AI body. `path`/`slug` semantics of the pre-generate flush are covered by tests with mocked responses.

## Next step
Delegate FT-1, then FT-2, then FT-3.
