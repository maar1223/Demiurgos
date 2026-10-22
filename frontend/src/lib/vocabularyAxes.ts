import type { MessageKey } from "@/i18n/messages";

/**
 * Canonical vocabulary axes (contract §5 — skill-vocabulary-axes spec). The
 * single source of term→axis attribution for every axis surface: both axes
 * render as visible row chips, each attributed to its own axis. Pure data +
 * builders — zero state.
 *
 * The activation axis was retired with the per-session guided method (S2):
 * the visible state of a skill in the library is chat availability, never an
 * "on/off" that secretly pins the guided method.
 */
export type VocabularyAxis =
  | "companion" // eje — skills disponibles en el chat
  | "scope"; // eje — alcance de taller

export const AXIS_COMPANION: VocabularyAxis = "companion";
export const AXIS_SCOPE: VocabularyAxis = "scope";

/** Term → axis registry — exported for tests (spec R1 scenario
 *  "Registry-sourced chips": visible chip text always equals this value). */
export const AXIS_TERMS: Record<string, VocabularyAxis> = {
  "En el chat": AXIS_COMPANION,
  Transversal: AXIS_SCOPE,
};

/**
 * Canonical (Spanish) axis term → catalogue key. The registry above and the
 * chip builders keep the canonical term as the stable contract (spec R1
 * "Registry-sourced chips"); renderers resolve the display string through
 * `t(AXIS_TERM_KEYS[chip.term])` so both locales share one source of truth.
 */
export const AXIS_TERM_KEYS: Record<string, MessageKey> = {
  "En el chat": "axis.term.enChat",
  Transversal: "axis.term.transversal",
};

/** A visible attributed chip; `variant` mirrors the Badge atom palette. */
export interface AxisChip {
  axis: VocabularyAxis;
  term: string;
  variant: "default" | "success" | "error" | "warning" | "info";
}

/** Chat-availability row chip (S1): the skill is added to the world's chat. */
export function chatChip(): AxisChip {
  return { axis: AXIS_COMPANION, term: "En el chat", variant: "success" };
}

/** Scope row chip: the skill belongs to another Taller but is compatible
 *  with the active one. */
export function scopeChip(): AxisChip {
  return { axis: AXIS_SCOPE, term: "Transversal", variant: "default" };
}
