import { describe, expect, it } from "vitest";
import {
  estimateLabelWidth,
  placeLabels,
  type LabelBox,
} from "@/lib/graphLabels";

const label = (x: number, y: number, text: string): LabelBox => ({
  x,
  y,
  width: estimateLabelWidth(text),
  height: 16,
});

const overlaps = (a: LabelBox, b: LabelBox): boolean =>
  a.x - a.width / 2 < b.x + b.width / 2 &&
  a.x + a.width / 2 > b.x - b.width / 2 &&
  a.y - a.height < b.y &&
  a.y > b.y - b.height;

/** Every accepted label must be a disjoint rectangle. */
function expectNoOverlaps(boxes: LabelBox[]) {
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      expect(
        overlaps(boxes[i], boxes[j]),
        `${boxes[i].x},${boxes[i].y} overlaps ${boxes[j].x},${boxes[j].y}`,
      ).toBe(false);
    }
  }
}

describe("estimateLabelWidth", () => {
  it("grows with the text and never goes below a floor", () => {
    expect(estimateLabelWidth("")).toBe(48);
    // Short labels sit on the floor so they stay tappable/legible.
    expect(estimateLabelWidth("DVIN")).toBe(48);
    expect(estimateLabelWidth("A MUCH LONGER SECTION NAME")).toBeGreaterThan(
      estimateLabelWidth("DVIN"),
    );
  });
});

describe("placeLabels", () => {
  it("leaves a free label exactly where it was", () => {
    const anchored = label(100, 100, "SECCION");
    const [out] = placeLabels([anchored], []);
    expect(out).toEqual({ ...anchored, visible: true });
  });

  it("keeps a label's x: it moves only in rows, over its own group", () => {
    const out = placeLabels(
      [label(300, 100, "ALFA GRUPO"), label(320, 100, "BETA GRUPO")],
      [],
    );
    expect(out[0].x).toBe(300);
    expect(out[1].x).toBe(320);
    expectNoOverlaps(out);
  });

  it("never lets a crowded band share pixels (realistic long sections)", () => {
    // Eight long section names is what a real world shows at once; the old
    // pairwise relaxation still left pairs painted on top of each other.
    const names = [
      "POLITICA-DISTRIBUCION-Y-TERRITORIOS",
      "SISTEMA-STAL-PODERES-VIBRANTES",
      "ENEAGRAMA-STAL-VIBRANTES-CANON",
      "AYAGARS-REPTILES-VIBRANTES",
      "CULTURA-COSTUMBRES-POPULARES",
      "PLANETA-VIBRAL-NATURALEZA-Y-BIODIVERSIDAD",
      "AYAGARS-REPTILES-VIBRANTES-DVIN",
      "AYAGARS-REPTILES-VIBRANTES-DVEX",
    ];
    const labels = names.map((name, index) => label(500 + index * 40, 240, name));
    const out = placeLabels(labels, [], { bounds: { width: 970, height: 690 } });

    expect(out.every((box) => box.visible)).toBe(true);
    expectNoOverlaps(out);
    // Every label stays over its own group: only y may change.
    out.forEach((box, index) => expect(box.x).toBe(labels[index].x));
  });

  it("does not lift a label onto the band above when a card covers it", () => {
    // The old order separated labels, then lifted, then never re-checked: the
    // lifted label landed exactly on the one above (the visible bug).
    const labels = [label(300, 240, "SECCION DE ARRIBA"), label(300, 262, "SECCION DE ABAJO")];
    const card = { left: 100, top: 250, right: 500, bottom: 300 };
    const out = placeLabels(labels, [card]);

    expect(out.every((box) => box.visible)).toBe(true);
    expectNoOverlaps(out);
    // The covered label moves away from the card...
    for (const box of out) {
      const rect = {
        left: box.x - box.width / 2,
        top: box.y - box.height,
        right: box.x + box.width / 2,
        bottom: box.y,
      };
      expect(
        rect.left < card.right &&
          rect.right > card.left &&
          rect.top < card.bottom &&
          rect.bottom > card.top,
      ).toBe(false);
    }
  });

  it("keeps every title inside the canvas instead of clipping it", () => {
    const labels = [
      label(20, 300, "SECCION PEGADA AL BORDE"),
      label(950, 300, "OTRA SECCION PEGADA AL BORDE"),
      label(485, 300, "SECCION CENTRAL"),
    ];
    const bounds = { width: 970, height: 690 };
    const out = placeLabels(labels, [], { bounds });

    expectNoOverlaps(out);
    for (const box of out) {
      expect(box.x - box.width / 2).toBeGreaterThanOrEqual(6);
      expect(box.x + box.width / 2).toBeLessThanOrEqual(bounds.width - 6);
      expect(box.y - box.height).toBeGreaterThanOrEqual(6);
      expect(box.y).toBeLessThanOrEqual(bounds.height - 6);
    }
  });

  it("hides a label only when the canvas cannot hold it", () => {
    const out = placeLabels([label(100, 30, "SECCION")], [], {
      bounds: { width: 300, height: 24 },
    });
    expect(out[0].visible).toBe(false);
  });

  it("is deterministic for the same input", () => {
    const labels = [
      label(400, 240, "UNO SECCION"),
      label(400, 240, "DOS SECCION"),
      label(400, 240, "TRES SECCION"),
    ];
    expect(placeLabels(labels, [])).toEqual(placeLabels(labels, []));
  });
});
