import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UpdateSection } from "@/components/organisms/UpdateSection";
import {
  applyUpdate,
  getUpdateStatus,
  setUpdateChannel,
} from "@/api/updates";
import { apiFetch } from "@/api/client";
import { getAppConfig } from "@/api/config";
import { getAuthStatus, logoutSession } from "@/api/wiki";
import { reloadPage } from "@/lib/reloadPage";
import { ApiError } from "@/api/types";
import type { Mock } from "vitest";

vi.mock("@/api/updates", () => ({
  getUpdateStatus: vi.fn(),
  setUpdateChannel: vi.fn(),
  applyUpdate: vi.fn(),
}));

vi.mock("@/api/config", () => ({
  getAppConfig: vi.fn(),
}));

vi.mock("@/api/wiki", () => ({
  getAuthStatus: vi.fn(),
  logoutSession: vi.fn(),
}));

vi.mock("@/lib/reloadPage", () => ({
  reloadPage: vi.fn(),
}));

// Only used by the API-contract test below (real applyUpdate via importActual).
vi.mock("@/api/client", () => ({
  apiFetch: vi.fn(),
}));

const baseStatus = {
  current_version: "0.2.0",
  channel: "Beta" as const,
  url_base: "https://example.test/channel",
  latest: "0.2.1",
  update_available: true,
  advisory_unavailable: false,
};

// The panel is manual-only (spec: "Read-only frontend update panel"): nothing
// is fetched on mount and nothing polls. These tests pin that contract, plus
// the Slice 3 apply flow (ConfirmDialog required, logout-first, long timeout).
describe("UpdateSection — Perfil → Actualizaciones", () => {
  beforeEach(() => {
    (getUpdateStatus as Mock).mockReset();
    (setUpdateChannel as Mock).mockReset();
    (applyUpdate as Mock).mockReset();
    (logoutSession as Mock).mockReset();
    (getAuthStatus as Mock).mockReset();
    (apiFetch as Mock).mockReset();
    (getAppConfig as Mock).mockReset();
    (getAppConfig as Mock).mockResolvedValue({
      language: "es",
      app_version: "0.1.1",
    });
    (logoutSession as Mock).mockResolvedValue({
      mode: "local-dev",
      enabled: true,
      authenticated: false,
      label: null,
    });
    (applyUpdate as Mock).mockResolvedValue({
      action: "update",
      accepted: true,
      version: "0.2.1",
    });
    (getAuthStatus as Mock).mockResolvedValue({
      mode: "local-dev",
      enabled: true,
      authenticated: false,
      label: null,
    });
    (reloadPage as Mock).mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("issues no update check on mount (manual-only); reads app config once", async () => {
    render(<UpdateSection />);
    // Give any accidental effect / microtask a chance to fire.
    await new Promise((resolve) => setTimeout(resolve, 20));
    // The update check and the channel write are never triggered on mount...
    expect(getUpdateStatus).not.toHaveBeenCalled();
    expect(setUpdateChannel).not.toHaveBeenCalled();
    // ...but the running version comes from a single app-metadata read.
    expect(getAppConfig).toHaveBeenCalledTimes(1);
  });

  it("shows the running version from config on render, channel after the check", async () => {
    (getUpdateStatus as Mock).mockResolvedValue(baseStatus);
    const user = userEvent.setup();
    render(<UpdateSection />);

    // On render the running version comes from app metadata (spec scenario
    // "Panel displays current version") — no update check needed yet.
    await waitFor(() =>
      expect(screen.getByTestId("update-current-version")).toHaveTextContent(
        "0.1.1",
      ),
    );
    // The channel is server-owned: it starts at the documented default until a
    // check reports the selected channel.
    expect(screen.getByTestId("update-channel-value")).toHaveTextContent(
      "Estable",
    );
    expect(getUpdateStatus).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("button", { name: "Buscar actualizaciones" }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("update-current-version")).toHaveTextContent(
        "0.2.0",
      ),
    );
    expect(screen.getByTestId("update-channel-value")).toHaveTextContent("Beta");
    expect(getUpdateStatus).toHaveBeenCalledTimes(1);
  });

  it("fetches once per explicit click and never in the background", async () => {
    (getUpdateStatus as Mock).mockResolvedValue(baseStatus);
    const user = userEvent.setup();
    render(<UpdateSection />);

    expect(getUpdateStatus).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: "Buscar actualizaciones" }),
    );
    await waitFor(() => expect(getUpdateStatus).toHaveBeenCalledTimes(1));
    // Still exactly one request once the response settles — no timer/poll.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(getUpdateStatus).toHaveBeenCalledTimes(1);
  });

  it("switching the channel PUTs the new value and reflects it", async () => {
    (setUpdateChannel as Mock).mockResolvedValue({ channel: "Beta" });
    const user = userEvent.setup();
    render(<UpdateSection />);

    expect(screen.getByRole("radio", { name: "Estable" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.click(screen.getByRole("radio", { name: "Beta" }));

    expect(setUpdateChannel).toHaveBeenCalledWith("Beta");
    await waitFor(() =>
      expect(screen.getByTestId("update-channel-value")).toHaveTextContent(
        "Beta",
      ),
    );
    expect(screen.getByRole("radio", { name: "Beta" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("reverts the channel and surfaces an error when the PUT is rejected", async () => {
    (setUpdateChannel as Mock).mockRejectedValue(new ApiError(400, "invalid"));
    const user = userEvent.setup();
    render(<UpdateSection />);

    await user.click(screen.getByRole("radio", { name: "Beta" }));

    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Estable" })).toHaveAttribute(
        "aria-checked",
        "true",
      ),
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("reports an unavailable advisory without fabricating a version", async () => {
    (getUpdateStatus as Mock).mockResolvedValue({
      ...baseStatus,
      latest: null,
      update_available: false,
      advisory_unavailable: true,
    });
    const user = userEvent.setup();
    render(<UpdateSection />);

    await user.click(
      screen.getByRole("button", { name: "Buscar actualizaciones" }),
    );

    expect(
      await screen.findByText(/No se pudo consultar el canal/),
    ).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Slice 3 — apply flow (spec: confirmation required, logout-first, 90s)
  // -------------------------------------------------------------------------

  /** Run a manual check that ends with an update available. */
  async function checkForUpdate(user: ReturnType<typeof userEvent.setup>) {
    await user.click(
      screen.getByRole("button", { name: "Buscar actualizaciones" }),
    );
    await screen.findByText(/Hay una actualización disponible/);
  }

  it("applies only after the ConfirmDialog is confirmed (spec scenario)", async () => {
    (getUpdateStatus as Mock).mockResolvedValue(baseStatus);
    const user = userEvent.setup();
    render(<UpdateSection />);
    await checkForUpdate(user);

    // Clicking "Instalar y reiniciar" opens the dialog but dispatches NOTHING.
    await user.click(screen.getByRole("button", { name: "Instalar y reiniciar" }));
    const dialog = screen.getByRole("dialog", {
      name: /instalar actualización/i,
    });
    expect(
      within(dialog).getByRole("button", { name: "Instalar y reiniciar" }),
    ).toBeInTheDocument();
    expect(applyUpdate).not.toHaveBeenCalled();
    expect(logoutSession).not.toHaveBeenCalled();

    // Cancelling closes the dialog and still dispatches nothing.
    await user.click(within(dialog).getByRole("button", { name: "Cancelar" }));
    expect(
      screen.queryByRole("dialog", { name: /instalar actualización/i }),
    ).not.toBeInTheDocument();
    expect(applyUpdate).not.toHaveBeenCalled();

    // Confirming dispatches: logout first, then the apply POST.
    await user.click(screen.getByRole("button", { name: "Instalar y reiniciar" }));
    await user.click(
      within(
        screen.getByRole("dialog", { name: /instalar actualización/i }),
      ).getByRole("button", { name: "Instalar y reiniciar" }),
    );
    await waitFor(() => expect(logoutSession).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(applyUpdate).toHaveBeenCalledTimes(1));
    // The full-screen installing overlay shows once the dispatch is accepted.
    expect(await screen.findByText(/Instalando actualización/)).toBeInTheDocument();
  });

  it("never dispatches the apply before the local session logout resolves (logout-first)", async () => {
    (getUpdateStatus as Mock).mockResolvedValue(baseStatus);
    let releaseLogout!: (value: unknown) => void;
    (logoutSession as Mock).mockReturnValue(
      new Promise((resolve) => {
        releaseLogout = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<UpdateSection />);
    await checkForUpdate(user);

    await user.click(screen.getByRole("button", { name: "Instalar y reiniciar" }));
    await user.click(
      within(
        screen.getByRole("dialog", { name: /instalar actualización/i }),
      ).getByRole("button", { name: "Instalar y reiniciar" }),
    );

    // While the logout is pending, the apply MUST NOT be dispatched — the
    // session is closed BEFORE the installer is ever told to run.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(logoutSession).toHaveBeenCalledTimes(1);
    expect(applyUpdate).not.toHaveBeenCalled();

    releaseLogout({
      mode: "local-dev",
      enabled: true,
      authenticated: false,
      label: null,
    });
    await waitFor(() => expect(applyUpdate).toHaveBeenCalledTimes(1));
    // Strict ordering: the logout call happened before the apply dispatch.
    expect((logoutSession as Mock).mock.invocationCallOrder[0]).toBeLessThan(
      (applyUpdate as Mock).mock.invocationCallOrder[0],
    );
  });

  it("shows an apply failure in the dialog and dispatches nothing", async () => {
    (getUpdateStatus as Mock).mockResolvedValue(baseStatus);
    (applyUpdate as Mock).mockRejectedValue(
      new ApiError(500, "early installer failure", "update.apply_failed"),
    );
    const user = userEvent.setup();
    render(<UpdateSection />);
    await checkForUpdate(user);

    await user.click(screen.getByRole("button", { name: "Instalar y reiniciar" }));
    await user.click(
      within(
        screen.getByRole("dialog", { name: /instalar actualización/i }),
      ).getByRole("button", { name: "Instalar y reiniciar" }),
    );

    // The 500 keeps the dialog open with the failure surfaced (retryable).
    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent(/Error interno del servidor/);
    expect(
      screen.getByRole("dialog", { name: /instalar actualización/i }),
    ).toBeInTheDocument();
  });

  it("treats a dropped connection during apply as accepted (overlay)", async () => {
    (getUpdateStatus as Mock).mockResolvedValue(baseStatus);
    (applyUpdate as Mock).mockRejectedValue(
      new ApiError(0, "fetch failed", "network.timeout"),
    );
    const user = userEvent.setup();
    render(<UpdateSection />);
    await checkForUpdate(user);

    await user.click(screen.getByRole("button", { name: "Instalar y reiniciar" }));
    await user.click(
      within(
        screen.getByRole("dialog", { name: /instalar actualización/i }),
      ).getByRole("button", { name: "Instalar y reiniciar" }),
    );

    // The installer killed the backend mid-dispatch: the connection drop is
    // the EXPECTED outcome, so the transition overlay shows instead of an error.
    expect(
      await screen.findByText(/Instalando actualización/),
    ).toBeInTheDocument();
  });

  it("posts the apply with the long 90s install timeout (API contract)", async () => {
    const realUpdates = await vi.importActual<
      typeof import("@/api/updates")
    >("@/api/updates");
    (apiFetch as Mock).mockResolvedValue({
      action: "update",
      accepted: true,
      version: "0.2.1",
    });

    const result = await realUpdates.applyUpdate();

    expect(result).toEqual({ action: "update", accepted: true, version: "0.2.1" });
    expect(apiFetch).toHaveBeenCalledWith("/api/update/apply", {
      method: "POST",
      credentials: "same-origin",
      timeout: 90_000,
    });
  });
});
