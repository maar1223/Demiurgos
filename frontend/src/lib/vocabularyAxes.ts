import {
  OPERATIONAL_TALLER_LABELS,
  type OperationalTaller,
} from "@/lib/constants";
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
  | "companion" // eje 2 — compañero en chat
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
  Compañera: AXIS_COMPANION,
  Transversal: AXIS_SCOPE,
  Bloqueada: AXIS_CONFLICT,
};

/** Neutral placeholder for the no-activation slot (spec R4). Deliberately NOT
 *  final copy — the ⑥ wording pass owns the committed term. */
export const NO_ACTIVATION_PLACEHOLDER = "—";

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

/** Axis-2 (compañero en chat) row chip. "Compañera" is byte-frozen until the
 *  ⑥ rename pass (spec R7) — never renamed here. */
export function companionChip(): AxisChip {
  return { axis: AXIS_COMPANION, term: "Compañera", variant: "info" };
}

/** Display label for a Taller key (short key → OPERATIONAL_TALLER_LABELS
 *  label, raw value fallback for unknown keys — e.g. imported free-form
 *  talleres). */
function tallerLabel(taller: string | null | undefined): string {
  if (taller == null) return "";
  return OPERATIONAL_TALLER_LABELS[taller as OperationalTaller] ?? taller;
}

/** Axis-4 (conflicto) tooltip/panel copy — exact REQ-TRE-6 S1 copy, taller
 *  names interpolated via OPERATIONAL_TALLER_LABELS. Registry-sourced (R3):
 *  conflict vocabulary renders ONLY into tooltips / panel blocks, never a
 *  primary badge. */
export function conflictExplanation(
  activeTaller: string,
  skillTaller: string | null | undefined,
): string {
  return `Esta skill es transversal de ${tallerLabel(activeTaller)} pero su taller primario (${tallerLabel(skillTaller)}) ya tiene una skill activa en este mundo. Adaptá la skill para resolver el conflicto o activala en otro mundo.`;
}