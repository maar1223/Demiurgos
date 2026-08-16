import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import WorldWorkshop from "@/pages/WorldWorkshop";
import { ACTIVE_WORLD_STORAGE_KEY } from "@/lib/currentWorld";

// Mock useWorlds entirely
vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

import { useWorlds } from "@/hooks/useWorlds";
import type { Mock } from "vitest";

const mockWorlds = [
  { name: "Vibrantes", path: "/vibrantes", lore_count: 77, character_count: 10, saga_count: 4 },
];

function renderWorldWorkshop() {
  return render(
    <MemoryRouter initialEntries={["/taller-mundo"]}>
      <Routes>
        <Route path="/taller-mundo" element={<WorldWorkshop />} />
        <Route path="/wiki/:mundo" element={<div data-testid="wiki">wiki</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("WorldWorkshop", () => {
  beforeEach(() => {
    (useWorlds as Mock).mockReturnValue({
      worlds: mockWorlds,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the workshop heading and world cards", () => {
    renderWorldWorkshop();

    expect(
      screen.getByRole("heading", { name: "Taller de Mundo" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Vibrantes")).toBeInTheDocument();
  });

  it("navigates into the world wiki workspace on card click", async () => {
    const user = userEvent.setup();
    renderWorldWorkshop();

    await user.click(screen.getByRole("button", { name: /Vibrantes/ }));

    expect(screen.getByTestId("wiki")).toBeInTheDocument();
  });

  it("choosing a card sets it as the active world and navigates", async () => {
    const user = userEvent.setup();
    renderWorldWorkshop();

    await user.click(screen.getByRole("button", { name: /Vibrantes/ }));

    expect(localStorage.getItem(ACTIVE_WORLD_STORAGE_KEY)).toBe("Vibrantes");
    expect(screen.getByTestId("wiki")).toBeInTheDocument();
  });

  it("redirects to the active world when one is persisted", () => {
    localStorage.setItem(ACTIVE_WORLD_STORAGE_KEY, "Vibrantes");
    renderWorldWorkshop();

    expect(screen.getByTestId("wiki")).toBeInTheDocument();
  });

  it("does not redirect to a stale world that no longer exists", () => {
    localStorage.setItem(ACTIVE_WORLD_STORAGE_KEY, "Ghost");
    renderWorldWorkshop();

    expect(
      screen.getByRole("heading", { name: "Taller de Mundo" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Vibrantes")).toBeInTheDocument();
  });

  it("shows the empty state when no worlds exist", () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    renderWorldWorkshop();

    expect(
      screen.getByText("No hay mundos disponibles. Creá un mundo primero."),
    ).toBeInTheDocument();
  });

  it("shows the error banner with retry on fetch failure", async () => {
    const mutate = vi.fn();
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: false,
      error: new Error("boom"),
      mutate,
    });

    const user = userEvent.setup();
    renderWorldWorkshop();

    expect(screen.getByText(/No se pudo cargar la lista de mundos/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(mutate).toHaveBeenCalled();
  });
});
