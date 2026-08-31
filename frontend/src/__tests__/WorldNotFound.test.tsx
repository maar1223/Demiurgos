import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { WorldNotFound } from "@/components/organisms/WorldNotFound";
import { useWorlds } from "@/hooks/useWorlds";
import type { Mock } from "vitest";

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
  it("lists the surviving worlds and navigates when one is chosen", async () => {
    renderNotFound("Avalor");

    expect(screen.getByText(/Mundo no encontrado/i)).toBeInTheDocument();
    expect(screen.getByText(/No existe un mundo llamado «Avalor»/i)).toBeInTheDocument();

    // The deleted world is excluded; the remaining ones are offered.
    expect(screen.getByRole("button", { name: /Vibrantes/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Avalor/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Vibrantes/i }));
    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent("/wiki/Vibrantes"),
    );
  });

  it("falls back to 'Volver al inicio' when there are no worlds left", () => {
    useWorldsMock.mockReturnValue({
      worlds: [],
      isLoading: false,
      isValidating: false,
      error: undefined,
      mutate: vi.fn(),
    });
    renderNotFound("Avalor");

    expect(screen.getByRole("button", { name: /Volver al inicio/i })).toBeInTheDocument();
  });
});
