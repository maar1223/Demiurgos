import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ConfigurationCenter from "@/pages/ConfigurationCenter";

vi.mock("@/api/onboarding", () => ({
  getReadiness: vi.fn(),
  getOnboardingStatus: vi.fn(),
  submitStep0: vi.fn(),
  createWorld: vi.fn(),
}));

vi.mock("@/api/migration", () => ({
  executeMigration: vi.fn(),
}));

import { getReadiness } from "@/api/onboarding";
import { executeMigration } from "@/api/migration";
import type { Mock } from "vitest";

/** Fresh honest readiness payload (ONB-3.4: offline breakdown included). */
function makeReadiness(overrides: Record<string, unknown> = {}) {
  return {
    local_editor: { probe: "local_editor", ok: true, detail: "ok" },
    cards: {
      identity: "pending",
      assistant: "pending",
      telegram: "pending",
      backup: "pending",
      locale: "configured",
      world: "configured",
      offline: "configured",
      import: "pending",
    },
    offline: {
      local_ready: true,
      remote_pending: ["identity", "telegram", "backup", "assistant"],
    },
    // ONB-4.2: read-only legacy detection — no findings by default.
    legacy: [],
    ...overrides,
  };
}

function renderCenter() {
  return render(
    <MemoryRouter initialEntries={["/centro-configuracion"]}>
      <Routes>
        <Route path="/centro-configuracion" element={<ConfigurationCenter />} />
        <Route path="/wiki" element={<div data-testid="wiki">wiki</div>} />
        <Route path="/perfil" element={<div data-testid="perfil">perfil</div>} />
        <Route path="/onboarding" element={<div data-testid="onboarding">onboarding</div>} />
        <Route path="/taller-mundo" element={<div data-testid="taller-mundo">taller</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ConfigurationCenter (ONB-1.7)", () => {
  beforeEach(() => {
    (getReadiness as Mock).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders every OC12 card with honest states", async () => {
    (getReadiness as Mock).mockResolvedValue(makeReadiness());
    renderCenter();

    expect(
      await screen.findByRole("heading", { name: "Centro de Configuración" }),
    ).toBeInTheDocument();

    for (const title of [
      "Identidad",
      "IA texto y visión",
      "Telegram",
      "Respaldo y restauración",
      "Idioma, región y zona horaria",
      "Mundos",
      "Offline / dispositivo",
      "Importar mundo",
    ]) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }

    // Local core states read as configured; cloud capabilities stay pending.
    expect(screen.getAllByText("Configurado")).toHaveLength(3);
    // Assistant renders its OC19 label instead of the bare generic one.
    expect(screen.getAllByText("Pendiente")).toHaveLength(4);
    expect(screen.getAllByText("Pendiente / no apto")).toHaveLength(1);
  });

  it("shows the local editor essential badge truthfully", async () => {
    (getReadiness as Mock).mockResolvedValue(
      makeReadiness({
        local_editor: { probe: "local_editor", ok: false, detail: "read-back mismatch" },
        cards: {
          identity: "pending",
          assistant: "pending",
          telegram: "pending",
          backup: "pending",
          locale: "pending",
          world: "pending",
          offline: "error",
          import: "pending",
        },
        offline: { local_ready: false, remote_pending: ["identity", "telegram", "backup", "assistant"] },
      }),
    );
    renderCenter();

    await screen.findByRole("heading", { name: "Centro de Configuración" });
    expect(screen.getAllByText("Error")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Offline / dispositivo" })).toBeInTheDocument();
  });

  it("resumes a section in isolation from its card action", async () => {
    (getReadiness as Mock).mockResolvedValue(makeReadiness());
    const user = userEvent.setup();
    renderCenter();

    await screen.findByRole("heading", { name: "Centro de Configuración" });
    await user.click(screen.getAllByRole("button", { name: "Configurar" })[0]);
    expect(screen.getByTestId("perfil")).toBeInTheDocument();
  });

  it("announces card states to assistive tech (aria-live, non-color status)", async () => {
    (getReadiness as Mock).mockResolvedValue(makeReadiness());
    const { container } = renderCenter();

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Centro de Configuración" })).toBeInTheDocument(),
    );
    // Every card is a labelled section with a visible text status, and the
    // state grid is a polite live region (color is never the only signal).
    // The essential-readiness block is a labelled section too.
    const sections = container.querySelectorAll("section[aria-labelledby]");
    expect(sections.length).toBe(9);
    expect(container.querySelector('[aria-live="polite"]')).not.toBeNull();
    expect(screen.getAllByText(/Estado:/)).toHaveLength(11);
  });

  // ---------------------------------------------------------------------------
  // ONB-3.2 — Badges UI (OC11/OC21): World + local editor essential badges and
  // cloud cards that can never render as ready from local evidence.
  // ---------------------------------------------------------------------------

  it("renders essential World + local editor badges from local truth", async () => {
    (getReadiness as Mock).mockResolvedValue(makeReadiness());
    renderCenter();

    const essential = await screen.findByRole("heading", { name: "Listo para trabajar" });
    // World + editor badges read "Listo" only when local truth proves them.
    expect(screen.getByText("Mundos:")).toBeInTheDocument();
    expect(screen.getByText("Editor local:")).toBeInTheDocument();
    expect(within(essential.closest("section") as HTMLElement).getAllByText("Listo")).toHaveLength(2);
  });

  it("shows honest pending essential badges when world or editor is not ready", async () => {
    (getReadiness as Mock).mockResolvedValue(
      makeReadiness({
        local_editor: { probe: "local_editor", ok: false, detail: "read-back mismatch" },
        cards: {
          identity: "pending",
          assistant: "pending",
          telegram: "pending",
          backup: "pending",
          locale: "pending",
          world: "pending",
          offline: "error",
          import: "pending",
        },
        offline: { local_ready: false, remote_pending: ["identity", "telegram", "backup", "assistant"] },
      }),
    );
    renderCenter();

    const essential = await screen.findByRole("heading", { name: "Listo para trabajar" });
    const essentialSection = essential.closest("section") as HTMLElement;
    expect(within(essentialSection).getAllByText("No disponible")).toHaveLength(1);
    expect(within(essentialSection).getAllByText("Pendiente").length).toBeGreaterThanOrEqual(1);
    expect(within(essentialSection).queryByText("Listo")).not.toBeInTheDocument();
  });

  it("never renders cloud cards as ready from stale local evidence", async () => {
    // A stale/buggy backend claims cloud capabilities are configured. The
    // UI must NOT overstate readiness: identity and backup stay pending
    // (they lack dedicated contracts). Telegram is exempt since WU-3b1 gave
    // it a real ONB-3.3 backend contract (server-side getMe proof), so its
    // configured state is truthful and honored. Import can never render
    // configured either (ONB-3.5: the importer is a separate SDD).
    (getReadiness as Mock).mockResolvedValue(
      makeReadiness({
        cards: {
          identity: "configured",
          assistant: "configured",
          telegram: "configured",
          backup: "configured",
          locale: "configured",
          world: "configured",
          offline: "configured",
          import: "configured",
        },
      }),
    );
    renderCenter();

    await screen.findByRole("heading", { name: "Centro de Configuración" });
    const configured = screen.getAllByText("Configurado");
    // Only capabilities with real evidence may render configured: assistant,
    // telegram (ONB-3.3 backend contract), locale, world, offline. Identity,
    // backup and import are forced back to pending by the UI's
    // anti-overstatement guard.
    expect(configured.length).toBe(5);
    expect(screen.getByRole("heading", { name: "Telegram" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Identidad" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Respaldo y restauración" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Importar mundo" })).toBeInTheDocument();
    expect(screen.getAllByText("Pendiente")).toHaveLength(3); // identity, backup, import
  });

  // ---------------------------------------------------------------------------
  // ONB-3.4 — Offline/dispositivo card: honest local-ready + remote-pending
  // breakdown; the local core never depends on the assistant (OC5/OC19).
  // ---------------------------------------------------------------------------

  it("offline card shows local-ready and remote-pending honestly", async () => {
    (getReadiness as Mock).mockResolvedValue(
      makeReadiness({
        offline: {
          local_ready: true,
          remote_pending: ["identity", "telegram", "backup", "assistant"],
        },
      }),
    );
    renderCenter();

    await screen.findByRole("heading", { name: "Centro de Configuración" });
    const offlineSection = screen.getByRole("heading", { name: "Offline / dispositivo" }).closest("section");
    // Local core ready without connection.
    expect(within(offlineSection as HTMLElement).getByText("Núcleo local")).toBeInTheDocument();
    expect(within(offlineSection as HTMLElement).getByText("Listo")).toBeInTheDocument();
    // Remote capabilities visibly pending (never claimed available offline).
    expect(within(offlineSection as HTMLElement).getByText("Remoto")).toBeInTheDocument();
    expect(within(offlineSection as HTMLElement).getByText(/requieren conexión/i)).toBeInTheDocument();
    expect(within(offlineSection as HTMLElement).getByText(/Telegram/i)).toBeInTheDocument();
    expect(within(offlineSection as HTMLElement).getByText(/Respaldo/i)).toBeInTheDocument();
  });

  it("offline card reports the local core unavailable when the probe fails", async () => {
    (getReadiness as Mock).mockResolvedValue(
      makeReadiness({
        local_editor: { probe: "local_editor", ok: false, detail: "read-only" },
        cards: {
          identity: "pending",
          assistant: "pending",
          telegram: "pending",
          backup: "pending",
          locale: "configured",
          world: "configured",
          offline: "error",
          import: "pending",
        },
        offline: { local_ready: false, remote_pending: ["identity", "telegram", "backup", "assistant"] },
      }),
    );
    renderCenter();

    await screen.findByRole("heading", { name: "Centro de Configuración" });
    const offlineSection = screen.getByRole("heading", { name: "Offline / dispositivo" }).closest("section");
    expect(within(offlineSection as HTMLElement).getByText("Núcleo local")).toBeInTheDocument();
    expect(within(offlineSection as HTMLElement).getByText("No disponible")).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // ONB-3.5 — Import handoff card: entry/pending/error only, never claims an
  // import happened (the importer is a separate SDD).
  // ---------------------------------------------------------------------------

  it("import handoff card exposes the entry point and stays pending", async () => {
    const user = userEvent.setup();
    (getReadiness as Mock).mockResolvedValue(makeReadiness());
    renderCenter();

    await screen.findByRole("heading", { name: "Importar mundo" });
    expect(screen.getByText(/contrato del importador/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Importar mundo" }).closest("section"))
      .toHaveTextContent("Pendiente");
    // The card links to the Taller de Mundo where the importer will live.
    await user.click(screen.getByRole("button", { name: "Ir al Taller de Mundo" }));
    expect(screen.getByTestId("taller-mundo")).toBeInTheDocument();
  });

  it("import handoff card never renders configured", async () => {
    (getReadiness as Mock).mockResolvedValue(
      makeReadiness({
        cards: {
          identity: "pending",
          assistant: "pending",
          telegram: "pending",
          backup: "pending",
          locale: "configured",
          world: "configured",
          offline: "configured",
          import: "configured", // stale/buggy claim — must be downgraded
        },
      }),
    );
    renderCenter();

    await screen.findByRole("heading", { name: "Importar mundo" });
    const importSection = screen.getByRole("heading", { name: "Importar mundo" }).closest("section");
    expect(importSection).toHaveTextContent("Pendiente");
    expect(importSection).not.toHaveTextContent("Configurado");
    // No fake completion vocabulary anywhere on the card.
    expect(importSection).not.toHaveTextContent(/completada|con éxito|importad[oa]s?\s+con/i);
  });

  // ---------------------------------------------------------------------------
  // ONB-3.6 — Assistant badge (OC19): pending/no-apto without a multimodal
  // model; the local core keeps working regardless.
  // ---------------------------------------------------------------------------

  it("assistant badge shows pendiente/no apto without a multimodal model", async () => {
    (getReadiness as Mock).mockResolvedValue(makeReadiness()); // assistant: pending
    renderCenter();

    await screen.findByRole("heading", { name: "Centro de Configuración" });
    const assistantSection = screen.getByRole("heading", { name: "IA texto y visión" }).closest("section");
    expect(assistantSection).toHaveTextContent("Pendiente / no apto");
    expect(assistantSection).not.toHaveTextContent("Configurado");
    // The local core stays ready: essential World + editor badges are Listo.
    const essential = screen.getByRole("heading", { name: "Listo para trabajar" });
    expect(within(essential.closest("section") as HTMLElement).getAllByText("Listo")).toHaveLength(2);
  });

  it("assistant badge shows configured only with the three proofs", async () => {
    (getReadiness as Mock).mockResolvedValue(
      makeReadiness({
        cards: {
          identity: "pending",
          assistant: "configured", // backend-proven three-proof acceptance
          telegram: "pending",
          backup: "pending",
          locale: "configured",
          world: "configured",
          offline: "configured",
          import: "pending",
        },
      }),
    );
    renderCenter();

    await screen.findByRole("heading", { name: "Centro de Configuración" });
    const assistantSection = screen.getByRole("heading", { name: "IA texto y visión" }).closest("section");
    expect(assistantSection).toHaveTextContent("Configurado");
    expect(assistantSection).not.toHaveTextContent("Pendiente / no apto");
  });

  // ---------------------------------------------------------------------------
  // ONB-4.2 + ONB-4.3 (WU-4c2) — Mundos card: read-only legacy detection notice
  // plus an EXPLICIT migration approval panel. Detection stays read-only; the
  // migration runs only through the panel's confirm dialog and never
  // automatically. After a completed migration the Center refreshes readiness,
  // so the notice disappears once the tree is canonical.
  // ---------------------------------------------------------------------------

  it("Mundos card shows the legacy notice and offers an explicit migration panel", async () => {
    (getReadiness as Mock).mockResolvedValue(
      makeReadiness({
        legacy: [{ world: "legacy-x", folders: ["Lore", "Personajes"] }],
      }),
    );
    renderCenter();

    await screen.findByRole("heading", { name: "Mundos" });
    const worldSection = screen.getByRole("heading", { name: "Mundos" }).closest("section") as HTMLElement;
    expect(within(worldSection).getByText("Carpetas legacy detectadas")).toBeInTheDocument();
    expect(worldSection).toHaveTextContent("legacy-x");
    // The case-sensitive risk is explained and never auto-renamed.
    expect(worldSection).toHaveTextContent(/distinguen mayúsculas y minúsculas/i);
    expect(worldSection).toHaveTextContent(/nunca se renombran de forma automática/i);
    // WU-4c2: the card now offers an explicit migration panel (hidden by
    // default); migration NEVER runs without the panel + confirm flow.
    const toggle = within(worldSection).getByRole("button", { name: "Migrar carpetas legacy" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(executeMigration).not.toHaveBeenCalled();
  });

  it("Mundos card renders no legacy notice when none is detected", async () => {
    (getReadiness as Mock).mockResolvedValue(makeReadiness()); // legacy: []
    renderCenter();

    await screen.findByRole("heading", { name: "Mundos" });
    const worldSection = screen.getByRole("heading", { name: "Mundos" }).closest("section") as HTMLElement;
    expect(worldSection).not.toHaveTextContent("Carpetas legacy detectadas");
    expect(worldSection).not.toHaveTextContent(/legacy/i);
    // No migration control without detected legacy folders.
    expect(within(worldSection).queryByRole("button", { name: /migrar/i })).not.toBeInTheDocument();
  });

  it("approved migration refreshes readiness and clears the legacy notice", async () => {
    const user = userEvent.setup();
    (getReadiness as Mock)
      .mockResolvedValueOnce(
        makeReadiness({
          legacy: [{ world: "legacy-x", folders: ["Lore", "Personajes"] }],
        }),
      )
      .mockResolvedValueOnce(makeReadiness()); // canonical tree after migration
    (executeMigration as Mock).mockResolvedValue({
      status: "completed",
      transaction_id: "mig-20260818-xyz789",
      world: "legacy-x",
      restore_verified: true,
      started_at: "2026-08-18T12:00:00Z",
      finished_at: "2026-08-18T12:00:01Z",
      error: null,
      steps: [],
    });
    renderCenter();

    await screen.findByRole("heading", { name: "Mundos" });
    await user.click(screen.getByRole("button", { name: "Migrar carpetas legacy" }));

    // The panel exposes the finding; still nothing has been executed.
    expect(screen.getByRole("button", { name: "Migrar carpetas de legacy-x" })).toBeInTheDocument();
    expect(executeMigration).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Migrar carpetas de legacy-x" }));

    // Explicit confirmation is required before the API call.
    expect(executeMigration).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Migrar" }));
    expect(executeMigration).toHaveBeenCalledWith("legacy-x", ["Lore", "Personajes"]);

    // Readiness refresh: the notice disappears once the tree is canonical.
    await waitFor(() =>
      expect(screen.queryByText("Carpetas legacy detectadas")).not.toBeInTheDocument(),
    );
    expect((getReadiness as Mock).mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  // ---------------------------------------------------------------------------
  // ONB-4.4 + ONB-4.5 (WU-4d) — Google identity and backup/restore cards:
  // entry points only. No fake OAuth, no fake backup, never configured.
  // ---------------------------------------------------------------------------

  it("identity card is an honest pending entry point and never renders configured", async () => {
    // A stale/buggy backend claims identity is configured. The card must
    // stay pending: OAuth/OIDC is not implemented in this change (ONB-4.4).
    (getReadiness as Mock).mockResolvedValue(
      makeReadiness({
        cards: {
          identity: "configured",
          assistant: "pending",
          telegram: "pending",
          backup: "pending",
          locale: "configured",
          world: "configured",
          offline: "configured",
          import: "pending",
        },
      }),
    );
    renderCenter();

    await screen.findByRole("heading", { name: "Identidad" });
    const identitySection = screen
      .getByRole("heading", { name: "Identidad" })
      .closest("section") as HTMLElement;
    expect(identitySection).toHaveTextContent("Pendiente");
    expect(identitySection).not.toHaveTextContent("Configurado");
    // Entry-only copy: revalidation / authorized recovery, stable sub id,
    // and no vocabulary claiming an active Google session.
    expect(identitySection).toHaveTextContent(/revalidación online|recuperación autorizada/i);
    expect(identitySection).toHaveTextContent(/identificador estable/i);
    expect(identitySection).toHaveTextContent("sub");
    expect(identitySection).not.toHaveTextContent(/inicia[dr] sesión con google|conectad[oa] con google/i);
  });

  it("identity card keeps the authorized-recovery entry to Perfil", async () => {
    const user = userEvent.setup();
    (getReadiness as Mock).mockResolvedValue(makeReadiness());
    renderCenter();

    await screen.findByRole("heading", { name: "Identidad" });
    await user.click(screen.getByRole("button", { name: "Ir a Perfil" }));
    expect(screen.getByTestId("perfil")).toBeInTheDocument();
  });

  it("backup/restore card is an honest pending entry point and never renders configured", async () => {
    (getReadiness as Mock).mockResolvedValue(
      makeReadiness({
        cards: {
          identity: "pending",
          assistant: "pending",
          telegram: "pending",
          backup: "configured", // stale/buggy claim — must be downgraded
          locale: "configured",
          world: "configured",
          offline: "configured",
          import: "pending",
        },
      }),
    );
    renderCenter();

    await screen.findByRole("heading", { name: "Respaldo y restauración" });
    const backupSection = screen
      .getByRole("heading", { name: "Respaldo y restauración" })
      .closest("section") as HTMLElement;
    expect(backupSection).toHaveTextContent("Pendiente");
    expect(backupSection).not.toHaveTextContent("Configurado");
    // Entry-only copy: not implemented yet, consent separation (identity ≠
    // Drive), backup and restore are distinct flows, no fake completion.
    expect(backupSection).toHaveTextContent(/no están implementados/i);
    expect(backupSection).toHaveTextContent(/consentimiento de Drive es independiente/i);
    expect(backupSection).toHaveTextContent(/flujos distintos/i);
    expect(backupSection).not.toHaveTextContent(/respaldo completado|restauración completada|con éxito/i);
    // No misleading "resume from this card" affordance without a dedicated
    // panel yet.
    expect(backupSection).not.toHaveTextContent("Se retoma desde esta tarjeta");
  });
});