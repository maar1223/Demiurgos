import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderHook } from "@testing-library/react";
import Onboarding from "@/pages/Onboarding";
import { useOnboardingGate } from "@/hooks/useOnboardingGate";
import { ApiError } from "@/api/types";

vi.mock("@/api/onboarding", () => ({
  getOnboardingStatus: vi.fn(),
  submitStep0: vi.fn(),
  createWorld: vi.fn(),
  getReadiness: vi.fn(),
}));

vi.mock("@/api/wiki", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/wiki")>();
  return { ...original, listWorlds: vi.fn() };
});

import {
  createWorld,
  getOnboardingStatus,
  submitStep0,
} from "@/api/onboarding";
import { listWorlds } from "@/api/wiki";
import type { Mock } from "vitest";

const FRESH_STATUS = {
  completed: false,
  current_step: "step0",
  completed_steps: [],
  pending_steps: ["step0", "ai", "telegram", "world", "backup_handoff", "ready"],
  remote_pending: ["ai", "telegram", "backup_handoff"],
  blocking_pending: ["step0"],
};

const STEP0_DONE_STATUS = {
  ...FRESH_STATUS,
  current_step: "world",
  completed_steps: ["step0"],
  pending_steps: ["ai", "telegram", "world", "backup_handoff", "ready"],
  blocking_pending: ["world"],
};

function renderOnboarding(initialEntry = "/onboarding") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/wiki" element={<div data-testid="wiki-home">wiki</div>} />
        <Route path="/centro-configuracion" element={<div data-testid="center">center</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("useOnboardingGate (ONB-1.1 first-run gate)", () => {
  beforeEach(() => {
    (getOnboardingStatus as Mock).mockReset();
    (listWorlds as Mock).mockReset();
  });

  it("forces onboarding on a fresh installation (no world, not completed)", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
    (listWorlds as Mock).mockResolvedValue([]);
    const { result } = renderHook(() => useOnboardingGate());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.needsOnboarding).toBe(true);
  });

  it("does NOT force onboarding when a world already exists", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
    (listWorlds as Mock).mockResolvedValue([{ name: "vibrantes" }]);
    const { result } = renderHook(() => useOnboardingGate());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.needsOnboarding).toBe(false);
  });

  it("does NOT force onboarding when already completed", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue({
      ...FRESH_STATUS, completed: true, current_step: "ready",
    });
    (listWorlds as Mock).mockResolvedValue([]);
    const { result } = renderHook(() => useOnboardingGate());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.needsOnboarding).toBe(false);
  });
});

describe("Onboarding page (ONB-1.1/ONB-1.4)", () => {
  beforeEach(() => {
    (getOnboardingStatus as Mock).mockReset();
    (submitStep0 as Mock).mockReset();
    (createWorld as Mock).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows step 0 (locale) and the remote pending cards on a fresh install", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
    renderOnboarding();

    expect(
      await screen.findByRole("heading", { name: /idioma, región y zona horaria/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Idioma de la interfaz")).toBeInTheDocument();
    expect(screen.getByLabelText("Idioma de conversación (asistente)")).toBeInTheDocument();
    expect(screen.getByLabelText("Idioma de contenido (prosa del mundo)")).toBeInTheDocument();
    expect(screen.getByText("Asistente de IA (texto y visión)")).toBeInTheDocument();
    expect(screen.getByText("Telegram")).toBeInTheDocument();
    expect(screen.getByText("Respaldo y restauración")).toBeInTheDocument();
  });

  it("submits three independent languages + region + IANA timezone", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
    (submitStep0 as Mock).mockResolvedValue(STEP0_DONE_STATUS);
    const user = userEvent.setup();
    renderOnboarding();

    await screen.findByRole("heading", { name: /idioma, región y zona horaria/i });
    await user.selectOptions(screen.getByLabelText("Idioma de la interfaz"), "en");
    await user.type(screen.getByLabelText(/Región \(opcional/), "AR");
    await user.click(screen.getByLabelText(/Confirmo la región/));
    const tzInput = screen.getByLabelText(/Zona horaria/);
    await user.clear(tzInput);
    await user.type(tzInput, "America/Argentina/Buenos_Aires");
    await user.click(screen.getByRole("button", { name: "Continuar" }));

    await waitFor(() =>
      expect(submitStep0).toHaveBeenCalledWith({
        ui: "en",
        conversation: "es",
        content: "es",
        region: "AR",
        region_explicit: true,
        iana_timezone: "America/Argentina/Buenos_Aires",
      }),
    );
    // After step 0, the world step is offered (not replayed step 0).
    expect(await screen.findByRole("heading", { name: "Creá tu mundo" })).toBeInTheDocument();
  });

  it("resumes at the world step after a restart: step 0 is never replayed", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(STEP0_DONE_STATUS);
    renderOnboarding();

    expect(await screen.findByRole("heading", { name: "Creá tu mundo" })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /Paso 1: idioma/ }),
    ).not.toBeInTheDocument();
  });

  it("creates a world and completes onboarding", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(STEP0_DONE_STATUS);
    (createWorld as Mock).mockResolvedValue({ kind: "created", name: "mi-mundo", path: "/x", message: "" });
    const user = userEvent.setup();
    renderOnboarding();

    await screen.findByRole("heading", { name: "Creá tu mundo" });
    await user.type(screen.getByLabelText("Nombre del mundo"), "mi-mundo");
    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    await waitFor(() => expect(createWorld).toHaveBeenCalledWith("mi-mundo", true));
    expect(await screen.findByTestId("wiki-home")).toBeInTheDocument();
  });

  it("surfaces a clear hint when a gated write is unauthenticated (fail closed)", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
    (submitStep0 as Mock).mockRejectedValue(new ApiError(401, "Authentication required."));
    const user = userEvent.setup();
    renderOnboarding();

    await screen.findByRole("heading", { name: /idioma, región y zona horaria/i });
    await user.click(screen.getByRole("button", { name: "Continuar" }));

    expect(
      await screen.findByText(/DEMIURGOS_AUTH_MODE=local-dev/i),
    ).toBeInTheDocument();
  });

  it("keeps remote capabilities visibly pending offline", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(STEP0_DONE_STATUS);
    renderOnboarding();

    await screen.findByRole("heading", { name: "Creá tu mundo" });
    expect(screen.getByText("Asistente de IA (texto y visión)")).toBeInTheDocument();
    expect(screen.getByText("Requiere conexión y una cuenta configurada. Se retoma desde el Centro de Configuración.")).toBeInTheDocument();
  });
});