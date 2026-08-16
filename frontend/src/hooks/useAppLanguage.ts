import { useEffect, useState } from "react";
import { getAppConfig } from "@/api/config";
import type { AppLanguage } from "@/api/types";

/** Safe frontend default when the config endpoint is unreachable. */
export const DEFAULT_APP_LANGUAGE: AppLanguage = "es";

let cachedLanguage: AppLanguage | null = null;
let inflight: Promise<AppLanguage> | null = null;

function resolveLanguage(value: AppLanguage): AppLanguage {
  return value === "en" ? "en" : "es";
}

async function loadAppLanguage(): Promise<AppLanguage> {
  if (cachedLanguage) return cachedLanguage;
  if (!inflight) {
    inflight = getAppConfig()
      .then((config) => {
        cachedLanguage = resolveLanguage(config.language);
        return cachedLanguage;
      })
      .catch(() => DEFAULT_APP_LANGUAGE)
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/**
 * The configured global UI language (DEMIURGOS_LANGUAGE via /api/config).
 * Falls back to the project default (es) when the endpoint is unreachable.
 * Returns synchronously on first render, then refines once config loads.
 */
export function useAppLanguage(): AppLanguage {
  const [language, setLanguage] = useState<AppLanguage>(
    () => cachedLanguage ?? DEFAULT_APP_LANGUAGE,
  );

  useEffect(() => {
    let active = true;
    void loadAppLanguage().then((value) => {
      if (active) setLanguage(value);
    });
    return () => {
      active = false;
    };
  }, []);

  return language;
}
