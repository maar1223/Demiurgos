import { apiFetch } from "@/api/client";
import { API_BASE_URL } from "@/lib/constants";
import type { UpdateChannel, UpdateStatus } from "@/api/types";

/**
 * In-app updater client (read-only check surface, v1).
 *
 * The panel that consumes these calls is manual-only: every request is issued
 * on an explicit user action, never on mount and never on a timer. The status
 * payload is advisory — the backend never authorizes an install from it.
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
