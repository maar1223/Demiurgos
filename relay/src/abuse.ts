/**
 * Layered abuse control for the report path (S13).
 *
 * A bot may post roughly 20 messages a minute to one group before Telegram
 * answers 429, so the throttling happens HERE, before Telegram, or the channel
 * becomes unusable for the reports that follow. The layers:
 *
 *   - dedup: the same report inside 24 h is not published twice,
 *   - linked principals: 5 an hour, 20 a day,
 *   - unlinked reporters: the per-IP and global-daily ceilings in `index.ts`,
 *   - a revoked install: blocked by its dead credential, in `identity.ts`.
 *
 * The dedup key is a digest of `description + platform + logs` — never the
 * contact or the version — so re-submitting the same failure after adding a
 * contact or upgrading the app still never opens a second topic.
 *
 * KV is eventually consistent, so two identical reports racing each other can
 * both be published. These are best-effort bounds for the Alpha volume, and the
 * caller must treat a counter failure as fail-CLOSED.
 */

import { bumpCounter } from "./counters.ts";
import type { KvLike } from "./identity.ts";

/** How long a published report is remembered for dedup. */
export const DEDUP_TTL_SECONDS = 24 * 60 * 60;

/** Reports one linked principal may send per rolling hour. */
export const PRINCIPAL_HOURLY_MAX = 5;

/** Reports one linked principal may send per UTC day. */
export const PRINCIPAL_DAILY_MAX = 20;

/** The part of a report that identifies "the same failure". */
export interface Fingerprintable {
  description: string;
  platform: Record<string, string>;
  logs: string | null;
}

export type Admission =
  | { verdict: "duplicate"; deliveryId: string }
  | { verdict: "limited"; code: string }
  | { verdict: "accepted"; fingerprint: string };

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

function dedupKey(fingerprint: string): string {
  return `dedup:${fingerprint}`;
}

/**
 * A stable digest of the failure itself. Platform keys are sorted, so a client
 * that serializes them in another order does not look like a new report.
 */
export async function reportFingerprint(report: Fingerprintable): Promise<string> {
  const platform = Object.keys(report.platform)
    .sort()
    .map((key) => [key, report.platform[key]]);
  return sha256Hex(
    JSON.stringify({
      description: report.description,
      platform,
      logs: report.logs,
    }),
  );
}

/** The delivery id of the report this fingerprint already produced, if any. */
export async function readRecentReport(
  kv: KvLike,
  fingerprint: string,
): Promise<string | null> {
  const raw = await kv.get(dedupKey(fingerprint));
  if (raw === null) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return typeof parsed.delivery_id === "string" && parsed.delivery_id.length > 0
      ? parsed.delivery_id
      : null;
  } catch {
    return null;
  }
}

/** Remember a report only after it was actually delivered. */
export async function rememberReport(
  kv: KvLike,
  fingerprint: string,
  deliveryId: string,
): Promise<void> {
  await kv.put(dedupKey(fingerprint), JSON.stringify({ delivery_id: deliveryId }), {
    expirationTtl: DEDUP_TTL_SECONDS,
  });
}

/** Seconds until the next UTC midnight, for the daily counters. */
export function secondsUntilUtcMidnight(now: Date): number {
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

/**
 * Decide what to do with one report before any delivery work.
 *
 * A duplicate short-circuits without touching a counter: an accidental double
 * submit must not spend the reporter's allowance. A linked principal counts
 * against its own hourly and daily buckets; `accountKey` is null when nothing
 * was verified, and the caller then applies the per-IP and global ceilings.
 */
export async function admitReport(
  kv: KvLike,
  report: Fingerprintable,
  accountKey: string | null,
  now: Date,
): Promise<Admission> {
  const fingerprint = await reportFingerprint(report);

  const seen = await readRecentReport(kv, fingerprint);
  if (seen !== null) {
    return { verdict: "duplicate", deliveryId: seen };
  }

  if (accountKey !== null) {
    const hourly = await bumpCounter(kv, `principal:hour:${accountKey}`, 3600);
    if (hourly > PRINCIPAL_HOURLY_MAX) {
      return { verdict: "limited", code: "relay.rate_limited" };
    }
    const daily = await bumpCounter(
      kv,
      `principal:day:${accountKey}`,
      secondsUntilUtcMidnight(now),
    );
    if (daily > PRINCIPAL_DAILY_MAX) {
      return { verdict: "limited", code: "relay.rate_limited" };
    }
  }

  return { verdict: "accepted", fingerprint };
}
