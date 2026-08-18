import { apiFetch } from "@/api/client";
import type { AppConfig, LocaleSettings } from "@/api/types";
import { API_BASE_URL } from "@/lib/constants";

/**
 * GET /api/config — non-sensitive global runtime metadata.
 * The normalized `language` is the single source of truth for visible copy.
 */
export function getAppConfig(): Promise<AppConfig> {
  return apiFetch<AppConfig>(`${API_BASE_URL}/api/config`, { timeout: 3_000 });
}

/**
 * GET /api/locale — G7/OC3 locale with independent UI/conversation/content
 * languages, an explicit region override, and an IANA timezone.
 */
export function getLocale(): Promise<LocaleSettings> {
  return apiFetch<LocaleSettings>(`${API_BASE_URL}/api/locale`, { timeout: 3_000 });
}
