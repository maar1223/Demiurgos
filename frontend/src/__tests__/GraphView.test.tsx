import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  act,
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from "@testing-library/react";
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

/** Latest props the component handed to React Flow (drag callbacks etc.). */
const mockFlowProps: { current: Record<string, unknown> | null } = {
  current: null,
};

vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  const { createElement } = await import("react");
  const RealReactFlow = actual.ReactFlow;
  return {
    ...actual,
    // Wrap ReactFlow to capture the instance onInit receives; every other
    // prop is forwarded untouched, so rendering behavior stays identical.
    ReactFlow: (props: ComponentProps<typeof RealReactFlow>) => {
      mockFlowProps.current = props as unknown as Record<string, unknown>;
      return createElement(RealReactFlow as ElementType, {
        ...props,
        onInit: (instance: ReactFlowInstance) => {
          mockFlowInstance.instance = instance;
          props.onInit?.(instance);
        },
      });
    },
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
/** React Flow measures its canvas pane through offsetWidth/offsetHeight; a
 *  node-sized container would clamp fitView to minZoom and make the graph look
 *  permanently zoomed out. Give the pane real viewport dimensions. */
function isFlowCanvas(element: HTMLElement): boolean {
  const list = element.classList;
  return (
    !!list &&
    (list.contains("react-flow") ||
      list.contains("react-flow__pane") ||
      list.contains("react-flow__renderer"))
  );
}

Object.defineProperty(globalThis.HTMLElement.prototype, "offsetWidth", {
  configurable: true,
  get() {
    return isFlowCanvas(this as HTMLElement) ? 800 : 150;
  },
});
Object.defineProperty(globalThis.HTMLElement.prototype, "offsetHeight", {
  configurable: true,
  get() {
    return isFlowCanvas(this as HTMLElement) ? 600 : 40;
  },
});

/** Three linked entities (2 edges) — Gamma receives a backlink from Bravo. */
const LINKED: GraphEntity[] = [
  {
    id: "Grupo::Alfa",
    name: "Alfa",
    type: "personaje",
    path: "personajes/Alfa.md",
    status: "stable",
    content: "",
    forward_links: ["Bravo"],
    backlinks: [],
    relaciones: [],
  },
  {
    id: "Grupo::Bravo",
    name: "Bravo",
    type: "personaje",
    path: "personajes/Bravo.md",
    status: "draft",
    content: "",
    forward_links: ["Gamma"],
    backlinks: ["personajes/Alfa.md"],
    relaciones: [],
  },
  {
    id: "Lugar::Gamma",
    name: "Gamma",
    type: "lugar",
    path: "lore/Gamma.md",
    status: "stable",
    content: "",
    forward_links: [],
    backlinks: ["personajes/Bravo.md"],
    relaciones: [],
  },
];

const LINKS: EntityLink[] = [
  { source: "Grupo::Alfa", target: "Grupo::Bravo", kind: "forward" },
  { source: "Grupo::Bravo", target: "Lugar::Gamma", kind: "forward" },
];

/** Search API result for Alfa — matches LINKED[0] by path and name. */
const ALFA_RESULT: SearchResult = {
  name: "Alfa",
  type: "personaje",
  path: "personajes/Alfa.md",
  title: "Alfa",
  description: "Un personaje de prueba",
  tags: [],
  link_count: 1,
  score: 0.9,
};

/** LINKED plus a true orphan (no forward AND no backlinks). */
const WITH_ORPHAN: GraphEntity[] = [
  ...LINKED,
  {
    id: "Grupo::Epsilon",
    name: "Epsilon",
    type: "cultura",
    path: "lore/Epsilon.md",
    status: "draft",
    content: "",
    forward_links: [],
    backlinks: [],
    relaciones: [],
  },
];

/** Self-contained fixture for the empty-section scenario: a "lore" folder
 *  whose ONLY entity is an orphan (no forward AND no back links). Selecting
 *  "lore" therefore renders zero visible nodes (orphans hidden by default)
 *  and must show the empty-section message. Gamma lives in "lugares" so it
 *  never leaks into the lore selection. */
const WITH_FOLDER_ONLY_ORPHAN: GraphEntity[] = [
  ...LINKED.map((entity) =>
    entity.id === "Lugar::Gamma"
      ? { ...entity, path: "lugares/Gamma.md" }
      : entity,
  ),
  {
    id: "Grupo::Zeta",
    name: "Zeta",
    type: "cultura",
    path: "lore/Zeta.md",
    status: "draft",
    content: "",
    forward_links: [],
    backlinks: [],
    relaciones: [],
  },
];

/** LINKED plus a nested entity under lore/historia — exercises the tree's
 *  nested rendering and the folder filter's prefix reach into subfolders.
 *  Delta carries a backlink so it is never hidden as an orphan. */
const WITH_NESTED: GraphEntity[] = [
  ...LINKED,
  {
    id: "Lugar::Delta",
    name: "Delta",
    type: "lugar",
    path: "lore/historia/Delta.md",
    status: "draft",
    content: "",
    forward_links: [],
    backlinks: ["personajes/Alfa.md"],
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

/** Stub `prefers-reduced-motion` (and every other media query) for a test. */
function stubMotionPreference(reduced: boolean): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: reduced && query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

/**
 * Replace requestAnimationFrame with a manual queue so the live layout only
 * advances when the test says so — no wall-clock waits, no act() warnings.
 */
function stubAnimationFrames() {
  const frames: FrameRequestCallback[] = [];
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    frames.push(callback);
    return frames.length;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
  const flush = (count = 1) => {
    for (let index = 0; index < count; index += 1) {
      const frame = frames.shift();
      if (!frame) return;
      frame(0);
    }
  };
  return { frames, flush };
}

type DragHandler = (
  event: unknown,
  node: { id: string; position: { x: number; y: number } },
) => void;

function dragHandler(name: "onNodeDragStart" | "onNodeDrag" | "onNodeDragStop"): DragHandler | undefined {
  return mockFlowProps.current?.[name] as DragHandler | undefined;
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
    expect(screen.getByText("Alfa")).toBeInTheDocument();
    expect(screen.getByText("Bravo")).toBeInTheDocument();
    expect(screen.getByText("Gamma")).toBeInTheDocument();
  });

  it("cools the layout down through the React Flow instance when motion is allowed", async () => {
    stubMotionPreference(false);
    const { flush } = stubAnimationFrames();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());
    const instance = mockFlowInstance.instance!;
    const before = new Map(
      instance.getNodes().map((node) => [node.id, { ...node.position }]),
    );

    act(() => flush(8));

    // S1/S2: the simulation advanced and wrote positions into the store
    // without the view re-seeding the node array from React state.
    const moved = instance
      .getNodes()
      .some((node) => {
        const start = before.get(node.id);
        return (
          !!start &&
          (node.position.x !== start.x || node.position.y !== start.y)
        );
      });
    expect(moved).toBe(true);
  });

  it("settles instantly and never animates under prefers-reduced-motion", async () => {
    stubMotionPreference(true);
    const { frames, flush } = stubAnimationFrames();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());
    const instance = mockFlowInstance.instance!;
    const setNodesSpy = vi.spyOn(instance, "setNodes");

    // Only the one-shot fitView frame exists; the simulation never scheduled
    // a frame of its own (S3).
    expect(frames.length).toBeLessThanOrEqual(1);
    act(() => flush(10));
    expect(setNodesSpy).not.toHaveBeenCalled();
  });

  it("collapses the floating filters into a pill and restores them", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();
    await waitFor(() => expect(countNodes()).toBe(3));

    await user.click(screen.getByRole("button", { name: "Ocultar filtros" }));
    expect(
      screen.queryByLabelText("Filtrar por estado"),
    ).not.toBeInTheDocument();
    const pill = screen.getByRole("button", { name: "Mostrar filtros" });
    expect(pill).toHaveTextContent("Filtros");

    await user.click(pill);
    expect(screen.getByLabelText("Filtrar por estado")).toBeInTheDocument();
  });

  it("floats the controls and the inspector over the full canvas surface", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    const surface = screen.getByTestId("graph-surface");
    const canvas = within(surface).getByTestId("graph-view");

    // S4: the canvas fills the surface; the controls overlay it (absolute)
    // instead of taking a column away from it.
    expect(canvas.className).toContain("h-full");
    expect(screen.getByRole("complementary")).toHaveClass("absolute");
    expect(
      within(surface).getByLabelText("Filtrar por estado"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByText("Alfa"));
    await screen.findByTestId("node-inspector-panel");
    expect(
      within(canvas).getByTestId("node-inspector-panel"),
    ).toBeInTheDocument();
  });

  it("leaves the canvas unbounded: nodes are not clamped to an extent", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();
    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());
    const instance = mockFlowInstance.instance!;

    // No per-node extent: the author can drag a card anywhere on the map.
    expect(instance.getNodes().every((node) => node.extent === undefined)).toBe(
      true,
    );

    const start = dragHandler("onNodeDragStart");
    const drag = dragHandler("onNodeDrag");
    const stop = dragHandler("onNodeDragStop");
    act(() => {
      start!(null, { id: "Grupo::Alfa", position: { x: 9000, y: 7000 } });
      drag!(null, { id: "Grupo::Alfa", position: { x: 9000, y: 7000 } });
      stop!(null, { id: "Grupo::Alfa", position: { x: 9000, y: 7000 } });
    });
    const dropped = instance
      .getNodes()
      .find((node) => node.id === "Grupo::Alfa")!;
    expect(dropped.position.x).toBeGreaterThan(8000);
    expect(dropped.position.y).toBeGreaterThan(6000);
  });

  it("pins a dragged node and re-heats its neighbours", async () => {
    stubMotionPreference(false);
    const { flush } = stubAnimationFrames();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());
    const instance = mockFlowInstance.instance!;

    // Let the initial cooling finish, so the drag is what moves the graph.
    act(() => flush(400));
    const before = new Map(
      instance.getNodes().map((node) => [node.id, { ...node.position }]),
    );

    const start = dragHandler("onNodeDragStart");
    const drag = dragHandler("onNodeDrag");
    expect(start).toBeTypeOf("function");
    expect(drag).toBeTypeOf("function");

    act(() => {
      start!(null, { id: "Grupo::Alfa", position: { x: 40, y: 40 } });
      drag!(null, { id: "Grupo::Alfa", position: { x: 40, y: 40 } });
      flush(6);
    });

    const after = instance.getNodes();
    // The dragged node stays exactly where the author dropped it…
    expect(after.find((node) => node.id === "Grupo::Alfa")?.position).toEqual({
      x: 40,
      y: 40,
    });
    // …and its neighbours react to the new pin.
    const neighbourMoved = after.some((node) => {
      if (node.id === "Grupo::Alfa") return false;
      const startPosition = before.get(node.id);
      return (
        !!startPosition &&
        (node.position.x !== startPosition.x ||
          node.position.y !== startPosition.y)
      );
    });
    expect(neighbourMoved).toBe(true);
  });

  it("labels folder sections while zoomed out and hides them up close", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());
    const instance = mockFlowInstance.instance!;

    await act(async () => {
      await instance.setViewport({ x: 0, y: 0, zoom: 0.7 });
    });
    // personajes holds Alfa + Bravo → one cluster; lore holds only Gamma, so
    // a lone entity never reads as a section (S7).
    await waitFor(() => {
      const labels = screen.getAllByTestId("graph-cluster");
      expect(labels).toHaveLength(1);
      expect(labels[0]).toHaveTextContent("personajes");
    });

    // Up close the cards are the reference; the soft labels would only add
    // noise over them.
    await act(async () => {
      await instance.setViewport({ x: 0, y: 0, zoom: 1.2 });
    });
    await waitFor(() =>
      expect(screen.queryByTestId("graph-cluster")).not.toBeInTheDocument(),
    );
  });

  it("never re-settles the map when a name is revealed or hidden", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();
    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());
    const instance = mockFlowInstance.instance!;
    const positions = () =>
      new Map(
        instance.getNodes().map((node) => [node.id, { ...node.position }]),
      );
    const expectStable = (before: Map<string, { x: number; y: number }>) => {
      for (const [id, position] of before) {
        expect(positions().get(id)).toEqual(position);
      }
    };

    // Compact band: non-hub names are hidden until focused.
    await act(async () => {
      await instance.setViewport({ x: 0, y: 0, zoom: 0.7 });
    });
    const before = positions();

    fireEvent.mouseEnter(document.querySelector('[data-id="Grupo::Alfa"]')!);
    await waitFor(() => expect(screen.getByText("Alfa")).toBeInTheDocument());
    // The card got wider to fit the name; the layout must not react.
    await new Promise((resolve) => setTimeout(resolve, 60));
    expectStable(before);

    fireEvent.mouseLeave(document.querySelector('[data-id="Grupo::Alfa"]')!);
    await waitFor(() =>
      expect(screen.queryByText("Alfa")).not.toBeInTheDocument(),
    );
    await new Promise((resolve) => setTimeout(resolve, 60));
    expectStable(before);
  });

  it("shows only each folder's main name in the middle zoom band until a node is focused", async () => {
    // Centro is a hub (5 connections); Ana is not.
    const spokes = ["Ana", "Bran", "Cael", "Dara", "Elen"];
    const HUB_WORLD: GraphEntity[] = [
      {
        id: "Hub::Centro",
        name: "Centro",
        type: "concepto",
        path: "lore/Centro.md",
        status: "stable",
        content: "",
        forward_links: spokes,
        backlinks: [],
        relaciones: [],
      },
      ...spokes.map((name) => ({
        id: `Hub::${name}`,
        name,
        type: "personaje",
        path: `personajes/${name}.md`,
        status: "draft" as const,
        content: "",
        forward_links: [],
        backlinks: ["lore/Centro.md"],
        relaciones: [],
      })),
    ];
    const HUB_LINKS: EntityLink[] = spokes.map((name) => ({
      source: "Hub::Centro",
      target: `Hub::${name}`,
      kind: "forward",
    }));
    mockFetch.mockResolvedValue({ entities: HUB_WORLD, links: HUB_LINKS });
    renderGraphView();
    await waitFor(() => expect(countNodes()).toBe(6));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());
    const instance = mockFlowInstance.instance!;

    await act(async () => {
      await instance.setViewport({ x: 0, y: 0, zoom: 0.7 });
    });
    await waitFor(() => {
      // Centro is alone in "lore" so it is that group's main and keeps its
      // name; the spokes share "personajes", where only the hierarchy main
      // (Ana, by the deterministic tiebreak) shows its name.
      expect(screen.getByText("Centro")).toBeInTheDocument();
      expect(screen.getByText("Ana")).toBeInTheDocument();
      expect(screen.queryByText("Bran")).not.toBeInTheDocument();
    });

    // Hovering the hub reveals its neighbourhood's names.
    fireEvent.mouseEnter(
      document.querySelector('[data-id="Hub::Centro"]')!,
    );
    await waitFor(() => expect(screen.getByText("Ana")).toBeInTheDocument());
    expect(screen.getByText("Bran")).toBeInTheDocument();
  });

  it("labels only the folder main when several nodes clear the hub threshold", async () => {
    // Alfa (6 links) and Zeta (5) are both hubs, so the old per-node rule
    // labelled both; the hierarchy picks Alfa as the folder main and Zeta is
    // revealed only on focus (L22).
    const peers = ["n1", "n2", "n3", "n4", "n5", "n6"];
    const ALFA_ENTITY: GraphEntity = {
      id: "Fam::Alfa",
      name: "Alfa",
      type: "concepto",
      path: "familia/Alfa.md",
      status: "stable",
      content: "",
      forward_links: peers,
      backlinks: [],
      relaciones: [],
    };
    const ZETA_ENTITY: GraphEntity = {
      id: "Fam::Zeta",
      name: "Zeta",
      type: "concepto",
      path: "familia/Zeta.md",
      status: "draft",
      content: "",
      forward_links: peers.slice(0, 5),
      backlinks: [],
      relaciones: [],
    };
    const PEERS: GraphEntity[] = peers.map((name) => ({
      id: `Fam::${name}`,
      name,
      type: "concepto",
      path: `familia/${name}.md`,
      status: "draft" as const,
      content: "",
      forward_links: [],
      backlinks: ["familia/Alfa.md"],
      relaciones: [],
    }));
    const links: EntityLink[] = [
      ...peers.map((name) => ({
        source: "Fam::Alfa",
        target: `Fam::${name}`,
        kind: "forward" as const,
      })),
      ...peers.slice(0, 5).map((name) => ({
        source: "Fam::Zeta",
        target: `Fam::${name}`,
        kind: "forward" as const,
      })),
    ];
    mockFetch.mockResolvedValue({
      entities: [ALFA_ENTITY, ZETA_ENTITY, ...PEERS],
      links,
    });
    renderGraphView();
    await waitFor(() => expect(countNodes()).toBe(8));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());
    const instance = mockFlowInstance.instance!;

    await act(async () => {
      await instance.setViewport({ x: 0, y: 0, zoom: 0.7 });
    });
    await waitFor(() => {
      expect(screen.getByText("Alfa")).toBeInTheDocument();
      expect(screen.queryByText("Zeta")).not.toBeInTheDocument();
      expect(screen.queryByText("n1")).not.toBeInTheDocument();
    });

    // Focusing Zeta reveals its name as a floating tag and lifts the node so
    // the tag is not painted under the neighbour cards.
    fireEvent.mouseEnter(document.querySelector('[data-id="Fam::Zeta"]')!);
    await waitFor(() => expect(screen.getByText("Zeta")).toBeInTheDocument());
    await waitFor(() =>
      expect(
        instance.getNodes().find((node) => node.id === "Fam::Zeta")?.zIndex,
      ).toBe(1000),
    );
    expect(
      instance.getNodes().find((node) => node.id === "Fam::Alfa")?.zIndex,
    ).toBe(0);
  });

  it("collapses nodes to status dots below the semantic-zoom threshold", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());
    const instance = mockFlowInstance.instance!;

    await act(async () => {
      await instance.setViewport({ x: 0, y: 0, zoom: 0.3 });
    });
    await waitFor(() =>
      expect(screen.getAllByTestId("graph-node-dot")).toHaveLength(3),
    );
    expect(
      screen.queryByTestId("graph-node-card"),
    ).not.toBeInTheDocument();

    await act(async () => {
      await instance.setViewport({ x: 0, y: 0, zoom: 1.1 });
    });
    await waitFor(() =>
      expect(screen.getAllByTestId("graph-node-card")).toHaveLength(3),
    );
    expect(screen.queryByTestId("graph-node-dot")).not.toBeInTheDocument();
  });

  it("draws curved, quiet edges with no arrowheads", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();
    await waitFor(() => expect(countEdges()).toBe(2));

    const paths = [
      ...document.querySelectorAll<SVGPathElement>(".react-flow__edge-path"),
    ];
    expect(paths).toHaveLength(2);
    for (const path of paths) {
      // Cubic bezier curve, never three straight points…
      expect(path.getAttribute("d")).toMatch(/C/);
      // …and direction is out of scope (L2): no arrowhead markers.
      expect(path.getAttribute("marker-end")).toBeNull();
      expect(path.style.strokeWidth).toBe("1.1");
      expect(Number(path.style.opacity)).toBeCloseTo(0.22, 2);
    }
  });

  it("anchors edges at node centres, not at the top/bottom handles", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();
    await waitFor(() => expect(countEdges()).toBe(2));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());

    await waitFor(() => {
      const centres = mockFlowInstance.instance!.getNodes().map((node) => ({
        x: node.position.x + (node.measured?.width ?? 150) / 2,
        y: node.position.y + (node.measured?.height ?? 40) / 2,
      }));
      const paths = [
        ...document.querySelectorAll<SVGPathElement>(".react-flow__edge-path"),
      ];
      expect(paths).toHaveLength(2);
      for (const path of paths) {
        const match = /^M\s*([-\d.]+),([-\d.]+)/.exec(
          path.getAttribute("d") ?? "",
        );
        expect(match).not.toBeNull();
        const x = Number(match![1]);
        const y = Number(match![2]);
        // One end sits on a node centre; the old top/bottom handles put it on
        // a card border instead, which is what made links loop around cards.
        const anchored = centres.some(
          (centre) => Math.abs(centre.x - x) < 2 && Math.abs(centre.y - y) < 2,
        );
        expect(anchored).toBe(true);
      }
    });
  });

  it("thickens a pair with more than one relation and highlights it on hover", async () => {
    // Alfa ↔ Bravo has two relation records (forward + back), so it must read
    // heavier than Bravo → Gamma, which has one.
    mockFetch.mockResolvedValue({
      entities: LINKED,
      links: [
        ...LINKS,
        { source: "Grupo::Bravo", target: "Grupo::Alfa", kind: "forward" },
      ],
    });
    renderGraphView();
    await waitFor(() => expect(countEdges()).toBe(2));

    const paths = () => [
      ...document.querySelectorAll<SVGPathElement>(".react-flow__edge-path"),
    ];
    const [heavier, lighter] = paths();
    expect(Number(heavier.style.strokeWidth)).toBeGreaterThan(
      Number(lighter.style.strokeWidth),
    );

    // Hovering Alfa lights its curve and lets the unrelated one recede.
    fireEvent.mouseEnter(screen.getByText("Alfa").closest(".react-flow__node")!);
    await waitFor(() => {
      const [highlighted, dimmed] = paths();
      expect(highlighted.style.opacity).toBe("0.85");
      expect(dimmed.style.opacity).toBe("0.05");
    });

    // Its neighbour stays legible; the unrelated card recedes too.
    const card = (name: string) =>
      screen.getByText(name).closest('[data-testid="graph-node-card"]')!;
    expect(card("Bravo")).not.toHaveClass("opacity-30");
    expect(card("Gamma")).toHaveClass("opacity-30");
  });

  it("isolates a neighbourhood and leaves it with Escape", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();
    await waitFor(() => expect(countNodes()).toBe(3));

    fireEvent.click(screen.getByText("Alfa"));
    fireEvent.click(await screen.findByTestId("isolate-neighborhood"));

    // Alfa + Bravo only: Gamma is two hops away.
    await waitFor(() => expect(countNodes()).toBe(2));
    expect(screen.getByTestId("isolation-pill")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(countNodes()).toBe(3));
    expect(screen.queryByTestId("isolation-pill")).not.toBeInTheDocument();
  });

  it("reads canon through fill, ring and a status dot, never border colour alone", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    const card = (name: string) =>
      screen.getByText(name).closest('[data-testid="graph-node-card"]')!;

    // S6: canon is fill + ring + dot; the border stays neutral on purpose.
    const rhyz = card("Alfa");
    expect(rhyz).toHaveAttribute("data-canon", "stable");
    expect(rhyz).toHaveClass("ring-emerald-500/60", "bg-emerald-500/10");
    expect(rhyz).toHaveClass("border-edge");
    expect(rhyz.querySelector('[data-testid="canon-dot"]')).toHaveClass(
      "bg-emerald-500",
    );

    const vael = card("Bravo");
    expect(vael).toHaveAttribute("data-canon", "draft");
    expect(vael).toHaveClass("ring-amber-400/60", "bg-amber-400/10");
    expect(vael.querySelector('[data-testid="canon-dot"]')).toHaveClass(
      "bg-amber-500",
    );
  });

  it("shows the entity type icon and sizes nodes by connection degree", async () => {
    const user = userEvent.setup();
    const spokes = ["Ana", "Bran", "Cael", "Dara", "Elen"];
    const HUB_WORLD: GraphEntity[] = [
      {
        id: "Hub::Centro",
        name: "Centro",
        type: "concepto",
        path: "lore/Centro.md",
        status: "stable",
        content: "",
        forward_links: spokes,
        backlinks: [],
        relaciones: [],
      },
      ...spokes.map((name) => ({
        id: `Hub::${name}`,
        name,
        type: "personaje",
        path: `personajes/${name}.md`,
        status: "draft" as const,
        content: "",
        forward_links: [],
        backlinks: ["lore/Centro.md"],
        relaciones: [],
      })),
      {
        id: "Hub::Solo",
        name: "Solo",
        type: "objeto",
        path: "lore/Solo.md",
        status: "draft" as const,
        content: "",
        forward_links: [],
        backlinks: [],
        relaciones: [],
      },
    ];
    const HUB_LINKS: EntityLink[] = spokes.map((name) => ({
      source: "Hub::Centro",
      target: `Hub::${name}`,
      kind: "forward",
    }));
    mockFetch.mockResolvedValue({ entities: HUB_WORLD, links: HUB_LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(6));
    const card = (name: string) =>
      screen.getByText(name).closest('[data-testid="graph-node-card"]')!;

    expect(card("Centro")).toHaveAttribute("data-tier", "hub");
    expect(card("Ana")).toHaveAttribute("data-tier", "node");
    expect(
      card("Centro").querySelector('[data-testid="node-type-icon"]'),
    ).toHaveAttribute("data-icon", "lightbulb");

    await user.click(screen.getByLabelText("Mostrar nodos aislados"));
    await waitFor(() => expect(countNodes()).toBe(7));
    expect(card("Solo")).toHaveAttribute("data-tier", "leaf");
    expect(
      card("Solo").querySelector('[data-testid="node-type-icon"]'),
    ).toHaveAttribute("data-icon", "file");
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
    expect(screen.queryByText("Epsilon")).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("Mostrar nodos aislados"));

    await waitFor(() => expect(countNodes()).toBe(4));
    expect(screen.getByText("Epsilon")).toBeInTheDocument();
  });

  it("selects a node and opens the inspector panel instead of navigating", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    // fireEvent.click dispatches ONLY "click" — userEvent's full pointer
    // sequence trips React Flow's d3-drag mousedown handler, which reads
    // event.view.document and crashes in jsdom (event.view is null).
    fireEvent.click(screen.getByText("Alfa"));

    // Selection opens the panel with Alfa's data…
    await waitFor(() =>
      expect(screen.getByTestId("node-inspector-panel")).toBeInTheDocument(),
    );
    expect(screen.getByRole("heading", { name: "Alfa" })).toBeInTheDocument();
    // …and the URL does NOT change (no navigation on node click).
    expect(navigate).not.toHaveBeenCalled();
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
    // The sidebar still renders (with an empty folder tree) so the empty
    // state is never an untrappable UI dead-end.
    expect(
      screen.getByRole("button", { name: "Todas las secciones" }),
    ).toBeInTheDocument();
  });

  // ── Connection UI + gated write flow (graph-connections-editor PR2) ──

  /** Connect Alfa → Bravo via React Flow click-to-connect: click the source
   *  handle (bottom) of Alfa, then the target handle (top) of Bravo. */
  async function connectAlfaToBravo() {
    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(countEdges()).toBe(2));
    fireEvent.click(
      document.querySelector(
        '.react-flow__handle[data-nodeid="Grupo::Alfa"][data-handlepos="bottom"]',
      ) as Element,
    );
    fireEvent.click(
      document.querySelector(
        '.react-flow__handle[data-nodeid="Grupo::Bravo"][data-handlepos="top"]',
      ) as Element,
    );
  }

  it("opens the create-connection modal when a connection is made", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await connectAlfaToBravo();

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent('Conectar "Alfa" con "Bravo"');
    // A connect start on a handle must never navigate to the ficha.
    expect(navigate).not.toHaveBeenCalled();
  });

  it("confirming the create modal calls createRelation and reloads the graph", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    mockCreateRelation.mockResolvedValue({
      success: true,
      path: "personajes/Alfa.md",
      action: "create",
      target_id: "Grupo::Bravo",
    });
    renderGraphView();

    await connectAlfaToBravo();
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: "Crear" }));

    await waitFor(() =>
      expect(mockCreateRelation).toHaveBeenCalledWith(
        "vibrantes",
        "personajes/Alfa.md",
        "Grupo::Bravo",
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
        '[data-testid="rf__edge-Grupo::Alfa->Grupo::Bravo"]',
      ) as Element,
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      'Romper la conexión entre "Alfa" y "Bravo"',
    );
  });

  it("confirming the break modal calls breakRelation and reloads the graph", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    mockBreakRelation.mockResolvedValue({
      success: true,
      path: "personajes/Alfa.md",
      action: "break",
      target_id: "Grupo::Bravo",
    });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(countEdges()).toBe(2));

    fireEvent.click(
      document.querySelector(
        '[data-testid="rf__edge-Grupo::Alfa->Grupo::Bravo"]',
      ) as Element,
    );
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: "Romper" }));

    await waitFor(() =>
      expect(mockBreakRelation).toHaveBeenCalledWith(
        "vibrantes",
        "personajes/Alfa.md",
        "Grupo::Bravo",
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

    await connectAlfaToBravo();
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

    await connectAlfaToBravo();
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
    mockSearchEntities.mockResolvedValue([ALFA_RESULT]);
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
    mockSearchEntities.mockResolvedValue([ALFA_RESULT]);
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());

    await user.type(screen.getByLabelText("Buscar nodo"), "Rhy");
    await screen.findByRole("option", { name: /Alfa/ });

    // Ignore the initial auto-fit calls (layout settle) — only the
    // search-driven fitView matters.
    const fitViewSpy = vi.spyOn(mockFlowInstance.instance!, "fitView");
    fitViewSpy.mockClear();

    await user.click(screen.getByRole("option", { name: /Alfa/ }));

    expect(fitViewSpy).toHaveBeenCalledWith({
      nodes: [{ id: "Grupo::Alfa" }],
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

  // ── Folder filter (graph-controls-sidebar PR3: hierarchical tree) ──

  it("renders the hierarchical folder tree from the entity paths", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: WITH_NESTED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(4));

    // The flat "Sección" dropdown is gone: level-1 folders render as tree
    // checkboxes, plus the clear-selection button.
    expect(screen.getByRole("checkbox", { name: "lore" })).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "personajes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Todas las secciones" }),
    ).toBeInTheDocument();

    // Nested folders are hidden inside their collapsed parent…
    expect(
      screen.queryByRole("checkbox", { name: "historia" }),
    ).not.toBeInTheDocument();
    // …and appear once the parent is expanded.
    await user.click(screen.getByRole("button", { name: "Expandir lore" }));
    expect(
      screen.getByRole("checkbox", { name: "historia" }),
    ).toBeInTheDocument();
  });

  it("selecting a folder in the tree filters the canvas to its prefix", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(countEdges()).toBe(2));

    await user.click(screen.getByRole("checkbox", { name: "personajes" }));

    // Gamma (lore/) is hidden along with the Bravo→Gamma edge; Alfa→Bravo
    // survives because both endpoints share the selected folder.
    await waitFor(() => expect(countNodes()).toBe(2));
    await waitFor(() => expect(countEdges()).toBe(1));
    expect(screen.getByText("Alfa")).toBeInTheDocument();
    expect(screen.getByText("Bravo")).toBeInTheDocument();
    expect(screen.queryByText("Gamma")).not.toBeInTheDocument();
    // A filter that still has nodes is never an empty section.
    expect(
      screen.queryByText("Esta sección no tiene nodos para mostrar."),
    ).not.toBeInTheDocument();
  });

  it("multi-select union shows entities from every selected folder", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: WITH_NESTED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(4));

    // Selecting "lore" alone shows lore/** — including the nested historia
    // entity (prefix semantics reach into subfolders).
    await user.click(screen.getByRole("checkbox", { name: "lore" }));
    await waitFor(() => expect(countNodes()).toBe(2));
    expect(screen.getByText("Gamma")).toBeInTheDocument();
    expect(screen.getByText("Delta")).toBeInTheDocument();

    // Adding "personajes" is a union: entities from both folders show.
    await user.click(screen.getByRole("checkbox", { name: "personajes" }));
    await waitFor(() => expect(countNodes()).toBe(4));
    expect(screen.getByText("Alfa")).toBeInTheDocument();
    expect(screen.getByText("Bravo")).toBeInTheDocument();
  });

  it('restores every node and edge via "Todas las secciones"', async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(countEdges()).toBe(2));

    await user.click(screen.getByRole("checkbox", { name: "personajes" }));
    await waitFor(() => expect(countNodes()).toBe(2));

    await user.click(
      screen.getByRole("button", { name: "Todas las secciones" }),
    );

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(countEdges()).toBe(2));
    expect(screen.getByText("Gamma")).toBeInTheDocument();
  });

  it("shows the empty-section message when the folder has no visible nodes", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({
      entities: WITH_FOLDER_ONLY_ORPHAN,
      links: LINKS,
    });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    await user.click(screen.getByRole("checkbox", { name: "lore" }));

    // Zeta is the only lore/ entity and it is an orphan (hidden by default),
    // so the section renders no nodes and shows the empty-section message.
    await waitFor(() => expect(countNodes()).toBe(0));
    expect(
      screen.getByText("Esta sección no tiene nodos para mostrar."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No hay entidades indexadas para este mundo."),
    ).not.toBeInTheDocument();
  });

  // ── Node inspector (graph-node-inspector PR3: selection + panel) ──

  it("does not render the inspector before any node is selected", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    expect(
      screen.queryByTestId("node-inspector-panel"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("separator", {
        name: "Redimensionar panel de inspección",
      }),
    ).not.toBeInTheDocument();
  });

  it("does not select a node when the click starts on a connection handle", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    // A click on a handle is click-to-connect, never selection.
    fireEvent.click(
      document.querySelector(
        '.react-flow__handle[data-nodeid="Grupo::Alfa"][data-handlepos="bottom"]',
      ) as Element,
    );

    expect(
      screen.queryByTestId("node-inspector-panel"),
    ).not.toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("clicking a different node replaces the selection", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    fireEvent.click(screen.getByText("Alfa"));
    await screen.findByTestId("node-inspector-panel");
    expect(screen.getByRole("heading", { name: "Alfa" })).toBeInTheDocument();

    // Click the Bravo NODE (the panel already renders a "Bravo" neighbor link,
    // so the click must target the graph node label, not the panel).
    fireEvent.click(
      document.querySelector(
        '.react-flow__node[data-id="Grupo::Bravo"] span',
      ) as Element,
    );

    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Bravo" }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("heading", { name: "Alfa" }),
    ).not.toBeInTheDocument();
  });

  it("renders the selected entity's metadata in the panel", async () => {
    const WITH_CONTENT: GraphEntity[] = [
      { ...LINKED[0], content: "Alfa es un cazador de la estepa." },
      ...LINKED.slice(1),
    ];
    mockFetch.mockResolvedValue({ entities: WITH_CONTENT, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    fireEvent.click(screen.getByText("Alfa"));
    await screen.findByTestId("node-inspector-panel");
    // Scope to the panel: the sidebar's status select also renders "Canon".
    const panel = within(screen.getByTestId("node-inspector-panel"));

    expect(panel.getByRole("heading", { name: "Alfa" })).toBeInTheDocument();
    expect(panel.getByText("Personaje")).toBeInTheDocument();
    // Status chip via STATUS_META (stable → "Canon").
    expect(panel.getByText("Canon")).toBeInTheDocument();
    expect(panel.getByText("personajes/Alfa.md")).toBeInTheDocument();
    expect(
      panel.getByText("Alfa es un cazador de la estepa."),
    ).toBeInTheDocument();
    // Alfa's forward link "Bravo" resolves to a clickable neighbor link.
    expect(panel.getByRole("button", { name: "Bravo" })).toBeInTheDocument();
  });

  it("centers a visible neighbor via fitView when its panel link is clicked", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));
    await waitFor(() => expect(mockFlowInstance.instance).not.toBeNull());

    fireEvent.click(screen.getByText("Alfa"));
    await screen.findByTestId("node-inspector-panel");

    const fitViewSpy = vi.spyOn(mockFlowInstance.instance!, "fitView");
    fitViewSpy.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Bravo" }));

    expect(fitViewSpy).toHaveBeenCalledWith({
      nodes: [{ id: "Grupo::Bravo" }],
      duration: 300,
    });
  });

  it("renders a status-filtered neighbor as plain text (not a link)", async () => {
    const user = userEvent.setup();
    // First fetch: all three. Stable refetch drops Bravo (draft) entirely.
    mockFetch
      .mockResolvedValueOnce({ entities: LINKED, links: LINKS })
      .mockResolvedValueOnce({
        entities: LINKED.filter((entity) => entity.status === "stable"),
        links: [],
      });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    fireEvent.click(screen.getByText("Alfa"));
    await screen.findByTestId("node-inspector-panel");
    expect(screen.getByRole("button", { name: "Bravo" })).toBeInTheDocument();

    await user.selectOptions(
      screen.getByLabelText("Filtrar por estado"),
      "stable",
    );

    // Alfa is still stable → selection survives the refetch…
    await waitFor(() => expect(countNodes()).toBe(2));
    expect(screen.getByTestId("node-inspector-panel")).toBeInTheDocument();
    // …but Bravo is no longer loaded → its entry degrades to plain text.
    const vaelEntry = screen.getByText("Bravo");
    expect(vaelEntry.tagName).toBe("SPAN");
    expect(
      screen.queryByRole("button", { name: "Bravo" }),
    ).not.toBeInTheDocument();
  });

  it("clears the selection when the selected entity leaves the loaded set", async () => {
    const user = userEvent.setup();
    // First fetch: all three. Stable refetch drops Bravo (draft) entirely.
    mockFetch
      .mockResolvedValueOnce({ entities: LINKED, links: LINKS })
      .mockResolvedValueOnce({
        entities: LINKED.filter((entity) => entity.status === "stable"),
        links: [],
      });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    fireEvent.click(screen.getByText("Bravo"));
    await screen.findByTestId("node-inspector-panel");
    expect(screen.getByRole("heading", { name: "Bravo" })).toBeInTheDocument();

    await user.selectOptions(
      screen.getByLabelText("Filtrar por estado"),
      "stable",
    );

    // Bravo (draft) is gone after the stable refetch → the panel closes.
    await waitFor(() =>
      expect(screen.queryByTestId("node-inspector-panel")).not.toBeInTheDocument(),
    );
  });

  it("navigates to the ficha route via the panel's ficha button", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    fireEvent.click(screen.getByText("Alfa"));
    await screen.findByTestId("node-inspector-panel");

    fireEvent.click(screen.getByRole("button", { name: "Abrir ficha" }));

    expect(navigate).toHaveBeenCalledWith(
      "/wiki/vibrantes/entity/Alfa",
    );
  });

  it("closes the inspector when the panel close button is clicked", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    fireEvent.click(screen.getByText("Alfa"));
    await screen.findByTestId("node-inspector-panel");

    fireEvent.click(
      screen.getByRole("button", { name: "Cerrar panel de inspección" }),
    );

    expect(screen.queryByTestId("node-inspector-panel")).not.toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("clamps the inspector width when the divider is dragged", async () => {
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    fireEvent.click(screen.getByText("Alfa"));
    await screen.findByTestId("node-inspector-panel");

    // jsdom viewport is 1024px → limits [205, 410]. Drag far left (600px of
    // travel) would grow the width to 880 → clamped to the 410px max.
    const divider = screen.getByRole("separator", {
      name: "Redimensionar panel de inspección",
    });
    fireEvent.mouseDown(divider, { clientX: 500 });
    fireEvent.mouseMove(document, { clientX: -100 });
    fireEvent.mouseUp(document);

    expect(screen.getByTestId("node-inspector")).toHaveStyle({
      width: "410px",
    });
  });

  it("hides and restores the inspector with the focus toggle", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ entities: LINKED, links: LINKS });
    renderGraphView();

    await waitFor(() => expect(countNodes()).toBe(3));

    fireEvent.click(screen.getByText("Alfa"));
    await screen.findByTestId("node-inspector-panel");

    // Activate focus mode → panel AND divider disappear (canvas expands).
    await user.click(
      screen.getByRole("button", { name: "Ocultar panel de inspección" }),
    );
    expect(screen.queryByTestId("node-inspector-panel")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("separator", {
        name: "Redimensionar panel de inspección",
      }),
    ).not.toBeInTheDocument();

    // Deactivate → the panel returns.
    await user.click(
      screen.getByRole("button", { name: "Mostrar panel de inspección" }),
    );
    expect(screen.getByTestId("node-inspector-panel")).toBeInTheDocument();
    expect(
      screen.getByRole("separator", {
        name: "Redimensionar panel de inspección",
      }),
    ).toBeInTheDocument();
  });
});