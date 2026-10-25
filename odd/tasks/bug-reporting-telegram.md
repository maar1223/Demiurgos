# bug-reporting-telegram — in-app bug reports delivered to a Telegram group, with release follow-up

Branch: `feat/bug-reporting-telegram`, base `master` @ `da2cfadf`. The predecessor chain (`feat/bug-reporting-s1a`..`s3b`, tip `01fc2f2d`) is **already merged into `master`** — see L9; no rebase or base decision is needed. Delivery: `stacked-to-main` (Owner, D3). Forecast ≈ 1,600 authored lines.
Test runners: `pytest` from `src/tools/demiurgos-suite`; `cd frontend && npm test`; `cd frontend && npm run typecheck`. Relay checks: `npm test` inside `relay/`.

## Specs

### T0 — Channel and topology

**S1 — Dedicated group, one topic per bug.** Reports land in a Telegram supergroup with forum topics enabled. Each report opens its own topic; discussion stays inside it. The group holds the Owner and the bot only — the reporter never joins it and never sees its content. (Owner, verbatim: `el canal de reportes de bugs en telegram sea como una especie de grupo aparte, donde "Demiurgos" desde el usuario X reporta que hay un bug en tal sitio de la herramienta. Tal vez con una imagen especifica del Bug.`)

**S2 — Separate bot, relay-owned.** The reports bot is a distinct bot account from the idea-bank bot. Its webhook points at the Cloudflare Worker relay; Hermes is not in the report path. The bot token lives only as a Worker secret. Reason: the idea-bank bot is an assistant with `web`, `memory`, `vision` and read access to the graph MCP, it long-polls its own token, and it does not exist on users' machines. The existing Owner-facing Telegram settings (`wiki/telegram_settings.py`, the `ConfigurationCenter` Telegram card for bot token and connection test) are **reused and extended**, not duplicated; the reporter-facing link block is a distinct concern shown in the same card.

**S3 — The report is born in the app.** The surface is the existing `Perfil → Reporte de errores` section. The current mandatory gate is preserved: submit stays disabled until the exact payload has been rendered in the preview, and any edit re-locks it.

### T1 — Payload

**S4 — Auto-attached context.** The bundle carries `context: { route, view, ui_area, world_id }` from the frontend, so the user never has to describe where the bug happened. The contract keeps `schema`, `app_version`, `platform`, `description`, `contact`, `logs`; `schema` becomes `2`.

**S5 — Screenshots.** Up to 2 attachments, 5 MB each, chosen explicitly by the user. They are delivered to the group as documents (never as `sendPhoto`, which recompresses and destroys UI detail). The preview shows each thumbnail, so nothing leaves unseen.

**S6 — Attribution levels, never faked.** A group message states exactly how the reporter's identity was established:
- `👤 @user · verified by Telegram` — the link came from a Telegram update.
- `👤 Name — declared · local session` — no link; the name is typed by the user.
- `👤 owner` — id supplied by relay configuration.
A configuration value is never presented as Telegram verification.

### T2 — Identity and linking

**S7 — Single-use ticket.** Linking uses a one-time ticket: TTL 10 minutes, single use, regenerable with one tap by reusing the pending ticket, and idempotent — a repeat `/start` from the same `telegram_user_id` for the same ticket is success, not an error.

**S8 — QR plus link.** The linking modal renders an SVG QR client-side (`qrcode`) of the same deep link, alongside `https://t.me/<bot>?start=<ticket>` and a copy-the-code action. The QR uses a white card, a 4-module quiet zone, and is never inverted — light-on-dark QR codes fail on older scanners. Only `https://t.me/...` links are used, never `tg://`, because native cameras do not open custom schemes.

**S9 — Phone-first detection.** While the modal is open the app polls `GET /link/status?ticket=...` every 2 s and closes itself with `Conectado como @user` the moment the phone completes the link. Polling stops at ticket expiry.

**S10 — One identity store, in the relay.** The relay stores `telegram_user_id` (global, stable per Telegram account), `username`, `display_name`, the bound `principal_id`, and `started_bots: {ideas, reports}`. The bound `principal_id` reuses the app's existing local principal (auth vault or `local-dev`). The idea bank is **not** migrated to this store (out of scope, see S17).

**S11 — Two independent permissions.** `report_identity` and `notify_releases` are stored and granted separately, so announcing features later never requires a data migration.

### T3 — Release follow-up

**S12 — In-app notice first.** A release that fixes a reported bug shows in `Perfil → Actualizaciones` for every reporter, linked by the `report_id` the app keeps locally. This needs no Telegram link and no extra step. The Telegram DM is the optional extra, sent only when the reporter linked the bot with `notify_releases`, and only for bugs that person reported. A release that touches none of that person's reports sends no DM.

### T4 — Abuse control

**S13 — Layered anti-spam.** Mandatory: `es importante que no se pueda hacer spam por dicho canal`.
- Dedup by hash of `description + platform + logs`: the same report within 24 h returns the existing `report_id` and posts nothing new.
- Linked principals: 5/hour, 20/day.
- Unlinked reports: the relay's existing per-IP plus global-daily ceiling in KV, which already fails closed when the rate-limit backend errors.
- Linking tickets: at most 3/hour per principal, one use each.
- `/link/revoke` removes the binding and blocks that principal's later reports.
- Rationale to preserve: a bot may post roughly 20 messages/minute to one group before Telegram answers 429, so throttling happens in the relay **before** Telegram, or the channel becomes unusable for legitimate reports that follow.

**S14 — No new delivery queue.** When Telegram delivery fails, the existing privacy-scrubbed copy-paste/GitHub-issue fallback applies. The email path **already in `master`** (`relay/` → Brevo) stays as the secondary channel for reporters who do not link Telegram; it is not removed by this feature.

**S15 — Secrets never travel.** The ticket and the `install_token` never enter the report bundle, never reach the group, and never land in logs. The panel reports the failure and offers the fallback instead.

### T5 — Bounds

**S16 — Distinct from the idea-bank bridge.** A bot cannot transfer delivery permission to another bot, so the idea-bank link cannot pre-authorize the reports bot. No bridge is built in this feature; the QR already removes the need to return to the PC.

**S17 — Out of scope.** (a) Migrating the idea bank to the shared identity store. (b) A one-tap bridge from the idea-bank bot to the reports bot — it would only ever fire for the Owner, since `TELEGRAM_ALLOWED_USERS` holds a single entry today. (c) Photo compression/re-encoding. (d) Automatic screen capture; screenshots are user-attached only. (e) Inbound free text on the reports bot — it is strictly one-way (Owner, D2: `unidireccional`).

## Tasks

### T0 — Base (cancelled)

- [x] ~~T0 — Decide and land the base~~ **Cancelled (L9):** the predecessor chain is already merged into `master`; there is nothing to rebase or land. New work starts from `master` @ `da2cfadf`.

### T1 — Relay identity

- [x] T1 — KV `LINKS` store: identity record shape, `started_bots`, permission flags (`S10`, `S11`). Same KV surface injected as `KvLike`, tested with `node --experimental-strip-types --test`. Commit recorded in L12.
- [ ] T2 — `POST /link/start`, `GET /link/status`, `POST /link/confirm`, `POST /link/revoke` with ticket TTL, reuse, idempotency, and the 3/hour ceiling. (`S7`, `S13`)
- [ ] T3 — Telegram webhook: `/start <ticket>` redemption, `/link/revoke` command, webhook secret validation. (`S2`, `S7`)

### T2 — Relay delivery

- [ ] T4 — Group publication: `createForumTopic` per report, `sendDocument` for attachments, caption ≤ 1024 chars with the full text in the bundle document. (`S1`, `S5`)
- [ ] T5 — Attribution rendering for the three levels. (`S6`)
- [ ] T6 — Dedup hash plus per-principal, per-IP and global ceilings, failing closed. (`S13`)

### T3 — App

- [ ] T7 — Backend: `schema: 2` contract (`context`, `attachments`, `install_token`), assemble path for the screenshot, scrubbing unchanged. (`S4`, `S5`, `S15`)
- [ ] T8 — Frontend: screenshot picker, thumbnails in the preview, capped at 2 × 5 MB. (`S3`, `S5`)
- [ ] T9 — Frontend: linking modal — QR (`qrcode`), deep link, copy code, countdown, regenerate, 2 s polling, auto-close. (`S8`, `S9`)
- [ ] T10 — Frontend: success screen with the optional `Abrir Telegram` action and the two separate permissions. (`S11`)
- [ ] T11 — Frontend: `Perfil → Actualizaciones` shows fixed reports, keyed by local `report_id`. (`S12`)

### T4 — Follow-up and close

- [ ] T12 — Relay: release DM to reporters of the fixed bugs only. (`S12`)
- [ ] T13 — Tests across relay, backend and frontend; `relay/README.md`, i18n in both catalogues, `payload_manifest.json` regenerated. (`S13`, `S14`)
- [ ] T14 — Full checks per runner, `Risk:` line, delivery slice boundaries recorded. (`S1`–`S17`)

## Log

**L1 (Owner, verbatim):** `por cierto, he estado pensando mejor en lo del sistema de reporte de bugs, y creo que hacerlo mediante telegram (por ahora) estaria bien. Sin embargo me gustaria analizar este video (no se si puedas hacerlo o necesites una skill especial para investigar desde youtube) https://youtu.be/p6nnqerea7w?si=o5Jr1FeCoY2BBS3H`

**L2 — Video analyzed (2026-10-25).** YouTube blocked subtitles (429) and media (403) from this IP; a `/tmp` deno runtime unlocked media formats and the audio was downloaded, but CPU Whisper was too slow and was aborted twice by the Owner at his request. Analysis therefore rests on video metadata/chapters plus the promoted repository `ericrisco/rsc-harness` (README read). Marginal value: its "the input is the factory entry" framing, and a `finding-verifier` that starts from "the finding is false" (already covered by this project's RDD refuter). It is a competing harness and is not adopted.

**L3 — Repository evidence (2026-10-25).** ~~The SDD `bug-reporting` chain exists complete but unmerged: `feat/bug-reporting-s1a`..`s3b` on base `5f83b191`, tip `01fc2f2d`, ~3,236 added lines across 24 files, including `relay/` (Cloudflare Worker → Brevo), `bug_report.py`, `content_scan.py`, `ReportSection.tsx`, `bugReports.ts`. `master` is `da2cfadf` and contains none of it.~~ **WRONG — superseded by L9.** The chain is merged; the file inventory and the `RATE_LIMIT` KV note remain correct, the delivery status does not.

**L4 — Identity evidence (2026-10-25).** ~~On `master` there is no user model; on `feat/bug-reporting-s3b` there is a local principal (`principal_id` + `label`) resolved by `_resolve_principal`, from `local-dev` (loopback) or the credentials vault. `DEMIURGOS_AUTH_MODE` is read there, not on `master`.~~ **Partially wrong — see L9.** `master` does resolve a local principal (`principal_id` + `label`) via `_resolve_principal`, and `DEMIURGOS_AUTH_MODE` is read at `wiki/api_server.py:1796`. What remains true: the idea bank keeps numeric Telegram ids only (`config/idea-capture.yaml`: `private_chat_ids`, `approved_groups`, derived `authorized_bindings`); usernames are never persisted; `TELEGRAM_ALLOWED_USERS` (in `~/.hermes/.env`) holds exactly one entry — the Owner.

**L5 — Telegram constraints confirmed (2026-10-25).** A bot cannot resolve `@username` to a `chat_id`; `sendMessage` needs the numeric id, and a bot cannot initiate a conversation (`403 bot can't initiate conversation`). The numeric user id is global and stable across bots, but delivery permission is **per bot** and cannot be transferred. This is why the ticket exists and why the idea-bank link cannot pre-authorize the reports bot.

**L6 — Owner decisions taken in conversation (2026-10-25).**
- `el canal de reportes de bugs en telegram sea como una especie de grupo aparte` — dedicated group, one topic per bug.
- The reports bot is `uno distinto al bot del banco de ideas, uno centralizado` — separate bot confirmed.
- `es importante que no se pueda hacer spam por dicho canal` — anti-spam is a requirement, not a nicety.
- `que si alguien vincula su telegram para el banco de ideas en ese momento el sistema le pregunte de una vez si quiere vincularse con el bot de reporte` — declined for this feature after the per-bot permission constraint was explained; recorded as a future improvement, conditional on the idea bank becoming multi-user (S17).
- `El enlace para abrir telegram ... debajo de ese enlace tambien haya un codigo qr` — QR added (S8).
- `el aviso de release` lives in the app first, with the Telegram DM as the optional extra (S12).
- Two separate permissions `report_identity` / `notify_releases` accepted (S11).
- Idea bank stays untouched: `el banco de ideas ya funciona perfecto tal como está` (S10, S17).
- Ticket TTL 10 minutes with one-tap regeneration confirmed after the distinction between the permanent link and the perishable ticket was explained.

**L7 — Open decisions (blocking, not yet answered).** ~~D1 base, D2 inbound text, D3 delivery chain.~~ **Answered in L10.**

**L8 — No source written yet (2026-10-25).** This document is the review artifact; implementation starts only after D1–D3 are answered. **D1–D3 answered in L10; implementation may start.**

**L9 — Correction: three earlier claims were false (2026-10-25).** Root cause: `rg` is not installed in this environment and my searches ended with `2>/dev/null`, so the shell's "command not found" produced empty output that I read as "no matches". Verified with `git` and `grep` instead:
- **The bug-reporting chain is already in `master`.** `git merge-base --is-ancestor feat/bug-reporting-s3b master` → yes; `git cat-file -e master:src/tools/demiurgos-suite/wiki/bug_report.py` → present; the `bugreport` commits are in `master`'s history; `ReportSection` is mounted at `frontend/src/pages/ProfilePage.tsx:1568`; `relay/` ships with `wrangler.toml` and `node_modules`.
- **`DEMIURGOS_AUTH_MODE` is not a dead key.** Read at `wiki/api_server.py:1796`, with the vault/`local-dev` providers described at lines 1842 and 2458.
- **Telegram is not absent from the repo.** `wiki/telegram_settings.py` (121 lines: token state, `has_token`, `test_connection`), plus `frontend/src/pages/ConfigurationCenter.tsx` with a Telegram card and `frontend/src/components/organisms/IdeaCapturePanel.tsx`.
Consequence: T0 is cancelled, and the reporter-facing link UI belongs in the existing Telegram card, not a new settings surface (S2).

**L10 — Owner decisions (2026-10-25, verbatim).** `D1, creo que es importante trabajar en esto antes de seguir con lo que estamos haciendo.` / `D2, unidireccional` / `D3, stacked to main`.
- **D2 = one-way.** The reports bot accepts only `/start <ticket>` and `/link/revoke`. No inbound free text, no assistant behaviour, no new moderation surface.
- **D3 = `stacked-to-main`.** Slices land on `master` in order as reviewable PRs.
- **D1 is moot** after L9: there is no unmerged chain to land, so the feature starts directly from `master` @ `da2cfadf`.

**L11 — T1 evidence (2026-10-25).** Branch `feat/bug-reporting-telegram` created from `master` @ `da2cfadf`.
- `relay/src/identity.ts` (new): `IdentityRecord` (`telegram_user_id`, `username`, `display_name`, `principal_id`, `linked_at`, `started_bots`, `permissions`), the two key directions `identity:tg:*` / `identity:principal:*`, and `readIdentity` / `readIdentityByPrincipal` / `writeIdentity` / `markBotStarted` / `revokeIdentity` over an injected `KvLike`.
- Fail-closed reads: malformed JSON, a non-numeric stored id, or a dangling principal pointer all read as absent, so corruption can only lose a link.
- One Telegram account per principal: relinking retires the previous telegram-side record, so no identity survives that cannot be revoked through the new link.
- `relay/test/identity.test.ts` (new, 9 tests) over an in-memory KV. RED observed first (module missing, 1 failed), then GREEN: `npm test` → 9 passed, 0 failed.
- `relay/src/index.ts`: `Env.LINKS` documented and typed. `relay/wrangler.toml`: separate `LINKS` namespace, with the reason it is not folded into `RATE_LIMIT` (personal data without TTL vs disposable counters).
- `relay/README.md`: identity-store section (key layout, record shape, the five enforced rules).
- `relay/package.json`: `test` script using Node's built-in runner and type stripping, so the relay gains tests without a new dependency.
- `npm run typecheck` → clean.
- Deliberate scope note: the principal-blocklist behind `/link/revoke` ("blocks that principal's later reports", S13) belongs to T6; T1 revokes and erases the binding.
