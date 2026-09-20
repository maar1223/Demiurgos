import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ProfilePage from "@/pages/ProfilePage";
import { getReadiness } from "@/api/onboarding";
import { getLocale } from "@/api/config";
import { getAuthStatus, getVaultConfig } from "@/api/wiki";
import { getBackupStatus } from "@/api/backup";
import {
  discoverAssistantModels,
  getAssistantSettings,
  runAssistantTextProbe,
  runAssistantVisionProbe,
  validateAssistantConnection,
} from "@/api/assistantSettings";
import { getIdeaCaptureStatus } from "@/api/ideaCapture";
import type { Mock } from "vitest";

// Mutable so one test can put the Cuenta section in the reachable
// vault-OFF + local-dev-not-started state without re-mocking the module.
const localDevMock = vi.hoisted(() => ({
  current: {
    mode: "local-dev",
    enabled: true,
    authenticated: true,
    label: "Local development user" as string | null,
  },
}));

// REQ-PIA-08 (emphasis rule) — AT MOST one primary action per visible view.
// The product owner accepted this interpretation: zero is allowed, since a
// read-only/status section needs no primary (`cuenta` with the vault ON and
// `mundos` legitimately render none). This suite mounts the real five Perfil
// sections (embedded panels included, not stubbed), counts the primary
// treatment (`bg-action`) inside the active tabpanel, and advances BOTH
// Conexiones wizards step by step — a static default view missed the two
// stacked primaries the assistant sub-wizard used to render. Destructive
// confirms use the danger treatment and are covered by the ConfirmDialog /
// WorldTrashPanel / PapeleraPanel / WorldImporter suites.

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
    status: localDevMock.current,
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
 * danger treatment (`bg-status-error`) is intentionally not counted here. A
 * hidden subtree (an inactive connection body) is a different view, so it is
 * excluded: the rule is at most one primary per VISIBLE view.
 */
function primaryLabels(): string[] {
  const panel = screen.getByRole("tabpanel");
  return Array.from(panel.querySelectorAll("button"))
    .filter((button) => !button.closest("[hidden]"))
    .filter((button) => button.className.includes("bg-action"))
    .map((button) => (button.textContent ?? "").trim());
}

/**
 * Open one connection by its index-row toggle (the `h3` title button, whose
 * accessible name is exactly the title) and wait until it is expanded.
 */
async function openConnection(name: string) {
  const toggle = screen.getByRole("button", { name });
  fireEvent.click(toggle);
  await waitFor(() =>
    expect(screen.getByRole("button", { name })).toHaveAttribute(
      "aria-expanded",
      "true",
    ),
  );
}

async function showSection(name: (typeof SECTIONS)[number]) {
  fireEvent.click(screen.getByRole("tab", { name }));
  await waitFor(() =>
    expect(screen.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true"),
  );
}

/** The spec rule: the visible section never shows more than one primary. */
async function expectAtMostOnePrimary() {
  await waitFor(() => expect(primaryLabels().length).toBeLessThanOrEqual(1));
}

function renderProfile() {
  render(
    <MemoryRouter initialEntries={["/perfil"]}>
      <ProfilePage />
    </MemoryRouter>,
  );
}

describe("ProfilePage emphasis rule (REQ-PIA-08)", () => {
  beforeEach(() => {
    // Default: an authenticated local-dev session, so `cuenta` renders no
    // session action. Individual tests may flip this to reach other states.
    localDevMock.current = {
      mode: "local-dev",
      enabled: true,
      authenticated: true,
      label: "Local development user",
    };
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
   * The audited primary labels per section. An empty list is a legitimate
   * outcome for a read-only/status section (accepted REQ-PIA-08 reading):
   * `Conexiones` now keeps only the idea-capture final commit as primary, and
   * `Mundos` owns no page-level CTA at all.
   */
  const AUDIT: Record<(typeof SECTIONS)[number], string[]> = {
    Cuenta: ["Crear cuenta y activar"],
    Respaldo: ["Backup ahora"],
    Preferencias: ["Guardar"],
    Conexiones: [],
    Mundos: [],
  };

  it("renders at most one primary in every section view", async () => {
    renderProfile();
    await screen.findByRole("tab", { name: "Cuenta" });

    for (const section of SECTIONS) {
      // eslint-disable-next-line no-await-in-loop
      await showSection(section);
      // eslint-disable-next-line no-await-in-loop
      await expectAtMostOnePrimary();
      const expected = AUDIT[section];
      if (expected.length > 0) {
        // eslint-disable-next-line no-await-in-loop
        await waitFor(() => expect(primaryLabels()).toEqual(expected));
      }
    }
  });

  it("never renders a second primary action in any section view", async () => {
    renderProfile();
    await screen.findByRole("tab", { name: "Cuenta" });

    for (const section of SECTIONS) {
      // eslint-disable-next-line no-await-in-loop
      await showSection(section);
      // eslint-disable-next-line no-await-in-loop
      await expectAtMostOnePrimary();
    }
  });

  it("renders zero primaries in the vault-ON Cuenta surface", async () => {
    // Vault ON: Cuenta renders the status card plus two collapsed management
    // disclosures. Every action inside is secondary or danger, so zero
    // primaries is correct — and the collapsed default hides no primary behind
    // a disclosure, so the count is asserted as exactly zero, not `<= 1`.
    (getVaultConfig as Mock).mockResolvedValue({
      enabled: true,
      account_exists: true,
      username: "ada",
      has_password: true,
      reauth_interval_d: 14,
      env_override: false,
    });

    renderProfile();
    await screen.findByRole("button", { name: "Gestionar credenciales" });

    await showSection("Cuenta");
    await waitFor(() => expect(primaryLabels()).toEqual([]));
    // Both management disclosures start collapsed.
    expect(
      screen.getByRole("button", { name: "Gestionar credenciales" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Zona peligrosa" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    // Mundos only offers per-row ghost actions (Renombrar/Borrar), the
    // recycle-bin Restaurar (secondary) and the migration action (secondary):
    // no page-owned primary exists, and none is invented here.
    await showSection("Mundos");
    await expectAtMostOnePrimary();
  });

  it("renders exactly one primary with the vault OFF and the local session not started", async () => {
    // Reachable state: vault OFF + local-dev enabled but not authenticated.
    // Starting the local session is the Navbar's job, so the section must not
    // stack its own "Iniciar sesión local" primary on top of ActivationPanel's.
    // Fails under the old code, which rendered both primaries here; after the
    // fix, ActivationPanel owns the section's single primary.
    localDevMock.current = {
      mode: "local-dev",
      enabled: true,
      authenticated: false,
      label: null,
    };

    renderProfile();
    await screen.findByRole("tab", { name: "Cuenta" });
    await showSection("Cuenta");

    // The duplicated action is gone — it lives only in the Navbar.
    expect(
      within(screen.getByRole("tabpanel")).queryByRole("button", {
        name: "Iniciar sesión local",
      }),
    ).not.toBeInTheDocument();
    // Exactly one primary remains, owned by the activation flow.
    await waitFor(() =>
      expect(primaryLabels()).toEqual(["Crear cuenta y activar"]),
    );
    await expectAtMostOnePrimary();
  });

  it("keeps at most one primary while advancing both Conexiones wizards step by step", async () => {
    // The idea-capture wizard needs a saved token to leave step 0; the
    // assistant panel needs a validated connection, discovered models and both
    // capability probes to reach its later steps.
    (getIdeaCaptureStatus as Mock).mockResolvedValue({
      config: {
        private_chat_ids: [],
        approved_groups: {},
        limits: { image_mb: 20, audio_mb: 50, audio_minutes: 5, raw_retention_days: 30 },
      },
      has_token: true,
      validation: { ok: true, errors: [] },
      serve: { command: "cmd", runnable: false, blocked_reasons: [] },
      worlds: [],
      limitations: [],
    });
    (validateAssistantConnection as Mock).mockResolvedValue({ outcome: "validated", message: null });
    (discoverAssistantModels as Mock).mockResolvedValue({
      outcome: "discovered",
      models: [
        { id: "deepseek-v4-flash", label: "DeepSeek V4 Flash", capability: "text-only", pricing: null },
      ],
    });
    (runAssistantTextProbe as Mock).mockResolvedValue({ outcome: "passed", oracle: "text-marker", message: null });
    (runAssistantVisionProbe as Mock).mockResolvedValue({ outcome: "passed", oracle: "causal-vision", message: null });

    // Under the old code every assistant CTA ("Validar conexión", "Descubrir
    // modelos", "Probar texto + visión", "Guardar configuración",
    // "Cambiar configuración") defaulted to primary. The assertion that fails
    // under the old code is the `expectAtMostOnePrimary()` right after entering
    // the assistant "Conexión" step (and at every later assistant step): it saw
    // two primary buttons — the assistant CTA plus the idea-capture
    // "Guardar configuración".
    renderProfile();
    await screen.findByRole("tab", { name: "Cuenta" });
    await showSection("Conexiones");

    // Assistant first and active by default. The hidden idea-capture body is
    // excluded from the count — the rule is per VISIBLE view.
    expect(
      screen.getByRole("button", { name: "Asistente del Wiki" }),
    ).toHaveAttribute("aria-expanded", "true");

    // --- assistant settings wizard: provider → confirmation
    await screen.findByRole("heading", { name: "Proveedor" });
    await expectAtMostOnePrimary();

    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    await screen.findByRole("heading", { name: "Conexión" });
    await expectAtMostOnePrimary();

    fireEvent.click(screen.getByRole("button", { name: "Validar conexión" }));
    await screen.findByText("Conexión validada.");
    await expectAtMostOnePrimary();

    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    await screen.findByRole("heading", { name: "Modelos" });
    await expectAtMostOnePrimary();

    fireEvent.click(screen.getByRole("button", { name: "Descubrir modelos" }));
    await screen.findByRole("combobox", { name: "Modelo descubierto" });
    await expectAtMostOnePrimary();

    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    await screen.findByRole("heading", { name: "Capacidad" });
    await expectAtMostOnePrimary();

    fireEvent.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    await screen.findByText("Prueba de texto superada.");
    await screen.findByText("Prueba de visión superada.");
    await expectAtMostOnePrimary();

    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    await screen.findByRole("heading", { name: "Confirmación" });
    await expectAtMostOnePrimary();

    // --- idea-capture wizard: open its row, then step 0 (connect) → step 3
    await openConnection("Captura de ideas");
    await screen.findByRole("heading", { name: "Conectá tu bot de Telegram" });
    await expectAtMostOnePrimary();

    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));
    await screen.findByRole("heading", { name: "Detectá el chat que recibirá tus ideas" });
    await expectAtMostOnePrimary();

    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));
    await screen.findByRole("heading", { name: "Revisá tu configuración" });
    await expectAtMostOnePrimary();

    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));
    await screen.findByRole("heading", { name: "Finalizá y arrancá la captura" });
    // The idea-capture final commit is the visible view's only primary.
    await waitFor(() => expect(primaryLabels()).toEqual(["Guardar configuración"]));
  });

  it("renders the two connection rows with one visible body and no second tablist", async () => {
    renderProfile();
    await screen.findByRole("tab", { name: "Cuenta" });
    await showSection("Conexiones");

    const panel = screen.getByRole("tabpanel");
    // Assistant first, Telegram second — both as `h3` index rows, never tabs.
    expect(
      within(panel)
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(["Asistente del Wiki", "Captura de ideas"]);

    const assistantToggle = screen.getByRole("button", { name: "Asistente del Wiki" });
    const telegramToggle = screen.getByRole("button", { name: "Captura de ideas" });
    expect(assistantToggle).toHaveAttribute("aria-expanded", "true");
    expect(telegramToggle).toHaveAttribute("aria-expanded", "false");

    // Both bodies stay mounted; exactly one is visible at a time.
    const bodies = panel.querySelectorAll('[id^="connection-"][id$="-body"]');
    expect(bodies).toHaveLength(2);
    expect(Array.from(bodies).filter((body) => !body.hasAttribute("hidden"))).toHaveLength(1);
    expect(document.getElementById("connection-assistant-body")).not.toHaveAttribute("hidden");
    expect(document.getElementById("connection-telegram-body")).toHaveAttribute("hidden");

    // The page's section rail still owns the only tablist.
    expect(screen.getAllByRole("tablist")).toHaveLength(1);

    // Switching connections flips which single body is visible.
    await openConnection("Captura de ideas");
    expect(document.getElementById("connection-assistant-body")).toHaveAttribute("hidden");
    expect(document.getElementById("connection-telegram-body")).not.toHaveAttribute("hidden");
  });
});
