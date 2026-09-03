import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { GlobalMethodologyLibrary } from "@/components/organisms/GlobalMethodologyLibrary";
import ToolWorkshop from "@/pages/ToolWorkshop";
import type { MethodologyInventoryItem } from "@/api/types";
import type { Mock } from "vitest";
// Raw source of the organism under test — used by the REQ-LIB-8 import
// boundary test (no node:fs dependency needed).
import globalLibrarySource from "@/components/organisms/GlobalMethodologyLibrary.tsx?raw";

const getInventoryMock = vi.hoisted(() => vi.fn());
const setCurrentTallerMock = vi.hoisted(() => vi.fn());

// Keep the REAL module (so any accidental mutation call would hit the real
// apiFetch → observable fetch) but make `getMethodologyInventory` a
// controllable mock (REQ-LIB-8 keeps the mutations importable-but-unused).
vi.mock("@/api/methodologies", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/methodologies")>();
  return { ...actual, getMethodologyInventory: getInventoryMock };
});

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

// Keep the real readers/subscriber; spy on the writer so the tab-toggle test
// can prove switching never persists a taller change.
vi.mock("@/lib/currentTaller", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/currentTaller")>();
  return { ...actual, setCurrentTaller: setCurrentTallerMock };
});

import { useWorlds } from "@/hooks/useWorlds";

const narrative: MethodologyInventoryItem = {
  skill_id: "narrative-proposer",
  version: "1.2.0",
  name: "Narrative Proposer",
  description: "Genera propuestas narrativas coherentes con el mundo.",
  digest: "abc123",
  published_at: "2026-01-01",
  taller: "Mundo",
  categoria_funcional: "Generación de ideas",
  etiquetas: ["narrativa", "ideas"],
  clasificacion: "Oficiales",
  trust_attributes: ["fundamental", "verified"],
};

const worldbuilding: MethodologyInventoryItem = {
  skill_id: "worldbuilding-core",
  version: "2.0.0",
  name: "Worldbuilding core",
  description: "Construcción segura de mundos desde cero.",
  digest: "def456",
  published_at: "2026-02-01",
  taller: "Herramientas",
  categoria_funcional: "Estructura",
  etiquetas: ["mundo", "estructura"],
  clasificacion: "Personalizadas",
  trust_attributes: ["derived"],
};

const brainstorming: MethodologyInventoryItem = {
  skill_id: "brainstorming",
  version: "1.0.0",
  name: "Brainstorming",
  description: "Lluvia de ideas estructurada.",
  digest: "ghi789",
  published_at: "2026-03-01",
  taller: "Ideas",
  etiquetas: [],
  clasificacion: "Comunitarias",
  trust_attributes: ["co-created"],
};

beforeEach(() => {
  getInventoryMock.mockReset();
  getInventoryMock.mockResolvedValue({ items: [narrative, worldbuilding] });
  setCurrentTallerMock.mockClear();
});

describe("GlobalMethodologyLibrary — list render (REQ-LIB-2)", () => {
  it("shows a loading state while the inventory request is in flight", () => {
    getInventoryMock.mockReturnValue(
      new Promise<{ items: MethodologyInventoryItem[] }>(() => undefined),
    );
    render(<GlobalMethodologyLibrary />);
    expect(screen.getByRole("status", { name: "Cargando" })).toBeInTheDocument();
  });

  it("calls getMethodologyInventory with no filters on mount and renders every item", async () => {
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });
    expect(screen.getByText("Worldbuilding core")).toBeInTheDocument();
    expect(getInventoryMock).toHaveBeenCalledTimes(1);
    expect(getInventoryMock).toHaveBeenCalledWith({});
  });

  it("shows the empty state when the inventory has no items", async () => {
    getInventoryMock.mockResolvedValue({ items: [] });
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(
        screen.getByText("No hay metodologías publicadas"),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText("Narrative Proposer")).not.toBeInTheDocument();
  });

  it("shows an error banner and retries the request (REQ-LIB-2 S2)", async () => {
    getInventoryMock.mockRejectedValueOnce(new Error("network down"));
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/No se pudo cargar el inventario global/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
  });

  it("renders classification badges and trust chips, never hiding rows with missing clasificacion (REQ-LIB-5)", async () => {
    getInventoryMock.mockResolvedValue({
      items: [
        narrative,
        { ...brainstorming, clasificacion: null, trust_attributes: [] },
      ],
    });
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Brainstorming")).toBeInTheDocument();
    });
    // Scope to the list: the filter bar's clasificacion select also contains
    // the option labels (Oficiales/Personalizadas/Comunitarias).
    const list = screen.getByRole("list");
    expect(within(list).getByText("Oficiales")).toBeInTheDocument();
    expect(within(list).getByText("fundamental")).toBeInTheDocument();
    expect(within(list).getByText("verified")).toBeInTheDocument();
    // Missing clasificacion → neutral badge, row still visible.
    expect(within(list).getByText("Sin clasificación")).toBeInTheDocument();
  });
});

describe("GlobalMethodologyLibrary — client-side search (REQ-LIB-3)", () => {
  it("filters by case-insensitive substring and yields the same result for uppercase input", async () => {
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    const searchBox = screen.getByRole("searchbox");
    await user.type(searchBox, "narrative");
    expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    expect(screen.queryByText("Worldbuilding core")).not.toBeInTheDocument();

    await user.clear(searchBox);
    await user.type(searchBox, "NARRATIVE");
    expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    expect(screen.queryByText("Worldbuilding core")).not.toBeInTheDocument();
  });

  it("matches against description and skill_id without hitting the backend again", async () => {
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    await user.type(screen.getByRole("searchbox"), "CONSTRUCCIÓN SEGURA");
    expect(screen.getByText("Worldbuilding core")).toBeInTheDocument();
    expect(screen.queryByText("Narrative Proposer")).not.toBeInTheDocument();
    // Search is client-side: no additional inventory request.
    expect(getInventoryMock).toHaveBeenCalledTimes(1);

    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "narrative-proposer");
    expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    expect(screen.queryByText("Worldbuilding core")).not.toBeInTheDocument();
  });

  it("shows 'Sin resultados' when the query matches nothing (REQ-LIB-3 S2)", async () => {
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    await user.type(screen.getByRole("searchbox"), "zzzzz");
    expect(screen.getByText("Sin resultados")).toBeInTheDocument();
    expect(screen.queryByText("Narrative Proposer")).not.toBeInTheDocument();
  });
});

describe("GlobalMethodologyLibrary — server-side filters (REQ-LIB-4)", () => {
  it("re-queries conjunctively when clasificacion and taller are both set", async () => {
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });
    expect(getInventoryMock).toHaveBeenLastCalledWith({});

    await user.selectOptions(screen.getByLabelText("Clasificación"), "Oficiales");
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({
        clasificacion: "Oficiales",
      });
    });

    // The taller filter reuses TallerSelector as a filter-only control.
    const tallerTrigger = screen
      .getAllByRole("button")
      .find((button) => button.getAttribute("aria-haspopup") === "listbox");
    expect(tallerTrigger).toBeDefined();
    await user.click(tallerTrigger!);
    await user.click(await screen.findByRole("option", { name: "Taller de Mundo" }));

    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({
        clasificacion: "Oficiales",
        taller: "Mundo",
      });
    });
  });

  it("drops a cleared filter from the re-query while keeping the others (REQ-LIB-4 S2)", async () => {
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    await user.selectOptions(screen.getByLabelText("Clasificación"), "Oficiales");
    const tallerTrigger = screen
      .getAllByRole("button")
      .find((button) => button.getAttribute("aria-haspopup") === "listbox");
    await user.click(tallerTrigger!);
    await user.click(await screen.findByRole("option", { name: "Taller de Mundo" }));
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({
        clasificacion: "Oficiales",
        taller: "Mundo",
      });
    });

    // Clear clasificacion → re-query without that key, taller persists.
    await user.selectOptions(screen.getByLabelText("Clasificación"), "");
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({ taller: "Mundo" });
    });
    expect(getInventoryMock).not.toHaveBeenLastCalledWith(
      expect.objectContaining({ clasificacion: expect.anything() }),
    );
  });
});

describe("GlobalMethodologyLibrary — detail panel (REQ-LIB-6)", () => {
  it("opens the detail panel with full metadata when a row is clicked", async () => {
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Narrative Proposer"));
    // Scope to the panel: the filter bar shares some field labels
    // (Categoría funcional) and the row keeps its own badges/chips.
    const detailPanel = screen
      .getByRole("heading", { name: "Narrative Proposer" })
      .closest("section")!;
    expect(
      within(detailPanel).getByText(
        "Genera propuestas narrativas coherentes con el mundo.",
      ),
    ).toBeInTheDocument();
    expect(
      within(detailPanel).getByText("Categoría funcional"),
    ).toBeInTheDocument();
    expect(within(detailPanel).getByText("narrativa")).toBeInTheDocument();
    expect(within(detailPanel).getByText("Oficiales")).toBeInTheDocument();
    expect(within(detailPanel).getByText("fundamental")).toBeInTheDocument();

    // Closing hides the panel again.
    await user.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(
      screen.queryByText("Genera propuestas narrativas coherentes con el mundo."),
    ).not.toBeInTheDocument();
  });
});

describe("GlobalMethodologyLibrary — compare selection (REQ-LIB-7)", () => {
  it("renders a side-by-side comparison of seven fields for two selections", async () => {
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    await user.click(screen.getAllByRole("button", { name: "Comparar" })[0]);
    await user.click(screen.getAllByRole("button", { name: "Comparar" })[0]);

    expect(screen.getByText("Comparación")).toBeInTheDocument();
    // Scope to the comparison table: the filter bar shares several labels
    // (Taller, Etiquetas, Categoría funcional, Clasificación).
    const comparePanel = screen.getByText("Comparación").closest("section")!;
    for (const field of [
      "Nombre",
      "Versión",
      "Taller",
      "Categoría funcional",
      "Etiquetas",
      "Descripción",
      "Clasificación",
    ]) {
      expect(within(comparePanel).getByText(field)).toBeInTheDocument();
    }
  });

  it("caps selection at two, replaces the oldest on a third selection, and clears on demand", async () => {
    getInventoryMock.mockResolvedValue({ items: [narrative, worldbuilding, brainstorming] });
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Brainstorming")).toBeInTheDocument();
    });

    await user.click(screen.getAllByRole("button", { name: "Comparar" })[0]);
    await user.click(screen.getAllByRole("button", { name: "Comparar" })[0]);
    await user.click(screen.getAllByRole("button", { name: "Comparar" })[0]);

    // Narrative (oldest) was replaced; Worldbuilding and Brainstorming stay.
    const states = screen.getAllByRole("button", { name: /Comparar|Quitar/ });
    expect(states).toHaveLength(3);
    expect(states[0]).toHaveTextContent("Comparar");
    expect(states[1]).toHaveTextContent("Quitar");
    expect(states[2]).toHaveTextContent("Quitar");
    expect(screen.getByText("Comparación")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Limpiar" }));
    expect(screen.queryByText("Comparación")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Comparar" })).toHaveLength(3);
  });
});

describe("ToolWorkshop — tab toggle preserves operational context (REQ-LIB-1)", () => {
  it("defaults to 'Taller activo' and never mutates activeTaller/world on switch", async () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [
        {
          name: "Vibrantes",
          path: "/vibrantes",
          lore_count: 1,
          character_count: 0,
          reference_count: 0,
        },
      ],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    // Real getMethodologyStatus runs through apiFetch → observable fetch.
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        published: [
          {
            skill_id: "guided-character-v1",
            version: "1.2.0",
            name: "Guided character methodology",
            description: "",
            digest: "abc",
            published_at: "2026-01-01",
            taller: "Herramientas",
          },
        ],
        activations: {},
        drafts: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const tallerBefore = window.localStorage.getItem("demiurgos-active-taller");
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/taller-herramientas"]}>
        <Routes>
          <Route path="/taller-herramientas" element={<ToolWorkshop />} />
        </Routes>
      </MemoryRouter>,
    );

    // Default tab is the Fase 2 operational tree (REQ-LIB-1 S1).
    expect(
      screen.getByRole("tab", { name: "Taller activo" }),
    ).toHaveAttribute("aria-selected", "true");
    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: "Taller de Herramientas" }),
    ).toBeInTheDocument();

    // Switch to the global library: renders without touching taller/world.
    await user.click(screen.getByRole("tab", { name: "Biblioteca global" }));
    await screen.findByRole("searchbox", { name: /buscar/i });
    expect(setCurrentTallerMock).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("demiurgos-active-taller")).toBe(
      tallerBefore,
    );

    // Switching back restores the operational tree, untouched.
    await user.click(screen.getByRole("tab", { name: "Taller activo" }));
    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: "Taller de Herramientas" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mundos" })).toBeInTheDocument();
    expect(setCurrentTallerMock).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("demiurgos-active-taller")).toBe(
      tallerBefore,
    );

    vi.unstubAllGlobals();
  });
});

describe("REQ-LIB-8 — read-only invariant", () => {
  const FORBIDDEN_VALUES = [
    "activateMethodology",
    "publishMethodologyDraft",
    "createMethodologyDraft",
    "rollbackMethodology",
    "getMethodologyStatus",
  ];
  const FORBIDDEN_MODULES = [
    "@/lib/currentTaller",
    "@/lib/tallerStates",
    "@/hooks/useWorlds",
    "@/hooks/useActiveTaller",
  ];

  it("(a) contains no mutation or operational-context import in the organism source", () => {
    for (const symbol of FORBIDDEN_VALUES) {
      expect(globalLibrarySource).not.toMatch(new RegExp(`\\b${symbol}\\b`));
    }
    for (const modulePath of FORBIDDEN_MODULES) {
      expect(globalLibrarySource).not.toContain(modulePath);
    }
    // The only allowed value import from the API module.
    expect(globalLibrarySource).toContain("getMethodologyInventory");
  });

  it("(b) renders without POSTing to /methodologies and without writing persisted state", async () => {
    getInventoryMock.mockResolvedValue({ items: [narrative] });
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const storageSpy = vi.spyOn(Storage.prototype, "setItem");

    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/methodologies"),
      expect.objectContaining({ method: "POST" }),
    );
    expect(storageSpy).not.toHaveBeenCalledWith(
      "demiurgos-active-taller",
      expect.anything(),
    );

    storageSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});