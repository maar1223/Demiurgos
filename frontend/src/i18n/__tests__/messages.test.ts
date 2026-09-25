import { describe, expect, it } from "vitest";
import { CATALOGUE, messages, translate, type MessageKey } from "@/i18n/messages";

const ES_KEYS = Object.keys(messages.es) as MessageKey[];

describe("typed bilingual catalogue (UI-REQ-1)", () => {
  it("defines the same key set in es and en (UI-SCN-1.1)", () => {
    const enKeys = Object.keys(messages.en).sort();
    const esKeys = [...ES_KEYS].sort();
    expect(esKeys).toEqual(enKeys);
  });

  it("holds non-empty strings for every key in both locales (UI-SCN-1.1)", () => {
    for (const key of ES_KEYS) {
      expect(messages.es[key].trim().length).toBeGreaterThan(0);
      expect(messages.en[key].trim().length).toBeGreaterThan(0);
    }
  });

  it("routes every catalogue value through CATALOGUE identically", () => {
    for (const key of ES_KEYS) {
      expect(CATALOGUE.es[key]).toBe(messages.es[key]);
      expect(CATALOGUE.en[key]).toBe(messages.en[key]);
    }
  });

  it("interpolates {name} params into the active-language template", () => {
    expect(translate("es", "nav.world.confirm.message", { name: "Vibrantes" })).toBe(
      "¿Quieres cambiar el mundo activo a «Vibrantes»?",
    );
    expect(translate("en", "nav.world.confirm.message", { name: "Vibrantes" })).toBe(
      'Do you want to change the active world to "Vibrantes"?',
    );
  });

  it("leaves unknown placeholders untouched and coerces numbers", () => {
    expect(translate("es", "profile.mundos.loreBadge", { count: 7 })).toBe("Lore 7");
    expect(translate("es", "profile.cuenta.inDaysMany", { days: 4 })).toBe("en 4 días");
    expect(translate("es", "profile.words.inputLabel", {})).toBe(
      "Palabras claves para {title}",
    );
  });

  it("returns the template verbatim when no params are given", () => {
    expect(translate("es", "onboarding.title")).toBe("Bienvenida a Demiurgos");
    expect(translate("en", "assistant.session.defaultTitle")).toBe("New session");
  });

  it("exposes the neutral-Spanish default title without mojibake", () => {
    expect(messages.es["assistant.session.defaultTitle"]).toBe("Nueva sesión");
  });
});