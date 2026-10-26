import { apiFetch } from "@/api/client";
import { API_BASE_URL } from "@/lib/constants";
import type {
  BugReportBundle,
  BugReportFallback,
  BugReportRelease,
  BugReportLinkStatus,
  BugReportLinkTicket,
  BugReportSubmitPayload,
  BugReportSubmitResult,
} from "@/api/types";

/**
 * Bug-report client — Perfil → Reporte de errores.
 *
 * Three calls, all through `apiFetch` (structured `ApiError` on failures):
 * the read-only assemble that builds the default, allow-listed,
 * content-scanned bundle server-side (the browser sandbox cannot read local
 * logs/`uname`), the stateless submit that re-validates and delivers through
 * the relay, and the strict fallback that returns a privacy-scrubbed
 * copy-paste issue body when delivery is unavailable. The times are explicit
 * per call: assemble and fallback are quick server-only operations (10s),
 * submit adds relay delivery round-trip slack (15s).
 */

/** GET /api/bugreport/assemble — the default report bundle. Principal-gated
 *  (401 when unauthenticated); world data, `.env` and the account username
 *  are excluded server-side by construction. */
export function assembleBugReport(): Promise<BugReportBundle> {
  return apiFetch<BugReportBundle>(`${API_BASE_URL}/api/bugreport/assemble`, {
    credentials: "same-origin",
    timeout: 10_000,
  });
}

/**
 * POST /api/bugreport/submit — re-validated (allow-list + caps + rate limit),
 * stateless relay delivery. Failures surface as `ApiError` with the stable codes
 * `bugreport.not_allowlisted` / `bugreport.too_large` /
 * `bugreport.invalid_attachment` / `bugreport.rate_limited` /
 * `bugreport.relay_unavailable` / `bugreport.delivery_failed`.
 *
 * With screenshots the request is `multipart/form-data` — the reviewed bundle in
 * a `report` part and each image as an `attachments` part — because binaries must
 * never ride inside the allow-listed JSON bundle or its size cap. Without them it
 * stays a plain JSON POST.
 */
export function submitBugReport(
  payload: BugReportSubmitPayload,
  attachments: File[] = [],
): Promise<BugReportSubmitResult> {
  const body =
    attachments.length === 0
      ? JSON.stringify(payload)
      : (() => {
          const form = new FormData();
          form.set("report", JSON.stringify(payload));
          for (const file of attachments) {
            form.append("attachments", file, file.name);
          }
          return form;
        })();
  return apiFetch<BugReportSubmitResult>(
    `${API_BASE_URL}/api/bugreport/submit`,
    {
      method: "POST",
      credentials: "same-origin",
      body,
      timeout: 30_000,
    },
  );
}

/** POST /api/bugreport/fallback — server-scrubbed copy-paste issue body plus
 *  the `maar1223/Demiurgos` issue-form link. Strict fallback: offered only
 *  when relay delivery is unavailable or failed. */
export function fallbackBody(
  payload: BugReportSubmitPayload,
): Promise<BugReportFallback> {
  return apiFetch<BugReportFallback>(`${API_BASE_URL}/api/bugreport/fallback`, {
    method: "POST",
    credentials: "same-origin",
    body: JSON.stringify(payload),
    timeout: 10_000,
  });
}
/** Flags the panel states when minting a ticket. Omitted means "leave as is". */
export interface BugReportLinkFlags {
  report_identity?: boolean;
  notify_releases?: boolean;
}

/**
 * POST /api/bugreport/link/start — mint (or reuse) the linking ticket.
 *
 * The backend resolves the stable account key server-side and proxies the relay
 * with the shared key, so the browser never talks to the relay. Reopening the
 * panel reuses a live ticket instead of burning the three-per-hour allowance.
 */
export function startTelegramLink(
  flags: BugReportLinkFlags = {},
): Promise<BugReportLinkTicket> {
  return apiFetch<BugReportLinkTicket>(
    `${API_BASE_URL}/api/bugreport/link/start`,
    {
      method: "POST",
      credentials: "same-origin",
      body: JSON.stringify(flags),
      timeout: 15_000,
    },
  );
}

/** POST /api/bugreport/link/status — poll the ticket. On completion the backend
 *  stores the signing token; this answer never carries it. */
export function telegramLinkStatus(
  ticket: string,
): Promise<BugReportLinkStatus> {
  return apiFetch<BugReportLinkStatus>(
    `${API_BASE_URL}/api/bugreport/link/status`,
    {
      method: "POST",
      credentials: "same-origin",
      body: JSON.stringify({ ticket }),
      timeout: 10_000,
    },
  );
}

/** POST /api/bugreport/link/revoke — unlink this install. The relay drops the
 *  binding and blocks the dead credential; the backend forgets the token. */
export function revokeTelegramLink(): Promise<{ revoked: boolean }> {
  return apiFetch<{ revoked: boolean }>(
    `${API_BASE_URL}/api/bugreport/link/revoke`,
    {
      method: "POST",
      credentials: "same-origin",
      body: JSON.stringify({}),
      timeout: 15_000,
    },
  );
}

/** GET /api/bugreport/releases — released versions and the reports they fixed.
 *  The list is public; the app matches the ids it kept locally (S12). */
export function getBugReportReleases(): Promise<{ releases: BugReportRelease[] }> {
  return apiFetch<{ releases: BugReportRelease[] }>(
    `${API_BASE_URL}/api/bugreport/releases`,
    { credentials: "same-origin", timeout: 10_000 },
  );
}
