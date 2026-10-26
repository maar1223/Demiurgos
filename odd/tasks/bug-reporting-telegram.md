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

**S18 — The relay URL ships with the release.** Every install must know where to deliver a report. Today `DEMIURGOS_BUGREPORT_RELAY_URL` only comes from the environment (`api_server.py:10142`), and with no value the submit fails closed into the copy-paste/GitHub-issue fallback. A released build must carry the relay URL as its default (installer/config), or no user's report can reach the group.

**S17 — Out of scope.** (a) Migrating the idea bank to the shared identity store. (b) A one-tap bridge from the idea-bank bot to the reports bot — it would only ever fire for the Owner, since `TELEGRAM_ALLOWED_USERS` holds a single entry today. (c) Photo compression/re-encoding. (d) Automatic screen capture; screenshots are user-attached only. (e) Inbound free text on the reports bot — it is strictly one-way (Owner, D2: `unidireccional`). A bare `/start` still gets one canned answer pointing to the app, because Telegram's own START button sends exactly that and silence there reads as a broken bot; it interprets nothing and handles no free text.

## Tasks

### T0 — Base (cancelled)

- [x] ~~T0 — Decide and land the base~~ **Cancelled (L9):** the predecessor chain is already merged into `master`; there is nothing to rebase or land. New work starts from `master` @ `da2cfadf`.

### T1 — Relay identity

- [x] T1 — KV `LINKS` store: identity record shape, `started_bots`, permission flags (`S10`, `S11`). Same KV surface injected as `KvLike`, tested with `node --experimental-strip-types --test`. Commit `8bfb410d`; the anchor was renamed `principal_id` -> `account_key` in T2 after L12.
- [x] T2 — `POST /link/start`, `POST /link/status`, `POST /link/revoke` behind the shared `x-relay-key`, with ticket TTL, pending-ticket reuse, idempotent redemption and the 3/hour ceiling; redemption is an internal function for the webhook, not a route (`S7`, `S9`, `S13`). Commit recorded in L13.
- [x] T3 — Telegram webhook: `/start <ticket>` redemption, `/link/revoke` command, webhook secret validation, free text ignored. (`S2`, `S7`, `S16`). Commit recorded in L17.

### T2 — Relay delivery

- [x] T4 — Group publication: `createForumTopic` per report, bounded summary message, `sendDocument` with the complete bundle as `report-<id>.txt`; degrades to a plain group message when topics are unavailable (`S1`, `S5`). Attachments ride the same document path in T7. Commit recorded in L18.
- [x] T5 — Attribution rendering for the three levels, resolved by the relay from the per-install `install_token` the app presents in `x-install-token` (`S6`, `S15`). Commits `62c6965f`, and the record below.
- [x] T6 — Dedup hash plus per-principal, per-IP and global ceilings, failing closed; `/link/revoke` blocks the dead credential (`S13`). Commit recorded in L24.

### T3 — App

- [x] T7a — Backend: `schema: 2` with `context`, the `x-install-token` header, the stable `account_key` (vault username or persisted `install_id`) and the `/link/start|status|revoke` proxies; scrubbing unchanged (`S4`, `S7`, `S10`, `S15`). Commit recorded in L26.
- [ ] T7b — Attachments transport (2 × 5 MB, delivered as documents) across backend → relay → group; deferred to pair with T8, since the upload shape and the picker are one unit and no client can send an attachment before T8 exists.
- [ ] T8 — Frontend: screenshot picker, thumbnails in the preview, capped at 2 × 5 MB. (`S3`, `S5`)
- [ ] T9 — Frontend: linking modal — QR (`qrcode`), deep link, copy code, countdown, regenerate, 2 s polling, auto-close. (`S8`, `S9`)
- [ ] T10 — Frontend: success screen with the optional `Abrir Telegram` action and the two separate permissions. (`S11`)
- [ ] T11 — Frontend: `Perfil → Actualizaciones` shows fixed reports, keyed by local `report_id`. (`S12`)

### T4 — Follow-up and close

- [ ] T12 — Relay: release DM to reporters of the fixed bugs only. (`S12`)
- [ ] T13 — Tests across relay, backend and frontend; `relay/README.md`, i18n in both catalogues, `payload_manifest.json` regenerated. (`S13`, `S14`)
- [ ] T14 — Full checks per runner, `Risk:` line, delivery slice boundaries recorded. (`S1`–`S18`)
- [ ] T15 — Ship the relay URL as a build default so any install delivers to the configured relay (`S18`). Touches the installer/config, not the relay.

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

**L16 — T3 evidence (2026-10-25).**
- `relay/src/telegram.ts` (new): `parseStartCommand` / `parseRevokeCommand`, `handleTelegramUpdate`, and a `sendMessage` that never throws and never echoes the token. Copy is Spanish, short sentences, matching the product's primary catalogue.
- `relay/src/index.ts`: `POST /telegram/webhook`, authenticated by `x-telegram-bot-api-secret-token` (the `setWebhook` `secret_token`), **not** by `x-relay-key` — the caller is Telegram, not the backend. Missing `TELEGRAM_BOT_TOKEN` or `TELEGRAM_WEBHOOK_SECRET` fails closed with `relay.not_configured`.
- **A handled failure answers 200, not an error.** Telegram redelivers any non-2xx, so an expired or already-claimed ticket is answered with a short message instead of an error status; otherwise the same update would replay forever.
- One-way enforced (D2): free text and non-message updates return 200 and make **no outbound call**, which also removes the cheapest spam lever.
- Reliability: a redemption that throws `LinkError` still writes a user-facing message, and an unexpected throw is swallowed into a 200 so Telegram does not retry.
- Tests: `relay/test/webhook.test.ts` (10) with the global `fetch` stubbed — auth (missing/wrong secret), fail-closed config, live ticket, repeated `/start`, expired ticket, ticket claimed by another account, `/link/revoke` with and without a link, free text ignored, and the token/secret never appearing in a response. One test initially failed because the test passed a user id where the webhook secret belonged; the source was correct.
- `npm test` -> **47 passed, 0 failed**; `npm run typecheck` -> clean.

**L17 — T4 evidence (2026-10-25).**
- `relay/src/publication.ts` (new): `topicName`, `summaryText`, `bundleText`, and `publishReport` (topic → summary message → `.txt` document).
- Why a document: a Telegram message caps at 4096 characters and the logs alone reach 65536, so the summary is truncated at 3800 and the complete report travels as `report-<id>.txt`. That also gives S5's "document, never `sendPhoto`" a home before user attachments arrive.
- Degradation: a plain group or a missing topic permission still receives the report, without a thread. A failed **summary** is a real delivery failure (`relay.delivery_failed`), never swallowed.
- Sink selection in `index.ts`: `TELEGRAM_CHAT_ID` + `TELEGRAM_BOT_TOKEN` selects Telegram; otherwise the existing Brevo path runs. Neither configured fails closed with `relay.not_configured` instead of answering success.
- Tests: `relay/test/publication.test.ts` (9) — naming bounds, summary bounds, full logs preserved, the three-call sequence, degradation without topics, a failed summary rejecting, no token in message or document, and both sink-selection paths through `POST /`.
- `npm test` -> **56 passed, 0 failed**; `npm run typecheck` -> clean; `wrangler deploy --dry-run` -> 30.51 KiB.

**L18 — Correction after verification of T3+T4 (2026-10-25).** `gentle-ai-verify` returned **FAIL** on one requirement (11 of 12 met).
- **Blocker:** the webhook guard rejected only `undefined` ids, so `chat.id` / `from.id` as `null`, `true`, `{}` or a float were stringified (`"null"`, `"true"`, `"[object Object]"`) and still produced an outbound `sendMessage` to a chat that does not exist. `redeemTicket` then failed on a non-numeric id and the failure was announced to that bogus chat.
- Fix: ids are read as numbers only (`Number.isSafeInteger`) or strings, then validated — chat ids `^-?[1-9][0-9]{0,19}$`, user ids positive — before any work. A malformed id now returns silence with no outbound call.
- Privacy bonus: no `identity:tg:<garbage>` can be created from a malformed update; the store already refused it, and now the request never reaches it.
- Regression test added covering `null`, `true`, `{}`, negative, fractional and non-numeric ids for both fields, plus a `text` that is not a string.
- `npm test` -> **57 passed, 0 failed**; `npm run typecheck` -> clean.
- Everything else in the round met its requirement: publication order, the 65536-character log preserved, the topic/summary/caption bounds, degradation without topics, `delivery_failed` on a failed summary, both sink-selection paths, and no token in any output. Advisory noted, unchanged from baseline: a 65536-character **multibyte** log exceeds the pre-existing 98304-byte payload cap.

**L19 — Where a report is visible, and the gap behind it (2026-10-25).** Verified while answering the Owner.
- A report is visible **only in the Telegram triage group**: one forum topic per report, a summary message, and `report-<id>.txt` with the full bundle. There is no in-app list and no dashboard; the group is the inbox. In-app surfacing (T11) is the "your report was fixed" notice, not a report browser.
- **Gap found:** the relay URL is read only from the environment (`api_server.py:10142`) with no default, and an unset value fails closed into the copy-paste/GitHub-issue fallback. Only this machine has the variable (added to `.env`). A released install would therefore never deliver to the group. Recorded as S18 and task T15.
- Also not yet visible in the group: the verified signature (needs T5 + the linking path T7–T10) and dedup/limits (T6). Until then every report says `sin contacto` unless the reporter typed one.

**L21 — T5's missing half: the relay had no way to know who reports (2026-10-25).** Opening T5 exposed a gap the document assumed away. The report `POST /` carries `contact` and nothing else, so "verified by Telegram" was unreachable: the relay could not tell a linked account from an anonymous one. This also blocks T6's per-principal ceilings and T11's in-app notice, so it is a prerequisite, not a detail.
- Two candidate transports. **(a)** The backend sends `x-relay-key` plus the `account_key`. **Rejected:** `RELAY_KEY` guards `/link/start` and `/link/revoke`, so shipping it inside every install would let any user mint a ticket for somebody else's account key — it must stay server-side. L12 had already flagged the report path's auth as its own decision.
- **(b) chosen: the per-install `install_token`, in an `x-install-token` header.** It is already minted at redemption and handed to the app once by `/link/status` — `linking.ts`'s own header comment calls it "the `install_token` it will use for later reports". It is per-install, revocable, and a header keeps it out of the body, so it cannot enter the bundle, the group or a log (`S15`), and does not touch `validateReport`'s strict field list.
- Only `sha256(token)` is stored. A KV dump therefore cannot be replayed as an identity, and a revoked or replaced token resolves to nothing.
- Consequence recorded honestly: the backend does not send the header yet. That is T7/T9's wiring; until then a real report still renders `declared`/`sin contacto`, and the verified path is proven by tests only.

**L22 — T5 evidence (2026-10-25).**
- `relay/src/identity.ts`: `recordInstallToken` / `readIdentityByInstallToken` over `link_token:<sha256>` → telegram id, with a `identity:token:<telegram id>` pointer so revocation can find it. `revokeIdentity` erases it; a replaced token retires the previous lookup; `writeIdentity` cleans the lookup of a Telegram account retired by relinking. Malformed tokens are refused before any KV read.
- `relay/src/linking.ts`: the handover in `linkStatus` registers the token **before** the ticket forgets it, so a report can only ever present a token the relay really issued, and a crash cannot leave the link unverifiable.
- `relay/src/attribution.ts` (new): `resolveAttribution` and `ownerTelegramIds`. Exact lines: `👤 @user · verified by Telegram`, `👤 Name — declared · local session`, `👤 owner`, `👤 sin contacto`. Two gates keep it honest — the token must resolve, and the link must carry `report_identity`; an Owner id on the config list is labelled `owner` only for a linked account, never for an unlinked one. The name is the handle, else the display name, else the numeric id: never invented.
- `relay/src/publication.ts`: `PublishableReport.attribution` is required, so every delivery path must state it and the compiler refuses a report that forgot. Topic name uses the short label, the summary uses the exact line, the bundle gains `Reported by:`.
- `relay/src/index.ts`: reads `x-install-token`, resolves the attribution, passes it to both sinks; the email body carries the same line. New optional `OWNER_TELEGRAM_USER_IDS`.
- Tests: `relay/test/attribution.test.ts` (15) plus 3 HTTP-level cases in `publication.test.ts` (signed report carries the verified line and the token in neither summary nor document; an unknown token stays `sin contacto`; a configured Owner id renders `owner`, not verification). `npm test` → **78 passed, 0 failed** (was 60); `npm run typecheck` → clean; `npx wrangler deploy --dry-run` → 35.27 KiB with both KV bindings.
- `Risk: item 2 (security — a bearer credential now travels on the report path and grants an attribution label).` Independent verification required.

**L23 — Correction after independent verification of T5 (2026-10-25).** `gentle-ai-verify` returned **FAIL** with two change-caused blockers; both were real, and the green suite was hiding the first.
- **B1 (S6): the topic name stated only *who*, never *how*.** It interpolated `attribution.label`, so a declared report whose free-text contact was `@brook` produced exactly the topic of a verified `@brook`. Fixed with a new `Attribution.tag` (`verified by Telegram`, `declared · local session`, `owner`, `sin contacto`) that **leads** the topic name and the document caption, so truncation can never cut it. `BUG · v<version> · <tag> · <label>`, without repeating the tag when the label already is it (`owner`).
- **B2: an unbound `LINKS` binding broke report delivery.** `resolveAttribution` only treated `undefined` as absent, so `LINKS = null` plus a well-formed token threw a `TypeError` from outside the delivery `try`; baseline (`f81e7e88`) answered `200` for the same request. Fixed in one place: `lookupIdentity` treats a null/undefined binding as "nothing verified" **and** turns a store error into `attribution.resolve_failed` plus the declared fallback. Rationale: attribution is a label, never a delivery dependency — it may lose a signature, never invent one, and never discard a report the person already wrote.
- **Advisories closed:** the document caption now carries the tag; a throwing KV no longer escapes the handler.
- **Advisory left alone:** the plaintext `install_token` still sits in `ticket:<ticket>` until handover. That is pre-existing at baseline and required to hand the raw token to the app; only the new lookup stores sha256. Recorded as a follow-up, not silently changed.
- Verifier probes committed as regression tests: `relay/test/t5-regressions.test.ts` (7), covering the look-alike contacts, the unbound namespace, the throwing store, a token in the JSON body (`400`), hash-only storage, and the handover order.
- `npm test` -> **85 passed, 0 failed**; `npm run typecheck` -> clean; `npx wrangler deploy --dry-run` -> 35.88 KiB.
- **Recheck (same verifier, same probes): B1 FIXED, B2 FIXED, no new blocker.** Topic names now read `BUG · v0.9.3-alpha · verified by Telegram · @brook`, `… · declared · local session · @brook`, and `… · owner` for a linked configured id — the look-alike contact no longer collides. `LINKS: null`, `LINKS: undefined` and a working binding all answer `200`; a throwing store answers `200` with the declared level and logs only `attribution.resolve_failed`. Baseline at `f81e7e88` still 60/60, so nothing was loosened to make this pass.

**L24 — T6 evidence (2026-10-25).** The anti-spam requirement (`es importante que no se pueda hacer spam por dicho canal`) is now enforced in the relay, before Telegram.
- `relay/src/abuse.ts` (new): `reportFingerprint` (sha256 of `description + platform + logs`, with platform keys sorted), `readRecentReport` / `rememberReport` over `dedup:<hash>` with a 24 h TTL, and `admitReport` returning `duplicate` / `limited` / `accepted`.
- Order of the guards, which matters: **block check → attribution → dedup → limits → deliver → remember**. Dedup comes first so an accidental double submit neither opens a second topic nor spends the reporter's allowance, and only a **delivered** report is remembered, so a failure stays retryable.
- Linked principals: 5 per rolling hour and 20 per UTC day, in `principal:hour:<account_key>` / `principal:day:<account_key>`. They apply only when the token actually resolved — an unlinked reporter keeps the pre-existing per-IP (5/10 min) and global (200/day) ceilings, which is what S13 asks for.
- `/link/revoke` now writes `blocked:<sha256(token)>` with a 30-day TTL before erasing the link, and `isBlockedInstall` refuses that credential with `403 relay.report_blocked`. Relinking mints a fresh token, so the block never follows the person. The token is never stored, only its digest.
- **Fail-closed layer boundary, decided here:** an *unbound* `LINKS` still delivers a declared report, but a `LINKS` that **fails** refuses with `503 relay.rate_limit_unavailable`. Rationale: the relay cannot prove the credential is still allowed, and a revoked install must not be able to exploit an outage. S14's copy-paste/GitHub fallback is what keeps a reporter unblocked when the relay cannot answer.
- Tests: `relay/test/abuse.test.ts` (11) — duplicate returns the first `delivery_id` and publishes once, a different description publishes again, fingerprint ignores key order and distinguishes absent from empty logs, a failed delivery is retryable, the hourly cap with a free duplicate, the daily cap, the unlinked per-IP ceiling, a counter failure answering `503`, a revoked install answering `403` with no outbound call, and a relinked account passing. Two earlier tests were tightened: revoking now leaves exactly one `blocked:` record, and the store-failure case asserts the controlled `503`.
- `npm test` -> **96 passed, 0 failed**; `npm run typecheck` -> clean; `npx wrangler deploy --dry-run` -> 39.39 KiB.
- `Risk: item 2 (security — rate-limit and blocklist guards on a public, unauthenticated path).`
- Still open from L23: A1 (the plaintext `install_token` in `ticket:<ticket>` until handover) is pre-existing and required by the handover; recorded as a follow-up.

**L25 — Correction after independent verification of T6 (2026-10-25).** `gentle-ai-verify` returned **FAIL** with one blocker, and it was the kind only a fresh look finds.
- **Blocker (S13): the hourly window never rolled for a reporter who kept retrying.** `bumpCounter` re-`put`s the key with `expirationTtl` on **every** call, so every refused attempt also reset the one-hour expiry. Probe: 5 reports at 10:00, a refusal at 10:30, a new report at 11:01 -> still refused; retrying forever kept the lockout alive. The principal bucket was new in T6; the same flaw existed at baseline in the per-IP bucket and in the linking mint counter since T2.
- **Fix at the source, not in the caller:** `counters.ts` gains `admitCounter(kv, key, ttl, max)`, which reads first and only writes when there is room — so a refusal cannot extend the window it is refusing. It is now used by the principal hour/day, the per-IP and global ceilings, and the linking ticket counter.
- **Semantics kept honest in the docs:** the window starts at the last *accepted* report, so it is stricter than a rolling hour and never more permissive; a refusal changes nothing.
- **Advisory fixed in the same batch:** a linked account that declined `report_identity` fell into the anonymous per-IP ceilings because `resolveAttribution` nulled the identity. `identity` now stays set whenever the token resolved, and only the *level* is gated by the permission — declining a signature is not a way out of the abuse bounds. The rendered line is unchanged.
- Regression tests from the verifier's probes: `relay/test/abuse-window.test.ts` (3) over a TTL-aware KV — the principal hour rolls, hammering the limit leaves the expiry untouched (asserted), and the linking window rolls instead of being pushed — plus one test that an unsigned linked account is still counted against its principal bucket.
- `npm test` -> **100 passed, 0 failed**; `npm run typecheck` -> clean.
- Advisories not changed: the pre-existing plaintext `install_token` in `ticket:<ticket>` until handover (L23/A1), the swallowed `rememberReport` failure after a delivered report, and cross-principal dedup returning the first reporter's `delivery_id` (literal to S13's hash definition).

**L26 — T7a evidence (2026-10-25).** The app can now say where a bug happened and prove who is reporting, without the browser ever touching the relay.
- **Schema 2 + `context`.** `ALLOWED_FIELDS` gains `context`; `CONTEXT_KEYS = {route, view, ui_area, world_id}`, 200 characters per value, raw-dict re-validation as before (an unknown key is `bugreport.not_allowlisted`, not silently dropped). Each value is passed through `content_scan.redact_secrets`, so a credential pasted into a route cannot leave the machine. The relay accepts **schema 1 and 2** and refuses unknown context keys and over-long values.
- **Rollout guard, deliberate:** the backend sends `schema: 2` + `context` only when there is context, and otherwise stays on `schema: 1` with the key omitted. The deployed Worker predates schema 2, so a hard switch would have rejected every report until the relay was redeployed. A dropped report is worse than a report without context.
- **`install_token` in the backend.** `bugreport_identity.py` (new) owns the stable `account_key` — the vault username when the vault is on, else an `install_id` minted once and persisted in `capabilities.bugreport` — plus the token slot (64 hex, validated on read). `_deliver` reads it and sends `x-install-token`; the token never enters the payload, the response, or a log (S15).
- **Linking proxies.** `POST /link/start` resolves the account key server-side and forwards the two permission flags only when they are booleans; `/link/status` **keeps** the one-time `install_token` and returns only `state`, `username`, `display_name` and the two permissions — never the token, the numeric Telegram id or the account key; `/link/revoke` clears the stored token. All three require the principal and fail closed (`bugreport.relay_unavailable`) without `DEMIURGOS_BUGREPORT_RELAY_KEY`.
- **Wiring:** `api_server.py` passes `relay_key`, `bot_username`, `local_state=_local_state` and `vault_active=_vault_active`. Required config (not committed): `DEMIURGOS_BUGREPORT_RELAY_KEY` (same value as the Worker secret) and `DEMIURGOS_BUGREPORT_BOT_USERNAME`.
- `payload_manifest.json` regenerated: it was missing the new module, which broke payload-boot and installer tests until updated.
- Tests: `wiki/tests/test_bugreport_identity.py` (5) and 13 new cases in `wiki/tests/test_bug_report_router.py` (context forwarding and schema choice, unknown key, cap, secret redaction, header present/absent, link start/status/revoke, token kept server-side, fail-closed without the relay key); relay `npm test` 103. Backend suite: **4241 passed, 18 skipped**; the 2 `test_gateway_hooks` failures only appear in full-suite ordering and pass on their own file (pre-existing pollution, not this change).
- `Risk: item 2 (credentials/identity) and item 3 (the relay wire contract).` Independent verification required.

**L27 — Correction after independent verification of T7a (2026-10-25).** `gentle-ai-verify` returned **FAIL** with two blockers; both were real.
- **B1 (no-regression): a schema-1 report gained a line it never had.** The bundle document rendered `Where: (not provided)` unconditionally, changing the delivered document for every contextless report. Fixed: the line is omitted when there is no context, so the old shape is byte-identical. The email and summary were already conditional.
- **B2 (fail-closed): `/link/status` could report "connected" on an unsigned install.** The relay hands the `install_token` exactly once. If that store failed — or a later poll won the race — the next poll returned `200 state=linked` with no token, so the UI claimed a link whose reports could never be signed. Fixed: linked with no token **and** no stored token now answers `409 bugreport.link_incomplete` so the UI asks for a relink instead of lying.
- Advisories fixed in the same batch: `GET /assemble` no longer gains an unrequested `context_keys` field; the context cap is counted in **UTF-16 units** (`_utf16_units`), matching the relay's JavaScript `length` — 200 emoji used to pass here and fail at the last hop; the module docstring no longer says "three endpoints" for four.
- Advisories left alone: empty context values are dropped (they carry no information); the relay's own `POST /` does not redact any field (pre-existing anonymous-path behaviour, unchanged); a fresh mint with omitted flags still defaults both permissions to `true` (pre-existing relay behaviour, unchanged); a missing `DEMIURGOS_BUGREPORT_BOT_USERNAME` returns `telegram_url: null` with a valid ticket, leaving the copy-the-code path usable.
- Regression tests from the verifier's probes: a failed token store followed by a tokenless poll asserting `500` then `409`; and a 200-emoji context asserting `413`.
- **Recheck (same verifier, same probes): B1 FIXED, B2 FIXED, A1 FIXED, A3 FIXED, no new blocker.** The schema-1 document matches baseline byte-for-byte (UUID-normalized, `diff` empty); a failed store followed by a tokenless poll answers `500` then `409` and never `linked`, while a normal second poll still answers `linked`; `/assemble` keys match baseline; 200 ASCII and 100 emoji pass, 201 ASCII and 101 emoji are refused at both hops.
- One out-of-domain note from the recheck: a hand-crafted lone surrogate would now be reported as over the cap instead of raising, but a real HTTP client cannot even encode that body — no test added, since it cannot be exercised.
- `npm test` (relay) -> **103 passed**; backend router+identity -> **41 passed**; `test_payload_boot` -> 4 passed.

**L20 — The silence on a bare `/start` (2026-10-25).** First real test: the Owner opened the bot's chat and pressed Telegram's START button, and got nothing. The relay was healthy — `getMe` returned `ReportesDemiurgosBot`, `getWebhookInfo` had the right URL, `pending_update_count: 0` and no `last_error_message`, so the update was consumed with a 200. Telegram's START button sends `/start` **with no ticket**, and the handler ignored anything that was not `/start <ticket>`, exactly as designed.
- That behavior is correct but is a bad first impression, since pressing START is what every new user does.
- Fix: a bare `/start` (optionally `@bot`) now answers one canned line pointing to `Perfil → Reporte de errores → Conectar Telegram`. It interprets nothing and still handles no free text, so D2 holds.
- Also fixed while here: `sendMessage` now logs `telegram.send_failed` with the status (never a secret) instead of failing silently, which is what made this take a round-trip to diagnose.
- Tests: 2 added (bare `/start` answered and links nothing; `@bot` form answered; `/help`, `/start algo con espacios` and plain text still silent). `npm test` -> **60 passed, 0 failed**.
