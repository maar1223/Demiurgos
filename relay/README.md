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

Create the KV namespace used for rate limiting, then paste the printed ids into
`wrangler.toml`:

```bash
npx wrangler kv namespace create RATE_LIMIT
npx wrangler kv namespace create RATE_LIMIT --preview
```

Set the three secrets. They are stored by Cloudflare and are **never** committed
to the repository:

```bash
npx wrangler secret put BREVO_API_KEY    # the provider key from step 2
npx wrangler secret put OWNER_INBOX      # the fixed destination inbox
npx wrangler secret put SENDER_FROM      # a verified sender on the domain from step 3
```

| Secret / binding | Purpose |
|---|---|
| `BREVO_API_KEY` | Provider API key (sent as the `api-key` request header). |
| `OWNER_INBOX` | Fixed inbox that receives every report. |
| `SENDER_FROM` | Verified sender address for the outgoing email. |
| `RATE_LIMIT` (KV) | Per-IP + global-daily rate-limit counters. |

## Run locally

```bash
npx wrangler dev
```

Local KV is simulated, so no real namespace id is required for a local run. To
exercise the handler without a real provider, point it at a stub: send the
contract body to the local `POST /` URL and confirm the JSON response shape.

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
