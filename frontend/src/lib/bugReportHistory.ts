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

/** Where the optional install pseudonym preference lives (S20). */
const PSEUDONYM_KEY = "demiurgos.bugreport.pseudonym";

/** A minted-but-not-yet-confirmed ticket, so a reload can resume the poll. */
const PENDING_LINK_KEY = "demiurgos.bugreport.linkTicket";

/** The one-time token is minted on the first poll after the phone confirms, so
 *  losing that poll strands the link. Keeping the ticket locally lets the panel
 *  pick the handover back up after a reload. */
export interface PendingLink {
  ticket: string;
  expires_at: string | null;
  telegram_url: string | null;
}

/** The stored ticket while it is still live; expired or unreadable -> null. */
export function readPendingLink(): PendingLink | null {
  try {
    const raw = localStorage.getItem(PENDING_LINK_KEY);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const record = parsed as Record<string, unknown>;
    if (typeof record.ticket !== "string" || record.ticket.length === 0) return null;
    const expiresAt = typeof record.expires_at === "string" ? record.expires_at : null;
    if (expiresAt !== null) {
      const target = Date.parse(expiresAt);
      if (Number.isNaN(target) || target <= Date.now()) return null;
    }
    return {
      ticket: record.ticket,
      expires_at: expiresAt,
      telegram_url:
        typeof record.telegram_url === "string" ? record.telegram_url : null,
    };
  } catch {
    return null;
  }
}

export function writePendingLink(link: PendingLink): void {
  try {
    localStorage.setItem(PENDING_LINK_KEY, JSON.stringify(link));
  } catch {
    // A blocked store only costs the reload-resume, never the link itself.
  }
}

export function clearPendingLink(): void {
  try {
    localStorage.removeItem(PENDING_LINK_KEY);
  } catch {
    // Best effort.
  }
}

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

/**
 * Whether the anonymous install pseudonym travels with a report.
 *
 * On by default: it costs the reporter nothing and it is what lets the Owner
 * see who is finding the most bugs. Stated explicitly in the panel, and off
 * means the backend sends no header at all.
 */
export function readPseudonymPreference(): boolean {
  try {
    return localStorage.getItem(PSEUDONYM_KEY) !== "0";
  } catch {
    return true;
  }
}

/** Remember the choice; a blocked store keeps it for this session only. */
export function writePseudonymPreference(on: boolean): void {
  try {
    localStorage.setItem(PSEUDONYM_KEY, on ? "1" : "0");
  } catch {
    // Best effort: losing the preference must never break the panel.
  }
}
