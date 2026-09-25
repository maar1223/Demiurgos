import {
  isOperationalTaller,
  OPERATIONAL_TALLER_LABELS,
} from "@/lib/constants";
import type { MessageKey, TFunction } from "@/i18n/messages";
import type { SkillState } from "@/lib/tallerStates";

/**
 * Canonical vocabulary axes (contract §5 — skill-vocabulary-axes spec). The
 * single source of term→axis attribution for every axis surface: axes 1+2
 * render as visible row chips; axes 3+4 render ONLY into tooltips / panel
 * blocks (spec R3). Pure data + builders — zero state; `tallerStates.ts`
 * stays untouched (contract §5:123).
 */
export type VocabularyAxis =
  | "activation" // eje 1 — activación por flujo (slot)
  | "companion" // eje 2 — metodología en chat (método, nunca voz/persona)
  | "scope" // eje 3 — alcance de taller
  | "conflict"; // eje 4 — conflicto

export const AXIS_ACTIVATION: VocabularyAxis = "activation";
export const AXIS_COMPANION: VocabularyAxis = "companion";
export const AXIS_SCOPE: VocabularyAxis = "scope";
export const AXIS_CONFLICT: VocabularyAxis = "conflict";

/** Term → axis registry — exported for tests (spec R1 scenario
 *  "Registry-sourced chips": visible chip text always equals this value). */
export const AXIS_TERMS: Record<string, VocabularyAxis> = {
  Activa: AXIS_ACTIVATION,
  Inactiva: AXIS_ACTIVATION,
  "Metodología en chat": AXIS_COMPANION, // nombre canónico del eje-2
  "Método en chat": AXIS_COMPANION, // forma corta del chip de fila
  Transversal: AXIS_SCOPE,
  Bloqueada: AXIS_CONFLICT,
};

/** Committed placeholder for the no-activation slot (spec R4/R-COPY-1):
 *  never "Inactiva", never "—". */
export const NO_ACTIVATION_PLACEHOLDER = "Sin activación en este flujo";

/**
 * Canonical (Spanish) axis term → catalogue key. The registry above and the
 * chip builders keep the canonical term as the stable contract (spec R1
 * "Registry-sourced chips"); renderers resolve the display string through
 * `t(AXIS_TERM_KEYS[chip.term])` so both locales share one source of truth.
 */
export const AXIS_TERM_KEYS: Record<string, MessageKey> = {
  Activa: "axis.term.activa",
  Inactiva: "axis.term.inactiva",
  "Metodología en chat": "axis.term.metodologiaEnChat",
  "Método en chat": "axis.term.metodoEnChat",
  Transversal: "axis.term.transversal",
  Bloqueada: "axis.term.bloqueada",
  [NO_ACTIVATION_PLACEHOLDER]: "axis.noActivation",
};

/** A visible attributed chip; `variant` mirrors the Badge atom palette. */
export interface AxisChip {
  axis: VocabularyAxis;
  term: string;
  variant: "default" | "success" | "error" | "warning" | "info";
}

export interface ActivationChipInput {
  state: SkillState;
  /** True when the world has an activation for the displayed flow. A
   *  no-activation slot renders the neutral placeholder, never "Inactiva"
   *  (spec R4). */
  hasActivation: boolean;
}

/** Axis-1 (activación por flujo) row chip. Scope states render the SAME slot
 *  chip — scope vocabulary never reaches the primary badge (R3); the group
 *  label carries the scope. */
export function activationChip({
  state,
  hasActivation,
}: ActivationChipInput): AxisChip {
  switch (state) {
    case "activa":
    case "transversal-activa":
      return { axis: AXIS_ACTIVATION, term: "Activa", variant: "success" };
    case "bloqueada":
    case "inactiva":
    case "transversal-inactiva":
      return hasActivation
        ? { axis: AXIS_ACTIVATION, term: "Inactiva", variant: "default" }
        : {
            axis: AXIS_ACTIVATION,
            term: NO_ACTIVATION_PLACEHOLDER,
            variant: "default",
          };
  }
}

/** Axis-2 (metodología en chat) row chip. Rendered term MUST equal the
 *  `AXIS_TERMS` key verbatim (spec R1 "Registry-sourced chips").
 *
 *  Rename basis (R-COPY-4): the runtime mechanism injects ONLY the
 *  ≤1000-token contract projection (the method), never the skill's voice or
 *  persona content — so the term is a methodological descriptor, not a
 *  re-romanticized companion figure. */
export function companionChip(): AxisChip {
  return { axis: AXIS_COMPANION, term: "Método en chat", variant: "info" };
}

/** Display label for a Taller key (short key → localized `OPERATIONAL_TALLER_LABELS`
 *  label, raw value fallback for unknown keys — e.g. imported free-form
 *  talleres). */
function tallerLabel(taller: string | null | undefined, t: TFunction): string {
  if (taller == null) return "";
  return isOperationalTaller(taller)
    ? t(OPERATIONAL_TALLER_LABELS[taller])
    : taller;
}

/** Axis-4 (conflicto) tooltip/panel copy — exact REQ-TRE-6 S1 copy, taller
 *  names interpolated through the catalogue. Registry-sourced (R3): conflict
 *  vocabulary renders ONLY into tooltips / panel blocks, never a primary
 *  badge. Neutral Spanish (R-COPY-3): no voseo. The `es` catalogue value is
 *  the locked canonical sentence. */
export function conflictExplanation(
  activeTaller: string,
  skillTaller: string | null | undefined,
  t: TFunction,
): string {
  return t("axis.conflict.explanation", {
    active: tallerLabel(activeTaller, t),
    primary: tallerLabel(skillTaller, t),
  });
}