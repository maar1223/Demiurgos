import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  forceCenter,
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
  type CoordinateExtent,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { fetchGraphEntities, type GraphStatusFilter } from "@/api/graph";
import type { EntityLink, FichaStatus, GraphEntity } from "@/api/types";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { Spinner } from "@/components/atoms/Spinner";
import { cn } from "@/lib/utils";

/** Node key: canonical id when present, path fallback for legacy entities. */
function nodeKey(entity: GraphEntity): string {
  return entity.id || entity.path;
}

/**
 * Simulation node: d3-force datum carrying the entity's node key as id.
 * `x`/`y` are filled in by the simulation.
 */
interface SimNode extends SimulationNodeDatum {
  id: string;
}

/** Force-layout canvas (matches the graph container's 480px height). */
const LAYOUT_WIDTH = 800;
const LAYOUT_HEIGHT = 480;
/** Hard bounds for the layout and node dragging: nodes can never leave this
 *  region, so nothing can drift off into an infinite canvas. */
const LAYOUT_BOUNDS: CoordinateExtent = [
  [0, 0],
  [LAYOUT_WIDTH, LAYOUT_HEIGHT],
];
/** Preferred link length in the settled layout. */
const LINK_DISTANCE = 130;
/** Repulsive force between every node pair (negative = repel). */
const CHARGE_STRENGTH = -300;
/** Strength pulling every node toward the center (limits group spread). */
const CENTER_STRENGTH = 0.08;
/** Synchronous settle budget; enough for ~52-node worlds. */
const SETTLE_TICKS = 300;

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
): Map<string, { x: number; y: number }> {
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
    .force("center", forceCenter<SimNode>(LAYOUT_WIDTH / 2, LAYOUT_HEIGHT / 2))
    .force("x", forceX<SimNode>(LAYOUT_WIDTH / 2).strength(CENTER_STRENGTH))
    .force("y", forceY<SimNode>(LAYOUT_HEIGHT / 2).strength(CENTER_STRENGTH))
    .stop();

  simulation.tick(SETTLE_TICKS);

  const positions = new Map<string, { x: number; y: number }>();
  for (const node of simulation.nodes()) {
    // Clamp to the layout bounds so clusters never spread off-canvas.
    const x = Math.min(Math.max(node.x ?? 0, LAYOUT_BOUNDS[0][0]), LAYOUT_BOUNDS[1][0]);
    const y = Math.min(Math.max(node.y ?? 0, LAYOUT_BOUNDS[0][1]), LAYOUT_BOUNDS[1][1]);
    positions.set(node.id, { x, y });
  }
  return positions;
}

/** Solid-background node look keyed by status (chips keep translucent bg).
 *  Border colors match STATUS_META so node colors never drift from chips. */
const NODE_STATUS_CLASS: Record<FichaStatus, string> = {
  draft: "border-amber-400/50 text-amber-200",
  stable: "border-emerald-500/60 text-emerald-200",
};

interface GraphNodeData extends Record<string, unknown> {
  label: string;
}

/** Custom node type: centered source/target handles so edges meet at the
 *  node center (Obsidian-style) instead of fanning from top/bottom edges. */
type GraphNodeType = Node<GraphNodeData, "graph">;

function GraphNode({ data }: NodeProps<GraphNodeType>) {
  const centerHandleStyle = {
    left: "50%",
    top: "50%",
    transform: "translate(-50%, -50%)",
    opacity: 0,
    pointerEvents: "none",
  } as const;
  return (
    <div className="relative">
      <Handle
        type="target"
        position={Position.Top}
        style={centerHandleStyle}
        isConnectable={false}
      />
      <span>{data.label}</span>
      <Handle
        type="source"
        position={Position.Bottom}
        style={centerHandleStyle}
        isConnectable={false}
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
 * - Node click navigates to the entity ficha route.
 * - Zoom/pan come from React Flow; referencias content is never included
 *   (backend _SCAN_SECTIONS excludes it — FR2.13 note below the filter bar).
 */
export default function GraphView({ mundo }: GraphViewProps) {
  const navigate = useNavigate();
  const [entities, setEntities] = useState<GraphEntity[]>([]);
  const [links, setLinks] = useState<EntityLink[]>([]);
  const [status, setStatus] = useState<GraphStatusFilter>("all");
  const [showOrphans, setShowOrphans] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Draggable node state. Nodes are seeded from the settled force layout and
  // updated by onNodesChange on drag; they are re-seeded only when the
  // dataset (filter/orphans) changes.
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNodeType>([]);
  const rf = useRef<ReactFlowInstance<GraphNodeType, Edge> | null>(null);

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

  // Build the settled force layout and (re)seed the draggable node state
  // whenever the dataset changes (filter/orphans). Dragging a node updates
  // state via onNodesChange and is NOT reset until the dataset changes.
  useEffect(() => {
    if (loading || error) return;
    if (entities.length === 0) {
      setNodes([]);
      return;
    }
    const orphanKeys = new Set(
      entities
        .filter(
          (e) => e.forward_links.length === 0 && e.backlinks.length === 0,
        )
        .map(nodeKey),
    );
    // Orphans hidden by default (W12); the toggle reveals them.
    const visible = showOrphans
      ? entities
      : entities.filter((e) => !orphanKeys.has(nodeKey(e)));

    const positions = computeForcePositions(visible, links);

    const nextNodes: GraphNodeType[] = visible.map((entity) => ({
      id: nodeKey(entity),
      type: "graph",
      position: positions.get(nodeKey(entity)) ?? { x: 0, y: 0 },
      data: { label: entity.name },
      extent: LAYOUT_BOUNDS,
      className: cn(
        "rounded-lg border-2 px-3 py-2 text-xs font-medium bg-surface-raised",
        entity.status
          ? NODE_STATUS_CLASS[entity.status]
          : "border-edge text-muted",
      ),
    }));
    setNodes(nextNodes);
    requestAnimationFrame(() => rf.current?.fitView({ padding: 0.2 }));
  }, [entities, links, showOrphans, loading, error, setNodes]);

  // Edges derived from the current node set (read-only; follow dragged nodes).
  const edges = useMemo(() => {
    const nodeIds = new Set(nodes.map((n) => n.id));
    return links
      .filter((link) => nodeIds.has(link.source) && nodeIds.has(link.target))
      .map((link): Edge => ({
        id: `${link.source}->${link.target}`,
        source: link.source,
        target: link.target,
      }));
  }, [nodes, links]);

  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      const entity = entities.find((e) => nodeKey(e) === node.id);
      if (!entity) return;
      const encoded = entity.path
        .split("/")
        .map((s) => encodeURIComponent(s))
        .join("/");
      navigate(`/wiki/${encodeURIComponent(mundo)}/entity/${encoded}`);
    },
    [entities, mundo, navigate],
  );

  return (
    <div className="flex flex-col gap-3">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-small text-muted">
          <span>Estado</span>
          <select
            aria-label="Filtrar por estado"
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as GraphStatusFilter)
            }
            className="rounded border border-edge bg-surface-raised px-2 py-1 text-small text-primary"
          >
            <option value="all">Todos los estados</option>
            <option value="draft">Borrador</option>
            <option value="stable">Canon</option>
          </select>
        </label>

        <label className="flex items-center gap-2 text-small text-muted">
          <input
            type="checkbox"
            checked={showOrphans}
            onChange={(event) => setShowOrphans(event.target.checked)}
          />
          Mostrar nodos aislados
        </label>

        <button
          type="button"
          onClick={() => rf.current?.fitView({ padding: 0.2 })}
          className="rounded border border-edge bg-surface-raised px-3 py-1 text-small text-primary transition-colors hover:border-action"
        >
          Ver todo
        </button>
      </div>

      {/* Referencias-exclusion note (FR2.13) */}
      <p className="text-xs text-muted">
        El grafo no incluye contenido de Referencias
      </p>

      {loading && (
        <div className="flex items-center justify-center py-24">
          <Spinner size="lg" />
        </div>
      )}

      {error && !loading && (
        <ErrorBanner message={error} onRetry={() => void load()} />
      )}

      {!loading && !error && nodes.length === 0 && (
        <EmptyState
          icon="empty"
          message="No hay entidades indexadas para este mundo."
        />
      )}

      {!loading && !error && nodes.length > 0 && (
        <div
          className="h-[480px] w-full rounded-xl border border-edge bg-surface"
          data-testid="graph-view"
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            nodeTypes={nodeTypes}
            defaultEdgeOptions={{ type: "straight" }}
            onNodeClick={handleNodeClick}
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
        </div>
      )}
    </div>
  );
}