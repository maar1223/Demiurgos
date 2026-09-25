import { useContext } from "react";
import { LocaleContext } from "@/i18n/LocaleProvider";
import { translate, type TFunction } from "@/i18n/messages";
import { readCachedLocale } from "@/hooks/useAppLocale";
import type { AppLanguage } from "@/api/types";

/** Safe frontend default when the config endpoint is unreachable. */
export const DEFAULT_APP_LANGUAGE: AppLanguage = "es";

function resolveLanguage(value: string): AppLanguage {
  return value === "en" ? "en" : "es";
}

/**
 * The single chrome driver (AD-3, UI-REQ-2): the active UI language plus the
 * `t` helper resolving every chrome string through the catalogue. Reads the
 * LocaleProvider context; outside the provider it falls back to a synchronous
 * `t` bound to the cached locale (isolated tests / SSR).
 */
export function useAppLanguage(): { language: AppLanguage; t: TFunction } {
  const context = useContext(LocaleContext);
  if (context) {
    return { language: context.language, t: context.t };
  }
  const language = resolveLanguage(readCachedLocale().ui);
  return { language, t: (key, params) => translate(language, key, params) };
}

/** Primary name for new code (AD-3); the same value as `useAppLanguage`. */
export const useTranslation = useAppLanguage;