/**
 * How a report states who sent it — and, above all, how that was established.
 *
 * Three levels, never blurred (S6):
 *
 *   👤 @user · verified by Telegram     the link came from a Telegram update
 *   👤 Name — declared · local session  no link; the name was typed by the user
 *   👤 owner                            id supplied by relay configuration
 *
 * The relay resolves the Telegram side itself, from the install token a report
 * presents, so a caller can never assert an identity it does not hold. A
 * configured id is only ever labelled `owner` for an account that actually
 * linked; presenting configuration as Telegram verification is the one thing
 * this module must never do.
 *
 * Two independent gates keep the label honest:
 *
 *   - the token must resolve to a stored link, and
 *   - that link must carry `report_identity`; declining it turns the report
 *     back into a declared one, without touching the link itself.
 */

import { readIdentityByInstallToken, type IdentityRecord, type KvLike } from "./identity.ts";

export type AttributionLevel = "verified" | "owner" | "declared" | "none";

export interface Attribution {
  level: AttributionLevel;
  /** Exact line rendered in the summary, the bundle and the email body. */
  line: string;
  /**
   * How the identity was established, as a short marker that can lead a topic
   * name or a document caption. It is what stops a typed `@handle` from looking
   * like a verified one.
   */
  tag: string;
  /** Who, in the shortest correct form. */
  label: string;
  /** The resolved link, or null when nothing could be verified. */
  identity: IdentityRecord | null;
}

export const NO_CONTACT_LINE = "👤 sin contacto";

/** Telegram user ids are positive integers, delivered as strings. */
const TELEGRAM_ID = /^[1-9][0-9]{0,19}$/;

/**
 * Parse the configured Owner ids. Anything that is not a Telegram id is
 * dropped: a typo in configuration must not silently label a stranger.
 */
export function ownerTelegramIds(raw: string | undefined): Set<string> {
  const ids = new Set<string>();
  if (raw === undefined) {
    return ids;
  }
  for (const part of raw.split(/[\s,]+/)) {
    if (TELEGRAM_ID.test(part)) {
      ids.add(part);
    }
  }
  return ids;
}

/**
 * What to call a linked account: the handle Telegram gave us, else the display
 * name, else the numeric id. Never an invented name.
 */
function verifiedName(identity: IdentityRecord): string {
  const username = identity.username?.trim() ?? "";
  if (username.length > 0) {
    return `@${username.replace(/^@/, "")}`;
  }
  const displayName = identity.display_name?.trim() ?? "";
  return displayName.length > 0 ? displayName : identity.telegram_user_id;
}

/**
 * Resolve the attribution of one report.
 *
 * `installToken` comes from the request header — never from the body, or it
 * would ride into the published bundle. `contact` is what the reporter typed,
 * and it is only ever used for the declared level.
 */
export async function resolveAttribution(
  kv: KvLike | null | undefined,
  installToken: string | null,
  contact: string | null,
  ownerIds: ReadonlySet<string>,
): Promise<Attribution> {
  const identity = await lookupIdentity(kv, installToken);

  if (identity !== null && identity.permissions.report_identity) {
    if (ownerIds.has(identity.telegram_user_id)) {
      return { level: "owner", line: "👤 owner", tag: "owner", label: "owner", identity };
    }
    const name = verifiedName(identity);
    return {
      level: "verified",
      line: `👤 ${name} · verified by Telegram`,
      tag: "verified by Telegram",
      label: name,
      identity,
    };
  }

  const declared = contact?.trim() ?? "";
  if (declared.length > 0) {
    return {
      level: "declared",
      line: `👤 ${declared} — declared · local session`,
      tag: "declared · local session",
      label: declared,
      identity: null,
    };
  }

  return {
    level: "none",
    line: NO_CONTACT_LINE,
    tag: "sin contacto",
    label: "sin contacto",
    identity: null,
  };
}

/**
 * Read the link behind a presented token. Attribution is a label, never a
 * delivery dependency: an unbound namespace, a store outage or any unexpected
 * failure degrades to "nothing verified" instead of failing a report the person
 * already wrote. It can only ever lose a signature, never invent one.
 */
async function lookupIdentity(
  kv: KvLike | null | undefined,
  installToken: string | null,
): Promise<IdentityRecord | null> {
  if (installToken === null) {
    return null;
  }
  if (kv === null || kv === undefined) {
    return null;
  }
  try {
    return await readIdentityByInstallToken(kv, installToken);
  } catch {
    console.error("attribution.resolve_failed");
    return null;
  }
}
