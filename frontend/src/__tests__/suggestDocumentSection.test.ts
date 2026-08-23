import { describe, it, expect } from "vitest";
import {
  CLASSIFIER_SECTIONS,
  SUGGESTION_SCAN_BYTES,
  suggestDocumentSection,
} from "@/pages/WorldImporter";

describe("suggestDocumentSection — classifier heuristic (BLOQUE 1 piece 1)", () => {
  it("suggests personajes for a personaje keyword in the head", () => {
    expect(suggestDocumentSection("Protagonista del clan")).toBe("personajes");
  });

  it("suggests personajes for each keyword in the table", () => {
    const keywords = [
      "personaje", "protagonista", "antagonista", "héroe", "villano",
      "criatura", "raza", "linaje", "clan", "familia",
    ];
    for (const kw of keywords) {
      expect(suggestDocumentSection(`Texto con ${kw} aquí`)).toBe("personajes");
    }
  });

  it("suggests referencias for a glosario keyword", () => {
    expect(suggestDocumentSection("El glosario de términos del mundo")).toBe(
      "referencias",
    );
  });

  it("suggests referencias for each keyword in the table", () => {
    const keywords = [
      "glosario", "índice", "apéndice", "términos", "vocabulario",
      "tabla de", "cronología", "bibliografía", "anexo",
    ];
    for (const kw of keywords) {
      expect(suggestDocumentSection(`Un ${kw} de referencia`)).toBe(
        "referencias",
      );
    }
  });

  it("defaults to lore for weak or no signal", () => {
    expect(suggestDocumentSection("")).toBe("lore");
    expect(suggestDocumentSection("Un texto sin señales claras.")).toBe("lore");
    expect(suggestDocumentSection("El paisaje se extiende bajo la luna.")).toBe(
      "lore",
    );
  });

  it("matches keywords in H1/H2 headings even beyond the 8KB head", () => {
    const body = "x".repeat(SUGGESTION_SCAN_BYTES + 1024);
    const withHeading = `## Glosario\n\n${body}`;
    expect(suggestDocumentSection(withHeading)).toBe("referencias");
    // H1 headings count too.
    expect(suggestDocumentSection(`# Clan del Norte\n\n${body}`)).toBe(
      "personajes",
    );
  });

  it("matches case-insensitively", () => {
    expect(suggestDocumentSection("PROTAGONISTA")).toBe("personajes");
    expect(suggestDocumentSection("GlOsArIo")).toBe("referencias");
    expect(suggestDocumentSection("Héroe de la ciudad")).toBe("personajes");
  });

  it("ignores keywords beyond the first 8KB of prose (head boundary)", () => {
    const head = "x".repeat(SUGGESTION_SCAN_BYTES);
    expect(suggestDocumentSection(`${head} glosario al final`)).toBe("lore");
    expect(
      suggestDocumentSection(`# Título\n\n${head} protagonista lejos`),
    ).toBe("lore");
  });

  it("personajes signals win over referencias when both are present", () => {
    expect(
      suggestDocumentSection("Protagonista del clan y glosario de términos"),
    ).toBe("personajes");
  });

  it("offers exactly the local classifier sections (no sagas)", () => {
    expect([...CLASSIFIER_SECTIONS]).toEqual([
      "lore",
      "personajes",
      "referencias",
    ]);
  });
});