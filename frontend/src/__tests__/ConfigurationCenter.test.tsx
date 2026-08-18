import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ConfigurationCenter from "@/pages/ConfigurationCenter";

vi.mock("@/api/onboarding", () => ({
  getReadiness: vi.fn(),
  getOnboardingStatus: vi.fn(),
  submitStep0: vi.fn(),
  createWorld: vi.fn(),
}));

import { getReadiness } from "@/api/onboarding";
import type { Mock } from "vitest";

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
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {
        identity: "pending",
        assistant: "pending",
        telegram: "pending",
        backup: "pending",
        locale: "configured",
        world: "configured",
        offline: "configured",
      },
    });
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
    ]) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }

    // Local core states read as configured; cloud capabilities stay pending.
    expect(screen.getAllByText("Configurado")).toHaveLength(3);
    expect(screen.getAllByText("Pendiente")).toHaveLength(4);
  });

  it("shows the local editor essential badge truthfully", async () => {
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: false, detail: "read-back mismatch" },
      cards: {
        identity: "pending",
        assistant: "pending",
        telegram: "pending",
        backup: "pending",
        locale: "pending",
        world: "pending",
        offline: "error",
      },
    });
    renderCenter();

    await screen.findByRole("heading", { name: "Centro de Configuración" });
    expect(screen.getAllByText("Error")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Offline / dispositivo" })).toBeInTheDocument();
  });

  it("resumes a section in isolation from its card action", async () => {
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {
        identity: "pending",
        assistant: "pending",
        telegram: "pending",
        backup: "pending",
        locale: "configured",
        world: "configured",
        offline: "configured",
      },
    });
    const user = userEvent.setup();
    renderCenter();

    await screen.findByRole("heading", { name: "Centro de Configuración" });
    await user.click(screen.getAllByRole("button", { name: "Configurar" })[0]);
    expect(screen.getByTestId("perfil")).toBeInTheDocument();
  });

  it("announces card states to assistive tech (aria-live, non-color status)", async () => {
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {
        identity: "pending",
        assistant: "pending",
        telegram: "pending",
        backup: "pending",
        locale: "configured",
        world: "configured",
        offline: "configured",
      },
    });
    const { container } = renderCenter();

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Centro de Configuración" })).toBeInTheDocument(),
    );
    // Every card is a labelled section with a visible text status, and the
    // state grid is a polite live region (color is never the only signal).
    const sections = container.querySelectorAll("section[aria-labelledby]");
    expect(sections.length).toBe(7);
    expect(container.querySelector('[aria-live="polite"]')).not.toBeNull();
    expect(screen.getAllByText(/Estado:/)).toHaveLength(7);
  });
});