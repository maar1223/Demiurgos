import { describe, expect, it } from "vitest";
import { tEs } from "@/__tests__/i18nTestUtils";
import {
  AXIS_COMPANION,
  AXIS_SCOPE,
  AXIS_TERMS,
  chatChip,
  scopeChip,
} from "@/lib/vocabularyAxes";

describe("vocabularyAxes registry (axis-binding-ui R1 — Term table pinned)", () => {
  it("maps every canonical term to exactly one axis", () => {
    expect(AXIS_TERMS["En el chat"]).toBe(AXIS_COMPANION);
    expect(AXIS_TERMS["Transversal"]).toBe(AXIS_SCOPE);
  });

  it("does not register any activation on/off vocabulary (S2)", () => {
    expect(AXIS_TERMS["Activa"]).toBeUndefined();
    expect(AXIS_TERMS["Inactiva"]).toBeUndefined();
    expect(AXIS_TERMS["Método en chat"]).toBeUndefined();
  });
});

describe("chatChip — chat-availability row chip (S1)", () => {
  it("attributes En el chat to the companion axis", () => {
    expect(chatChip()).toEqual({
      axis: AXIS_COMPANION,
      term: "En el chat",
      variant: "success",
    });
    expect(tEs("axis.term.enChat")).toBe("En el chat");
  });
});

describe("scopeChip — transversal row chip", () => {
  it("attributes Transversal to the scope axis", () => {
    expect(scopeChip()).toEqual({
      axis: AXIS_SCOPE,
      term: "Transversal",
      variant: "default",
    });
    expect(tEs("axis.term.transversal")).toBe("Transversal");
  });
});
