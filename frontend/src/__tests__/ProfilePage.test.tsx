import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Router, useSearchParams } from "react-router-dom";
import { createMemoryHistory } from "@remix-run/router";
import { useLayoutEffect, useState, type ReactNode } from "react";
import ProfilePage from "@/pages/ProfilePage";
import { getReadiness } from "@/api/onboarding";
import { getLocale } from "@/api/config";
import { getAuthStatus, getVaultConfig } from "@/api/wiki";
import type { Mock } from "vitest";

/** Controlled Router that subscribes to a memory history so push/Back/replace
 *  navigation is observable in tests (MemoryRouter hides its history). */
function HistoryRouter({
  history,
  children,
}: {
  history: ReturnType<typeof createMemoryHistory>;
  children: ReactNode;
}) {
  const [state, setState] = useState({
    action: history.action,
    location: history.location,
  });
  useLayoutEffect(() => history.listen(setState), [history]);
  return (
    <Router location={state.location} navigationType={state.action} navigator={history}>
      {children}
    </Router>
  );
}

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: () => ({ worlds: [] }),
}));

vi.mock("@/api/onboarding", () => ({
  getReadiness: vi.fn(),
}));

// The inline locale form (REQ-PIA-12) prefills from the saved locale on
// mount; resolve it locally so the preferencias cases stay hermetic.
vi.mock("@/api/config", () => ({
  getLocale: vi.fn(),
}));

// The default `cuenta` section stacks the session and vault surfaces (the
// account/security merge is WU-2); keep the page test hermetic by resolving
// the session and vault reads locally.
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

// The configuration tab now mounts the real BackupSection (WU-15); keep the
// page test hermetic by resolving its read-only status calls locally.
vi.mock("@/api/backup", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/backup")>();
  return {
    ...actual,
    getBackupStatus: vi.fn().mockResolvedValue({
      state: "pending",
      destination: null,
      mode: null,
      blocked: false,
      warning: null,
      last_write: null,
      copy: null,
    }),
    getBackupCandidates: vi.fn().mockResolvedValue({ candidates: [], picker: true }),
    getBackupRestoreStatus: vi.fn().mockResolvedValue({
      pending: false,
      leftovers: [],
      last_write: null,
    }),
  };
});

// The status overview header (REQ-PIA-05) reads assistant state on every
// ProfilePage render; resolve it locally so this suite stays hermetic.
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
  });

  it("renders the assistant panel entry point inside Conexiones", () => {
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Conexiones" }));

    expect(screen.getByText("assistant settings panel")).toBeInTheDocument();
  });

  it("renders the configuration tab between cuenta and conexiones with only kept cards", async () => {
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

    // Tab order: Cuenta → Respaldo → Preferencias → Conexiones → Mundos.
    const tabLabels = screen
      .getAllByRole("tab")
      .map((tab) => tab.textContent);
    const order = (label: string) => tabLabels.indexOf(label);
    expect(order("Cuenta")).toBeGreaterThanOrEqual(0);
    expect(order("Respaldo")).toBeGreaterThan(order("Cuenta"));
    expect(order("Preferencias")).toBeGreaterThan(order("Respaldo"));
    expect(order("Conexiones")).toBeGreaterThan(order("Preferencias"));
    expect(order("Mundos")).toBeGreaterThan(order("Conexiones"));

    fireEvent.click(screen.getByRole("tab", { name: "Preferencias" }));

    // Readiness summary + the inline locale form + the kept offline card render.
    expect(
      await screen.findByRole("heading", { name: "Listo para trabajar" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Idioma, región y zona horaria" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Offline / dispositivo" }),
    ).toBeInTheDocument();

    // Redundant cards are NOT duplicated — they live in other Profile tabs
    // (Asistente IA / Mundos / Conexiones) or in the Profile itself.
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

  it("drops the redundant backup card from Preferencias while keeping the offline card", async () => {
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {
        backup: "pending",
        locale: "configured",
        offline: "configured",
      },
      offline: { local_ready: true, remote_pending: [] },
      legacy: [],
    });

    render(
      <MemoryRouter initialEntries={["/perfil?tab=preferencias"]}>
        <ProfilePage />
      </MemoryRouter>,
    );

    // The offline card is still the kept configuration card in Preferencias.
    expect(
      await screen.findByRole("heading", { name: "Offline / dispositivo" }),
    ).toBeInTheDocument();

    // The redundant backup card is gone (product-owner decision): it merely
    // navigated to the Respaldo section — which already has its own rail entry
    // — and its only remaining value, the status badge, was declared
    // unnecessary. Under the previous keepCards allowlist (`["backup",
    // "offline"]`) the assertion below fails: the card rendered here.
    expect(
      screen.queryByRole("heading", { name: "Respaldo y restauración" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Configurar respaldo" }),
    ).not.toBeInTheDocument();
  });

  it("renders the locale form inline in Preferencias (REQ-PIA-12)", async () => {
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {
        backup: "pending",
        locale: "configured",
        offline: "configured",
      },
      offline: { local_ready: true, remote_pending: [] },
      legacy: [],
    });

    render(
      <MemoryRouter initialEntries={["/perfil?tab=preferencias"]}>
        <ProfilePage />
      </MemoryRouter>,
    );

    // The locale surface IS the form, rendered directly in Preferencias — the
    // old "Configurar" reconfigure handoff is gone (REQ-PIA-12).
    const heading = await screen.findByRole("heading", {
      name: "Idioma, región y zona horaria",
    });
    const section = heading.closest("section") as HTMLElement;
    expect(section.id).toBe("config-card-locale");

    // All six fields are usable inline, without leaving /perfil.
    expect(within(section).getByLabelText("Idioma de la interfaz")).toBeInTheDocument();
    expect(within(section).getByLabelText("Idioma de conversación (asistente)")).toBeInTheDocument();
    expect(within(section).getByLabelText("Idioma de contenido (prosa del mundo)")).toBeInTheDocument();
    expect(within(section).getByLabelText(/Región \(opcional/)).toBeInTheDocument();
    expect(within(section).getByLabelText(/Confirmo la región/)).toBeInTheDocument();
    expect(within(section).getByLabelText(/Zona horaria/)).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Guardar" })).toBeInTheDocument();
    // No handoff control remains on the form.
    expect(within(section).queryByRole("button", { name: "Configurar" })).not.toBeInTheDocument();
  });

  it("hosts the backup surface inside the Respaldo section (REQ-PIA-02)", async () => {
    render(
      <MemoryRouter initialEntries={["/perfil?tab=respaldo"]}>
        <ProfilePage />
      </MemoryRouter>,
    );

    // BackupSection owns the respaldo section: its status heading renders
    // against the mocked pending state.
    expect(
      await screen.findByRole("heading", { name: "Estado del respaldo" }),
    ).toBeInTheDocument();
    // The backup surface renders exactly once: BackupSection owns it here, and
    // the removed Preferencias card no longer duplicates it (REQ-PIA-02).
    expect(
      screen.queryByRole("heading", { name: "Respaldo y restauración" }),
    ).not.toBeInTheDocument();
  });

  it("renders the idea-capture wizard as the only Telegram surface inside Conexiones", () => {
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Conexiones" }));

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

    fireEvent.click(screen.getByRole("tab", { name: "Mundos" }));

    expect(await screen.findByText("migration panel")).toBeInTheDocument();
  });

  it("does not render the migration panel without legacy findings", async () => {
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Mundos" }));
    await screen.findByText("Zona peligrosa");

    expect(screen.queryByText("migration panel")).not.toBeInTheDocument();
  });
});

describe("ProfilePage shell — URL-driven sections and ARIA rail (REQ-PIA-03/04/06/07/11)", () => {
  beforeEach(() => {
    (getReadiness as Mock).mockResolvedValue({
      local_editor: { probe: "local_editor", ok: true, detail: "ok" },
      cards: {},
      offline: { local_ready: true, remote_pending: [] },
      legacy: [],
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
  });

  /** Probe the `?tab` param exactly as the page reads it. */
  function UrlTabProbe() {
    const [params] = useSearchParams();
    return <span data-testid="url-tab">{params.get("tab") ?? ""}</span>;
  }

  it("opens the deep-linked section from ?tab= and preserves it across a reload", () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={["/perfil?tab=respaldo"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("tab", { name: "Respaldo" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Respaldo");
    expect(screen.getByRole("heading", { name: "Respaldo" })).toBeInTheDocument();

    // A reload re-renders from the same URL; the query param drives the state.
    unmount();
    render(
      <MemoryRouter initialEntries={["/perfil?tab=respaldo"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("tab", { name: "Respaldo" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("lands on cuenta without pushing when ?tab is absent", () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <UrlTabProbe />
        <ProfilePage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("tab", { name: "Cuenta" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByTestId("url-tab")).toHaveTextContent("");
  });

  it("pushes on an explicit tab click and Back returns to the previous section", () => {
    const history = createMemoryHistory({
      initialEntries: ["/perfil"],
      v5Compat: true,
    });
    render(
      <HistoryRouter history={history}>
        <UrlTabProbe />
        <ProfilePage />
      </HistoryRouter>,
    );
    expect(screen.getByRole("tab", { name: "Cuenta" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.click(screen.getByRole("tab", { name: "Conexiones" }));
    expect(screen.getByTestId("url-tab")).toHaveTextContent("conexiones");
    expect(screen.getByRole("tab", { name: "Conexiones" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    act(() => history.go(-1));
    expect(screen.getByTestId("url-tab")).toHaveTextContent("");
    expect(screen.getByRole("tab", { name: "Cuenta" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("replaces an invalid ?tab with cuenta without pushing a history entry", async () => {
    const history = createMemoryHistory({
      initialEntries: ["/perfil?tab=does-not-exist"],
      v5Compat: true,
    });
    render(
      <HistoryRouter history={history}>
        <UrlTabProbe />
        <ProfilePage />
      </HistoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("url-tab")).toHaveTextContent("cuenta"),
    );
    // `replace` keeps the history index; a push would have advanced it.
    expect(history.index).toBe(0);
    expect(screen.getByRole("tab", { name: "Cuenta" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("does not push when clicking the already-active tab", () => {
    const history = createMemoryHistory({
      initialEntries: ["/perfil"],
      v5Compat: true,
    });
    render(
      <HistoryRouter history={history}>
        <UrlTabProbe />
        <ProfilePage />
      </HistoryRouter>,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Cuenta" }));
    expect(screen.getByTestId("url-tab")).toHaveTextContent("");
    expect(history.index).toBe(0);
  });

  it("wires the tablist/tab/tabpanel contract with aria-selected and aria-controls", () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    const tablist = screen.getByRole("tablist", { name: "Secciones del perfil" });
    const tabs = within(tablist).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Cuenta",
      "Respaldo",
      "Preferencias",
      "Conexiones",
      "Mundos",
    ]);
    const activeTab = within(tablist).getByRole("tab", { name: "Cuenta" });
    expect(activeTab).toHaveAttribute("aria-selected", "true");
    expect(activeTab).toHaveAttribute("aria-controls", "profile-panel-cuenta");
    for (const tab of tabs) {
      if (tab !== activeTab) {
        expect(tab).toHaveAttribute("aria-selected", "false");
      }
    }
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", "profile-panel-cuenta");
    expect(panel).toHaveAttribute("aria-labelledby", "profile-tab-cuenta");
  });

  it("roves focus with ArrowLeft/Right/Home/End and selects the adjacent section", () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    const cuentaTab = screen.getByRole("tab", { name: "Cuenta" });
    fireEvent.keyDown(cuentaTab, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Respaldo" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Respaldo" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.keyDown(screen.getByRole("tab", { name: "Respaldo" }), { key: "End" });
    expect(screen.getByRole("tab", { name: "Mundos" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Mundos" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.keyDown(screen.getByRole("tab", { name: "Mundos" }), { key: "Home" });
    expect(screen.getByRole("tab", { name: "Cuenta" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Cuenta" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // ArrowLeft wraps back to the last tab.
    fireEvent.keyDown(screen.getByRole("tab", { name: "Cuenta" }), { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "Mundos" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Mundos" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("moves focus to the panel heading after a click-driven section change", () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Mundos" }));
    expect(document.getElementById("profile-panel-heading-mundos")).toHaveFocus();
  });

  it("keeps focus away from the panel heading on the default landing", () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    expect(
      document.getElementById("profile-panel-heading-cuenta"),
    ).not.toHaveFocus();
  });

  it("shows exactly one icon per section", () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    for (const tab of screen.getAllByRole("tab")) {
      expect(tab.querySelectorAll("svg")).toHaveLength(1);
    }
  });

  it("scrolls the rail horizontally on small widths instead of overflowing", () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("tablist")).toHaveClass("overflow-x-auto");
  });

  it("exposes an h1 followed by the section h2 with no skipped heading levels", () => {
    render(
      <MemoryRouter initialEntries={["/perfil"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    const levels = screen
      .getAllByRole("heading")
      .map((heading) => Number(heading.tagName.slice(1)));
    expect(levels[0]).toBe(1); // h1 "Perfil"
    expect(levels[1]).toBe(2); // the section's h2
    for (let i = 1; i < levels.length; i += 1) {
      expect(levels[i]).toBeLessThanOrEqual(levels[i - 1] + 1);
    }
  });

  it("keeps a contiguous heading outline inside Conexiones (REQ-PIA-07)", () => {
    render(
      <MemoryRouter initialEntries={["/perfil?tab=conexiones"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    const panel = within(screen.getByRole("tabpanel"));
    // The section owns its h3 heading directly under the panel h2.
    expect(
      panel.getByRole("heading", { name: "Captura de ideas", level: 3 }),
    ).toBeInTheDocument();
    const levels = panel
      .getAllByRole("heading")
      .map((heading) => Number(heading.tagName.slice(1)));
    expect(levels[0]).toBe(2); // the panel h2 "Conexiones"
    for (let i = 1; i < levels.length; i += 1) {
      expect(levels[i]).toBeLessThanOrEqual(levels[i - 1] + 1);
    }
  });

  it("keeps the Mundos subsections at h3 under the panel h2 (REQ-PIA-07)", () => {
    render(
      <MemoryRouter initialEntries={["/perfil?tab=mundos"]}>
        <ProfilePage />
      </MemoryRouter>,
    );
    const panel = within(screen.getByRole("tabpanel"));
    // The section intro stays h3; every subsection starts at the same h3
    // level, so the world list, the recycle bin and the legacy migration
    // panel never emit an orphan h4 under it.
    expect(panel.getByRole("heading", { name: "Zona peligrosa", level: 3 })).toBeInTheDocument();
    expect(
      panel.getByRole("heading", { name: "Papelera de mundos", level: 3 }),
    ).toBeInTheDocument();
    const levels = panel
      .getAllByRole("heading")
      .map((heading) => Number(heading.tagName.slice(1)));
    expect(levels[0]).toBe(2); // the panel h2 "Mundos"
    for (let i = 1; i < levels.length; i += 1) {
      expect(levels[i]).toBeLessThanOrEqual(levels[i - 1] + 1);
    }
  });
});