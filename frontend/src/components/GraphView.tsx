import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import {
  Background,
  Handle,
  Position,
  ReactFlow,
  useNodesState,
  type Connection,
  type CoordinateExtent,
  type Edge,
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
import { Icon } from "@/components/atoms/Icon";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { GraphControlsSidebar } from "@/components/organisms/GraphControlsSidebar";
import { NodeInspectorPanel } from "@/components/organisms/NodeInspectorPanel";
import {
  buildFolderTree,
  filterEntitiesByFolders,
  type FolderNode,
} from "@/lib/graphFilters";
import { cn } from "@/lib/utils";

/** Node key: canonical id when present, path fallback for legacy entities. */
function nodeKey(entity: GraphEntity): string {
  return entity.id || entity.path;
}

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

/**
 * Simulation node: d3-force datum carrying the entity's node key as id.
 * `x`/`y` are filled in by the simulation.
 */
interface SimNode extends SimulationNodeDatum {
  id: string;
}

/** Minimum layout area side; grows with node count so nodes never overlap. */
const LAYOUT_MIN_SIZE = 400;
/** Per-node target spacing used to size the layout area (no collision force). */
const LAYOUT_NODE_SPACING = 180;
/** Preferred link length in the settled layout. */
const LINK_DISTANCE = 160;
/** Repulsive force between every node pair (negative = repel). */
const CHARGE_STRENGTH = -400;
/** Strength pulling every node toward the center (limits group spread). */
const CENTER_STRENGTH = 0.06;
/** Collision radius keeping node centers apart so labels never overlap. */
const NODE_COLLIDE_RADIUS = 75;
/** Minimum distance a node center keeps from edges it is NOT connected to,
 *  so a node never sits on another group's relations looking connected. */
const EDGE_MIN_DISTANCE = 60;
/** Fallback node size used when measured dimensions are unavailable. */
const NODE_MIN_WIDTH = 140;
const NODE_MIN_HEIGHT = 36;
/** Synchronous settle budget; enough for ~52-node worlds. */
const SETTLE_TICKS = 300;

/**
 * Layout area side length scales with node count (sqrt(N) * spacing) so the
 * graph has room to spread nodes without overlapping — no collision force.
 */
function computeLayoutSize(nodeCount: number): number {
  return Math.max(
    LAYOUT_MIN_SIZE,
    Math.sqrt(Math.max(1, nodeCount)) * LAYOUT_NODE_SPACING,
  );
}

/**
 * Custom d3-force: repels every node from edge SEGMENTS it is NOT connected
 * to. Keeps a node from sitting on another group's relations, which visually
 * reads as a connection that does not exist. Runs inside the settle ticks.
 */
function edgeAvoidanceForce(
  simNodes: SimNode[],
  simLinks: SimulationLinkDatum<SimNode>[],
) {
  return (alpha: number) => {
    for (const node of simNodes) {
      for (const link of simLinks) {
        const sourceNode =
          typeof link.source === "object" ? (link.source as SimNode) : undefined;
        const targetNode =
          typeof link.target === "object" ? (link.target as SimNode) : undefined;
        if (!sourceNode || !targetNode) continue;
        if (sourceNode.id === node.id || targetNode.id === node.id) continue;
        const sx = sourceNode.x ?? 0;
        const sy = sourceNode.y ?? 0;
        const tx = targetNode.x ?? 0;
        const ty = targetNode.y ?? 0;
        const dx = tx - sx;
        const dy = ty - sy;
        const len2 = dx * dx + dy * dy;
        let t = 0;
        if (len2 > 0) {
          t = Math.max(
            0,
            Math.min(
              1,
              (((node.x ?? 0) - sx) * dx + ((node.y ?? 0) - sy) * dy) / len2,
            ),
          );
        }
        const px = sx + t * dx;
        const py = sy + t * dy;
        const dist = Math.hypot((node.x ?? 0) - px, (node.y ?? 0) - py);
        if (dist < EDGE_MIN_DISTANCE && dist > 0.0001) {
          const force = ((EDGE_MIN_DISTANCE - dist) / dist) * alpha * 0.4;
          node.vx = (node.vx ?? 0) + ((node.x ?? 0) - px) * force;
          node.vy = (node.vy ?? 0) + ((node.y ?? 0) - py) * force;
        }
      }
    }
  };
}

/**
 * Force-directed layout via d3-force — replaces the deterministic grid.
 * Nodes repel each other while links pull connected ones together, so the
 * result reads as an organic graph instead of a table. The simulation runs
 * ONCE, synchronously: `stop()` disables the internal timer and a manual
 * `tick()` loop settles it — no async timers, so tests stay deterministic
 * and React never sees updates outside `act()`. No collision force on
 * purpose: overlapping nodes are acceptable (Obsidian-style organic look).
 */
function computeForcePositions(
  entities: GraphEntity[],
  links: EntityLink[],
  size: number,
): Map<string, { x: number; y: number }> {
  const bounds: CoordinateExtent = [
    [0, 0],
    [size, size],
  ];
  const nodeIds = new Set(entities.map(nodeKey));
  const simNodes: SimNode[] = entities.map((entity) => ({
    id: nodeKey(entity),
  }));
  // Only links whose endpoints are both visible participate (mirrors the
  // edge filtering below, so the layout and the rendered edges agree).
  const simLinks: SimulationLinkDatum<SimNode>[] = links
    .filter((link) => nodeIds.has(link.source) && nodeIds.has(link.target))
    .map((link) => ({ source: link.source, target: link.target }));

  const simulation = forceSimulation<SimNode>(simNodes)
    .force(
      "link",
      forceLink<SimNode, SimulationLinkDatum<SimNode>>(simLinks)
        .id((d) => d.id)
        .distance(LINK_DISTANCE),
    )
    .force("charge", forceManyBody<SimNode>().strength(CHARGE_STRENGTH))
    .force("center", forceCenter<SimNode>(size / 2, size / 2))
    .force("x", forceX<SimNode>(size / 2).strength(CENTER_STRENGTH))
    .force("y", forceY<SimNode>(size / 2).strength(CENTER_STRENGTH))
    .force(
      "collide",
      forceCollide<SimNode>()
        .radius(NODE_COLLIDE_RADIUS)
        .strength(0.8),
    )
    .force("edgeAvoid", edgeAvoidanceForce(simNodes, simLinks))
    .stop();

  simulation.tick(SETTLE_TICKS);

  const positions = new Map<string, { x: number; y: number }>();
  for (const node of simulation.nodes()) {
    // Clamp to the layout bounds so clusters never spread off-canvas.
    const x = Math.min(Math.max(node.x ?? 0, bounds[0][0]), bounds[1][0]);
    const y = Math.min(Math.max(node.y ?? 0, bounds[0][1]), bounds[1][1]);
    positions.set(node.id, { x, y });
  }
  return positions;
}

/** Solid-background node look keyed by status (chips keep translucent bg).
 *  Border colors match STATUS_META so node colors never drift from chips.
 *  Text uses dark: variants: dark amber/emerald on light mode, light on dark. */
const NODE_STATUS_CLASS: Record<FichaStatus, string> = {
  draft: "border-amber-400/50 text-amber-700 dark:text-amber-200",
  stable: "border-emerald-500/60 text-emerald-700 dark:text-emerald-200",
};

interface GraphNodeData extends Record<string, unknown> {
  label: string;
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

function GraphNode({ data }: NodeProps<GraphNodeType>) {
  return (
    <div className="relative">
      <Handle
        type="target"
        position={Position.Top}
        style={handleStyle}
        isConnectable={true}
      />
      <span>{data.label}</span>
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

interface GraphViewProps {
  mundo: string;
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
 * - All graph controls (search, status, folder tree, orphans toggle, fitView)
 *   live in the left GraphControlsSidebar. The folder tree is a hierarchical
 *   multi-select that hides nodes outside the selected folders (prefix union);
 *   edges touching hidden nodes vanish.
 * - Zoom/pan come from React Flow.
 */
export default function GraphView({ mundo }: GraphViewProps) {
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

  // Draggable node state. Nodes are seeded from the settled force layout and
  // updated by onNodesChange on drag; they are re-seeded only when the
  // dataset (filter/orphans) changes.
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNodeType>([]);
  const rf = useRef<ReactFlowInstance<GraphNodeType, Edge> | null>(null);

  // Node inspector: selection state plus right-panel resize/focus. The
  // selected entity is DERIVED from the loaded set (by node key), so a status
  // re-fetch or mundo switch can never leave the panel showing stale data.
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [panelWidth, setPanelWidth] = useState<number>(() =>
    clampPanel(RIGHT_DEFAULT),
  );
  const [focusMode, setFocusMode] = useState(false);
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
        err instanceof Error ? err.message : "No se pudo cargar el grafo",
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
  const visibleEntities = useMemo(
    () => filterEntitiesByFolders(entities, selectedFolders),
    [entities, selectedFolders],
  );

  // Inspector lookups: the selected entity is re-derived from the loaded set
  // on every render, so it is never stale after a re-fetch. `entityByKey`
  // covers ALL loaded entities (neighbor resolution still works for
  // filtered-out neighbors, which then render as plain text); the visible
  // key set is exactly the rendered node set (orphan/folder filtered).
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
          err instanceof Error ? err.message : "No se pudo buscar nodos",
        );
        setSearchResults([]);
      } finally {
        if (searchRequestId.current === requestId) setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, mundo]);

  // Build the settled force layout and (re)seed the draggable node state
  // whenever the dataset changes (folder filter/orphans). Dragging a node
  // updates state via onNodesChange and is NOT reset until the dataset
  // changes.
  useEffect(() => {
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
    const visible = showOrphans
      ? visibleEntities
      : visibleEntities.filter((e) => !orphanKeys.has(nodeKey(e)));

    const size = computeLayoutSize(visible.length);
    const positions = computeForcePositions(visible, links, size);
    const bounds: CoordinateExtent = [
      [0, 0],
      [size, size],
    ];

    const nextNodes: GraphNodeType[] = visible.map((entity) => ({
      id: nodeKey(entity),
      type: "graph",
      position: positions.get(nodeKey(entity)) ?? { x: 0, y: 0 },
      data: { label: entity.name },
      extent: bounds,
      className: cn(
        "rounded-lg border-2 px-3 py-2 text-xs font-medium bg-surface-raised",
        entity.status
          ? NODE_STATUS_CLASS[entity.status]
          : "border-edge text-muted",
      ),
    }));
    setNodes(nextNodes);
    requestAnimationFrame(() => rf.current?.fitView({ padding: 0.2 }));
  }, [
    visibleEntities,
    links,
    showOrphans,
    loading,
    error,
    setNodes,
  ]);

  // Edges derived from the current node set (read-only; follow dragged nodes).
  // Mutual references (A→B and B→A) collapse into a single line per pair so
  // one relationship never renders as two overlapping edges.
  const edges = useMemo(() => {
    const nodeIds = new Set(nodes.map((n) => n.id));
    const seen = new Set<string>();
    const result: Edge[] = [];
    for (const link of links) {
      if (!nodeIds.has(link.source) || !nodeIds.has(link.target)) continue;
      const key = [link.source, link.target].sort().join("::");
      if (seen.has(key)) continue;
      seen.add(key);
      result.push({
        id: `${link.source}->${link.target}`,
        source: link.source,
        target: link.target,
      });
    }
    return result;
  }, [nodes, links]);

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
      setToast({ message: "Conexión actualizada", kind: "success" });
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

  // After a drag ends, push the dropped node out of any overlap so nodes can
  // never be left stacked on top of each other (extent bounds the canvas, but
  // not node-vs-node collision).
  const handleNodeDragStop = useCallback(
    (_event: unknown, dragged: Node) => {
      setNodes((current) => {
        const dw = dragged.measured?.width ?? NODE_MIN_WIDTH;
        const dh = dragged.measured?.height ?? NODE_MIN_HEIGHT;
        let nx = dragged.position.x;
        let ny = dragged.position.y;
        for (const other of current) {
          if (other.id === dragged.id) continue;
          const ow = other.measured?.width ?? NODE_MIN_WIDTH;
          const oh = other.measured?.height ?? NODE_MIN_HEIGHT;
          const overlapX = Math.min(
            nx + dw - other.position.x,
            other.position.x + ow - nx,
          );
          const overlapY = Math.min(
            ny + dh - other.position.y,
            other.position.y + oh - ny,
          );
          if (overlapX > 0 && overlapY > 0) {
            // Push out along the axis of least penetration.
            if (overlapX < overlapY) {
              nx = nx < other.position.x
                ? other.position.x - dw
                : other.position.x + ow;
            } else {
              ny = ny < other.position.y
                ? other.position.y - dh
                : other.position.y + oh;
            }
          }
        }
        return current.map((n) =>
          n.id === dragged.id ? { ...n, position: { x: nx, y: ny } } : n,
        );
      });
    },
    [setNodes],
  );

  return (
    <div className="flex h-full flex-col gap-3 md:flex-row">
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

      <main className="min-w-0 flex-1">
        {loading && (
          <div className="flex items-center justify-center py-24">
            <Spinner size="lg" />
          </div>
        )}

        {error && !loading && (
          <ErrorBanner message={error} onRetry={() => void load()} />
        )}

        {!loading && !error && entities.length === 0 && (
          <EmptyState
            icon="empty"
            message="No hay entidades indexadas para este mundo."
          />
        )}

        {!loading && !error && entities.length > 0 && nodes.length === 0 && (
          <EmptyState
            icon="empty"
            message="Esta sección no tiene nodos para mostrar."
          />
        )}

        {!loading && !error && nodes.length > 0 && (
          <div
            className="relative min-h-[520px] h-[70vh] w-full rounded-xl border border-edge bg-surface"
            data-testid="graph-view"
          >
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              nodeTypes={nodeTypes}
              defaultEdgeOptions={{ type: "straight" }}
              onNodeClick={handleNodeClick}
              onNodeDragStop={handleNodeDragStop}
              onConnect={handleConnect}
              onEdgeClick={handleEdgeClick}
              onInit={(inst) => {
                rf.current = inst;
              }}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.2}
              maxZoom={2}
            >
              <Background />
            </ReactFlow>

            {/* Focus toggle: hide the inspector (and its divider) to give the
                canvas every pixel; toggling back restores the last width. */}
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
                className="absolute right-2 top-2 z-10 rounded border border-edge bg-surface-raised p-1.5 text-icon-muted shadow-sm transition-colors hover:text-primary"
              >
                <Icon
                  name={focusMode ? "minimize" : "expand"}
                  size={16}
                />
              </button>
            )}
          </div>
        )}
      </main>

      {/* Right-hand inspector (node-inspector): divider + panel, siblings of
          <main> in the flex row (Approach 1). Hidden in focus mode at ALL
          breakpoints; absent entirely when nothing is selected. */}
      {selectedEntity && !focusMode && (
        <>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Redimensionar panel de inspección"
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
            className={cn(
              "hidden md:flex w-2 cursor-col-resize items-center justify-center border-l border-edge bg-surface-raised hover:bg-surface-hover active:bg-surface-hover transition-colors",
              draggingPanel && "bg-surface-hover select-none",
            )}
          >
            <Icon name="grip" size={14} className="text-muted" />
          </div>

          <div
            className="hidden md:flex h-full overflow-hidden"
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
              mundo={mundo}
            />
          </div>
        </>
      )}

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