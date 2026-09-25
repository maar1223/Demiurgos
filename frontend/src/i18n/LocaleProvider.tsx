import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getLocale } from "@/api/config";
import type { AppLanguage, LocaleSettings } from "@/api/types";
import { translate, type MessageKey, type TParams } from "@/i18n/messages";
import {
  readCachedLocale,
  STORAGE_KEY,
} from "@/hooks/useAppLocale";

/**
 * Single owner of the runtime locale (AD-2). The provider seeds synchronously
 * from the `demiurgos-locale` cache so the first paint already matches the
 * persisted locale, then refines from `GET /api/locale` (backend-authoritative)
 * and re-renders the whole tree on any change → instant switch, no reload.
 * The shell effect keeps `<html lang>` and `document.title` in sync (UI-REQ-5).
 */
export interface LocaleContextValue {
  locale: LocaleSettings;
  language: AppLanguage;
  t: (key: MessageKey, params?: TParams) => string;
  /** Instant switch: applies a locale without a refetch. */
  applyLocale: (next: LocaleSettings) => void;
  /** Refetch the backend-authoritative locale and apply it. */
  refreshLocale: () => Promise<void>;
}

export const LocaleContext = createContext<LocaleContextValue | null>(null);

function resolveLanguage(value: string): AppLanguage {
  return value === "en" ? "en" : "es";
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<LocaleSettings>(readCachedLocale);
  const language = resolveLanguage(locale.ui);

  // Refine from the backend exactly once; keep the cache in sync so the next
  // first paint matches (AD-10). Failure keeps the cached/safe default.
  useEffect(() => {
    let active = true;
    void getLocale()
      .then((value) => {
        if (!active) return;
        setLocale(value);
        if (typeof window !== "undefined") {
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
        }
      })
      .catch(() => {
        // offline/failure — keep the cached/safe default; never invent values
      });
    return () => {
      active = false;
    };
  }, []);

  const t = useCallback(
    (key: MessageKey, params?: TParams) => translate(language, key, params),
    [language],
  );

  const applyLocale = useCallback((next: LocaleSettings) => {
    setLocale(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    }
  }, []);

  const refreshLocale = useCallback(async () => {
    try {
      const value = await getLocale();
      setLocale(value);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
      }
    } catch {
      // keep the current locale; never invent values
    }
  }, []);

  // Runtime document shell sync: <html lang> and the document title follow
  // the active locale (UI-REQ-5, UI-SCN-5.1, UI-SCN-5.2).
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.lang = language;
    document.title = translate(language, "document.title");
  }, [language]);

  const value = useMemo<LocaleContextValue>(
    () => ({ locale, language, t, applyLocale, refreshLocale }),
    [locale, language, t, applyLocale, refreshLocale],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

/**
 * Read the locale context. Falls back to a stable, synchronous value derived
 * from the cache when no provider is mounted (isolated tests / SSR), so
 * consumers never crash outside the app tree.
 */
export function useLocale(): LocaleContextValue {
  const context = useContext(LocaleContext);
  if (context) return context;
  const cached = readCachedLocale();
  const language = resolveLanguage(cached.ui);
  return {
    locale: cached,
    language,
    t: (key: MessageKey, params?: TParams) => translate(language, key, params),
    applyLocale: () => undefined,
    refreshLocale: async () => undefined,
  };
}