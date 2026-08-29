import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { CardState } from "@/api/types";
import {
  CARD_DEFS,
  DEFERRED_CARD_KEYS,
  ESSENTIAL_BADGES,
  MigrationPanel,
  REMOTE_LABELS,
  STATE_META,
  cardLabel,
  cardState,
  essentialBadgeFor,
} from "@/pages/ConfigurationCenter";

/**
 * ConfigurationCenter is now a shared exporter module (nav-restructure
 * decision): the standalone `/centro-configuracion` page and route are gone —
 * the surface lives inside the Profile (`/perfil` → "Centro de Configuración"
 * tab, with the idea-capture wizard under Integraciones and MigrationPanel
 * under Mundos). These tests pin the module's remaining contract: card
 * definitions, honest state helpers and the re-exported migration panel. The
 * panel has a dedicated suite (MigrationPanel.test.tsx) and the Profile tabs
 * are covered by ProfilePage.test.tsx.
 */
describe("ConfigurationCenter shared module (OC12, nav-restructure)", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("exposes the eight OC12 card definitions with honest descriptions", () => {
    const keys = CARD_DEFS.map((card) => card.key);
    expect(keys).toEqual([
      "identity",
      "assistant",
      "telegram",
      "backup",
      "locale",
      "world",
      "offline",
      "import",
    ]);
    // Every card carries a title, a description and an explicit action (or null).
    for (const card of CARD_DEFS) {
      expect(card.title.length).toBeGreaterThan(0);
      expect(card.description.length).toBeGreaterThan(0);
    }
    // The import card keeps the operational copy (world-importer slice 2).
    const importCard = CARD_DEFS.find((card) => card.key === "import");
    expect(importCard?.description).toMatch(/El importador está operativo/i);
  });

  it("cardState never overstates deferred capabilities (ONB-3.1/ONB-3.5)", () => {
    const stale: Record<string, CardState> = Object.fromEntries(
      CARD_DEFS.map((card) => [card.key, "configured"]),
    );
    // backup and import lack dedicated contracts → forced pending.
    for (const key of DEFERRED_CARD_KEYS) {
      expect(cardState(stale, key)).toBe("pending");
    }
    // identity (auth-google-vault R-ID1 backend contract), telegram (WU-3b1,
    // ONB-3.3), assistant, locale, world and offline may truthfully render
    // configured.
    for (const key of ["identity", "telegram", "assistant", "locale", "world", "offline"]) {
      expect(cardState(stale, key)).toBe("configured");
    }
    // Unknown keys default to pending.
    expect(cardState({}, "nope")).toBe("pending");
  });

  it("cardLabel reports the OC19 assistant label instead of bare pending", () => {
    expect(cardLabel("assistant", "pending")).toBe("Pendiente / no apto");
    expect(cardLabel("assistant", "configured")).toBe("Configurado");
    expect(cardLabel("telegram", "pending")).toBe("Pendiente");
    expect(cardLabel("telegram", "requires_connection")).toBe("Requiere conexión");
    expect(cardLabel("telegram", "error")).toBe("Error");
  });

  it("essentialBadgeFor reflects local editor and world truth (OC11/OC21)", () => {
    const cards: Record<string, CardState> = { world: "configured" };
    expect(
      essentialBadgeFor({ local_editor: { probe: "local_editor", ok: true, detail: "ok" } } as never, cards, "editor"),
    ).toEqual({ label: "Listo", badge: "success" });
    expect(
      essentialBadgeFor({ local_editor: { probe: "local_editor", ok: false, detail: "read-back mismatch" } } as never, cards, "editor"),
    ).toEqual({ label: "No disponible", badge: "error" });
    expect(
      essentialBadgeFor(null, cards, "world"),
    ).toEqual({ label: "Listo", badge: "success" });
    expect(
      essentialBadgeFor(null, { world: "pending" }, "world"),
    ).toEqual({ label: "Pendiente", badge: "default" });
  });

  it("exposes the essential badges, remote labels and state meta", () => {
    expect(ESSENTIAL_BADGES.map((b) => b.key)).toEqual(["world", "editor"]);
    expect(REMOTE_LABELS).toMatchObject({
      identity: "Identidad",
      telegram: "Telegram",
      backup: "Respaldo",
      assistant: "Asistente (IA)",
    });
    expect(STATE_META.pending.label).toBe("Pendiente");
    expect(STATE_META.configured.badge).toBe("success");
    expect(STATE_META.requires_connection.label).toBe("Requiere conexión");
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