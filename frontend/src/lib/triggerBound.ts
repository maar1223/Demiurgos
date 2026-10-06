/**
 * Client-side mirror of the server trigger bounds (design TD-F).
 *
 * UX ONLY: the client disables approve while over the intake bound and shows
 * the bounded preview with a visible truncation marker. The server re-validates
 * every approve request (`TRIGGER_INTAKE_LIMIT` in `methodology_library.py`) and
 * remains authoritative — these constants must never be trusted as enforcement.
 */

/** Authored intake bound: the maximum number of characters the Author may
 *  approve (mirrors `skill_renderer.DESCRIPTION_INTAKE_LIMIT`). */
export const TRIGGER_INTAKE_LIMIT = 60;

/** Render bound: the maximum characters of the trigger the model may see;
 *  an over-limit trigger is truncated with a visible `…` marker. */
export const TRIGGER_RENDER_LIMIT = 57;

/** Collapse every whitespace run to a single space and trim the edges.
 *  Mirrors the server's `normalize_trigger` so an approval digest and its
 *  preview stay whitespace-insensitive. */
export function normalizeTrigger(value: string): string {
  return value.split(/\s+/).filter(Boolean).join(" ");
}

/** Bound a raw trigger to `TRIGGER_RENDER_LIMIT`, signalling whether it was
 *  cut. Mirrors the server's `norm[:56].rstrip() + "…"` so the preview the
 *  Author sees matches the value Hermes will index. */
export function boundTrigger(raw: string): {
  value: string;
  truncated: boolean;
} {
  const normalized = normalizeTrigger(raw);
  if (normalized.length <= TRIGGER_RENDER_LIMIT) {
    return { value: normalized, truncated: false };
  }
  return {
    value: normalized.slice(0, TRIGGER_RENDER_LIMIT - 1).trimEnd() + "…",
    truncated: true,
  };
}
