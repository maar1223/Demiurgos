import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import WikiWorld from "@/pages/WikiWorld";
import { ACTIVE_WORLD_STORAGE_KEY } from "@/lib/currentWorld";

// Mock useWorlds entirely
vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

import { useWorlds } from "@/hooks/useWorlds";
import type { Mock } from "vitest";

const mockWorlds = [
  { name: "Vibrantes", path: "/vibrantes", lore_count: 77, character_count: 10 },
];

/** Probe that renders the section param of the current route. */
function SectionProbe() {
  const { section } = useParams<{ section: string }>();
  return <div data-testid="section">{section}</div>;
}

/** Probe for the Relaciones y Canon page route. */
function RelacionesProbe() {
  return <div data-testid="relaciones-page">relaciones</div>;
}

function renderWikiWorld(initialEntry = "/wiki/Vibrantes") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/wiki/:mundo" element={<WikiWorld />} />
        <Route path="/wiki/:mundo/:section" element={<SectionProbe />} />
        <Route
          path="/taller-mundo/:mundo/relaciones-canon"
          element={<RelacionesProbe />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("WikiWorld", () => {
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

  it("renders a section card for each section", () => {
    renderWikiWorld();

    expect(screen.getByRole("heading", { name: "Lore" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Personajes" }),
    ).toBeInTheDocument();
  });

  it("shows the world file counts on the cards", () => {
    renderWikiWorld();

    expect(screen.getByText("77 archivos")).toBeInTheDocument();
    expect(screen.getByText("10 archivos")).toBeInTheDocument();
  });

  it("shows 'vacío' for sections with zero files", () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [
        { name: "Vibrantes", path: "/vibrantes", lore_count: 77, character_count: 0 },
      ],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    renderWikiWorld();

    expect(screen.getByText("vacío")).toBeInTheDocument();
  });

  it("navigates to the section when a card is clicked", async () => {
    const user = userEvent.setup();
    renderWikiWorld();

    // Card accessible name includes its description — disambiguates from the
    // Navbar "Personajes" placeholder link
    await user.click(
      screen.getByRole("button", {
        name: /Fichas de personajes y desarrollo/,
      }),
    );

    expect(screen.getByTestId("section")).toHaveTextContent("personajes");
  });

  it("shows the Relaciones y Canon card in the section grid", () => {
    renderWikiWorld();

    expect(
      screen.getByRole("heading", { name: "Relaciones y Canon" }),
    ).toBeInTheDocument();
  });

  it("navigates to Relaciones y Canon when the card is clicked", async () => {
    const user = userEvent.setup();
    renderWikiWorld();

    await user.click(
      screen.getByRole("button", { name: /Relaciones y Canon/ }),
    );

    expect(screen.getByTestId("relaciones-page")).toBeInTheDocument();
  });

  it("shows loading spinner when loading", () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: true,
      error: null,
      mutate: vi.fn(),
    });

    renderWikiWorld();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows 'Mundo no encontrado' for unknown worlds", () => {
    renderWikiWorld("/wiki/UnknownWorld");

    expect(screen.getByText(/Mundo no encontrado/i)).toBeInTheDocument();
  });

  it("marks the visited world as the active world", () => {
    renderWikiWorld();

    expect(localStorage.getItem(ACTIVE_WORLD_STORAGE_KEY)).toBe("Vibrantes");
  });

  it("does not mark an unknown world as active", () => {
    renderWikiWorld("/wiki/UnknownWorld");

    expect(localStorage.getItem(ACTIVE_WORLD_STORAGE_KEY)).toBeNull();
  });
});
