import { useCallback, useContext, useState } from "react";
import { LocaleContext } from "@/i18n/LocaleProvider";
import { translate, type MessageKey, type TFunction, type TParams } from "@/i18n/messages";
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
 *
 * The fallback `t` is referentially stable across renders — consumers use it
 * in `useCallback`/`useEffect` dependency arrays, so a fresh function per
 * render would make those effects re-run on every paint.
 */
export function useAppLanguage(): { language: AppLanguage; t: TFunction } {
  const context = useContext(LocaleContext);
  const [cachedLanguage] = useState(() =>
    resolveLanguage(readCachedLocale().ui),
  );
  const fallbackT = useCallback(
    (key: MessageKey, params?: TParams) =>
      translate(cachedLanguage, key, params),
    [cachedLanguage],
  );
  if (context) {
    return { language: context.language, t: context.t };
  }
  return { language: cachedLanguage, t: fallbackT };
}

/** Primary name for new code (AD-3); the same value as `useAppLanguage`. */
export const useTranslation = useAppLanguage;