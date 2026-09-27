# Feature: materialize-preview-ux-latency

## Status
- Route: delegated direct (ODD) — no SDD selected.
- TDD: OFF. Source: no project TDD config found (no pytest.ini/pyproject testpolicy, no `sdd-init` strict_tdd evidence); user did not request TDD. Checks = run the existing suites.
- Delivery strategy: `single-pr` (inferred: user asked for the work, no chaining requested; keep the diff one reviewable unit).
- Review (RDD): OFF (`gentle-ai review mode status` → off, decided by clone_local). No native review lifecycle was started.
- Verification tier: `gentle-ai review assess` → `medium`, `review_due: true` (`slice_budget_reached`, 1620 changed lines). Writers ran on a small/flash profile → tier raised one level → independent verifier required and run.
- Outcome: independent verifier `ok`, all 8 acceptance criteria MET, no BLOCKER/CRITICAL, 5 MINOR/INFO findings.
- Nothing committed; all work sits in the working tree for the user's decision.

## Objective
Fix the Taller de Ideas "Previsualizar" flow so it never looks hung, and remove the wasted work that inflates the wait — **without changing the generated content quality**.

## Problem
1. `POST /api/ideas/{slug}/materialize-preview` runs ONE full Hermes agent run and only then returns. Measured: 21.4 s (2298 output tokens) and 8.1 s (1294 output tokens). The user sees only the button label "Previsualizando..." — no progress, no timeout, no feedback.
2. The backend caps the run at 30 s (`DEADLINE_MS`) and discards slower generations, even though a real run took 21.4 s (close to the cap).
3. The run sends ~6.3 k tokens of tool schemas it never uses (`tool_turns=0`).
4. The "preview" is not a preview: it is the complete AI generation shown before saving, so the destination (path, collision) is only revealed after paying the full cost.

## Why it matters
- Perceived hang → users think the tool is broken (the reported symptom).
- Lost generations at the 30 s cap → wasted waits.
- Cost/input waste on unused tool schemas.
- Wrong folder chosen → pay 20 s, then discover the target is wrong.

## Authorized scope
- `src/tools/demiurgos-suite/wiki/idea_materialization_protocol.py`
- `src/tools/demiurgos-suite/wiki/api_server.py` (materialize endpoints + provider wiring)
- `src/tools/demiurgos-suite/wiki/idea_materialization_provider.py`
- `src/tools/demiurgos-suite/wiki/tests/*` (materialize-related only)
- `frontend/src/pages/IdeasWorkshop.tsx`, `frontend/src/api/ideas.ts`, `frontend/src/i18n/messages.ts`, `frontend/src/__tests__/*` (ideas-related only)
- `odd/tasks/materialize-preview-ux-latency.md` (this document)

## Out of scope
- Changing the model or the generated ficha content/quality.
- The stale `Text/plain` header bug (already fixed and built in the previous work unit).
- Global Hermes config (`auxiliary.title_generation`) — affects all assistant sessions; NOT touched.
- Any SDD artifact store change.

## Acceptance criteria
1. Clicking "Previsualizar" shows the resolved destination (path, and collision if any) **immediately**, with no AI call.
2. The AI generation is an explicit action ("Generar contenido") that shows a blocking progress dialog with: an honest time expectation, a live elapsed-seconds counter, and a Cancel action that aborts the request.
3. A failed generation surfaces its error **inside that dialog** — never silently.
4. The backend allows up to 60 s for one generation and the UI copy matches that bound.
5. The generation request no longer ships unused tool schemas (`tool_choice: "none"`, `model: "hermes-agent"`), matching the existing `_run_hermes_sync` precedent.
6. Generated content is byte-identical in intent: same prompt text, same model, same envelope validation.
7. Existing suites pass: backend `pytest tests/` (wiki), frontend `vitest run`, `npm run typecheck`, `npm run build`.
8. No hardcoded user-visible literals (the i18n catalogue guard must pass) — all new copy in `es` + `en`, neutral Spanish.

## Tasks

- [x] **WU-1 — Backend: raise the generation deadline to 60 s** (delegated writer)
  - `idea_materialization_protocol.py`: `DEADLINE_MS = 30_000` → `60_000`.
  - Update any test asserting 30_000. Verify no upper-bound validator rejects it.
  - Evidence: `api_server.py:8235` (`deadline_ms=DEADLINE_MS`) and `:8243` (`asyncio.wait_for`).

- [x] **WU-2 — Backend: instant target resolution endpoint** (delegated writer)
  - New `POST /api/ideas/{slug}/materialize-target`, body `{world, section, folder}`.
  - NO provider call. Same auth guard, same world/section/traversal validation as `materialize_preview`.
  - 200 `{ "target": {world, section, folder, slug, path} }`; 409 `{detail, collision}` when the file exists (same `suggest_free_slug` shape as the preview).
  - Extract the shared target resolution + collision detection into one helper used by BOTH endpoints (no duplicated logic).
  - Tests: new cases in `test_ideas_bank_router.py` or the materialize API test file — auth, world 404, section 400, traversal 400, 200, 409 collision.

- [x] **WU-3 — Frontend: two-step preview + progress dialog** (delegated writer)
  - Step 1: "Previsualizar" calls `previewMaterializeTarget` (new API fn in `frontend/src/api/ideas.ts`) → opens the dialog in destination mode.
  - Dialog destination mode: shows `target.path`; if collision, the existing collision block and NO generate button.
  - Primary button "Generar contenido" → sets `previewing`, shows the progress dialog, calls the existing `previewMaterialize`.
  - Progress dialog: heading, honest copy (up to a minute), ticking elapsed-seconds counter, animated indicator, "Cancelar" that aborts via `AbortController` (extend `previewMaterialize` with an optional `signal`).
  - On error: render the localized message INSIDE the dialog, with a close action. Never rely on a top-of-page banner alone.
  - On success: progress dialog closes; the same dialog shows content + relations + "Crear ficha" (existing behaviour).
  - i18n: new keys in `es` and `en` (neutral Spanish), no hardcoded literals.
  - Tests (`frontend/src/__tests__/IdeasWorkshop.test.tsx` + `ideas-api.test.ts`): destination mode renders instantly without calling the generate endpoint; progress dialog appears while pending; elapsed counter advances with fake timers; cancel aborts; error renders inside the dialog; success reveals content.

- [x] **WU-4 — Backend: stop shipping unused tool schemas** (delegated writer)
  - `HermesMaterializationProvider.invoke`: POST `_GATEWAY_URL` (`/v1/chat/completions`) non-streaming with `{"model":"hermes-agent","tool_choice":"none","messages":[{"role":"user","content":prompt}]}`, mirroring `_run_hermes_sync` (`api_server.py:7601-7667`).
  - Read `choices[0].message.content`; keep `_build_prompt`, `_strip_fences`, `_parse_output` unchanged.
  - RAISE on non-200/transport error so the handler maps PROVIDER_UNAVAILABLE (do not return fallback text, which would map to MALFORMED_OUTPUT).
  - Keep `probe()` working against the capability endpoint; stamp `provider_run_id` from the response id and `provenance`.
  - Rewrite `tests/test_idea_materialization_provider.py` to a `MockTransport` returning `choices[0].message.content`.
  - NOTE: this degrades run-correlation provenance (a `chatcmpl-` id is not resolvable via `GET /v1/runs/{id}`). Accepted tradeoff for the token/cost saving.

- [x] **WU-5 — Verify and build** (parent, bounded actions)
  - Backend: `python -m pytest tests/ -q` from `src/tools/demiurgos-suite/wiki`.
  - Frontend: `npx vitest run`, `npm run typecheck`, `npm run build`.
  - Re-read the built bundle to confirm the new copy and the `tool_choice` payload.
  - Record the assessed tier and outcome.

## Iteration 2 — the name you give must be the name used (user-reported defect)

Reported: creating a ficha produced `2026-08-28-524e8b9c9770.md` instead of a readable name derived from the typed title. Verified findings:
- The filename came from the idea's internal `slug` (`2026-08-28-524e8b9c9770`, a Telegram id), never from `title_hint`.
- The frontmatter `title` was the IDEA's title, while the body H1 used the `title_hint` — the two disagree, a defect in itself.
- `slugify_title` exists in `idea_materialization_domain.py`, is exported, documented as AD5 and tested — and is wired to NOTHING. It is the missing piece.
- `based_on: ideas/{slug}` already preserves the idea link, so a readable filename loses no traceability.

Decision (user): the name is auto-derived from the title AND editable in the instant destination step.

### Traps to respect (verified before writing)
1. `build_ficha_skeleton` uses its `slug` parameter for BOTH `_ficha_id(...)` and `based_on: ideas/{slug}`. Splitting the file slug from the idea slug requires a NEW parameter; passing the file slug today would silently corrupt `based_on`.
2. `_MATERIALIZE_PENDING_PROPOSALS[...]["slug"]` is consumed by `IdeasBank().materialize(pending["slug"], mundo)` (api_server.py:4740) to mark the IDEA used. It MUST stay the idea slug; only `target` carries the new filename.
3. `_ficha_id`'s `canonical-single` branch tests `slug == (folder or section)` to detect "this file IS the folder index". A title-derived slug correctly fails that test; do not "fix" it.
4. QUALITY: `MaterializationRequest` (prompt inputs `slug`, `title`, `title_hint`) must stay EXACTLY as today. Only the server-owned frontmatter title and the filename change. Zero prompt-text change.

### Contract (authoritative)
- `ficha_title = (title_hint or "").strip() or (idea.title or "").strip() or idea.slug`
- `default_file_slug = slugify_title(ficha_title) or idea.slug`
- `file_slug = slugify_title(client_slug) if client_slug else default_file_slug`; if the normalized result is empty, fall back to `default_file_slug`. `slugify_title` strips everything outside `[a-z0-9-]`, so client input is traversal-safe by construction — normalize, do not reject.
- The response `target.slug`/`target.path` always report the RESOLVED slug, so the UI shows exactly what will be written.
- `title_hint` still goes to the provider unchanged; frontmatter `title` = `ficha_title`.

### Tasks (iteration 2)

- [x] **WU-6 — Backend: title-driven filename + separate idea slug** (delegated writer)
  - `idea_materialization_domain.py`: add `idea_slug: str` to `build_ficha_skeleton` and use it for `based_on` (`slug` keeps driving `_ficha_id`). Update its call site + domain tests.
  - `api_server.py`: add a single `_materialize_file_slug(idea, title_hint, client_slug)` helper implementing the contract above; `_resolve_materialize_target` takes the resolved `file_slug` instead of `idea.slug`.
  - `materialize_preview`: compute `ficha_title` + `file_slug`; pass `slug=file_slug, idea_slug=idea.slug, title=ficha_title` to `build_ficha_skeleton`; keep `MaterializationRequest` byte-identical to today; pending record keeps `slug=idea.slug` and gains `file_slug`.
  - `materialize_target`: accept `title_hint` + optional `slug`; return the resolved target.
  - `ideas_bank_router.py`: `IdeaMaterializePreviewRequest` + `IdeaMaterializeTargetRequest` gain `slug: str | None = None`; the target request also gains `title_hint: str | None = None`.
  - Tests: filename derived from `title_hint`; derived from the idea title when no hint; falls back to the idea slug for an untitled idea; a client `slug` overrides and is normalized (`"Mi Nombre Raro!"` -> `mi-nombre-raro`); empty/empty-normalizing client slug falls back to the default; `based_on` still points at the IDEA slug (assert the exact string); a collision on the derived name still yields 409 + `-2`; the id/frontmatter title now follow `ficha_title`.

- [x] **WU-7 — Frontend: editable filename in the destination step** (delegated writer)
  - Destination step gains a labeled filename field (i18n, es+en) prefilled with `target.slug` (without extension); `target.path` stays visible below.
  - Editing it re-resolves via `previewMaterializeTarget` with the current world/section/folder/title_hint + the edited `slug`, debounced (~400 ms), updating `targetPreview` + `collision`. The server-normalized slug is written back into the field.
  - "Generar contenido" sends the SAME resolved `slug`.
  - On collision the warning stays and generation stays blocked, but the existing `suggested_slug` becomes one-click applicable (sets the field and re-resolves).
  - Tests: editing the name updates the path; the generate call carries the edited slug; a collision suggestion applies and clears; the field shows the server-normalized value.

- [x] **WU-8 — Verify, build, restart** (parent, bounded actions)

## Iteration 2 — verification evidence
- Backend: `pytest tests/ -q` → 1 failed, 3177 passed, 1 skipped. Sole failure is the known pre-existing live E2E. Focused: domain+api → 541 passed.
- Frontend: `npx vitest run` → 114 files / 1382 passed (i18n guards included); `npm run typecheck` clean; `npm run build` OK; rebuilt bundle contains `materialize-target`, `slug`, `elapsedSeconds`.
- Parent spot checks: `MaterializationRequest(...)` construction in `materialize_preview` is byte-identical to HEAD (`slug=idea.slug`, `title=(idea.title or "").strip() or idea.slug`, `title_hint=body.title_hint`); `ficha_title` is a separate variable, so the prompt is untouched.
- Runtime: backend restarted (pid 273327, log `/tmp/demiurgos-api.log`; previous at `/tmp/demiurgos-api.log.pre-wu7`). Both routes answer 401 (exist) through the `:4173` proxy.
- Risk assessment: `gentle-ai review assess` → `medium`, 15 paths / 2753 changed lines, `review_due: true` (`slice_budget_reached`). RDD OFF → no native review.
- Independent verifier (iteration 2, fresh context, read-only): status `ok`, checks 1-5 and 7 PASS, check 6 (test honesty) FAIL-MINOR; no BLOCKER/CRITICAL.
  - Empirically confirmed normalisation: `"Mi Nombre Raro!"`→`mi-nombre-raro`, `"../../etc/passwd"`→`etc-passwd`, `"/etc/passwd"`→`etc-passwd`, `"!!!"`→default; all `^[a-z0-9-]+$` and ≤ 120 chars.
  - Confirmed `based_on: ideas/2026-08-28-524e8b9c9770` while the id/title follow the typed name.
  - Confirmed pending keeps `slug=idea.slug` (consumed by `IdeasBank().materialize`) while `target` carries the new filename.
  - Findings 1 and 2 were FIXED (WU-7c). Findings 3 (Generate within the 400 ms debounce sends the last resolved slug — path and sent slug still agree) and 4 (no end-to-end preview→confirm test with a derived filename) were accepted and recorded as follow-ups.
- Could NOT verify offline: the live preview→confirm→disk write with a title-derived filename (findings 4); live gateway behaviour.

## Constraints
- Do NOT change the prompt text, the model, or the generated body. Quality is explicitly protected by the user.
- Do NOT touch global Hermes config.
- Neutral/professional Spanish for UI copy; technical artifacts in English.
- The two-step flow deviates from the archived SDD spec `materialize-idea-into-world-ficha` (the preview used to be one call). A spec refresh is a follow-up, not part of this change.

## Progress log
- 2026-09-25: Document created. WU-1..WU-5 queued. No source writes yet.
- 2026-09-25: WU-1+WU-2 (backend) done via delegated writer — `_resolve_materialize_target` helper + `materialize-target` endpoint + 60s deadline. WU-3 (frontend) done — two-step flow, progress dialog, cancel, in-dialog error, 6 i18n keys. WU-4 (backend) done — chat-completions transport with `tool_choice: "none"`, prompt/model/envelope untouched. WU-5 done — full suites green, dist rebuilt, backend restarted, independent verification passed.
- 2026-09-25: Independent verification `ok` (no BLOCKER/CRITICAL); 5 MINOR/INFO findings recorded and NOT fixed (out of the authorized scope).

## Verification evidence
- Backend full suite: `pytest tests/ -q` → 1 failed, 3151 passed, 1 skipped (~72s). Sole failure `tests/test_semantic_e2e.py::TestLiveHermesFirstE2E::test_live_guided_start_semantic_first`. CONFIRMED pre-existing: reproduced on the base with the 3 backend source files stashed → identical `IndexError: list index out of range`.
- Parent spot checks: `tests/test_api_server.py -k materialize` → 40 passed; `tests/test_idea_materialization_provider.py tests/test_idea_materialization_protocol.py` → 65 passed; `ideas-api.test.ts + IdeasWorkshop.test.tsx` → 55 passed.
- Frontend: `npx vitest run` → 114 files / 1369 passed (includes hardcoded-literal + catalogue guards); `npm run typecheck` clean; `npm run build` OK.
- Built-bundle asserts: `materialize-target` + `elapsedSeconds` present in `IdeasWorkshop-*.js`; the six new Spanish copy strings present in `index-*.js`.
- Runtime: backend restarted (pid 218014, log `/tmp/demiurgos-api.log`; previous log preserved at `/tmp/demiurgos-api.log.pre-wu`). `POST /api/ideas/x/materialize-target` → 401 (route exists; 404 would mean missing), same through the `:4173` preview proxy.
- Independent verifier (fresh context, read-only): status `ok`; criteria 1-8 all MET; no BLOCKER/CRITICAL.
- Verifier findings (MINOR/INFO): missing test for the generation-call 409 race; Cancel aborts only the browser fetch (the server-side generation still completes); no provenance stamped when the response omits an id; JSX branch order differs from the stated priority but is functionally equivalent; untracked `.impeccable/` + `config/backup.json` are unrelated pollution.
- Could NOT verify offline: that the live gateway honors `tool_choice: "none"`, and that the live generation output is equivalent to the old `/v1/runs` path.

## Next step
- Iteration 2 is DONE and verified. Nothing in flight.
- Then: user decision on commit / branch, and whether to rename the already-created `2026-08-28-524e8b9c9770.md`.
- Optional follow-ups from verification: (a) add a test for the generation-call 409 race; (b) decide whether "Cancelar" should also stop server-side work or be relabeled to what it really does; (c) run one live preview to confirm the end-to-end flow and measure the new latency.

## Rationale (accepted changes)
- Do the backend contract first so the frontend has an endpoint to call.
- Keep the risky transport change (WU-4) last and separable.
- Cancel + in-dialog error are included because the original bug report was literally "nothing appears"; the failure path must be visible.
