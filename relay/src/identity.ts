/**
 * Telegram identity store for the bug-report relay.
 *
 * One record binds a Telegram account to the app's stable account key. The store
 * lives in Workers KV and is reachable from both directions:
 *
 *   identity:tg:<telegram_user_id>   -> IdentityRecord
 *   identity:acct:<account_key> -> <telegram_user_id>   (pointer)
 *
 * It also answers "who is reporting?" without ever receiving the account key:
 *
 *   link_token:<sha256(install_token)> -> <telegram_user_id>
 *   identity:token:<telegram_user_id>  -> <sha256(install_token)>   (pointer)
 *
 * The `install_token` is the one-time credential the app received when the link
 * completed. A report presents it in a header, which is why it never enters the
 * report bundle, never reaches the group and never lands in a log. Only the
 * hash is stored, so a KV dump cannot be replayed as an identity.
 *
 * The account key is the app's own identity (auth vault or `local-dev`); it is
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
  account_key: string;
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

export function identityKeyForAccount(accountKey: string): string {
  return `identity:acct:${accountKey}`;
}

/** The install token is 32 random bytes rendered as lowercase hex. */
const INSTALL_TOKEN = /^[0-9a-f]{64}$/;

function tokenLookupKey(hash: string): string {
  return `link_token:${hash}`;
}

function tokenPointerKey(telegramUserId: string): string {
  return `identity:token:${telegramUserId}`;
}

/**
 * A revoked install keeps its credential digest for a bounded time, so the
 * client that unlinked cannot keep reporting through the dead token. It is a
 * digest, never the token, and it expires: a block is a guard, not a permanent
 * shadow over a person.
 */
const BLOCK_TTL_SECONDS = 30 * 24 * 60 * 60;

function blockKey(hash: string): string {
  return `blocked:${hash}`;
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
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
    typeof parsed.account_key !== "string" ||
    parsed.account_key.length === 0 ||
    typeof parsed.linked_at !== "string"
  ) {
    return null;
  }
  return {
    telegram_user_id: parsed.telegram_user_id,
    username: typeof parsed.username === "string" ? parsed.username : null,
    display_name: typeof parsed.display_name === "string" ? parsed.display_name : null,
    account_key: parsed.account_key,
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
  if (record.account_key.trim().length === 0) {
    throw new Error("identity.invalid_account_key");
  }
}

export async function readIdentity(
  kv: KvLike,
  telegramUserId: string,
): Promise<IdentityRecord | null> {
  return parseRecord(await kv.get(identityKeyForTelegram(telegramUserId)));
}

export async function readIdentityByAccount(
  kv: KvLike,
  accountKey: string,
): Promise<IdentityRecord | null> {
  const pointer = await kv.get(identityKeyForAccount(accountKey));
  if (pointer === null || !TELEGRAM_ID.test(pointer)) {
    return null;
  }
  const record = await readIdentity(kv, pointer);
  // A pointer to a missing record must not resolve to anything.
  return record !== null && record.account_key === accountKey ? record : null;
}

/**
 * Persist a binding in both directions. A stable account has at most one Telegram
 * account, so relinking retires the previous telegram-side record instead of
 * leaving an identity that could no longer be revoked through the new link.
 */
export async function writeIdentity(kv: KvLike, record: IdentityRecord): Promise<void> {
  assertWritable(record);

  // The same Telegram account moving to a different account key must not leave
  // an old pointer behind. It reads as absent already (fail-closed), but a stale
  // key nobody can revoke is still a leak waiting for a bug.
  const previousRecord = await readIdentity(kv, record.telegram_user_id);
  if (previousRecord !== null && previousRecord.account_key !== record.account_key) {
    await kv.delete(identityKeyForAccount(previousRecord.account_key));
  }

  // A different Telegram account claiming an account key that is already bound
  // does NOT erase the current binding or its token. A guessed account key must
  // never be able to take somebody's signature away, and an install that lost
  // its own token must not be locked out of linking again (S19). The pointer
  // simply moves; the previous identity stays valid and revocable by its owner.
  const previousTelegramId = await kv.get(identityKeyForAccount(record.account_key));
  void previousTelegramId;

  await kv.put(identityKeyForTelegram(record.telegram_user_id), JSON.stringify(record));
  await kv.put(identityKeyForAccount(record.account_key), record.telegram_user_id);
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
 * Remove a binding in both directions, erasing the stored personal data and the
 * install token that could still sign reports as this account.
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
  const hash = await kv.get(tokenPointerKey(telegramUserId));
  if (hash !== null) {
    await kv.put(blockKey(hash), "revoked", { expirationTtl: BLOCK_TTL_SECONDS });
  }

  await kv.delete(identityKeyForTelegram(telegramUserId));
  // Only remove the account pointer when it still points at this identity: a
  // newer binding may legitimately own it, and revoking one link must never
  // unbind another.
  const pointed = await kv.get(identityKeyForAccount(current.account_key));
  if (pointed === telegramUserId) {
    await kv.delete(identityKeyForAccount(current.account_key));
  }
  await eraseInstallToken(kv, telegramUserId);
  return true;
}

/**
 * Whether this credential belongs to an install that unlinked. Malformed tokens
 * are not blocked — they are simply not identity, and `resolveAttribution`
 * already refuses them.
 */
export async function isBlockedInstall(kv: KvLike, token: string): Promise<boolean> {
  if (!INSTALL_TOKEN.test(token)) {
    return false;
  }
  return (await kv.get(blockKey(await sha256Hex(token)))) !== null;
}

/** Drop the token lookup of one Telegram account, if it has one. */
async function eraseInstallToken(kv: KvLike, telegramUserId: string): Promise<void> {
  const hash = await kv.get(tokenPointerKey(telegramUserId));
  if (hash !== null) {
    await kv.delete(tokenLookupKey(hash));
  }
  await kv.delete(tokenPointerKey(telegramUserId));
}

/**
 * Remember that this Telegram account holds this install token.
 *
 * Called when the token is handed to the app: from then on a report can present
 * it and the relay resolves the identity itself. Only the hash is stored, and a
 * newer token for the same account retires the previous lookup, so a token that
 * was never handed over — or was replaced — signs nothing.
 */
export async function recordInstallToken(
  kv: KvLike,
  token: string,
  telegramUserId: string,
): Promise<void> {
  if (!INSTALL_TOKEN.test(token) || !TELEGRAM_ID.test(telegramUserId)) {
    return;
  }
  const hash = await sha256Hex(token);
  const previous = await kv.get(tokenPointerKey(telegramUserId));
  if (previous !== null && previous !== hash) {
    await kv.delete(tokenLookupKey(previous));
  }
  await kv.put(tokenLookupKey(hash), telegramUserId);
  await kv.put(tokenPointerKey(telegramUserId), hash);
}

/**
 * Resolve the install token a report presented. Unknown, revoked, replaced or
 * malformed tokens resolve to nothing; the caller then falls back to what the
 * reporter typed.
 */
export async function readIdentityByInstallToken(
  kv: KvLike,
  token: string,
): Promise<IdentityRecord | null> {
  if (!INSTALL_TOKEN.test(token)) {
    return null;
  }
  const pointer = await kv.get(tokenLookupKey(await sha256Hex(token)));
  if (pointer === null || !TELEGRAM_ID.test(pointer)) {
    return null;
  }
  return readIdentity(kv, pointer);
}
