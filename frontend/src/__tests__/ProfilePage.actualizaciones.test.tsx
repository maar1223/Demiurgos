import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import ProfilePage from "@/pages/ProfilePage";

// The Perfil page renders the seven-section rail; this suite proves the
// "Actualizaciones" section is present, selectable, and mounts the read-only
// update panel. The panel's own behavior is covered by UpdateSection.test.tsx.

vi.mock("@/hooks/useProfileStatus", () => ({
  useProfileStatus: () => ({
    auth: {
      mode: "local-dev",
      enabled: true,
      authenticated: true,
      label: "Local development user",
    },
    backup: null,
    assistant: null,
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: () => ({ worlds: [], isLoading: false, error: null, mutate: vi.fn() }),
}));

// CuentaSection mounts when the page lands on `?tab=cuenta`; mock its sources
// so its async reads settle without React `act(...)` noise.
vi.mock("@/api/wiki", () => ({
  getAuthStatus: vi.fn().mockResolvedValue({
    mode: "local-dev",
    enabled: true,
    authenticated: true,
    label: "Local development user",
  }),
  getVaultConfig: vi.fn().mockResolvedValue({
    enabled: false,
    account_exists: false,
    username: null,
    has_password: false,
    reauth_interval_d: 14,
    env_override: false,
  }),
  changeUsername: vi.fn(),
  changePassword: vi.fn(),
  removePassword: vi.fn(),
  rotateWords: vi.fn(),
  enableVault: vi.fn(),
  disableVault: vi.fn(),
  setReauthInterval: vi.fn(),
}));

vi.mock("@/hooks/useLocalDevAuth", () => ({
  useLocalDevAuth: () => ({
    status: {
      mode: "local-dev",
      enabled: true,
      authenticated: true,
      label: "Local development user",
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
      mode: "local-dev",
      enabled: true,
      authenticated: true,
      label: "Local development user",
    },
    isLoading: false,
    error: null,
  }),
}));

vi.mock("@/api/updates", () => ({
  getUpdateStatus: vi.fn(),
  setUpdateChannel: vi.fn(),
}));

function renderProfile(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <ProfilePage />
    </MemoryRouter>,
  );
}

describe("ProfilePage — Actualizaciones section", () => {
  it("lists the sixth section in the rail", () => {
    renderProfile("/perfil?tab=actualizaciones");
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(7);
    expect(screen.getByRole("tab", { name: "Actualizaciones" })).toBeInTheDocument();
  });

  it("marks the section selected and renders the read-only panel", () => {
    renderProfile("/perfil?tab=actualizaciones");

    expect(screen.getByRole("tab", { name: "Actualizaciones" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    const panel = screen.getByRole("tabpanel");
    expect(
      within(panel).getByRole("button", { name: "Buscar actualizaciones" }),
    ).toBeInTheDocument();
    // Channel selector is present (Estable/Beta) — no data loaded yet.
    expect(within(panel).getByRole("radio", { name: "Estable" })).toBeInTheDocument();
    expect(within(panel).getByRole("radio", { name: "Beta" })).toBeInTheDocument();
  });

  it("is selectable from another section", async () => {
    const user = userEvent.setup();
    renderProfile("/perfil?tab=cuenta");

    // Land on Cuenta (settled) before navigating, so the switch is a real
    // cross-section change rather than the initial landing.
    await screen.findByRole("heading", { name: "Sesión", level: 3 });
    await user.click(screen.getByRole("tab", { name: "Actualizaciones" }));

    expect(screen.getByRole("tab", { name: "Actualizaciones" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      within(screen.getByRole("tabpanel")).getByRole("button", {
        name: "Buscar actualizaciones",
      }),
    ).toBeInTheDocument();
  });
});
