import { apiFetch } from "@/api/client";
import { API_BASE_URL } from "@/lib/constants";
import type { UpdateApplyResult, UpdateChannel, UpdateStatus } from "@/api/types";

/**
 * In-app updater client (manual check + detached apply).
 *
 * The panel that consumes these calls is manual-only: every request is issued
 * on an explicit user action, never on mount and never on a timer. The status
 * payload is advisory — the backend never authorizes an install from it. Only
 * `applyUpdate` dispatches an install, and its result never carries a version
 * that the client supplied: the backend resolves the target server-side.
 */

/** GET /api/update/status — current version, selected channel and advisory
 *  latest for that channel. Principal-gated (401 when unauthenticated). */
export function getUpdateStatus(): Promise<UpdateStatus> {
  return apiFetch<UpdateStatus>(`${API_BASE_URL}/api/update/status`, {
    credentials: "same-origin",
    timeout: 5_000,
  });
}

/** PUT /api/update/channel — persist the selected channel. Invalid values are
 *  rejected server-side with `update.invalid_channel` (persisted value stays). */
export function setUpdateChannel(
  channel: UpdateChannel,
): Promise<{ channel: UpdateChannel }> {
  return apiFetch<{ channel: UpdateChannel }>(
    `${API_BASE_URL}/api/update/channel`,
    {
      method: "PUT",
      credentials: "same-origin",
      body: JSON.stringify({ channel }),
      timeout: 5_000,
    },
  );
}

/**
 * POST /api/update/apply — dispatch the installer for the server-resolved
 * offered version. The local session MUST be logged out BEFORE this call, and
 * the call MUST use the long install timeout (90s) instead of the apiFetch
 * default 5s (precedent: `systemControlAction` in `@/api/wiki`). A dropped
 * connection during the install is the EXPECTED outcome (the installer
 * restarts the stack) and surfaces as `ApiError(status: 0)`.
 */
export function applyUpdate(): Promise<UpdateApplyResult> {
  return apiFetch<UpdateApplyResult>(`${API_BASE_URL}/api/update/apply`, {
    method: "POST",
    credentials: "same-origin",
    timeout: 90_000,
  });
}
