/**
 * Section-label placement for the graph canvas.
 *
 * Labels are drawn in screen space (constant pixel size), so their position is
 * a plain 2D packing problem: keep each one over its group, out of the node
 * cards, and out of the other labels. Measuring the DOM was unreliable (a
 * label can be read before it has layout, and jsdom always reports 0), so the
 * width comes from the text itself.
 */

export interface LabelBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** Width of one uppercase section label at 12px with wide tracking.
 *  Deliberately a slight over-estimate: extra air is harmless, a short
 *  estimate lets two titles touch. */
const CHAR_WIDTH = 9.4;
const MIN_LABEL_WIDTH = 48;

export function estimateLabelWidth(text: string): number {
  return Math.max(MIN_LABEL_WIDTH, Math.ceil(text.length * CHAR_WIDTH));
}

function toRect(box: LabelBox): Rect {
  return {
    left: box.x - box.width / 2,
    top: box.y - box.height,
    right: box.x + box.width / 2,
    bottom: box.y,
  };
}

function intersects(a: Rect, b: Rect): boolean {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

/**
 * Spread overlapping labels sideways, then lift the ones a card still covers.
 *
 * Sideways first on purpose: two sections whose groups sit side by side share
 * a height, and pushing them up produced a tight stack of titles. Horizontal
 * separation keeps each label over its own group.
 */
export function spreadLabels(
  labels: LabelBox[],
  cards: Rect[],
  { gap = 6, passes = 12 }: { gap?: number; passes?: number } = {},
): LabelBox[] {
  const placed = labels.map((label) => ({ ...label }));

  for (let pass = 0; pass < passes; pass += 1) {
    let moved = false;
    for (let i = 0; i < placed.length; i += 1) {
      for (let j = i + 1; j < placed.length; j += 1) {
        const a = toRect(placed[i]);
        const b = toRect(placed[j]);
        if (!intersects(a, b)) continue;
        const overlap =
          Math.min(a.right, b.right) - Math.max(a.left, b.left);
        if (overlap <= 0) continue;
        const push = overlap / 2 + gap;
        const left = placed[i].x <= placed[j].x ? i : j;
        const right = left === i ? j : i;
        placed[left].x -= push;
        placed[right].x += push;
        moved = true;
      }
    }
    if (!moved) break;
  }

  for (const label of placed) {
    for (let attempt = 0; attempt < 6; attempt += 1) {
      const rect = toRect(label);
      if (!cards.some((card) => intersects(rect, card))) break;
      label.y -= label.height + gap;
    }
  }

  return placed;
}
