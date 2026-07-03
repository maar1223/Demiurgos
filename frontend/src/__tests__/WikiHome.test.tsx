import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import WikiHome from "@/pages/WikiHome";

// Mock useWorlds entirely
vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

import { useWorlds } from "@/hooks/useWorlds";
import type { Mock } from "vitest";

const mockWorlds: WorldInfo[] = [
  { name: "Vibrantes", has_lore: true, has_personajes: true, has_sagas: false },
  { name: "Sombras", has_lore: true, has_personajes: false, has_sagas: true },
];

interface WorldInfo {
  name: string;
  has_lore: boolean;
  has_personajes: boolean;
  has_sagas: boolean;
}

function renderWikiHome() {
  return render(
    <MemoryRouter initialEntries={["/wiki"]}>
      <WikiHome />
    </MemoryRouter>,
  );
}

describe("WikiHome", () => {
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

  it("renders world cards for each world", () => {
    renderWikiHome();
    expect(screen.getByText("Vibrantes")).toBeInTheDocument();
    expect(screen.getByText("Sombras")).toBeInTheDocument();
  });

  it("shows loading spinner when loading", () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: true,
      error: null,
      mutate: vi.fn(),
    });

    renderWikiHome();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows error banner on error", () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: false,
      error: new Error("Network error"),
      mutate: vi.fn(),
    });

    renderWikiHome();
    expect(
      screen.getByText(/No se pudo cargar la lista de mundos/i),
    ).toBeInTheDocument();
  });

  it("shows empty state when no worlds", () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    renderWikiHome();
    expect(
      screen.getByText(/No hay mundos disponibles/i),
    ).toBeInTheDocument();
  });

  it("renders navbar with world selector", () => {
    renderWikiHome();
    expect(screen.getByText("Mundos")).toBeInTheDocument();
  });
});
