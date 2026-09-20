import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ProfilePage from "@/pages/ProfilePage";
import { getReadiness } from "@/api/onboarding";
import { getLocale } from "@/api/config";
import { getAuthStatus, getVaultConfig } from "@/api/wiki";
import { getBackupStatus } from "@/api/backup";
import { getAssistantSettings } from "@/api/assistantSettings";
import { getIdeaCaptureStatus } from "@/api/ideaCapture";
import type { Mock } from "vitest";

// The Conexiones section renders BOTH real connection panels (never stubbed):
// the goal is to prove they now read as one card family — a two-row index with
// the assistant first and active by default, driving a single visible body.

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

function renderProfile() {
  return render(
    <MemoryRouter initialEntries={["/perfil?tab=conexiones"]}>
      <ProfilePage />
    </MemoryRouter>,
  );
}

describe("ProfilePage — Conexiones connection-card family", () => {
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
    (getVaultConfig as Mock).mockResolvedValue({
      enabled: false,
      account_exists: false,
      username: null,
      has_password: false,
      reauth_interval_d: 14,
      env_override: false,
    });
    (getBackupStatus as Mock).mockResolvedValue({
      state: "pending",
      destination: null,
      mode: null,
      blocked: false,
      warning: null,
      last_write: null,
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

  it("shows the assistant first, active by default, with a single visible body", async () => {
    renderProfile();
    await screen.findByRole("tab", { name: "Conexiones" });
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Conexiones" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );

    const panel = screen.getByRole("tabpanel");
    // Index order: assistant first, Telegram second, each as one `h3` row.
    expect(
      within(panel)
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(["Asistente del Wiki", "Captura de ideas"]);

    expect(screen.getByRole("button", { name: "Asistente del Wiki" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByRole("button", { name: "Captura de ideas" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    // Both bodies are mounted, but only the assistant body is visible.
    const bodies = panel.querySelectorAll('[id^="connection-"][id$="-body"]');
    expect(bodies).toHaveLength(2);
    const visibleBodies = Array.from(bodies).filter(
      (body) => !body.hasAttribute("hidden"),
    );
    expect(visibleBodies).toHaveLength(1);
    expect(visibleBodies[0].id).toBe("connection-assistant-body");

    // The visible assistant body renders its wizard…
    expect(
      await within(visibleBodies[0] as HTMLElement).findByRole("heading", {
        name: "Proveedor",
      }),
    ).toBeInTheDocument();
    // …while the hidden Telegram body keeps its content mounted (state warm).
    expect(document.getElementById("connection-telegram-body")).toHaveTextContent(
      "Cómo funciona",
    );
    // The index is a toggle group, not a second tablist.
    expect(screen.getAllByRole("tablist")).toHaveLength(1);
  });
});
