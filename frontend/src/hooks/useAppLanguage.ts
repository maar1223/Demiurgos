import { useAppLocale } from "@/hooks/useAppLocale";
import type { AppLanguage } from "@/api/types";

/** Safe frontend default when the config endpoint is unreachable. */
export const DEFAULT_APP_LANGUAGE: AppLanguage = "es";

function resolveLanguage(value: string): AppLanguage {
  return value === "en" ? "en" : "es";
}

/**
 * The configured global UI language. Prefers the G7/OC3 locale (independent
 * UI domain from GET /api/locale) and falls back to the legacy /api/config
 * projection. Falls back to the project default (es) when unreachable.
 * Returns synchronously on first render, then refines once locale loads.
 */
export function useAppLanguage(): AppLanguage {
  const locale = useAppLocale();
  return resolveLanguage(locale.ui);
}
