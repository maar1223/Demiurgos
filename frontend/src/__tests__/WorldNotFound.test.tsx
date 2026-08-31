import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { WorldNotFound } from "@/components/organisms/WorldNotFound";
import { useWorlds } from "@/hooks/useWorlds";

vi.mock("@/hooks/useWorlds", () => ({ useWorlds: vi.fn() }));
const useWorldsMock = vi.mocked(useWorlds);

const worlds = [
  { name: "Avalor", path: "mundos/Avalor", lore_count: 1, character_count: 2, reference_count: 0 },
  { name: "Vibrantes", path: "mundos/Vibrantes", lore_count: 3, character_count: 4, reference_count: 0 },
];

function LocationProbe() {
  const { pathname } = useLocation();
  return <div data-testid="path">{pathname}</div>;
}

function renderNotFound(mundo = "Avalor") {
  return render(
    <MemoryRouter initialEntries={["/wiki/Avalor"]}>
      <WorldNotFound mundo={mundo} />
      <Routes>
        <Route path="/wiki/:mundo" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorldsMock.mockReturnValue({
    worlds,
    isLoading: false,
    isValidating: false,
    error: undefined,
    mutate: vi.fn(),
  });
});

describe("WorldNotFound", () => {
  it("auto-opens a dialog listing the surviving worlds and navigates when one is chosen", async () => {
    renderNotFound("Avalor");

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Elegí un mundo")).toBeInTheDocument();
    expect(screen.getByText(/El mundo «Avalor» ya no existe/)).toBeInTheDocument();

    // The deleted world is excluded; the remaining ones are offered.
    expect(screen.getByRole("button", { name: /Vibrantes/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Avalor/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Vibrantes/ }));
    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent("/wiki/Vibrantes"),
    );
  });

  it("offers 'Nuevo mundo' and a note when there are no other worlds", () => {
    useWorldsMock.mockReturnValue({
      worlds: [],
      isLoading: false,
      isValidating: false,
      error: undefined,
      mutate: vi.fn(),
    });
    renderNotFound("Avalor");

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Nuevo mundo/ })).toBeInTheDocument();
    expect(screen.getByText(/No hay otros mundos creados todavía/)).toBeInTheDocument();
  });

  it("opens the create-world dialog when 'Nuevo mundo' is clicked", async () => {
    renderNotFound("Avalor");

    fireEvent.click(screen.getByRole("button", { name: /Nuevo mundo/ }));

    // The picker closes and the create dialog (same shell) opens with the name
    // field — regression for the z-index/stacking bug that hid it.
    await waitFor(() =>
      expect(screen.getByRole("dialog")).toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/Nombre del mundo/)).toBeInTheDocument();
    expect(screen.queryByText("Elegí un mundo")).not.toBeInTheDocument();
  });
});
