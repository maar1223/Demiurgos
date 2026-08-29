import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Navbar } from "@/components/organisms/Navbar";
import { ApiError } from "@/api/types";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import { getAuthStatus, logoutSession, systemControlAction } from "@/api/wiki";
import { reloadPage } from "@/lib/reloadPage";
import type { Mock } from "vitest";

vi.mock("@/hooks/useLocalDevAuth", () => ({
  useLocalDevAuth: vi.fn(),
}));

vi.mock("@/api/wiki", () => ({
  getAuthStatus: vi.fn(),
  logoutSession: vi.fn(),
  systemControlAction: vi.fn(),
}));

vi.mock("@/lib/reloadPage", () => ({
  reloadPage: vi.fn(),
}));

const enabledStatus = {
  mode: "local-dev",
  enabled: true,
  authenticated: true,
  label: "Local development user",
};

const loggedOutStatus = { ...enabledStatus, authenticated: false };

function renderNavbar() {
  return render(
    <MemoryRouter initialEntries={["/start"]}>
      <Navbar worlds={[]} />
      <Routes>
        <Route path="*" element={<div data-testid="path">/start</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

async function openProfile(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Perfil" }));
}

describe("Navbar system-control zone", () => {
  beforeEach(() => {
    (useLocalDevAuth as Mock).mockReturnValue({
      status: { ...enabledStatus },
      isLoading: false,
      error: null,
      start: vi.fn(),
      logout: vi.fn().mockResolvedValue(loggedOutStatus),
    });
    (getAuthStatus as Mock).mockResolvedValue({
      mode: "local-dev",
      enabled: true,
      authenticated: false,
      label: null,
    });
    (logoutSession as Mock).mockResolvedValue(loggedOutStatus);
    (systemControlAction as Mock).mockResolvedValue({ action: "restart", accepted: true });
    (reloadPage as Mock).mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("hides the system-control zone when local auth is disabled (S-3.1)", async () => {
    (useLocalDevAuth as Mock).mockReturnValue({
      status: { mode: "disabled", enabled: false, authenticated: false, label: null },
      isLoading: false,
      error: null,
      start: vi.fn(),
      logout: vi.fn(),
    });
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);

    expect(screen.getByRole("dialog", { name: "Perfil" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reiniciar Demiurgos" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Apagar Demiurgos" }),
    ).not.toBeInTheDocument();
  });

  it("renders both system-control buttons when an active session exists", async () => {
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);

    expect(
      screen.getByRole("button", { name: "Reiniciar Demiurgos" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Apagar Demiurgos" }),
    ).toBeInTheDocument();
  });

  it("hides the system-control zone when logged out (auth enabled, no session)", async () => {
    (useLocalDevAuth as Mock).mockReturnValue({
      status: { ...loggedOutStatus },
      isLoading: false,
      error: null,
      start: vi.fn(),
      logout: vi.fn(),
    });
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);

    expect(screen.getByRole("dialog", { name: "Perfil" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reiniciar Demiurgos" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Apagar Demiurgos" }),
    ).not.toBeInTheDocument();
  });

  it("opens the ConfirmDialog when a system button is clicked (S-3.2)", async () => {
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);
    await user.click(screen.getByRole("button", { name: "Reiniciar Demiurgos" }));

    const dialog = screen.getByRole("dialog", { name: /reiniciar demiurgos/i });
    expect(
      within(dialog).getByRole("button", { name: "Reiniciar" }),
    ).toBeInTheDocument();
  });

  it("cancel closes the dialog without calling the API", async () => {
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);
    await user.click(screen.getByRole("button", { name: "Reiniciar Demiurgos" }));

    const dialog = screen.getByRole("dialog", { name: /reiniciar demiurgos/i });
    await user.click(within(dialog).getByRole("button", { name: "Cancelar" }));

    expect(
      screen.queryByRole("dialog", { name: /reiniciar demiurgos/i }),
    ).not.toBeInTheDocument();
    expect(systemControlAction).not.toHaveBeenCalled();
  });

  it("shows the busy state while the operation is in flight (S-3.3)", async () => {
    let resolveFetch!: (value: unknown) => void;
    (systemControlAction as Mock).mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);
    await user.click(screen.getByRole("button", { name: "Reiniciar Demiurgos" }));

    const dialog = screen.getByRole("dialog", { name: /reiniciar demiurgos/i });
    await user.click(within(dialog).getByRole("button", { name: "Reiniciar" }));

    // Busy: both actions disabled while the POST is pending.
    expect(
      within(dialog).getByRole("button", { name: "Reiniciar" }),
    ).toBeDisabled();
    expect(
      within(dialog).getByRole("button", { name: "Cancelar" }),
    ).toBeDisabled();

    resolveFetch({ action: "restart", accepted: true });
    // On success the dialog closes and the full-screen restart overlay shows.
    expect(
      await screen.findByText(/Reiniciando Demiurgos/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: /reiniciar demiurgos/i }),
    ).not.toBeInTheDocument();
  });

  it("closing mid-operation stops the busy state (no stuck dialog)", async () => {
    let resolveFetch!: (value: unknown) => void;
    (systemControlAction as Mock).mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);
    await user.click(screen.getByRole("button", { name: "Reiniciar Demiurgos" }));

    let dialog = screen.getByRole("dialog", { name: /reiniciar demiurgos/i });
    await user.click(within(dialog).getByRole("button", { name: "Reiniciar" }));
    expect(
      within(dialog).getByRole("button", { name: "Reiniciar" }),
    ).toBeDisabled();

    // The X (close) stays enabled while busy — closing must reset the state.
    await user.click(within(dialog).getByRole("button", { name: "Cerrar" }));
    expect(
      screen.queryByRole("dialog", { name: /reiniciar demiurgos/i }),
    ).not.toBeInTheDocument();

    // Resolving afterwards must not resurrect the dialog.
    resolveFetch({ action: "restart", accepted: true });
    expect(
      screen.queryByRole("dialog", { name: /reiniciar demiurgos/i }),
    ).not.toBeInTheDocument();
  });

  it("dispatches the system POST directly without logging out first (S-3.4)", async () => {
    const logout = vi.fn().mockResolvedValue(loggedOutStatus);
    (useLocalDevAuth as Mock).mockReturnValue({
      status: { ...enabledStatus },
      isLoading: false,
      error: null,
      start: vi.fn(),
      logout,
    });
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);
    await user.click(screen.getByRole("button", { name: "Reiniciar Demiurgos" }));

    const dialog = screen.getByRole("dialog", { name: /reiniciar demiurgos/i });
    await user.click(within(dialog).getByRole("button", { name: "Reiniciar" }));

    expect(systemControlAction).toHaveBeenCalledWith("restart");
    // The POST is dispatched while the cookie is still valid — no logout is
    // performed beforehand (that would drop the auth and 401 the endpoint).
    expect(logout).not.toHaveBeenCalled();
  });

  it("surfaces a 401 (autenticación requerida) instead of logging the user out", async () => {
    (systemControlAction as Mock).mockRejectedValue(
      new ApiError(401, "Autenticación requerida"),
    );
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);
    await user.click(screen.getByRole("button", { name: "Reiniciar Demiurgos" }));

    const dialog = screen.getByRole("dialog", { name: /reiniciar demiurgos/i });
    await user.click(within(dialog).getByRole("button", { name: "Reiniciar" }));

    expect(
      await screen.findByText("Autenticación requerida"),
    ).toBeInTheDocument();
    // A real auth error keeps the dialog open so the user can retry/close.
    expect(
      screen.getByRole("dialog", { name: /reiniciar demiurgos/i }),
    ).toBeInTheDocument();
  });

  it("treats a dropped connection on restart as success (overlay)", async () => {
    (systemControlAction as Mock).mockRejectedValue(
      new ApiError(0, "connection dropped"),
    );
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);
    await user.click(screen.getByRole("button", { name: "Reiniciar Demiurgos" }));

    const dialog = screen.getByRole("dialog", { name: /reiniciar demiurgos/i });
    await user.click(within(dialog).getByRole("button", { name: "Reiniciar" }));

    // A dropped connection means the launcher killed uvicorn = expected. The
    // dialog closes and the restart overlay shows (no error).
    expect(
      await screen.findByText(/Reiniciando Demiurgos/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: /reiniciar demiurgos/i }),
    ).not.toBeInTheDocument();
  });

  it("auto-reloads the page when the server is back after a restart (S-3.7)", async () => {
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);
    await user.click(screen.getByRole("button", { name: "Reiniciar Demiurgos" }));

    const dialog = screen.getByRole("dialog", { name: /reiniciar demiurgos/i });
    await user.click(within(dialog).getByRole("button", { name: "Reiniciar" }));

    // Overlay shows while the server restarts; the polling effect detects the
    // backend is back (getAuthStatus resolves) and reloads the page.
    expect(
      await screen.findByText(/Reiniciando Demiurgos/i),
    ).toBeInTheDocument();
    await waitFor(() => expect(reloadPage).toHaveBeenCalled(), { timeout: 5000 });
    expect(
      screen.queryByRole("dialog", { name: /reiniciar demiurgos/i }),
    ).not.toBeInTheDocument();
  });

  it("shutdown opens its own dialog and dispatches the shutdown action", async () => {
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);
    await user.click(screen.getByRole("button", { name: "Apagar Demiurgos" }));

    const dialog = screen.getByRole("dialog", { name: /apagar demiurgos/i });
    await user.click(within(dialog).getByRole("button", { name: "Apagar" }));

    expect(systemControlAction).toHaveBeenCalledWith("shutdown");
    expect(
      await screen.findByText(/Apagando Demiurgos/i),
    ).toBeInTheDocument();
  });
});