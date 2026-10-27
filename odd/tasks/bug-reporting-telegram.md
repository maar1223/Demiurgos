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

**S7 — Single-use ticket.** Linking uses a one-time ticket: TTL 10 minutes, single use, regenerable with one tap by reusing the pending ticket, and idempotent — a repeat `/start` from the same `telegram_user_id` for the same ticket is success, not an error. The ticket is minted, polled and revoked **by the backend**, never by the app directly: the relay accepts identity calls only with a shared `x-relay-key`, because an unauthenticated caller could otherwise mint a ticket for somebody else's account key. Redemption is not an HTTP route at all — it is an internal function the webhook calls after authenticating the Telegram update, so the app can never bind a Telegram account it does not control.

**S8 — QR plus link.** The linking modal renders an SVG QR client-side (`qrcode`) of the same deep link, alongside `https://t.me/<bot>?start=<ticket>` and a copy-the-code action. The QR uses a white card, a 4-module quiet zone, and is never inverted — light-on-dark QR codes fail on older scanners. Only `https://t.me/...` links are used, never `tg://`, because native cameras do not open custom schemes.

**S9 — Phone-first detection.** While the modal is open the app polls its own backend every 2 s (the backend proxies relay `POST /link/status`), and closes itself with `Conectado como @user` the moment the phone completes the link. Polling stops at ticket expiry. Identity calls are `POST` on purpose: a ticket must never travel in a URL or a Worker log.

**S10 — One identity store, in the relay.** The relay stores `telegram_user_id` (global, stable per Telegram account), `username`, `display_name`, the bound `account_key`, and `started_bots: {ideas, reports}`. The `account_key` is the app's **stable** identity: the credentials-vault account username when the vault is on, otherwise a persisted `install_id` written once into the local state. It must never be the session-scoped `principal_id` (`local-dev-session-<hex>` / `credentials-session-<hex>`), or the link would die on every logout. The backend resolves the `account_key` server-side and never accepts it from the browser. The idea bank is **not** migrated to this store (out of scope, see S17).

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

- [x] T1 — KV `LINKS` store: identity record shape, `started_bots`, permission flags (`S10`, `S11`). Same KV surface injected as `KvLike`, tested with `node --experimental-strip-types --test`. Commit `8bfb410d`; the anchor was renamed `principal_id` -> `account_key` in T2 after L12.
- [x] T2 — `POST /link/start`, `POST /link/status`, `POST /link/revoke` behind the shared `x-relay-key`, with ticket TTL, pending-ticket reuse, idempotent redemption and the 3/hour ceiling; redemption is an internal function for the webhook, not a route (`S7`, `S9`, `S13`). Commit recorded in L13.
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

**L12 — Two spec corrections found while opening T2 (2026-10-25).**
- **The anchor was wrong.** `principal_id` is minted per session in `api_server.py:2015` (`local-dev-session-<hex>`) and `:2145` (`credentials-session-<hex>`). Binding the link to it would break on every logout or restart. The record field is now `account_key`: the credentials-vault account username when the vault is on, otherwise a persisted `install_id` in the local state, always resolved server-side. `S10` rewritten; the rename landed in T2.
- **The relay is unauthenticated.** `bug_report.py::_deliver` posts with no credential, so the relay trusts anyone who reaches the URL. An identity route accepting a caller-supplied `account_key` would let anyone mint a ticket for it and bind a Telegram account they control. Identity calls now require `x-relay-key` (new Worker secret, shared with the backend) and **redemption is not an HTTP route**: it is an internal function the webhook calls, so the app can never assert a Telegram identity. `S7` and `S9` corrected.
- Deliberately **not** changed: the existing `POST /` report path stays unauthenticated as it ships today; hardening it is a separate decision and would need the backend to start sending the key. Recorded as a follow-up, not silently altered.

**L13 — T2 evidence (2026-10-25).**
- `relay/src/counters.ts` (new): the existing `bumpCounter` moved out of `index.ts` so the report path and the linking path share one implementation instead of two.
- `relay/src/linking.ts` (new): `startLink` (mint-or-reuse, 3 per hour), `redeemTicket` (internal, idempotent per Telegram account), `linkStatus` (pending/expired/linked with a one-time `install_token` handover), `revokeLink` (erases both directions). Tickets are 8 Crockford-base32 characters (Crockford excludes I/L/O/U so a hand-typed ticket cannot be misread), TTL 600 s.
- `relay/src/index.ts`: `LINK_PATHS` routing before the report path, `handleLink` guarded by `x-relay-key`, unknown paths answer `404 relay.not_found` instead of `405`.
- `relay/tsconfig.json`: `allowImportingTsExtensions` so the Node runner and `tsc` agree on explicit `.ts` specifiers.
- Tests: `relay/test/linking.test.ts` (11) and `relay/test/routes.test.ts` (6) over in-memory KV through the exported `fetch`. `npm test` -> **26 passed, 0 failed**; `npm run typecheck` -> clean; `npx wrangler deploy --dry-run` -> bundles 17.79 KiB with both KV bindings resolved.
- Docs: `relay/README.md` gains the identity-store rules, the endpoint table, the `RELAY_KEY` secret, the new codes and a Tests section.

**L14 — Correction after independent verification (2026-10-25).** `gentle-ai-verify` returned **FAIL** with two change-caused blockers; both were real defects in T2, not verifier noise.
- **B1 (S10): the account-key rule was stricter than the vault.** `^[A-Za-z0-9_-]{6,128}$` rejected `ana`, `Mr. Smith` and `jose@example.com`, all valid vault usernames, so a large class of accounts could not link. Replaced with the minimum a KV key needs: non-empty, trimmed, no control characters, at most 400 UTF-8 bytes. Regression tests cover both the accepted and the refused shapes.
- **B2 (S11): explicit permissions were silently dropped on ticket reuse.** Reopening the panel with `notify_releases: false` returned `200 {reused: true}` and redeemed with the first mint's flags. Reuse now applies any explicitly stated flag and keeps the unspecified ones.
- **Advisories fixed in the same batch:** `revokeLink` now also deletes the pending ticket record, so a ticket photographed before a revoke cannot re-link; and `writeIdentity` retires a stale `identity:acct:*` pointer when the same Telegram account moves to another account key.
- Rechecked: `npm test` -> **30 passed, 0 failed**; `npm run typecheck` -> clean; `npx wrangler deploy --dry-run` -> bundles with both KV bindings.

**L15 — Second correction: B2 survived the first fix (2026-10-25).** The limited recheck confirmed B1 fixed and the revoke advisory closed, but found B2 still open **through the HTTP path**: `handleLink` normalized an omitted flag with `body.report_identity !== false`, turning "not stated" into an explicit `true`, which the new reuse logic then persisted. Probe: start with both flags `false`, reuse with only `account_key`, redeem -> both permissions silently back to `true`. Baseline `b5eedbfc` was correct here, so the correction itself introduced the flip.
- Fix: the route now forwards a flag only when it is a boolean and leaves it `undefined` otherwise, and rejects a non-boolean flag with `400 relay.invalid_payload` instead of coercing it.
- Regression tests added from the verifier's probes: vault usernames accepted / unusable keys refused at the HTTP entry path, omitted-flag reuse keeping the stored value, non-boolean flag rejected, HTTP revoke invalidating the ticket, omitted-flag merge at the function level, and the stored record carrying `account_key` with no `principal_id`.
- `npm test` -> **36 passed, 0 failed**; `npm run typecheck` -> clean.
