# chat-attachments — document attachments in the Assistant chat

Branch: `feat/chat-attachments` (base `origin/master` @ 7d85766c). Delivery: `ask-on-risk`.
Test runners: `pytest` from `src/tools/demiurgos-suite`; `cd frontend && npm test`.

## Specs

**S1 — Attach control.** The Assistant composer exposes one attach action that accepts only `.docx` and `.pdf`. A chosen file uploads to the server; a chip shows the file name and its extracted character count; a remove action discards it. The attach action is disabled while a turn is in flight.

**S2 — Upload endpoint.** `POST /api/{mundo}/ai/attachments` accepts multipart `file`, validates the extension and a 15 MB size cap, extracts the text server-side, stores it for 4 hours (at most 32 stored attachments; oldest evicted first), and returns `{id, name, kind, chars, truncated}`. Rejections are structured with a stable machine code and HTTP status: `attachment_unsupported_type` (422), `attachment_too_large` (413), `attachment_empty` (422), `attachment_conversion_unavailable` (422), `attachment_conversion_failed` (422).

**S3 — Failure is safe.** Extraction and dependency failures never crash the server and never kill a request. A rejected upload stores nothing and leaves the chat state unchanged.

**S4 — Prompt context.** Each send carries the conversation's `attachment_ids`. The server injects the extracted text into the activity run prompt in a delimited block, capped at 30,000 characters per attachment, and marks truncation. The semantic classifier gate receives only attachment metadata (names and kinds), never document text.

**S5 — Grounded answer.** On the activity surface the assistant answers using the attached content. When a question refers to an attachment, it must not invent content that is not in the attachment.

**S6 — Default prompt.** Sending with an attachment and no typed text uses the localized default prompt: `Resume el documento adjunto.` / `Summarize the attached document.`

**S7 — Attachment lifetime.** Attachments belong to the conversation and are re-sent on every turn until removed. An unknown or expired id returns `attachment_expired` (409); the frontend drops the stale chips and shows a localized notice without sending.

**S8 — Memory hygiene.** Document text is never written to conversation memory or distilled summaries; only attachment names are recorded.

**S9 — Scope.** Works for the world-scoped Assistant and the global (Taller de Ideas) Assistant.

**S10 — PDF dependency.** The optional dependency set ships markitdown's PDF extra so `.pdf` conversion works where the optional install succeeds; where it does not, the `attachment_conversion_unavailable` degradation applies.

### Assumptions (not requested verbatim; Owner may overturn)

- A1: T1 covers text extraction only (`.docx`, `.pdf`). Images are T2, out of scope here.
- A2: Limits — 15 MB per file, 30,000 injected characters per attachment, 4 h TTL, 32 stored attachments, at most 5 attachments per turn.
- A3: Multiple attachments per conversation are allowed.

### Out of scope

- Image attachments and vision (`T2`, later).
- Drag-and-drop upload.
- Persisting attachment bytes or text across a server restart.

## Tasks

- [x] T1 — Backend attachment module: bounded store + extraction seam (`S2`, `S3`, `S10`). Commit `95fde16d`.
- [x] T2 — Upload endpoint and structured rejection contract (`S2`, `S3`). Commit `dc5622cf`.
- [x] T3 — Ask wiring: `AskRequest.attachment_ids`, gate metadata, activity prompt block, memory hygiene, expired-id handling (`S4`, `S5`, `S7`, `S8`, `S9`). Commit `e3db887a`.
- [x] T4 — Frontend API client and types (`S1`, `S2`). Commit `3c835aa9`.
- [x] T5 — Composer UI: attach action, chips, default prompt, localized errors (`S1`, `S6`, `S7`). Commit `3c835aa9`.
- [x] T6 — Backend + frontend tests and dependency/docs update (`S10`). Commit `3c835aa9`.

## Log

**L1 (Owner, verbatim):** `continúa chat-attachments mas especificamente con las features de docx y pdf`

**L2 — Prior agreed framing (from checkpoint `nec/checkpoint`, session 2026-08-19):** "Próxima feature acordada: **adjuntos en el chat del Asistente** (PDF/.docx primero, imágenes después)". Orden acordado: T1 PDF/.docx (texto) → T2 imágenes (visión). This document implements T1 only.

**L3 — Repository evidence (2026-10-23):**
- Chat send path: `AIAssistantSidebar` → `useAIAssistantSessions.sendMessage` → `POST /api/{mundo}/ai/ask/activity` (SSE, primary) with `POST /api/{mundo}/ai/ask` as fallback; both take `AskRequest{prompt, session_id, section, file_path, guided_*}`.
- The semantic gate (`_semantic_gate` → `HermesSemanticProvider`) receives `body.prompt` and returns a bounded one-sentence answer plus a decision. The real streaming answer comes from `_build_ai_ask_prompt(...)` → `HermesActivityRequest.prompt` → Hermes `/v1/runs` `{input}`.
- Existing extraction seam: `sync_lore.utils.converter.convert_to_markdown` (markitdown) plus `import_analysis.strip_broken_data_uris`; `import_analysis._CONVERTIBLE_SUFFIXES` already lists `.docx`/`.pdf`.
- `requirements-optional.txt` installs `markitdown[docx]`; the PDF extra (`pdfminer-six`, `pdfplumber`) was absent from the dev venv. Installed locally and verified: a handcrafted PDF converts to text; the repo docx (`mundos/Vibrantes-Legacy/Enciclopedia de los Vibrantes.docx`) converts to 250,703 chars (hence truncation is mandatory).
- Global assistant context key: `ideas-global` (backend `GLOBAL_ASSISTANT_CONTEXT`, frontend `GLOBAL_ASSISTANT_CONTEXT`).
- Tests run from `src/tools/demiurgos-suite`; `TestClient(api_server.app, client=("127.0.0.1", 50000))` is the established API-test pattern.

**L4 — Implementation evidence (2026-10-23):**
- Backend: `src/tools/demiurgos-suite/wiki/chat_attachments.py` (extraction + store + prompt renderers), `error_codes.py` (`attachment.*` codes), `api_server.py` (upload endpoint, `AskRequest.attachment_ids`, gate metadata, run-prompt block, memory hygiene).
- Frontend: `src/api/chatAttachments.ts`, `Session.attachments` in `useAIAssistantSessions`, composer attach action/chips in `AIAssistantSidebar`, `error.attachment.*` + `assistant.attach.*` copy in both catalogues.
- Delivery: `requirements-optional.txt` now installs `markitdown[docx,pdf]`; `payload_manifest.json` regenerated (163 files) so the packaged app boots with the new module.
- Backend checks: `pytest wiki/tests/test_chat_attachments.py` → 28 passed; `test_api_server.py` → 523 passed; full suite (CI's ignore list, `-k "not live"`) → 3940 passed, 2 failed (`test_gateway_hooks`, known order-dependent, 39/39 in isolation), 30 deselected.
- Frontend checks: `npm test -- --run` → 124 files / 1503 tests passed; `npm run typecheck` clean.
- Deliberate limitation: the legacy `POST /ai/ask` fallback (used only when the activity surface is unavailable) returns the classifier's one-sentence answer, so document *content* answers come from `/ai/ask/activity`. The gate receives attachment metadata only by design.
- Native RDD: `review mode status` and the lifecycle are unavailable on this filesystem (RAR rejects the NTFS/FUSE Git common dir). `review assess --base-ref 7d85766c --committed-only` reported `risk: medium`, `review_due: false`, `under_budget`. No native review ran.

**Risk:** item 5 — delivery/environment (`requirements-optional.txt` adds the PDF extra; `payload_manifest.json` changes the shipped allow-list). Item 3 does not apply: the new endpoint and the `AskRequest.attachment_ids` field are additive.
