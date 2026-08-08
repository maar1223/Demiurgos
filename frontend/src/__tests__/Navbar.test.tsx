import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { Navbar } from "@/components/organisms/Navbar";
import {
  NAV_LINKS,
  PLACEHOLDER_TOAST,
} from "@/lib/constants";
import type { WorldInfo } from "@/api/types";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import type { Mock } from "vitest";

vi.mock("@/hooks/useLocalDevAuth", () => ({
  useLocalDevAuth: vi.fn(),
}));

const worlds: WorldInfo[] = [
  {
    name: "Vibrantes",
    path: "/vibrantes",
    lore_count: 77,
    character_count: 10,
    saga_count: 4,
  },
];

/** Probe that reports the current router path. */
function LocationProbe() {
  const { pathname } = useLocation();
  return <div data-testid="path">{pathname}</div>;
}

interface NavbarTestProps {
  worlds?: WorldInfo[];
  currentWorld?: string;
  onWorldChange?: (world: string) => void;
}

function renderNavbar(
  props: NavbarTestProps = {},
  initialEntry = "/start",
) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Navbar
        worlds={props.worlds ?? []}
        currentWorld={props.currentWorld}
        onWorldChange={props.onWorldChange}
      />
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** The mobile-menu-toggle is the only unnamed button when the menu is closed. */
function unnamedButtons() {
  return screen.getAllByRole("button");
}

describe("Navbar", () => {
  beforeEach(() => {
    vi.spyOn(window, "alert").mockImplementation(() => {});
    (useLocalDevAuth as Mock).mockReturnValue({
      status: {
        mode: "disabled",
        enabled: false,
        authenticated: false,
        label: null,
      },
      isLoading: false,
      error: null,
      start: vi.fn(),
      logout: vi.fn(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the brand, every nav link, world selector, and avatar", () => {
    renderNavbar({ worlds });

    expect(screen.getByText("Demiurgos")).toBeInTheDocument();
    for (const link of NAV_LINKS) {
      expect(
        screen.getByRole("button", { name: link.label }),
      ).toBeInTheDocument();
    }
    // No current world → the selector shows the fallback label
    expect(screen.getByRole("button", { name: "Mundos" })).toBeInTheDocument();
  });

  it("shows the current world name in the world selector", () => {
    renderNavbar({ worlds, currentWorld: "Vibrantes" });

    expect(
      screen.getByRole("button", { name: "Vibrantes" }),
    ).toBeInTheDocument();
  });

  it("inactive nav links show the placeholder alert and do NOT navigate", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    await user.click(screen.getByRole("button", { name: "Personajes" }));

    expect(window.alert).toHaveBeenCalledWith(PLACEHOLDER_TOAST);
    expect(screen.getByTestId("path")).toHaveTextContent("/start");
  });

  it("the active Wiki link navigates to /wiki", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    await user.click(screen.getByRole("button", { name: "Wiki" }));

    expect(screen.getByTestId("path")).toHaveTextContent("/wiki");
    expect(window.alert).not.toHaveBeenCalled();
  });

  it("clicking the logo navigates to /wiki", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds }, "/wiki/Vibrantes/lore");

    await user.click(screen.getByText("Demiurgos"));

    expect(screen.getByTestId("path")).toHaveTextContent("/wiki");
  });

  it("clicking the avatar opens the local session control", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    await user.click(screen.getByRole("button", { name: "Perfil" }));

    expect(screen.getByRole("dialog", { name: "Perfil" })).toBeInTheDocument();
    expect(screen.getByText(/Autenticación local desactivada/i)).toBeInTheDocument();
  });

  it("starts the explicit local session from the profile control", async () => {
    const user = userEvent.setup();
    const start = vi.fn().mockResolvedValue({
      mode: "local-dev",
      enabled: true,
      authenticated: true,
      label: "Local development user",
    });
    (useLocalDevAuth as Mock).mockReturnValue({
      status: {
        mode: "local-dev",
        enabled: true,
        authenticated: false,
        label: null,
      },
      isLoading: false,
      error: null,
      start,
      logout: vi.fn(),
    });

    renderNavbar({ worlds });
    await user.click(screen.getByRole("button", { name: "Perfil" }));
    await user.click(screen.getByRole("button", { name: "Iniciar sesión local" }));

    expect(start).toHaveBeenCalledOnce();
  });

  it("world selector opens and reports the selection via onWorldChange", async () => {
    const user = userEvent.setup();
    const onWorldChange = vi.fn();
    renderNavbar({ worlds, onWorldChange });

    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("option", { name: "Vibrantes" }));

    expect(onWorldChange).toHaveBeenCalledWith("Vibrantes");
    // Dropdown closed after selection
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("world selector falls back to navigation when onWorldChange is omitted", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("option", { name: "Vibrantes" }));

    expect(screen.getByTestId("path")).toHaveTextContent(
      "/wiki/Vibrantes/lore",
    );
  });

  it("shows 'No hay mundos' when the world list is empty", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds: [] });

    await user.click(screen.getByRole("button", { name: "Mundos" }));

    expect(screen.getByText("No hay mundos")).toBeInTheDocument();
  });

  it("mobile toggle opens the nav menu (links duplicated)", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    const buttons = unnamedButtons();
    await user.click(buttons[buttons.length - 1]);

    // Desktop nav + mobile menu
    expect(
      screen.getAllByRole("button", { name: "Revisar" }),
    ).toHaveLength(2);
  });

  it("mobile active link navigates and closes the menu", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    const buttons = unnamedButtons();
    await user.click(buttons[buttons.length - 1]);
    await user.click(screen.getAllByRole("button", { name: "Wiki" })[1]);

    expect(screen.getByTestId("path")).toHaveTextContent("/wiki");
    // Menu closed → only the desktop nav link remains
    expect(
      screen.getAllByRole("button", { name: "Revisar" }),
    ).toHaveLength(1);
  });

  it("mobile inactive link alerts and keeps the menu open", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    const buttons = unnamedButtons();
    await user.click(buttons[buttons.length - 1]);
    await user.click(screen.getAllByRole("button", { name: "Personajes" })[1]);

    expect(window.alert).toHaveBeenCalledWith(PLACEHOLDER_TOAST);
    // handleNavClick returns before closing the menu for inactive links
    expect(
      screen.getAllByRole("button", { name: "Personajes" }),
    ).toHaveLength(2);
  });
});
