/**
 * KV-backed counters shared by the relay's abuse bounds.
 *
 * Workers KV is eventually consistent, not atomic, so these are best-effort
 * limits — sufficient for the Alpha volume and never the only line of defence.
 * A counter-backend failure must be treated as fail-CLOSED by the caller.
 */

import type { KvLike } from "./identity.ts";

/** Read-increment-write one counter in a KV namespace. */
export async function bumpCounter(
  kv: KvLike,
  key: string,
  ttlSeconds: number,
): Promise<number> {
  const next = (await readCounter(kv, key)) + 1;
  await kv.put(key, String(next), {
    expirationTtl: Math.max(60, Math.ceil(ttlSeconds)),
  });
  return next;
}

/** The stored count, or 0 when absent or unreadable. */
export async function readCounter(kv: KvLike, key: string): Promise<number> {
  const raw = await kv.get(key);
  if (raw === null) {
    return 0;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * Take one unit from a bounded window, or refuse without touching it.
 *
 * `bumpCounter` rewrites the key on every call, and a rewrite also resets its
 * expiry. A caller refused at the limit that keeps retrying would therefore
 * push the window forward on every attempt and never get through. This variant
 * reads first and only writes when there is room, so a refusal cannot extend
 * the window it is refusing.
 */
export async function admitCounter(
  kv: KvLike,
  key: string,
  ttlSeconds: number,
  max: number,
): Promise<boolean> {
  const current = await readCounter(kv, key);
  if (current >= max) {
    return false;
  }
  await kv.put(key, String(current + 1), {
    expirationTtl: Math.max(60, Math.ceil(ttlSeconds)),
  });
  return true;
}
