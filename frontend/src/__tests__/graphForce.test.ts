import { describe, expect, it } from "vitest";
import {
  computeForcePositions,
  computeLayoutSize,
  createLiveForceLayout,
  ringPositions,
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

    layout.pin("ana", 120, 120);
    layout.step(60);

    expect(layout.positions().get("ana")).toEqual({ x: 120, y: 120 });
    expect(layout.positions().get("dario")).not.toEqual({ x: 120, y: 120 });
  });

  it("releases a pinned node so the simulation can move it again", () => {
    const layout = createLiveForceLayout({ entities: WORLD, links: LINKS, size });
    layout.pin("ana", 120, 120);
    layout.step(60);
    expect(layout.positions().get("ana")).toEqual({ x: 120, y: 120 });

    layout.release("ana");
    layout.reheat();
    layout.step(200);
    expect(layout.positions().get("ana")).not.toEqual({ x: 120, y: 120 });
  });

  it("sizes collision from the measured cards so wide nodes stop overlapping", () => {
    const wide = 2000;
    const distance = (layout: ReturnType<typeof createLiveForceLayout>) => {
      const a = layout.positions().get("ana")!;
      const b = layout.positions().get("bruno")!;
      return Math.hypot(a.x - b.x, a.y - b.y);
    };
    const layout = createLiveForceLayout({
      entities: WORLD,
      links: LINKS,
      size: wide,
    });
    layout.step(300);
    const withoutSizes = distance(layout);

    layout.updateSizes(
      new Map([
        ["ana", { width: 400, height: 40 }],
        ["bruno", { width: 400, height: 40 }],
      ]),
    );
    layout.reheat();
    layout.step(300);
    // Two 400px cards need 2 × (200 + 10) between their centres, more than
    // the 240px link distance, so the measured size must win.
    expect(distance(layout)).toBeGreaterThan(withoutSizes + 50);
  });

  it("keeps the automatic layout inside the box, half a card from each edge", () => {
    const sizes = new Map(
      WORLD.map((node) => [node.id, { width: 300, height: 40 }] as const),
    );
    const layout = createLiveForceLayout({
      entities: WORLD,
      links: LINKS,
      size: 600,
      sizes,
    });
    layout.step(300);
    for (const { x, y } of layout.positions().values()) {
      expect(x).toBeGreaterThanOrEqual(150);
      expect(x).toBeLessThanOrEqual(450);
      expect(y).toBeGreaterThanOrEqual(20);
      expect(y).toBeLessThanOrEqual(580);
    }
  });

  it("keeps a dropped node exactly where it was dropped, even outside the box", () => {
    const layout = createLiveForceLayout({
      entities: WORLD,
      links: LINKS,
      size: 1000,
      sizes: new Map([["ana", { width: 300, height: 40 }]]),
    });
    layout.pin("ana", -500, 1900);
    // The author owns dragged nodes: the layout box only frames the automatic
    // arrangement, it is not a cage.
    expect(layout.positions().get("ana")).toEqual({ x: -500, y: 1900 });
  });

  it("keeps each folder group around its own main node", () => {
    const world = [
      entity("a-main", "grupo-a/main.md"),
      entity("a-one", "grupo-a/one.md"),
      entity("a-two", "grupo-a/two.md"),
      entity("b-main", "grupo-b/main.md"),
      entity("b-one", "grupo-b/one.md"),
      entity("b-two", "grupo-b/two.md"),
    ].map((node) => ({ ...node, name: node.id }) as unknown as GraphEntity);
    const worldLinks = [
      link("a-main", "a-one"),
      link("a-main", "a-two"),
      link("a-one", "a-two"),
      link("b-main", "b-one"),
      link("b-main", "b-two"),
      link("b-one", "b-two"),
      link("a-main", "b-main"),
    ];
    const layout = createLiveForceLayout({
      entities: world,
      links: worldLinks,
      size: 2200,
    });
    layout.step(300);
    const positions = layout.positions();
    const distance = (from: string, to: string) => {
      const a = positions.get(from)!;
      const b = positions.get(to)!;
      return Math.hypot(a.x - b.x, a.y - b.y);
    };
    for (const member of ["a-one", "a-two"]) {
      expect(distance(member, "a-main")).toBeLessThan(
        distance(member, "b-main"),
      );
    }
    for (const member of ["b-one", "b-two"]) {
      expect(distance(member, "b-main")).toBeLessThan(
        distance(member, "a-main"),
      );
    }
  });

  it("puts the most connected node at the centre of its folder group", () => {
    const group = ["alpha", "beta", "gamma", "delta", "epsilon"].map((id) =>
      entity(id, `grupo/${id}.md`),
    );
    const groupLinks = [
      link("alpha", "beta"),
      link("alpha", "gamma"),
      link("alpha", "delta"),
      link("alpha", "epsilon"),
      link("beta", "gamma"),
    ];
    const layout = createLiveForceLayout({
      entities: group,
      links: groupLinks,
      size: 1600,
    });
    layout.step(300);
    const positions = layout.positions();
    const centroid = [...positions.values()].reduce(
      (sum, position) => ({
        x: sum.x + position.x / positions.size,
        y: sum.y + position.y / positions.size,
      }),
      { x: 0, y: 0 },
    );
    const distance = (id: string) => {
      const position = positions.get(id)!;
      return Math.hypot(position.x - centroid.x, position.y - centroid.y);
    };

    // alpha has four connections, so it is the group's main theme: it must
    // read as the centre, not as one more scattered node.
    for (const child of ["beta", "gamma", "delta", "epsilon"]) {
      expect(distance("alpha")).toBeLessThan(distance(child));
    }
    // The view needs the same choice to label only the group's main (S11).
    expect([...layout.mainIds()]).toEqual(["alpha"]);
  });

  it("reports exactly one hierarchy main per folder", () => {
    const world = [
      entity("a-main", "grupo-a/main.md"),
      entity("a-one", "grupo-a/one.md"),
      entity("a-two", "grupo-a/two.md"),
      entity("a-three", "grupo-a/three.md"),
      entity("b-main", "grupo-b/main.md"),
      entity("b-one", "grupo-b/one.md"),
      entity("b-two", "grupo-b/two.md"),
      entity("b-three", "grupo-b/three.md"),
    ];
    // Each main has three links and every other member exactly one, so the
    // choice is unambiguous (degree, then in-degree).
    const worldLinks = [
      link("a-main", "a-one"),
      link("a-main", "a-two"),
      link("a-main", "a-three"),
      link("b-main", "b-one"),
      link("b-main", "b-two"),
      link("b-main", "b-three"),
    ];
    const layout = createLiveForceLayout({
      entities: world,
      links: worldLinks,
      size: 1600,
    });
    expect([...layout.mainIds()].sort()).toEqual(["a-main", "b-main"]);
  });

  it("separates a dense world of wide cards without stacking any pair", () => {
    const many = Array.from({ length: 60 }, (_, index) => entity(`n${index}`));
    const manyLinks = [
      ...many.slice(0, -1).map((node, index) => link(node.id, many[index + 1].id)),
      ...many.slice(0, 20).map((node) => link(node.id, "n59")),
    ];
    const cards = new Map(
      many.map((node) => [node.id, { width: 200, height: 40 }] as const),
    );
    const layout = createLiveForceLayout({
      entities: many,
      links: manyLinks,
      size: computeLayoutSize(many.length),
      sizes: cards,
    });
    layout.step(300);
    const positions = [...layout.positions()];
    let overlaps = 0;
    for (let index = 0; index < positions.length; index += 1) {
      for (let other = index + 1; other < positions.length; other += 1) {
        const [, a] = positions[index];
        const [, b] = positions[other];
        const separated =
          Math.abs(a.x - b.x) >= 199.5 || Math.abs(a.y - b.y) >= 39.5;
        if (!separated) overlaps += 1;
      }
    }
    expect(overlaps).toBe(0);
  });

  it("leaves no overlapping cards once the layout settles", () => {
    const cards = new Map(
      WORLD.map((node) => [node.id, { width: 200, height: 40 }] as const),
    );
    const layout = createLiveForceLayout({
      entities: WORLD,
      links: LINKS,
      size: 600,
      sizes: cards,
    });
    layout.step(300);
    const positions = [...layout.positions()];
    for (let index = 0; index < positions.length; index += 1) {
      for (let other = index + 1; other < positions.length; other += 1) {
        const [, a] = positions[index];
        const [, b] = positions[other];
        const separated =
          Math.abs(a.x - b.x) >= 200 - 0.5 ||
          Math.abs(a.y - b.y) >= 40 - 0.5;
        expect(separated).toBe(true);
      }
    }
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

describe("ringPositions", () => {
  it("places every key at the same radius, starting at the top", () => {
    const ring = ringPositions({ x: 0, y: 0 }, ["a", "b", "c", "d"], 100);
    expect([...ring.keys()]).toEqual(["a", "b", "c", "d"]);
    for (const point of ring.values()) {
      expect(Math.hypot(point.x, point.y)).toBeCloseTo(100, 6);
    }
    const top = ring.get("a")!;
    expect(top.x).toBeCloseTo(0, 6);
    expect(top.y).toBeCloseTo(-100, 6);
  });

  it("is deterministic regardless of input order", () => {
    const left = ringPositions({ x: 5, y: 5 }, ["b", "a"], 50);
    const right = ringPositions({ x: 5, y: 5 }, ["a", "b"], 50);
    expect([...left.entries()]).toEqual([...right.entries()]);
  });

  it("returns an empty map when there is nothing to place", () => {
    expect(ringPositions({ x: 0, y: 0 }, [], 100).size).toBe(0);
  });
});
