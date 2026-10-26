/**
 * Publication of one report into the Telegram triage group.
 *
 * Each report opens its own forum topic, so the group stays readable and every
 * bug keeps a thread for follow-up. The topic gets a short summary message plus
 * the complete report as a `.txt` document: Telegram caps a message at 4096
 * characters, and the logs alone can be 65536, so the document is the only way
 * to deliver the full bundle without truncating it.
 *
 * Degradation is deliberate: if the chat is a plain group, or the bot lacks the
 * topic permission, the report is still delivered — into the group without a
 * thread — instead of being lost.
 */

import type { Attribution } from "./attribution.ts";

const TELEGRAM_API = "https://api.telegram.org";

/** Screenshot attachments ride the same document path, capped by the client. */
export const ATTACHMENTS_MAX = 2;
export const ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024;
export const ATTACHMENT_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const ATTACHMENT_NAME_MAX = 64;

/** One user-chosen screenshot, already validated by the caller. */
export interface ReportAttachment {
  name: string;
  type: string;
  bytes: ArrayBuffer;
}
const REQUEST_TIMEOUT_MS = 10000;
const TOPIC_NAME_MAX = 128;
const SUMMARY_MAX = 3800;

export interface PublicationEnv {
  TELEGRAM_BOT_TOKEN: string;
  /** Supergroup id, for example `-1001234567890`. */
  TELEGRAM_CHAT_ID: string;
}

/** The wire report, already validated by the caller. */
export interface PublishableReport {
  app_version: string;
  platform: Record<string, string>;
  description: string;
  contact: string | null;
  logs: string | null;
  /** Where in the app it happened; empty when the client sent none. */
  context: Record<string, string>;
  /**
   * Who sent it and how that was established. Required on purpose: every
   * delivery path must state it, and the compiler refuses a report that forgot.
   */
  attribution: Attribution;
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

/**
 * Forum topic names are capped by Telegram and cannot be empty.
 *
 * The attribution tag leads, so truncation can only ever cut the name, never
 * the statement of how the identity was established: a typed `@handle` and a
 * Telegram-verified one never produce the same topic.
 */
export function topicName(report: PublishableReport): string {
  const version = report.app_version === "" ? "unknown" : report.app_version;
  const { tag, label } = report.attribution;
  const who = label === tag || label.length === 0 ? tag : `${tag} · ${label}`;
  return truncate(`BUG · v${version} · ${who}`, TOPIC_NAME_MAX);
}

/** `key=value` pairs in their original order, or an empty string. */
function pairs(values: Record<string, string>): string {
  return Object.entries(values)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
}

/** The message shown in the topic: what fits, with the rest in the document. */
export function summaryText(report: PublishableReport): string {
  const platform = pairs(report.platform);
  const context = pairs(report.context);
  const header = [
    `🐞 v${report.app_version === "" ? "unknown" : report.app_version}`,
    platform === "" ? null : `🖥️ ${platform}`,
    context === "" ? null : `🧭 ${context}`,
    report.attribution.line,
  ].filter((line): line is string => line !== null);
  const body = report.description.trim() === "" ? "(sin descripción)" : report.description;
  return truncate([...header, "", body].join("\n"), SUMMARY_MAX);
}

/** The complete report, delivered as a document so nothing is truncated. */
export function bundleText(report: PublishableReport, reportId: string): string {
  const platform = pairs(report.platform);
  const context = pairs(report.context);
  return [
    "Demiurgos bug report",
    "",
    `Report id: ${reportId}`,
    `App version: ${report.app_version || "(unknown)"}`,
    `Platform: ${platform || "(none)"}`,
    // Omitted when there is no context: a schema-1 report must keep the exact
    // document shape it had before, not gain a line saying "nothing here".
    ...(context === "" ? [] : [`Where: ${context}`]),
    `Reported by: ${report.attribution.line}`,
    `Contact: ${report.contact ?? "(not provided)"}`,
    "",
    "Description:",
    report.description || "(empty)",
    "",
    "Logs (already content-scanned by the client):",
    report.logs ?? "(none)",
  ].join("\n");
}

async function callTelegram(
  env: PublicationEnv,
  method: string,
  payload: Record<string, unknown>,
  fetchImpl: typeof fetch,
): Promise<Record<string, unknown>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetchImpl(
      `${TELEGRAM_API}/bot${env.TELEGRAM_BOT_TOKEN}/${method}`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      },
    );
    if (!response.ok) {
      throw new Error(`telegram.${method}.rejected`);
    }
    const data = (await response.json()) as { result?: unknown };
    const result = data.result;
    return typeof result === "object" && result !== null
      ? (result as Record<string, unknown>)
      : {};
  } finally {
    clearTimeout(timer);
  }
}

/**
 * The real image type, read from the bytes.
 *
 * A declared content type is a client claim: a renamed HTML file would pass it
 * and reach the group as a document. The magic bytes are what the file actually
 * is, so they decide — and a mismatch is corrected rather than trusted.
 */
export function sniffImageType(bytes: ArrayBuffer): string | null {
  const view = new Uint8Array(bytes);
  if (
    view.length >= 8 &&
    view[0] === 0x89 && view[1] === 0x50 && view[2] === 0x4e && view[3] === 0x47 &&
    view[4] === 0x0d && view[5] === 0x0a && view[6] === 0x1a && view[7] === 0x0a
  ) {
    return "image/png";
  }
  if (view.length >= 3 && view[0] === 0xff && view[1] === 0xd8 && view[2] === 0xff) {
    return "image/jpeg";
  }
  if (
    view.length >= 12 &&
    view[0] === 0x52 && view[1] === 0x49 && view[2] === 0x46 && view[3] === 0x46 &&
    view[8] === 0x57 && view[9] === 0x45 && view[10] === 0x42 && view[11] === 0x50
  ) {
    return "image/webp";
  }
  return null;
}

/** A filename safe to hand to Telegram: no paths, no control characters. */
export function attachmentName(raw: string, index: number, type: string): string {
  const base = raw.split(/[\\/]/).pop() ?? "";
  // Control characters AND the invisible ones that reorder text on screen: a
  // filename must render exactly as it reads.
  // eslint-disable-next-line no-control-regex
  const cleaned = base
    .replace(
      /[\u0000-\u001f\u007f-\u009f\u00ad\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff]/g,
      "",
    )
    .trim();
  const name = cleaned.length === 0 ? "" : cleaned.slice(0, ATTACHMENT_NAME_MAX);
  if (name.length > 0) {
    return name;
  }
  const extension = type === "image/jpeg" ? "jpg" : (type.split("/").pop() || "png");
  return `screenshot-${index + 1}.${extension}`;
}

/** Send one screenshot as a DOCUMENT, never as a photo: no recompression. */
async function sendAttachment(
  env: PublicationEnv,
  reportId: string,
  index: number,
  attachment: ReportAttachment,
  threadId: number | null,
  fetchImpl: typeof fetch,
): Promise<void> {
  const body = new FormData();
  body.set("chat_id", env.TELEGRAM_CHAT_ID);
  if (threadId !== null) {
    body.set("message_thread_id", String(threadId));
  }
  body.set("caption", truncate(`Captura ${index + 1} · ${reportId}`, 1024));
  body.set(
    "document",
    new Blob([attachment.bytes], { type: attachment.type }),
    attachment.name,
  );

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetchImpl(
      `${TELEGRAM_API}/bot${env.TELEGRAM_BOT_TOKEN}/sendDocument`,
      { method: "POST", body, signal: controller.signal },
    );
    if (!response.ok) {
      throw new Error("telegram.sendDocument.rejected");
    }
  } finally {
    clearTimeout(timer);
  }
}

async function sendBundle(
  env: PublicationEnv,
  reportId: string,
  text: string,
  attributionTag: string,
  threadId: number | null,
  fetchImpl: typeof fetch,
): Promise<void> {
  const body = new FormData();
  body.set("chat_id", env.TELEGRAM_CHAT_ID);
  if (threadId !== null) {
    body.set("message_thread_id", String(threadId));
  }
  body.set(
    "caption",
    truncate(`Reporte completo · ${reportId} · ${attributionTag}`, 1024),
  );
  body.set(
    "document",
    new Blob([text], { type: "text/plain;charset=utf-8" }),
    `report-${reportId}.txt`,
  );

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetchImpl(
      `${TELEGRAM_API}/bot${env.TELEGRAM_BOT_TOKEN}/sendDocument`,
      { method: "POST", body, signal: controller.signal },
    );
    if (!response.ok) {
      throw new Error("telegram.sendDocument.rejected");
    }
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Publish one report. Throws only when the report could not be delivered at
 * all; a missing forum topic degrades to a plain group message.
 */
export async function publishReport(
  env: PublicationEnv,
  report: PublishableReport,
  reportId: string,
  attachments: ReportAttachment[] = [],
  fetchImpl: typeof fetch = fetch,
): Promise<{ threadId: number | null }> {
  let threadId: number | null = null;
  try {
    const topic = await callTelegram(
      env,
      "createForumTopic",
      { chat_id: env.TELEGRAM_CHAT_ID, name: topicName(report) },
      fetchImpl,
    );
    const id = topic.message_thread_id;
    threadId = typeof id === "number" ? id : null;
  } catch {
    // A plain group, or no topic permission: keep going without a thread.
    threadId = null;
  }

  const message: Record<string, unknown> = {
    chat_id: env.TELEGRAM_CHAT_ID,
    text: summaryText(report),
    link_preview_options: { is_disabled: true },
  };
  if (threadId !== null) {
    message.message_thread_id = threadId;
  }
  await callTelegram(env, "sendMessage", message, fetchImpl);

  for (const [index, attachment] of attachments.entries()) {
    await sendAttachment(env, reportId, index, attachment, threadId, fetchImpl);
  }

  await sendBundle(
    env,
    reportId,
    bundleText(report, reportId),
    report.attribution.tag,
    threadId,
    fetchImpl,
  );

  return { threadId };
}
