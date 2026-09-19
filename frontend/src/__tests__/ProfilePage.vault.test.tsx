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
  logoutSession,
  removePassword,
  rotateWords,
  setReauthInterval,
} from "@/api/wiki";
import { getReadiness } from "@/api/onboarding";
import { reloadPage } from "@/lib/reloadPage";
import type { Mock } from "vitest";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: () => ({ worlds: [] }),
}));

vi.mock("@/api/onboarding", () => ({
  getReadiness: vi.fn(),
}));

vi.mock("@/api/wiki", () => ({
  getAuthStatus: vi.fn(),
  logoutSession: vi.fn(),
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

// The page-level status header (REQ-PIA-05) reads backup and assistant state
// on every render; resolve both locally so these flows stay hermetic.
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

vi.mock("@/lib/reloadPage", () => ({
  reloadPage: vi.fn(),
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

// The `cuenta` section stacks the session and vault surfaces until WU-2
// merges them; the vault read must be hermetic in every test.
function renderProfile() {
  return render(
    <MemoryRouter>
      <ProfilePage />
    </MemoryRouter>,
  );
}

describe("ProfilePage account section (credentials mode)", () => {
  beforeEach(() => {
    (getAuthStatus as Mock).mockResolvedValue(credentialsStatus);
    (logoutSession as Mock).mockResolvedValue({
      ...credentialsStatus,
      authenticated: false,
    });
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
    (getVaultConfig as Mock).mockResolvedValue({
      enabled: false,
      account_exists: false,
      username: null,
      has_password: false,
      reauth_interval_d: 14,
      env_override: false,
    });
  });

  it("renders the Account section instead of the local-dev panel", async () => {
    renderProfile();

    expect(
      await screen.findByRole("heading", { name: "Cuenta", level: 3 }),
    ).toBeInTheDocument();
    // The header badge also shows the account label (REQ-PIA-05); scope to the
    // panel so the duplicate doesn't collide with the Account-section assert.
    const panel = within(screen.getByRole("tabpanel"));
    expect(panel.getByText("el-autor")).toBeInTheDocument();
    expect(panel.getByText("Proveedor: Credenciales")).toBeInTheDocument();
    expect(panel.getByRole("button", { name: "Cerrar sesión" })).toBeInTheDocument();
    expect(
      panel.getByRole("button", { name: "Rotar palabras claves" }),
    ).toBeInTheDocument();
    // The local-dev panel must not render in credentials mode.
    expect(
      screen.queryByRole("button", { name: "Cerrar sesión local" }),
    ).not.toBeInTheDocument();
  });

  it("shows the soft re-auth countdown with the warning copy (R-AC-04d)", async () => {
    renderProfile();

    expect(
      await screen.findByText("Reingreso recomendado en 4 días"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /si no reingresas tu contraseña, la sesión de demiurgos se cerrará/i,
      ),
    ).toBeInTheDocument();
  });

  it("changes the username by proving ownership with the words", async () => {
    renderProfile();

    const form = await screen.findByRole("heading", {
      name: "Cambiar usuario",
    }).then((heading) => heading.closest("div") as HTMLElement);

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

    const form = await screen.findByRole("heading", {
      name: "Cambiar contraseña",
    }).then((heading) => heading.closest("div") as HTMLElement);

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

  it("removes the password (back to passwordless) with a two-click confirm", async () => {
    renderProfile();

    const form = await screen.findByRole("heading", {
      name: "Retirar contraseña",
    }).then((heading) => heading.closest("div") as HTMLElement);

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

  it("rotates the words and shows the new plaintext exactly once", async () => {
    renderProfile();

    fireEvent.click(
      await screen.findByRole("button", { name: "Rotar palabras claves" }),
    );

    expect(
      await screen.findByText("alpha beta gamma delta"),
    ).toBeInTheDocument();
    expect(rotateWords).toHaveBeenCalledTimes(1);
  });

  it("logs out through the unified session endpoint and reloads", async () => {
    renderProfile();

    fireEvent.click(
      await screen.findByRole("button", { name: "Cerrar sesión" }),
    );

    await waitFor(() => expect(logoutSession).toHaveBeenCalled());
    await waitFor(() => expect(reloadPage).toHaveBeenCalled());
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

async function openVaultTab() {
    renderProfile();
    fireEvent.click(await screen.findByRole("tab", { name: "Cuenta" }));
  }

  it("renders the create-account activation form when vault OFF and no account", async () => {
    await openVaultTab();

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
      .mockResolvedValue({
        enabled: true,
        account_exists: true,
        username: "el-autor",
        has_password: true,
        reauth_interval_d: 14,
        env_override: false,
      });
    (enableVault as Mock).mockResolvedValue({
      enabled: true,
      words: "alpha beta gamma delta",
    });
    await openVaultTab();

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
    fireEvent.click(
      screen.getByRole("button", { name: "Guardé mis palabras" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Desactivar bóveda" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("vault-words")).not.toBeInTheDocument();
  });

  it("activates an existing account by verifying the words (S-VC-03b/c)", async () => {
    (getVaultConfig as Mock).mockResolvedValue({
      enabled: false,
      account_exists: true,
      username: "el-autor",
      has_password: true,
      reauth_interval_d: 14,
      env_override: false,
    });
    await openVaultTab();

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

  it("renders the management UI when the vault is ON (R-VC-02b)", async () => {
    (getVaultConfig as Mock).mockResolvedValue({
      enabled: true,
      account_exists: true,
      username: "el-autor",
      has_password: true,
      reauth_interval_d: 14,
      env_override: false,
    });
    await openVaultTab();

    expect(await screen.findByText("Activa")).toBeInTheDocument();
    expect(screen.getByText(/Cuenta:/)).toBeInTheDocument();
    // Until WU-2 merges the account and vault surfaces, the management
    // controls exist on both stacked panels; assert presence, not uniqueness.
    expect(screen.getAllByText("el-autor").length).toBeGreaterThan(0);
    expect(
      screen.getAllByRole("heading", { name: "Cambiar usuario" }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByRole("heading", { name: "Cambiar contraseña" }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByRole("heading", { name: "Retirar contraseña" }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByRole("heading", { name: "Rotar palabras claves" }).length,
    ).toBeGreaterThan(0);
    // Vault-only surfaces: reauth interval and disable-vault live solely in
    // the management panel.
    expect(
      screen.getByRole("heading", { name: "Intervalo de reingreso" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Desactivar bóveda" }),
    ).toBeInTheDocument();
    // Activation-only surfaces must not render while ON.
    expect(
      screen.queryByRole("button", { name: "Activar bóveda" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Crear cuenta y activar" }),
    ).not.toBeInTheDocument();
  });

  it("adjusts the reauth interval (S-VC-05a)", async () => {
    (getVaultConfig as Mock).mockResolvedValue({
      enabled: true,
      account_exists: true,
      username: "el-autor",
      has_password: true,
      reauth_interval_d: 14,
      env_override: false,
    });
    await openVaultTab();

    const input = await screen.findByLabelText("Días entre reingresos");
    fireEvent.change(input, { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() =>
      expect(setReauthInterval).toHaveBeenCalledWith(7),
    );
    expect(
      await screen.findByText("Listo. Intervalo guardado."),
    ).toBeInTheDocument();
  });

  it("disables the vault with the words after a two-click confirm (S-VC-04a/b)", async () => {
    (getVaultConfig as Mock)
      .mockResolvedValueOnce({
        enabled: true,
        account_exists: true,
        username: "el-autor",
        has_password: true,
        reauth_interval_d: 14,
        env_override: false,
      })
      .mockResolvedValue({
        enabled: false,
        account_exists: true,
        username: "el-autor",
        has_password: true,
        reauth_interval_d: 14,
        env_override: false,
      });
    await openVaultTab();

    const form = await screen
      .findByRole("heading", { name: "Desactivar bóveda" })
      .then((heading) => heading.closest("div") as HTMLElement);
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