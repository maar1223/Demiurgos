/**
 * Linking tickets — the one-time credential that binds a Telegram account to a
 * stable app account key.
 *
 * Flow: the app (through the backend) asks for a ticket, shows it as a QR/deep
 * link, the person opens the reports bot, Telegram delivers `/start <ticket>`,
 * and the webhook redeems it here. The app then polls the ticket and receives
 * the `install_token` it will use for later reports.
 *
 * Why a ticket at all: a bot cannot resolve `@username` to a chat and cannot
 * start a conversation, so the numeric Telegram id only exists once the person
 * writes to that bot. The ticket carries the app side of the binding until
 * both halves meet.
 *
 * The ticket is a credential, so it is single-use, short-lived, minted only
 * three times per hour per account, and idempotent for a repeated `/start`
 * from the same Telegram account — a double tap must never look like an error.
 */

import { admitCounter } from "./counters.ts";
import {
  readIdentity,
  readIdentityByAccount,
  recordInstallToken,
  revokeIdentity,
  writeIdentity,
  type IdentityPermissions,
  type IdentityRecord,
  type KvLike,
} from "./identity.ts";

/** How long a ticket stays redeemable. The link itself never expires. */
export const TICKET_TTL_SECONDS = 600;

/** New tickets allowed per account per rolling hour. Reuse does not count. */
export const LINK_START_MAX_PER_HOUR = 3;

const TICKET_LENGTH = 8;
// Crockford base32: no I, L, O or U, so a ticket read aloud or typed by hand
// cannot be confused. 256 % 32 === 0, so random bytes map without bias.
const TICKET_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/**
 * Account keys are whatever the vault stored, which is any non-empty trimmed
 * username (`account.py::create_account` imposes no charset). The relay must not
 * be stricter than the upstream or a valid account cannot link, so it only
 * enforces what a KV key needs: trimmed, no control characters, and bounded
 * well under the 512-byte key limit including the longest prefix.
 */
const MAX_ACCOUNT_KEY_BYTES = 400;
// eslint-disable-next-line no-control-regex
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;

function isValidAccountKey(value: string): boolean {
  if (value.length === 0 || value !== value.trim()) {
    return false;
  }
  if (CONTROL_CHARACTERS.test(value)) {
    return false;
  }
  return new TextEncoder().encode(value).length <= MAX_ACCOUNT_KEY_BYTES;
}

/** Internal error carrying the HTTP status and non-secret relay code. */
export class LinkError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(code);
    this.name = "LinkError";
    this.status = status;
    this.code = code;
  }
}

export interface StartLinkRequest {
  account_key: string;
  /** Sign this account's reports. Defaults to true: that is why they linked. */
  report_identity?: boolean;
  /** Receive a DM when a reported bug is fixed. Defaults to true. */
  notify_releases?: boolean;
}

export interface StartedLink {
  ticket: string;
  expires_at: string;
  /** True when an unexpired ticket was returned instead of minting a new one. */
  reused: boolean;
}

/** Ticket state as stored in KV. */
interface TicketRecord {
  ticket: string;
  account_key: string;
  permissions: IdentityPermissions;
  created_at: string;
  expires_at: string;
  consumed_at: string | null;
  consumed_by: string | null;
  install_token: string | null;
}

export type LinkStatus =
  | { state: "pending"; expires_at: string }
  | { state: "expired" }
  | {
      state: "linked";
      identity: IdentityRecord;
      install_token: string | null;
    };

export interface TelegramUser {
  id: string;
  username?: string | null;
  displayName?: string | null;
}

function ticketKey(ticket: string): string {
  return `ticket:${ticket}`;
}

function pendingKey(accountKey: string): string {
  return `ticket:pending:${accountKey}`;
}

function startCounterKey(accountKey: string): string {
  return `linkstart:${accountKey}`;
}

function randomFromAlphabet(length: number): string {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  let out = "";
  for (const byte of bytes) {
    out += TICKET_ALPHABET[byte % TICKET_ALPHABET.length];
  }
  return out;
}

export function generateTicket(): string {
  return randomFromAlphabet(TICKET_LENGTH);
}

function randomToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function parseTicket(raw: string | null): TicketRecord | null {
  if (raw === null) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return null;
  }
  const value = parsed as Record<string, unknown>;
  const permissions = value.permissions;
  if (
    typeof value.ticket !== "string" ||
    typeof value.account_key !== "string" ||
    typeof value.created_at !== "string" ||
    typeof value.expires_at !== "string" ||
    typeof permissions !== "object" ||
    permissions === null ||
    Array.isArray(permissions)
  ) {
    return null;
  }
  const perms = permissions as Record<string, unknown>;
  return {
    ticket: value.ticket,
    account_key: value.account_key,
    permissions: {
      report_identity: perms.report_identity === true,
      notify_releases: perms.notify_releases === true,
    },
    created_at: value.created_at,
    expires_at: value.expires_at,
    consumed_at: typeof value.consumed_at === "string" ? value.consumed_at : null,
    consumed_by: typeof value.consumed_by === "string" ? value.consumed_by : null,
    install_token: typeof value.install_token === "string" ? value.install_token : null,
  };
}

async function readTicket(kv: KvLike, ticket: string): Promise<TicketRecord | null> {
  return parseTicket(await kv.get(ticketKey(ticket)));
}

async function writeTicket(
  kv: KvLike,
  record: TicketRecord,
  ttlSeconds: number,
): Promise<void> {
  await kv.put(ticketKey(record.ticket), JSON.stringify(record), {
    expirationTtl: Math.max(60, Math.ceil(ttlSeconds)),
  });
}

function isLive(record: TicketRecord, now: Date): boolean {
  return Date.parse(record.expires_at) > now.getTime();
}

/**
 * Mint a ticket, or hand back the still-valid pending one. Reuse is deliberate:
 * reopening the panel must not burn the three-per-hour allowance.
 */
export async function startLink(
  kv: KvLike,
  request: StartLinkRequest,
  now: Date,
): Promise<StartedLink> {
  if (!isValidAccountKey(request.account_key)) {
    throw new LinkError(400, "link.invalid_account");
  }

  const pendingTicket = await kv.get(pendingKey(request.account_key));
  const pending = pendingTicket === null ? null : await readTicket(kv, pendingTicket);
  if (
    pending !== null &&
    pending.consumed_at === null &&
    pending.account_key === request.account_key &&
    isLive(pending, now)
  ) {
    // A caller that states a permission explicitly must not have it silently
    // dropped: the panel may have changed it before the ticket was redeemed.
    if (request.report_identity !== undefined || request.notify_releases !== undefined) {
      const permissions = {
        report_identity:
          request.report_identity ?? pending.permissions.report_identity,
        notify_releases:
          request.notify_releases ?? pending.permissions.notify_releases,
      };
      if (
        permissions.report_identity !== pending.permissions.report_identity ||
        permissions.notify_releases !== pending.permissions.notify_releases
      ) {
        const remaining = Math.ceil(
          (Date.parse(pending.expires_at) - now.getTime()) / 1000,
        );
        await writeTicket(kv, { ...pending, permissions }, remaining);
      }
    }
    return { ticket: pending.ticket, expires_at: pending.expires_at, reused: true };
  }

  let withinHour: boolean;
  try {
    // A refused attempt must not push the window forward, or hammering the
    // button would keep the account locked out indefinitely.
    withinHour = await admitCounter(
      kv,
      startCounterKey(request.account_key),
      3600,
      LINK_START_MAX_PER_HOUR,
    );
  } catch {
    throw new LinkError(503, "link.rate_limit_unavailable");
  }
  if (!withinHour) {
    throw new LinkError(429, "link.rate_limited");
  }

  const expiresAt = new Date(now.getTime() + TICKET_TTL_SECONDS * 1000).toISOString();
  const record: TicketRecord = {
    ticket: generateTicket(),
    account_key: request.account_key,
    permissions: {
      report_identity: request.report_identity !== false,
      notify_releases: request.notify_releases !== false,
    },
    created_at: now.toISOString(),
    expires_at: expiresAt,
    consumed_at: null,
    consumed_by: null,
    install_token: null,
  };
  await writeTicket(kv, record, TICKET_TTL_SECONDS);
  await kv.put(pendingKey(request.account_key), record.ticket, {
    expirationTtl: TICKET_TTL_SECONDS,
  });

  return { ticket: record.ticket, expires_at: expiresAt, reused: false };
}

/**
 * Redeem a ticket from a Telegram update. Called only by the webhook after the
 * update is authenticated — never exposed to the app, or the app could bind a
 * Telegram account it does not control.
 */
export async function redeemTicket(
  kv: KvLike,
  ticket: string,
  telegramUser: TelegramUser,
  now: Date,
): Promise<IdentityRecord> {
  const record = await readTicket(kv, ticket);
  if (record === null) {
    throw new LinkError(404, "link.ticket_invalid");
  }
  if (record.consumed_at !== null) {
    if (record.consumed_by !== telegramUser.id) {
      throw new LinkError(409, "link.ticket_consumed");
    }
    const existing = await readIdentity(kv, telegramUser.id);
    if (existing === null) {
      throw new LinkError(404, "link.ticket_invalid");
    }
    return existing;
  }
  if (!isLive(record, now)) {
    throw new LinkError(410, "link.ticket_expired");
  }

  const identity: IdentityRecord = {
    telegram_user_id: telegramUser.id,
    username: telegramUser.username ?? null,
    display_name: telegramUser.displayName ?? null,
    account_key: record.account_key,
    linked_at: now.toISOString(),
    started_bots: { ideas: false, reports: true },
    permissions: record.permissions,
  };
  await writeIdentity(kv, identity);

  const consumed: TicketRecord = {
    ...record,
    consumed_at: now.toISOString(),
    consumed_by: telegramUser.id,
    install_token: randomToken(),
  };
  await writeTicket(kv, consumed, TICKET_TTL_SECONDS);

  return identity;
}

/**
 * The app's poll. Hands over the `install_token` exactly once, then keeps
 * answering `linked` without one so a reload never re-exposes the secret.
 */
export async function linkStatus(
  kv: KvLike,
  ticket: string,
  now: Date,
): Promise<LinkStatus> {
  const record = await readTicket(kv, ticket);
  if (record === null) {
    return { state: "expired" };
  }

  if (record.consumed_at !== null) {
    const identity = record.consumed_by === null
      ? null
      : await readIdentity(kv, record.consumed_by);
    if (identity === null) {
      return { state: "expired" };
    }
    if (record.install_token !== null) {
      // The token is registered before the ticket forgets it: a report can only
      // present it after this handover, and losing it here would leave the link
      // unverifiable until the account relinked.
      if (record.consumed_by !== null) {
        await recordInstallToken(kv, record.install_token, record.consumed_by);
      }
      await writeTicket(kv, { ...record, install_token: null }, TICKET_TTL_SECONDS);
      return { state: "linked", identity, install_token: record.install_token };
    }
    return { state: "linked", identity, install_token: null };
  }

  if (!isLive(record, now)) {
    return { state: "expired" };
  }

  return { state: "pending", expires_at: record.expires_at };
}

/**
 * Unlink by account key and erase every stored direction, including any
 * outstanding ticket: otherwise a ticket photographed before the revoke would
 * still re-link the account for the rest of its TTL.
 */
export async function revokeLink(kv: KvLike, accountKey: string): Promise<boolean> {
  const pendingTicket = await kv.get(pendingKey(accountKey));
  if (pendingTicket !== null) {
    await kv.delete(ticketKey(pendingTicket));
  }
  await kv.delete(pendingKey(accountKey));

  const identity = await readIdentityByAccount(kv, accountKey);
  if (identity === null) {
    return false;
  }
  await revokeIdentity(kv, identity.telegram_user_id);
  return true;
}
