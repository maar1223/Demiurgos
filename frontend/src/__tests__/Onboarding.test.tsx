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

vi.mock("@/api/config", () => ({
  getAppConfig: vi.fn(),
  getLocale: vi.fn(),
}));

vi.mock("@/api/wiki", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/wiki")>();
  return {
    ...original,
    listWorlds: vi.fn(),
    getAuthStatus: vi.fn(),
    createAccount: vi.fn(),
  };
});

import {
  createWorld,
  getOnboardingStatus,
  submitStep0,
} from "@/api/onboarding";
import { createAccount, getAuthStatus, listWorlds } from "@/api/wiki";
import { getLocale } from "@/api/config";
import type { Mock } from "vitest";

const CREDENTIALS_AUTH = {
  mode: "credentials",
  enabled: true,
  authenticated: false,
  label: null,
  provider: "credentials",
};

const FRESH_STATUS = {
  completed: false,
  current_step: "step0",
  completed_steps: [],
  pending_steps: ["step0", "account", "ai", "telegram", "world", "backup_handoff", "ready"],
  remote_pending: ["ai", "telegram", "backup_handoff"],
  blocking_pending: ["step0"],
};

/** After step 0 the backend derives the BLOCKING account step (R-AC-01). */
const STEP0_DONE_STATUS = {
  ...FRESH_STATUS,
  current_step: "account",
  completed_steps: ["step0"],
  pending_steps: ["account", "ai", "telegram", "world", "backup_handoff", "ready"],
  blocking_pending: ["account"],
};

/** After the account step the flow resumes at the world step. */
const ACCOUNT_DONE_STATUS = {
  ...FRESH_STATUS,
  current_step: "world",
  completed_steps: ["step0", "account"],
  pending_steps: ["ai", "telegram", "world", "backup_handoff", "ready"],
  blocking_pending: ["world"],
};

/** The real end state: nothing blocking is pending any more. */
const COMPLETED_STATUS = {
  completed: true,
  current_step: "ready",
  completed_steps: ["step0", "account", "world", "ready"],
  pending_steps: ["ai", "telegram", "backup_handoff"],
  remote_pending: ["ai", "telegram", "backup_handoff"],
  blocking_pending: [],
};

/** The safe locale the reconfigure read falls back to when nothing is stored. */
const DEFAULT_LOCALE = {
  ui: "es",
  conversation: "es",
  content: "es",
  region: null,
  region_explicit: false,
  iana_timezone: "UTC",
};

function renderOnboarding(initialEntry = "/onboarding") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/wiki" element={<div data-testid="wiki-home">wiki</div>} />
        <Route path="/perfil" element={<div data-testid="perfil">perfil</div>} />
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

describe("Onboarding page (ONB-1.1/ONB-1.4 + account step R-AC-01)", () => {
  beforeEach(() => {
    (getOnboardingStatus as Mock).mockReset();
    (submitStep0 as Mock).mockReset();
    (createWorld as Mock).mockReset();
    (getAuthStatus as Mock).mockReset();
    (createAccount as Mock).mockReset();
    (getLocale as Mock).mockReset();
    (getAuthStatus as Mock).mockResolvedValue(CREDENTIALS_AUTH);
    (getLocale as Mock).mockResolvedValue(DEFAULT_LOCALE);
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
    // After step 0, the BLOCKING account step is offered (not step 0 again).
    expect(await screen.findByRole("heading", { name: "Creá tu cuenta" })).toBeInTheDocument();
  });

  it("creates the account and shows the recovery words exactly once", async () => {
    (getOnboardingStatus as Mock)
      .mockResolvedValueOnce(STEP0_DONE_STATUS)
      .mockResolvedValue(ACCOUNT_DONE_STATUS);
    (createAccount as Mock).mockResolvedValue({
      username: "el-autor",
      words: "alpha beta gamma delta",
    });
    const user = userEvent.setup();
    renderOnboarding();

    await screen.findByRole("heading", { name: "Creá tu cuenta" });
    await user.type(screen.getByLabelText("Usuario"), "el-autor");
    await user.type(screen.getByLabelText("Contraseña (opcional)"), "clave-fuerte");
    await user.click(screen.getByRole("button", { name: "Crear cuenta" }));

    await waitFor(() =>
      expect(createAccount).toHaveBeenCalledWith("el-autor", "clave-fuerte"),
    );

    // The words are shown once (S-AC-01a) with the loss warning (R-NF-03).
    expect(await screen.findByTestId("onboarding-words")).toHaveTextContent(
      "alpha beta gamma delta",
    );

    await user.click(screen.getByRole("button", { name: "Guardé mis palabras" }));

    // Words never shown again; the world step is offered next.
    expect(screen.queryByTestId("onboarding-words")).not.toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Creá tu mundo" }),
    ).toBeInTheDocument();
  });

  it("creates a passwordless account (empty password → undefined)", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(STEP0_DONE_STATUS);
    (createAccount as Mock).mockResolvedValue({
      username: "el-autor",
      words: "alpha beta gamma delta",
    });
    const user = userEvent.setup();
    renderOnboarding();

    await screen.findByRole("heading", { name: "Creá tu cuenta" });
    await user.type(screen.getByLabelText("Usuario"), "el-autor");
    await user.click(screen.getByRole("button", { name: "Crear cuenta" }));

    await waitFor(() =>
      expect(createAccount).toHaveBeenCalledWith("el-autor", undefined),
    );
  });

  it("shows the account step even outside credentials mode (no authMode guard)", async () => {
    // vault-settings-configure: the account step is ALWAYS active on a fresh
    // install (R-AC-01) — the old `authMode === "credentials"` guard is gone,
    // so local-dev/disabled onboarding offers the account step too (S-AC-01b).
    (getAuthStatus as Mock).mockResolvedValue({
      mode: "local-dev",
      enabled: true,
      authenticated: true,
      label: "Local development user",
      provider: "local-dev",
    });
    (getOnboardingStatus as Mock).mockResolvedValue(STEP0_DONE_STATUS);
    renderOnboarding();

    expect(
      await screen.findByRole("heading", { name: "Creá tu cuenta" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Creá tu mundo" }),
    ).not.toBeInTheDocument();
  });

  it("resumes at the account step after a restart: step 0 is never replayed", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(STEP0_DONE_STATUS);
    renderOnboarding();

    expect(
      await screen.findByRole("heading", { name: "Creá tu cuenta" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /Paso 1: idioma/ }),
    ).not.toBeInTheDocument();
  });

  it("creates a world and completes onboarding", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(ACCOUNT_DONE_STATUS);
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
      await screen.findByText(/La sesión expiró/i),
    ).toBeInTheDocument();
  });

  it("keeps remote capabilities visibly pending offline", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(ACCOUNT_DONE_STATUS);
    renderOnboarding();

    await screen.findByRole("heading", { name: "Creá tu mundo" });
    expect(screen.getByText("Asistente de IA (texto y visión)")).toBeInTheDocument();
    expect(screen.getByText("Requiere conexión y una cuenta configurada. Se retoma desde el Centro de Configuración.")).toBeInTheDocument();
  });

  it("lands on the Profile (not a standalone page) after reconfiguring locale", async () => {
    // Reconfigure (`?step=step0`) re-opens ONLY the locale step; after saving
    // the user must land on `/perfil`, where the Centro de Configuración tab
    // lives (nav-restructure decision — the `/centro-configuracion` route is gone).
    (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
    (submitStep0 as Mock).mockResolvedValue(STEP0_DONE_STATUS);
    const user = userEvent.setup();
    renderOnboarding("/onboarding?step=step0");

    await screen.findByRole("heading", { name: /idioma, región y zona horaria/i });
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByTestId("perfil")).toBeInTheDocument();
  });

  it("reconfigure (?step=step0) shows the SAVED locale and sends it back on save", async () => {
    // Regression: the form used to render the fresh-install defaults, so the
    // stored region showed blank and submitting overwrote it with null.
    (getOnboardingStatus as Mock).mockResolvedValue(COMPLETED_STATUS);
    (getLocale as Mock).mockResolvedValue({
      ui: "es",
      conversation: "es",
      content: "es",
      region: "VE",
      region_explicit: false,
      iana_timezone: "America/Caracas",
    });
    (submitStep0 as Mock).mockResolvedValue(COMPLETED_STATUS);
    const user = userEvent.setup();
    renderOnboarding("/onboarding?step=step0");

    await screen.findByRole("heading", { name: /idioma, región y zona horaria/i });
    await waitFor(() =>
      expect(screen.getByLabelText(/Región \(opcional/)).toHaveValue("VE"),
    );
    expect(screen.getByLabelText(/Zona horaria/)).toHaveValue("America/Caracas");
    // The first-run pending cards belong to onboarding, not to reconfiguration.
    expect(screen.queryByText("Asistente de IA (texto y visión)")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() =>
      expect(submitStep0).toHaveBeenCalledWith(
        expect.objectContaining({ region: "VE", iana_timezone: "America/Caracas" }),
      ),
    );
  });
});