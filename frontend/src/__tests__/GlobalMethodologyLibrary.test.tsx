import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GlobalMethodologyLibrary, toggleCompareSelection } from "@/components/organisms/GlobalMethodologyLibrary";
import { MethodologyStatePanel } from "@/components/organisms/MethodologyStatePanel";
import type { MethodologyInventoryItem, MethodologyStatus } from "@/api/types";
// Raw source of the organism under test — used by the REQ-LIB-8 import
// boundary test (no node:fs dependency needed).
import globalLibrarySource from "@/components/organisms/GlobalMethodologyLibrary.tsx?raw";

const getInventoryMock = vi.hoisted(() => vi.fn());

// Keep the REAL module (so any accidental mutation call would hit the real
// apiFetch → observable fetch) but make `getMethodologyInventory` a
// controllable mock (REQ-LIB-8 keeps the mutations importable-but-unused).
vi.mock("@/api/methodologies", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/methodologies")>();
  return { ...actual, getMethodologyInventory: getInventoryMock };
});

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
  trust_attributes: ["fundacional", "verified"],
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

/** Seeded-style inventory item: mirrors the record the server installs for
 *  `narrative-character-creation@1.0` (foundational-skills-seeding) — Oficiales
 *  + `fundacional` from server-injected trust; taller "Mundo" because the seed
 *  manifest declares `taller: Mundo`. */
const seededNarrative: MethodologyInventoryItem = {
  skill_id: "narrative-character-creation",
  version: "1.0",
  name: "Creación de Personajes",
  description:
    "Metodología fundacional para co-crear personajes narrativos nuevos, agnóstica al mundo. Esqueleto universal de ficha: identidad, carácter, Eneatipo, Subtipo, Arquetipo, Alineamiento, conflicto y arco. Principio 40/60 (diálogo, no cuestionario) y densidad por nivel narrativo (1º, 2º y 3º). El color del mundo lo aporta la skill personalizada de mundo.",
  digest: "seed-digest-1",
  published_at: "2026-09-09",
  taller: "Mundo",
  categoria_funcional: "Creación",
  etiquetas: [],
  clasificacion: "Oficiales",
  trust_attributes: ["fundacional"],
};

beforeEach(() => {
  getInventoryMock.mockReset();
  getInventoryMock.mockResolvedValue({ items: [narrative, worldbuilding] });
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
    expect(within(list).getByText("Fundacional")).toBeInTheDocument();
    expect(within(list).getByText("Verificado")).toBeInTheDocument();
    // Missing clasificacion → neutral badge, row still visible.
    expect(within(list).getByText("Sin clasificación")).toBeInTheDocument();
  });
});

describe("GlobalMethodologyLibrary — seeded foundational skill (foundational-skills-seeding)", () => {
  it("renders a seeded-style item with Oficiales + Fundacional badges and its taller sub-line", async () => {
    getInventoryMock.mockResolvedValue({ items: [seededNarrative] });
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Creación de Personajes")).toBeInTheDocument();
    });
    expect(
      screen.getByText("v1.0 · Mundo · narrative-character-creation"),
    ).toBeInTheDocument();
    // Scope to the list: the filter bar's clasificacion select also contains
    // the option labels (Oficiales/Personalizadas/Comunitarias).
    const list = screen.getByRole("list");
    expect(within(list).getByText("Oficiales")).toBeInTheDocument();
    expect(within(list).getByText("Fundacional")).toBeInTheDocument();
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
  it("re-queries conjunctively when clasificacion and etiquetas are both set", async () => {
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

    // No taller filter in the catalog (the sidebar header carries the taller
    // selector); etiquetas is a server-side conjunctive control alongside
    // clasificacion. fireEvent.change sets the value in one shot (user.type
    // is flaky here because each keystroke re-queries and re-renders).
    fireEvent.change(screen.getByLabelText("Etiquetas"), {
      target: { value: "plot" },
    });
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({
        clasificacion: "Oficiales",
        etiquetas: "plot",
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
    fireEvent.change(screen.getByLabelText("Etiquetas"), {
      target: { value: "plot" },
    });
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({
        clasificacion: "Oficiales",
        etiquetas: "plot",
      });
    });

    // Clear clasificacion → re-query without that key, etiquetas persists.
    await user.selectOptions(screen.getByLabelText("Clasificación"), "");
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({ etiquetas: "plot" });
    });
    expect(getInventoryMock).not.toHaveBeenLastCalledWith(
      expect.objectContaining({ clasificacion: expect.anything() }),
    );
  });

  it("shows the categoría funcional placeholder drawn from the allowed set (UC-5 S1)", async () => {
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    // The placeholder must be an example from CATEGORIA_FUNCIONAL_ALLOWED
    // (spec UC-5 S1), not the old "Ej. Generación de ideas".
    expect(screen.getByPlaceholderText("Ej. Creación")).toBeInTheDocument();
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
    expect(within(detailPanel).getByText("Fundacional")).toBeInTheDocument();

    // Closing hides the panel again.
    await user.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(
      screen.queryByText("Genera propuestas narrativas coherentes con el mundo."),
    ).not.toBeInTheDocument();
  });
});

describe("Compare selection (REQ-LIB-7 / UL-4) — compare panel lives in the right panel area", () => {
  const panelSelected = { skill_id: "narrative-proposer", version: "1.2.0" };
  const panelStatus: MethodologyStatus = {
    published: [
      {
        skill_id: "narrative-proposer",
        version: "1.2.0",
        name: "Narrative Proposer",
        description: "Genera propuestas narrativas coherentes con el mundo.",
        digest: "abc123",
        published_at: "2026-01-01",
        taller: "Mundo",
      },
      {
        skill_id: "worldbuilding-core",
        version: "2.0.0",
        name: "Worldbuilding core",
        description: "Construcción segura de mundos desde cero.",
        digest: "def456",
        published_at: "2026-02-01",
        taller: "Herramientas",
      },
    ],
    activations: {},
    drafts: [],
  };

  function renderComparePanel(
    compareSelection: MethodologyInventoryItem[],
    onCompareClear = vi.fn(),
  ) {
    render(
      <MethodologyStatePanel
        selected={panelSelected}
        status={panelStatus}
        lens="catalogo-total"
        onActivate={vi.fn()}
        onAdaptar={vi.fn()}
        onComparar={vi.fn()}
        onExportar={vi.fn()}
        compareSelection={compareSelection}
        onCompareClear={onCompareClear}
      />,
    );
    return onCompareClear;
  }

  it("renders the side-by-side comparison of seven fields in MethodologyStatePanel (UL-4)", () => {
    renderComparePanel([narrative, worldbuilding]);

    expect(screen.getByText("Comparación")).toBeInTheDocument();
    // Scope to the comparison table: the state panel shares several labels
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

  it("caps selection at two and replaces the oldest on a third selection (REQ-LIB-7)", () => {
    let selection = toggleCompareSelection([], narrative);
    selection = toggleCompareSelection(selection, worldbuilding);
    selection = toggleCompareSelection(selection, brainstorming);

    // Narrative (oldest) was replaced; Worldbuilding and Brainstorming stay.
    expect(selection).toEqual([worldbuilding, brainstorming]);

    // Toggling an already-selected item removes it again.
    selection = toggleCompareSelection(selection, worldbuilding);
    expect(selection).toEqual([brainstorming]);
  });

  it("clears the comparison through onCompareClear in the right panel (UL-4)", () => {
    const onCompareClear = renderComparePanel([narrative, worldbuilding]);
    expect(screen.getByText("Comparación")).toBeInTheDocument();

    // The clear control moved with the panel: it lives in the right panel
    // area now, not the catalog.
    fireEvent.click(screen.getByRole("button", { name: "Limpiar" }));
    expect(onCompareClear).toHaveBeenCalled();
  });

  it("does not render the compare panel or Limpiar in the catalog (moved to the right panel)", async () => {
    getInventoryMock.mockResolvedValue({ items: [narrative, worldbuilding] });
    render(
      <GlobalMethodologyLibrary
        compareSelection={[narrative, worldbuilding]}
        onCompareToggle={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    expect(screen.queryByText("Comparación")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Limpiar" }),
    ).not.toBeInTheDocument();
  });
});

describe("GlobalMethodologyLibrary — export action (REQ-IMP-1)", () => {
  /** jsdom lacks URL.createObjectURL; define it for the download path. */
  function stubObjectUrl() {
    const createObjectURL = vi.fn(() => "blob:mock");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectURL,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectURL,
    });
    return { createObjectURL, revokeObjectURL };
  }

  function unstubObjectUrl() {
    const urlApi = URL as unknown as {
      createObjectURL?: unknown;
      revokeObjectURL?: unknown;
    };
    delete urlApi.createObjectURL;
    delete urlApi.revokeObjectURL;
  }

  it("downloads the published version as a zip when Exportar is clicked", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Blob(["zip-bytes"], { type: "application/zip" }), {
        status: 200,
        headers: { "Content-Type": "application/zip" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { createObjectURL, revokeObjectURL } = stubObjectUrl();

    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    await user.click(screen.getAllByRole("button", { name: "Exportar" })[0]);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/methodologies/published/narrative-proposer/1.2.0/export",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(createObjectURL).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock");

    unstubObjectUrl();
    vi.unstubAllGlobals();
  });

  it("shows an inline error when the export fails", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "boom" }), { status: 500 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    await user.click(screen.getAllByRole("button", { name: "Exportar" })[0]);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se pudo exportar la metodología.",
    );
    vi.unstubAllGlobals();
  });
});

describe("GlobalMethodologyLibrary — page-level selection (SC-SB-2.2)", () => {
  it("reports the clicked row to onSelect alongside the internal detail panel", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<GlobalMethodologyLibrary onSelect={onSelect} />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Narrative Proposer"));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        skill_id: "narrative-proposer",
        version: "1.2.0",
      }),
    );
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