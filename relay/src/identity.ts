/**
 * Telegram identity store for the bug-report relay.
 *
 * One record binds a Telegram account to the app's local principal. The store
 * lives in Workers KV and is reachable from both directions:
 *
 *   identity:tg:<telegram_user_id>   -> IdentityRecord
 *   identity:principal:<principal_id> -> <telegram_user_id>   (pointer)
 *
 * The principal is the app's own identity (auth vault or `local-dev`); it is
 * never derived from a client-supplied header. The Telegram side comes from a
 * Telegram update, so the binding cannot be forged by the app: the app only
 * presents the ticket the relay issued, and the relay resolves the identity
 * from what Telegram told it.
 *
 * Reads fail closed: a malformed value or a dangling pointer reads as absent,
 * never as a partial identity, so a corrupted entry can only lose a link — it
 * can never grant one.
 *
 * The KV surface is injected as `KvLike` so the logic is unit-testable without
 * the Workers runtime.
 */

/** The bots that can deliver to a linked account. Delivery permission is per bot. */
export type BotName = "ideas" | "reports";

/** What a linked account agreed to. Granted separately, never bundled. */
export interface IdentityPermissions {
  /** Sign this account's bug reports in the triage group. */
  report_identity: boolean;
  /** Send a direct message when a reported bug is fixed. */
  notify_releases: boolean;
}

/** The stored identity record. */
export interface IdentityRecord {
  telegram_user_id: string;
  username: string | null;
  display_name: string | null;
  principal_id: string;
  /** ISO timestamp of the first successful link. */
  linked_at: string;
  /** Which bots this account has started; a bot cannot message the others. */
  started_bots: Record<BotName, boolean>;
  permissions: IdentityPermissions;
}

/** The subset of Workers KV this module needs. */
export interface KvLike {
  get(key: string): Promise<string | null>;
  put(key: string, value: string, options?: { expirationTtl?: number }): Promise<void>;
  delete(key: string): Promise<void>;
}

/** Telegram user ids are positive integers, delivered as strings. */
const TELEGRAM_ID = /^[1-9][0-9]{0,19}$/;

export function identityKeyForTelegram(telegramUserId: string): string {
  return `identity:tg:${telegramUserId}`;
}

export function identityKeyForPrincipal(principalId: string): string {
  return `identity:principal:${principalId}`;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Parse a stored record; anything unexpected reads as absent. */
function parseRecord(raw: string | null): IdentityRecord | null {
  if (raw === null) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isPlainObject(parsed)) {
    return null;
  }
  const bots = parsed.started_bots;
  const permissions = parsed.permissions;
  if (!isPlainObject(bots) || !isPlainObject(permissions)) {
    return null;
  }
  if (
    typeof parsed.telegram_user_id !== "string" ||
    !TELEGRAM_ID.test(parsed.telegram_user_id) ||
    typeof parsed.principal_id !== "string" ||
    parsed.principal_id.length === 0 ||
    typeof parsed.linked_at !== "string"
  ) {
    return null;
  }
  return {
    telegram_user_id: parsed.telegram_user_id,
    username: typeof parsed.username === "string" ? parsed.username : null,
    display_name: typeof parsed.display_name === "string" ? parsed.display_name : null,
    principal_id: parsed.principal_id,
    linked_at: parsed.linked_at,
    started_bots: {
      ideas: bots.ideas === true,
      reports: bots.reports === true,
    },
    permissions: {
      report_identity: permissions.report_identity === true,
      notify_releases: permissions.notify_releases === true,
    },
  };
}

/** Refuse to persist a record that could never be resolved later. */
function assertWritable(record: IdentityRecord): void {
  if (!TELEGRAM_ID.test(record.telegram_user_id)) {
    throw new Error("identity.invalid_telegram_user_id");
  }
  if (record.principal_id.trim().length === 0) {
    throw new Error("identity.invalid_principal_id");
  }
}

export async function readIdentity(
  kv: KvLike,
  telegramUserId: string,
): Promise<IdentityRecord | null> {
  return parseRecord(await kv.get(identityKeyForTelegram(telegramUserId)));
}

export async function readIdentityByPrincipal(
  kv: KvLike,
  principalId: string,
): Promise<IdentityRecord | null> {
  const pointer = await kv.get(identityKeyForPrincipal(principalId));
  if (pointer === null || !TELEGRAM_ID.test(pointer)) {
    return null;
  }
  const record = await readIdentity(kv, pointer);
  // A pointer to a missing record must not resolve to anything.
  return record !== null && record.principal_id === principalId ? record : null;
}

/**
 * Persist a binding in both directions. A principal has at most one Telegram
 * account, so relinking retires the previous telegram-side record instead of
 * leaving an identity that could no longer be revoked through the new link.
 */
export async function writeIdentity(kv: KvLike, record: IdentityRecord): Promise<void> {
  assertWritable(record);

  const previousTelegramId = await kv.get(identityKeyForPrincipal(record.principal_id));
  if (
    previousTelegramId !== null &&
    previousTelegramId !== record.telegram_user_id
  ) {
    await kv.delete(identityKeyForTelegram(previousTelegramId));
  }

  await kv.put(identityKeyForTelegram(record.telegram_user_id), JSON.stringify(record));
  await kv.put(identityKeyForPrincipal(record.principal_id), record.telegram_user_id);
}

/** Record that a bot can now deliver to this account. Unknown identity -> null. */
export async function markBotStarted(
  kv: KvLike,
  telegramUserId: string,
  bot: BotName,
): Promise<IdentityRecord | null> {
  const current = await readIdentity(kv, telegramUserId);
  if (current === null) {
    return null;
  }
  const updated: IdentityRecord = {
    ...current,
    started_bots: { ...current.started_bots, [bot]: true },
  };
  await writeIdentity(kv, updated);
  return updated;
}

/**
 * Remove a binding in both directions, erasing the stored personal data.
 * Returns whether anything was linked.
 */
export async function revokeIdentity(
  kv: KvLike,
  telegramUserId: string,
): Promise<boolean> {
  const current = await readIdentity(kv, telegramUserId);
  if (current === null) {
    return false;
  }
  await kv.delete(identityKeyForTelegram(telegramUserId));
  await kv.delete(identityKeyForPrincipal(current.principal_id));
  return true;
}
