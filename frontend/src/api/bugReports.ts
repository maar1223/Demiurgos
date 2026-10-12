import { apiFetch } from "@/api/client";
import { API_BASE_URL } from "@/lib/constants";
import type {
  BugReportBundle,
  BugReportFallback,
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

/** POST /api/bugreport/submit — re-validated (allow-list + caps + rate
 *  limit), stateless relay delivery. Failures surface as `ApiError` with the
 *  stable codes `bugreport.not_allowlisted` / `bugreport.too_large` /
 *  `bugreport.rate_limited` / `bugreport.relay_unavailable` /
 *  `bugreport.delivery_failed`. */
export function submitBugReport(
  payload: BugReportSubmitPayload,
): Promise<BugReportSubmitResult> {
  return apiFetch<BugReportSubmitResult>(
    `${API_BASE_URL}/api/bugreport/submit`,
    {
      method: "POST",
      credentials: "same-origin",
      body: JSON.stringify(payload),
      timeout: 15_000,
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