import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import RelacionesCanon from "@/pages/RelacionesCanon";
import type { Mock } from "vitest";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

vi.mock("@/components/GraphView", () => ({
  default: () => <div data-testid="graph-view">GraphView</div>,
}));

import { useWorlds } from "@/hooks/useWorlds";

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/taller-mundo/vibrantes/relaciones-canon"]}>
      <Routes>
        <Route
          path="/taller-mundo/:mundo/relaciones-canon"
          element={<RelacionesCanon />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RelacionesCanon", () => {
  beforeEach(() => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
  });

  it("renders three tabs with Grafo active and the graph visible by default", () => {
    renderPage();

    const grafo = screen.getByRole("tab", { name: "Grafo" });
    expect(grafo).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("tab", { name: "Conflictos" }),
    ).toHaveAttribute("aria-selected", "false");
    expect(
      screen.getByRole("tab", { name: "Propuestas" }),
    ).toHaveAttribute("aria-selected", "false");
    expect(screen.getByTestId("graph-view")).toBeInTheDocument();
  });

  it("shows a Próximamente placeholder in the Conflictos tab", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("tab", { name: "Conflictos" }));

    // Navbar also renders a "Próximamente" teaser — scope to the panel.
    expect(
      within(screen.getByTestId("placeholder-panel")).getByText(
        "Próximamente",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("graph-view")).not.toBeInTheDocument();
  });

  it("shows a Próximamente placeholder in the Propuestas tab", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("tab", { name: "Propuestas" }));

    expect(
      within(screen.getByTestId("placeholder-panel")).getByText(
        "Próximamente",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("graph-view")).not.toBeInTheDocument();
  });
});