import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
export type ThemeMode = Theme | "system";

export const THEME_STORAGE_KEY = "demiurgos-theme";

export const FAVICON_LIGHT = "/favicon-light.svg";
export const FAVICON_DARK = "/favicon-dark.svg";

/**
 * Theme hook for the Demiurgos brand theme (PR-1).
 *
 * - The user-facing choice is binary: "light" | "dark". A manual pick is
 *   persisted in localStorage under `demiurgos-theme` and wins from then on.
 * - "system" is INTERNAL ONLY: it is the initial/default mode while the user
 *   has not picked yet, and it resolves by following the OS `prefers-color-scheme`
 *   live (THEME-01). The user is never offered "system"; once they pick
 *   manually, the mode is pinned to that explicit value and "system" no
 *   longer applies.
 * - Applies the `.dark` class on <html> and swaps the favicon per resolved
 *   theme (FAVICON-01), mirroring the anti-FOUC inline script in index.html.
 *
 * Guarded for environments without `window.matchMedia` (e.g. jsdom tests).
 */
export function systemPrefersDark(): boolean {
  if (typeof window === "undefined") return false;
  if (typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Reads the stored theme, falling back to the system preference. */
export function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // localStorage unavailable (blocked storage / file://) — fall through to
    // the system preference.
  }
  return systemPrefersDark() ? "dark" : "light";
}

export function useTheme(): {
  /** Effective theme applied to the DOM ("light" | "dark"). */
  resolvedTheme: Theme;
  /** Sets the theme ("light" | "dark"), persisting it to localStorage. */
  setTheme: (mode: Theme) => void;
  /** Current effective theme ("light" | "dark"). */
  theme: Theme;
} {
  const [mode, setThemeMode] = useState<ThemeMode>(() => {
    try {
      const stored = localStorage.getItem(THEME_STORAGE_KEY);
      if (stored === "light" || stored === "dark") return stored;
    } catch {
      // localStorage unavailable — default to following the system.
    }
    return "system";
  });
  const [resolvedTheme, setResolvedTheme] = useState<Theme>(getInitialTheme);

  const applyTheme = useCallback((next: Theme) => {
    document.documentElement.classList.toggle("dark", next === "dark");
    const favicon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (favicon) {
      favicon.href = next === "dark" ? FAVICON_DARK : FAVICON_LIGHT;
    }
    setResolvedTheme(next);
  }, []);

  // Keep the DOM in sync with the persisted/system state on mount.
  useEffect(() => {
    applyTheme(getInitialTheme());
  }, [applyTheme]);

  // Follow the mode: explicit choice, or live system changes while "system".
  useEffect(() => {
    if (mode !== "system") {
      applyTheme(mode);
      return;
    }
    applyTheme(systemPrefersDark() ? "dark" : "light");
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (event: MediaQueryListEvent) => {
      applyTheme(event.matches ? "dark" : "light");
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [mode, applyTheme]);

  const setTheme = useCallback(
    (next: Theme) => {
      // The public choice is binary: once the user picks light/dark, the mode
      // is pinned to that explicit value and "system" no longer applies.
      setThemeMode(next);
      try {
        localStorage.setItem(THEME_STORAGE_KEY, next);
      } catch {
        // localStorage unavailable — the in-memory mode still applies.
      }
    },
    [],
  );

  return { resolvedTheme, setTheme, theme: resolvedTheme };
}
