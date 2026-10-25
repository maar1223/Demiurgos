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

/** Server-side bindings and secrets. Values are configured, never committed. */
export interface Env {
  /** KV namespace backing the per-IP + global-daily rate-limit counters. */
  RATE_LIMIT: KVNamespace;
  /**
   * KV namespace holding linked Telegram identities (`identity:tg:*` records and
   * `identity:principal:*` pointers). Kept apart from `RATE_LIMIT` because these
   * entries are personal data with no TTL, not disposable counters.
   */
  LINKS: KVNamespace;
  /** Provider API key (Worker secret). Never logged or returned. */
  BREVO_API_KEY: string;
  /** Fixed Owner inbox that receives every report (Worker secret/variable). */
  OWNER_INBOX: string;
  /** Verified sender address, e.g. `reports@your-verified-domain` (secret). */
  SENDER_FROM: string;
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

/** Read-increment-write one counter in the `RATE_LIMIT` KV namespace. */
async function bumpCounter(
  kv: KVNamespace,
  key: string,
  ttlSeconds: number,
): Promise<number> {
  const raw = await kv.get(key);
  const current = raw === null ? 0 : Number.parseInt(raw, 10);
  const next = (Number.isFinite(current) ? current : 0) + 1;
  await kv.put(key, String(next), {
    expirationTtl: Math.max(60, Math.ceil(ttlSeconds)),
  });
  return next;
}

function utcDayKey(now: Date): string {
  return `global:${now.toISOString().slice(0, 10)}`;
}

function secondsUntilUtcMidnight(now: Date): number {
  const next = Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate() + 1,
    0,
    0,
    0,
    0,
  );
  return (next - now.getTime()) / 1000;
}

function buildSubject(report: Report): string {
  const version = report.app_version || "unknown";
  return `[Demiurgos] Bug report — ${version}`;
}

function buildBody(report: Report): string {
  const platform = Object.entries(report.platform)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
  return [
    "Demiurgos bug report",
    "",
    `App version: ${report.app_version || "(unknown)"}`,
    `Platform: ${platform || "(none)"}`,
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
async function sendViaProvider(env: Env, report: Report): Promise<string> {
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
        textContent: buildBody(report),
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

export default {
  async fetch(
    request: Request,
    env: Env,
    _ctx: ExecutionContext,
  ): Promise<Response> {
    if (request.method !== "POST") {
      return fail(405, "relay.method_not_allowed");
    }

    // Config fail-closed: a missing secret never reaches the provider.
    if (!env.BREVO_API_KEY || !env.OWNER_INBOX || !env.SENDER_FROM) {
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
      // A rate-limit backend failure must fail CLOSED, never open.
      return fail(503, "relay.rate_limit_unavailable");
    }

    try {
      const deliveryId = await sendViaProvider(env, report);
      return jsonResponse({ ok: true, delivery_id: deliveryId }, 200);
    } catch (error) {
      if (error instanceof RelayError) {
        return fail(error.status, error.code);
      }
      return fail(502, "relay.delivery_failed");
    }
  },
} satisfies ExportedHandler<Env>;
