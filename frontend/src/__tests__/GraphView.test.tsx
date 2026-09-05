import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { ComponentProps, ElementType } from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import type { EntityLink, GraphEntity, SearchResult } from "@/api/types";
import type { Mock } from "vitest";

const navigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => navigate };
});

vi.mock("@/api/graph", () => ({
  fetchGraphEntities: vi.fn(),
  createRelation: vi.fn(),
  breakRelation: vi.fn(),
  searchEntities: vi.fn(),
}));

/**
 * Holds the live React Flow instance once the graph mounts (set by the
 * onInit wrapper below) so tests can spy on viewport helpers like fitView.
 * The "mock" prefix is required: vitest hoists vi.mock factories above all
 * imports, and only mock-prefixed module variables are reachable from them.
 */
const mockFlowInstance: { instance: ReactFlowInstance | null } = {
  instance: null,
};

vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  const { createElement } = await import("react");
  const RealReactFlow = actual.ReactFlow;
  return {
    ...actual,
    // Wrap ReactFlow to capture the instance onInit receives; every other
    // prop is forwarded untouched, so rendering behavior stays identical.
    ReactFlow: (props: ComponentProps<typeof RealReactFlow>) =>
      createElement(RealReactFlow as ElementType, {
        ...props,
        onInit: (instance: ReactFlowInstance) => {
          mockFlowInstance.instance = instance;
          props.onInit?.(instance);
        },
      }),
  };
});

import {
  breakRelation,
  createRelation,
  fetchGraphEntities,
  searchEntities,
} from "@/api/graph";
import GraphView from "@/components/GraphView";

const mockFetch = fetchGraphEntities as Mock;
const mockCreateRelation = createRelation as Mock;
const mockBreakRelation = breakRelation as Mock;
const mockSearchEntities = searchEntities as Mock;

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

/** Search API result for Rhyz — matches LINKED[0] by path and name. */
const RHYZ_RESULT: SearchResult = {
  name: "Rhyz",
  type: "personaje",
  path: "personajes/Rhyz.md",
  title: "Rhyz",
  description: "Un personaje de prueba",
  tags: [],
  link_count: 1,
  score: 0.9,
};

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
    // jsdom lacks elementFromPoint; returning null makes React Flow's
    // connection validation fall back to its handleDomNode querySelector.
    document.elementFromPoint = () => null;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete (
      document as unknown as { elementFromPoint?: () => Element | null }
    ).elementFromPoint;
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

  // ── Connection UI + gated write flow (graph-connections-editor PR2) ──

  /** Connect Rhyz → Vael via React Flow click-to-connect: click the source
   *  handle (bottom) of Rhyz, then the target handle (top) of Vael. */
  async function connectRhyzToVael() {
    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(countEdges()).toBe(2));
    fireEvent.click(
      document.querySelector(
        '.react-flow__handle[data-nodeid="Stal::Rhyz"][data-handlepos="bottom"]',
      ) as Element,
    );
    fireEvent.click(
      document.querySelector(
        '.react-flow__handle[data-nodeid="Stal::Vael"][data-handlepos="top"]',
      ) as Element,
    );
  }

  it("opens the create-connection modal when a connection is made", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await connectRhyzToVael();

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent('Conectar "Rhyz" con "Vael"');
    // A connect start on a handle must never navigate to the ficha.
    expect(navigate).not.toHaveBeenCalled();
  });

  it("confirming the create modal calls createRelation and reloads the graph", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    mockCreateRelation.mockResolvedValue({
      success: true,
      path: "personajes/Rhyz.md",
      action: "create",
      target_id: "Stal::Vael",
    });
    renderGraphView();

    await connectRhyzToVael();
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: "Crear" }));

    await waitFor(() =>
      expect(mockCreateRelation).toHaveBeenCalledWith(
        "vibrantes",
        "personajes/Rhyz.md",
        "Stal::Vael",
      ),
    );
    // Initial fetch + post-write re-fetch (load()).
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("opens the break-connection modal when an edge is clicked", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(countEdges()).toBe(2));

    fireEvent.click(
      document.querySelector(
        '[data-testid="rf__edge-Stal::Rhyz->Stal::Vael"]',
      ) as Element,
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      'Romper la conexión entre "Rhyz" y "Vael"',
    );
  });

  it("confirming the break modal calls breakRelation and reloads the graph", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    mockBreakRelation.mockResolvedValue({
      success: true,
      path: "personajes/Rhyz.md",
      action: "break",
      target_id: "Stal::Vael",
    });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(countEdges()).toBe(2));

    fireEvent.click(
      document.querySelector(
        '[data-testid="rf__edge-Stal::Rhyz->Stal::Vael"]',
      ) as Element,
    );
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: "Romper" }));

    await waitFor(() =>
      expect(mockBreakRelation).toHaveBeenCalledWith(
        "vibrantes",
        "personajes/Rhyz.md",
        "Stal::Vael",
      ),
    );
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("cancelling the modal closes it without any API call", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await connectRhyzToVael();
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: "Cancelar" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(mockCreateRelation).not.toHaveBeenCalled();
    expect(mockBreakRelation).not.toHaveBeenCalled();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("shows an error toast and keeps the modal open when the write fails", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    mockCreateRelation.mockRejectedValue(new Error("La relación ya existe"));
    renderGraphView();

    await connectRhyzToVael();
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: "Crear" }));

    // Error toast (role="status") surfaces the failure…
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "La relación ya existe",
      ),
    );
    // …and the modal stays open so the author can retry or cancel.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(mockCreateRelation).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledTimes(1); // no reload on failure
  });

  // ── Node search (graph-connections-editor PR3) ──

  it("debounces the searchEntities call as the author types a node query", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    mockSearchEntities.mockResolvedValue([RHYZ_RESULT]);
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    await user.type(screen.getByLabelText("Buscar nodo"), "Rhy");
    // Inside the 300ms debounce window nothing has fired yet…
    expect(mockSearchEntities).not.toHaveBeenCalled();
    // …then the settled query is sent for the current mundo.
    await waitFor(() =>
      expect(mockSearchEntities).toHaveBeenCalledWith("vibrantes", "Rhy"),
    );
  });

  it("centers the selected search result in the viewport via fitView", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    mockSearchEntities.mockResolvedValue([RHYZ_RESULT]);
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());

    await user.type(screen.getByLabelText("Buscar nodo"), "Rhy");
    await screen.findByRole("option", { name: /Rhyz/ });

    // Ignore the initial auto-fit calls (layout settle) — only the
    // search-driven fitView matters.
    const fitViewSpy = vi.spyOn(mockFlowInstance.instance!, "fitView");
    fitViewSpy.mockClear();

    await user.click(screen.getByRole("option", { name: /Rhyz/ }));

    expect(fitViewSpy).toHaveBeenCalledWith({
      nodes: [{ id: "Stal::Rhyz" }],
      duration: 300,
    });
    // Picking a result closes the dropdown.
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("shows a no-results message and drops the dropdown when the query is emptied", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    mockSearchEntities.mockResolvedValue([]);
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    await user.type(screen.getByLabelText("Buscar nodo"), "Zzz");
    expect(await screen.findByText("Sin resultados")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Buscar nodo"));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.queryByText("Sin resultados")).not.toBeInTheDocument();
    // An empty query never fires a search request; the graph stays untouched.
    expect(mockSearchEntities).not.toHaveBeenCalledWith("vibrantes", "");
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});