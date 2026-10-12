import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ReportSection } from "@/components/organisms/ReportSection";
import { assembleBugReport } from "@/api/bugReports";
import { type BugReportBundle } from "@/api/types";
import type { Mock } from "vitest";
import { tEs } from "@/__tests__/i18nTestUtils";
import ProfilePage from "@/pages/ProfilePage";

vi.mock("@/api/bugReports", () => ({
  assembleBugReport: vi.fn(),
}));

/** A canonical allow-listed bundle, shaped exactly like the backend response
 *  (sorted allow-list; logs dropped with a non-secret reason). */
const baseBundle: BugReportBundle = {
  app_version: "0.2.0",
  platform: {
    os: "Linux",
    os_version: "6.8.0",
    arch: "x86_64",
    python_version: "3.11.9",
  },
  logs: {
    included: false,
    content: "",
    redacted_lines: 0,
    reason: "no logs available",
  },
  allow_list: ["app_version", "contact", "description", "logs", "platform"],
  contact_slot: true,
};

describe("ReportSection — Perfil → Reporte de errores (S2a skeleton)", () => {
  beforeEach(() => {
    (assembleBugReport as Mock).mockReset();
  });

  it("calls assembleBugReport once on mount and renders the assembled bundle", async () => {
    (assembleBugReport as Mock).mockResolvedValue(baseBundle);
    render(<ReportSection />);

    expect(assembleBugReport).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.getByTestId("bugreport-app-version")).toHaveTextContent("0.2.0"),
    );
    // Allow-listed platform facts render as one summary line.
    expect(screen.getByTestId("bugreport-platform")).toHaveTextContent(
      "Linux 6.8.0 · x86_64 · Python 3.11.9",
    );
    // Logs dropped with the non-secret reason surface verbatim.
    expect(screen.getByTestId("bugreport-logs-status")).toHaveTextContent(
      tEs("profile.bugreport.logsExcluded"),
    );
    expect(
      screen.getByText(`${tEs("profile.bugreport.logsReason")}: no logs available`),
    ).toBeInTheDocument();
    // The allow-list itself renders, joined in server order.
    expect(screen.getByTestId("bugreport-allow-list")).toHaveTextContent(
      "app_version, contact, description, logs, platform",
    );
  });

  it("renders the redaction count when logs were included but scrubbed", async () => {
    (assembleBugReport as Mock).mockResolvedValue({
      ...baseBundle,
      logs: {
        included: true,
        content: "[redacted: bot-token]\ndebug line",
        redacted_lines: 1,
        reason: "",
      },
    });
    render(<ReportSection />);

    await waitFor(() =>
      expect(screen.getByTestId("bugreport-logs-status")).toHaveTextContent(
        `${tEs("profile.bugreport.logsIncluded")} · ${tEs("profile.bugreport.redactedLines", { count: 1 })}`,
      ),
    );
  });

  it("shows the localized error instead of crashing when assembly fails", async () => {
    (assembleBugReport as Mock).mockRejectedValue(new Error("boom"));
    render(<ReportSection />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        tEs("profile.bugreport.loadError"),
      ),
    );
  });
});

// ProfilePage assertion (spec: the bug-report flow is the 7th Profile entry,
// after `actualizaciones`). Mirrors the actualizaciones suite mock set so the
// page render stays hermetic.
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
  applyUpdate: vi.fn(),
}));

function renderProfile(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <ProfilePage />
    </MemoryRouter>,
  );
}

describe("ProfilePage — bug-report section entry (7th, after Actualizaciones)", () => {
  beforeEach(() => {
    (assembleBugReport as Mock).mockReset();
    (assembleBugReport as Mock).mockResolvedValue(baseBundle);
  });

  it("lists the report entry as the 7th tab, right after Actualizaciones", async () => {
    renderProfile("/perfil");
    // Settle the default CuentaSection view before asserting the rail.
    await screen.findByRole("heading", { name: "Sesión", level: 3 });

    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(7);
    expect(tabs[5].textContent).toBe(tEs("profile.section.actualizaciones"));
    expect(tabs[6].textContent).toBe(tEs("profile.section.reporte"));
    expect(screen.getByRole("tab", { name: tEs("profile.section.reporte") })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("opens the report flow when the entry is selected", async () => {
    renderProfile("/perfil?tab=reporte");

    expect(
      screen.getByRole("tab", { name: tEs("profile.section.reporte") }),
    ).toHaveAttribute("aria-selected", "true");

    const panel = screen.getByRole("tabpanel");
    // The panel h2 carries the section name; the section owns its h3 title.
    expect(
      within(panel).getByRole("heading", {
        name: tEs("profile.bugreport.panelTitle"),
        level: 3,
      }),
    ).toBeInTheDocument();
    // Mounting the entry assembles the bundle once.
    await waitFor(() => expect(assembleBugReport).toHaveBeenCalledTimes(1));
  });
});