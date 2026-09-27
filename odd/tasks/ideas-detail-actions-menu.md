# Feature: ideas-detail-actions-menu

## Status
- Route: delegated direct (ODD) — no SDD selected.
- TDD: OFF (no project TDD config; not requested).
- Delivery strategy: `single-pr` (inferred).
- Review (RDD): OFF (`clone_local`). No native review lifecycle.
- Base: `feat/materialize-preview-ux` @ `db3b0a0` (the predecessor work is committed; this change starts from a clean tree).

## Objective
Make the idea detail view readable and its actions reachable without scrolling: one visible primary action, one options menu for the rest, and a single collapsible section for the idea's metadata.

## Problem
- The detail view is long. Renaming, classifying, attaching an image and materializing all live at the BOTTOM, so changing anything means scrolling past the whole idea body.
- The header spends its prime space (next to the identity badges) on two export buttons.
- There are three sources of truth for the name: the idea title, the "Título sugerido" field in the materialize picker, and the file name. The "sugerido" field wins over the title it is supposed to be hinting at.

## Decisions (user-approved)
1. **One title.** The materialize flow uses the idea's title. The "Título sugerido (opcional)" field disappears. The editable FILE NAME in the destination step stays — it is not a second title, it is the only name that can collide.
2. **`Usar en un mundo` stays VISIBLE** next to the title, NOT inside the menu: it is the action that turns an idea into canon, and burying it flattens the hierarchy.
3. **The `⋯` menu** holds `Título`, `Imagen` ("Adjuntar o reemplazar imagen"), a separator, `Exportar idea a DOCX`, `Exportar idea a PDF`.
4. **One collapsible section below the title** holds `Clasificación` (the type) + `Historial de versiones`. Both describe the idea; neither is its content.
5. **The version history shows a readable label** ("Versión N · dd/mm/aaaa"), not the absolute disk path.

## Resulting layout
```
┌──────────────────────────────────────────────────────────────┐
│ Silpah — Lince relámpago de Chaae   [Concepto][Usada]        │
│ Origen · Creada · Etiquetas · Usada en        [Usar en un mundo] [⋯] │
├──────────────────────────────────────────────────────────────┤
│ ▸ Detalles de la idea   (colapsable: Clasificación + Historial) │
├──────────────────────────────────────────────────────────────┤
│ [imagen]                                                     │
│ # cuerpo de la idea (sin cambios)                            │
└──────────────────────────────────────────────────────────────┘
```
Menu contents: `Título` · `Imagen` · ─── · `Exportar idea a DOCX` · `Exportar idea a PDF`

## Out of scope
- Any change to the idea body rendering, the markdown viewer, or the world editor.
- Exporting other formats, sharing, or new backend endpoints.
- Removing anything from the backend API (the optional `title_hint` request field stays for compatibility; the UI simply stops sending it).
- Reworking the sidebars (list, assistant) or the app shell.

## Constraints
- **The AI prompt, the model and the envelope validation stay untouched.**
- All new copy goes through the i18n catalogue (`es` + `en`, neutral Spanish); the hardcoded-literal guard must pass. If the catalogue guard rejects keys that become unused, remove them from BOTH locales.
- Functional-first: reuse the existing design tokens and dialog shell; no restyle, no new dependency.
- Accessibility is not optional here: the menu must be keyboard reachable, `Escape` closes it, focus is managed, and the collapse control exposes `aria-expanded`.

## Tasks

- [x] **DM-1 — One title** (delegated writer)
  - Remove the "Título sugerido (opcional)" input and its state from the materialize picker.
  - Stop sending `title_hint` from every materialize call (target resolve, debounced re-resolve, generate). Keep the optional field in the API types.
  - The ficha title and the derived file name therefore come from the idea title; the destination step still lets the file name be edited.
  - Tests: update the assertions that expected `title_hint` in the request payloads; the picker no longer renders the field; the derived file name still follows the idea title.
- [x] **DM-2 — Detail actions menu + collapsible metadata** (delegated writer)
  - Header: keep the title + badges + metadata rows; replace the inline `PDF`/`DOCX` buttons with a visible `Usar en un mundo` button plus a `⋯` options menu.
  - `Usar en un mundo` opens the existing picker/destination/generate/preview/confirm flow inside a dialog (the flow itself does not change).
  - `⋯` menu items: `Título` (dialog with the title input + save), `Imagen` (dialog: attach or replace; label must say it replaces and versions the idea), separator, `Exportar idea a DOCX`, `Exportar idea a PDF` (these execute; PDF opens the existing export dialog).
  - Below the title: ONE collapsible section (`aria-expanded`, default COLLAPSED) containing the type selector ("Clasificación") and the version history.
  - Version history rows show `Versión N · dd/mm/aaaa` (locale-aware), not the absolute path.
  - Delete the now-dead inline sections (Título, Clasificación, Usar en un mundo, Historial de versiones) and the header export buttons.
  - Remove the toast / clipboard affordances that belonged only to the deleted inline sections if they become orphaned.
  - Tests: the menu opens and is keyboard/Escape closable; each item opens its dialog; the exports are invoked from the menu; the collapsible toggles and exposes state; the version history renders a date label and NOT an absolute path; the materialize flow still works end to end from the visible button.
- [x] **DM-3 — Verify, build, restart, commit** (parent, bounded actions)

## Verification plan
- Backend: `pytest tests/ -q` (should be untouched by DM-1/DM-2; the edge case `test_semantic_e2e.py::TestLiveHermesFirstE2E::test_live_guided_start_semantic_first` is a known pre-existing failure).
- Frontend: `npx vitest run`, `npm run typecheck`, `npm run build`.
- Independent verifier at the end (RDD is off; the writers run on a small profile, so the tier is raised).

## Progress log
- 2026-09-25: Document created after the user approved the design. Predecessor committed as `db3b0a0`. DM-1..DM-3 queued.

## Verification evidence
- Backend: `pytest tests/ -q` → 1 failed, 3193 passed, 1 skipped. Sole failure is the known pre-existing live E2E. Router tests → 42 passed.
- Frontend: `npx vitest run` → 114 files / 1398 passed (i18n guards included); `npm run typecheck` clean; `npm run build` OK.
- Runtime: backend restarted (the versions endpoint changed). `GET /api/ideas/x/versions` → 401 (route exists).
- Risk assessment: `gentle-ai review assess` → `medium`, 8 paths / 1470 changed lines, `review_due: true` (`slice_budget_reached`). RDD OFF → no native review.
- Independent verifier (fresh context, read-only): status `ok`; all six checks PASS; ONE MAJOR finding.
  - MAJOR (FIXED in DM-2b): failures raised from inside a modal rendered the page banner behind the overlay → silent failure. Regression versus the inline layout, and the same class as the user's original report.
  - Confirmed by the verifier: every capability survives with a reachable location; the picker is a STEP of one dialog (no stacked overlays); menu order/escape/outside-click/aria correct; exactly one default-collapsed section with `aria-expanded` below the title; no frontend materialize call sends `title_hint`; the destination file-name field survives; version rows show the localized date and never the absolute path while the copy-path icon-only action survives; only `ideas_bank_router.py` changed on the backend.
  - Accepted (not fixed): the menu's `isModalOpen` guard is a single extension point that a future modal could bypass (now commented and tested); focus moves to the dialog container rather than the first field; the materialize dialog's Escape handling is new so its step-close semantics deserve a future UX pass.
- Could NOT verify offline: real keyboard/screen-reader behaviour, and the visual result (no browser run).

## Next step
Delegate DM-1, then DM-2, then DM-3.
