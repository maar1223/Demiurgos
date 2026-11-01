import { describe, expect, it } from "vitest";
import { estimateLabelWidth, spreadLabels } from "@/lib/graphLabels";

const label = (x: number, y: number, text: string) => ({
  x,
  y,
  width: estimateLabelWidth(text),
  height: 14,
});

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

describe("spreadLabels", () => {
  it("separates two labels that share a height", () => {
    const out = spreadLabels([label(300, 100, "ALFA GRUPO"), label(340, 100, "BETA GRUPO")], []);
    const [a, b] = out;
    const aRight = a.x + a.width / 2;
    const bLeft = b.x - b.width / 2;
    expect(bLeft).toBeGreaterThanOrEqual(aRight);
    expect(a.y).toBe(100);
    expect(b.y).toBe(100);
  });

  it("spreads three neighbours without stacking them", () => {
    const out = spreadLabels(
      [
        label(300, 100, "UNO GRUPO"),
        label(320, 100, "DOS GRUPO"),
        label(340, 100, "TRES GRUPO"),
      ],
      [],
    );
    for (let i = 0; i < out.length; i += 1) {
      for (let j = i + 1; j < out.length; j += 1) {
        const left = Math.min(out[i].x + out[i].width / 2, out[j].x + out[j].width / 2);
        const right = Math.max(out[i].x - out[i].width / 2, out[j].x - out[j].width / 2);
        expect(right).toBeGreaterThanOrEqual(left);
      }
    }
  });

  it("lifts a label that a card covers", () => {
    const out = spreadLabels([label(100, 100, "SECCION")], [
      { left: 0, top: 80, right: 200, bottom: 110 },
    ]);
    expect(out[0].y).toBeLessThan(100);
  });

  it("leaves a free label exactly where it was", () => {
    const out = spreadLabels([label(100, 100, "SECCION")], []);
    expect(out[0]).toEqual(label(100, 100, "SECCION"));
  });
});
