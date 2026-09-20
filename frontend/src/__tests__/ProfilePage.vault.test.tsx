import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ProfilePage from "@/pages/ProfilePage";
import {
  changePassword,
  changeUsername,
  disableVault,
  enableVault,
  getAuthStatus,
  getVaultConfig,
  removePassword,
  rotateWords,
  setReauthInterval,
} from "@/api/wiki";
import { getReadiness } from "@/api/onboarding";
import type { Mock } from "vitest";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: () => ({ worlds: [] }),
}));

vi.mock("@/api/onboarding", () => ({
  getReadiness: vi.fn(),
}));

vi.mock("@/api/wiki", () => ({
  getAuthStatus: vi.fn(),
  changeUsername: vi.fn(),
  changePassword: vi.fn(),
  removePassword: vi.fn(),
  rotateWords: vi.fn(),
  getVaultConfig: vi.fn(),
  enableVault: vi.fn(),
  disableVault: vi.fn(),
  setReauthInterval: vi.fn(),
}));

// The status overview header (REQ-PIA-05) reads backup + assistant state on
// every ProfilePage render; resolve them locally so this flow stays hermetic.
vi.mock("@/api/backup", () => ({
  getBackupStatus: vi.fn().mockResolvedValue({
    state: "pending",
    destination: null,
    mode: null,
    blocked: false,
    warning: null,
    last_write: null,
    copy: null,
  }),
}));

vi.mock("@/api/assistantSettings", () => ({
  getAssistantSettings: vi.fn().mockResolvedValue({
    provider: "opencode-go",
    base_url: "",
    model: "",
    model_metadata: { id: "", label: "", capability: "unknown", pricing: null },
    key_configured: false,
    models: [],
    active_profile: "",
    revision: 0,
    runtime_state: "saved-not-active",
  }),
}));

vi.mock("@/hooks/useLocalDevAuth", () => ({
  useLocalDevAuth: () => ({
    status: {
      mode: "local-dev",
      enabled: false,
      authenticated: false,
      label: null,
    },
    isLoading: false,
    error: null,
    start: vi.fn(),
    logout: vi.fn(),
  }),
}));

vi.mock("@/hooks/useAuthSession", () => ({
  useAuthSession: () => ({
    status: {
      mode: "credentials",
      enabled: true,
      authenticated: true,
      label: "el-autor",
      provider: "credentials",
    },
    isLoading: false,
    error: null,
  }),
}));

vi.mock("@/components/organisms/Navbar", () => ({
  Navbar: () => <div aria-label="navbar" />,
}));

vi.mock("@/components/organisms/IdeaCapturePanel", () => ({
  IdeaCapturePanel: () => <div>idea capture</div>,
}));

vi.mock("@/components/organisms/AssistantSettingsPanel", () => ({
  AssistantSettingsPanel: () => <div>assistant settings panel</div>,
}));

vi.mock("@/components/organisms/MigrationPanel", () => ({
  MigrationPanel: () => <div>migration panel</div>,
}));

const credentialsStatus = {
  mode: "credentials",
  enabled: true,
  authenticated: true,
  label: "el-autor",
  provider: "credentials",
  last_auth_at: "2026-08-15T12:00:00+00:00",
  days_until_reauth: 4,
};

/** Vault ON — the merged cuenta surface renders the management disclosures. */
const vaultOnConfig = {
  enabled: true,
  account_exists: true,
  username: "el-autor",
  has_password: true,
  reauth_interval_d: 14,
  env_override: false,
};

const vaultOffExisting = {
  enabled: false,
  account_exists: true,
  username: "el-autor",
  has_password: true,
  reauth_interval_d: 14,
  env_override: false,
};

function renderProfile() {
  return render(
    <MemoryRouter>
      <ProfilePage />
    </MemoryRouter>,
  );
}

/** Open the collapsed "Gestionar credenciales" disclosure. */
async function openCredentials() {
  fireEvent.click(
    await screen.findByRole("button", { name: "Gestionar credenciales" }),
  );
}

/** Open the collapsed "Zona sensible" disclosure. */
async function openSensitive() {
  fireEvent.click(await screen.findByRole("button", { name: "Zona sensible" }));
}

/** Pick one of the four credentials panels in the segmented control. */
function selectPanel(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
}

/** The words form whose h4 is `title`, as its containing panel element. */
function wordsForm(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("div") as HTMLElement;
}

describe("ProfilePage account section (credentials mode)", () => {
  beforeEach(() => {
    (getAuthStatus as Mock).mockResolvedValue(credentialsStatus);
    (changeUsername as Mock).mockResolvedValue({ success: true });
    (changePassword as Mock).mockResolvedValue({ success: true });
    (removePassword as Mock).mockResolvedValue({ success: true });
    (rotateWords as Mock).mockResolvedValue({
      new_words: "alpha beta gamma delta",
    });
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {},
      offline: { local_ready: true, remote_pending: [] },
      legacy: [],
    });
    (getVaultConfig as Mock).mockResolvedValue(vaultOnConfig);
  });

  it("renders the status card with the account, words and reingreso rows", async () => {
    renderProfile();

    const panel = within(await screen.findByRole("tabpanel"));
    expect(
      panel.getByRole("heading", { name: "Sesión", level: 3 }),
    ).toBeInTheDocument();
    expect(panel.getByText("Activa")).toBeInTheDocument();

    // Three compact rows: account, session words lock and re-auth countdown.
    expect(panel.getByText("Cuenta", { selector: "dt" })).toBeInTheDocument();
    expect(panel.getByText("el-autor")).toBeInTheDocument();
    expect(panel.getByText("contraseña definida")).toBeInTheDocument();
    expect(
      panel.getByText("Palabras claves", { selector: "dt" }),
    ).toBeInTheDocument();
    expect(panel.getByText("Bloqueadas")).toBeInTheDocument();
    expect(panel.getByText("Reingreso", { selector: "dt" })).toBeInTheDocument();
    expect(panel.getByText("en 4 días")).toBeInTheDocument();
    // The duplicated status paragraphs and the old vault header are gone.
    expect(panel.queryByText("Proveedor: Credenciales")).not.toBeInTheDocument();
    expect(panel.queryByText("Sesión activa")).not.toBeInTheDocument();
  });

  it("collapses 'Gestionar credenciales' by default and expands on demand", async () => {
    // Fails under the old code: there was no disclosure trigger at all, so
    // `findByRole(..., { name: "Gestionar credenciales" })` threw.
    renderProfile();
    await screen.findByRole("heading", { name: "Sesión", level: 3 });

    const trigger = screen.getByRole("button", { name: "Gestionar credenciales" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveAttribute("aria-controls", "cuenta-credentials-region");
    expect(
      screen.queryByRole("heading", { name: "Cambiar usuario" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Usuario" }),
    ).not.toBeInTheDocument();

    fireEvent.click(trigger);

    expect(
      screen.getByRole("button", { name: "Gestionar credenciales" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("heading", { name: "Cambiar usuario" }),
    ).toBeInTheDocument();
  });

  it("shows one credentials form at a time through the segmented control", async () => {
    // Fails under the old code: no segmented control existed and the four
    // words forms rendered simultaneously.
    renderProfile();
    await openCredentials();

    // Default panel: Usuario.
    expect(
      screen.getByRole("heading", { name: "Cambiar usuario" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Cambiar contraseña" }),
    ).not.toBeInTheDocument();

    selectPanel("Contraseña");
    expect(
      screen.getByRole("heading", { name: "Cambiar contraseña" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Cambiar usuario" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Contraseña" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Usuario" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    selectPanel("Palabras claves");
    expect(
      screen.getByRole("heading", { name: "Rotar palabras claves" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Cambiar contraseña" }),
    ).not.toBeInTheDocument();

    selectPanel("Reingreso");
    expect(
      screen.getByRole("heading", { name: "Intervalo de reingreso" }),
    ).toBeInTheDocument();

    // The segmented control is a toggle-button group, not a second tablist
    // (REQ-PIA-04 keeps that role exclusive to the section rail).
    expect(screen.getAllByRole("tablist")).toHaveLength(1);
  });

  it("collapses the sensitive zone with the destructive forms", async () => {
    renderProfile();
    await screen.findByRole("heading", { name: "Sesión", level: 3 });

    const trigger = screen.getByRole("button", { name: "Zona sensible" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("heading", { name: "Retirar contraseña" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Desactivar bóveda" }),
    ).not.toBeInTheDocument();

    fireEvent.click(trigger);

    expect(
      screen.getByRole("heading", { name: "Retirar contraseña" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Desactivar bóveda" }),
    ).toBeInTheDocument();
  });

  it("does not duplicate the Navbar logout controls (REQ-PIA-09 deviation)", async () => {
    // The Navbar profile menu owns both "Cerrar sesión" (credentials) and
    // "Cerrar sesión local", so the section must not repeat them. Fails under
    // the old code, which rendered "Cerrar sesión" in the Sesión card.
    renderProfile();
    await screen.findByRole("heading", { name: "Sesión", level: 3 });

    expect(
      screen.queryByRole("button", { name: "Cerrar sesión" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cerrar sesión local" }),
    ).not.toBeInTheDocument();
  });

  it("shows the soft re-auth countdown with the warning copy (R-AC-04d)", async () => {
    renderProfile();

    // The status row carries the countdown…
    expect(await screen.findByText("en 4 días")).toBeInTheDocument();
    // …and the warning copy lives once, inside the Reingreso panel.
    await openCredentials();
    selectPanel("Reingreso");
    expect(
      screen.getByText(/Reingreso recomendado en 4 días\./),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /si no reingresas tu contraseña, la sesión de demiurgos se cerrará/i,
      ),
    ).toBeInTheDocument();
  });

  it("changes the username by proving ownership with the words", async () => {
    renderProfile();
    await openCredentials();

    const form = wordsForm("Cambiar usuario");
    fireEvent.change(
      within(form).getByLabelText("Palabras claves para Cambiar usuario"),
      { target: { value: "alpha beta gamma" } },
    );
    fireEvent.change(within(form).getByLabelText("Nuevo usuario"), {
      target: { value: "nuevo-nombre" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Cambiar usuario" }));

    await waitFor(() =>
      expect(changeUsername).toHaveBeenCalledWith("alpha beta gamma", "nuevo-nombre"),
    );
    expect(
      await within(form).findByText("Listo. Cambio guardado."),
    ).toBeInTheDocument();
  });

  it("changes the password by proving ownership with the words", async () => {
    renderProfile();
    await openCredentials();
    selectPanel("Contraseña");

    const form = wordsForm("Cambiar contraseña");
    fireEvent.change(
      within(form).getByLabelText("Palabras claves para Cambiar contraseña"),
      { target: { value: "alpha beta gamma" } },
    );
    fireEvent.change(within(form).getByLabelText("Nueva contraseña"), {
      target: { value: "clave-nueva" },
    });
    fireEvent.click(
      within(form).getByRole("button", { name: "Cambiar contraseña" }),
    );

    await waitFor(() =>
      expect(changePassword).toHaveBeenCalledWith("alpha beta gamma", "clave-nueva"),
    );
  });

  it("rotates the words and shows the new plaintext exactly once", async () => {
    renderProfile();
    await openCredentials();
    selectPanel("Palabras claves");

    fireEvent.click(
      screen.getByRole("button", { name: "Rotar palabras claves" }),
    );

    expect(
      await screen.findByText("alpha beta gamma delta"),
    ).toBeInTheDocument();
    expect(rotateWords).toHaveBeenCalledTimes(1);
  });

  it("adjusts the reauth interval (S-VC-05a)", async () => {
    renderProfile();
    await openCredentials();
    selectPanel("Reingreso");

    const input = await screen.findByLabelText("Días entre reingresos");
    fireEvent.change(input, { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() => expect(setReauthInterval).toHaveBeenCalledWith(7));
    expect(
      await screen.findByText("Listo. Intervalo guardado."),
    ).toBeInTheDocument();
  });

  it("removes the password (back to passwordless) with a two-click confirm", async () => {
    renderProfile();
    await openSensitive();

    const form = wordsForm("Retirar contraseña");
    fireEvent.change(
      within(form).getByLabelText("Palabras claves para Retirar contraseña"),
      { target: { value: "alpha beta gamma" } },
    );
    fireEvent.click(
      within(form).getByRole("button", { name: "Retirar contraseña" }),
    );

    // First click only arms the confirmation; nothing was sent yet.
    expect(removePassword).not.toHaveBeenCalled();
    expect(
      within(form).getByRole("button", { name: "¿Confirmás el retiro?" }),
    ).toBeInTheDocument();

    fireEvent.click(
      within(form).getByRole("button", { name: "¿Confirmás el retiro?" }),
    );

    await waitFor(() =>
      expect(removePassword).toHaveBeenCalledWith("alpha beta gamma"),
    );
  });
});

describe("ProfilePage session words unlock (REQ-SRW-01..04)", () => {
  beforeEach(() => {
    (getAuthStatus as Mock).mockResolvedValue(credentialsStatus);
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {},
      offline: { local_ready: true, remote_pending: [] },
      legacy: [],
    });
    (getVaultConfig as Mock).mockResolvedValue(vaultOnConfig);
    (changeUsername as Mock).mockResolvedValue({ success: true });
    (changePassword as Mock).mockResolvedValue({ success: true });
    (removePassword as Mock).mockResolvedValue({ success: true });
    (rotateWords as Mock).mockResolvedValue({
      new_words: "alpha beta gamma delta",
    });
  });

  it("unlocks once with a successful words action and replays on later actions", async () => {
    renderProfile();

    // First words-gated action types the words; success arms the unlock.
    await openCredentials();
    const usernameForm = wordsForm("Cambiar usuario");
    fireEvent.change(
      within(usernameForm).getByLabelText("Palabras claves para Cambiar usuario"),
      { target: { value: "alpha beta gamma" } },
    );
    fireEvent.change(within(usernameForm).getByLabelText("Nuevo usuario"), {
      target: { value: "nuevo-nombre" },
    });
    fireEvent.click(
      within(usernameForm).getByRole("button", { name: "Cambiar usuario" }),
    );

    await waitFor(() =>
      expect(changeUsername).toHaveBeenCalledWith("alpha beta gamma", "nuevo-nombre"),
    );
    // The status row arms for the session.
    expect(
      await screen.findByText("Desbloqueadas esta sesión"),
    ).toBeInTheDocument();

    // The next words action no longer re-requests the words (REQ-SRW-01):
    // the input is hidden and the cached words replay on submit.
    selectPanel("Contraseña");
    const passwordForm = wordsForm("Cambiar contraseña");
    expect(
      within(passwordForm).queryByLabelText(
        "Palabras claves para Cambiar contraseña",
      ),
    ).not.toBeInTheDocument();
    fireEvent.change(within(passwordForm).getByLabelText("Nueva contraseña"), {
      target: { value: "clave-nueva" },
    });
    fireEvent.click(
      within(passwordForm).getByRole("button", { name: "Cambiar contraseña" }),
    );

    await waitFor(() =>
      expect(changePassword).toHaveBeenCalledWith("alpha beta gamma", "clave-nueva"),
    );
  });

  it("stays locked after an invalid words attempt", async () => {
    (changeUsername as Mock).mockRejectedValue(new Error("Palabras incorrectas"));
    renderProfile();

    await openCredentials();
    const form = wordsForm("Cambiar usuario");
    fireEvent.change(
      within(form).getByLabelText("Palabras claves para Cambiar usuario"),
      { target: { value: "wrong words" } },
    );
    fireEvent.change(within(form).getByLabelText("Nuevo usuario"), {
      target: { value: "nuevo-nombre" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Cambiar usuario" }));

    expect(await within(form).findByText("Palabras incorrectas")).toBeInTheDocument();
    // No session replay is armed: the row stays locked and the next panel
    // still asks for the words.
    expect(screen.getByText("Bloqueadas")).toBeInTheDocument();
    selectPanel("Contraseña");
    expect(
      await screen.findByLabelText("Palabras claves para Cambiar contraseña"),
    ).toBeInTheDocument();
  });

  it("never persists the unlocked words to web storage (REQ-SRW-02)", async () => {
    renderProfile();

    await openCredentials();
    const form = wordsForm("Cambiar usuario");
    fireEvent.change(
      within(form).getByLabelText("Palabras claves para Cambiar usuario"),
      { target: { value: "alpha beta gamma" } },
    );
    fireEvent.change(within(form).getByLabelText("Nuevo usuario"), {
      target: { value: "nuevo-nombre" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Cambiar usuario" }));
    await screen.findByText("Desbloqueadas esta sesión");

    // The words must be absent from every web-storage surface.
    for (const storage of [localStorage, sessionStorage]) {
      for (let i = 0; i < storage.length; i += 1) {
        const key = storage.key(i);
        if (key !== null) {
          expect(storage.getItem(key)).not.toContain("alpha beta gamma");
        }
      }
    }
    expect(document.cookie).not.toContain("alpha beta gamma");
  });

  it("clears the unlocked words when the surface unmounts (REQ-SRW-03)", async () => {
    const { unmount } = renderProfile();

    await openCredentials();
    const form = wordsForm("Cambiar usuario");
    fireEvent.change(
      within(form).getByLabelText("Palabras claves para Cambiar usuario"),
      { target: { value: "alpha beta gamma" } },
    );
    fireEvent.change(within(form).getByLabelText("Nuevo usuario"), {
      target: { value: "nuevo-nombre" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Cambiar usuario" }));
    await screen.findByText("Desbloqueadas esta sesión");

    // Unmount destroys the page-level session state; a fresh render starts
    // locked and re-requests the words.
    unmount();
    renderProfile();
    await openCredentials();
    expect(
      await screen.findByLabelText("Palabras claves para Cambiar usuario"),
    ).toBeInTheDocument();
    expect(screen.getByText("Bloqueadas")).toBeInTheDocument();
  });
});

describe("ProfilePage vault panel (Seguridad / Bóveda, R-VC-02..05)", () => {
  beforeEach(() => {
    (getAuthStatus as Mock).mockResolvedValue(credentialsStatus);
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {},
      offline: { local_ready: true, remote_pending: [] },
      legacy: [],
    });
    (getVaultConfig as Mock).mockResolvedValue({
      enabled: false,
      account_exists: false,
      username: null,
      has_password: false,
      reauth_interval_d: 14,
      env_override: false,
    });
    (enableVault as Mock).mockResolvedValue({ enabled: true });
    (disableVault as Mock).mockResolvedValue({ enabled: false });
    (setReauthInterval as Mock).mockResolvedValue({ reauth_interval_d: 7 });
  });

  it("renders the create-account activation form when vault OFF and no account", async () => {
    renderProfile();

    expect(
      await screen.findByRole("heading", { name: "Seguridad / Bóveda" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Apagada")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Crear cuenta y activar" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Usuario")).toBeInTheDocument();
    expect(screen.getByLabelText("Contraseña (opcional)")).toBeInTheDocument();
    // Management-only surfaces must not render while OFF.
    expect(
      screen.queryByRole("heading", { name: "Desactivar bóveda" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Gestionar credenciales" }),
    ).not.toBeInTheDocument();
  });

  it("creates the account on activation and shows the words exactly once (S-VC-03a)", async () => {
    (getVaultConfig as Mock)
      .mockResolvedValueOnce({
        enabled: false,
        account_exists: false,
        username: null,
        has_password: false,
        reauth_interval_d: 14,
        env_override: false,
      })
      .mockResolvedValue(vaultOnConfig);
    (enableVault as Mock).mockResolvedValue({
      enabled: true,
      words: "alpha beta gamma delta",
    });
    renderProfile();

    fireEvent.change(await screen.findByLabelText("Usuario"), {
      target: { value: "el-autor" },
    });
    fireEvent.change(screen.getByLabelText("Contraseña (opcional)"), {
      target: { value: "clave-fuerte" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Crear cuenta y activar" }),
    );

    await waitFor(() =>
      expect(enableVault).toHaveBeenCalledWith({
        username: "el-autor",
        password: "clave-fuerte",
      }),
    );
    // Words are shown exactly once; confirming reloads into the management UI.
    expect(
      await screen.findByTestId("vault-words"),
    ).toHaveTextContent("alpha beta gamma delta");
    // REQ-PIA-07: the activation state is an h3 directly under the panel h2 —
    // it must not skip to h4 with no containing h3.
    expect(
      screen.getByRole("heading", { name: "Bóveda activada", level: 3 }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Guardé mis palabras" }),
    );
    expect(
      await screen.findByRole("button", { name: "Gestionar credenciales" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("vault-words")).not.toBeInTheDocument();
  });

  it("activates an existing account by verifying the words (S-VC-03b/c)", async () => {
    (getVaultConfig as Mock).mockResolvedValue(vaultOffExisting);
    renderProfile();

    fireEvent.change(
      await screen.findByLabelText("Palabras claves para activar la bóveda"),
      { target: { value: "alpha beta gamma" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Activar bóveda" }),
    );

    await waitFor(() =>
      expect(enableVault).toHaveBeenCalledWith({
        words: "alpha beta gamma",
      }),
    );
  });

  it("renders one account/security surface with no duplicated controls (REQ-PIA-09)", async () => {
    (getVaultConfig as Mock).mockResolvedValue(vaultOnConfig);
    renderProfile();

    const panel = within(await screen.findByRole("tabpanel"));
    expect(await panel.findByText("Activa")).toBeInTheDocument();
    // Exactly one status card, one credentials disclosure, one sensitive zone.
    expect(
      panel.getAllByRole("heading", { name: "Sesión", level: 3 }),
    ).toHaveLength(1);
    expect(
      panel.getAllByRole("button", { name: "Gestionar credenciales" }),
    ).toHaveLength(1);
    expect(
      panel.getAllByRole("button", { name: "Zona sensible" }),
    ).toHaveLength(1);
    // No duplicated logout inside the section.
    expect(
      panel.queryByRole("button", { name: "Cerrar sesión" }),
    ).not.toBeInTheDocument();

    // Each management action renders exactly once, one panel at a time.
    await openCredentials();
    expect(
      panel.getAllByRole("heading", { name: "Cambiar usuario" }),
    ).toHaveLength(1);
    selectPanel("Contraseña");
    expect(
      panel.getAllByRole("heading", { name: "Cambiar contraseña" }),
    ).toHaveLength(1);
    expect(
      panel.queryByRole("heading", { name: "Cambiar usuario" }),
    ).not.toBeInTheDocument();
    selectPanel("Palabras claves");
    expect(
      panel.getAllByRole("heading", { name: "Rotar palabras claves" }),
    ).toHaveLength(1);
    selectPanel("Reingreso");
    expect(
      panel.getAllByRole("heading", { name: "Intervalo de reingreso" }),
    ).toHaveLength(1);

    // Activation-only surfaces must not render while ON.
    expect(
      panel.queryByRole("button", { name: "Activar bóveda" }),
    ).not.toBeInTheDocument();
    expect(
      panel.queryByRole("heading", { name: "Crear cuenta y activar" }),
    ).not.toBeInTheDocument();
  });

  it("disables the vault with the words after a two-click confirm (S-VC-04a/b)", async () => {
    (getVaultConfig as Mock)
      .mockResolvedValueOnce(vaultOnConfig)
      .mockResolvedValue(vaultOffExisting);
    renderProfile();
    await openSensitive();

    const form = wordsForm("Desactivar bóveda");
    fireEvent.change(
      within(form).getByLabelText("Palabras claves para Desactivar bóveda"),
      { target: { value: "alpha beta gamma" } },
    );
    fireEvent.click(
      within(form).getByRole("button", { name: "Desactivar bóveda" }),
    );

    // First click only arms the confirmation; nothing was sent yet.
    expect(disableVault).not.toHaveBeenCalled();
    fireEvent.click(
      within(form).getByRole("button", { name: "¿Confirmás la desactivación?" }),
    );

    await waitFor(() =>
      expect(disableVault).toHaveBeenCalledWith("alpha beta gamma"),
    );
    // After the reload the panel is back in activation mode (vault OFF).
    expect(
      await screen.findByRole("heading", { name: "Activar la bóveda" }),
    ).toBeInTheDocument();
  });
});
