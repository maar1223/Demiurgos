import { describe, expect, it } from "vitest";
import {
  AXIS_ACTIVATION,
  AXIS_COMPANION,
  AXIS_CONFLICT,
  AXIS_SCOPE,
  AXIS_TERMS,
  NO_ACTIVATION_PLACEHOLDER,
  activationChip,
  companionChip,
  conflictExplanation,
} from "@/lib/vocabularyAxes";

describe("vocabularyAxes registry (axis-binding-ui R1)", () => {
  it("maps every canonical term to exactly one axis", () => {
    expect(AXIS_TERMS["Activa"]).toBe(AXIS_ACTIVATION);
    expect(AXIS_TERMS["Inactiva"]).toBe(AXIS_ACTIVATION);
    expect(AXIS_TERMS["Compañera"]).toBe(AXIS_COMPANION);
    expect(AXIS_TERMS["Transversal"]).toBe(AXIS_SCOPE);
    expect(AXIS_TERMS["Bloqueada"]).toBe(AXIS_CONFLICT);
  });

  it("exports a neutral no-activation placeholder that is not final copy", () => {
    expect(NO_ACTIVATION_PLACEHOLDER).toBeTruthy();
    expect(NO_ACTIVATION_PLACEHOLDER).not.toBe("Inactiva");
  });
});

describe("activationChip — axis-1 (activación por flujo) row chip", () => {
  it("attributes the active slot term to the activation axis with the success variant", () => {
    expect(activationChip({ state: "activa", hasActivation: true })).toEqual({
      axis: AXIS_ACTIVATION,
      term: "Activa",
      variant: "success",
    });
    // Transversal-active rows keep the SAME slot chip: scope vocabulary never
    // reaches the primary badge (R3).
    expect(
      activationChip({ state: "transversal-activa", hasActivation: true }),
    ).toEqual({ axis: AXIS_ACTIVATION, term: "Activa", variant: "success" });
  });

  it("attributes inactive rows to the activation axis when the slot is filled", () => {
    expect(
      activationChip({ state: "inactiva", hasActivation: true }),
    ).toEqual({ axis: AXIS_ACTIVATION, term: "Inactiva", variant: "default" });
    expect(
      activationChip({ state: "transversal-inactiva", hasActivation: true }),
    ).toEqual({ axis: AXIS_ACTIVATION, term: "Inactiva", variant: "default" });
  });

  it("renders the neutral placeholder when the world lacks an activation (R4)", () => {
    expect(
      activationChip({ state: "inactiva", hasActivation: false }),
    ).toEqual({
      axis: AXIS_ACTIVATION,
      term: NO_ACTIVATION_PLACEHOLDER,
      variant: "default",
    });
    expect(
      activationChip({ state: "transversal-inactiva", hasActivation: false }),
    ).toEqual({
      axis: AXIS_ACTIVATION,
      term: NO_ACTIVATION_PLACEHOLDER,
      variant: "default",
    });
  });

  it("attributes blocked rows to the activation axis — never Bloqueada (R3)", () => {
    expect(
      activationChip({ state: "bloqueada", hasActivation: true }),
    ).toEqual({ axis: AXIS_ACTIVATION, term: "Inactiva", variant: "default" });
  });
});

describe("companionChip — axis-2 (compañero en chat) row chip", () => {
  it("attributes the frozen Compañera term to the companion axis (R7)", () => {
    expect(companionChip()).toEqual({
      axis: AXIS_COMPANION,
      term: "Compañera",
      variant: "info",
    });
  });
});

describe("conflictExplanation — axis-4 (conflicto) tooltip/panel copy (REQ-TRE-6 S1)", () => {
  it("interpolates taller labels into the verbatim conflict copy", () => {
    expect(conflictExplanation("Mundo", "Ideas")).toBe(
      "Esta skill es transversal de Taller de Mundo pero su taller primario (Taller de Ideas) ya tiene una skill activa en este mundo. Adaptá la skill para resolver el conflicto o activala en otro mundo.",
    );
  });

  it("falls back to the raw taller value for unknown taller keys", () => {
    expect(conflictExplanation("Mundo", "Taller Custom")).toBe(
      "Esta skill es transversal de Taller de Mundo pero su taller primario (Taller Custom) ya tiene una skill activa en este mundo. Adaptá la skill para resolver el conflicto o activala en otro mundo.",
    );
  });
});