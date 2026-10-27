# Demiurgos bug-report relay

A small, separately-deployable email relay that turns a validated bug-report
bundle into an email delivered to a fixed Owner inbox. It runs as a
[Cloudflare Worker](https://developers.cloudflare.com/workers/) and is the only
place a transactional-email credential ever lives.

The desktop app never imports this directory: it is **not** part of the app
payload. The backend `POST`s the vendor-neutral contract below to a relay URL;
the relay validates it, rate-limits it, and forwards it to the email provider.

## Request contract (vendor-neutral)

```
POST /   Content-Type: application/json
{
  "schema": 2,
  "app_version": "...",
  "platform": { "os": "...", "os_version": "...", "arch": "...", "python_version": "..." },
  "description": "...",
  "contact": "..." | null,
  "logs": "..." | null,
  "context": { "route": "...", "view": "...", "ui_area": "...", "world_id": "..." }
}
-> 200 { "ok": true,  "delivery_id": "...", "deduped"?: true }
-> 4xx/5xx { "ok": false, "code": "<relay code>" }
```

`deduped: true` means the same report was already published inside the last 24
hours and `delivery_id` is the original one; nothing new was posted. An optional
`x-install-token` header carries the credential the app received when it linked
its Telegram account; it is never part of the body.

### Screenshots

A report may carry up to **two screenshots**, 5 MB each. They are sent as
`multipart/form-data`: the bundle travels in a `report` part (the same JSON as
above) and each image is an `attachments` file part. Binaries never enter the
JSON bundle — it is capped at 98 KB, and base64 would both break that cap and
make the report harder to audit.

```
POST /   Content-Type: multipart/form-data
  report       = <the JSON bundle>
  attachments  = <image/png | image/jpeg | image/webp>   (at most two, 5 MB each)
```

Each image is published as a **document**, never as a photo: `sendPhoto`
recompresses and destroys exactly the interface detail a screenshot exists to
show. The order inside the topic is summary → screenshots → `report-<id>.txt`.
A bad type, an empty file or an oversized image fails closed before any Telegram
call. The **magic bytes** decide the type, not the client's claim: a renamed HTML
file is refused, and a PNG declared as JPEG is published as a PNG. The filename is
reduced to its basename so a path can never travel downstream. The email channel carries text only, and states how many attachments
it could not deliver instead of pretending they arrived.

The contract mirrors `bug_report.py::_deliver`, which is the source of truth for
the wire shape. Field caps (`description` 4000, `contact` 200, `logs` 65536,
`context` 200 per value, total 98304 bytes) are identical on both sides.

`context` (schema 2) says **where in the app** the bug happened, so the reporter
never has to describe it. Both schema **1 and 2** are accepted: a backend without
context keeps speaking the older contract, and a version mismatch here would drop
reports — which is worse than a report without context. Unknown context keys are
refused, so the block cannot become a smuggling channel.

Relay codes are non-secret and never carry a credential:
`relay.invalid_payload`, `relay.unsupported_schema`, `relay.too_large`,
`relay.rate_limited`, `relay.rate_limit_unavailable`, `relay.report_blocked`,
`relay.not_configured`, `relay.provider_unreachable`, `relay.provider_rejected`,
`relay.delivery_failed`, `relay.method_not_allowed`.

## Identity store (Telegram linking)

A linked account binds a Telegram user to the app's stable account key. The relay
is the only component that knows both sides, so the store lives here
(`src/identity.ts`) in the `LINKS` KV namespace:

```
identity:tg:<telegram_user_id>      -> IdentityRecord (JSON)
identity:acct:<account_key>         -> <telegram_user_id>      (pointer)
link_token:<sha256(install_token)>  -> <telegram_user_id>      (report signature)
identity:token:<telegram_user_id>   -> <sha256(install_token)> (pointer)
blocked:<sha256(install_token)>     -> "revoked"                 (30-day guard)
```

Only the hash of the `install_token` is stored, and it is removed by a revoke.
The revoked digest survives for 30 days so the unlinked client cannot keep
reporting through the dead credential; relinking issues a new token that is not
blocked.
That is what lets a report prove who sent it without ever carrying a secret in
its body.

```json
{
  "telegram_user_id": "1234567890",
  "username": "brook",
  "display_name": "Brook",
  "account_key": "prin_abc123",
  "linked_at": "2026-10-25T12:00:00.000Z",
  "started_bots": { "ideas": false, "reports": true },
  "permissions": { "report_identity": true, "notify_releases": true }
}
```

Rules the store enforces:

- **Reads fail closed.** A malformed value or a dangling pointer reads as
  absent, so corruption can only lose a link, never grant one.
- **One Telegram account per account key.** Relinking retires the previous
  telegram-side record instead of leaving an identity that can no longer be
  revoked.
- **Delivery permission is per bot.** `started_bots` records which bots the
  account has actually started; a bot cannot transfer that permission to
  another bot.
- **Permissions are separate.** `report_identity` and `notify_releases` are
  granted and read independently. A caller that states one explicitly on a
  reused ticket has it applied, never silently dropped.
- **`account_key` validation matches the vault, not a stricter rule.** The vault
  stores any non-empty trimmed username (`account.py::create_account` imposes no
  charset), so the relay only rejects what a KV key cannot hold: empty, untrimmed,
  containing control characters, or over 400 UTF-8 bytes.
- **Revoke erases both directions.** `revokeLink` deletes the record, the
  pointer, the pending ticket **and** the ticket record, so a ticket
  photographed before the revoke cannot re-link the account for the rest of its
  TTL.

`LINKS` is a separate namespace from `RATE_LIMIT` on purpose: identities are
personal data with no TTL, while the counters are disposable and expires.
Mixing them would eventually let a TTL sweep erase a link.

## Identity endpoints

Called by the **backend**, never by the app: the backend owns the session that
proves the account and keeps the credentials server-side. Because a released
install cannot carry a shared secret, the client routes do **not** use
`x-relay-key`; each one presents the credential that install already holds:

| Route | Auth | Body | Answer |
|---|---|---|---|
| `POST /link/start` | open, per-IP bounded | `{account_key, report_identity?, notify_releases?}` | `{ok, ticket, expires_at, reused}` |
| `POST /link/status` | the `ticket` itself (random, single-use, 10 min) | `{ticket}` | `{ok, state: pending\|expired\|linked, identity?, install_token?}` |
| `POST /link/state` | `x-install-token` | `{}` | `{ok, state: linked\|unlinked, identity?}` |
| `POST /link/revoke` | `x-install-token` | `{}` | `{ok, revoked}` |
| `POST /release` | `x-relay-key` | `{version, report_ids[]}` | `{ok, version, report_ids, releases}` |
| `POST /releases` | open (public read) | `{}` | `{ok, releases[]}` |
| `POST /telegram/webhook` | Telegram secret header | Telegram update | `{ok: true}` |

Why it is split this way: `RELAY_KEY` cannot ship in a public installer — anyone
holding it could mint tickets for another account or revoke somebody's link — so
the routes a user's install needs are bounded per IP instead, and the
self-service half proves possession of the install token. Guessing an account
key reveals nothing, because no route accepts one for reading or revoking.

Behaviour worth knowing:

- A ticket lives 10 minutes and is single-use; the **link** it creates never expires.
- Reopening the panel reuses the pending ticket, so it does not burn the
  three-per-hour allowance (only minting does).
- `install_token` is returned by `/link/status` **once**, then withheld, so a
  reload cannot re-expose it. It is minted **at that handover**, never at
  redemption: no usable credential waits in KV while the user scans the QR, and
  the store keeps only its digest.
- `/link/state` is how the panel remembers a link after a reload: it proves
  possession with the `install_token`, and answers with the handle, the display
  name and the two permission flags only — never the account key, the numeric
  Telegram id or a credential — so a link revoked from Telegram stops being
  reported as connected.
- `/releases` is a public read on purpose: every install shows "this was fixed"
  without linking anything. Only writing a release needs the shared key.
- Redemption (`/start <ticket>`) is not an HTTP route: it is an internal
  function the Telegram webhook calls, because a public redeem endpoint would
  let the app bind a Telegram account it does not control.

## Released fixes

A report often ends later than it starts: the bug is fixed in some version, and
the person who reported it deserves to know. The relay keeps a small, **public
and anonymous** list of releases:

```json
[{ "version": "v0.5.0", "report_ids": ["…"], "at": "2026-10-25T…" }]
```

Nothing about a reporter is stored — no person, no contact, no link. The app
keeps the ids of the reports it sent and matches them locally, which is what
lets `Perfil → Actualizaciones` say "your report was fixed in v0.5.0" without a
Telegram link.

Recording a release is one call, guarded by the same shared key as the identity
routes:

```bash
curl -X POST "$RELAY/release"   -H "x-relay-key: $RELAY_KEY" -H 'content-type: application/json'   -d '{"version":"v0.5.0","report_ids":["<id>","<id>"]}'
```

Every report's topic summary ends with `🆔 <id>`, so the ids to list are exactly
the ones you can read in the group. Calling it again for the same version
corrects that entry instead of duplicating it.

The Telegram DM is deliberately **not** implemented: it would require mapping a
report to a person, and the in-app notice covers the need without that cost.

## Who sent it (attribution)

A report states how the reporter's identity was established, and a group message
never blurs the three levels:

| Rendered line | What it means |
|---|---|
| `👤 @user · verified by Telegram` | The relay resolved the link from the report's `x-install-token`. |
| `👤 Name — declared · local session` | No link; the name is what the person typed. |
| `👤 owner` | The linked Telegram id is listed in `OWNER_TELEGRAM_USER_IDS`. |

Rules that keep it honest (`src/attribution.ts`):

- The token travels in the **`x-install-token` header**, never in the body, so it
  can never reach the group or a log. Unknown, replaced or malformed tokens fall
  back to the declared level instead of failing the report; a revoked one is
  refused with `403 relay.report_blocked`.
- An **unbound** `LINKS` namespace means nothing can be verified, so the report
  still travels as a declared one. A store that *fails* refuses the report with
  `503 relay.rate_limit_unavailable` — the same fail-closed posture as the
  counters, because the relay cannot prove the credential is still allowed.
- A linked account only signs its reports while it holds `report_identity`.
  Turning that permission off turns the report back into a declared one; the link
  itself is untouched.
- Configuration never impersonates verification: an id on the Owner list is only
  labelled `owner` when the report presents a link that resolves to it. Without a
  link the report stays declared.
- A linked account is named by its Telegram handle, else its display name, else
  its numeric id. A name is never invented.

The email path carries the same line, as `Reported by:` in the body.

## Abuse control (S13)

A bot can post roughly 20 messages a minute to a group before Telegram answers
429, so every bound is enforced here, before Telegram, or the channel becomes
unusable for legitimate reports.

| Layer | Bound | Storage |
|---|---|---|
| Dedup | Same `description + platform + logs` inside 24 h returns the first `delivery_id` and posts nothing. | `dedup:<sha256>` (24 h) |
| Linked principal | 5 per hour, 20 per UTC day | `principal:hour:<account_key>`, `principal:day:<account_key>` |
| Unlinked reporter | 5 per IP per 10 min, 200 per UTC day globally | `ip:<addr>`, `global:<date>` |
| Linking tickets | 3 mints per hour per account (reuse is free) | `linkstart:<account_key>` |
| Linking by IP | 10 link-start calls and 1200 polls per hour (reuse counts) | `linkstart:ip:<addr>`, `linkpoll:ip:<addr>` |
| Revoked install | Its dead token is refused for 30 days | `blocked:<sha256>` |

Notes worth keeping:

- Dedup runs **first**, so an accidental double submit neither opens a second
  topic nor spends the reporter's allowance. Only a **delivered** report is
  remembered, so a failed one stays retryable.
- The dedup write is **retried once**. If both attempts fail the request still
  answers success: the report already reached the group, and a 502 would invite a
  retry that publishes it twice. The loss is logged as `dedup.write_failed`.
- Dedup is **per failure, not per person**: two accounts reporting the same crash
  get the first `delivery_id` and only the first is published, which is what keeps
  one topic per distinct problem. The id is not a secret — it already appears in
  the public release list.
- The optional **install pseudonym** (`x-install-id`, sent only when the reporter
  keeps it on) is a ranking aid, never a credential: the relay stores only its
  sha256 under `reporter:<digest>` and shows `🆔 instalación a3f9 · N reportes`.
  The counter is cumulative, written only after a delivery, and grants nothing —
  the per-IP and principal bounds above are unchanged.
- The fingerprint deliberately excludes the contact and the app version: adding a
  contact or upgrading must not look like a new report.
- A **refused attempt never extends the window it is being refused by**. The
  window starts at the last accepted report, so a reporter who keeps retrying
  cannot push it forward and lock themselves out for good.
- Every counter failure is **fail-CLOSED**. KV is eventually consistent, so two
  identical reports racing each other can both publish; these are best-effort
  bounds for the Alpha volume, never the only line of defence.

## Publication into the triage group

When `TELEGRAM_CHAT_ID` is set, a report is published into the Telegram group
instead of being emailed. The email path stays available for a deployment
without a chat id, and it is also the fallback channel for reporters who never
link Telegram.

One report becomes one **forum topic**, so the group stays readable and each bug
keeps its thread:

1. `createForumTopic` named `BUG · v<version> · <level> · <who>`. The level
   leads (`verified by Telegram`, `declared · local session`, `owner`,
   `sin contacto`) so truncation can never cut it and a typed `@handle` can
   never produce the topic of a verified account.
2. `sendMessage` with a bounded summary (Telegram caps a message at 4096
   characters; the summary is cut at 3800).
3. `sendDocument` with `report-<id>.txt` (its caption carries the same level)
   holding the **complete** report —
   description and up to 65536 characters of logs — because the message alone
   could never carry them.

Degradation is deliberate: a plain group, or a bot without the topic
permission, still receives the report — without a thread. A failure to send the
summary is a real delivery failure (`relay.delivery_failed`) and is reported as
such, never swallowed.

## Telegram webhook

Telegram calls this route, so it authenticates with the secret **Telegram**
echoes — `x-telegram-bot-api-secret-token`, the `secret_token` you pass to
`setWebhook` — not with the backend key.

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://<worker-url>/telegram/webhook" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

The bot accepts exactly two commands and never free text (this is a one-way
channel by decision):

| Command | Effect |
|---|---|
| `/start` (no ticket) | Telegram's own START button sends this. Answers where to get the link instead of staying silent. |
| `/start <ticket>` | Redeems the linking ticket, answers `Conectado. Te avisaré cuando arreglemos lo que reportes.` |
| `/link/revoke` | Unlinks the account, erases the identity, confirms |

Anything else is acknowledged with `200` and ignored, without an outbound call.

**Handled failures answer `200`, not an error.** Telegram redelivers any
non-2xx answer, so an expired or already-claimed ticket is answered with a short
explanatory message instead. A non-2xx here would make Telegram replay the same
update.

New codes: `relay.unauthorized`, `relay.not_found`, `link.invalid_account`,
`link.rate_limited`, `link.rate_limit_unavailable`, `link.ticket_invalid`,
`link.ticket_expired`, `link.ticket_consumed`, `link.failed`.

## Prerequisites

1. **Cloudflare account** with `wrangler` available (`npm install` in this
   directory installs it as a dev dependency).
2. **A transactional-email account with Brevo** (the free tier is enough for the
   Alpha feedback volume). Create an API key under *SMTP & API → API Keys*.
3. **A verified sender domain (SPF + DKIM).** Brevo only accepts a `SENDER_FROM`
   address on a domain you have authenticated: add the DKIM and SPF DNS records
   Brevo prints for your domain and wait for verification. Without a verified
   domain the provider rejects every send and the relay returns
   `relay.provider_rejected`.
4. **A fixed Owner inbox** (`OWNER_INBOX`) that will receive every report.

## Configure

Create both KV namespaces, then paste the printed ids into `wrangler.toml`:

```bash
npx wrangler kv namespace create RATE_LIMIT
npx wrangler kv namespace create RATE_LIMIT --preview
npx wrangler kv namespace create LINKS
npx wrangler kv namespace create LINKS --preview
```

Set the secrets. They are stored by Cloudflare and are **never** committed
to the repository:

```bash
npx wrangler secret put BREVO_API_KEY    # the provider key from step 2
npx wrangler secret put OWNER_INBOX      # the fixed destination inbox
npx wrangler secret put SENDER_FROM      # a verified sender on the domain from step 3
npx wrangler secret put RELAY_KEY        # shared with the backend; guards the identity routes
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put TELEGRAM_WEBHOOK_SECRET
```

| Secret / binding | Purpose |
|---|---|
| `BREVO_API_KEY` | Provider API key (sent as the `api-key` request header). |
| `OWNER_INBOX` | Fixed inbox that receives every report. |
| `SENDER_FROM` | Verified sender address for the outgoing email. |
| `RELAY_KEY` | Admin secret for `POST /release` (`x-relay-key`). The app no longer needs it: the routes a user's install calls are bounded per IP or prove possession of the install token. |
| `OWNER_TELEGRAM_USER_IDS` (optional var) | Comma- or space-separated Telegram user ids labelled `owner`. Never shipped as a secret. |
| `TELEGRAM_BOT_TOKEN` | Reports-bot token from @BotFather. |
| `TELEGRAM_WEBHOOK_SECRET` | Value Telegram must echo on the webhook; set with `setWebhook`. |
| `RATE_LIMIT` (KV) | Per-IP + global-daily rate-limit counters, plus the per-install pseudonym tally. |
| `LINKS` (KV) | Linked Telegram identities and pending tickets. |

## Run locally

```bash
npx wrangler dev
```

Local KV is simulated, so no real namespace id is required for a local run. To
exercise the handler without a real provider, point it at a stub: send the
contract body to the local `POST /` URL and confirm the JSON response shape.

## Tests

```bash
npm test
```

Node's built-in test runner with type stripping, so the relay gains tests
without a new dependency. The clock is injected, so ticket expiry is tested by
moving time, never by sleeping.

## Typecheck

```bash
npx tsc --noEmit
```

## Deploy

```bash
npx wrangler deploy
```

Then set `DEMIURGOS_BUGREPORT_RELAY_URL` (in the backend environment) to the
deployed Worker URL so `POST /api/bugreport/submit` can reach it. Unsetting that
variable is the operational kill-switch: submit fails closed with
`bugreport.relay_unavailable` and the client offers the GitHub-issue fallback.

## Not committed / not shipped

- No credential is stored in this repository. The provider key exists only as a
  Worker secret.
- `node_modules/` is not committed (see the repository `.gitignore`).
- This directory is not part of `payload_manifest.json` and therefore never
  ships with the desktop app.
