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
  const raw = await kv.get(key);
  const current = raw === null ? 0 : Number.parseInt(raw, 10);
  const next = (Number.isFinite(current) ? current : 0) + 1;
  await kv.put(key, String(next), {
    expirationTtl: Math.max(60, Math.ceil(ttlSeconds)),
  });
  return next;
}
