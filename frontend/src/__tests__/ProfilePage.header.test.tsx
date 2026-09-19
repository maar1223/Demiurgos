import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ProfilePage from "@/pages/ProfilePage";
import { getReadiness } from "@/api/onboarding";
import { getAuthStatus, getVaultConfig } from "@/api/wiki";
import { getBackupStatus } from "@/api/backup";
import { getAssistantSettings } from "@/api/assistantSettings";
import type { Mock } from "vitest";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: () => ({ worlds: [] }),
}));

vi.mock("@/api/onboarding", () => ({
  getReadiness: vi.fn(),
}));

// The header (REQ-PIA-05) reads identity, backup and assistant state on every
// render; keep the page hermetic by resolving all three locally.
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

vi.mock("@/api/backup", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/backup")>();
  return {
    ...actual,
    getBackupStatus: vi.fn(),
    getBackupCandidates: vi.fn().mockResolvedValue({ candidates: [], picker: true }),
    getBackupRestoreStatus: vi.fn().mockResolvedValue({
      pending: false,
      leftovers: [],
      last_write: null,
    }),
  };
});

vi.mock("@/api/assistantSettings", () => ({
  getAssistantSettings: vi.fn(),
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

const SECTIONS = ["Cuenta", "Respaldo", "Preferencias", "Conexiones", "Mundos"] as const;

/** The status strip element, scoped so page-level duplicates (e.g.
 *  `el-autor`) don't collide with the header's own readouts. */
function headerStrip() {
  return screen.getByLabelText("Estado del perfil");
}

describe("ProfilePage status overview header (REQ-PIA-05)", () => {
  beforeEach(() => {
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {},
      offline: { local_ready: true, remote_pending: [] },
      legacy: [],
    });
    (getAuthStatus as Mock).mockResolvedValue({
      mode: "credentials",
      enabled: true,
      authenticated: true,
      label: "el-autor",
      provider: "credentials",
    });
    (getVaultConfig as Mock).mockResolvedValue({
      enabled: true,
      account_exists: true,
      username: "el-autor",
      has_password: true,
      reauth_interval_d: 14,
      env_override: false,
    });
    (getBackupStatus as Mock).mockResolvedValue({
      state: "configured",
      destination: {
        schema_version: 1,
        path: "/data/respaldo",
        provider: "folder",
        source: "user",
        confidence: "verified",
        mode_hint: "mirrored",
        updated_at: "2026-09-19T10:00:00Z",
      },
      mode: "mirrored",
      blocked: false,
      warning: null,
      last_write: {
        destination: "/data/respaldo",
        written_at: "2026-09-19T10:00:00Z",
        status: "ok",
      },
      copy: null,
    });
    (getAssistantSettings as Mock).mockResolvedValue({
      provider: "opencode-go",
      base_url: "https://opencode.ai/zen/go/v1",
      model: "deepseek-v4-flash",
      model_metadata: {
        id: "deepseek-v4-flash",
        label: "DeepSeek V4 Flash",
        capability: "text-only",
        pricing: null,
      },
      key_configured: true,
      models: [],
      active_profile: "default",
      revision: 1,
      runtime_state: "active",
    });
  });

  it("shows identity, backup and assistant status on the default section", async () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );

    const strip = within(headerStrip());
    expect(await strip.findByText("el-autor")).toBeInTheDocument();
    expect(strip.getByText("Respaldo configurado")).toBeInTheDocument();
    expect(strip.getByText("Asistente activo")).toBeInTheDocument();
  });

  it("keeps the header visible on every section", async () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );

    const strip = within(headerStrip());
    await strip.findByText("Respaldo configurado");

    for (const section of SECTIONS) {
      fireEvent.click(screen.getByRole("tab", { name: section }));
      await waitFor(() =>
        expect(screen.getByRole("tab", { name: section })).toHaveAttribute(
          "aria-selected",
          "true",
        ),
      );
      // The header strip is page-owned, above the rail: every section keeps
      // the three statuses (identity, backup, assistant).
      expect(strip.getByText("el-autor")).toBeInTheDocument();
      expect(strip.getByText("Respaldo configurado")).toBeInTheDocument();
      expect(strip.getByText("Asistente activo")).toBeInTheDocument();
    }
  });

  it("fails open: an unavailable backup source degrades that badge only", async () => {
    (getBackupStatus as Mock).mockRejectedValue(new Error("backend down"));

    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );

    // Identity and assistant still resolve; backup shows the neutral badge.
    const strip = within(headerStrip());
    expect(await strip.findByText("el-autor")).toBeInTheDocument();
    expect(strip.getByText("Respaldo no disponible")).toBeInTheDocument();
    expect(strip.getByText("Asistente activo")).toBeInTheDocument();
  });

  it("fails open: an unavailable assistant source degrades that badge only", async () => {
    (getAssistantSettings as Mock).mockRejectedValue(new Error("hermes down"));

    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );

    const strip = within(headerStrip());
    expect(await strip.findByText("el-autor")).toBeInTheDocument();
    expect(strip.getByText("Respaldo configurado")).toBeInTheDocument();
    expect(strip.getByText("Asistente no disponible")).toBeInTheDocument();
  });
});