import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Route,
  Routes,
  useParams,
  useSearchParams,
} from "react-router-dom";
import WikiWorld from "@/pages/WikiWorld";
import { ACTIVE_WORLD_STORAGE_KEY } from "@/lib/currentWorld";
import { FIRST_VALUE_HANDOFF_PENDING_KEY } from "@/lib/constants";

// Mock useWorlds entirely
vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

import { useWorlds } from "@/hooks/useWorlds";
import type { Mock } from "vitest";

const mockWorlds = [
  { name: "Vibrantes", path: "/vibrantes", lore_count: 77, character_count: 10, reference_count: 0 },
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

/** Probe for the world-scoped importer route. */
function ImporterProbe() {
  return <div data-testid="importer-page">importer</div>;
}

/** Probe for the profile page, echoing the `tab` query param. */
function PerfilProbe() {
  const [params] = useSearchParams();
  return <div data-testid="perfil-page">tab:{params.get("tab")}</div>;
}

function renderWikiWorld(initialEntry = "/wiki/Vibrantes") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/wiki/:mundo" element={<WikiWorld />} />
        <Route path="/wiki/:mundo/:section" element={<SectionProbe />} />
        <Route path="/wiki/:mundo/importer" element={<ImporterProbe />} />
        <Route path="/perfil" element={<PerfilProbe />} />
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

  it("shows an actionable hint for sections with zero files", () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [
        { name: "Vibrantes", path: "/vibrantes", lore_count: 77, character_count: 0, reference_count: 0 },
      ],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    renderWikiWorld();

    // Two sections (personajes, referencias) are empty with this world.
    expect(
      screen.getAllByText("Empieza aquí: crea tu primer archivo"),
    ).toHaveLength(2);
    expect(screen.queryByText("vacío")).not.toBeInTheDocument();
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

  describe("first-value handoff", () => {
    const PENDING = JSON.stringify(["Vibrantes"]);

    it("shows the hero when the world has a pending flag", () => {
      localStorage.setItem(FIRST_VALUE_HANDOFF_PENDING_KEY, PENDING);
      renderWikiWorld();

      expect(
        screen.getByRole("heading", { name: "Tu mundo está listo" }),
      ).toBeInTheDocument();
      // The section grid stays visible alongside the hero — never a gate.
      expect(screen.getByRole("heading", { name: "Lore" })).toBeInTheDocument();
    });

    it("does not show the hero when no flag is pending", () => {
      renderWikiWorld();

      expect(
        screen.queryByRole("heading", { name: "Tu mundo está listo" }),
      ).not.toBeInTheDocument();
    });

    it("import → completes and navigates to /wiki/Vibrantes/importer", async () => {
      localStorage.setItem(FIRST_VALUE_HANDOFF_PENDING_KEY, PENDING);
      const user = userEvent.setup();
      renderWikiWorld();

      await user.click(
        screen.getByRole("button", { name: "Importar documentos" }),
      );

      expect(screen.getByTestId("importer-page")).toBeInTheDocument();
      expect(
        localStorage.getItem(FIRST_VALUE_HANDOFF_PENDING_KEY),
      ).toBe("[]");
    });

    it("write note → completes and navigates to /wiki/Vibrantes/lore", async () => {
      localStorage.setItem(FIRST_VALUE_HANDOFF_PENDING_KEY, PENDING);
      const user = userEvent.setup();
      renderWikiWorld();

      await user.click(
        screen.getByRole("button", { name: "Escribir la primera nota" }),
      );

      expect(screen.getByTestId("section")).toHaveTextContent("lore");
      expect(
        localStorage.getItem(FIRST_VALUE_HANDOFF_PENDING_KEY),
      ).toBe("[]");
    });

    it("assistant → completes and navigates to /perfil?tab=conexiones", async () => {
      localStorage.setItem(FIRST_VALUE_HANDOFF_PENDING_KEY, PENDING);
      const user = userEvent.setup();
      renderWikiWorld();

      await user.click(
        screen.getByRole("button", { name: "Configurar el asistente" }),
      );

      expect(screen.getByTestId("perfil-page")).toHaveTextContent(
        "tab:conexiones",
      );
      expect(
        localStorage.getItem(FIRST_VALUE_HANDOFF_PENDING_KEY),
      ).toBe("[]");
    });

    it("dismiss hides the hero and clears the flag", async () => {
      localStorage.setItem(FIRST_VALUE_HANDOFF_PENDING_KEY, PENDING);
      const user = userEvent.setup();
      renderWikiWorld();

      await user.click(screen.getByRole("button", { name: "Ahora no" }));

      expect(
        screen.queryByRole("heading", { name: "Tu mundo está listo" }),
      ).not.toBeInTheDocument();
      expect(
        localStorage.getItem(FIRST_VALUE_HANDOFF_PENDING_KEY),
      ).toBe("[]");
      // The section grid remains fully reachable after dismissal.
      expect(screen.getByRole("heading", { name: "Lore" })).toBeInTheDocument();
    });

    it("shows no hero on revisit after completion", () => {
      localStorage.setItem(FIRST_VALUE_HANDOFF_PENDING_KEY, "[]");
      renderWikiWorld();

      expect(
        screen.queryByRole("heading", { name: "Tu mundo está listo" }),
      ).not.toBeInTheDocument();
    });
  });
});
