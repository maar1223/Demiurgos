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
}

function renderSelector(props: SelectorTestProps = {}) {
  return render(
    <MemoryRouter initialEntries={["/wiki"]}>
      <WorldSelector worlds={worlds} {...props} />
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
});