/**
 * Release records — "this version fixed these reports" (S12).
 *
 * The app owns the notice: it keeps the ids of the reports it sent and matches
 * them against this public list, so a reporter learns their bug is fixed without
 * a Telegram link and without the relay storing who reported what.
 *
 * The list is deliberately small and public: a version, the report ids it fixed
 * and when it was recorded. No reporter, no contact, no account key.
 *
 * The Telegram DM is the optional extra and is NOT implemented here: it would
 * require mapping a report to a person, and S12 puts the in-app notice first.
 */

import type { KvLike } from "./identity.ts";

/** One released version and the reports it closed. */
export interface ReleaseRecord {
  version: string;
  report_ids: string[];
  at: string;
}

/** Where the bounded list lives in the LINKS namespace. */
const RELEASES_KEY = "releases:all";

/** Keep only the most recent releases; the app has no use for ancient ones. */
export const MAX_RELEASES = 50;

/** A single release may close at most this many reports. */
export const MAX_REPORT_IDS = 100;

/** Version strings are short and printable; this is not a changelog field. */
const VERSION_MAX_CHARS = 64;

/** Report ids are the delivery ids the relay minted: UUID-shaped or similar. */
const REPORT_ID = /^[0-9A-Za-z-]{8,64}$/;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseRelease(value: unknown): ReleaseRecord | null {
  if (!isPlainObject(value)) return null;
  const version = value.version;
  const reportIds = value.report_ids;
  const at = value.at;
  if (typeof version !== "string" || version.length === 0 || version.length > VERSION_MAX_CHARS) {
    return null;
  }
  if (!Array.isArray(reportIds) || typeof at !== "string") {
    return null;
  }
  const ids = reportIds.filter(
    (id): id is string => typeof id === "string" && REPORT_ID.test(id),
  );
  return { version, report_ids: ids, at };
}

/** Newest first. A corrupt store reads as empty, never as a partial release. */
export async function readReleases(kv: KvLike): Promise<ReleaseRecord[]> {
  const raw = await kv.get(RELEASES_KEY);
  if (raw === null) {
    return [];
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) {
    return [];
  }
  return parsed
    .map(parseRelease)
    .filter((record): record is ReleaseRecord => record !== null);
}

/** Validate one release request; throws a plain `Error` with a stable reason. */
export function normalizeRelease(raw: unknown): { version: string; report_ids: string[] } {
  if (!isPlainObject(raw)) {
    throw new Error("release.invalid_payload");
  }
  const version = raw.version;
  if (typeof version !== "string") {
    throw new Error("release.invalid_payload");
  }
  const trimmed = version.trim();
  if (trimmed.length === 0 || trimmed.length > VERSION_MAX_CHARS) {
    throw new Error("release.invalid_version");
  }
  const ids = raw.report_ids;
  if (!Array.isArray(ids)) {
    throw new Error("release.invalid_payload");
  }
  const reportIds: string[] = [];
  for (const id of ids) {
    if (typeof id !== "string" || !REPORT_ID.test(id)) {
      throw new Error("release.invalid_report_id");
    }
    if (!reportIds.includes(id)) {
      reportIds.push(id);
    }
  }
  if (reportIds.length > MAX_REPORT_IDS) {
    throw new Error("release.too_large");
  }
  return { version: trimmed, report_ids: reportIds };
}

/**
 * Append one release. Recording the same version twice replaces its entry, so
 * a repeated call corrects the list instead of duplicating it.
 */
export async function recordRelease(
  kv: KvLike,
  version: string,
  reportIds: string[],
  now: Date,
): Promise<ReleaseRecord[]> {
  const existing = await readReleases(kv);
  const record: ReleaseRecord = {
    version,
    report_ids: reportIds,
    at: now.toISOString(),
  };
  const next = [record, ...existing.filter((entry) => entry.version !== version)].slice(
    0,
    MAX_RELEASES,
  );
  await kv.put(RELEASES_KEY, JSON.stringify(next));
  return next;
}
