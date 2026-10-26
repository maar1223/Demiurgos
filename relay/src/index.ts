/**
 * Demiurgos bug-report relay — Cloudflare Worker.
 *
 * A separately-deployable unit that turns a validated, vendor-neutral report
 * bundle into an email delivered to a fixed Owner inbox. It is NOT part of the
 * desktop app payload: the application never imports this code, and the only
 * credential involved — the transactional-email provider key — lives HERE, in
 * Worker secrets, never in the client install.
 *
 * Request contract (mirrors `bug_report.py::_deliver`, the single source of
 * truth for the wire shape):
 *
 *   POST /   Content-Type: application/json
 *   {
 *     "schema": 1,
 *     "app_version": "...",
 *     "platform": { "os": "...", "os_version": "...", "arch": "...", "python_version": "..." },
 *     "description": "...",
 *     "contact": "..." | null,
 *     "logs": "..." | null
 *   }
 *   -> 200 { "ok": true,  "delivery_id": "..." }
 *   -> 4xx/5xx { "ok": false, "code": "<relay code>" }
 *
 * An optional `x-install-token` header carries the credential the app received
 * when it linked its Telegram account. It is a header on purpose: the token
 * never enters the bundle, so it can never be published to the group or reach a
 * log. Its only job is letting the relay establish who is reporting, instead of
 * trusting a caller-supplied claim.
 *
 * Fail-closed: any validation, configuration, rate-limit or provider error
 * returns `{ "ok": false, "code": ... }` with a non-secret message. No
 * credential, token, or upstream response body is ever echoed to the caller.
 *
 * The provider is an implementation detail: this Worker forwards via Brevo
 * (`POST https://api.brevo.com/v3/smtp/email`). Swapping providers means
 * editing only `sendViaProvider` — the request contract above stays
 * vendor-neutral.
 *
 * The relay is intentionally unauthenticated (the install carries no shared
 * secret); the abuse bound is the per-IP + global-daily rate limit below, plus
 * the backend's own per-principal limit and the provider's free-tier cap.
 */

import { bumpCounter } from "./counters.ts";
import { admitReport, rememberReport, secondsUntilUtcMidnight } from "./abuse.ts";
import { isBlockedInstall } from "./identity.ts";
import {
  LinkError,
  linkStatus,
  revokeLink,
  startLink,
  type StartLinkRequest,
} from "./linking.ts";
import { handleTelegramUpdate } from "./telegram.ts";
import { publishReport } from "./publication.ts";
import { ownerTelegramIds, resolveAttribution, type Attribution } from "./attribution.ts";

/** Server-side bindings and secrets. Values are configured, never committed. */
export interface Env {
  /** KV namespace backing the per-IP + global-daily rate-limit counters. */
  RATE_LIMIT: KVNamespace;
  /**
   * KV namespace holding linked Telegram identities (`identity:tg:*` records and
   * `identity:acct:*` pointers). Kept apart from `RATE_LIMIT` because these
   * entries are personal data with no TTL, not disposable counters.
   */
  LINKS: KVNamespace;
  /** Provider API key (Worker secret). Never logged or returned. */
  BREVO_API_KEY: string;
  /** Fixed Owner inbox that receives every report (Worker secret/variable). */
  OWNER_INBOX: string;
  /** Verified sender address, e.g. `reports@your-verified-domain` (secret). */
  SENDER_FROM: string;
  /** Reports-bot token (Worker secret). Never logged or returned. */
  TELEGRAM_BOT_TOKEN: string;
  /**
   * Triage group id (for example `-1001234567890`). When set, reports are
   * published there instead of being emailed. Optional so the email-only
   * deployment keeps working.
   */
  TELEGRAM_CHAT_ID?: string;
  /**
   * Value Telegram must echo in `x-telegram-bot-api-secret-token`, set with the
   * webhook's `secret_token`. Without it anyone could post a forged update.
   */
  TELEGRAM_WEBHOOK_SECRET: string;
  /**
   * Shared secret the backend presents on every identity call (`x-relay-key`).
   * The relay never accepts an account key from an unauthenticated caller: that
   * would let anyone bind a Telegram account to somebody else's app. Missing
   * value fails closed (`relay.not_configured`).
   */
  RELAY_KEY: string;
  /**
   * Comma- or space-separated Telegram user ids of the Owner (optional). A
   * linked account on this list is labelled `owner`; an unlinked one never is,
   * because configuration must never be presented as verification.
   */
  OWNER_TELEGRAM_USER_IDS?: string;
}

/** Wire contract version, must match `_RELAY_SCHEMA` in `bug_report.py`. */
const RELAY_SCHEMA = 1;

/** The only top-level keys the contract allows. */
const ALLOWED_FIELDS = new Set([
  "schema",
  "app_version",
  "platform",
  "description",
  "contact",
  "logs",
]);

/** The only platform facts the contract allows. */
const ALLOWED_PLATFORM_KEYS = new Set([
  "os",
  "os_version",
  "arch",
  "python_version",
]);

// Size caps — kept identical to the backend caps in `bug_report.py` so the
// relay is never the weaker link in the validation chain.
const DESCRIPTION_MAX_CHARS = 4000;
const CONTACT_MAX_CHARS = 200;
const LOGS_MAX_CHARS = 65536;
const PAYLOAD_MAX_BYTES = 98304;

// Abuse bounds. KV is eventually consistent, not atomic, so these are
// best-effort limits — sufficient for the Alpha feedback volume.
const PER_IP_MAX = 5;
const PER_IP_WINDOW_SECONDS = 600;
const GLOBAL_DAILY_MAX = 200;

const PROVIDER_URL = "https://api.brevo.com/v3/smtp/email";
const PROVIDER_TIMEOUT_MS = 10000;

/** A validated, normalized report ready for delivery. */
interface Report {
  app_version: string;
  platform: Record<string, string>;
  description: string;
  contact: string | null;
  logs: string | null;
}

/** Internal error carrying the HTTP status and non-secret relay code. */
class RelayError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(code);
    this.name = "RelayError";
    this.status = status;
    this.code = code;
  }
}

function jsonResponse(body: Record<string, unknown>, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function fail(status: number, code: string): Response {
  return jsonResponse({ ok: false, code }, status);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function utf8ByteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

/** Normalize an optional string field: empty/whitespace/null all mean absent. */
function normalizeOptional(
  value: unknown,
  code: string,
): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value !== "string") {
    throw new RelayError(400, code);
  }
  const trimmed = value.trim();
  return trimmed.length === 0 ? null : value;
}

/** Validate the raw body against the exact contract; throw `RelayError` otherwise. */
function validateReport(raw: unknown): Report {
  if (!isPlainObject(raw)) {
    throw new RelayError(400, "relay.invalid_payload");
  }
  for (const key of Object.keys(raw)) {
    if (!ALLOWED_FIELDS.has(key)) {
      throw new RelayError(400, "relay.invalid_payload");
    }
  }
  if (raw.schema !== RELAY_SCHEMA) {
    throw new RelayError(400, "relay.unsupported_schema");
  }

  const appVersion = typeof raw.app_version === "string" ? raw.app_version : "";
  const description = typeof raw.description === "string" ? raw.description : "";

  const platformRaw = raw.platform ?? {};
  if (!isPlainObject(platformRaw)) {
    throw new RelayError(400, "relay.invalid_payload");
  }
  const platform: Record<string, string> = {};
  for (const [key, value] of Object.entries(platformRaw)) {
    if (!ALLOWED_PLATFORM_KEYS.has(key)) {
      throw new RelayError(400, "relay.invalid_payload");
    }
    if (typeof value !== "string") {
      throw new RelayError(400, "relay.invalid_payload");
    }
    platform[key] = value;
  }

  const contact = normalizeOptional(raw.contact, "relay.invalid_payload");
  const logs = normalizeOptional(raw.logs, "relay.invalid_payload");

  if (description.length > DESCRIPTION_MAX_CHARS) {
    throw new RelayError(413, "relay.too_large");
  }
  if (contact !== null && contact.length > CONTACT_MAX_CHARS) {
    throw new RelayError(413, "relay.too_large");
  }
  if (logs !== null && logs.length > LOGS_MAX_CHARS) {
    throw new RelayError(413, "relay.too_large");
  }
  if (utf8ByteLength(JSON.stringify(raw)) > PAYLOAD_MAX_BYTES) {
    throw new RelayError(413, "relay.too_large");
  }

  return {
    app_version: appVersion,
    platform,
    description,
    contact,
    logs,
  };
}

/** Best-effort client IP for the per-IP bucket. */
function clientIp(request: Request): string {
  return (
    request.headers.get("CF-Connecting-IP") ??
    request.headers.get("X-Forwarded-For") ??
    "unknown"
  );
}

function utcDayKey(now: Date): string {
  return `global:${now.toISOString().slice(0, 10)}`;
}

function buildSubject(report: Report): string {
  const version = report.app_version || "unknown";
  return `[Demiurgos] Bug report — ${version}`;
}

function buildBody(report: Report, attribution: Attribution): string {
  const platform = Object.entries(report.platform)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
  return [
    "Demiurgos bug report",
    "",
    `App version: ${report.app_version || "(unknown)"}`,
    `Platform: ${platform || "(none)"}`,
    `Reported by: ${attribution.line}`,
    `Contact: ${report.contact ?? "(not provided)"}`,
    "",
    "Description:",
    report.description || "(empty)",
    "",
    "Logs (already content-scanned by the client):",
    report.logs ?? "(none)",
  ].join("\n");
}

/**
 * Forward one report to the provider. Throws `RelayError` with a non-secret
 * code on timeout, network failure, or a non-2xx provider response. The
 * provider response body is never propagated to the caller.
 */
async function sendViaProvider(
  env: Env,
  report: Report,
  attribution: Attribution,
): Promise<string> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROVIDER_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(PROVIDER_URL, {
      method: "POST",
      headers: {
        "api-key": env.BREVO_API_KEY,
        "content-type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({
        sender: { email: env.SENDER_FROM },
        to: [{ email: env.OWNER_INBOX }],
        subject: buildSubject(report),
        textContent: buildBody(report, attribution),
      }),
      signal: controller.signal,
    });
  } catch {
    throw new RelayError(502, "relay.provider_unreachable");
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    throw new RelayError(502, "relay.provider_rejected");
  }

  let messageId = "";
  try {
    const data = (await response.json()) as Record<string, unknown>;
    if (typeof data.messageId === "string") {
      messageId = data.messageId;
    }
  } catch {
    // A 2xx with a non-JSON body still means the provider accepted it.
  }
  return messageId || crypto.randomUUID();
}

/** Identity routes. All POST: a ticket must never travel in a URL or a log. */
const LINK_PATHS = new Set(["/link/start", "/link/status", "/link/revoke"]);

/**
 * Identity endpoints. The caller must present the shared `x-relay-key`: an
 * unauthenticated caller could otherwise mint a ticket for somebody else's
 * account key and bind an attacker-controlled Telegram account to it.
 */
async function handleLink(
  request: Request,
  env: Env,
  path: string,
): Promise<Response> {
  if (!env.LINKS || !env.RELAY_KEY) {
    return fail(500, "relay.not_configured");
  }
  if ((request.headers.get("x-relay-key") ?? "") !== env.RELAY_KEY) {
    return fail(401, "relay.unauthorized");
  }
  if (request.method !== "POST") {
    return fail(405, "relay.method_not_allowed");
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return fail(400, "relay.invalid_payload");
  }
  if (!isPlainObject(body)) {
    return fail(400, "relay.invalid_payload");
  }

  try {
    if (path === "/link/start") {
      if (typeof body.account_key !== "string") {
        return fail(400, "link.invalid_account");
      }
      // An omitted flag stays omitted. Coercing it to `true` here would make a
      // reused ticket silently re-enable a permission the account had turned off.
      for (const flag of ["report_identity", "notify_releases"] as const) {
        if (body[flag] !== undefined && typeof body[flag] !== "boolean") {
          return fail(400, "relay.invalid_payload");
        }
      }
      const started = await startLink(
        env.LINKS,
        {
          account_key: body.account_key,
          report_identity:
            typeof body.report_identity === "boolean" ? body.report_identity : undefined,
          notify_releases:
            typeof body.notify_releases === "boolean" ? body.notify_releases : undefined,
        },
        new Date(),
      );
      return jsonResponse(
        {
          ok: true,
          ticket: started.ticket,
          expires_at: started.expires_at,
          reused: started.reused,
        },
        200,
      );
    }

    if (path === "/link/status") {
      if (typeof body.ticket !== "string") {
        return fail(400, "link.ticket_invalid");
      }
      const status = await linkStatus(env.LINKS, body.ticket, new Date());
      return jsonResponse({ ok: true, ...status }, 200);
    }

    if (typeof body.account_key !== "string") {
      return fail(400, "link.invalid_account");
    }
    const revoked = await revokeLink(env.LINKS, body.account_key);
    return jsonResponse({ ok: true, revoked }, 200);
  } catch (error) {
    if (error instanceof LinkError) {
      return fail(error.status, error.code);
    }
    return fail(500, "link.failed");
  }
}

/**
 * Telegram webhook. Authenticated by the secret header Telegram echoes, not by
 * the backend key: the caller here is Telegram, not the app.
 */
async function handleWebhook(request: Request, env: Env): Promise<Response> {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_WEBHOOK_SECRET || !env.LINKS) {
    return fail(500, "relay.not_configured");
  }
  if (
    (request.headers.get("x-telegram-bot-api-secret-token") ?? "") !==
    env.TELEGRAM_WEBHOOK_SECRET
  ) {
    return fail(401, "relay.unauthorized");
  }
  if (request.method !== "POST") {
    return fail(405, "relay.method_not_allowed");
  }

  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return fail(400, "relay.invalid_payload");
  }

  try {
    await handleTelegramUpdate(raw, {
      TELEGRAM_BOT_TOKEN: env.TELEGRAM_BOT_TOKEN,
      TELEGRAM_WEBHOOK_SECRET: env.TELEGRAM_WEBHOOK_SECRET,
      LINKS: env.LINKS,
    });
  } catch {
    // A handled update must not be redelivered; the user simply sees no reply.
    return jsonResponse({ ok: true }, 200);
  }
  return jsonResponse({ ok: true }, 200);
}

export default {
  async fetch(
    request: Request,
    env: Env,
    _ctx: ExecutionContext,
  ): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/telegram/webhook") {
      return handleWebhook(request, env);
    }
    if (LINK_PATHS.has(url.pathname)) {
      return handleLink(request, env, url.pathname);
    }
    if (url.pathname !== "/") {
      return fail(404, "relay.not_found");
    }
    if (request.method !== "POST") {
      return fail(405, "relay.method_not_allowed");
    }

    // Config fail-closed: neither sink is configured, so nothing could be
    // delivered and the caller would see a success that never happened.
    const telegramSink = Boolean(env.TELEGRAM_CHAT_ID && env.TELEGRAM_BOT_TOKEN);
    const emailSink = Boolean(env.BREVO_API_KEY && env.OWNER_INBOX && env.SENDER_FROM);
    if (!telegramSink && !emailSink) {
      return fail(500, "relay.not_configured");
    }

    let raw: unknown;
    try {
      raw = await request.json();
    } catch {
      return fail(400, "relay.invalid_payload");
    }

    let report: Report;
    try {
      report = validateReport(raw);
    } catch (error) {
      if (error instanceof RelayError) {
        return fail(error.status, error.code);
      }
      return fail(400, "relay.invalid_payload");
    }

    const now = new Date();
    const installToken = (request.headers.get("x-install-token") ?? "").trim();

    // A revoked install must not keep reporting through the credential the
    // revoke just killed; only callers presenting a credential are checked, so
    // an unbound namespace never blocks the anonymous fallback path.
    //
    // A store that *fails* is refused, not assumed clean: the same fail-closed
    // posture as the counters. S14's copy-paste/GitHub fallback is what keeps a
    // reporter unblocked when the relay cannot answer.
    let attribution: Attribution;
    try {
      if (installToken.length > 0 && env.LINKS) {
        if (await isBlockedInstall(env.LINKS, installToken)) {
          return fail(403, "relay.report_blocked");
        }
      }

      // Who is reporting is resolved here, from a credential the relay issued —
      // never from a claim in the body. A missing, unknown or revoked token
      // simply falls back to what the reporter typed.
      attribution = await resolveAttribution(
        env.LINKS,
        installToken.length === 0 ? null : installToken,
        report.contact,
        ownerTelegramIds(env.OWNER_TELEGRAM_USER_IDS),
      );
    } catch {
      return fail(503, "relay.rate_limit_unavailable");
    }

    // Dedup first: an accidental double submit must not spend the reporter's
    // allowance, and it must not open a second topic for the same failure.
    let admission: Awaited<ReturnType<typeof admitReport>>;
    try {
      admission = await admitReport(
        env.RATE_LIMIT,
        report,
        attribution.identity?.account_key ?? null,
        now,
      );
    } catch {
      // Abuse control fails CLOSED, never open.
      return fail(503, "relay.rate_limit_unavailable");
    }
    if (admission.verdict === "duplicate") {
      return jsonResponse(
        { ok: true, delivery_id: admission.deliveryId, deduped: true },
        200,
      );
    }
    if (admission.verdict === "limited") {
      return fail(429, admission.code);
    }

    // Linked principals are bounded by their own buckets; unlinked reporters
    // keep the per-IP and global-daily ceilings.
    if (attribution.identity === null) {
      try {
        const perIp = await bumpCounter(
          env.RATE_LIMIT,
          `ip:${clientIp(request)}`,
          PER_IP_WINDOW_SECONDS,
        );
        if (perIp > PER_IP_MAX) {
          return fail(429, "relay.rate_limited");
        }
        const daily = await bumpCounter(
          env.RATE_LIMIT,
          utcDayKey(now),
          secondsUntilUtcMidnight(now),
        );
        if (daily > GLOBAL_DAILY_MAX) {
          return fail(429, "relay.rate_limited");
        }
      } catch {
        return fail(503, "relay.rate_limit_unavailable");
      }
    }

    let deliveryId: string;
    try {
      if (telegramSink && env.TELEGRAM_CHAT_ID) {
        deliveryId = crypto.randomUUID();
        await publishReport(
          {
            TELEGRAM_BOT_TOKEN: env.TELEGRAM_BOT_TOKEN,
            TELEGRAM_CHAT_ID: env.TELEGRAM_CHAT_ID,
          },
          { ...report, attribution },
          deliveryId,
        );
      } else {
        deliveryId = await sendViaProvider(env, report, attribution);
      }
    } catch (error) {
      if (error instanceof RelayError) {
        return fail(error.status, error.code);
      }
      return fail(502, "relay.delivery_failed");
    }

    // Only a delivered report is remembered: a failed one must be retryable.
    try {
      await rememberReport(env.RATE_LIMIT, admission.fingerprint, deliveryId);
    } catch {
      console.error("dedup.write_failed");
    }

    return jsonResponse({ ok: true, delivery_id: deliveryId }, 200);
  },
} satisfies ExportedHandler<Env>;
