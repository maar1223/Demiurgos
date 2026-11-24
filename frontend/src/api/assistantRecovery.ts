import { apiFetch } from "@/api/client";
import type {
  AssistantRecoveryStatus,
  AssistantRestartResponse,
} from "@/api/types";

const CREDENTIALS = { credentials: "same-origin" as const };

/**
 * Recovery read model for the assistant runtime (S11).
 *
 * The server owns the closed cause vocabulary; the client renders localized
 * copy and never sees raw provider, gateway or log text. The endpoint is
 * authenticated and fails closed: a non-200 read simply leaves the banner
 * without a cause.
 */
export function getAssistantRecoveryStatus(): Promise<AssistantRecoveryStatus> {
  return apiFetch<AssistantRecoveryStatus>("/api/system/assistant", CREDENTIALS);
}

/**
 * Restart ONLY the assistant runtime. The API and the user's in-flight work
 * survive; the server coalesces repeated requests and reports whether the
 * launcher dispatch was accepted.
 */
export function restartAssistant(): Promise<AssistantRestartResponse> {
  return apiFetch<AssistantRestartResponse>("/api/system/assistant/restart", {
    method: "POST",
    ...CREDENTIALS,
    timeout: 15_000,
  });
}
