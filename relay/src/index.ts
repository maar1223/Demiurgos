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

import { admitCounter } from "./counters.ts";
import {
  admitReport,
  installDigest,
  rememberReport,
  secondsUntilUtcMidnight,
} from "./abuse.ts";
import { isBlockedInstall, readIdentityByInstallToken } from "./identity.ts";
import {
  LinkError,
  linkStatus,
  revokeLink,
  startLink,
  type StartLinkRequest,
} from "./linking.ts";
import { handleTelegramUpdate } from "./telegram.ts";
import {
  ATTACHMENTS_MAX,
  ATTACHMENT_MAX_BYTES,
  ATTACHMENT_TYPES,
  attachmentName,
  publishReport,
  sniffImageType,
  type ReportAttachment,
} from "./publication.ts";
import { ownerTelegramIds, resolveAttribution, type Attribution } from "./attribution.ts";
import { normalizeRelease, readReleases, recordRelease } from "./release.ts";

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

/**
 * Wire contract versions this relay understands, newest first.
 *
 * 2 adds the `context` block (where in the app the bug happened). Both are
 * accepted so a backend that still speaks 1 keeps delivering while the relay is
 * rolled out ahead of it: a version mismatch here would drop reports, and a
 * dropped report is worse than a report without context.
 */
const RELAY_SCHEMAS = new Set([1, 2]);

/** The only top-level keys the contract allows. */
const ALLOWED_FIELDS = new Set([
  "schema",
  "app_version",
  "platform",
  "description",
  "contact",
  "logs",
  "context",
]);

/** The only platform facts the contract allows. */
const ALLOWED_PLATFORM_KEYS = new Set([
  "os",
  "os_version",
  "arch",
  "python_version",
]);

/** Where in the app a report came from (schema 2). */
const ALLOWED_CONTEXT_KEYS = new Set(["route", "view", "ui_area", "world_id"]);

// Size caps — kept identical to the backend caps in `bug_report.py` so the
// relay is never the weaker link in the validation chain.
const DESCRIPTION_MAX_CHARS = 4000;
const CONTACT_MAX_CHARS = 200;
const LOGS_MAX_CHARS = 65536;
const CONTEXT_VALUE_MAX_CHARS = 200;
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
  /** Where in the app it happened; empty on a schema-1 client. */
  context: Record<string, string>;
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
  if (typeof raw.schema !== "number" || !RELAY_SCHEMAS.has(raw.schema)) {
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

  const contextRaw = raw.context ?? {};
  if (!isPlainObject(contextRaw)) {
    throw new RelayError(400, "relay.invalid_payload");
  }
  const context: Record<string, string> = {};
  for (const [key, value] of Object.entries(contextRaw)) {
    if (!ALLOWED_CONTEXT_KEYS.has(key) || typeof value !== "string") {
      throw new RelayError(400, "relay.invalid_payload");
    }
    if (value.length > CONTEXT_VALUE_MAX_CHARS) {
      throw new RelayError(413, "relay.too_large");
    }
    if (value.trim().length > 0) {
      context[key] = value;
    }
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
    context,
    contact,
    logs,
  };
}

interface ParsedReportBody {
  raw: unknown;
  attachments: ReportAttachment[];
}

/**
 * Read a report from either a JSON body (no attachments) or a multipart body
 * carrying the JSON in a `report` part plus up to two screenshots.
 *
 * Attachments never travel inside the JSON: the bundle is size-capped at 98 KB,
 * and base64 would both break that cap and make the report harder to audit. They
 * are delivered as documents, never as photos, so Telegram does not recompress
 * a screenshot into uselessness.
 */
async function readReportBody(request: Request): Promise<ParsedReportBody> {
  const contentType = (request.headers.get("content-type") ?? "")
    .split(";")[0]
    .trim()
    .toLowerCase();
  if (contentType !== "multipart/form-data") {
    return { raw: await request.json(), attachments: [] };
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    throw new RelayError(400, "relay.invalid_payload");
  }
  const report = form.get("report");
  if (typeof report !== "string") {
    throw new RelayError(400, "relay.invalid_payload");
  }
  let raw: unknown;
  try {
    raw = JSON.parse(report);
  } catch {
    throw new RelayError(400, "relay.invalid_payload");
  }

  const entries = form.getAll("attachments");
  // A part with an empty filename is parsed as a plain string: dropping it
  // silently would accept a report whose attachment never arrives.
  for (const entry of entries) {
    if (typeof File === "undefined" || !(entry instanceof File)) {
      throw new RelayError(400, "relay.invalid_attachment");
    }
  }
  const files = entries as File[];
  if (files.length > ATTACHMENTS_MAX) {
    throw new RelayError(413, "relay.too_large");
  }

  const attachments: ReportAttachment[] = [];
  for (const [index, file] of files.entries()) {
    if (file.size === 0) {
      throw new RelayError(400, "relay.invalid_attachment");
    }
    if (file.size > ATTACHMENT_MAX_BYTES) {
      throw new RelayError(413, "relay.too_large");
    }
    const bytes = await file.arrayBuffer();
    // The bytes decide the type, not the client's claim about it.
    const type = sniffImageType(bytes);
    if (type === null || !ATTACHMENT_TYPES.has(type)) {
      throw new RelayError(400, "relay.invalid_attachment");
    }
    attachments.push({
      name: attachmentName(file.name, index, type),
      type,
      bytes,
    });
  }
  return { raw, attachments };
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

function buildBody(
  report: Report,
  attribution: Attribution,
  attachmentCount = 0,
  pseudonym: string | null = null,
): string {
  const platform = Object.entries(report.platform)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
  const context = Object.entries(report.context)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
  return [
    "Demiurgos bug report",
    "",
    `App version: ${report.app_version || "(unknown)"}`,
    `Platform: ${platform || "(none)"}`,
    ...(context === "" ? [] : [`Where: ${context}`]),
    `Reported by: ${attribution.line}`,
    ...(pseudonym === null ? [] : [`Install: ${pseudonym}`]),
    `Contact: ${report.contact ?? "(not provided)"}`,
    // The email channel carries text only; a dropped attachment is stated, so
    // nobody believes a screenshot arrived when it did not.
    ...(attachmentCount === 0
      ? []
      : [`Attachments: ${attachmentCount} (not delivered over email)`]),
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
  attachmentCount = 0,
  pseudonym: string | null = null,
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
        textContent: buildBody(report, attribution, attachmentCount, pseudonym),
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
const LINK_PATHS = new Set(["/link/start", "/link/status", "/link/state", "/link/revoke"]);

/** Ticket mints one IP may attempt per hour (on top of 3/hour per account). */
const LINK_START_IP_MAX = 10;

/**
 * Ticket polls one IP may make per hour. The panel polls every 2 s while a
 * ticket is live (about 300 per ticket), so this bounds a brute-force search
 * without ever throttling a real scan.
 */
const LINK_POLL_IP_MAX = 1200;

const LINK_IP_WINDOW_SECONDS = 3600;

/**
 * Identity endpoints for the CLIENT (S19).
 *
 * No shared key: a released install cannot carry one, and `RELAY_KEY` would then
 * let anyone mint tickets or revoke somebody else's link. Each route instead
 * uses the credential that install already holds:
 *
 *   - `/link/start` and `/link/status` are open, bounded per IP — the ticket is
 *     random, single-use and short-lived, so it is its own bearer.
 *   - `/link/state` and `/link/revoke` require the `x-install-token` the relay
 *     issued at the handover, so an install can only read or revoke its own
 *     link. A guessed account key reveals nothing.
 *
 * The administrative side (`/release`) keeps `x-relay-key`.
 */
async function handleLink(
  request: Request,
  env: Env,
  path: string,
): Promise<Response> {
  if (!env.LINKS) {
    return fail(500, "relay.not_configured");
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
      const limited = await ipBudget(env, request, "linkstart", LINK_START_IP_MAX);
      if (limited !== null) {
        return limited;
      }
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
      const limited = await ipBudget(env, request, "linkpoll", LINK_POLL_IP_MAX);
      if (limited !== null) {
        return limited;
      }
      if (typeof body.ticket !== "string") {
        return fail(400, "link.ticket_invalid");
      }
      const status = await linkStatus(env.LINKS, body.ticket, new Date());
      return jsonResponse({ ok: true, ...status }, 200);
    }

    // The self-service half: possession of the install token is the proof, so
    // no account key travels and no handle can be read by asking.
    const presented = (request.headers.get("x-install-token") ?? "").trim();
    if (presented.length === 0) {
      return fail(401, "relay.unauthorized");
    }
    const identity = await readIdentityByInstallToken(env.LINKS, presented);

    if (path === "/link/state") {
      // Only what the connected state renders leaves the store: never the
      // account key, the numeric Telegram id, the bot bookkeeping or a
      // credential (the install token was spent once, at redemption).
      if (identity === null) {
        return jsonResponse({ ok: true, state: "unlinked" }, 200);
      }
      return jsonResponse(
        {
          ok: true,
          state: "linked",
          identity: {
            username: identity.username,
            display_name: identity.display_name,
            permissions: identity.permissions,
          },
        },
        200,
      );
    }

    // An unknown or revoked token revokes nothing and says so; that keeps the
    // call idempotent without disclosing whether the account key exists.
    const revoked =
      identity === null ? false : await revokeLink(env.LINKS, identity.account_key);
    return jsonResponse({ ok: true, revoked }, 200);
  } catch (error) {
    if (error instanceof LinkError) {
      return fail(error.status, error.code);
    }
    return fail(500, "link.failed");
  }
}

/**
 * Per-IP budget for the routes that cannot require a credential. A counter
 * backend that fails REFUSES the call: the same fail-closed posture as reports.
 */
async function ipBudget(
  env: Env,
  request: Request,
  prefix: string,
  max: number,
): Promise<Response | null> {
  try {
    const allowed = await admitCounter(
      env.RATE_LIMIT,
      `${prefix}:ip:${clientIp(request)}`,
      LINK_IP_WINDOW_SECONDS,
      max,
    );
    return allowed ? null : fail(429, "link.rate_limited");
  } catch {
    return fail(503, "relay.rate_limit_unavailable");
  }
}

/**
 * Release records: "version X fixed reports A, B" (S12).
 *
 * Reading the list is PUBLIC on purpose: it carries versions and report ids,
 * never a reporter, and every install needs it to show "this was fixed" without
 * linking anything (S19). Writing it still needs the shared `x-relay-key`.
 * Nothing personal is stored, which is what keeps the in-app notice free of a
 * person→report mapping.
 */
async function handleRelease(
  request: Request,
  env: Env,
  path: string,
): Promise<Response> {
  if (!env.LINKS) {
    return fail(500, "relay.not_configured");
  }
  if (request.method !== "POST") {
    return fail(405, "relay.method_not_allowed");
  }
  if (path === "/release") {
    if (!env.RELAY_KEY) {
      return fail(500, "relay.not_configured");
    }
    if ((request.headers.get("x-relay-key") ?? "") !== env.RELAY_KEY) {
      return fail(401, "relay.unauthorized");
    }
  }

  if (path === "/releases") {
    return jsonResponse({ ok: true, releases: await readReleases(env.LINKS) }, 200);
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return fail(400, "relay.invalid_payload");
  }
  let release: { version: string; report_ids: string[] };
  try {
    release = normalizeRelease(body);
  } catch (error) {
    const code = error instanceof Error ? error.message : "release.invalid_payload";
    return fail(code === "release.too_large" ? 413 : 400, code);
  }
  const releases = await recordRelease(
    env.LINKS,
    release.version,
    release.report_ids,
    new Date(),
  );
  return jsonResponse(
    {
      ok: true,
      version: release.version,
      report_ids: release.report_ids,
      releases: releases.length,
    },
    200,
  );
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

/**
 * Remember a delivered report for dedup, retrying once.
 *
 * The report has already reached the group, so this write is the only thing
 * keeping the same failure from opening a second topic inside 24 h. One
 * transient KV error is worth a retry; if both attempts fail the request still
 * answers success, because telling the reporter it failed would invite a retry
 * that publishes the same report twice.
 */
async function rememberDeliveredReport(
  kv: KVNamespace,
  fingerprint: string,
  deliveryId: string,
): Promise<void> {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await rememberReport(kv, fingerprint, deliveryId);
      return;
    } catch {
      // Falls through to the second attempt.
    }
  }
  console.error("dedup.write_failed", deliveryId);
}

/** The pseudonym shape the backend mints (`install_` + 24 lowercase hex). */
const INSTALL_ID = /^install_[0-9a-f]{24}$/;

interface ReporterLabel {
  /** What the group shows: a short digest prefix plus the accepted count. */
  label: string;
  /** The count INCLUDING the report being published now. */
  count: number;
  /** KV key of the cumulative counter, written only after a delivery. */
  key: string;
}

/**
 * Label for the optional install pseudonym, counting the current report (S20).
 *
 * The counter is cumulative and has no TTL: it is how the Owner sees who is
 * finding the most bugs without knowing who they are. Only the digest is
 * stored, and a forged id would have to guess a 96-bit value.
 */
async function readReporterLabel(
  kv: KVNamespace,
  installId: string,
): Promise<ReporterLabel> {
  const digest = await installDigest(installId);
  const key = `reporter:${digest}`;
  const raw = await kv.get(key);
  const previous = raw !== null && /^[0-9]{1,9}$/.test(raw) ? Number(raw) : 0;
  const count = previous + 1;
  const noun = count === 1 ? "reporte" : "reportes";
  return { label: `instalación ${digest.slice(0, 4)} · ${count} ${noun}`, count, key };
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
    if (url.pathname === "/release" || url.pathname === "/releases") {
      return handleRelease(request, env, url.pathname);
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

    let body: ParsedReportBody;
    try {
      body = await readReportBody(request);
    } catch (error) {
      if (error instanceof RelayError) {
        return fail(error.status, error.code);
      }
      return fail(400, "relay.invalid_payload");
    }
    const raw = body.raw;

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
        body.attachments.map((attachment) => attachment.bytes),
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

    // Linked principals are bounded by their own buckets — including the ones
    // that declined to sign, since declining a signature is not a way out of the
    // bounds. Anonymous reporters keep the per-IP and global-daily ceilings.
    if (attribution.identity === null) {
      try {
        const perIp = await admitCounter(
          env.RATE_LIMIT,
          `ip:${clientIp(request)}`,
          PER_IP_WINDOW_SECONDS,
          PER_IP_MAX,
        );
        if (!perIp) {
          return fail(429, "relay.rate_limited");
        }
        const daily = await admitCounter(
          env.RATE_LIMIT,
          utcDayKey(now),
          secondsUntilUtcMidnight(now),
          GLOBAL_DAILY_MAX,
        );
        if (!daily) {
          return fail(429, "relay.rate_limited");
        }
      } catch {
        return fail(503, "relay.rate_limit_unavailable");
      }
    }

    // The optional install pseudonym (S20). Cosmetic and never a credential: a
    // store hiccup drops the line instead of the report, and the counter is only
    // written once the report actually reached its sink.
    const installId = (request.headers.get("x-install-id") ?? "").trim();
    let reporter: ReporterLabel | null = null;
    if (INSTALL_ID.test(installId)) {
      try {
        reporter = await readReporterLabel(env.RATE_LIMIT, installId);
      } catch {
        reporter = null;
      }
    }
    const pseudonym = reporter === null ? null : reporter.label;

    let deliveryId: string;
    try {
      if (telegramSink && env.TELEGRAM_CHAT_ID) {
        deliveryId = crypto.randomUUID();
        await publishReport(
          {
            TELEGRAM_BOT_TOKEN: env.TELEGRAM_BOT_TOKEN,
            TELEGRAM_CHAT_ID: env.TELEGRAM_CHAT_ID,
          },
          { ...report, attribution, pseudonym },
          deliveryId,
          body.attachments,
        );
      } else {
        deliveryId = await sendViaProvider(
          env,
          report,
          attribution,
          body.attachments.length,
          pseudonym,
        );
      }
    } catch (error) {
      if (error instanceof RelayError) {
        return fail(error.status, error.code);
      }
      return fail(502, "relay.delivery_failed");
    }

    if (reporter !== null) {
      try {
        await env.RATE_LIMIT.put(reporter.key, String(reporter.count));
      } catch {
        console.error("reporter.count_failed");
      }
    }

    // Only a delivered report is remembered: a failed one must be retryable.
    await rememberDeliveredReport(env.RATE_LIMIT, admission.fingerprint, deliveryId);

    return jsonResponse({ ok: true, delivery_id: deliveryId }, 200);
  },
} satisfies ExportedHandler<Env>;
