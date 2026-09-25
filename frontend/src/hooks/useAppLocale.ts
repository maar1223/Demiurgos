import { useContext } from "react";
import { LocaleContext } from "@/i18n/LocaleProvider";
import type { LocaleSettings } from "@/api/types";

/** Safe frontend default when the locale endpoint is unreachable (UTC storage, es UI). */
export const DEFAULT_LOCALE: LocaleSettings = {
  ui: "es",
  conversation: "es",
  content: "es",
  region: null,
  region_explicit: false,
  iana_timezone: "UTC",
};

/** localStorage key persisting the resolved G7/OC3 locale (AD-2, AD-10). */
export const STORAGE_KEY = "demiurgos-locale";

/** Synchronous cache read; the first React render matches the persisted value. */
export function readCachedLocale(): LocaleSettings {
  if (typeof window === "undefined") return DEFAULT_LOCALE;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as LocaleSettings;
  } catch {
    // corrupt cache — fall through to the safe default
  }
  return DEFAULT_LOCALE;
}

/**
 * G7/OC3 runtime locale: independent UI/conversation/content languages plus
 * region override and IANA timezone. Reads the `LocaleProvider` context
 * (AD-2): the provider owns the state, seeds it from the cache, refines it
 * from the backend and re-renders the whole tree on any change, so every
 * consumer follows the same value. Falls back to the cached/safe default when
 * no provider is mounted (isolated tests / SSR).
 */
export function useAppLocale(): LocaleSettings {
  const context = useContext(LocaleContext);
  return context?.locale ?? readCachedLocale();
}