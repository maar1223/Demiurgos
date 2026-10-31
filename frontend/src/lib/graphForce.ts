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

/** Measured card size used to size the collision radius. */
export interface NodeSize {
  width: number;
  height: number;
}

export type ForcePositions = Map<string, ForcePosition>;

/** Schedules one simulation step and returns its cancel handle. */
export type ForceTicker = (step: () => void) => () => void;

export interface LiveForceLayoutOptions {
  entities: GraphEntity[];
  links: EntityLink[];
  size: number;
  ticker?: ForceTicker;
  /** Measured node sizes; cards are much wider than they are tall, so a fixed
   *  circular radius leaves them overlapping. */
  sizes?: ReadonlyMap<string, NodeSize>;
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
  /** Refresh the collision radii with measured card sizes. */
  updateSizes(sizes: ReadonlyMap<string, NodeSize>): void;
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
const LAYOUT_NODE_SPACING = 230;
/** Minimum link length in the settled layout. */
const LINK_DISTANCE = 240;
/** Extra space between two connected cards, beyond their half widths. */
const LINK_GAP = 40;
/** Minimum gap kept between two card rectangles by the final overlap pass. */
const CARD_GAP = 18;
/** Iterations of the final rectangle-separation pass. */
const SEPARATION_PASSES = 120;
/** Repulsive force between every node pair (negative = repel). */
const CHARGE_STRENGTH = -400;
/** Strength pulling every node toward the center (limits group spread). */
const CENTER_STRENGTH = 0.06;
/** Fallback collision radius, used until a node is measured. */
const NODE_COLLIDE_RADIUS = 75;
/** Fallback card size (rough node card), used to keep cards inside the bounds
 *  before React Flow measures them. */
const NODE_FALLBACK_WIDTH = 150;
const NODE_FALLBACK_HEIGHT = 36;
/** Breathing room added to the measured collision radius. */
const NODE_COLLIDE_PADDING = 10;
/** Minimum distance a node center keeps from edges it is NOT connected to,
 *  so a node never sits on another group's relations looking connected. */
const EDGE_MIN_DISTANCE = 90;
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
  const sizes = new Map<string, NodeSize>(options.sizes ?? []);

  const visible = new Set(entities.map(nodeKey));
  const simNodes: SimNode[] = entities.map((entity) => ({
    id: nodeKey(entity),
  }));
  const nodeById = new Map(simNodes.map((node) => [node.id, node]));
  const simLinks: SimLink[] = links
    .filter((link) => visible.has(link.source) && visible.has(link.target))
    .map((link) => ({ source: link.source, target: link.target }));

  // Positions are node CENTRES. React Flow bounds each node's top-left corner
  // by the same [0, size] extent, so a centre clamped to `size` would have its
  // card clamped back to `size - width`, stacking nodes on the edge. Keep the
  // centre inside the box with room for half the card on each side.
  const halfSize = (id: string): { x: number; y: number } => {
    const measured = sizes.get(id);
    return {
      x: (measured?.width ?? NODE_FALLBACK_WIDTH) / 2,
      y: (measured?.height ?? NODE_FALLBACK_HEIGHT) / 2,
    };
  };
  const clampAxis = (value: number, half: number) => {
    const maximum = Math.max(half, size - half);
    return Math.min(maximum, Math.max(half, value));
  };

  // A card is a wide, short rectangle; a circle that contains it is the safe
  // collision primitive. Falling back to the fixed radius keeps unmeasured
  // nodes from stacking.
  const collideRadius = (node: SimNode): number => {
    const measured = sizes.get(node.id);
    if (!measured) return NODE_COLLIDE_RADIUS;
    return (
      Math.max(measured.width, measured.height) / 2 + NODE_COLLIDE_PADDING
    );
  };

  const halfWidth = (id: string): number =>
    (sizes.get(id)?.width ?? NODE_FALLBACK_WIDTH) / 2;

  const endpointId = (endpoint: SimLink["source"]): string =>
    typeof endpoint === "object" ? endpoint.id : String(endpoint);

  // Two connected wide cards must be at least their half widths plus a gap
  // apart; the collide force alone loses to the link force once alpha cools,
  // which is exactly what left cards overlapping on screen.
  const linkDistance = (link: SimLink): number =>
    Math.max(
      LINK_DISTANCE,
      halfWidth(endpointId(link.source)) +
        halfWidth(endpointId(link.target)) +
        LINK_GAP,
    );

  /** Final guarantee: d3's circular collide is alpha-scaled and can leave
   *  overlaps once the layout cools, so a direct rectangle pass separates the
   *  cards (wide, short) the last few pixels. Pinned nodes stay put; the other
   *  node of the pair takes the whole push. */
  const resolveOverlaps = () => {
    // Work in the SAME coordinates `positions()` returns: clamping at read
    // time otherwise reintroduces overlaps that the pass already fixed on the
    // raw (out-of-bounds) coordinates.
    for (const node of simNodes) {
      if (node.fx != null && node.fy != null) continue;
      const half = halfSize(node.id);
      node.x = clampAxis(node.x ?? 0, half.x);
      node.y = clampAxis(node.y ?? 0, half.y);
    }
    for (let pass = 0; pass < SEPARATION_PASSES; pass += 1) {
      let moved = false;
      for (let index = 0; index < simNodes.length; index += 1) {
        const a = simNodes[index];
        const halfA = halfSize(a.id);
        for (let other = index + 1; other < simNodes.length; other += 1) {
          const b = simNodes[other];
          const halfB = halfSize(b.id);
          const dx = (b.x ?? 0) - (a.x ?? 0);
          const dy = (b.y ?? 0) - (a.y ?? 0);
          const overlapX = halfA.x + halfB.x + CARD_GAP - Math.abs(dx);
          const overlapY = halfA.y + halfB.y + CARD_GAP - Math.abs(dy);
          if (overlapX <= 0 || overlapY <= 0) continue;
          const aPinned = a.fx != null && a.fy != null;
          const bPinned = b.fx != null && b.fy != null;
          if (aPinned && bPinned) continue;
          moved = true;
          const horizontal = overlapX <= overlapY;
          const pushX = horizontal
            ? (dx >= 0 ? overlapX : -overlapX)
            : 0;
          const pushY = horizontal
            ? 0
            : (dy >= 0 ? overlapY : -overlapY);
          const move = (node: SimNode, dx: number, dy: number) => {
            const half = halfSize(node.id);
            node.x = clampAxis((node.x ?? 0) + dx, half.x);
            node.y = clampAxis((node.y ?? 0) + dy, half.y);
          };
          if (aPinned) {
            move(b, pushX, pushY);
          } else if (bPinned) {
            move(a, -pushX, -pushY);
          } else {
            move(a, -pushX / 2, -pushY / 2);
            move(b, pushX / 2, pushY / 2);
          }
        }
      }
      if (!moved) return;
    }
  };

  const linkForce = forceLink<SimNode, SimLink>(simLinks)
    .id((node) => node.id)
    .distance(linkDistance);

  const simulation = forceSimulation<SimNode>(simNodes)
    .force("link", linkForce)
    .force("charge", forceManyBody<SimNode>().strength(CHARGE_STRENGTH))
    .force("center", forceCenter<SimNode>(size / 2, size / 2))
    .force("x", forceX<SimNode>(size / 2).strength(CENTER_STRENGTH))
    .force("y", forceY<SimNode>(size / 2).strength(CENTER_STRENGTH))
    .force(
      "collide",
      forceCollide<SimNode>().radius(collideRadius).strength(0.8),
    )
    .force("edgeAvoid", edgeAvoidanceForce(simNodes, simLinks))
    .alpha(ALPHA_START)
    .alphaDecay(1 - Math.pow(ALPHA_AFTER_SETTLE / ALPHA_START, 1 / SETTLE_TICKS))
    .stop();

  let cancelFrame: (() => void) | null = null;
  // Once the simulation cools and the overlap pass has run, further ticks only
  // add float noise; freeze until something explicitly re-heats the layout.
  let frozen = false;

  const positions = (): ForcePositions => {
    const result: ForcePositions = new Map();
    for (const node of simNodes) {
      const half = halfSize(node.id);
      // A node the author dropped is theirs, even outside the layout box; the
      // box only frames the automatic layout.
      const pinned = node.fx != null && node.fy != null;
      result.set(node.id, {
        x: pinned ? (node.x ?? 0) : clampAxis(node.x ?? 0, half.x),
        y: pinned ? (node.y ?? 0) : clampAxis(node.y ?? 0, half.y),
      });
    }
    return result;
  };

  const layout: LiveForceLayout = {
    step(ticks = 1) {
      if (!frozen) {
        for (let index = 0; index < ticks; index += 1) simulation.tick();
        if (simulation.alpha() <= simulation.alphaMin()) {
          resolveOverlaps();
          frozen = true;
        }
      }
      return positions();
    },
    settle() {
      simulation.alpha(ALPHA_START);
      simulation.tick(SETTLE_TICKS);
      resolveOverlaps();
      frozen = true;
      return positions();
    },
    reheat(alpha = 0.6) {
      simulation.alpha(alpha);
      simulation.alphaTarget(0);
      frozen = false;
    },
    pin(id, x, y) {
      const node = nodeById.get(id);
      if (!node) return;
      frozen = false;
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
      frozen = false;
      node.fx = null;
      node.fy = null;
    },
    updateSizes(next) {
      frozen = false;
      sizes.clear();
      for (const [id, measured] of next) sizes.set(id, measured);
      // d3 caches each link's length when a force initializes, so new card
      // widths only reach the layout after re-initializing the link force.
      linkForce.initialize?.(simNodes, Math.random);
    },
    positions,
    isSettled() {
      return simulation.alpha() <= simulation.alphaMin();
    },
    start() {
      if (cancelFrame) return;
      const frame = () => {
        simulation.tick();
        if (layout.isSettled()) resolveOverlaps();
        layout.onPositions?.(positions());
        if (layout.isSettled()) {
          frozen = true;
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
