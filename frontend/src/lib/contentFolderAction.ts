/**
 * Which action the content folder offers, in one place (step 5).
 *
 * The rule depends on the STATE, never on the screen:
 *
 * | target              | current content | action |
 * |---------------------|-----------------|--------|
 * | empty               | no worlds       | use    |
 * | already holds data  | has content     | use    |
 * | empty               | has content     | move   |
 * | holds content       | no content      | use    |
 *
 * "use" means point the app at that folder; "move" means copy the content into
 * it. Duplicating over existing content is never a move — that would be a merge,
 * and this product does not do merges with the author's data.
 */

export type ContentAction = "use" | "move";

export function contentActionFor({
  worlds,
  targetHasContent,
}: {
  worlds: number;
  targetHasContent: boolean;
}): ContentAction {
  if (targetHasContent) return "use";
  return worlds > 0 ? "move" : "use";
}
