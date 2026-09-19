import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ProfilePage from "@/pages/ProfilePage";
import { getReadiness } from "@/api/onboarding";
import { getLocale } from "@/api/config";
import { getAuthStatus, getVaultConfig } from "@/api/wiki";
import { getBackupStatus } from "@/api/backup";
import { getAssistantSettings } from "@/api/assistantSettings";
import { getIdeaCaptureStatus } from "@/api/ideaCapture";
import type { Mock } from "vitest";

// REQ-PIA-08 (emphasis rule) — one primary action per visible view. This suite
// mounts the real five Perfil sections (embedded panels included, not stubbed)
// and counts the primary treatment (`bg-action`) inside the active tabpanel.
// Destructive confirms use the danger treatment and are covered by the
// ConfirmDialog / WorldTrashPanel / PapeleraPanel / WorldImporter suites.

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: () => ({ worlds: [] }),
}));

vi.mock("@/api/onboarding", () => ({
  getReadiness: vi.fn(),
  submitStep0: vi.fn(),
}));

vi.mock("@/api/config", () => ({
  getLocale: vi.fn(),
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
  validateAssistantConnection: vi.fn(),
  discoverAssistantModels: vi.fn(),
  runAssistantTextProbe: vi.fn(),
  runAssistantVisionProbe: vi.fn(),
  saveAssistantConfiguration: vi.fn(),
  clearAssistantKey: vi.fn(),
}));

vi.mock("@/api/ideaCapture", () => ({
  getIdeaCaptureStatus: vi.fn(),
  saveIdeaCaptureConfig: vi.fn(),
  setIdeaCaptureToken: vi.fn(),
  clearIdeaCaptureToken: vi.fn(),
  discoverChatCandidates: vi.fn(),
  authorizeChat: vi.fn(),
}));

vi.mock("@/api/worlds", () => ({
  renameWorld: vi.fn(),
  listTrash: vi.fn().mockResolvedValue([]),
  permanentDelete: vi.fn(),
  restoreWorld: vi.fn(),
  createWorld: vi.fn(),
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

const SECTIONS = ["Cuenta", "Respaldo", "Preferencias", "Conexiones", "Mundos"] as const;

/**
 * Primary actions rendered inside the active section panel. A primary action
 * is a `button` carrying the `Button` primary surface (`bg-action`); the
 * danger treatment (`bg-status-error`) is intentionally not counted here.
 */
function primaryLabels(): string[] {
  const panel = screen.getByRole("tabpanel");
  return Array.from(panel.querySelectorAll("button"))
    .filter((button) => button.className.includes("bg-action"))
    .map((button) => (button.textContent ?? "").trim());
}

async function showSection(name: (typeof SECTIONS)[number]) {
  fireEvent.click(screen.getByRole("tab", { name }));
  await waitFor(() =>
    expect(screen.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true"),
  );
}

describe("ProfilePage emphasis rule (REQ-PIA-08)", () => {
  beforeEach(() => {
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {},
      offline: { local_ready: true, remote_pending: [] },
      legacy: [],
    });
    (getLocale as Mock).mockResolvedValue({
      ui: "es",
      conversation: "es",
      content: "es",
      region: null,
      region_explicit: false,
      iana_timezone: "UTC",
    });
    (getAuthStatus as Mock).mockResolvedValue({
      mode: "local-dev",
      enabled: true,
      authenticated: true,
      label: "Local development user",
    });
    // Vault OFF with no account yet: `cuenta` renders its activation view.
    (getVaultConfig as Mock).mockResolvedValue({
      enabled: false,
      account_exists: false,
      username: null,
      has_password: false,
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
    (getIdeaCaptureStatus as Mock).mockResolvedValue({
      config: {
        private_chat_ids: [],
        approved_groups: {},
        limits: { image_mb: 20, audio_mb: 50, audio_minutes: 5, raw_retention_days: 30 },
      },
      has_token: false,
      validation: { ok: true, errors: [] },
      serve: { command: "cmd", runnable: false, blocked_reasons: [] },
      worlds: [],
      limitations: [],
    });
  });

  /**
   * The audited per-section primary counts. Cuenta/Respaldo/Preferencias/
   * Conexiones must render exactly one; Mundos currently renders none, which is
   * reported as a product decision rather than invented here.
   */
  const AUDIT: Record<(typeof SECTIONS)[number], string[]> = {
    Cuenta: ["Crear cuenta y activar"],
    Respaldo: ["Backup ahora"],
    Preferencias: ["Guardar"],
    Conexiones: ["Continuar"],
    Mundos: [],
  };

  it("renders the audited primary count in every section view", async () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    await screen.findByRole("tab", { name: "Cuenta" });

    for (const section of SECTIONS) {
      // eslint-disable-next-line no-await-in-loop
      await showSection(section);
      const expected = AUDIT[section];
      // eslint-disable-next-line no-await-in-loop
      await waitFor(() => expect(primaryLabels()).toEqual(expected));
      if (expected.length === 1) {
        expect(primaryLabels()).toHaveLength(1);
      }
    }
  });

  it("never renders a second primary action in any section view", async () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    await screen.findByRole("tab", { name: "Cuenta" });

    for (const section of SECTIONS) {
      // eslint-disable-next-line no-await-in-loop
      await showSection(section);
      // The concrete spec scenario: "exactly one primary action and no second
      // primary". Conexiones previously rendered three ("Guardar token",
      // "Continuar" and the assistant's active step chip).
      // eslint-disable-next-line no-await-in-loop
      await waitFor(() => expect(primaryLabels().length).toBeLessThanOrEqual(1));
    }
  });

  it("documents the Mundos section rendering no primary (needs product decision)", async () => {
    render(
      <MemoryRouter initialEntries={["/perfil?tab=mundos"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    await screen.findByRole("tab", { name: "Mundos" });
    // The section only offers per-row ghost actions (Renombrar/Borrar), the
    // recycle-bin Restaurar (secondary), and the migration action (secondary).
    // No page-owned CTA exists, so none is invented here.
    await waitFor(() => expect(primaryLabels()).toHaveLength(0));
  });
});
