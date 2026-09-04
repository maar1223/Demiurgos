import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MethodologyStatePanel } from "@/components/organisms/MethodologyStatePanel";
import type { MethodologyStatus } from "@/api/types";

const status: MethodologyStatus = {
  published: [
    {
      skill_id: "eneagrama",
      version: "1.2.0",
      name: "Eneagrama",
      description: "Tipos de personalidad",
      digest: "abc",
      published_at: "2026-01-01",
      taller: "Herramientas",
      talleres_compatibles: ["Mundo", "Ideas"],
      etiquetas: ["personalidad"],
      parent_skill_id: "base",
      parent_version: "1.0.0",
    },
    {
      skill_id: "eneagrama",
      version: "1.3.0",
      name: "Eneagrama",
      description: "Tipos de personalidad",
      digest: "def",
      published_at: "2026-02-01",
      taller: "Herramientas",
    },
    {
      skill_id: "otra-skill",
      version: "1.0.0",
      name: "Otra skill",
      description: "",
      digest: "ghi",
      published_at: "2026-03-01",
      taller: "Mundo",
    },
  ],
  activations: {
    nec: {
      world: "nec",
      skill_id: "eneagrama",
      version: "1.2.0",
      digest: "abc",
      activated_at: "2026-01-02",
    },
  },
  drafts: [],
};

const selected = { skill_id: "eneagrama", version: "1.2.0" };

function renderPanel(
  overrides: Partial<Parameters<typeof MethodologyStatePanel>[0]> = {},
) {
  const props = {
    selected,
    status,
    lens: "mi-mundo" as const,
    world: "nec",
    onActivate: vi.fn(),
    onAdaptar: vi.fn(),
    onComparar: vi.fn(),
    onExportar: vi.fn(),
    ...overrides,
  };
  render(<MethodologyStatePanel {...props} />);
  return props;
}

describe("MethodologyStatePanel (SC-SB-4)", () => {
  it("renders versions/activations filtered by skill_id", () => {
    renderPanel();

    // Only eneagrama versions are listed (SC-SB-4: filtered by skill_id) —
    // "otra-skill" is not in the list, "1.3.0" is.
    expect(screen.getByText("v1.2.0")).toBeInTheDocument();
    expect(screen.getByText("v1.3.0")).toBeInTheDocument();
    expect(screen.queryByText("v1.0.0")).not.toBeInTheDocument();
    // The 1.2.0 activation for world "nec" surfaces as "Activa en nec".
    expect(screen.getByText("Activa en nec")).toBeInTheDocument();
  });

  it("shows Activar + Adaptar in mi-mundo (SC-SB-4.1)", () => {
    const props = renderPanel();

    const activar = screen.getByRole("button", { name: "Activar" });
    const adaptar = screen.getByRole("button", { name: "Adaptar" });
    expect(activar).toBeInTheDocument();
    expect(adaptar).toBeInTheDocument();
    expect(activar).toBeEnabled();

    fireEvent.click(activar);
    expect(props.onActivate).toHaveBeenCalledWith("eneagrama", "1.2.0");
  });

  it("shows Adaptar + Comparar + Exportar and NO Activar in catalogo (SC-SB-4.2)", () => {
    const props = renderPanel({ lens: "catalogo-total" as const });

    expect(screen.getByRole("button", { name: "Adaptar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Comparar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exportar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activar" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Comparar" }));
    expect(props.onComparar).toHaveBeenCalledWith(
      expect.objectContaining({ skill_id: "eneagrama", version: "1.2.0" }),
    );
  });

  it("renders the provenance badge from parent fields (SC-SB-4.3)", () => {
    renderPanel();
    expect(screen.getByText("Deriva de base@1.0.0")).toBeInTheDocument();
  });

  it("renders the empty state when selected is null (SC-SB-4.4)", () => {
    renderPanel({ selected: null });

    expect(
      screen.getByText(/Seleccioná una metodología para ver su estado/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activar" })).not.toBeInTheDocument();
  });
});