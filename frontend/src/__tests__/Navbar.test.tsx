import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { Navbar } from "@/components/organisms/Navbar";
import {
  NAV_LINKS,
  PLACEHOLDER_TOAST,
} from "@/lib/constants";
import { ACTIVE_WORLD_STORAGE_KEY } from "@/lib/currentWorld";
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
    character_count: 10, reference_count: 0,
  },
  {
    name: "Sombras",
    path: "/sombras",
    lore_count: 5,
    character_count: 0, reference_count: 0,
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

// Core-only workshop contract: only Taller de Mundo / Taller de Herramientas
// are available; everything else is a non-actionable "Próximamente" teaser.
const availableLinks = NAV_LINKS.filter(
  (link) => link.availability === "available",
);
const teaserLinks = NAV_LINKS.filter(
  (link) => link.availability === "teaser",
);

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

  it("makes every available Core nav link navigate to its workshop", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    for (const link of availableLinks) {
      await user.click(screen.getByRole("button", { name: link.label }));
      expect(screen.getByTestId("path")).toHaveTextContent(link.to);
    }
  });

  it("keeps the generic teaser non-actionable: alert and no navigation", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    expect(teaserLinks.length).toBe(1);
    await user.click(screen.getByRole("button", { name: "Próximamente" }));

    expect(window.alert).toHaveBeenCalledWith(PLACEHOLDER_TOAST);
    expect(screen.getByTestId("path")).toHaveTextContent("/start");
  });

  it("shows exactly one non-actionable Próximamente teaser next to the Core workshops", () => {
    renderNavbar({ worlds });

    expect(
      screen.getAllByRole("button", { name: "Próximamente" }),
    ).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Taller de Mundo" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Taller de Herramientas" }),
    ).toBeInTheDocument();
  });

  it("places Taller de Ideas between Taller de Herramientas and Taller de Mundo", () => {
    const availableLabels = NAV_LINKS.filter(
      (link) => link.availability === "available",
    ).map((link) => link.label);
    expect(availableLabels).toEqual([
      "Taller de Herramientas",
      "Taller de Ideas",
      "Taller de Mundo",
    ]);

    renderNavbar({ worlds });

    // DOM order mirrors NAV_LINKS order: the ideas entry renders between the
    // two existing workshops in the desktop nav.
    const herramientas = screen.getByRole("button", { name: "Taller de Herramientas" });
    const ideas = screen.getByRole("button", { name: "Taller de Ideas" });
    const mundo = screen.getByRole("button", { name: "Taller de Mundo" });
    expect(
      herramientas.compareDocumentPosition(ideas) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      ideas.compareDocumentPosition(mundo) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("hides legacy narrative phases and Taller de Publicación while unavailable", () => {
    renderNavbar({ worlds });

    for (const label of [
      "Personajes",
      "Escritura",
      "Planificar",
      "Revisar",
      "Taller de Publicación",
    ]) {
      expect(
        screen.queryByRole("button", { name: label }),
      ).not.toBeInTheDocument();
    }
  });

  it("shows the current world name in the world selector", () => {
    renderNavbar({ worlds, currentWorld: "Vibrantes" });

    expect(
      screen.getByRole("button", { name: "Vibrantes" }),
    ).toBeInTheDocument();
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

  it("profile dropdown links to the full profile page at /perfil", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    await user.click(screen.getByRole("button", { name: "Perfil" }));
    await user.click(screen.getByRole("button", { name: "Perfil completo" }));

    expect(screen.getByTestId("path")).toHaveTextContent("/perfil");
  });

  it("world selector opens and reports the selection via onWorldChange after confirming", async () => {
    const user = userEvent.setup();
    const onWorldChange = vi.fn();
    renderNavbar({ worlds, onWorldChange });

    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("option", { name: "Vibrantes" }));
    await user.click(screen.getByRole("button", { name: "Cambiar" }));

    expect(onWorldChange).toHaveBeenCalledWith("Vibrantes");
    // Dropdown closed after selection
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("world selector asks for confirmation and does not navigate", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("option", { name: "Vibrantes" }));

    // Confirmation before any persistence — and no navigation away
    expect(
      screen.getByRole("dialog", { name: /cambiar mundo activo/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("path")).toHaveTextContent("/start");

    await user.click(screen.getByRole("button", { name: "Cambiar" }));

    expect(localStorage.getItem(ACTIVE_WORLD_STORAGE_KEY)).toBe("Vibrantes");
    expect(screen.getByTestId("path")).toHaveTextContent("/start");
  });

  it("world selector cancel keeps the previous world and persists nothing", async () => {
    localStorage.setItem(ACTIVE_WORLD_STORAGE_KEY, "Vibrantes");
    const user = userEvent.setup();
    renderNavbar({ worlds });

    await user.click(screen.getByRole("button", { name: "Vibrantes" }));
    await user.click(screen.getByRole("option", { name: "Sombras" }));

    const dialog = screen.getByRole("dialog", { name: /cambiar mundo activo/i });
    await user.click(within(dialog).getByRole("button", { name: "Cancelar" }));

    expect(localStorage.getItem(ACTIVE_WORLD_STORAGE_KEY)).toBe("Vibrantes");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Taller de Mundo navigates to the active world when one exists", async () => {
    localStorage.setItem(ACTIVE_WORLD_STORAGE_KEY, "Vibrantes");
    const user = userEvent.setup();
    renderNavbar({ worlds });

    await user.click(screen.getByRole("button", { name: "Taller de Mundo" }));

    expect(screen.getByTestId("path")).toHaveTextContent("/wiki/Vibrantes");
  });

  it("Taller de Mundo still leads to the workshop when no world is active", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    await user.click(screen.getByRole("button", { name: "Taller de Mundo" }));

    expect(screen.getByTestId("path")).toHaveTextContent("/taller-mundo");
  });

  it("shows 'No hay mundos' when the world list is empty", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds: [] });

    await user.click(screen.getByRole("button", { name: "Mundos" }));

    expect(screen.getByText("No hay mundos")).toBeInTheDocument();
  });

  it("syncs worlds into the selector when the prop arrives after mount (F5 reload)", async () => {
    const user = userEvent.setup();
    // On a hard reload, SWR mounts with an empty list and the real worlds
    // arrive after the fetch resolves — the selector must show them (and the
    // `+ Nuevo mundo` entry), not stay frozen on the initial empty state.
    const view = renderNavbar({ worlds: [] });

    view.rerender(
      <MemoryRouter initialEntries={["/start"]}>
        <Navbar worlds={worlds} onWorldChange={undefined} />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "Mundos" }));

    expect(screen.getByRole("option", { name: "Vibrantes" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Sombras" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "+ Nuevo mundo" })).toBeInTheDocument();
  });

  it("mobile toggle opens the nav menu (links duplicated)", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    const buttons = unnamedButtons();
    await user.click(buttons[buttons.length - 1]);

    // Desktop nav + mobile menu
    expect(
      screen.getAllByRole("button", { name: "Taller de Mundo" }),
    ).toHaveLength(2);
  });

  it("mobile available link navigates and closes the menu", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    const buttons = unnamedButtons();
    await user.click(buttons[buttons.length - 1]);
    await user.click(screen.getAllByRole("button", { name: "Taller de Mundo" })[1]);

    expect(screen.getByTestId("path")).toHaveTextContent("/taller-mundo");
    // Menu closed → only the desktop nav link remains
    expect(
      screen.getAllByRole("button", { name: "Taller de Mundo" }),
    ).toHaveLength(1);
  });

  it("mobile teaser link alerts and keeps the menu open", async () => {
    const user = userEvent.setup();
    renderNavbar({ worlds });

    const buttons = unnamedButtons();
    await user.click(buttons[buttons.length - 1]);
    await user.click(screen.getAllByRole("button", { name: "Próximamente" })[1]);

    expect(window.alert).toHaveBeenCalledWith(PLACEHOLDER_TOAST);
    // handleNavClick returns before closing the menu for teaser links
    expect(
      screen.getAllByRole("button", { name: "Próximamente" }),
    ).toHaveLength(2);
  });
});
