import { createElement } from "react";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { LocaleProvider } from "@/i18n/LocaleProvider";
import { translate, type MessageKey, type TParams } from "@/i18n/messages";
import { DEFAULT_LOCALE } from "@/hooks/useAppLocale";
import type { LocaleSettings } from "@/api/types";

/**
 * Test helpers for key-based copy assertions (AD-11, UI-REQ-8): migrated
 * suites assert through the catalogue or `data-testid`, never bare literals,
 * so copy edits and de-voseo do not churn the suite.
 */

/** Resolve a catalogue key in the es locale for assertions. */
export function tEs(key: MessageKey, params?: TParams): string {
  return translate("es", key, params);
}

/** Resolve a catalogue key in the en locale for assertions. */
export function tEn(key: MessageKey, params?: TParams): string {
  return translate("en", key, params);
}

/**
 * Render a node inside LocaleProvider seeded with the given locale (the
 * cache is set before mount so the provider's first paint already matches).
 */
export function renderWithLocale(
  ui: ReactElement,
  locale: LocaleSettings = DEFAULT_LOCALE,
) {
  window.localStorage.setItem("demiurgos-locale", JSON.stringify(locale));
  return render(createElement(LocaleProvider, null, ui));
}