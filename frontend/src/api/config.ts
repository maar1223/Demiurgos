import { apiFetch } from "@/api/client";
import type { AppConfig } from "@/api/types";
import { API_BASE_URL } from "@/lib/constants";

/**
 * GET /api/config — non-sensitive global runtime metadata.
 * The normalized `language` is the single source of truth for visible copy.
 */
export function getAppConfig(): Promise<AppConfig> {
  return apiFetch<AppConfig>(`${API_BASE_URL}/api/config`, { timeout: 3_000 });
}
