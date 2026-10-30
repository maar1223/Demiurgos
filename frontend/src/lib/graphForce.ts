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
import type { EntityLink, GraphEntity } from "@/api/types";

/**
 * Force-directed layout for the relations graph.
 *
 * Two entry points, one force stack:
 * - `computeForcePositions` settles synchronously and returns the positions
 *   (the reduced-motion path and the fallback for non-animated contexts);
 * - `createLiveForceLayout` owns a persistent simulation that can be ticked,
 *   re-heated and pinned, so the graph can move like a living map.
 *
 * The simulation NEVER runs on its own timer unless `start()` is called, and
 * `start()` only advances through the injected ticker. Tests drive it with
 * `step()`/`settle()`, so nothing depends on wall-clock time.
 */

/** Simulation node: a d3-force datum carrying the entity's node key as id. */
interface SimNode extends SimulationNodeDatum {
  id: string;
}

type SimLink = SimulationLinkDatum<SimNode>;

export interface ForcePosition {
  x: number;
  y: number;
}

export type ForcePositions = Map<string, ForcePosition>;

/** Schedules one simulation step and returns its cancel handle. */
export type ForceTicker = (step: () => void) => () => void;

export interface LiveForceLayoutOptions {
  entities: GraphEntity[];
  links: EntityLink[];
  size: number;
  ticker?: ForceTicker;
}

export interface LiveForceLayout {
  /** Advance `ticks` steps synchronously and return the clamped positions. */
  step(ticks?: number): ForcePositions;
  /** Jump straight to the settled layout (reduced motion). */
  settle(): ForcePositions;
  /** Raise alpha so the layout starts moving again. */
  reheat(alpha?: number): void;
  /** Pin a node at an exact position (dragging). */
  pin(id: string, x: number, y: number): void;
  /** Release a pinned node. */
  release(id: string): void;
  positions(): ForcePositions;
  isSettled(): boolean;
  /** Drive the simulation through the ticker until it settles. */
  start(): void;
  stop(): void;
  /** Called with the clamped positions after every animation frame. */
  onPositions?: (positions: ForcePositions) => void;
}

/** The node id used by React Flow: the entity id, falling back to its path. */
export function nodeKey(entity: GraphEntity): string {
  return entity.id || entity.path;
}

/** Minimum layout area side; grows with node count so nodes never overlap. */
const LAYOUT_MIN_SIZE = 400;
/** Per-node target spacing used to size the layout area. */
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
/** Synchronous settle budget; enough for ~52-node worlds. */
export const SETTLE_TICKS = 300;
/** Initial alpha the simulation cools down from. */
const ALPHA_START = 1;
/** Alpha reached after the settle budget. Below d3's alphaMin (0.001) on
 *  purpose: relying on the default decay leaves alpha exactly at the
 *  threshold after 300 ticks, which makes "settled" flaky. */
const ALPHA_AFTER_SETTLE = 0.0005;

/**
 * Layout area side length scales with node count (sqrt(N) * spacing) so the
 * graph has room to spread nodes without collapsing into a blob.
 */
export function computeLayoutSize(nodeCount: number): number {
  return Math.max(
    LAYOUT_MIN_SIZE,
    Math.sqrt(Math.max(1, nodeCount)) * LAYOUT_NODE_SPACING,
  );
}

/**
 * Custom d3-force: repels every node from edge SEGMENTS it is NOT connected
 * to. Keeps a node from sitting on another group's relations, which visually
 * reads as a connection that does not exist.
 */
function edgeAvoidanceForce(simNodes: SimNode[], simLinks: SimLink[]) {
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

/** requestAnimationFrame ticker with a timer fallback for non-browser hosts. */
const animationFrameTicker: ForceTicker = (step) => {
  if (typeof requestAnimationFrame === "function") {
    const handle = requestAnimationFrame(step);
    return () => cancelAnimationFrame(handle);
  }
  const handle = setTimeout(step, 16) as unknown as number;
  return () => clearTimeout(handle);
};

/**
 * Build a live d3-force layout for the visible entities.
 *
 * Only links whose endpoints are both visible participate, mirroring the edge
 * filtering in the view, so the layout and the rendered edges always agree.
 */
export function createLiveForceLayout(
  options: LiveForceLayoutOptions,
): LiveForceLayout {
  const { entities, links, size } = options;
  const ticker = options.ticker ?? animationFrameTicker;

  const visible = new Set(entities.map(nodeKey));
  const simNodes: SimNode[] = entities.map((entity) => ({
    id: nodeKey(entity),
  }));
  const nodeById = new Map(simNodes.map((node) => [node.id, node]));
  const simLinks: SimLink[] = links
    .filter((link) => visible.has(link.source) && visible.has(link.target))
    .map((link) => ({ source: link.source, target: link.target }));

  const clamp = (value: number) => Math.min(size, Math.max(0, value));

  const simulation = forceSimulation<SimNode>(simNodes)
    .force(
      "link",
      forceLink<SimNode, SimLink>(simLinks)
        .id((node) => node.id)
        .distance(LINK_DISTANCE),
    )
    .force("charge", forceManyBody<SimNode>().strength(CHARGE_STRENGTH))
    .force("center", forceCenter<SimNode>(size / 2, size / 2))
    .force("x", forceX<SimNode>(size / 2).strength(CENTER_STRENGTH))
    .force("y", forceY<SimNode>(size / 2).strength(CENTER_STRENGTH))
    .force(
      "collide",
      forceCollide<SimNode>().radius(NODE_COLLIDE_RADIUS).strength(0.8),
    )
    .force("edgeAvoid", edgeAvoidanceForce(simNodes, simLinks))
    .alpha(ALPHA_START)
    .alphaDecay(1 - Math.pow(ALPHA_AFTER_SETTLE / ALPHA_START, 1 / SETTLE_TICKS))
    .stop();

  let cancelFrame: (() => void) | null = null;

  const positions = (): ForcePositions => {
    const result: ForcePositions = new Map();
    for (const node of simNodes) {
      result.set(node.id, { x: clamp(node.x ?? 0), y: clamp(node.y ?? 0) });
    }
    return result;
  };

  const layout: LiveForceLayout = {
    step(ticks = 1) {
      for (let index = 0; index < ticks; index += 1) simulation.tick();
      return positions();
    },
    settle() {
      simulation.alpha(ALPHA_START);
      simulation.tick(SETTLE_TICKS);
      return positions();
    },
    reheat(alpha = 0.6) {
      simulation.alpha(alpha);
      simulation.alphaTarget(0);
    },
    pin(id, x, y) {
      const node = nodeById.get(id);
      if (!node) return;
      // x/y move with the pin, not only fx/fy: a dragged node is visually
      // here NOW, and positions() must agree before the next tick.
      node.fx = x;
      node.fy = y;
      node.x = x;
      node.y = y;
    },
    release(id) {
      const node = nodeById.get(id);
      if (!node) return;
      node.fx = null;
      node.fy = null;
    },
    positions,
    isSettled() {
      return simulation.alpha() <= simulation.alphaMin();
    },
    start() {
      if (cancelFrame) return;
      const frame = () => {
        simulation.tick();
        layout.onPositions?.(positions());
        if (layout.isSettled()) {
          cancelFrame = null;
          return;
        }
        cancelFrame = ticker(frame);
      };
      cancelFrame = ticker(frame);
    },
    stop() {
      if (!cancelFrame) return;
      const cancel = cancelFrame;
      cancelFrame = null;
      cancel();
    },
  };

  return layout;
}

/**
 * Settled layout for the same force stack — the deterministic path used by
 * reduced motion and by contexts that must not animate.
 */
export function computeForcePositions(
  entities: GraphEntity[],
  links: EntityLink[],
  size: number,
): ForcePositions {
  return createLiveForceLayout({ entities, links, size }).settle();
}
