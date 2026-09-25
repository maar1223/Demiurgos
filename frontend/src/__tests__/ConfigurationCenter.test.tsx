import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { CardState } from "@/api/types";
import {
  CARD_DEFS,
  DEFERRED_CARD_KEYS,
  ESSENTIAL_BADGES,
  MigrationPanel,
  STATE_META,
  cardLabelKey,
  cardState,
  essentialBadgeFor,
} from "@/pages/ConfigurationCenter";
import { tEs } from "@/__tests__/i18nTestUtils";

/**
 * ConfigurationCenter is now a shared exporter module (nav-restructure
 * decision): the standalone `/centro-configuracion` page and route are gone —
 * the surface lives inside the Profile (`/perfil` → "Preferencias", with the
 * idea-capture wizard under Conexiones and MigrationPanel under Mundos).
 * These tests pin the module's remaining contract: card definitions, honest
 * state helpers and the re-exported migration panel. The panel has a dedicated
 * suite (MigrationPanel.test.tsx) and the Profile sections are covered by
 * ProfilePage.test.tsx.
 *
 * i18n (app-bilingual-i18n): every user-visible string lives in the catalogue
 * behind a `MessageKey`; assertions resolve through `tEs` so a copy change or
 * a locale switch never breaks a contract test (UI-REQ-8).
 */
describe("ConfigurationCenter shared module (OC12, nav-restructure)", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("exposes the six OC12 card definitions with honest descriptions", () => {
    const keys = CARD_DEFS.map((card) => card.key);
    expect(keys).toEqual([
      "identity",
      "assistant",
      "telegram",
      "locale",
      "world",
      "import",
    ]);
    // Every card carries a title, a description and an explicit action (or null).
    for (const card of CARD_DEFS) {
      expect(tEs(card.titleKey).length).toBeGreaterThan(0);
      expect(tEs(card.descriptionKey).length).toBeGreaterThan(0);
    }
    // The import card keeps the operational copy (world-importer slice 2).
    const importCard = CARD_DEFS.find((card) => card.key === "import");
    expect(tEs(importCard!.descriptionKey)).toMatch(/El importador está operativo/i);

    // The redundant backup card was removed (product-owner decision): it only
    // pointed at the Respaldo section, which already has its own rail entry.
    // The Offline/dispositivo card was removed for the same redundancy reason:
    // the locale card still targets Preferencias — the `configuracion` tab and
    // the `?step=step0` reconfigure path no longer exist.
    expect(CARD_DEFS.some((card) => card.key === "backup")).toBe(false);
    expect(CARD_DEFS.some((card) => card.key === "offline")).toBe(false);
    const localeCard = CARD_DEFS.find((card) => card.key === "locale");
    expect(localeCard?.action).toEqual({
      labelKey: "configCenter.card.locale.action",
      to: "/perfil?tab=preferencias",
    });
    expect(tEs(localeCard!.action!.labelKey)).toBe("Configurar");
  });

  it("cardState never overstates deferred capabilities (ONB-3.1/ONB-3.5)", () => {
    const stale: Record<string, CardState> = {
      ...Object.fromEntries(CARD_DEFS.map((card) => [card.key, "configured"])),
      // `backup` no longer has a card definition, but its readiness contract is
      // unchanged: it left the forced-pending set, so its dedicated contract
      // (backup_state) is the authority.
      backup: "configured",
    };
    // import lacks a dedicated contract → forced pending.
    for (const key of DEFERRED_CARD_KEYS) {
      expect(cardState(stale, key)).toBe("pending");
    }
    // SC-CC-2.2 — backup left the forced-pending set; its own dedicated
    // contract (backup_state) is the authority, so a stale claim is no longer
    // downgraded here. The BackupSection still gates "Configurado" on evidence.
    expect(DEFERRED_CARD_KEYS.has("backup")).toBe(false);
    expect([...DEFERRED_CARD_KEYS]).toEqual(["import"]);
    expect(cardState(stale, "backup")).toBe("configured");
    // identity (auth-vault-credentials R-ID1 backend contract), telegram (WU-3b1,
    // ONB-3.3), assistant, locale and world may truthfully render configured.
    for (const key of ["identity", "telegram", "assistant", "locale", "world"]) {
      expect(cardState(stale, key)).toBe("configured");
    }
    // Unknown keys default to pending.
    expect(cardState({}, "nope")).toBe("pending");
  });

  it("cardLabel reports the OC19 assistant label instead of bare pending", () => {
    expect(tEs(cardLabelKey("assistant", "pending"))).toBe("Pendiente / no apto");
    expect(tEs(cardLabelKey("assistant", "configured"))).toBe("Configurado");
    expect(tEs(cardLabelKey("telegram", "pending"))).toBe("Pendiente");
    expect(tEs(cardLabelKey("telegram", "requires_connection"))).toBe("Requiere conexión");
    expect(tEs(cardLabelKey("telegram", "error"))).toBe("Error");
  });

  it("essentialBadgeFor reflects local editor and world truth (OC11/OC21)", () => {
    const cards: Record<string, CardState> = { world: "configured" };
    expect(
      essentialBadgeFor({ local_editor: { probe: "local_editor", ok: true, detail: "ok" } } as never, cards, "editor", tEs),
    ).toEqual({ label: "Listo", badge: "success" });
    expect(
      essentialBadgeFor({ local_editor: { probe: "local_editor", ok: false, detail: "read-back mismatch" } } as never, cards, "editor", tEs),
    ).toEqual({ label: "No disponible", badge: "error" });
    expect(
      essentialBadgeFor(null, cards, "world", tEs),
    ).toEqual({ label: "Listo", badge: "success" });
    expect(
      essentialBadgeFor(null, { world: "pending" }, "world", tEs),
    ).toEqual({ label: "Pendiente", badge: "default" });
  });

  it("exposes the essential badges and state meta", () => {
    expect(ESSENTIAL_BADGES.map((b) => b.key)).toEqual(["world", "editor"]);
    expect(tEs(STATE_META.pending.labelKey)).toBe("Pendiente");
    expect(STATE_META.configured.badge).toBe("success");
    expect(tEs(STATE_META.requires_connection.labelKey)).toBe("Requiere conexión");
    expect(STATE_META.error.badge).toBe("error");
  });

  it("re-exports MigrationPanel (ONB-4.3, WU-4c2) for the Profile Mundos tab", () => {
    const { rerender } = render(
      <MigrationPanel findings={[]} />,
    );
    // No findings → nothing to migrate → no UI at all.
    expect(screen.queryByRole("heading", { name: /migración/i })).not.toBeInTheDocument();
    rerender(
      <MigrationPanel findings={[{ world: "legacy-x", folders: ["Lore"] }]} />,
    );
    expect(
      screen.getByRole("heading", { name: "Migración de carpetas legacy" }),
    ).toBeInTheDocument();
    // Never auto-migrates on mount.
    expect(
      screen.getByRole("button", { name: "Migrar carpetas de legacy-x" }),
    ).toBeInTheDocument();
  });
});
