import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ReportSection } from "@/components/organisms/ReportSection";
import { assembleBugReport, fallbackBody, submitBugReport } from "@/api/bugReports";
import { ApiError, type BugReportBundle } from "@/api/types";
import type { Mock } from "vitest";
import { tEs } from "@/__tests__/i18nTestUtils";
import ProfilePage from "@/pages/ProfilePage";

vi.mock("@/api/bugReports", () => ({
  assembleBugReport: vi.fn(),
  submitBugReport: vi.fn(),
  fallbackBody: vi.fn(),
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

/** Same bundle but with default-on logs included, so removal is meaningful. */
const logsBundle: BugReportBundle = {
  ...baseBundle,
  logs: {
    included: true,
    content: "2026-01-01 debug line",
    redacted_lines: 0,
    reason: "",
  },
};

describe("submitBugReport — attachments travel as multipart", () => {
  it("puts the bundle in a report part and each image in its own part", async () => {
    const { submitBugReport: realSubmit } = await vi.importActual<
      typeof import("@/api/bugReports")
    >("@/api/bugReports");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true, delivery_id: "d-9" }),
      headers: new Headers(),
    });
    const original = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
    try {
      const file = new File([new Uint8Array(8)], "captura.png", { type: "image/png" });
      await realSubmit(
        {
          app_version: "0.2.0",
          platform: {
            os: "Linux",
            os_version: "6.8.0",
            arch: "x86_64",
            python_version: "3.11.9",
          },
          description: "boom",
          logs: "line",
        },
        [file],
      );

      const body = (fetchMock.mock.calls[0][1] as RequestInit).body;
      expect(body).toBeInstanceOf(FormData);
      const form = body as FormData;
      expect(JSON.parse(String(form.get("report"))).description).toBe("boom");
      const part = form.get("attachments");
      expect(part).toBeInstanceOf(File);
      expect((part as File).name).toBe("captura.png");
    } finally {
      globalThis.fetch = original;
    }
  });
});

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

// S2b — mandatory preview gate, editable description, removable fields, submit
// through the relay and the STRICT fallback (copy-paste body + issue link)
// offered only when delivery fails.
describe("ReportSection — preview gate, submit and strict fallback (S2b)", () => {
  beforeEach(() => {
    (assembleBugReport as Mock).mockReset();
    (submitBugReport as Mock).mockReset();
    (fallbackBody as Mock).mockReset();
    (assembleBugReport as Mock).mockResolvedValue(logsBundle);
  });

  /** Mount the section with an assembled bundle and return a user-event handle. */
  async function renderReady() {
    const user = userEvent.setup();
    render(<ReportSection />);
    await screen.findByTestId("bugreport-app-version");
    return user;
  }

  function image(name = "captura.png", type = "image/png", size = 1024): File {
    return new File([new Uint8Array(size)], name, { type });
  }

  it("adds a screenshot, shows its thumbnail, and re-locks the gate", async () => {
    const user = await renderReady();
    const preview = screen.getByRole("button", {
      name: tEs("profile.bugreport.preview"),
    });
    const submit = screen.getByRole("button", {
      name: tEs("profile.bugreport.submit"),
    });
    await user.click(preview);
    expect(submit).toBeEnabled();

    await user.upload(screen.getByLabelText(tEs("profile.bugreport.addScreenshot")), image());

    // New input invalidates the preview: nothing ships unseen.
    expect(submit).toBeDisabled();
    expect(screen.getAllByTestId("bugreport-attachment")).toHaveLength(1);
    expect(screen.getByTestId("bugreport-attachment")).toHaveTextContent("captura.png");
  });

  it("lists the screenshots in the preview and sends them with the report", async () => {
    const user = await renderReady();
    const file = image("pantalla.png");

    await user.upload(screen.getByLabelText(tEs("profile.bugreport.addScreenshot")), file);
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.preview") }),
    );

    expect(screen.getByTestId("bugreport-preview-attachments")).toHaveTextContent(
      tEs("profile.bugreport.previewAttachments", { count: 1 }),
    );

    (submitBugReport as Mock).mockResolvedValue({ ok: true, delivery_id: "d-7" });
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.submit") }),
    );

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledTimes(1));
    const [, attachments] = (submitBugReport as Mock).mock.calls[0];
    expect(attachments).toEqual([file]);
  });

  it("removing a screenshot re-locks the gate", async () => {
    const user = await renderReady();

    await user.upload(
      screen.getByLabelText(tEs("profile.bugreport.addScreenshot")),
      image(),
    );
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.preview") }),
    );
    const submit = screen.getByRole("button", {
      name: tEs("profile.bugreport.submit"),
    });
    expect(submit).toBeEnabled();

    await user.click(screen.getByRole("button", { name: /Quitar captura/ }));

    expect(submit).toBeDisabled();
    expect(screen.queryAllByTestId("bugreport-attachment")).toHaveLength(0);
  });

  it("sends no attachments when none were chosen", async () => {
    const user = await renderReady();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.preview") }),
    );
    (submitBugReport as Mock).mockResolvedValue({ ok: true, delivery_id: "d-8" });
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.submit") }),
    );

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledTimes(1));
    expect((submitBugReport as Mock).mock.calls[0][1]).toEqual([]);
  });

  it("keeps at most two screenshots and says so", async () => {
    const user = await renderReady();
    const input = screen.getByLabelText(tEs("profile.bugreport.addScreenshot"));

    await user.upload(input, [image("a.png"), image("b.png")]);
    await user.upload(input, image("c.png"));

    expect(screen.getAllByTestId("bugreport-attachment")).toHaveLength(2);
    expect(screen.getByRole("alert")).toHaveTextContent(
      tEs("profile.bugreport.attachmentLimit"),
    );
  });

  it("refuses an oversized or non-image screenshot locally", async () => {
    // The picker filters by `accept`, but a desktop dialog can still hand a file
    // over, so the panel re-checks and must say why it refused.
    const user = userEvent.setup({ applyAccept: false });
    (assembleBugReport as Mock).mockResolvedValue(baseBundle);
    render(<ReportSection />);
    await screen.findByTestId("bugreport-app-version");
    const input = screen.getByLabelText(tEs("profile.bugreport.addScreenshot"));

    await user.upload(input, image("grande.png", "image/png", 5 * 1024 * 1024 + 1));
    expect(screen.queryAllByTestId("bugreport-attachment")).toHaveLength(0);
    expect(screen.getByRole("alert")).toHaveTextContent(
      tEs("profile.bugreport.attachmentTooLarge"),
    );

    await user.upload(input, image("notas.txt", "text/plain", 10));
    expect(screen.queryAllByTestId("bugreport-attachment")).toHaveLength(0);
    expect(screen.getByRole("alert")).toHaveTextContent(
      tEs("profile.bugreport.attachmentType"),
    );
  });

  it("keeps submit disabled until the preview is rendered (mandatory gate)", async () => {
    const user = await renderReady();

    const submit = screen.getByRole("button", {
      name: tEs("profile.bugreport.submit"),
    });
    // No preview yet → the exact bundle has not been shown → submission blocked.
    expect(submit).toBeDisabled();
    expect(screen.queryByTestId("bugreport-preview")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.preview") }),
    );

    expect(screen.getByTestId("bugreport-preview")).toBeInTheDocument();
    expect(submit).toBeEnabled();

    // Editing after the preview invalidates it: the submitted payload must be
    // exactly what was shown, so submit re-locks until the user previews again.
    await user.type(
      screen.getByLabelText(tEs("profile.bugreport.descriptionLabel")),
      "changed",
    );
    expect(submit).toBeDisabled();
    expect(screen.queryByTestId("bugreport-preview")).not.toBeInTheDocument();
  });

  it("reflects the edited description and removed logs in the submitted payload", async () => {
    const user = await renderReady();

    await user.type(
      screen.getByLabelText(tEs("profile.bugreport.descriptionLabel")),
      "It crashed on save",
    );
    // Logs are default-on; removing them must drop the field entirely.
    await user.click(screen.getByLabelText(tEs("profile.bugreport.includeLogs")));
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.preview") }),
    );

    (submitBugReport as Mock).mockResolvedValue({ ok: true, delivery_id: "d-1" });
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.submit") }),
    );

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledTimes(1));
    const payload = (submitBugReport as Mock).mock.calls[0][0];
    expect(payload.description).toBe("It crashed on save");
    expect(payload).not.toHaveProperty("logs");
    expect(payload.app_version).toBe("0.2.0");
  });

  it("includes a provided contact in the submitted payload", async () => {
    const user = await renderReady();

    await user.type(
      screen.getByLabelText(tEs("profile.bugreport.contactLabel")),
      "dev@example.com",
    );
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.preview") }),
    );
    (submitBugReport as Mock).mockResolvedValue({ ok: true, delivery_id: "d-5" });
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.submit") }),
    );

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledTimes(1));
    expect((submitBugReport as Mock).mock.calls[0][0].contact).toBe(
      "dev@example.com",
    );
  });

  it("omits the contact field entirely when the user leaves it empty", async () => {
    const user = await renderReady();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.preview") }),
    );
    (submitBugReport as Mock).mockResolvedValue({ ok: true, delivery_id: "d-6" });
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.submit") }),
    );

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledTimes(1));
    // The spec: an empty contact is OMITTED, never serialized as "".
    expect((submitBugReport as Mock).mock.calls[0][0]).not.toHaveProperty(
      "contact",
    );
  });

  it("shows the success feedback and hides the fallback when delivery succeeds", async () => {
    const user = await renderReady();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.preview") }),
    );
    (submitBugReport as Mock).mockResolvedValue({ ok: true, delivery_id: "d-2" });
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.submit") }),
    );

    await screen.findByText(tEs("profile.bugreport.submitSuccess"));
    expect(screen.queryByTestId("bugreport-fallback")).not.toBeInTheDocument();
  });

  it("shows the copy-paste fallback and issue link when delivery fails", async () => {
    const user = await renderReady();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.preview") }),
    );
    (submitBugReport as Mock).mockRejectedValue(
      new ApiError(502, "relay down", undefined, "bugreport.relay_unavailable"),
    );
    (fallbackBody as Mock).mockResolvedValue({
      body: "scrubbed issue body",
      issue_url:
        "https://github.com/maar1223/Demiurgos/issues/new?template=bug_report.yml",
      findings: 2,
    });
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.submit") }),
    );

    await screen.findByTestId("bugreport-fallback");
    expect(screen.getByTestId("bugreport-fallback-body")).toHaveValue(
      "scrubbed issue body",
    );
    expect(screen.getByTestId("bugreport-fallback-link")).toHaveAttribute(
      "href",
      "https://github.com/maar1223/Demiurgos/issues/new?template=bug_report.yml",
    );
    expect(fallbackBody).toHaveBeenCalledTimes(1);
    // The failed delivery still surfaces a localized, non-secret error code.
    expect(screen.getByRole("alert")).toHaveTextContent(
      tEs("error.bugreport.relay_unavailable"),
    );
  });

  it("offers the fallback strictly on failure, never alongside a success", async () => {
    const user = await renderReady();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.preview") }),
    );
    (submitBugReport as Mock).mockResolvedValue({ ok: true, delivery_id: "d-3" });
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.submit") }),
    );

    await screen.findByText(tEs("profile.bugreport.submitSuccess"));
    // Strict fallback: a successful delivery never prepares or shows it.
    expect(fallbackBody).not.toHaveBeenCalled();
    expect(screen.queryByTestId("bugreport-fallback")).not.toBeInTheDocument();
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
    expect(tabs).toHaveLength(8);
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