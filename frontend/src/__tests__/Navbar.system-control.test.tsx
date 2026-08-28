import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Navbar } from "@/components/organisms/Navbar";
import { ApiError } from "@/api/types";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import { systemControlAction } from "@/api/wiki";
import type { Mock } from "vitest";

vi.mock("@/hooks/useLocalDevAuth", () => ({
  useLocalDevAuth: vi.fn(),
}));

vi.mock("@/api/wiki", () => ({
  systemControlAction: vi.fn(),
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
    (systemControlAction as Mock).mockResolvedValue({ action: "restart", accepted: true });
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

  it("renders both system-control buttons when local auth is enabled", async () => {
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

    // Busy: both actions disabled while logout + POST are pending.
    expect(
      within(dialog).getByRole("button", { name: "Reiniciar" }),
    ).toBeDisabled();
    expect(
      within(dialog).getByRole("button", { name: "Cancelar" }),
    ).toBeDisabled();

    resolveFetch({ action: "restart", accepted: true });
    expect(
      await screen.findByText(/Demiurgos se está reiniciando/i),
    ).toBeInTheDocument();
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

    // The in-flight operation resolves afterwards without crashing or
    // leaving the dialog stuck.
    resolveFetch({ action: "restart", accepted: true });
    expect(
      await screen.findByText(/Demiurgos se está reiniciando/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: /reiniciar demiurgos/i }),
    ).not.toBeInTheDocument();
  });

  it("calls logout BEFORE the system POST (S-3.4)", async () => {
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

    expect(logout).toHaveBeenCalledTimes(1);
    expect(systemControlAction).toHaveBeenCalledWith("restart");
    // Ordering guarantee: the DELETE session resolves before the POST.
    expect(logout.mock.invocationCallOrder[0]).toBeLessThan(
      (systemControlAction as Mock).mock.invocationCallOrder[0],
    );
  });

  it("does NOT POST when logout fails (fail-closed ordering)", async () => {
    const logout = vi.fn().mockRejectedValue(new Error("No se pudo cerrar la sesión"));
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

    expect(await screen.findByText("No se pudo cerrar la sesión")).toBeInTheDocument();
    expect(systemControlAction).not.toHaveBeenCalled();
  });

  it("shows the connection-lost message when the POST fails with a network error (S-3.6)", async () => {
    (systemControlAction as Mock).mockRejectedValue(
      new ApiError(0, "No se pudo conectar al servidor. Verificá que esté corriendo."),
    );
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);
    await user.click(screen.getByRole("button", { name: "Reiniciar Demiurgos" }));

    const dialog = screen.getByRole("dialog", { name: /reiniciar demiurgos/i });
    await user.click(within(dialog).getByRole("button", { name: "Reiniciar" }));

    expect(
      await screen.findByText(/Se perdió la conexión mientras se reiniciaba/i),
    ).toBeInTheDocument();
    // The dialog stays open so the user sees the failure and can retry/close.
    expect(
      screen.getByRole("dialog", { name: /reiniciar demiurgos/i }),
    ).toBeInTheDocument();
  });

  it("instructs re-authentication after a successful restart (S-3.7)", async () => {
    const user = userEvent.setup();
    renderNavbar();
    await openProfile(user);
    await user.click(screen.getByRole("button", { name: "Reiniciar Demiurgos" }));

    const dialog = screen.getByRole("dialog", { name: /reiniciar demiurgos/i });
    await user.click(within(dialog).getByRole("button", { name: "Reiniciar" }));

    expect(
      await screen.findByText(/Iniciá sesión nuevamente cuando vuelva/i),
    ).toBeInTheDocument();
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
      await screen.findByText(/Iniciá sesión nuevamente cuando lo vuelvas a iniciar/i),
    ).toBeInTheDocument();
  });
});