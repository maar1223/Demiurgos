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

/** Two more published versions of the same seeded skill: the multi-version
 *  group case in the catalog (TW7). Each description is unique so client-side
 *  search can discriminate between the versions. */
const personajesV11: MethodologyInventoryItem = {
  ...seededNarrative,
  version: "1.1",
  digest: "seed-digest-11",
  description: "Revisión de la metodología base.",
};

const personajesV20: MethodologyInventoryItem = {
  ...seededNarrative,
  version: "2.0",
  digest: "seed-digest-20",
  description: "Expansión de la metodología base.",
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

  it("shows the most specific origin label per row and never hides rows with missing clasificacion (REQ-LIB-5)", async () => {
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
    // narrative is Oficiales WITH fundacional + verified → the implied
    // "Oficiales" badge is suppressed; the trust chips carry the origin.
    expect(within(list).queryByText("Oficiales")).not.toBeInTheDocument();
    expect(within(list).getByText("Fundacional")).toBeInTheDocument();
    expect(within(list).getByText("Verificado")).toBeInTheDocument();
    // Missing clasificacion → neutral badge, row still visible.
    expect(within(list).getByText("Sin clasificación")).toBeInTheDocument();
  });
});

describe("GlobalMethodologyLibrary — seeded foundational skill (foundational-skills-seeding)", () => {
  it("renders a seeded-style item with only the Fundacional chip (Oficiales is implied) and its taller sub-line", async () => {
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
    // The seed is Oficiales + fundacional → only the more specific chip shows.
    expect(within(list).queryByText("Oficiales")).not.toBeInTheDocument();
    expect(within(list).getByText("Fundacional")).toBeInTheDocument();
  });
});

describe("GlobalMethodologyLibrary — catalog grouped by skill (TW7 presentation)", () => {
  const multiVersionItems = [seededNarrative, personajesV11, personajesV20];

  it("renders exactly ONE group header per multi-version skill with all versions nested, expanded by default", async () => {
    getInventoryMock.mockResolvedValue({ items: multiVersionItems });
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Creación de Personajes")).toBeInTheDocument();
    });

    // Exactly one disclosure header: the only button whose accessible name
    // carries the skill_id (nested version rows omit it by design).
    const headers = screen.getAllByRole("button", {
      name: /narrative-character-creation/,
    });
    expect(headers).toHaveLength(1);
    expect(headers[0]).toHaveAttribute("aria-expanded", "true");

    // The skill name lives in the header only — never repeated per version.
    expect(screen.getAllByText("Creación de Personajes")).toHaveLength(1);

    // Expanded by default: every version row is visible on mount, nested
    // without repeating the name/skill_id (version · taller only).
    expect(screen.getByText("v1.0 · Mundo")).toBeInTheDocument();
    expect(screen.getByText("v1.1 · Mundo")).toBeInTheDocument();
    expect(screen.getByText("v2.0 · Mundo")).toBeInTheDocument();
  });

  it("renders a plain row without any disclosure control for a single-version skill", async () => {
    getInventoryMock.mockResolvedValue({ items: [narrative] });
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    // No disclosure control anywhere: nothing exposes aria-expanded.
    expect(
      screen.queryByRole("button", { expanded: true }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { expanded: false }),
    ).not.toBeInTheDocument();
    // Plain full row: the sub-line still carries the skill_id.
    expect(
      screen.getByText("v1.2.0 · Mundo · narrative-proposer"),
    ).toBeInTheDocument();
  });

  it("collapses and expands the group through the disclosure header", async () => {
    const user = userEvent.setup();
    getInventoryMock.mockResolvedValue({ items: multiVersionItems });
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("v1.0 · Mundo")).toBeInTheDocument();
    });

    const header = screen.getByRole("button", {
      name: /narrative-character-creation/,
    });
    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("v1.0 · Mundo")).not.toBeInTheDocument();
    expect(screen.queryByText("v1.1 · Mundo")).not.toBeInTheDocument();
    expect(screen.queryByText("v2.0 · Mundo")).not.toBeInTheDocument();

    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("v1.0 · Mundo")).toBeInTheDocument();
    expect(screen.getByText("v1.1 · Mundo")).toBeInTheDocument();
    expect(screen.getByText("v2.0 · Mundo")).toBeInTheDocument();
  });

  it("reports the exact nested version to onSelect and highlights only the selected version in the compare queue", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    getInventoryMock.mockResolvedValue({ items: multiVersionItems });
    render(
      <GlobalMethodologyLibrary
        onSelect={onSelect}
        compareSelection={[personajesV11]}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("v1.1 · Mundo")).toBeInTheDocument();
    });

    await user.click(screen.getByText("v1.1 · Mundo"));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        skill_id: "narrative-character-creation",
        version: "1.1",
      }),
    );

    // The compare highlight marks exactly that version's row (nearest card).
    const v11Row = screen
      .getByText("v1.1 · Mundo")
      .closest("div.border-edge")!;
    expect(v11Row).toHaveClass("border-action/50");
    const v10Row = screen
      .getByText("v1.0 · Mundo")
      .closest("div.border-edge")!;
    expect(v10Row).not.toHaveClass("border-action/50");
  });

  it("keeps a multi-version group coherent under a query: only surviving versions render", async () => {
    const user = userEvent.setup();
    getInventoryMock.mockResolvedValue({ items: multiVersionItems });
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("v1.0 · Mundo")).toBeInTheDocument();
    });

    // "base" matches only the v1.1 and v2.0 descriptions — v1.0 drops out.
    await user.type(screen.getByRole("searchbox"), "base");
    expect(screen.getByText("v1.1 · Mundo")).toBeInTheDocument();
    expect(screen.getByText("v2.0 · Mundo")).toBeInTheDocument();
    expect(screen.queryByText("v1.0 · Mundo")).not.toBeInTheDocument();

    // The group header survives with the surviving count, client-side only.
    const header = screen.getByRole("button", {
      name: /narrative-character-creation/,
    });
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText("narrative-character-creation · Mundo · 2 versiones"),
    ).toBeInTheDocument();
    expect(getInventoryMock).toHaveBeenCalledTimes(1);
  });

  it("degrades a multi-version skill to a plain row when only one version survives the query", async () => {
    const user = userEvent.setup();
    getInventoryMock.mockResolvedValue({ items: multiVersionItems });
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("v1.0 · Mundo")).toBeInTheDocument();
    });

    // "Revisión" matches only v1.1 — the skill now has exactly one survivor.
    await user.type(screen.getByRole("searchbox"), "Revisión");
    expect(
      screen.queryByRole("button", { expanded: true }),
    ).not.toBeInTheDocument();
    // Plain full row again: name plus version · taller · skill_id sub-line.
    expect(screen.getByText("Creación de Personajes")).toBeInTheDocument();
    expect(
      screen.getByText("v1.1 · Mundo · narrative-character-creation"),
    ).toBeInTheDocument();
    expect(screen.queryByText("v1.0 · Mundo")).not.toBeInTheDocument();
    expect(screen.queryByText("v2.0 · Mundo")).not.toBeInTheDocument();
  });
});

describe("GlobalMethodologyLibrary — implied Oficiales badge is suppressed (REQ-LIB-5)", () => {
  it("hides Oficiales when only the verified trust chip is present", async () => {
    getInventoryMock.mockResolvedValue({
      items: [{ ...narrative, trust_attributes: ["verified"] }],
    });
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    const list = screen.getByRole("list");
    expect(within(list).queryByText("Oficiales")).not.toBeInTheDocument();
    expect(within(list).getByText("Verificado")).toBeInTheDocument();
  });

  it("keeps the badge for a non-Oficiales classification", async () => {
    // worldbuilding is Personalizadas — no trust chip implies it.
    getInventoryMock.mockResolvedValue({ items: [{ ...worldbuilding, trust_attributes: [] }] });
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Worldbuilding core")).toBeInTheDocument();
    });

    const list = screen.getByRole("list");
    expect(within(list).getByText("Personalizadas")).toBeInTheDocument();
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

  it("matches etiquetas and categoría funcional through the single search field", async () => {
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    // "ideas" is only present as data on narrative (tag + categoría funcional),
    // not in worldbuilding's name/id/description.
    await user.type(screen.getByRole("searchbox"), "ideas");
    expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    expect(screen.queryByText("Worldbuilding core")).not.toBeInTheDocument();

    // "estructura" is worldbuilding's categoría funcional + tag, not its name.
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "estructura");
    expect(screen.getByText("Worldbuilding core")).toBeInTheDocument();
    expect(screen.queryByText("Narrative Proposer")).not.toBeInTheDocument();
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
  it("re-queries conjunctively when clasificacion and categoría funcional are both set", async () => {
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

    // Both facets are closed-set selects; there is no free-text tag filter —
    // the single "Buscar" field covers tags client-side.
    await user.selectOptions(
      screen.getByLabelText("Categoría funcional"),
      "Creación",
    );
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({
        clasificacion: "Oficiales",
        categoria_funcional: "Creación",
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
    await user.selectOptions(
      screen.getByLabelText("Categoría funcional"),
      "Creación",
    );
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({
        clasificacion: "Oficiales",
        categoria_funcional: "Creación",
      });
    });

    // Clear clasificacion → re-query without that key, categoría persists.
    await user.selectOptions(screen.getByLabelText("Clasificación"), "");
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({
        categoria_funcional: "Creación",
      });
    });
    expect(getInventoryMock).not.toHaveBeenLastCalledWith(
      expect.objectContaining({ clasificacion: expect.anything() }),
    );
  });

  it("renders Categoría funcional as a closed-set select, not a search box (UC-5 S1)", async () => {
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    // The field is an enum (methodology_compiler.CATEGORIA_FUNCIONAL_ALLOWED),
    // so it filters through a select with every allowed value.
    const categoria = screen.getByLabelText("Categoría funcional");
    expect(categoria.tagName).toBe("SELECT");
    for (const value of [
      "Creación",
      "Investigación",
      "Diseño",
      "Análisis",
      "Organización",
      "Visualización",
    ]) {
      expect(within(categoria).getByRole("option", { name: value })).toBeInTheDocument();
    }
  });

  it("offers 'Fundacional' in Clasificación and maps it to its own trust facet", async () => {
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    // The Clasificación select carries the origin enum plus the "Fundacional"
    // trust facet (server-seeded skills) — a UI convenience mapping to its own
    // `fundacional` query param, not to a `clasificacion` origin value.
    const clasificacion = screen.getByLabelText("Clasificación");
    expect(
      within(clasificacion).getByRole("option", { name: "Fundacional" }),
    ).toBeInTheDocument();

    // Selecting "Fundacional" sends { fundacional: true } with no clasificacion.
    await user.selectOptions(clasificacion, "Fundacional");
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({ fundacional: true });
    });
    expect(getInventoryMock).not.toHaveBeenLastCalledWith(
      expect.objectContaining({ clasificacion: expect.anything() }),
    );

    // Selecting "Oficiales" afterwards drops fundacional and restores the origin facet.
    await user.selectOptions(clasificacion, "Oficiales");
    await waitFor(() => {
      expect(getInventoryMock).toHaveBeenLastCalledWith({
        clasificacion: "Oficiales",
      });
    });
    expect(getInventoryMock).not.toHaveBeenLastCalledWith(
      expect.objectContaining({ fundacional: expect.anything() }),
    );
  });
});

describe("GlobalMethodologyLibrary — filter bar stays mounted during re-query (regression)", () => {
  it("keeps the filter bar mounted and holds the selected filter while the debounced request is pending", async () => {
    const user = userEvent.setup();
    render(<GlobalMethodologyLibrary />);
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });

    // Next request stays pending so we can observe the in-flight state.
    let resolvePending: (value: {
      items: MethodologyInventoryItem[];
    }) => void = () => undefined;
    getInventoryMock.mockReturnValueOnce(
      new Promise<{ items: MethodologyInventoryItem[] }>((resolve) => {
        resolvePending = resolve;
      }),
    );

    await user.selectOptions(
      screen.getByLabelText("Categoría funcional"),
      "Creación",
    );

    // The debounced fetch fires; while it is pending the filter bar must stay
    // mounted (no early return) and keep the selected value.
    await waitFor(() => {
      expect(
        screen.getByRole("status", { name: "Cargando" }),
      ).toBeInTheDocument();
    });
    const stillMounted = screen.getByLabelText("Categoría funcional");
    expect(stillMounted).toBeInTheDocument();
    expect(stillMounted).toHaveValue("Creación");

    resolvePending({ items: [narrative] });
    await waitFor(() => {
      expect(screen.getByText("Narrative Proposer")).toBeInTheDocument();
    });
  });
});

describe("GlobalMethodologyLibrary — no inline detail (center view owns it)", () => {
  it("reports the clicked row upward without rendering a detail panel inline", async () => {
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
    // The full description/metadata lives in the center MethodologyDetailView;
    // the catalog list must never repeat it inline.
    expect(
      screen.queryByText("Genera propuestas narrativas coherentes con el mundo."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cerrar" }),
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
        onDeactivate={vi.fn()}
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

describe("GlobalMethodologyLibrary — page-level selection (SC-SB-2.2)", () => {
    it("reports the clicked row to onSelect (detail renders in the center view)", async () => {
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