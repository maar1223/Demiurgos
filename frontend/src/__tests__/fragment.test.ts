import { describe, expect, it } from "vitest";
import { locateFragment } from "@/lib/fragment";

const BODY = "Cuando el mundo no tenía nombre,\ninvoco el poder de Stal, su Áyagar Celestial.\nUno ... tres.";

describe("locateFragment", () => {
  it("finds an exact quote", () => {
    const range = locateFragment(BODY, "invoco el poder de Stal");

    expect(BODY.slice(range!.start, range!.end)).toBe(
      "invoco el poder de Stal",
    );
  });

  it("ignores accents and case", () => {
    const range = locateFragment(BODY, "su Ayagar celestial");

    expect(BODY.slice(range!.start, range!.end)).toBe(
      "su Áyagar Celestial",
    );
  });

  it("ignores punctuation differences", () => {
    const text = "Stal, cristales mágicos";
    const range = locateFragment(text, "Stal cristales");

    expect(text.slice(range!.start, range!.end)).toBe("Stal, cristales");
  });

  it("uses the first fragment of an elided quote", () => {
    const text = "Uno dos tres";
    const range = locateFragment(text, "Uno ... tres");

    expect(text.slice(range!.start, range!.end)).toBe("Uno");
  });

  it("returns null when the quote is not in the text", () => {
    expect(locateFragment(BODY, "no aparece en ningun lado")).toBeNull();
  });

  it("returns null for an empty quote or text", () => {
    expect(locateFragment(BODY, "")).toBeNull();
    expect(locateFragment("", "algo")).toBeNull();
  });

  it("refuses a fragment too short to prove anything", () => {
    expect(locateFragment(BODY, "de la")).toBeNull();
  });
});
