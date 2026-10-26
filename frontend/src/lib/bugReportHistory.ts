/**
 * The reports this install sent, kept locally so a release can be matched against
 * them (S12).
 *
 * Only the delivery id, the version it was sent from and the timestamp are
 * stored — never the description, the logs or the contact. That is enough for
 * "your report was fixed in vX", and it means the in-app notice needs no
 * server-side mapping between a report and a person.
 *
 * The store is best-effort: localStorage can be unavailable (private mode, a
 * blocked origin), and losing the history must never break the panel.
 */

const STORAGE_KEY = "demiurgos.bugreport.reports";

/** Keep the list bounded; nobody matches against ancient reports. */
const MAX_REPORTS = 50;

export interface SubmittedReport {
  id: string;
  at: string;
  app_version: string;
}

export interface ReleasedVersion {
  version: string;
  report_ids: string[];
  at: string;
}

export interface FixedReport {
  id: string;
  version: string;
}

function isSubmittedReport(value: unknown): value is SubmittedReport {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.id === "string" &&
    record.id.length > 0 &&
    typeof record.at === "string" &&
    typeof record.app_version === "string"
  );
}

/** The locally remembered reports, newest first. Unreadable storage -> []. */
export function readSubmittedReports(): SubmittedReport[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === null) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isSubmittedReport);
  } catch {
    return [];
  }
}

/** Remember one delivered report. Repeats of the same id are not duplicated. */
export function rememberSubmittedReport(report: SubmittedReport): void {
  if (report.id.length === 0) return;
  const next = [report, ...readSubmittedReports().filter((entry) => entry.id !== report.id)]
    .slice(0, MAX_REPORTS);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // A full or blocked store loses the history, never the report itself.
  }
}

/**
 * Which of the locally sent reports a release has fixed.
 *
 * A report can only be fixed by the newest release that mentions it; the result
 * is ordered by release (newest first) and carries the version so the panel can
 * say where.
 */
export function matchReleasedReports(
  reports: SubmittedReport[],
  releases: ReleasedVersion[],
): FixedReport[] {
  const mine = new Set(reports.map((report) => report.id));
  const seen = new Set<string>();
  const fixed: FixedReport[] = [];
  for (const release of releases) {
    for (const id of release.report_ids) {
      if (mine.has(id) && !seen.has(id)) {
        seen.add(id);
        fixed.push({ id, version: release.version });
      }
    }
  }
  return fixed;
}
