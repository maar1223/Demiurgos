import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { MethodologyStatePanel } from "@/components/organisms/MethodologyStatePanel";
import {
  getCompanionLatencyNotified,
  markCompanionLatencyNotified,
} from "@/lib/companionLatency";
import { AXIS_SCOPE, AXIS_TERMS } from "@/lib/vocabularyAxes";
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
      taller: "Mundo",
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
      taller: "Mundo",
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

/** Registry scope term for the scope axis — reverse lookup so the test never
 *  hardcodes the vocabulary (spec R1: visible text equals registry value). */
const SCOPE_TERM =
  Object.entries(AXIS_TERMS).find(([, axis]) => axis === AXIS_SCOPE)?.[0] ?? "";

/** A transversal skill of the active taller "Mundo" (own taller Ideas). */
const transversalStatus: MethodologyStatus = {
  published: [
    {
      skill_id: "sk-trans",
      version: "1.0.0",
      name: "Skill transversal",
      description: "",
      digest: "t",
      published_at: "2026-01-01",
      taller: "Ideas",
      talleres_compatibles: ["Mundo"],
    },
  ],
  activations: {},
  drafts: [],
};

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
    activeTaller: "Mundo",
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
  it("renders versions filtered by skill_id and no activation line (S1/S2)", () => {
    renderPanel();

    expect(screen.getByText("v1.2.0")).toBeInTheDocument();
    expect(screen.getByText("v1.3.0")).toBeInTheDocument();
    expect(screen.queryByText("v1.0.0")).not.toBeInTheDocument();
    expect(screen.queryByText(/Activa en/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activar" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Desactivar" }),
    ).not.toBeInTheDocument();
  });

  it("shows Adaptar in mi-mundo (SC-SB-4.1)", () => {
    const props = renderPanel({
      selected: { skill_id: "eneagrama", version: "1.3.0" },
    });

    const adaptar = screen.getByRole("button", { name: "Adaptar" });
    expect(adaptar).toBeInTheDocument();
    expect(adaptar).toHaveAttribute(
      "title",
      "Deriva una versión editable de esta publicación.",
    );
    expect(
      screen.queryByRole("button", { name: "Activar" }),
    ).not.toBeInTheDocument();

    fireEvent.click(adaptar);
    expect(props.onAdaptar).toHaveBeenCalledWith(
      expect.objectContaining({ skill_id: "eneagrama", version: "1.3.0" }),
    );
  });

  it("shows Adaptar + Comparar + Exportar and no chat block in catalogo (SC-SB-4.2)", () => {
    const props = renderPanel({ lens: "catalogo-total" as const });

    expect(screen.getByRole("button", { name: "Adaptar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Comparar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exportar" })).toBeInTheDocument();
    expect(screen.queryByText("Chat de nec")).not.toBeInTheDocument();

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
      screen.getByText(/Selecciona una metodología para ver su estado/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activar" })).not.toBeInTheDocument();
  });

  it("switches the selection when a version row is clicked (UL-3)", () => {
    const props = renderPanel({ onSelect: vi.fn() });

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

  it("surfaces an inline export error when onExportar rejects (REQ-IMP-1 feedback in the right panel)", async () => {
    const onExportar = vi.fn().mockRejectedValue(new Error("boom"));
    renderPanel({ lens: "catalogo-total" as const, onExportar });

    fireEvent.click(screen.getByRole("button", { name: "Exportar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se pudo exportar la metodología.",
    );
  });

  it("shows the latency notice for the world just added (R-UI notice)", () => {
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

describe("chat block (S1/S2/S5)", () => {
  it("names the world and explains that the chat routes on its own", () => {
    renderPanel();
    expect(screen.getByText("Chat de nec")).toBeInTheDocument();
    expect(
      screen.getByText(
        "El chat elige solo entre estas skills según la conversación.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Ninguna skill añadida al chat.")).toBeInTheDocument();
  });

  it("adds the selected version to the chat when it is not there", () => {
    const props = renderPanel({ selected: { skill_id: "eneagrama", version: "1.3.0" } });

    fireEvent.click(screen.getByRole("button", { name: "Añadir al chat" }));
    expect(props.onToggleCompanion).toHaveBeenCalledWith(
      "eneagrama",
      "1.3.0",
      true,
    );
  });

  it("removes the selected version from the chat when it is already there", () => {
    const props = renderPanel({ status: companionStatus });

    expect(screen.getByText("eneagrama@1.2.0")).toBeInTheDocument();
    fireEvent.click(
      screen.getAllByRole("button", { name: "Quitar del chat" })[0],
    );
    expect(props.onToggleCompanion).toHaveBeenCalledWith(
      "eneagrama",
      "1.2.0",
      false,
    );
  });

  it("lists every chat skill with a Quitar del chat action", () => {
    renderPanel({ status: companionStatus });

    const list = screen.getByText("Skills en el chat").closest("div")!;
    fireEvent.click(
      within(list).getByRole("button", { name: "Quitar del chat" }),
    );
    expect(screen.getByText("eneagrama@1.2.0")).toBeInTheDocument();
  });
});

describe("guided assistant info (S1/S6)", () => {
  it("explains that the method is chosen at session start", () => {
    renderPanel();
    expect(screen.getByText("Asistente de personajes")).toBeInTheDocument();
    expect(
      screen.getByText(
        "El asistente elige su método al iniciar la sesión; si no eliges, usa el de fábrica.",
      ),
    ).toBeInTheDocument();
  });

  it("never pins a guided method from the panel", () => {
    renderPanel();
    expect(screen.queryByText(/Activar/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Desactivar/)).not.toBeInTheDocument();
  });
});

describe("scope block (R3 / REQ-TRE-6)", () => {
  it("shows the registry scope term in the Alcance de taller block for a transversal skill", () => {
    renderPanel({
      status: transversalStatus,
      selected: { skill_id: "sk-trans", version: "1.0.0" },
      activeTaller: "Mundo",
    });

    const block = screen.getByText("Alcance de taller").closest("div")!;
    const chip = within(block).getByText(SCOPE_TERM).closest("[data-axis]");
    expect(chip).toHaveAttribute("data-axis", AXIS_SCOPE);
  });
});
