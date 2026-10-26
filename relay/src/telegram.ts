/**
 * Telegram webhook handling for the reports bot.
 *
 * The bot is strictly one-way (Owner decision D2): it accepts exactly two
 * commands and never free text.
 *
 *   /start <ticket>   redeem a linking ticket, then say so
 *   /link/revoke      unlink the account and erase the stored identity
 *
 * Everything else is acknowledged with 200 and ignored. Telegram retries any
 * non-2xx answer, so an expected user-facing failure (expired ticket, ticket
 * already claimed) is answered **200 plus an explanatory message**, never an
 * error status — an error would make Telegram redeliver the same update.
 */

import { readIdentity, revokeIdentity, type KvLike } from "./identity.ts";
import { LinkError, redeemTicket } from "./linking.ts";

const TELEGRAM_API = "https://api.telegram.org";
const SEND_TIMEOUT_MS = 8000;

/** The subset of a Telegram update this bot reacts to. */
interface TelegramMessage {
  message_id?: number;
  chat?: { id?: number | string };
  from?: {
    id?: number | string;
    username?: string;
    first_name?: string;
    last_name?: string;
  };
  text?: string;
}

interface TelegramUpdate {
  update_id?: number;
  message?: TelegramMessage;
}

export interface TelegramEnv {
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_WEBHOOK_SECRET: string;
  LINKS: KvLike;
}

/** User-facing copy. Spanish is the product's primary language. */
const COPY = {
  welcome:
    "Para conectar tu cuenta, abre Demiurgos en Perfil, entra en Reporte de errores y pulsa Conectar Telegram. Yo te aviso por aquí cuando arreglemos lo que reportes.",
  linked: "Conectado. Te avisaré cuando arreglemos lo que reportes.",
  invalid:
    "Ese enlace ya no es válido. Genera uno nuevo desde Demiurgos, en Perfil.",
  consumed: "Ese enlace ya se usó con otra cuenta de Telegram.",
  revoked: "Desconectado. No volverás a recibir avisos por aquí.",
  nothing: "Esta cuenta no estaba conectada.",
} as const;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** `/start <ticket>` -> ticket. Anything else -> null. */
export function parseStartCommand(text: string): string | null {
  const match = /^\/start(?:@[A-Za-z0-9_]+)?\s+([0-9A-Za-z]{4,32})\s*$/.exec(text);
  return match === null ? null : match[1];
}

/**
 * A bare `/start`, which is what Telegram's own START button sends. It carries
 * no ticket, so it cannot link anything — but answering it is the difference
 * between "the bot is broken" and "here is the button you need to press".
 */
export function isBareStart(text: string): boolean {
  return /^\/start(?:@[A-Za-z0-9_]+)?\s*$/.test(text);
}

/** `/link/revoke` (optionally addressed to the bot) -> true. */
export function parseRevokeCommand(text: string): boolean {
  return /^\/link\/revoke(?:@[A-Za-z0-9_]+)?\s*$/.test(text);
}

/** Chat ids may be negative; user ids are always positive. */
const CHAT_ID = /^-?[1-9][0-9]{0,19}$/;
const USER_ID = /^[1-9][0-9]{0,19}$/;

/**
 * Read an id that Telegram sends as a number. Anything else — `null`, a
 * boolean, an object, a float — is not an id, and stringifying it would send a
 * message to a chat that does not exist.
 */
function idText(value: unknown): string | null {
  if (typeof value === "number") {
    return Number.isSafeInteger(value) ? String(value) : null;
  }
  return typeof value === "string" ? value : null;
}

function displayName(from: NonNullable<TelegramMessage["from"]>): string | null {
  const parts = [from.first_name, from.last_name].filter(
    (part): part is string => typeof part === "string" && part.trim().length > 0,
  );
  return parts.length === 0 ? null : parts.join(" ");
}

/**
 * Send one message. Never throws and never echoes the token: a delivery failure
 * must not turn a handled update into a redelivered one.
 */
async function sendMessage(
  env: TelegramEnv,
  chatId: string,
  text: string,
  fetchImpl: typeof fetch,
): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SEND_TIMEOUT_MS);
  try {
    const response = await fetchImpl(
      `${TELEGRAM_API}/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, text }),
        signal: controller.signal,
      },
    );
    if (!response.ok) {
      // No secret in the log: only which call failed and its status.
      console.error("telegram.send_failed", { status: response.status });
    }
    return response.ok;
  } catch {
    console.error("telegram.send_failed", { status: "network" });
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Handle one webhook call. The secret header is the only authentication: it is
 * the value set with `setWebhook`'s `secret_token`, so nobody else can forge an
 * update that redeems a ticket.
 */
export async function handleTelegramUpdate(
  raw: unknown,
  env: TelegramEnv,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  if (!isPlainObject(raw)) {
    return;
  }
  const update = raw as unknown as TelegramUpdate;
  const message = update.message;
  if (typeof message !== "object" || message === null) {
    return;
  }

  const text = typeof message.text === "string" ? message.text.trim() : "";
  const chatId = idText(message.chat?.id);
  const telegramUserId = idText(message.from?.id);
  if (
    text.length === 0 ||
    chatId === null ||
    !CHAT_ID.test(chatId) ||
    telegramUserId === null ||
    !USER_ID.test(telegramUserId)
  ) {
    return;
  }

  const ticket = parseStartCommand(text);
  if (ticket !== null) {
    try {
      await redeemTicket(
        env.LINKS,
        ticket,
        {
          id: telegramUserId,
          username: message.from?.username ?? null,
          displayName: message.from === undefined ? null : displayName(message.from),
        },
        new Date(),
      );
      await sendMessage(env, chatId, COPY.linked, fetchImpl);
    } catch (error) {
      const copy =
        error instanceof LinkError && error.code === "link.ticket_consumed"
          ? COPY.consumed
          : COPY.invalid;
      await sendMessage(env, chatId, copy, fetchImpl);
    }
    return;
  }

  if (isBareStart(text)) {
    await sendMessage(env, chatId, COPY.welcome, fetchImpl);
    return;
  }

  if (parseRevokeCommand(text)) {
    const identity = await readIdentity(env.LINKS, telegramUserId);
    if (identity === null) {
      await sendMessage(env, chatId, COPY.nothing, fetchImpl);
      return;
    }
    await revokeIdentity(env.LINKS, telegramUserId);
    await sendMessage(env, chatId, COPY.revoked, fetchImpl);
    return;
  }

  // Free text is ignored on purpose: one-way means no assistant behaviour and
  // no outbound call per stray message, which is also the cheapest anti-spam.
}
