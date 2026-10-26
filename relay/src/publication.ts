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

/** The message shown in the topic: what fits, with the rest in the document. */
export function summaryText(report: PublishableReport): string {
  const platform = Object.entries(report.platform)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
  const header = [
    `🐞 v${report.app_version === "" ? "unknown" : report.app_version}`,
    platform === "" ? null : `🖥️ ${platform}`,
    report.attribution.line,
  ].filter((line): line is string => line !== null);
  const body = report.description.trim() === "" ? "(sin descripción)" : report.description;
  return truncate([...header, "", body].join("\n"), SUMMARY_MAX);
}

/** The complete report, delivered as a document so nothing is truncated. */
export function bundleText(report: PublishableReport, reportId: string): string {
  const platform = Object.entries(report.platform)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
  return [
    "Demiurgos bug report",
    "",
    `Report id: ${reportId}`,
    `App version: ${report.app_version || "(unknown)"}`,
    `Platform: ${platform || "(none)"}`,
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
