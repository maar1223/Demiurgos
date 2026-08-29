import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ProfilePage from "@/pages/ProfilePage";
import { getReadiness } from "@/api/onboarding";
import type { Mock } from "vitest";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: () => ({ worlds: [] }),
}));

vi.mock("@/api/onboarding", () => ({
  getReadiness: vi.fn(),
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

describe("ProfilePage", () => {
  beforeEach(() => {
    // Default readiness: no legacy folders. The Mundos tab's migration panel
    // only renders when readiness reports legacy findings.
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {},
      offline: { local_ready: true, remote_pending: [] },
      legacy: [],
    });
  });

  it("renders the assistant section entry point and panel", () => {
    render(<ProfilePage />);

    fireEvent.click(screen.getByRole("button", { name: "Asistente IA" }));

    expect(screen.getByText("assistant settings panel")).toBeInTheDocument();
  });

  it("renders the configuration tab between sesión and integraciones with only kept cards", async () => {
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {
        backup: "pending",
        locale: "configured",
        offline: "configured",
      },
      offline: {
        local_ready: true,
        remote_pending: ["identity", "telegram", "backup", "assistant"],
      },
      legacy: [],
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    // Tab order: Sesión de edición → Centro de Configuración → Integraciones.
    const tabLabels = screen
      .getAllByRole("button")
      .map((button) => button.textContent);
    const order = (label: string) => tabLabels.indexOf(label);
    expect(order("Sesión de edición")).toBeGreaterThanOrEqual(0);
    expect(order("Centro de Configuración")).toBeGreaterThan(
      order("Sesión de edición"),
    );
    expect(order("Integraciones")).toBeGreaterThan(
      order("Centro de Configuración"),
    );

    fireEvent.click(screen.getByRole("button", { name: "Centro de Configuración" }));

    // Readiness summary + the three kept cards render.
    expect(
      await screen.findByRole("heading", { name: "Listo para trabajar" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Respaldo y restauración" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Idioma, región y zona horaria" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Offline / dispositivo" }),
    ).toBeInTheDocument();

    // Redundant cards are NOT duplicated — they live in other Profile tabs
    // (Asistente IA / Mundos / Integraciones) or in the Profile itself.
    for (const redundant of [
      "Identidad",
      "IA texto y visión",
      "Telegram",
      "Mundos",
      "Importar mundo",
    ]) {
      expect(
        screen.queryByRole("heading", { name: redundant }),
      ).not.toBeInTheDocument();
    }
  });

  it("renders the idea-capture wizard as the only Telegram surface inside Integraciones", () => {
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Integraciones" }));

    // "Captura de ideas" (IdeaCapturePanel) is the single Telegram surface:
    // no separate TelegramCard block may render alongside it.
    expect(screen.getByText("idea capture")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Telegram" }),
    ).not.toBeInTheDocument();
  });

  it("renders the relocated legacy migration panel inside Mundos when readiness detects legacy folders", async () => {
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {},
      offline: { local_ready: true, remote_pending: [] },
      legacy: [{ world: "legacy-x", folders: ["Lore"] }],
    });
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Mundos" }));

    expect(await screen.findByText("migration panel")).toBeInTheDocument();
  });

  it("does not render the migration panel without legacy findings", async () => {
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Mundos" }));
    await screen.findByText("Zona peligrosa");

    expect(screen.queryByText("migration panel")).not.toBeInTheDocument();
  });
});
