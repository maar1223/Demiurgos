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
  "schema": 1,
  "app_version": "...",
  "platform": { "os": "...", "os_version": "...", "arch": "...", "python_version": "..." },
  "description": "...",
  "contact": "..." | null,
  "logs": "..." | null
}
-> 200 { "ok": true,  "delivery_id": "..." }
-> 4xx/5xx { "ok": false, "code": "<relay code>" }
```

The contract mirrors `bug_report.py::_deliver`, which is the source of truth for
the wire shape. Field caps (`description` 4000, `contact` 200, `logs` 65536,
total 98304 bytes) are identical on both sides.

Relay codes are non-secret and never carry a credential:
`relay.invalid_payload`, `relay.unsupported_schema`, `relay.too_large`,
`relay.rate_limited`, `relay.rate_limit_unavailable`, `relay.not_configured`,
`relay.provider_unreachable`, `relay.provider_rejected`, `relay.delivery_failed`,
`relay.method_not_allowed`.

## Identity store (Telegram linking)

A linked account binds a Telegram user to the app's stable account key. The relay
is the only component that knows both sides, so the store lives here
(`src/identity.ts`) in the `LINKS` KV namespace:

```
identity:tg:<telegram_user_id>      -> IdentityRecord (JSON)
identity:acct:<account_key>   -> <telegram_user_id>            (pointer)
```

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
  granted and read independently.
- **Revoke erases both directions.** `revokeIdentity` deletes the record and the
  pointer, so unlinked personal data does not linger.

`LINKS` is a separate namespace from `RATE_LIMIT` on purpose: identities are
personal data with no TTL, while the counters are disposable and expires.
Mixing them would eventually let a TTL sweep erase a link.

## Identity endpoints

Called by the **backend**, never by the app: the backend owns the session that
proves the account, and the relay trusts only that caller. Every route requires
the `x-relay-key` header and rejects a mismatch with `401 relay.unauthorized`.
All three are `POST` so a ticket never travels in a URL or a Worker log.

| Route | Body | Answer |
|---|---|---|
| `POST /link/start` | `{account_key, report_identity?, notify_releases?}` | `{ok, ticket, expires_at, reused}` |
| `POST /link/status` | `{ticket}` | `{ok, state: pending\|expired\|linked, identity?, install_token?}` |
| `POST /link/revoke` | `{account_key}` | `{ok, revoked}` |

Behaviour worth knowing:

- A ticket lives 10 minutes and is single-use; the **link** it creates never expires.
- Reopening the panel reuses the pending ticket, so it does not burn the
  three-per-hour allowance (only minting does).
- `install_token` is returned by `/link/status` **once**, then withheld, so a
  reload cannot re-expose it.
- Redemption (`/start <ticket>`) is not an HTTP route: it is an internal
  function the Telegram webhook calls, because a public redeem endpoint would
  let the app bind a Telegram account it does not control.

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
```

| Secret / binding | Purpose |
|---|---|
| `BREVO_API_KEY` | Provider API key (sent as the `api-key` request header). |
| `OWNER_INBOX` | Fixed inbox that receives every report. |
| `SENDER_FROM` | Verified sender address for the outgoing email. |
| `RELAY_KEY` | Shared secret the backend presents as `x-relay-key` on identity calls. |
| `RATE_LIMIT` (KV) | Per-IP + global-daily rate-limit counters. |
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
