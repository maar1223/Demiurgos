import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  Background,
  Handle,
  Position,
  ReactFlow,
  useReactFlow,
  useStore,
  type Connection,
  type Edge,
  type EdgeTypes,
  type Node,
  type NodeProps,
  type NodeTypes,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  breakRelation,
  createRelation,
  fetchGraphEntities,
  searchEntities,
  type GraphStatusFilter,
} from "@/api/graph";
import {
  computeLayoutSize,
  createLiveForceLayout,
  nodeKey,
  SETTLE_TICKS,
  ringPositions,
  type ForcePosition,
  type ForcePositions,
  type LiveForceLayout,
  type NodeSize,
} from "@/lib/graphForce";
import type {
  EntityLink,
  FichaStatus,
  GraphEntity,
  SearchResult,
} from "@/api/types";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { Spinner } from "@/components/atoms/Spinner";
import { Toast } from "@/components/atoms/Toast";
import { Icon, type IconName } from "@/components/atoms/Icon";
import { GraphEdge } from "@/components/GraphEdge";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { GraphControlsSidebar } from "@/components/organisms/GraphControlsSidebar";
import { NodeInspectorPanel } from "@/components/organisms/NodeInspectorPanel";
import {
  buildFolderTree,
  filterEntitiesByFolders,
  neighborhoodKeys,
  type FolderNode,
} from "@/lib/graphFilters";
import { cn } from "@/lib/utils";
import { useAppLanguage } from "@/hooks/useAppLanguage";

/** Default inspector panel width (desktop). */
const RIGHT_DEFAULT = 280;

/** Proportional inspector limits (1/5–2/5 of the viewport width) — computed
 *  live so drag/resize adapts to the current window size (EditorLayout). */
const panelLimits = () => {
  const vw = window.innerWidth || 1200;
  return { min: Math.round(vw * 0.2), max: Math.round(vw * 0.4) };
};

const clampPanel = (w: number) => {
  const { min, max } = panelLimits();
  return Math.min(max, Math.max(min, Math.round(w)));
};

/** Fallback node size used when measured dimensions are unavailable (the
 *  drag push-out below; the force engine owns its own constants). */
const NODE_MIN_WIDTH = 140;
const NODE_MIN_HEIGHT = 36;

/** Ticks applied before the first paint: centres the initial d3 spiral so the
 *  graph does not visibly explode from the top-left corner. */
const INITIAL_LIVE_TICKS = 2;
/** Alpha restored on a dataset change: enough movement to read as "alive". */
const DATASET_REHEAT_ALPHA = 0.35;
/** Alpha restored while a node is dragged, so neighbours keep reacting. */
const DRAG_REHEAT_ALPHA = 0.35;
/** Alpha restored on drop: the neighbourhood re-settles around the pin. */
const DROP_REHEAT_ALPHA = 0.5;
/** Alpha used by the synchronous settle after a drag under reduced motion. */
const SETTLE_ALPHA = 1;

/** Edge look (S5): quiet by default, neighbourhood-first on hover. No
 *  arrowheads — direction is explicitly out of scope (L2). */
const EDGE_STROKE = "rgb(var(--color-muted))";
const EDGE_BASE_OPACITY = 0.22;
const EDGE_HIGHLIGHT_OPACITY = 0.85;
const EDGE_DIM_OPACITY = 0.05;
const EDGE_BASE_WIDTH = 1.1;
/** Extra stroke width per parallel relation between the same pair. */
const EDGE_WIDTH_STEP = 0.45;
const EDGE_MAX_WIDTH = 2.8;

/** Below this zoom level nodes collapse to status dots (semantic zoom, S8). */
const SEMANTIC_ZOOM_THRESHOLD = 0.55;
/** Below this zoom level only hubs and the focused neighbourhood show names;
 *  every card showing its name at once is what made a close view noisy. */
const LABEL_ZOOM_THRESHOLD = 0.95;

/**
 * Whether the graph must skip animation. Reduced motion is a hard requirement
 * (S3); a host with no media-query API (jsdom in tests) also takes the
 * synchronous path, so the layout stays deterministic instead of animating
 * blindly.
 */
function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return true;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Entity-type icon (S6): the frontmatter type decides the glyph; unknown
 *  types fall back to a plain document instead of a blank card. */
const TYPE_ICONS: Record<string, IconName> = {
  personaje: "avatar",
  character: "avatar",
  lugar: "world",
  place: "world",
  location: "world",
  evento: "history",
  event: "history",
  concepto: "lightbulb",
  concept: "lightbulb",
  idea: "lightbulb",
  objeto: "file",
  object: "file",
  item: "file",
  referencia: "markdown",
  reference: "markdown",
};

function typeIcon(type?: string): IconName {
  if (!type) return "file";
  return TYPE_ICONS[type.toLowerCase()] ?? "file";
}

/** Degree tiers (S6): hubs read first, isolated nodes recede. */
type NodeTier = "hub" | "node" | "leaf";
/** Minimum connections for a node to read as a hub. */
const HUB_MIN_DEGREE = 5;

function nodeTier(degree: number): NodeTier {
  if (degree >= HUB_MIN_DEGREE) return "hub";
  if (degree === 0) return "leaf";
  return "node";
}

/** Card chrome (padding, icon, gap, status dot, border) beyond the label. */
const CARD_CHROME_WIDTH = 70;
/** Average glyph width at the card's 13px type scale. */
const CARD_CHAR_WIDTH = 8;
/** Card width cap: the label truncates at 11rem (176px). */
const CARD_MAX_WIDTH = 244;

/**
 * Deterministic layout footprint of a card. It must NOT depend on the
 * presentation tier: if revealing a name on hover (or hiding it while zoomed
 * out) changed the footprint, the simulation would re-settle and the whole map
 * would jump — the author would be chasing the node instead of reading it.
 */
function estimateNodeSize(entity: GraphEntity, tier: NodeTier): NodeSize {
  const width = Math.min(
    CARD_MAX_WIDTH,
    Math.max(120, CARD_CHROME_WIDTH + entity.name.length * CARD_CHAR_WIDTH),
  );
  const height = tier === "hub" ? 46 : tier === "leaf" ? 36 : 42;
  return { width, height };
}

const NODE_TIER_CLASS: Record<NodeTier, string> = {
  hub: "gap-2 px-3.5 py-2.5 text-small font-semibold",
  node: "gap-2 px-3 py-2 text-small font-medium",
  leaf: "gap-1.5 px-2.5 py-1.5 text-xs font-normal",
};

/** Canon reads through fill + ring + status dot — never border colour alone
 *  (S6). The base border stays neutral so the status never depends on it. */
const NODE_CANON_CLASS: Record<
  FichaStatus,
  { card: string; dot: string }
> = {
  draft: {
    card: "bg-amber-400/10 ring-1 ring-amber-400/60",
    dot: "bg-amber-500",
  },
  stable: {
    card: "bg-emerald-500/10 ring-1 ring-emerald-500/60",
    dot: "bg-emerald-500",
  },
};

interface GraphNodeData extends Record<string, unknown> {
  label: string;
  type?: string;
  status?: FichaStatus;
  tier: NodeTier;
  /** Whether the compact zoom band shows this node's name inline: only the
   *  folder group's hierarchy main does (S11), not every hub. */
  compactLabel: boolean;
}

/**
 * Presentation tier shared with the node components:
 * - `dot`: far away, a canon-coloured dot (S8);
 * - `compact`: close enough to see the cards, only each folder group's main
 *   node (and the focused neighbourhood) carries a name (S11);
 * - `labels`: fully zoomed in, every card shows its name.
 */
type ZoomTier = "dot" | "compact" | "labels";

const ZoomTierContext = createContext<ZoomTier>("labels");

/**
 * Hover focus shared with the node components: while a node is hovered its
 * neighbours stay legible and everything else recedes, so the author can read
 * "what connects to what" without following every line (S5).
 */
interface HoverFocus {
  /** Node under the pointer (drives edge/node dimming). */
  hovered: string | null;
  /** Node whose neighbourhood is revealed: hovered, or the selected one. */
  focus: string | null;
  neighbours: Set<string>;
}

const EMPTY_HOVER: HoverFocus = {
  hovered: null,
  focus: null,
  neighbours: new Set(),
};
const HoverFocusContext = createContext<HoverFocus>(EMPTY_HOVER);

/** A folder/section that reads as a cluster (S7). */
interface GraphCluster {
  id: string;
  label: string;
  members: string[];
}

/** Group entities by their folder path; single-entity folders stay unnamed. */
function buildClusters(entities: GraphEntity[]): GraphCluster[] {
  const byFolder = new Map<string, GraphCluster>();
  for (const entity of entities) {
    const slash = entity.path.lastIndexOf("/");
    if (slash < 0) continue;
    const folder = entity.path.slice(0, slash);
    const existing = byFolder.get(folder);
    if (existing) {
      existing.members.push(nodeKey(entity));
    } else {
      byFolder.set(folder, {
        id: folder,
        label: folder.split("/").pop() ?? folder,
        members: [nodeKey(entity)],
      });
    }
  }
  return [...byFolder.values()].filter((cluster) => cluster.members.length >= 2);
}

/**
 * Fits the viewport once the canvas is measured AND the nodes are initialized.
 * The `fitView` prop fires as soon as nodes initialize, which can race a 0×0
 * container (jsdom, or a hidden tab) and lock the viewport at minZoom — that
 * would make a small graph look like a field of far-away dots.
 */
function AutoFit() {
  const { fitView } = useReactFlow();
  const width = useStore((state) => state.width);
  const height = useStore((state) => state.height);
  const initialized = useStore((state) => state.nodesInitialized);
  const fitted = useRef(false);
  useEffect(() => {
    if (fitted.current || !initialized || width <= 0 || height <= 0) return;
    fitted.current = true;
    void fitView({ padding: 0.2 });
  }, [initialized, width, height, fitView]);
  return null;
}

/**
 * Reports the semantic-zoom tier from inside the React Flow store. It only
 * calls back when the tier flips, so panning never re-renders the graph.
 */
function ZoomTierWatcher({
  semanticThreshold,
  labelThreshold,
  onChange,
}: {
  semanticThreshold: number;
  labelThreshold: number;
  onChange: (tier: ZoomTier) => void;
}) {
  const zoom = useStore((state) => state.transform[2]);
  const tier: ZoomTier =
    zoom < semanticThreshold
      ? "dot"
      : zoom < labelThreshold
        ? "compact"
        : "labels";
  useEffect(() => {
    onChange(tier);
  }, [tier, onChange]);
  return null;
}

/**
 * A connection write awaiting author confirmation in the modal. `kind`
 * selects the endpoint action; `sourcePath`/`targetId` are exactly what the
 * backend relation endpoint expects (mundo-relative ficha path + canonical id).
 */
interface PendingRelation {
  kind: "create" | "break";
  sourcePath: string;
  sourceLabel: string;
  targetId: string;
  targetLabel: string;
}

/**
 * Custom node type with invisible connection handles: the target handle sits
 * at the top edge and the source handle at the bottom edge, so drag-to-connect
 * and click-to-connect work while the graph keeps its current look (edge
 * anchors are computed from the handle `position` prop, so they still meet the
 * node at top/bottom center). `opacity: 0` hides the handles; pointer events
 * stay enabled so connections can actually be started on them.
 */
type GraphNodeType = Node<GraphNodeData, "graph">;

const handleStyle = { opacity: 0 } as const;

function GraphNode({ id, data }: NodeProps<GraphNodeType>) {
  const zoomTier = useContext(ZoomTierContext);
  const hover = useContext(HoverFocusContext);
  const focused = hover.focus !== null && hover.neighbours.has(id);
  // Hover/selection dims the rest of the map, but only while focusing.
  const faded = hover.hovered !== null && !hover.neighbours.has(id);
  const canon = data.status ? NODE_CANON_CLASS[data.status] : null;

  // S8: far away, a node is a dot coloured by canon.
  if (zoomTier === "dot") {
    return (
      <div className="relative flex h-3 w-3 items-center justify-center">
        <Handle
          type="target"
          position={Position.Top}
          style={handleStyle}
          isConnectable={true}
        />
        <span
          data-testid="graph-node-dot"
          data-canon={data.status ?? "none"}
          className={cn(
            "h-3 w-3 rounded-full shadow-sm",
            canon?.dot ?? "bg-muted",
            faded && "opacity-30",
          )}
        />
        <Handle
          type="source"
          position={Position.Bottom}
          style={handleStyle}
          isConnectable={true}
        />
      </div>
    );
  }

  // Progressive labels: the folder group's main node keeps its name in the
  // compact band; everything else appears when fully zoomed in or while it
  // belongs to the focused neighbourhood.
  const inlineLabel =
    zoomTier === "labels" || (zoomTier === "compact" && data.compactLabel);
  // Focused nodes that are not showing their name inline get a FLOATING label.
  // Growing the card on hover changed its measured box and painted over the
  // neighbouring cards (the "blip"); a floating tag never touches geometry.
  const floatingLabel = !inlineLabel && focused;

  return (
    <div className="relative">
      <Handle
        type="target"
        position={Position.Top}
        style={handleStyle}
        isConnectable={true}
      />
      <div
        data-testid="graph-node-card"
        data-tier={data.tier}
        data-canon={data.status ?? "none"}
        data-label={inlineLabel || floatingLabel ? "shown" : "hidden"}
        className={cn(
          "flex items-center rounded-lg border-2 border-edge bg-surface-raised shadow-sm text-primary transition-opacity",
          NODE_TIER_CLASS[data.tier],
          canon?.card,
          faded && "opacity-30",
        )}
      >
        <Icon
          name={typeIcon(data.type)}
          size={data.tier === "leaf" ? 12 : 14}
          data-testid="node-type-icon"
          data-icon={typeIcon(data.type)}
          className="text-muted"
        />
        {inlineLabel && (
          <span className="max-w-[11rem] truncate">{data.label}</span>
        )}
        <span
          data-testid="canon-dot"
          aria-hidden="true"
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            canon?.dot ?? "bg-muted",
          )}
        />
      </div>
      {floatingLabel && (
        <span className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded-md border border-edge bg-surface-raised/95 px-2 py-0.5 text-xs font-medium text-primary shadow-lg backdrop-blur-sm">
          {data.label}
        </span>
      )}
      <Handle
        type="source"
        position={Position.Bottom}
        style={handleStyle}
        isConnectable={true}
      />
    </div>
  );
}

const nodeTypes: NodeTypes = { graph: GraphNode };
const edgeTypes: EdgeTypes = { graph: GraphEdge };

interface GraphViewProps {
  mundo: string;
  /** Fill the parent instead of the fixed card (rounded border + 18rem of
   *  reserved height): used when the page gives the canvas the whole viewport. */
  bleed?: boolean;
}

/**
 * GraphView — React Flow visualization of world entities + forward links
 * (Relaciones y Canon, BLOQUE 4 · Slice A; W12 first-version contract).
 *
 * - Nodes = entities, colored by status via STATUS_META tokens (draft=amber,
 *   stable=emerald); edges = forward links (source/target entity ids).
 * - Status filter (all/draft/stable) re-fetches with the query param.
 * - Orphans (no forward AND no back links) are hidden by default; the
 *   "Mostrar nodos aislados" toggle reveals them.
 * - Node click SELECTS the node and opens the right-hand inspector panel
 *   (name, type, status, path, neighbor links, content preview); the ficha
 *   route is reached via the panel's "Abrir ficha" button.
 * - Node search input (debounced) centers a matching node in the viewport.
 * - The canvas is unbounded: no node extent is applied, so the author can drag
 *   any node anywhere (the layout box only frames the automatic layout).
 * - The canvas owns the whole surface (S4): controls and the inspector float
 *   over it as translucent panels instead of taking columns. The folder tree
 *   is a hierarchical multi-select that hides nodes outside the selected
 *   folders (prefix union); edges touching hidden nodes vanish.
 * - Zoom/pan come from React Flow.
 */
export default function GraphView({ mundo, bleed = false }: GraphViewProps) {
  const { t } = useAppLanguage();
  const navigate = useNavigate();
  const [entities, setEntities] = useState<GraphEntity[]>([]);
  const [links, setLinks] = useState<EntityLink[]>([]);
  const [status, setStatus] = useState<GraphStatusFilter>("all");
  const [showOrphans, setShowOrphans] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Folder filter (client-side): hierarchical multi-select over entity
  // folder paths. An empty selection shows every folder.
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);

  // Pending gated write: a connection proposal awaiting author confirmation.
  // `pendingConnection` is set by onConnect (drag/click-to-connect),
  // `pendingBreak` by onEdgeClick. Only one is ever non-null at a time; the
  // confirmation modal is the governance gate before any write reaches disk.
  const [pendingConnection, setPendingConnection] =
    useState<PendingRelation | null>(null);
  const [pendingBreak, setPendingBreak] =
    useState<PendingRelation | null>(null);
  const [modalBusy, setModalBusy] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);
  const [toast, setToast] = useState<{
    message: string;
    kind: "success" | "error";
  } | null>(null);

  // Node search: debounced server-side search (searchEntities) with a
  // results dropdown. Selecting a result centers the node in the viewport.
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Structural node state: ids, labels, classes and the INITIAL positions.
  // React Flow runs uncontrolled (`defaultNodes`) and owns the live positions;
  // the simulation writes them straight into its store, so an animation frame
  // never re-renders this component (S2). The state is re-seeded only when the
  // dataset (filter/orphans/reload) changes.
  const [nodes, setNodes] = useState<GraphNodeType[]>([]);
  const rf = useRef<ReactFlowInstance<GraphNodeType, Edge> | null>(null);
  const layoutRef = useRef<LiveForceLayout | null>(null);
  const reducedMotionRef = useRef(prefersReducedMotion());
  const clusterRefs = useRef(new Map<string, HTMLDivElement>());
  // Section labels are fixed-size in screen space, so measuring once is enough.
  const labelSizesRef = useRef(
    new Map<string, { width: number; height: number }>(),
  );
  const clusterMembersRef = useRef<GraphCluster[]>([]);
  const nodeSizesRef = useRef<Map<string, NodeSize>>(new Map());
  const positionsRef = useRef<ForcePositions>(new Map());

  // Node inspector: selection state plus right-panel resize/focus. The
  // selected entity is DERIVED from the loaded set (by node key), so a status
  // re-fetch or mundo switch can never leave the panel showing stale data.
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  // Hovered node: its edges light up while the rest recede (S5). Purely
  // visual, so it never touches the graph data or the layout.
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  // Presentation tier: dots far away, compact cards in the middle, names when
  // fully zoomed in (S8 + progressive labels).
  const [zoomTier, setZoomTier] = useState<ZoomTier>("labels");
  const [panelWidth, setPanelWidth] = useState<number>(() =>
    clampPanel(RIGHT_DEFAULT),
  );
  const [focusMode, setFocusMode] = useState(false);
  // "Isolate neighbourhood": the canvas keeps only this node and its direct
  // neighbours, so every connection fits on screen and names stay readable.
  const [isolatedNodeId, setIsolatedNodeId] = useState<string | null>(null);
  const [draggingPanel, setDraggingPanel] = useState(false);
  const panelDragRef = useRef<{ startX: number; startW: number } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchGraphEntities(mundo, status);
      setEntities(data.entities);
      setLinks(data.links);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("graph.loadError"),
      );
    } finally {
      setLoading(false);
    }
  }, [mundo, status]);

  useEffect(() => {
    void load();
  }, [load]);

  // Hierarchical folder tree derived from the loaded entity paths (folders
  // only, arbitrary depth). Rebuilt whenever the entity set changes.
  const folderTree = useMemo(() => buildFolderTree(entities), [entities]);

  // Entities inside the selected folders (prefix union). An empty selection
  // keeps every entity visible.
  const visibleEntities = useMemo(() => {
    if (isolatedNodeId) {
      // Isolation wins over the folder filter: a neighbour shows even when its
      // folder is unselected, because the point is to see the whole
      // neighbourhood of the node being inspected.
      const keep = neighborhoodKeys(links, isolatedNodeId);
      return entities.filter((entity) => keep.has(nodeKey(entity)));
    }
    return filterEntitiesByFolders(entities, selectedFolders);
  }, [entities, selectedFolders, isolatedNodeId, links]);

  // Inspector lookups: the selected entity is re-derived from the loaded set
  // on every render, so it is never stale after a re-fetch. `entityByKey`
  // covers ALL loaded entities (neighbor resolution still works for
  // filtered-out neighbors, which then render as plain text); the visible
  // key set is exactly the rendered node set (orphan/folder filtered).
  const exitIsolation = useCallback(() => {
    setIsolatedNodeId(null);
    window.setTimeout(
      () => rf.current?.fitView({ duration: 350, padding: 0.2 }),
      120,
    );
  }, []);

  // Escape leaves the isolated view; the whole world comes back.
  useEffect(() => {
    if (!isolatedNodeId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") exitIsolation();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isolatedNodeId, exitIsolation]);

  // Frame the neighbourhood once the layout has the reduced node set.
  useEffect(() => {
    if (!isolatedNodeId) return;
    const ids = [...neighborhoodKeys(links, isolatedNodeId)].map((id) => ({ id }));
    const timer = window.setTimeout(
      () => rf.current?.fitView({ nodes: ids, duration: 350, padding: 0.35 }),
      140,
    );
    return () => window.clearTimeout(timer);
  }, [isolatedNodeId, links]);

  const selectedEntity = useMemo(
    () => entities.find((e) => nodeKey(e) === selectedNodeId) ?? null,
    [entities, selectedNodeId],
  );
  const entityByKey = useMemo(
    () => new Map(entities.map((e) => [nodeKey(e), e])),
    [entities],
  );
  const visibleEntityKeys = useMemo(
    () => new Set(nodes.map((n) => n.id)),
    [nodes],
  );

  // Inspector panel resize (EditorLayout pattern): document-level
  // mousedown/mousemove/mouseup drag loop, widths clamped to the live
  // proportional limits, and re-clamp on window resize.
  const startPanelDrag = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      panelDragRef.current = { startX: e.clientX, startW: panelWidth };
      setDraggingPanel(true);
    },
    [panelWidth],
  );

  useEffect(() => {
    if (!draggingPanel) return;
    const onMove = (e: MouseEvent) => {
      if (!panelDragRef.current) return;
      const { startX, startW } = panelDragRef.current;
      setPanelWidth(clampPanel(startW + (startX - e.clientX)));
    };
    const onUp = () => {
      panelDragRef.current = null;
      setDraggingPanel(false);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [draggingPanel]);

  useEffect(() => {
    const onResize = () => setPanelWidth((w) => clampPanel(w));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Clear the selection when the selected entity leaves the LOADED set
  // (status re-fetch, mundo switch, empty result) — the panel must never
  // show an entity that no longer exists in the current world view.
  useEffect(() => {
    if (!selectedNodeId) return;
    const stillLoaded = entities.some((e) => nodeKey(e) === selectedNodeId);
    if (!stillLoaded) setSelectedNodeId(null);
  }, [entities, selectedNodeId]);

  // The isolated node must exist in the loaded set (status re-fetch, mundo
  // switch); otherwise the canvas would render an empty neighbourhood.
  useEffect(() => {
    if (!isolatedNodeId) return;
    if (!entities.some((e) => nodeKey(e) === isolatedNodeId)) {
      setIsolatedNodeId(null);
    }
  }, [entities, isolatedNodeId]);

  // When the loaded entity set no longer contains a selected folder (status
  // re-fetch, mundo switch, empty result), prune it so the tree never shows
  // a selection pointing at a folder that vanished.
  useEffect(() => {
    if (selectedFolders.length === 0) return;
    const existing = new Set<string>();
    const collect = (nodes: FolderNode[]): void => {
      for (const node of nodes) {
        existing.add(node.path);
        collect(node.children);
      }
    };
    collect(folderTree);
    const next = selectedFolders.filter((path) => existing.has(path));
    if (next.length !== selectedFolders.length) setSelectedFolders(next);
  }, [folderTree, selectedFolders]);

  // Auto-clear the feedback toast (mirrors WikiEditor/IdeasWorkshop).
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2500);
    return () => clearTimeout(t);
  }, [toast]);

  // Debounce the searchEntities call (300ms) so each keystroke does not fire
  // a request. A monotonic request id discards out-of-order responses when
  // the query changes while a previous request is still in flight.
  const searchRequestId = useRef(0);
  useEffect(() => {
    const query = searchQuery.trim();
    const requestId = ++searchRequestId.current;
    if (!query) {
      setSearching(false);
      setSearchResults([]);
      setSearchError(null);
      return;
    }
    setSearching(true);
    setSearchResults([]);
    const timer = setTimeout(async () => {
      try {
        const results = await searchEntities(mundo, query);
        if (searchRequestId.current !== requestId) return;
        setSearchResults(results);
        setSearchError(null);
      } catch (err) {
        if (searchRequestId.current !== requestId) return;
        setSearchError(
          err instanceof Error ? err.message : t("graph.searchError"),
        );
        setSearchResults([]);
      } finally {
        if (searchRequestId.current === requestId) setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, mundo]);

  /** Move every cluster label to the centroid of its members (S7). Written
   *  imperatively, like node positions, so it follows the live layout without
   *  re-rendering. */
  const positionClusters = useCallback((positions: ForcePositions) => {
    type Box = { left: number; top: number; right: number; bottom: number };
    const viewport = rf.current?.getViewport() ?? { x: 0, y: 0, zoom: 1 };
    const cards: Box[] = (rf.current?.getNodes() ?? []).map((node) => {
      const size = nodeSizesRef.current.get(node.id);
      const width = (size?.width ?? NODE_MIN_WIDTH) * viewport.zoom;
      const height = (size?.height ?? NODE_MIN_HEIGHT) * viewport.zoom;
      const left = node.position.x * viewport.zoom + viewport.x;
      const top = node.position.y * viewport.zoom + viewport.y;
      return { left, top, right: left + width, bottom: top + height };
    });

    const labels: {
      element: HTMLDivElement;
      x: number;
      y: number;
      width: number;
      height: number;
    }[] = [];

    for (const cluster of clusterMembersRef.current) {
      const element = clusterRefs.current.get(cluster.id);
      if (!element) continue;
      let sumX = 0;
      let topY = Number.POSITIVE_INFINITY;
      let count = 0;
      for (const member of cluster.members) {
        const position = positions.get(member);
        if (!position) continue;
        sumX += position.x;
        const size = nodeSizesRef.current.get(member);
        // Anchor above the GROUP, not on its centroid: the centroid is where
        // the hub card sits, so the label used to land on top of it.
        topY = Math.min(topY, position.y - (size?.height ?? NODE_MIN_HEIGHT) / 2);
        count += 1;
      }
      if (count === 0) continue;

      // Screen space, not flow space: the section label must stay legible from
      // far away, where it is the only wayfinding cue.
      const measured = labelSizesRef.current.get(cluster.id);
      const width = measured?.width ?? element.offsetWidth;
      const height = measured?.height ?? element.offsetHeight;
      // Never cache a zero measure: a label rendered before its styles apply
      // would keep a 0×0 box and stop dodging anything.
      if (!measured && width > 0 && height > 0) {
        labelSizesRef.current.set(cluster.id, { width, height });
      }
      labels.push({
        element,
        x: (sumX / count) * viewport.zoom + viewport.x,
        y: topY * viewport.zoom + viewport.y - 10,
        width,
        height,
      });
    }

    const boxes = () =>
      labels.map((label) => ({
        left: label.x - label.width / 2,
        top: label.y - label.height,
        right: label.x + label.width / 2,
        bottom: label.y,
      }));
    const hits = (a: Box, b: Box) =>
      a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

    // Two sections can share a height (their groups sit side by side). Pushing
    // one UP produced a tight stack of titles; separating them SIDEWAYS keeps
    // each label over its own group and spreads them evenly.
    for (let pass = 0; pass < 12; pass += 1) {
      let moved = false;
      const current = boxes();
      for (let i = 0; i < labels.length; i += 1) {
        for (let j = i + 1; j < labels.length; j += 1) {
          if (!hits(current[i], current[j])) continue;
          const overlap =
            Math.min(current[i].right, current[j].right) -
            Math.max(current[i].left, current[j].left);
          const push = overlap / 2 + 6;
          const left = labels[i].x <= labels[j].x ? i : j;
          const right = left === i ? j : i;
          labels[left].x -= push;
          labels[right].x += push;
          moved = true;
        }
      }
      if (!moved) break;
    }

    // A card can still sit where the header goes: lift the label instead of
    // drawing the two on top of each other.
    for (const label of labels) {
      for (let attempt = 0; attempt < 6; attempt += 1) {
        const box: Box = {
          left: label.x - label.width / 2,
          top: label.y - label.height,
          right: label.x + label.width / 2,
          bottom: label.y,
        };
        if (!cards.some((card) => hits(box, card))) break;
        label.y -= label.height + 6;
      }
      label.element.style.transform =
        `translate(${label.x}px, ${label.y}px) translate(-50%, -100%)`;
    }
  }, []);

  /** The engine lays nodes out by their CENTRE; React Flow positions a node
   *  by its top-left corner (and clamps it inside the extent by its size).
   *  Converting here keeps both coordinate systems honest. */
  const centreToTopLeft = useCallback(
    (id: string, centre: ForcePosition): ForcePosition => {
      const size = nodeSizesRef.current.get(id);
      const width = size?.width ?? NODE_MIN_WIDTH;
      const height = size?.height ?? NODE_MIN_HEIGHT;
      return { x: centre.x - width / 2, y: centre.y - height / 2 };
    },
    [],
  );

  const topLeftToCentre = useCallback(
    (id: string, topLeft: ForcePosition): ForcePosition => {
      const size = nodeSizesRef.current.get(id);
      const width = size?.width ?? NODE_MIN_WIDTH;
      const height = size?.height ?? NODE_MIN_HEIGHT;
      return { x: topLeft.x + width / 2, y: topLeft.y + height / 2 };
    },
    [],
  );

  /** Push simulation positions straight into the React Flow store. This is
   *  the only per-frame write: it keeps the component tree out of the loop
   *  (S2) while React Flow still re-renders the node it owns. */
  const applyPositions = useCallback(
    (positions: ForcePositions) => {
      // While the hover magnet holds the ring, a late layout tick must not
      // undo it (the simulation is stopped, but a scheduled frame can land).
      if (magnetRef.current) return;
      positionsRef.current = positions;
      rf.current?.setNodes((current) =>
        current.map((node) => {
          const centre = positions.get(node.id);
          return centre
            ? { ...node, position: centreToTopLeft(node.id, centre) }
            : node;
        }),
      );
      positionClusters(positions);
    },
    [centreToTopLeft, positionClusters],
  );

  // Build the layout and (re)seed the node set whenever the dataset changes
  // (folder filter/orphans/reload). A fresh dataset means a fresh simulation:
  // it cools down from a readable starting point, or settles synchronously
  // when motion is reduced (S1/S3).
  useEffect(() => {
    layoutRef.current?.stop();
    layoutRef.current = null;

    if (loading || error) return;
    if (visibleEntities.length === 0) {
      setNodes([]);
      return;
    }
    // Folder filter first: entities outside the selected folders never
    // participate — not in the layout, the node set, or the orphan pass.
    const orphanKeys = new Set(
      visibleEntities
        .filter(
          (e) => e.forward_links.length === 0 && e.backlinks.length === 0,
        )
        .map(nodeKey),
    );
    // Orphans hidden by default (W12); the toggle reveals them.
    // An isolated node may be an orphan: the toggle must not hide it.
    const visible =
      isolatedNodeId || showOrphans
        ? visibleEntities
        : visibleEntities.filter((e) => !orphanKeys.has(nodeKey(e)));

    const size = computeLayoutSize(visible.length);
    // One deterministic footprint per node for the whole dataset: stable under
    // hover and zoom, so the map never re-settles while being read.
    const layoutSizes = new Map<string, NodeSize>();
    for (const entity of visible) {
      const degree = entity.forward_links.length + entity.backlinks.length;
      layoutSizes.set(nodeKey(entity), estimateNodeSize(entity, nodeTier(degree)));
    }
    nodeSizesRef.current = layoutSizes;

    const layout = createLiveForceLayout({
      entities: visible,
      links,
      size,
      sizes: layoutSizes,
    });
    layoutRef.current = layout;

    const reducedMotion = prefersReducedMotion();
    reducedMotionRef.current = reducedMotion;
    // Reduced motion jumps to the settled layout in the same frame; otherwise
    // a couple of ticks let the initial spiral centre before the first paint.
    // An ISOLATED neighbourhood settles too: it is a reading mode, and a
    // drifting layout pushed the neighbours out of the framed viewport right
    // after the fit.
    const positions =
      reducedMotion || isolatedNodeId
        ? layout.settle()
        : layout.step(INITIAL_LIVE_TICKS);
    positionsRef.current = positions;

    const mainIds = layout.mainIds();
    const nextNodes: GraphNodeType[] = visible.map((entity) => {
      const degree = entity.forward_links.length + entity.backlinks.length;
      const key = nodeKey(entity);
      const centre = positions.get(key) ?? { x: 0, y: 0 };
      return {
        id: key,
        type: "graph",
        position: centreToTopLeft(key, centre),
        data: {
          label: entity.name,
          type: entity.type ?? undefined,
          status: entity.status ?? undefined,
          tier: nodeTier(degree),
          // One name per folder group in the compact band: the hierarchy main
          // (S11). If the layout ever runs without hierarchy, fall back to the
          // hub tier so the band is never blank.
          compactLabel:
            mainIds.size > 0
              ? mainIds.has(key)
              : nodeTier(degree) === "hub",
        },
      };
    });
    setNodes(nextNodes);
    // The prop only seeds the first mount; later dataset changes must reach
    // the already-mounted canvas through its instance. AutoFit owns the
    // viewport on mount, so no fit is scheduled here (a 0×0 container would
    // clamp the zoom to minZoom and never recover).
    rf.current?.setNodes(nextNodes);

    if (!reducedMotion && !isolatedNodeId) {
      layout.onPositions = applyPositions;
      layout.reheat(DATASET_REHEAT_ALPHA);
      layout.start();
    }

    return () => layout.stop();
  }, [
    visibleEntities,
    links,
    showOrphans,
    loading,
    error,
    applyPositions,
    centreToTopLeft,
    isolatedNodeId,
  ]);

  // Folder clusters (S7): entities from the same folder read as one group.
  const clusters = useMemo(() => {
    const clusterEntities = nodes
      .map((node) => entityByKey.get(node.id))
      .filter((entity): entity is GraphEntity => Boolean(entity));
    return buildClusters(clusterEntities);
  }, [nodes, entityByKey]);

  // Keep the imperative label placement in sync with the current clusters and
  // the layout's positions (the labels themselves render through the portal).
  useEffect(() => {
    clusterMembersRef.current = clusters;
    positionClusters(layoutRef.current?.positions() ?? new Map());
  }, [clusters, positionClusters, zoomTier]);

  /** Remount key for the canvas: a new node identity set (status refetch,
   *  folder filter, orphans toggle) needs a fresh uncontrolled instance seeded
   *  with the new nodes; updates that only change positions/links reuse it. */
  const canvasKey = useMemo(
    () => nodes.map((node) => `${node.id}:${node.data.label}`).join("|"),
    [nodes],
  );

  // Edges derived from the current node set (read-only; follow dragged
  // nodes). Mutual references (A→B and B→A) collapse into a single curve per
  // pair, and every extra relation between that pair thickens it. Hovering a
  // node lights up its curves while the rest recede (S5).
  const edges = useMemo(() => {
    const nodeIds = new Set(nodes.map((n) => n.id));
    const pairs = new Map<
      string,
      { source: string; target: string; weight: number }
    >();
    for (const link of links) {
      if (!nodeIds.has(link.source) || !nodeIds.has(link.target)) continue;
      const key = [link.source, link.target].sort().join("::");
      const pair = pairs.get(key);
      if (pair) {
        pair.weight += 1;
      } else {
        pairs.set(key, {
          source: link.source,
          target: link.target,
          weight: 1,
        });
      }
    }

    const result: Edge[] = [];
    for (const pair of pairs.values()) {
      const highlighted =
        hoveredNodeId !== null &&
        (pair.source === hoveredNodeId || pair.target === hoveredNodeId);
      const dimmed = hoveredNodeId !== null && !highlighted;
      result.push({
        id: `${pair.source}->${pair.target}`,
        source: pair.source,
        target: pair.target,
        type: "graph",
        style: {
          stroke: EDGE_STROKE,
          strokeWidth: Math.min(
            EDGE_MAX_WIDTH,
            EDGE_BASE_WIDTH + (pair.weight - 1) * EDGE_WIDTH_STEP,
          ),
          opacity: dimmed
            ? EDGE_DIM_OPACITY
            : highlighted
              ? EDGE_HIGHLIGHT_OPACITY
              : EDGE_BASE_OPACITY,
          transition: "opacity 150ms ease",
        },
        // Always below the nodes: a highlighted edge used to rise to z-index 1
        // and paint over the cards, cutting through their text.
        zIndex: 0,
      });
    }
    return result;
  }, [nodes, links, hoveredNodeId]);

  const focusNodeId = hoveredNodeId ?? selectedNodeId;
  const hoverFocus = useMemo<HoverFocus>(() => {
    if (!focusNodeId) return EMPTY_HOVER;
    const neighbours = new Set<string>([focusNodeId]);
    for (const edge of edges) {
      if (edge.source === focusNodeId) neighbours.add(edge.target);
      if (edge.target === focusNodeId) neighbours.add(edge.source);
    }
    return { hovered: hoveredNodeId, focus: focusNodeId, neighbours };
  }, [hoveredNodeId, focusNodeId, edges]);

  // Raise the focused node above the rest: the floating name is a child of the
  // node wrapper, so without this the tag is painted under the cards that come
  // later in the DOM and becomes unreadable in dense areas (L22). Focus changes
  // are the only writes here; positions keep their per-frame path.
  useEffect(() => {
    const instance = rf.current;
    if (!instance) return;
    instance.setNodes((current) =>
      current.map((node) => {
        // Every node sits above every edge; the focused one above the rest so
        // its floating name is never painted under a neighbour card.
        const zIndex = node.id === focusNodeId ? 1000 : 1;
        return node.zIndex === zIndex ? node : { ...node, zIndex };
      }),
    );
  }, [focusNodeId, nodes]);

  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      // A click starting on a connection handle is click-to-connect, not
      // selection — never select a node from a handle.
      if ((_event.target as HTMLElement).closest(".react-flow__handle")) return;
      // Selecting opens the inspector panel; ficha access moves to the
      // panel's "Abrir ficha" button (REQ-INS-1/INS-4).
      setSelectedNodeId(node.id);
    },
    [],
  );

  // Hover magnet: while the pointer rests on a node, its neighbours gather in
  // a ring around it so every connection is visible at the current zoom; on
  // leave they return to the exact positions they had.
  const hoverSnapshotRef = useRef<Map<string, { x: number; y: number }> | null>(
    null,
  );
  const magnetRef = useRef(false);

  const handleNodeMouseEnter = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      setHoveredNodeId(node.id);

      const neighbourKeys = [...neighborhoodKeys(links, node.id)].filter(
        (key) => key !== node.id,
      );
      if (neighbourKeys.length === 0) return;
      // Uncontrolled canvas: the live positions live in the instance, not in
      // the React state that seeded the first mount.
      const current = rf.current?.getNodes() ?? nodes;
      const byId = new Map(current.map((item) => [item.id, item]));
      const centreNode = byId.get(node.id);
      if (!centreNode) return;

      // The live simulation would overwrite the ring on its next tick.
      magnetRef.current = true;
      layoutRef.current?.stop();

      const sizeOf = (key: string) => nodeSizesRef.current.get(key);
      const centreSize = sizeOf(node.id);
      const centre = {
        x: centreNode.position.x + (centreSize?.width ?? 0) / 2,
        y: centreNode.position.y + (centreSize?.height ?? 0) / 2,
      };
      // Keep the ring inside the viewport: the visible side in screen pixels
      // converted to flow units by the live zoom.
      const zoom = Math.max(rf.current?.getViewport().zoom ?? 1, 0.05);
      const radius =
        (Math.min(window.innerWidth, window.innerHeight) * 0.34) / zoom;
      const ring = ringPositions(centre, neighbourKeys, radius);

      const snapshot = new Map<string, { x: number; y: number }>();
      const next = current.map((item) => {
        snapshot.set(item.id, { ...item.position });
        const target = ring.get(item.id);
        if (!target) return item;
        const size = sizeOf(item.id);
        return {
          ...item,
          position: {
            x: target.x - (size?.width ?? 0) / 2,
            y: target.y - (size?.height ?? 0) / 2,
          },
        };
      });
      hoverSnapshotRef.current = snapshot;
      // React Flow runs uncontrolled (defaultNodes): the canvas owns the live
      // positions, so the ring must be written through the instance.
      rf.current?.setNodes(next);
    },
    [links, nodes],
  );

  const handleNodeMouseLeave = useCallback(() => {
    setHoveredNodeId(null);
    magnetRef.current = false;
    const snapshot = hoverSnapshotRef.current;
    hoverSnapshotRef.current = null;
    if (snapshot) {
      rf.current?.setNodes((current) =>
        current.map((item) => {
          const original = snapshot.get(item.id);
          return original ? { ...item, position: original } : item;
        }),
      );
    }
    // Resume where it stopped; an isolated neighbourhood stays settled.
    if (!isolatedNodeId && !prefersReducedMotion()) {
      layoutRef.current?.start();
    }
  }, [isolatedNodeId]);

  /** "Abrir ficha" in the inspector — navigate by the entity NAME (the same
   *  identifier WikiLink uses). The entity page resolves a name, not a file
   *  path; passing the path left the backend unable to resolve it and the
   *  page rendered a blank screen (crash on a malformed entity). */
  const handleOpenFicha = useCallback(() => {
    if (!selectedEntity) return;
    const encoded = selectedEntity.name
      .split("/")
      .map((s) => encodeURIComponent(s))
      .join("/");
    navigate(`/wiki/${encodeURIComponent(mundo)}/entity/${encoded}`);
  }, [selectedEntity, mundo, navigate]);

  /** Neighbor link clicked in the inspector: center the neighbor node in the
   *  viewport. Only visible neighbors are clickable, so the id is always in
   *  the current node set; fitView with an unknown id is a safe no-op. */
  const handleNeighborClick = useCallback((nodeKey: string) => {
    rf.current?.fitView({ nodes: [{ id: nodeKey }], duration: 300 });
  }, []);

  /** Select a search result: center the matching flow node in the viewport.
   *  The node id is nodeKey(entity) (canonical id, path fallback) — the same
   *  id the flow nodes use. Results for entities not in the current node set
   *  (orphans hidden by default, status filter) are safe no-ops. */
  const handleSelectResult = useCallback(
    (result: SearchResult) => {
      setSearchQuery("");
      const entity = entities.find(
        (e) => e.path === result.path || e.name === result.name,
      );
      if (!entity) return;
      rf.current?.fitView({ nodes: [{ id: nodeKey(entity) }], duration: 300 });
    },
    [entities],
  );

  /** Resolve the two entities behind a proposed connection. The node ids are
   *  nodeKey(entity) (canonical id, path fallback), so both endpoints resolve
   *  back to GraphEntities. */
  const resolveEndpoints = useCallback(
    (sourceId: string, targetId: string) => {
      const source = entities.find((e) => nodeKey(e) === sourceId);
      const target = entities.find((e) => nodeKey(e) === targetId);
      if (!source || !target || !target.id) return null;
      return { source, target };
    },
    [entities],
  );

  /** onConnect — the author dragged (or click-connected) node-to-node:
   *  stage the create proposal and open the confirmation gate. */
  const handleConnect = useCallback(
    (connection: Connection) => {
      const resolved = resolveEndpoints(
        connection.source,
        connection.target,
      );
      if (!resolved) return;
      const { source, target } = resolved;
      setPendingConnection({
        kind: "create",
        sourcePath: source.path,
        sourceLabel: source.name,
        targetId: target.id,
        targetLabel: target.name,
      });
    },
    [resolveEndpoints],
  );

  /** onEdgeClick — the author clicked an existing edge: stage the break
   *  proposal for the source ficha and open the confirmation gate. */
  const handleEdgeClick = useCallback(
    (_event: React.MouseEvent, edge: Edge) => {
      const resolved = resolveEndpoints(edge.source, edge.target);
      if (!resolved) return;
      const { source, target } = resolved;
      setPendingBreak({
        kind: "break",
        sourcePath: source.path,
        sourceLabel: source.name,
        targetId: target.id,
        targetLabel: target.name,
      });
    },
    [resolveEndpoints],
  );

  const closeModal = useCallback(() => {
    setPendingConnection(null);
    setPendingBreak(null);
    setModalError(null);
  }, []);

  /** Modal confirm — the governance gate: only now does the write hit the
   *  backend (create or break). On success re-fetch the graph so the new/
   *  removed edge renders; on failure keep the modal open and toast the error. */
  const handleConfirm = useCallback(async () => {
    const pending = pendingConnection ?? pendingBreak;
    if (!pending) return;
    setModalBusy(true);
    setModalError(null);
    try {
      if (pending.kind === "create") {
        await createRelation(mundo, pending.sourcePath, pending.targetId);
      } else {
        await breakRelation(mundo, pending.sourcePath, pending.targetId);
      }
      closeModal();
      await load();
      setToast({ message: t("graph.connectionUpdated"), kind: "success" });
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "No se pudo actualizar la conexión";
      setModalError(message);
      setToast({ message, kind: "error" });
    } finally {
      setModalBusy(false);
    }
  }, [pendingConnection, pendingBreak, mundo, load, closeModal]);

  /** Re-heat after an interaction. Animated when motion is allowed; under
   *  reduced motion the neighbourhood settles synchronously in the same tick
   *  (S1/S3). */
  const reheatAfterInteraction = useCallback(
    (alpha: number) => {
      const layout = layoutRef.current;
      if (!layout) return;
      if (reducedMotionRef.current) {
        layout.reheat(SETTLE_ALPHA);
        applyPositions(layout.step(SETTLE_TICKS));
        return;
      }
      layout.reheat(alpha);
      layout.start();
    },
    [applyPositions],
  );

  /** Drag start: pin the node where the author grabbed it and wake the
   *  simulation so its neighbours react (Obsidian-style live physics). */
  const handleNodeDragStart = useCallback(
    (_event: unknown, node: Node) => {
      const layout = layoutRef.current;
      if (!layout) return;
      const centre = topLeftToCentre(node.id, node.position);
      layout.pin(node.id, centre.x, centre.y);
      if (!reducedMotionRef.current) {
        layout.reheat(DRAG_REHEAT_ALPHA);
        layout.start();
      }
    },
    [topLeftToCentre],
  );

  const handleNodeDrag = useCallback(
    (_event: unknown, node: Node) => {
      const layout = layoutRef.current;
      if (!layout) return;
      // The dragged node follows the pointer exactly; it must never drift.
      const centre = topLeftToCentre(node.id, node.position);
      layout.pin(node.id, centre.x, centre.y);
      if (!reducedMotionRef.current && layout.isSettled()) {
        layout.reheat(DRAG_REHEAT_ALPHA);
        layout.start();
      }
    },
    [topLeftToCentre],
  );

  // Drop: the node STAYS pinned (Obsidian keeps dragged nodes put) and is
  // pushed out of any overlap — collide cannot separate a pinned node, and the
  // extent bounds the canvas but not node-vs-node stacking.
  const handleNodeDragStop = useCallback(
    (_event: unknown, dragged: Node) => {
      const layout = layoutRef.current;
      if (!layout) return;
      const simCentres = layout.positions();
      const current = rf.current?.getNodes() ?? nodes;
      const dw = dragged.measured?.width ?? NODE_MIN_WIDTH;
      const dh = dragged.measured?.height ?? NODE_MIN_HEIGHT;
      let nx = dragged.position.x;
      let ny = dragged.position.y;
      for (const other of current) {
        if (other.id === dragged.id) continue;
        const ow = other.measured?.width ?? NODE_MIN_WIDTH;
        const oh = other.measured?.height ?? NODE_MIN_HEIGHT;
        const centre = simCentres.get(other.id) ?? topLeftToCentre(other.id, other.position);
        const position = { x: centre.x - ow / 2, y: centre.y - oh / 2 };
        const overlapX = Math.min(
          nx + dw - position.x,
          position.x + ow - nx,
        );
        const overlapY = Math.min(
          ny + dh - position.y,
          position.y + oh - ny,
        );
        if (overlapX > 0 && overlapY > 0) {
          // Push out along the axis of least penetration.
          if (overlapX < overlapY) {
            nx = nx < position.x ? position.x - dw : position.x + ow;
          } else {
            ny = ny < position.y ? position.y - dh : position.y + oh;
          }
        }
      }
      const centre = {
        x: nx + dw / 2,
        y: ny + dh / 2,
      };
      layout.pin(dragged.id, centre.x, centre.y);
      reheatAfterInteraction(DROP_REHEAT_ALPHA);
    },
    [nodes, reheatAfterInteraction, topLeftToCentre],
  );

  return (
    <div className="flex h-full w-full flex-col">
      <div
        className={
          bleed
            ? "relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface"
            : "relative flex h-[calc(100dvh-18rem)] min-h-[520px] w-full flex-col overflow-hidden rounded-xl border border-edge bg-surface"
        }
        data-testid="graph-surface"
      >
        {loading && (
          <div className="flex h-full items-center justify-center">
            <Spinner size="lg" />
          </div>
        )}

        {error && !loading && (
          <div className="flex h-full items-center justify-center p-6 md:pl-80">
            <ErrorBanner message={error} onRetry={() => void load()} />
          </div>
        )}

        {!loading && !error && entities.length === 0 && (
          <div className="flex h-full items-center justify-center p-6 md:pl-80">
            <EmptyState icon="empty" message={t("graph.noEntities")} />
          </div>
        )}

        {!loading && !error && entities.length > 0 && nodes.length === 0 && (
          <div className="flex h-full items-center justify-center p-6 md:pl-80">
            <EmptyState icon="empty" message={t("graph.noNodes")} />
          </div>
        )}

        {!loading && !error && nodes.length > 0 && (
          <ZoomTierContext.Provider value={zoomTier}>
            <HoverFocusContext.Provider value={hoverFocus}>
              <div className="relative h-full w-full" data-testid="graph-view">
              <ReactFlow
                key={canvasKey}
                // Uncontrolled on purpose: the force engine owns live positions
                // and writes them through the instance store (S2), so this
                // component never re-renders per animation frame.
                defaultNodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                onNodeClick={handleNodeClick}
                onNodeMouseEnter={handleNodeMouseEnter}
                onNodeMouseLeave={handleNodeMouseLeave}
                onNodeDragStart={handleNodeDragStart}
                onNodeDrag={handleNodeDrag}
                onNodeDragStop={handleNodeDragStop}
                onConnect={handleConnect}
                onEdgeClick={handleEdgeClick}
                onMove={() => positionClusters(positionsRef.current)}
                onInit={(inst) => {
                  rf.current = inst;
                  // Measurements may have re-settled the layout before the
                  // instance existed; push the latest positions once.
                  if (positionsRef.current.size > 0) {
                    applyPositions(positionsRef.current);
                  }
                }}
                minZoom={0.2}
                maxZoom={2}
                className="h-full w-full"
              >
                <Background />
                <AutoFit />
                <ZoomTierWatcher
                  semanticThreshold={SEMANTIC_ZOOM_THRESHOLD}
                  labelThreshold={LABEL_ZOOM_THRESHOLD}
                  onChange={setZoomTier}
                />
                {/* Section clusters (S7): they orient the far view; close up
                    they would only add noise over the cards, so they hide. */}

              </ReactFlow>

              {/* Section labels live OUTSIDE the viewport transform: they keep
                  a constant pixel size, so the far view is readable without
                  zooming in (where the node names take over). */}
              {zoomTier !== "labels" ? (
                <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
                  {clusters.map((cluster) => (
                    <div
                      key={cluster.id}
                      ref={(element) => {
                        if (element) {
                          clusterRefs.current.set(cluster.id, element);
                        } else {
                          clusterRefs.current.delete(cluster.id);
                        }
                      }}
                      data-testid="graph-cluster"
                      className="absolute left-0 top-0 whitespace-nowrap text-xs font-semibold uppercase tracking-[0.14em] text-muted/80 [text-shadow:0_1px_3px_rgba(0,0,0,0.95)]"
                    >
                      {cluster.label}
                    </div>
                  ))}
                </div>
              ) : null}

              {isolatedNodeId ? (
                <div
                  data-testid="isolation-pill"
                  className="absolute left-2 top-2 z-30 flex items-center gap-2 rounded-full border border-edge bg-surface-raised/95 px-3 py-1 text-small shadow-sm backdrop-blur-sm"
                >
                  <span className="max-w-[16rem] truncate text-primary">
                    {t("graph.isolatedHint", {
                      name:
                        entityByKey.get(isolatedNodeId)?.name ?? isolatedNodeId,
                    })}
                  </span>
                  <button
                    type="button"
                    onClick={exitIsolation}
                    className="rounded-full border border-edge px-2 py-0.5 text-xs text-action transition-colors hover:border-action"
                  >
                    {t("graph.exitIsolation")}
                  </button>
                </div>
              ) : null}

              {/* Focus toggle: hide the inspector to give the canvas every pixel;
                  toggling back restores the last width. It docks to the left edge
                  of the floating panel while the panel is open. */}
              {selectedEntity && (
                <button
                  type="button"
                  onClick={() => setFocusMode((prev) => !prev)}
                  aria-label={
                    focusMode
                      ? "Mostrar panel de inspección"
                      : "Ocultar panel de inspección"
                  }
                  aria-pressed={focusMode}
                  style={
                    {
                      "--inspector-offset": `${panelWidth + 8}px`,
                    } as CSSProperties
                  }
                  className={cn(
                    "absolute right-2 top-2 z-30 rounded border border-edge bg-surface-raised/90 p-1.5 text-icon-muted shadow-sm backdrop-blur-sm transition-colors hover:text-primary",
                    !focusMode && "md:right-[var(--inspector-offset)]",
                  )}
                >
                  <Icon
                    name={focusMode ? "minimize" : "expand"}
                    size={16}
                  />
                </button>
              )}

              {/* Inspector floats over the canvas at a fixed width; the divider
                  on its left edge resizes it. Hidden on small screens and in
                  focus mode; absent entirely when nothing is selected. */}
              {selectedEntity && !focusMode && (
                <>
                  <div
                    role="separator"
                    aria-orientation="vertical"
                    aria-label={t("graph.resizeInspector")}
                    tabIndex={0}
                    onMouseDown={startPanelDrag}
                    onKeyDown={(e) => {
                      const { min, max } = panelLimits();
                      const step = 40;
                      if (e.key === "ArrowLeft")
                        setPanelWidth((w) => Math.min(max, w + step));
                      if (e.key === "ArrowRight")
                        setPanelWidth((w) => Math.max(min, w - step));
                    }}
                    style={{ right: panelWidth }}
                    className={cn(
                      "absolute top-0 z-20 hidden h-full w-2 cursor-col-resize items-center justify-center border-l border-edge bg-surface-raised/80 backdrop-blur-sm transition-colors hover:bg-surface-hover active:bg-surface-hover md:flex",
                      draggingPanel && "bg-surface-hover select-none",
                    )}
                  >
                    <Icon name="grip" size={14} className="text-muted" />
                  </div>

                  <div
                    className="absolute right-0 top-0 z-10 hidden h-full overflow-hidden border-l border-edge bg-surface/90 shadow-2xl backdrop-blur-md md:flex"
                    style={{ width: panelWidth }}
                    data-testid="node-inspector"
                  >
                    <NodeInspectorPanel
                      entity={selectedEntity}
                      visibleEntityKeys={visibleEntityKeys}
                      entityByKey={entityByKey}
                      onNeighborClick={handleNeighborClick}
                      onOpenFicha={handleOpenFicha}
                      onClose={() => setSelectedNodeId(null)}
                      onIsolate={() =>
                        selectedNodeId && setIsolatedNodeId(selectedNodeId)
                      }
                      onRemoveRelation={(targetKey) => {
                        const sourcePath = selectedEntity?.path;
                        if (!sourcePath) return;
                        void (async () => {
                          try {
                            await breakRelation(mundo, sourcePath, targetKey);
                            await load();
                            setToast({
                              message: t("graph.relationRemoved"),
                              kind: "success",
                            });
                          } catch (err) {
                            const message =
                              err instanceof Error
                                ? err.message
                                : t("graph.connectionError");
                            setToast({ message, kind: "error" });
                          }
                        })();
                      }}
                      mundo={mundo}
                    />
                  </div>
                </>
              )}
            </div>
            </HoverFocusContext.Provider>
          </ZoomTierContext.Provider>
        )}

        {/* Controls float over the canvas instead of shrinking it (S4). */}
        {!loading && !error && (
          <GraphControlsSidebar
            status={status}
            onStatusChange={setStatus}
            selectedFolders={selectedFolders}
            onSelectedFoldersChange={setSelectedFolders}
            showOrphans={showOrphans}
            onShowOrphansChange={setShowOrphans}
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
            searchResults={searchResults}
            searching={searching}
            searchError={searchError}
            onSelectResult={handleSelectResult}
            folderTree={folderTree}
            onFitView={() => rf.current?.fitView()}
          />
        )}
      </div>

      {/* Gated write modal: the author reviews the pending connection change
          (create or break) before it is persisted. Cancel/overlay/Escape abort
          with no API call — the write only happens on explicit confirm. */}
      {(pendingConnection || pendingBreak) && (
        <ConfirmDialog
          title={pendingConnection ? "Crear conexión" : "Romper conexión"}
          message={
            pendingConnection
              ? `Conectar "${pendingConnection.sourceLabel}" con "${pendingConnection.targetLabel}"?`
              : `Romper la conexión entre "${pendingBreak!.sourceLabel}" y "${pendingBreak!.targetLabel}"?`
          }
          confirmLabel={pendingConnection ? "Crear" : "Romper"}
          isBusy={modalBusy}
          error={modalError}
          onConfirm={() => void handleConfirm()}
          onClose={closeModal}
        />
      )}

      {toast && <Toast message={toast.message} kind={toast.kind} />}
    </div>
  );
}