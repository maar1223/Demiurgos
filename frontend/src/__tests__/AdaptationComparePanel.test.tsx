import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  AdaptationComparePanel,
  classifySection,
  parseSourceSections,
} from "@/components/organisms/CoCreation/AdaptationComparePanel";
import type {
  DraftPayload,
  PublishedMethodologyDetail,
} from "@/api/types";
import { tEs } from "@/__tests__/i18nTestUtils";

const originalSource = `# Eneagrama

Tipos de personalidad.

## Propósito

Modelar los nueve eneatipos.

## Alcance

Personajes.

## Flujo principal

Clasificar y derivar arcos.

## Ramas y reglas

- Rama original
`;

const original: PublishedMethodologyDetail = {
  skill_id: "eneagrama",
  version: "1.2.0",
  name: "Eneagrama",
  description: "Tipos de personalidad",
  digest: "abc",
  published_at: "2026-01-01",
  phases: [],
  language: "es",
  source: originalSource,
  parent_skill_id: null,
  parent_version: null,
};

const derivedPayload: DraftPayload = {
  name: "Eneagrama",
  description: "Tipos de personalidad",
  purpose: "Modelar los nueve eneatipos",
  scope: "Personajes y criaturas",
  main_flow: "Clasificar y derivar arcos",
  branches: ["Rama original", "Rama nueva"],
  rules: [],
  pending_questions: [],
  world: null,
};

function renderPanel(
  overrides: Partial<Parameters<typeof AdaptationComparePanel>[0]> = {},
) {
  const props = {
    original,
    derivedPayload,
    derivedFrom: { skill_id: "eneagrama", version: "1.2.0" },
    isOpen: true,
    onClose: () => undefined,
    canvas: <div data-testid="derived-canvas" />,
    ...overrides,
  };
  render(<AdaptationComparePanel {...props} />);
  return props;
}

describe("classifySection (REQ-CC-18)", () => {
  it("classifies unchanged sections as conservado", () => {
    expect(classifySection("Modelar", "Modelar")).toBe("conservado");
    expect(classifySection("", "")).toBe("conservado");
  });

  it("classifies changed sections as modificado", () => {
    expect(classifySection("Modelar", "Modelar y narrar")).toBe("modificado");
  });

  it("classifies sections absent in the original as añadido", () => {
    expect(classifySection("", "Nueva regla")).toBe("añadido");
  });

  it("classifies sections removed in the derived as eliminado", () => {
    expect(classifySection("Regla vieja", "")).toBe("eliminado");
  });
});

describe("parseSourceSections (deterministic template reverse)", () => {
  it("extracts name, description and typed sections from the template source", () => {
    const parsed = parseSourceSections(originalSource);

    expect(parsed.name).toBe("Eneagrama");
    expect(parsed.description).toBe("Tipos de personalidad.");
    expect(parsed.purpose).toBe("Modelar los nueve eneatipos.");
    expect(parsed.scope).toBe("Personajes.");
    expect(parsed.main_flow).toBe("Clasificar y derivar arcos.");
    // Known lossiness: template bullets (branches+rules adjacent lists) seed
    // into `branches` only; the Author reclassifies in the canvas.
    expect(parsed.branches).toEqual(["Rama original"]);
  });

  it("never raises on non-template sources", () => {
    expect(parseSourceSections("sin estructura")).toEqual({});
    expect(parseSourceSections("")).toEqual({});
  });
});

describe("AdaptationComparePanel", () => {
  it("renders per-section classification badges (REQ-CC-18)", () => {
    renderPanel();

    // scope changed -> modificado; branches extended -> modificado
    expect(
      screen.getAllByText(tEs("cocreation.classification.modificado")).length,
    ).toBeGreaterThanOrEqual(2);
    expect(
      screen.getAllByText(tEs("cocreation.classification.conservado")).length,
    ).toBeGreaterThan(0);
  });

  it("renders the original read-only and the derived side editable", () => {
    renderPanel();

    // Original column: the published source renders via MarkdownViewer.
    expect(
      screen.getByText(tEs("cocreation.compare.original")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(tEs("cocreation.compare.derived")),
    ).toBeInTheDocument();
    // The derived side is the injected editable canvas node.
    expect(screen.getByTestId("derived-canvas")).toBeInTheDocument();
  });

  it("shows the TW14 provenance badge on the derivation", () => {
    renderPanel();

    expect(
      screen.getByText(
        tEs("cocreation.provenance", { skillId: "eneagrama", version: "1.2.0" }),
      ),
    ).toBeInTheDocument();
  });

  it("renders nothing when closed", () => {
    renderPanel({ isOpen: false });

    expect(
      screen.queryByText(tEs("cocreation.compare.title")),
    ).not.toBeInTheDocument();
  });
});