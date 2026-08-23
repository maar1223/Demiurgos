import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { EntityLink, GraphEntity } from "@/api/types";
import type { Mock } from "vitest";

const navigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => navigate };
});

vi.mock("@/api/graph", () => ({
  fetchGraphEntities: vi.fn(),
}));

import { fetchGraphEntities } from "@/api/graph";
import GraphView from "@/components/GraphView";

const mockFetch = fetchGraphEntities as Mock;

/**
 * jsdom does not implement ResizeObserver; React Flow needs it on mount AND
 * needs measurement callbacks to mark nodes initialized and render edges.
 * Real ResizeObserver fires asynchronously (after mount effects set
 * domNode/nodeLookup in the store), so this mock defers each callback to a
 * macrotask and reports an 800x600 content rect (jsdom layout is 0x0).
 */
class ResizeObserverMock {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element) {
    const entry = {
      target,
      contentRect: { width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0 },
      borderBoxSize: [{ inlineSize: 800, blockSize: 600 }],
      contentBoxSize: [{ inlineSize: 800, blockSize: 600 }],
    } as unknown as ResizeObserverEntry;
    setTimeout(() => {
      this.callback([entry], this as unknown as ResizeObserver);
    }, 0);
  }

  unobserve() {}
  disconnect() {}
}

/**
 * jsdom does not implement DOMMatrixReadOnly; React Flow's
 * updateNodeInternals constructs one from the viewport transform and reads
 * m22 (zoom). Minimal shape keeps node measurement from crashing.
 */
class DOMMatrixReadOnlyMock {
  m22 = 1;
  constructor(_transform?: string) {}
}

/**
 * React Flow measures nodes via element.offsetWidth/offsetHeight
 * (getDimensions), which jsdom always reports as 0 — the isNodeInitialized
 * gate then never passes and edges never render. Give elements a real size.
 */
Object.defineProperty(globalThis.HTMLElement.prototype, "offsetWidth", {
  configurable: true,
  get: () => 150,
});
Object.defineProperty(globalThis.HTMLElement.prototype, "offsetHeight", {
  configurable: true,
  get: () => 40,
});

/** Three linked entities (2 edges) — Dottua receives a backlink from Vael. */
const LINKED: GraphEntity[] = [
  {
    id: "Stal::Rhyz",
    name: "Rhyz",
    type: "personaje",
    path: "personajes/Rhyz.md",
    status: "stable",
    content: "",
    forward_links: ["Vael"],
    backlinks: [],
    relaciones: [],
  },
  {
    id: "Stal::Vael",
    name: "Vael",
    type: "personaje",
    path: "personajes/Vael.md",
    status: "draft",
    content: "",
    forward_links: ["Dottua"],
    backlinks: ["personajes/Rhyz.md"],
    relaciones: [],
  },
  {
    id: "Origen::Dottua",
    name: "Dottua",
    type: "lugar",
    path: "lore/Dottua.md",
    status: "stable",
    content: "",
    forward_links: [],
    backlinks: ["personajes/Vael.md"],
    relaciones: [],
  },
];

const LINKS: EntityLink[] = [
  { source: "Stal::Rhyz", target: "Stal::Vael", kind: "forward" },
  { source: "Stal::Vael", target: "Origen::Dottua", kind: "forward" },
];

/** LINKED plus a true orphan (no forward AND no backlinks). */
const WITH_ORPHAN: GraphEntity[] = [
  ...LINKED,
  {
    id: "Cultura::Ecos",
    name: "Ecos",
    type: "cultura",
    path: "lore/Ecos.md",
    status: "draft",
    content: "",
    forward_links: [],
    backlinks: [],
    relaciones: [],
  },
];

function renderGraphView() {
  return render(
    <MemoryRouter>
      <GraphView mundo="vibrantes" />
    </MemoryRouter>,
  );
}

function countNodes(): number {
  return document.querySelectorAll(".react-flow__node").length;
}

function countEdges(): number {
  return document.querySelectorAll(".react-flow__edge").length;
}

describe("GraphView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
    vi.stubGlobal("DOMMatrixReadOnly", DOMMatrixReadOnlyMock);
    vi.stubGlobal("DOMMatrix", DOMMatrixReadOnlyMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders nodes and edges from entities and links", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    // Edges render after React Flow measures the nodes (async observer).
    await waitFor(() => expect(countEdges()).toBe(2));
    expect(screen.getByText("Rhyz")).toBeInTheDocument();
    expect(screen.getByText("Vael")).toBeInTheDocument();
    expect(screen.getByText("Dottua")).toBeInTheDocument();
  });

  it("colors nodes by status via STATUS_META tokens", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    // stable → emerald token; draft → amber token (STATUS_META chipClass).
    const rhyz = screen.getByText("Rhyz").closest(".react-flow__node");
    expect(rhyz).toHaveClass("border-emerald-500/60");
    const vael = screen.getByText("Vael").closest(".react-flow__node");
    expect(vael).toHaveClass("border-amber-400/50");
  });

  it("re-fetches with the selected status filter", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    expect(mockFetch).toHaveBeenCalledWith("vibrantes", "all");

    await user.selectOptions(
      screen.getByLabelText("Filtrar por estado"),
      "stable",
    );

    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith("vibrantes", "stable"),
    );
  });

  it("hides orphan nodes by default and reveals them with the toggle", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: WITH_ORPHAN, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    expect(screen.queryByText("Ecos")).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("Mostrar nodos aislados"));

    await waitFor(() => expect(countNodes()).toBe(4));
    expect(screen.getByText("Ecos")).toBeInTheDocument();
  });

  it("navigates to the ficha route when a node is clicked", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    // fireEvent.click dispatches ONLY "click" — userEvent's full pointer
    // sequence trips React Flow's d3-drag mousedown handler, which reads
    // event.view.document and crashes in jsdom (event.view is null).
    fireEvent.click(screen.getByText("Rhyz"));

    expect(navigate).toHaveBeenCalledWith(
      "/wiki/vibrantes/entity/personajes/Rhyz.md",
    );
  });

  it("shows an error banner with retry when the fetch fails", async () => {
    const user = userEvent.setup();
    mockFetch.mockRejectedValueOnce(new Error("El servidor no respondió"));
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    expect(
      await screen.findByText("El servidor no respondió"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("graph-view")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reintentar" }));

    await waitFor(() => expect(countNodes()).toBe(3));
  });

  it("shows an empty state when the world has no entities", async () => {
    mockFetch.mockResolvedValue({ entities: [], links: [] });
    renderGraphView();

    expect(
      await screen.findByText("No hay entidades indexadas para este mundo."),
    ).toBeInTheDocument();
  });

  it("renders the referencias-exclusion note (FR2.13)", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    expect(
      screen.getByText("El grafo no incluye contenido de Referencias"),
    ).toBeInTheDocument();
  });
});