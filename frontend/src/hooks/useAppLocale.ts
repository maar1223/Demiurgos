import { useEffect, useState } from "react";
import { getLocale } from "@/api/config";
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

const STORAGE_KEY = "demiurgos-locale";

function readCachedLocale(): LocaleSettings {
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
 * region override and IANA timezone. Sourced from the backend (authoritative);
 * a local cache keeps the first render stable offline. Timestamps are stored
 * UTC; the IANA zone governs presentation only.
 */
export function useAppLocale(): LocaleSettings {
  const [locale, setLocale] = useState<LocaleSettings>(readCachedLocale);

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

  return locale;
}