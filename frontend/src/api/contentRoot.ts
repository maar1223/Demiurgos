import { apiFetch } from "@/api/client";
import type { OnboardingStatus } from "@/api/types";
import { API_BASE_URL } from "@/lib/constants";

/**
 * Content folder API (step 4).
 *
 * `GET /api/data-root` reports the folder the running app uses plus the facts a
 * picker needs; `POST /api/data-root` records a new one. A recorded change moves
 * no bytes and takes effect on the NEXT start, so the response carries
 * `restart_required` and the step must offer a restart instead of continuing.
 */

export interface ContentRootDisk {
  free_bytes: number | null;
  total_bytes: number | null;
  volume: string | null;
}

export interface ContentRootInfo {
  path: string | null;
  origin: "env" | "pointer" | "unconfigured";
  configured: boolean;
  recorded_path: string | null;
  pending_restart: boolean;
  usable: boolean;
  worlds: number;
  disk: ContentRootDisk;
  mode: "mirrored" | "streaming" | "unknown";
  warning: string | null;
  reason: string | null;
  restart_required?: boolean;
}

/** GET /api/data-root — the folder in use, its disk facts and its usability. */
export function getContentRoot(): Promise<ContentRootInfo> {
  return apiFetch<ContentRootInfo>(`${API_BASE_URL}/api/data-root`);
}

/** POST /api/data-root — record a new folder (takes effect on the next start). */
export function setContentRoot(path: string): Promise<ContentRootInfo> {
  return apiFetch<ContentRootInfo>(`${API_BASE_URL}/api/data-root`, {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

/** POST /api/onboarding/content-folder — mark the step done, nothing moves. */
export function commitContentFolderStep(): Promise<OnboardingStatus> {
  return apiFetch<OnboardingStatus>(
    `${API_BASE_URL}/api/onboarding/content-folder`,
    { method: "POST" },
  );
}
