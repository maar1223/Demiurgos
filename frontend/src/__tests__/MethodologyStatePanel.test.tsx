import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MethodologyStatePanel } from "@/components/organisms/MethodologyStatePanel";
import {
  getCompanionLatencyNotified,
  markCompanionLatencyNotified,
} from "@/lib/companionLatency";
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

/** Status carrying one active companion (eneagrama@1.2.0) in world "nec". */
const companionStatus: MethodologyStatus = {
  ...status,
  companions: {
    nec: [
      {
        world: "nec",
        skill_id: "eneagrama",
        version: "1.2.0",
        description: "",
        activated_at: "2026-01-03",
      },
    ],
  },
};

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
    onToggleCompanion: vi.fn(),
    busy: false,
    latencyNoticeWorld: null,
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

  it("switches the selection when a version row is clicked (UL-3)", () => {
    const props = renderPanel({
      onSelect: vi.fn(),
    });

    // Versiones rows are clickable buttons: clicking v1.3.0 reports the new
    // selection upward (spec UL-3 S1).
    fireEvent.click(screen.getByText("v1.3.0"));
    expect(props.onSelect).toHaveBeenCalledWith({
      skill_id: "eneagrama",
      version: "1.3.0",
    });
  });

  it("renders the compare panel below the actions when two items are compared (UL-4)", () => {
    const compareItems = [
      {
        skill_id: "eneagrama",
        version: "1.2.0",
        name: "Eneagrama",
        description: "",
        digest: "abc",
        published_at: "2026-01-01",
      },
      {
        skill_id: "eneagrama",
        version: "1.3.0",
        name: "Eneagrama",
        description: "",
        digest: "def",
        published_at: "2026-02-01",
      },
    ];
    const props = renderPanel({
      compareSelection: compareItems,
      onCompareClear: vi.fn(),
    });

    expect(screen.getByText("Comparación")).toBeInTheDocument();

    // The clear control moved with the panel (REQ-LIB-7).
    fireEvent.click(screen.getByRole("button", { name: "Limpiar" }));
    expect(props.onCompareClear).toHaveBeenCalled();
  });

  it("does not render the compare panel with fewer than two comparisons (UL-4)", () => {
    renderPanel({
      compareSelection: [
        {
          skill_id: "eneagrama",
          version: "1.2.0",
          name: "Eneagrama",
          description: "",
          digest: "abc",
          published_at: "2026-01-01",
        },
      ],
      onCompareClear: vi.fn(),
    });

    expect(screen.queryByText("Comparación")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Limpiar" }),
    ).not.toBeInTheDocument();
  });

  it("shows consequence tooltips on the Activar and Adaptar actions (UC-6)", () => {
    renderPanel();

    expect(screen.getByRole("button", { name: "Activar" })).toHaveAttribute(
      "title",
      "Activa esta versión para nuevas sesiones en el mundo seleccionado.",
    );
    expect(screen.getByRole("button", { name: "Adaptar" })).toHaveAttribute(
      "title",
      "Derivá una versión editable de esta publicación.",
    );
  });

  it("reflects a companion chip ON from status and lists the ON entry (R-UI chips)", () => {
    const props = renderPanel({ status: companionStatus });

    const chip = screen.getByRole("switch", { name: "Compañera en nec" });
    expect(chip).toHaveAttribute("aria-checked", "true");

    // Flipping the ON chip OFF reports the toggle with the selected version.
    fireEvent.click(chip);
    expect(props.onToggleCompanion).toHaveBeenCalledWith(
      "eneagrama",
      "1.2.0",
      false,
    );

    // The companion list shows the active entry with an OFF button.
    expect(screen.getByText("eneagrama@1.2.0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Apagar" }));
    expect(props.onToggleCompanion).toHaveBeenCalledWith(
      "eneagrama",
      "1.2.0",
      false,
    );
  });

  it("keeps the chip OFF for a selected version that is not a companion (R-UI chips)", () => {
    renderPanel({
      status: companionStatus,
      selected: { skill_id: "eneagrama", version: "1.3.0" },
    });

    expect(screen.getByRole("switch", { name: "Compañera en nec" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("never renders the word slot in the panel (R-UI slot vocabulary)", () => {
    renderPanel({ status: companionStatus });
    expect(screen.queryByText(/slot/i)).not.toBeInTheDocument();
  });

  it("shows the latency notice for the world just activated (R-UI notice)", () => {
    renderPanel({ latencyNoticeWorld: "nec" });
    expect(
      screen.getByText(
        /Las charlas de IA en este mundo pueden tardar un poco más/,
      ),
    ).toBeInTheDocument();
  });

  it("keeps the latency notice hidden for other worlds (R-UI notice)", () => {
    renderPanel({ latencyNoticeWorld: "otro-mundo" });
    expect(
      screen.queryByText(/Las charlas de IA en este mundo pueden tardar/),
    ).not.toBeInTheDocument();
  });

  it("persists the notice-once flag in localStorage (R-UI notice)", () => {
    window.localStorage.clear();

    expect(markCompanionLatencyNotified("nec")).toBe(true);
    expect(markCompanionLatencyNotified("nec")).toBe(false);
    expect(getCompanionLatencyNotified()).toEqual(["nec"]);
    expect(window.localStorage.getItem("demiurgos-companion-latency-notified")).toBe(
      '["nec"]',
    );
  });
});