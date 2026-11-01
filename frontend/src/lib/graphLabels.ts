/**
 * Section-label placement for the graph canvas.
 *
 * Labels are drawn in screen space (constant pixel size), so their position is
 * a packing problem: keep each one over its group, out of the node cards, out
 * of the other labels, and inside the canvas.
 *
 * Why this is a single greedy pass with hard checks instead of a relaxation:
 * the previous implementation pushed overlapping pairs apart and then lifted
 * labels that a card covered. Two independent failures came out of that shape:
 *
 * 1. The lift ran AFTER the separation, so a lifted label could land exactly on
 *    top of the labels in the band above and nothing re-checked them.
 * 2. Pairwise pushes are not guaranteed to converge: with the eight long
 *    section names a real world has, twelve passes still left labels stacked on
 *    each other (and pushed others outside the canvas).
 *
 * Placing each label once, against every box already accepted, makes the
 * guarantee structural: two labels can never share a pixel, at any zoom. A
 * label only ever moves in ROWS, so its x stays on its own group; a row step is
 * the label height plus the gap, so neighbouring rows never touch either.
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

/** A label after placement. `visible` is false when no free spot was found:
 *  the caller hides it rather than paint unreadable text over another one. */
export interface PlacedLabel extends LabelBox {
  visible: boolean;
}

export interface LabelBounds {
  width: number;
  height: number;
}

export interface PlaceLabelsOptions {
  /** Air kept between two labels, and between a label and the canvas edge. */
  gap?: number;
  /** Canvas size in the same screen space as the boxes. Omitted or 0×0 (an
   *  unmeasured container, jsdom) means "no bounds to respect". */
  bounds?: LabelBounds;
  /** Rows tried above and below the anchor before giving up on a label. */
  maxRows?: number;
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
 * Place every label once, or hide it.
 *
 * Order: walk down the canvas (anchor y, then x), so a label always negotiates
 * with the ones above it. For each one try the row holding its anchor first,
 * then rows just above and below, alternating, so a label moves as little as it
 * can. A row that leaves the canvas or touches an accepted label is skipped;
 * covering a card only adds cost (a very wide section name in a dense band
 * would otherwise disappear). Every accepted box is checked against all the
 * previous ones, so no two labels can intersect — the guarantee is total.
 */
export function placeLabels(
  labels: LabelBox[],
  cards: Rect[],
  { gap = 6, bounds, maxRows = 12 }: PlaceLabelsOptions = {},
): PlacedLabel[] {
  const canvas =
    bounds && bounds.width > 0 && bounds.height > 0 ? bounds : null;
  const result: PlacedLabel[] = labels.map((label) => ({
    ...label,
    visible: false,
  }));

  const order = labels
    .map((_, index) => index)
    .sort(
      (a, b) =>
        labels[a].y - labels[b].y || labels[a].x - labels[b].x || a - b,
    );

  const placed: LabelBox[] = [];

  for (const index of order) {
    const anchor = labels[index];
    // The label stays on its group's x. Close to a canvas edge it shifts just
    // enough to stay fully readable instead of being clipped in half.
    const x = canvas
      ? Math.min(
          canvas.width - gap - anchor.width / 2,
          Math.max(gap + anchor.width / 2, anchor.x),
        )
      : anchor.x;
    // Candidate rows: the anchor's own row plus up to `maxRows` above and
    // below. A row step is the label height plus the gap, so neighbouring rows
    // never touch either.
    const rows: number[] = [0];
    for (let offset = 1; offset <= maxRows; offset += 1) {
      rows.push(-offset, offset);
    }
    // Cost of a row: distance from the anchor dominates, a card under the text
    // costs a couple of rows, so the label dodges a card when a clean row is
    // close and tolerates it when dodging would drag the title away from its
    // group (a wide name in a dense band is all cards).
    const CARD_COST = 45;
    let best: LabelBox | null = null;
    let bestCost = Number.POSITIVE_INFINITY;

    for (const row of rows) {
      const y = anchor.y + row * (anchor.height + gap);
      // Bounds are `gap` inside the layer on every side, so a title is never
      // half-clipped by the canvas edge (which reads as a broken label).
      if (
        canvas &&
        (y - anchor.height < gap ||
          y > canvas.height - gap ||
          anchor.width + gap * 2 > canvas.width)
      ) {
        continue;
      }
      const box: LabelBox = { x, y, width: anchor.width, height: anchor.height };
      const rect = toRect(box);
      // Label-on-label is never allowed: this is the bug this pass exists for.
      if (placed.some((other) => intersects(rect, toRect(other)))) continue;
      const cost =
        Math.abs(row) * (anchor.height + gap) +
        (cards.some((card) => intersects(rect, card)) ? CARD_COST : 0);
      if (cost < bestCost) {
        best = box;
        bestCost = cost;
      }
    }

    if (best) {
      placed.push(best);
      result[index] = { ...best, visible: true };
    }
  }

  return result;
}
