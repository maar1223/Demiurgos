import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderHook } from "@testing-library/react";
import Onboarding from "@/pages/Onboarding";
import { useOnboardingGate } from "@/hooks/useOnboardingGate";
import { ApiError } from "@/api/types";
import { tEs } from "@/__tests__/i18nTestUtils";

vi.mock("@/api/onboarding", () => ({
  getOnboardingStatus: vi.fn(),
  submitStep0: vi.fn(),
  createWorld: vi.fn(),
  getReadiness: vi.fn(),
}));

// The shared LocaleForm prefills step 0 from the saved locale; resolve it
// locally so the suite stays hermetic and fast.
vi.mock("@/api/config", () => ({
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
import { getLocale } from "@/api/config";
import { createAccount, getAuthStatus, listWorlds } from "@/api/wiki";
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
    (getLocale as Mock).mockResolvedValue({
      ui: "es",
      conversation: "es",
      content: "es",
      region: null,
      region_explicit: false,
      iana_timezone: "UTC",
    });
    (getAuthStatus as Mock).mockResolvedValue(CREDENTIALS_AUTH);
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
    expect(screen.getByText("Asistente de Demiurgos (texto y visión)")).toBeInTheDocument();
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
    await user.selectOptions(
      screen.getByLabelText(/Zona horaria/),
      "Europe/Madrid",
    );
    await user.click(screen.getByRole("button", { name: "Continuar" }));

    await waitFor(() =>
      expect(submitStep0).toHaveBeenCalledWith({
        ui: "en",
        conversation: "en",
        content: "en",
        conversation_explicit: false,
        content_explicit: false,
        region: "AR",
        region_explicit: true,
        iana_timezone: "Europe/Madrid",
      }),
    );
    // After step 0, the BLOCKING account step is offered (not step 0 again).
    expect(await screen.findByRole("heading", { name: tEs("onboarding.account.title") })).toBeInTheDocument();
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

    await screen.findByRole("heading", { name: tEs("onboarding.account.title") });
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
      await screen.findByRole("heading", { name: tEs("onboarding.world.title") }),
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

    await screen.findByRole("heading", { name: tEs("onboarding.account.title") });
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
      await screen.findByRole("heading", { name: tEs("onboarding.account.title") }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: tEs("onboarding.world.title") }),
    ).not.toBeInTheDocument();
  });

  it("resumes at the account step after a restart: step 0 is never replayed", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(STEP0_DONE_STATUS);
    renderOnboarding();

    expect(
      await screen.findByRole("heading", { name: tEs("onboarding.account.title") }),
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

    await screen.findByRole("heading", { name: tEs("onboarding.world.title") });
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

    await screen.findByRole("heading", { name: tEs("onboarding.world.title") });
    expect(screen.getByText("Asistente de Demiurgos (texto y visión)")).toBeInTheDocument();
  });

  it("prefills step 0 from the saved locale via the shared LocaleForm (REQ-PIA-12)", async () => {
    // The extracted locale form loads GET /api/locale on mount, so the
    // onboarding step reflects the persisted values instead of hardcoded
    // defaults (the reconfigure path this replaces is retired).
    (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
    (getLocale as Mock).mockResolvedValue({
      ui: "en",
      conversation: "en",
      content: "es",
      region: "MX",
      region_explicit: true,
      iana_timezone: "America/Mexico_City",
    });
    renderOnboarding();

    await screen.findByRole("heading", { name: /idioma, región y zona horaria/i });
    expect(screen.getByLabelText("Idioma de la interfaz")).toHaveValue("en");
    // AD-7: without explicit domain flags the conversation/content selects
    // prefill as "inherit" (""), resolving to the ui value on save.
    expect(screen.getByLabelText("Idioma de conversación (asistente)")).toHaveValue("");
    expect(screen.getByLabelText("Idioma de contenido (prosa del mundo)")).toHaveValue("");
    expect(screen.getByLabelText(/Región \(opcional/)).toHaveValue("MX");
    expect(screen.getByLabelText(/Confirmo la región/)).toBeChecked();
    // The timezone control is a dropdown and the stored zone is the selected
    // option (labelled with its main city), not a raw free-text value.
    const tzSelect = screen.getByLabelText(/Zona horaria/);
    expect(tzSelect).toHaveRole("combobox");
    expect(tzSelect).toHaveValue("America/Mexico_City");
    expect(
      (
        screen.getByRole("option", {
          name: "America/Mexico_City - Mexico City",
        }) as HTMLOptionElement
      ).selected,
    ).toBe(true);
  });

  it("renders the timezone field as a grouped select, not a free-text input", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
    renderOnboarding();

    await screen.findByRole("heading", { name: /idioma, región y zona horaria/i });
    const tzSelect = screen.getByLabelText(/Zona horaria/);

    // Under the old free-text implementation this control was an <input>
    // (role "textbox", tagName "INPUT"), so both assertions fail there.
    expect(tzSelect).toHaveRole("combobox");
    expect(tzSelect.tagName).toBe("SELECT");
    expect(tzSelect).not.toHaveAttribute("list");
  });

  it("labels every timezone option with its IANA zone and main city", async () => {
    (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
    renderOnboarding();

    await screen.findByRole("heading", { name: /idioma, región y zona horaria/i });
    const tzSelect = screen.getByLabelText(/Zona horaria/);

    // City is derived from the last path segment (underscores → spaces).
    const mexicoCity = within(tzSelect).getByRole("option", {
      name: "America/Mexico_City - Mexico City",
    });
    expect(mexicoCity).toHaveValue("America/Mexico_City");
    expect(within(tzSelect).getByRole("option", { name: "Europe/Madrid - Madrid" })).toBeInTheDocument();

    // ~400 zones are unusable flat: they are grouped by first IANA segment.
    expect(within(tzSelect).getByRole("group", { name: "Europe" })).toBeInTheDocument();
    expect(within(tzSelect).getByRole("group", { name: "America" })).toBeInTheDocument();
  });

  it("keeps a stored IANA alias the engine canonicalizes away as an option", async () => {
    // ICU canonicalizes `America/Argentina/Buenos_Aires` to
    // `America/Buenos_Aires`, so the stored alias is absent from the derived
    // list and must be injected to stay selectable and selected.
    (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
    (getLocale as Mock).mockResolvedValue({
      ui: "es",
      conversation: "es",
      content: "es",
      region: null,
      region_explicit: false,
      iana_timezone: "America/Argentina/Buenos_Aires",
    });
    renderOnboarding();

    await screen.findByRole("heading", { name: /idioma, región y zona horaria/i });
    const tzSelect = screen.getByLabelText(/Zona horaria/);
    const alias = within(tzSelect).getByRole("option", {
      name: "America/Argentina/Buenos_Aires - Buenos Aires",
    });
    expect(alias).toHaveValue("America/Argentina/Buenos_Aires");
    expect(tzSelect).toHaveValue("America/Argentina/Buenos_Aires");
    expect((alias as HTMLOptionElement).selected).toBe(true);
  });

  it("preserves a stored zone the runtime does not list (UTC) as a selected option", async () => {
    // `Intl.supportedValuesOf("timeZone")` enumerates the IANA set but omits
    // UTC, so the control must inject the stored value instead of dropping it.
    (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
    (getLocale as Mock).mockResolvedValue({
      ui: "es",
      conversation: "es",
      content: "es",
      region: null,
      region_explicit: false,
      iana_timezone: "UTC",
    });
    renderOnboarding();

    await screen.findByRole("heading", { name: /idioma, región y zona horaria/i });
    const tzSelect = screen.getByLabelText(/Zona horaria/);
    const utc = within(tzSelect).getByRole("option", { name: "UTC" });
    expect(utc).toHaveValue("UTC");
    expect(tzSelect).toHaveValue("UTC");
    expect((utc as HTMLOptionElement).selected).toBe(true);
  });

  it("falls back to a curated list when Intl.supportedValuesOf is unavailable", async () => {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
    const original = intl.supportedValuesOf;
    intl.supportedValuesOf = undefined;
    try {
      (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
      renderOnboarding();

      await screen.findByRole("heading", { name: /idioma, región y zona horaria/i });
      const tzSelect = screen.getByLabelText(/Zona horaria/);
      expect(tzSelect).toHaveRole("combobox");
      expect(
        within(tzSelect).getByRole("option", { name: "Europe/Madrid - Madrid" }),
      ).toBeInTheDocument();
      expect(within(tzSelect).getByRole("option", { name: "UTC" })).toBeInTheDocument();
    } finally {
      intl.supportedValuesOf = original;
    }
  });

  it("derives the options at runtime and injects the stored value on top", async () => {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
    const original = intl.supportedValuesOf;
    intl.supportedValuesOf = () => ["Europe/Madrid", "America/New_York", "Asia/Tokyo"];
    try {
      (getOnboardingStatus as Mock).mockResolvedValue(FRESH_STATUS);
      renderOnboarding();

      await screen.findByRole("heading", { name: /idioma, región y zona horaria/i });
      const tzSelect = screen.getByLabelText(/Zona horaria/);
      // The three mocked zones plus the stored "UTC" the engine did not list.
      expect(within(tzSelect).getAllByRole("option")).toHaveLength(4);
      expect(within(tzSelect).getByRole("group", { name: "Asia" })).toBeInTheDocument();
      expect(
        (within(tzSelect).getByRole("option", { name: "UTC" }) as HTMLOptionElement).selected,
      ).toBe(true);
    } finally {
      intl.supportedValuesOf = original;
    }
  });
});
