# Feature: materialize-carry-idea-image

## Status
- Route: delegated direct (ODD) — no SDD selected.
- TDD: OFF (no project TDD config; not requested).
- Delivery strategy: `single-pr` (inferred).
- Review (RDD): OFF (`clone_local`). No native review lifecycle.
- Predecessor: `odd/tasks/materialize-preview-ux-latency.md` (the preview/confirm flow this extends).

## Objective
When an idea that carries an image is materialized into a world ficha, the image must be carried over and **always** included. The world owns a copy of the bytes; the ficha must never depend on the global ideas folder.

## Problem (verified)
- The idea has `media_path: media/2026-08-28-524e8b9c9770.jpg` and its body opens with `![idea image](/api/ideas/media/2026-08-28-524e8b9c9770.jpg)`.
- The created ficha carries **no image**. The materialization code never mentions `media`/`image` — the transfer was never implemented.
- Root cause: the ficha body is AI-authored, and the prompt forbids the model from writing paths; the AI cannot copy bytes. The idea's URL (`/api/ideas/media/...`) is also wrong inside a world.
- World fichas reference images as `media/<file>`, which `_resolve_media_path` resolves to `mundos/{world}/wiki/media/<file>` ("importer convention").

## Why it matters
An illustrated idea loses its illustration on materialization, silently. The canon should own its own assets; a ficha pointing at `ideas/media/...` would break when the idea is deleted.

## Authorized scope
- `src/tools/demiurgos-suite/wiki/idea_materialization_domain.py`
- `src/tools/demiurgos-suite/wiki/api_server.py` (materialize preview + the materialize branch of `create_file`)
- `src/tools/demiurgos-suite/wiki/tests/test_idea_materialization_domain.py`, `tests/test_api_server.py`
- `frontend/src/pages/IdeasWorkshop.tsx` (display substitution only), `frontend/src/__tests__/IdeasWorkshop.test.tsx`
- `odd/tasks/materialize-carry-idea-image.md` (this document)

## Out of scope
- A per-image include/exclude toggle — the user decided: **images are always included**.
- Multiple images, image editing, thumbnails, or gallery UI.
- Moving/rewriting the already-created fichas.
- Any change to the AI prompt, model, or the generated body text.

## Hard invariants (do not break)
1. **ZERO canon writes at preview** (R-IM-04). The image bytes are copied only at CONFIRM. Preview may READ the world media dir (to pick a free name) but must never create it or write to it.
2. **Digest binding.** The previewed `content` is what the confirm must send byte-for-byte (`pending["content"] == body["content"]` and the digest). The image reference is therefore part of the previewed content; the destination NAME must be final at preview time and reused verbatim at confirm.
3. **Prompt unchanged.** No change to `MaterializationRequest` or `_build_prompt`.
4. **Fail closed, never half-broken.** If the copy cannot be performed (any error, or the destination appeared after preview), abort BEFORE any canon write.
5. Ideas without an image behave exactly as today.

## Contract
### At preview (`POST /api/ideas/{slug}/materialize-preview`)
- Resolve the idea image: `idea.media_path` must be a bare `media/<name>` with an allowlisted image extension, and the file must exist under `<ideas_root>/media/`. A missing file or a non-image extension → treat as "no image" (log, do not fail the preview).
- Destination name: `<file_slug><ext>` (e.g. `silpah-lince-de-chaae.jpg`). If `mundos/{world}/wiki/media/<name>` already exists, pick the next free `<name>-2`, `<name>-3`, … (READ only) using the existing `suggest_free_slug` semantics.
- Inject `![<ficha_title>](media/<dest_name>)` into the assembled ficha content, immediately after the body's first line when that line is an H1, else at the very start of the body. One blank line separates it from the following text.
- Response gains an optional block: `"media": {"src": "/api/ideas/media/<source_name>", "dest": "media/<dest_name>"}`. Absent when there is no image.
- Pending record gains `"media": {"source": "<source_name>", "dest": "media/<dest_name>"}` (bare source filename + world-relative dest; never an absolute path).

### At confirm (`POST /api/{mundo}/{section}/create`, materialize branch)
- BEFORE `_write_content` and after the existing principal/target/content/digest verification: copy `<ideas_root>/media/<source>` → `mundos/{mundo}/wiki/media/<dest_name>`, creating `wiki/media` with `mkdir(parents=True, exist_ok=True)` if needed.
- If the destination file already exists at confirm time (a race after preview), or the source is gone, or the copy fails → raise 409 (`detail` naming the image) and write NOTHING. The user re-previews to pick a new name.
- The copy is a plain byte copy (`shutil.copyfile`); no re-encode. An orphan image left by a later `_write_content` failure is acceptable and harmless (never a broken ficha).
- The reindex/digest/`used_in` steps are unchanged.

## Tasks

- [x] **CI-1 — Backend: carry the idea image** (delegated writer)
  - `idea_materialization_domain.py`: add an optional keyword-only `image_rel: str | None = None` to `build_ficha_skeleton` that injects `![{title}]({image_rel})` after the H1 (or at the start when there is no H1). No image → byte-identical output to today.
  - `api_server.py`: resolve the idea image at preview (allowlisted extension, existence, traversal-safe bare name, free dest name via the existing slug helper); pass `image_rel` to `build_ficha_skeleton`; add the `media` response block and the `media` pending-record entry; implement the confirm-time copy with fail-closed semantics.
  - Tests: domain injection (with H1, without H1, no image → unchanged); preview injects the reference + returns the `media` block; the world media dir is UNTOUCHED after a preview; confirm copies the bytes and the reference resolves; dest dedupe at preview; a dest that appears between preview and confirm → 409 with NO canon write; an idea without media is unaffected; a missing media file degrades to "no image" without failing.
- [x] **CI-2 — Frontend: show the image in the preview dialog** (delegated writer)
  - The dialog renders `preview.content`; when `preview.media` is present, substitute `dest` → `src` for DISPLAY ONLY so the not-yet-copied image renders. The content actually sent to confirm stays untouched.
  - i18n: none expected; if a label is needed, add it to both `es` and `en`.
  - Tests: with `media` present the rendered markdown targets the idea URL; the confirm payload still carries the original `content`.
- [x] **CI-3 — Verify, build, restart** (parent, bounded actions)

## Constraints
- Do NOT change the prompt, the model, or the generated body text.
- Do NOT introduce a toggle; images are always included.
- Neutral/professional Spanish for UI copy; technical artifacts in English.
- Nothing committed; the working tree already holds the predecessor feature's uncommitted work.

## Progress log
- 2026-09-25: Document created after diagnosing the missing-image defect. CI-1..CI-3 queued.

## Verification evidence
- Backend: `pytest tests/ -q` → 1 failed, 3193 passed, 1 skipped. Sole failure is the known pre-existing live E2E. Focused: domain+api → 557 passed. New image tests alone → 15 passed.
- Frontend: `npx vitest run` → 114 files / 1384 passed (i18n guards included); `npm run typecheck` clean; `npm run build` OK.
- Runtime: backend restarted (pid 339814, log `/tmp/demiurgos-api.log`; previous at `/tmp/demiurgos-api.log.pre-image`).
- Risk assessment: `gentle-ai review assess` → `medium`, 15 paths / 3340 changed lines, `review_due: true` (`slice_budget_reached`). RDD OFF → no native review.
- Independent verifier (fresh context, read-only): status `ok`; all 10 mandatory checks PASS; no BLOCKER/CRITICAL.
  - Confirmed: `_resolve_materialize_image` is provably read-only (no mkdir/write/shutil reachable) and the zero-write test also asserts `wiki/media` is NOT created; the dest name is fixed at preview and reused verbatim; the copy runs after verification and before `_write_content` with the pending proposal preserved on failure; `shutil.copyfile` with the dest re-derived from the server-only pending record (not client input); the `MaterializationRequest` construction and `_build_prompt` are byte-identical to HEAD (`_build_prompt` sha256 `34aac6db…` on both); `image_rel=None` is byte-identical (golden test verified against the code); alt escaping verified.
- Verifier findings (all MINOR, NOT fixed): the zero-write test lists paths rather than hashing contents (mitigated by code inspection); a pre-existing gap where `create_file` never pins the confirm `mundo` to `materialize_pending["world"]`; `..` substring over-rejection in a legitimate filename; the display-only substitution rewrites every occurrence (cosmetic, confirm content untouched); the copy re-validates traversal but not the extension (non-exploitable — the pending record is server-created from an allowlisted source).
- Could NOT verify offline: strict content-hash byte-identity of pre-existing canon files across a preview.
- Inline parent hardening (1 source line + 1 test): the image alt is now flattened (newlines) and bracket-escaped, so a title containing `[`/`]` cannot break the Markdown image syntax.

## Next step
- CI-1..CI-3 DONE and verified.
- The ficha already created by the user (`silpah-lince-de-chaae.md`) predates this feature and therefore has NO image; the idea is now `used_in: Vibrantes` and a file exists, so a re-preview collides. Regenerate it (delete + re-materialize) or inject the image into the existing ficha as a one-off.
- Pre-existing hardening worth a separate change: pin the confirm `mundo` to the preview `world` in `create_file`.

## Next step
Delegate CI-1 (backend), then CI-2 (frontend), then CI-3 (parent).
