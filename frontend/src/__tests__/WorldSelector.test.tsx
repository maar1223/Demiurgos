import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { WorldSelector } from "@/components/molecules/WorldSelector";
import { ACTIVE_WORLD_STORAGE_KEY } from "@/lib/currentWorld";
import type { WorldInfo } from "@/api/types";

const worlds: WorldInfo[] = [
  {
    name: "Vibrantes",
    path: "/vibrantes",
    lore_count: 77,
    character_count: 10,
    saga_count: 4,
  },
  {
    name: "Sombras",
    path: "/sombras",
    lore_count: 5,
    character_count: 0,
    saga_count: 3,
  },
];

/** Probe that reports the current router path. */
function LocationProbe() {
  const { pathname } = useLocation();
  return <div data-testid="path">{pathname}</div>;
}

interface SelectorTestProps {
  currentWorld?: string;
  onWorldChange?: (world: string) => void;
  onRequestCreate?: () => void;
}

function renderSelector(
  props: SelectorTestProps = {},
  worldsList: WorldInfo[] = worlds,
) {
  return render(
    <MemoryRouter initialEntries={["/wiki"]}>
      <WorldSelector worlds={worldsList} {...props} />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("WorldSelector", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("selecting a different world opens a confirmation and does not navigate", async () => {
    const user = userEvent.setup();
    renderSelector();

    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("option", { name: "Sombras" }));

    expect(
      screen.getByRole("dialog", { name: /cambiar mundo activo/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("path")).toHaveTextContent("/wiki");
  });

  it("cancel keeps the previous world and persists nothing", async () => {
    localStorage.setItem(ACTIVE_WORLD_STORAGE_KEY, "Vibrantes");
    const user = userEvent.setup();
    renderSelector({ currentWorld: "Vibrantes" });

    await user.click(screen.getByRole("button", { name: "Vibrantes" }));
    await user.click(screen.getByRole("option", { name: "Sombras" }));
    await user.click(
      within(screen.getByRole("dialog", { name: /cambiar mundo activo/i })).getByRole(
        "button",
        { name: "Cancelar" },
      ),
    );

    expect(localStorage.getItem(ACTIVE_WORLD_STORAGE_KEY)).toBe("Vibrantes");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("confirm persists the new world and notifies onWorldChange", async () => {
    const onWorldChange = vi.fn();
    const user = userEvent.setup();
    renderSelector({ onWorldChange });

    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("option", { name: "Vibrantes" }));
    await user.click(screen.getByRole("button", { name: "Cambiar" }));

    expect(localStorage.getItem(ACTIVE_WORLD_STORAGE_KEY)).toBe("Vibrantes");
    expect(onWorldChange).toHaveBeenCalledWith("Vibrantes");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("path")).toHaveTextContent("/wiki");
  });

  it("selecting the current world does nothing", async () => {
    const onWorldChange = vi.fn();
    const user = userEvent.setup();
    renderSelector({ currentWorld: "Vibrantes", onWorldChange });

    await user.click(screen.getByRole("button", { name: "Vibrantes" }));
    await user.click(screen.getByRole("option", { name: "Vibrantes" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onWorldChange).not.toHaveBeenCalled();
    expect(localStorage.getItem(ACTIVE_WORLD_STORAGE_KEY)).toBeNull();
  });

  it("reads the persisted world when no currentWorld prop is given", () => {
    localStorage.setItem(ACTIVE_WORLD_STORAGE_KEY, "Sombras");
    renderSelector();

    expect(screen.getByRole("button", { name: "Sombras" })).toBeInTheDocument();
  });

  it("renders + Nuevo mundo entry when worlds is non-empty", async () => {
    const user = userEvent.setup();
    renderSelector({ onRequestCreate: vi.fn() });

    await user.click(screen.getByRole("button", { name: "Mundos" }));

    expect(
      screen.getByRole("menuitem", { name: /nuevo mundo/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("separator")).toBeInTheDocument();
  });

  it("does NOT render + Nuevo mundo entry when worlds is empty", async () => {
    const user = userEvent.setup();
    renderSelector({ onRequestCreate: vi.fn() }, []);

    await user.click(screen.getByRole("button", { name: "Mundos" }));

    expect(
      screen.queryByRole("menuitem", { name: /nuevo mundo/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("No hay mundos")).toBeInTheDocument();
  });

  it("entry is exposed as role=menuitem, never role=option", async () => {
    const user = userEvent.setup();
    renderSelector({ onRequestCreate: vi.fn() });

    await user.click(screen.getByRole("button", { name: "Mundos" }));

    const entry = screen.getByRole("menuitem", { name: /nuevo mundo/i });
    expect(entry).toHaveAttribute("type", "button");
    expect(screen.queryByRole("option", { name: /nuevo mundo/i })).toBeNull();
  });

  it("clicking the entry calls onRequestCreate and closes the dropdown", async () => {
    const onRequestCreate = vi.fn();
    const user = userEvent.setup();
    renderSelector({ onRequestCreate });

    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(
      screen.getByRole("menuitem", { name: /nuevo mundo/i }),
    );

    expect(onRequestCreate).toHaveBeenCalledTimes(1);
    // Dropdown is gone — the entry and the existing-world options are gone too.
    expect(
      screen.queryByRole("menuitem", { name: /nuevo mundo/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("keyboard activates the entry with Enter and Space without selecting an existing world", async () => {
    const onRequestCreate = vi.fn();
    const user = userEvent.setup();
    const onWorldChange = vi.fn();
    renderSelector({ onRequestCreate, onWorldChange });

    await user.click(screen.getByRole("button", { name: "Mundos" }));

    const entry = screen.getByRole("menuitem", { name: /nuevo mundo/i });
    entry.focus();

    await user.keyboard("{Enter}");
    expect(onRequestCreate).toHaveBeenCalledTimes(1);
    expect(onWorldChange).not.toHaveBeenCalled();

    // Open again and try Space.
    await user.click(screen.getByRole("button", { name: "Mundos" }));
    const entryAfter = screen.getByRole("menuitem", { name: /nuevo mundo/i });
    entryAfter.focus();
    await user.keyboard(" ");
    expect(onRequestCreate).toHaveBeenCalledTimes(2);
    expect(onWorldChange).not.toHaveBeenCalled();
  });
});