import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Background,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { fetchGraphEntities, type GraphStatusFilter } from "@/api/graph";
import type { EntityLink, GraphEntity } from "@/api/types";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { Spinner } from "@/components/atoms/Spinner";
import { STATUS_META } from "@/lib/status";
import { cn } from "@/lib/utils";

/** Node key: canonical id when present, path fallback for legacy entities. */
function nodeKey(entity: GraphEntity): string {
  return entity.id || entity.path;
}

/**
 * Explicit deterministic layered-grid layout — NO dagre, NO second graph
 * dependency. Entities are grouped by type, types sorted alphabetically,
 * one row per type, entities placed left-to-right in backend order (paths
 * are sorted server-side). Satisfies NFR1.2 for ~52 nodes.
 */
function computePositions(
  entities: GraphEntity[],
): Map<string, { x: number; y: number }> {
  const byType = new Map<string, GraphEntity[]>();
  for (const entity of entities) {
    const type = entity.type || "Ficha";
    const list = byType.get(type);
    if (list) {
      list.push(entity);
    } else {
      byType.set(type, [entity]);
    }
  }
  const typeOrder = Array.from(byType.keys()).sort((a, b) =>
    a.localeCompare(b),
  );
  const positions = new Map<string, { x: number; y: number }>();
  const COL_GAP = 280;
  const ROW_GAP = 140;
  const PAD = 60;
  let y = PAD;
  for (const type of typeOrder) {
    const list = byType.get(type) ?? [];
    list.forEach((entity, i) => {
      positions.set(nodeKey(entity), { x: PAD + i * COL_GAP, y });
    });
    y += ROW_GAP;
  }
  return positions;
}

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

  const { nodes, edges } = useMemo(() => {
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

    const positions = computePositions(visible);

    const nodes: Node[] = visible.map((entity) => {
      const meta = entity.status ? STATUS_META[entity.status] : undefined;
      return {
        id: nodeKey(entity),
        position: positions.get(nodeKey(entity)) ?? { x: 0, y: 0 },
        data: { label: entity.name },
        className: cn(
          "rounded-lg border-2 px-3 py-2 text-xs font-medium",
          meta
            ? meta.chipClass
            : "border-edge bg-surface-raised text-muted",
        ),
      };
    });

    const nodeIds = new Set(nodes.map((n) => n.id));
    // Edges to/from hidden nodes are removed too (spec S2.5).
    const edges: Edge[] = links
      .filter((link) => nodeIds.has(link.source) && nodeIds.has(link.target))
      .map((link) => ({
        id: `${link.source}->${link.target}`,
        source: link.source,
        target: link.target,
      }));

    return { nodes, edges };
  }, [entities, links, showOrphans]);

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
            onNodeClick={handleNodeClick}
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