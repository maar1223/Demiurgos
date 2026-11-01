import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { GraphEntity } from "@/api/types";
import {
  NodeInspectorPanel,
  stripMarkdownPreview,
  truncateContent,
} from "@/components/organisms/NodeInspectorPanel";

/** Rhyz with a full metadata set, content, and one forward link to Vael. */
const RHYZ: GraphEntity = {
  id: "Stal::Rhyz",
  name: "Rhyz",
  type: "personaje",
  path: "personajes/Rhyz.md",
  status: "stable",
  content: "",
  forward_links: ["Vael"],
  backlinks: [],
  relaciones: ["Stal::Vael"],
};

/** Vael — the neighbor Rhyz references. */
const VAEL: GraphEntity = {
  id: "Stal::Vael",
  name: "Vael",
  type: "personaje",
  path: "personajes/Vael.md",
  status: "draft",
  content: "",
  forward_links: [],
  backlinks: ["personajes/Rhyz.md"],
  relaciones: [],
};

function entityByKey(entities: GraphEntity[]): Map<string, GraphEntity> {
  return new Map(entities.map((entity) => [entity.id || entity.path, entity]));
}

const KEYS = entityByKey([RHYZ, VAEL]);
const VISIBLE = new Set(["Stal::Rhyz", "Stal::Vael"]);

function renderPanel(
  overrides: Partial<{
    entity: GraphEntity;
    visibleEntityKeys: Set<string>;
    entityByKey: Map<string, GraphEntity>;
    mundo: string;
    onRemoveRelation: (reference: string) => void;
  }> = {},
) {
  const onNeighborClick = vi.fn();
  const onOpenFicha = vi.fn();
  const onClose = vi.fn();
  render(
    <NodeInspectorPanel
      entity={overrides.entity ?? RHYZ}
      visibleEntityKeys={overrides.visibleEntityKeys ?? VISIBLE}
      entityByKey={overrides.entityByKey ?? KEYS}
      onNeighborClick={onNeighborClick}
      onOpenFicha={onOpenFicha}
      onClose={onClose}
      onRemoveRelation={overrides.onRemoveRelation}
      mundo={overrides.mundo ?? "vibrantes"}
    />,
  );
  return { onNeighborClick, onOpenFicha, onClose };
}

describe("NodeInspectorPanel", () => {
  it("offers a per-relation remove action only when the handler is provided", () => {
    const { unmount } = render(
      <NodeInspectorPanel
        entity={RHYZ}
        visibleEntityKeys={VISIBLE}
        entityByKey={KEYS}
        onNeighborClick={vi.fn()}
        onOpenFicha={vi.fn()}
        onClose={vi.fn()}
        mundo="vibrantes"
      />,
    );
    expect(screen.queryAllByTestId("remove-relation")).toHaveLength(0);
    unmount();
  });

  it("removes a relation by its node key", () => {
    const onRemoveRelation = vi.fn();
    renderPanel({ onRemoveRelation });

    const buttons = screen.getAllByTestId("remove-relation");
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);

    expect(onRemoveRelation).toHaveBeenCalledWith("Stal::Vael");
  });

  it("renders name, type, status chip, and path from the entity", () => {
    renderPanel();

    expect(
      screen.getByRole("heading", { name: "Rhyz" }),
    ).toBeInTheDocument();
    // Type is capitalized for display; status chip uses STATUS_META (stable → "Canon").
    expect(screen.getByText("Personaje")).toBeInTheDocument();
    expect(screen.getByText("Canon")).toBeInTheDocument();
    expect(screen.getByText("personajes/Rhyz.md")).toBeInTheDocument();
    expect(screen.getByText("Mundo: vibrantes")).toBeInTheDocument();
  });

  it("renders a draft status chip via STATUS_META", () => {
    renderPanel({ entity: { ...RHYZ, status: "draft" } });
    expect(screen.getByText("Borrador")).toBeInTheDocument();
  });

  it("truncates long content to ~280 chars with an ellipsis", () => {
    const longContent = "x".repeat(500);
    renderPanel({ entity: { ...RHYZ, content: longContent } });

    const preview = screen.getByText(/x+…/);
    // 280 chars + the "…" suffix.
    expect(preview.textContent).toHaveLength(281);
    expect(preview.textContent?.endsWith("…")).toBe(true);
  });

  it("shows a placeholder when the entity has no content", () => {
    renderPanel({ entity: { ...RHYZ, content: "" } });
    expect(screen.getByText("Sin contenido")).toBeInTheDocument();
  });

  it("shows an empty state when there are no relaciones", () => {
    renderPanel({ entity: { ...RHYZ, relaciones: [] } });
    // The Relaciones list falls back to the shared empty label.
    expect(screen.getAllByText("Ninguna").length).toBeGreaterThan(0);
  });

  it("renders a resolved visible neighbor as a clickable link", () => {
    const { onNeighborClick } = renderPanel({
      entity: { ...RHYZ, relaciones: [] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Vael" }));
    expect(onNeighborClick).toHaveBeenCalledWith("Stal::Vael");
  });

  it("renders an unresolved neighbor as plain text", () => {
    const { onNeighborClick } = renderPanel({
      entity: { ...RHYZ, forward_links: ["Zzz Desconocido"], relaciones: [] },
    });
    const entry = screen.getByText("Zzz Desconocido");
    expect(entry.tagName).toBe("SPAN");
    expect(onNeighborClick).not.toHaveBeenCalled();
  });

  it("renders a filtered-out neighbor as plain text (not clickable)", () => {
    const { onNeighborClick } = renderPanel({
      // Vael is loaded but NOT in the visible node set (status/folder filter).
      entity: { ...RHYZ, relaciones: [] },
      visibleEntityKeys: new Set(["Stal::Rhyz"]),
    });
    const entry = screen.getByText("Vael");
    expect(entry.tagName).toBe("SPAN");
    expect(onNeighborClick).not.toHaveBeenCalled();
  });

  it("renders backlinks as neighbor entries (path-backed resolution)", () => {
    const { onNeighborClick } = renderPanel({
      entity: {
        ...RHYZ,
        forward_links: [],
        relaciones: [],
        backlinks: ["personajes/Vael.md"],
      },
    });
    // Vael's path form resolves to its node key and renders as a link.
    fireEvent.click(screen.getByRole("button", { name: "Vael" }));
    expect(onNeighborClick).toHaveBeenCalledWith("Stal::Vael");
  });

  it("renders a relaciones entry and resolves it to its entity", () => {
    const { onNeighborClick } = renderPanel({
      entity: { ...RHYZ, forward_links: [] },
    });
    // "Stal::Vael" is a canonical-id entry → resolves to Vael, clickable.
    fireEvent.click(screen.getByRole("button", { name: "Vael" }));
    expect(onNeighborClick).toHaveBeenCalledWith("Stal::Vael");
  });

  it("calls onOpenFicha when the ficha button is clicked", () => {
    const { onOpenFicha } = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Abrir ficha" }));
    expect(onOpenFicha).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when the close button is clicked", () => {
    const { onClose } = renderPanel();
    fireEvent.click(
      screen.getByRole("button", { name: "Cerrar panel de inspección" }),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("strips markdown markers from the content preview", () => {
    expect(stripMarkdownPreview("# **Vibristal | Niveles**")).toBe(
      "Vibristal | Niveles",
    );
    expect(
      stripMarkdownPreview("[[Vibrastal-Estados-y-Niveles][media/x]]"),
    ).toBe("Vibrastal-Estados-y-Niveles");
    expect(stripMarkdownPreview("- uno\n- dos")).toBe("• uno\n• dos");
  });

  it("truncateContent keeps short content untouched", () => {
    expect(truncateContent("corto")).toBe("corto");
    expect(truncateContent("x".repeat(280))).toHaveLength(280);
  });
});