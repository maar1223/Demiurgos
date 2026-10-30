import { describe, expect, it } from "vitest";
import {
  computeForcePositions,
  computeLayoutSize,
  createLiveForceLayout,
} from "@/lib/graphForce";
import type { EntityLink, GraphEntity } from "@/api/types";

/** Minimal GraphEntity: the engine only reads id/path (node key) via nodeKey. */
function entity(id: string, path = `/${id}.md`): GraphEntity {
  return { id, path, name: id } as unknown as GraphEntity;
}

function link(source: string, target: string): EntityLink {
  return { source, target } as unknown as EntityLink;
}

const WORLD = [
  entity("ana"),
  entity("bruno"),
  entity("carla"),
  entity("dario"),
  entity("elena"),
];

const LINKS = [link("ana", "bruno"), link("bruno", "carla")];

describe("computeLayoutSize", () => {
  it("grows with the square root of the node count and never shrinks below the floor", () => {
    expect(computeLayoutSize(0)).toBe(400);
    expect(computeLayoutSize(1)).toBe(400);
    expect(computeLayoutSize(100)).toBeGreaterThan(computeLayoutSize(25));
  });
});

describe("computeForcePositions (static path)", () => {
  it("is deterministic for the same input", () => {
    const size = computeLayoutSize(WORLD.length);
    const first = computeForcePositions(WORLD, LINKS, size);
    const second = computeForcePositions(WORLD, LINKS, size);

    expect([...first.keys()].sort()).toEqual([...second.keys()].sort());
    for (const [key, position] of first) {
      expect(second.get(key)).toEqual(position);
    }
  });

  it("clamps every position inside the layout bounds", () => {
    const size = computeLayoutSize(WORLD.length);
    const positions = computeForcePositions(WORLD, LINKS, size);
    for (const { x, y } of positions.values()) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(size);
      expect(y).toBeLessThanOrEqual(size);
    }
  });

  it("separates nodes instead of stacking them on one point", () => {
    const size = computeLayoutSize(WORLD.length);
    const positions = [...computeForcePositions(WORLD, LINKS, size).values()];
    const distinct = new Set(positions.map((p) => `${p.x.toFixed(1)}|${p.y.toFixed(1)}`));
    expect(distinct.size).toBe(WORLD.length);
  });
});

describe("createLiveForceLayout", () => {
  const size = computeLayoutSize(WORLD.length);

  it("starts hot and settles after the documented budget", () => {
    const layout = createLiveForceLayout({ entities: WORLD, links: LINKS, size });
    expect(layout.isSettled()).toBe(false);

    layout.step(300);
    expect(layout.isSettled()).toBe(true);
  });

  it("moves while hot and stops moving once settled", () => {
    const layout = createLiveForceLayout({ entities: WORLD, links: LINKS, size });
    const start = layout.positions();
    layout.step(20);
    const mid = layout.positions();

    const moved = [...mid].some(([key, p]) => {
      const from = start.get(key);
      return !from || Math.abs(from.x - p.x) > 0.5 || Math.abs(from.y - p.y) > 0.5;
    });
    expect(moved).toBe(true);

    layout.step(300);
    const settled = layout.positions();
    layout.step(50);
    const after = layout.positions();
    for (const [key, p] of settled) {
      expect(Math.abs((after.get(key)?.x ?? 0) - p.x)).toBeLessThan(0.01);
      expect(Math.abs((after.get(key)?.y ?? 0) - p.y)).toBeLessThan(0.01);
    }
  });

  it("re-heats back into motion on demand", () => {
    const layout = createLiveForceLayout({ entities: WORLD, links: LINKS, size });
    layout.step(300);
    expect(layout.isSettled()).toBe(true);

    layout.reheat();
    expect(layout.isSettled()).toBe(false);

    const before = layout.positions();
    layout.step(5);
    const after = layout.positions();
    const moved = [...after].some(([key, p]) => {
      const from = before.get(key);
      return !from || Math.abs(from.x - p.x) > 0.01 || Math.abs(from.y - p.y) > 0.01;
    });
    expect(moved).toBe(true);
  });

  it("pins a dragged node exactly where it was dropped and lets neighbours react", () => {
    const layout = createLiveForceLayout({ entities: WORLD, links: LINKS, size });
    layout.step(300);

    layout.pin("ana", 42, 84);
    layout.step(60);

    expect(layout.positions().get("ana")).toEqual({ x: 42, y: 84 });
    expect(layout.positions().get("dario")).not.toEqual({ x: 42, y: 84 });
  });

  it("releases a pinned node so the simulation can move it again", () => {
    const layout = createLiveForceLayout({ entities: WORLD, links: LINKS, size });
    layout.pin("ana", 42, 84);
    layout.step(60);
    expect(layout.positions().get("ana")).toEqual({ x: 42, y: 84 });

    layout.release("ana");
    layout.reheat();
    layout.step(200);
    expect(layout.positions().get("ana")).not.toEqual({ x: 42, y: 84 });
  });

  it("keeps pinned coordinates clamped inside the bounds", () => {
    const layout = createLiveForceLayout({ entities: WORLD, links: LINKS, size });
    layout.pin("ana", -500, size + 900);
    expect(layout.positions().get("ana")).toEqual({ x: 0, y: size });
  });

  it("ignores links whose endpoints are not visible", () => {
    const withDangling = [...LINKS, link("ana", "ghost")];
    const clean = createLiveForceLayout({ entities: WORLD, links: LINKS, size });
    const noisy = createLiveForceLayout({ entities: WORLD, links: withDangling, size });
    clean.step(300);
    noisy.step(300);

    for (const [key, position] of clean.positions()) {
      expect(noisy.positions().get(key)).toEqual(position);
    }
  });

  it("drives itself through the injected ticker until it settles", () => {
    const scheduled: Array<() => void> = [];
    const layout = createLiveForceLayout({
      entities: WORLD,
      links: LINKS,
      size,
      ticker: (step) => {
        scheduled.push(step);
        return () => undefined;
      },
    });

    const emissions: number[] = [];
    layout.onPositions = (positions) => emissions.push(positions.size);
    layout.start();
    expect(scheduled.length).toBe(1);

    // Each scheduled step runs one tick and schedules the next one until the
    // layout cools down.
    for (let i = 0; i < 400 && scheduled.length > 0; i += 1) {
      const step = scheduled.shift();
      step?.();
    }

    expect(emissions.length).toBeGreaterThan(1);
    expect(emissions.every((count) => count === WORLD.length)).toBe(true);
    expect(layout.isSettled()).toBe(true);
    // A settled layout stops asking for frames: nothing is left scheduled.
    expect(scheduled.length).toBe(0);
  });

  it("cancels a running animation on stop()", () => {
    let cancelled = false;
    const pending: Array<() => void> = [];
    const layout = createLiveForceLayout({
      entities: WORLD,
      links: LINKS,
      size,
      ticker: (step) => {
        pending.push(step);
        return () => {
          cancelled = true;
        };
      },
    });

    layout.start();
    for (let i = 0; i < 5; i += 1) pending.shift()?.();
    expect(layout.isSettled()).toBe(false);

    layout.stop();
    expect(cancelled).toBe(true);
  });

  it("settles synchronously without a ticker, for reduced motion", () => {
    const layout = createLiveForceLayout({ entities: WORLD, links: LINKS, size });
    const positions = layout.settle();

    expect(layout.isSettled()).toBe(true);
    expect(positions.size).toBe(WORLD.length);
    for (const { x, y } of positions.values()) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(size);
      expect(y).toBeLessThanOrEqual(size);
    }
  });
});
