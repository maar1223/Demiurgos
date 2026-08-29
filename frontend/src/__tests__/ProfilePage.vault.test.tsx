import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ProfilePage from "@/pages/ProfilePage";
import { getAuthStatus, logoutSession, rotateEmergencyKey } from "@/api/wiki";
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
  rotateEmergencyKey: vi.fn(),
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

const googleStatus = {
  mode: "google",
  enabled: true,
  authenticated: true,
  label: "author@example.com",
  provider: "google",
};

describe("ProfilePage vault session controls (google mode)", () => {
  beforeEach(() => {
    (getAuthStatus as Mock).mockResolvedValue(googleStatus);
    (logoutSession as Mock).mockResolvedValue({
      ...googleStatus,
      authenticated: false,
    });
    (rotateEmergencyKey as Mock).mockResolvedValue({
      new_key: "alpha beta gamma delta",
    });
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {},
      offline: { local_ready: true, remote_pending: [] },
      legacy: [],
    });
  });

  it("renders the vault session controls instead of the local-dev panel", async () => {
    render(<ProfilePage />);

    expect(
      await screen.findByRole("heading", { name: "Sesión de edición" }),
    ).toBeInTheDocument();
    expect(screen.getByText("author@example.com")).toBeInTheDocument();
    expect(screen.getByText("Proveedor: Google")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cerrar sesión" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rotar clave de emergencia" }),
    ).toBeInTheDocument();
    // The local-dev panel must not render in google mode.
    expect(
      screen.queryByRole("button", { name: "Cerrar sesión local" }),
    ).not.toBeInTheDocument();
  });

  it("rotates the emergency key and shows the new key exactly once", async () => {
    render(<ProfilePage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Rotar clave de emergencia" }),
    );

    expect(await screen.findByText("alpha beta gamma delta")).toBeInTheDocument();
    expect(rotateEmergencyKey).toHaveBeenCalledTimes(1);
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