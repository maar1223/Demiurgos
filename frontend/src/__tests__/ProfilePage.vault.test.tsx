import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import ProfilePage from "@/pages/ProfilePage";
import {
  changePassword,
  changeUsername,
  getAuthStatus,
  logoutSession,
  removePassword,
  rotateWords,
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
  });

  it("renders the Account section instead of the local-dev panel", async () => {
    render(<ProfilePage />);

    expect(
      await screen.findByRole("heading", { name: "Cuenta" }),
    ).toBeInTheDocument();
    expect(screen.getByText("el-autor")).toBeInTheDocument();
    expect(screen.getByText("Proveedor: Credenciales")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cerrar sesión" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rotar palabras claves" }),
    ).toBeInTheDocument();
    // The local-dev panel must not render in credentials mode.
    expect(
      screen.queryByRole("button", { name: "Cerrar sesión local" }),
    ).not.toBeInTheDocument();
  });

  it("shows the soft re-auth countdown with the warning copy (R-AC-04d)", async () => {
    render(<ProfilePage />);

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
    render(<ProfilePage />);

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
    render(<ProfilePage />);

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
    render(<ProfilePage />);

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
    render(<ProfilePage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Rotar palabras claves" }),
    );

    expect(
      await screen.findByText("alpha beta gamma delta"),
    ).toBeInTheDocument();
    expect(rotateWords).toHaveBeenCalledTimes(1);
  });

  it("logs out through the unified session endpoint and reloads", async () => {
    render(<ProfilePage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Cerrar sesión" }),
    );

    await waitFor(() => expect(logoutSession).toHaveBeenCalled());
    await waitFor(() => expect(reloadPage).toHaveBeenCalled());
  });
});