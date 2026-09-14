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

/** Registry scope term for axis-3 — reverse lookup so the test never
 *  hardcodes the vocabulary (spec R1: visible text equals registry value). */
const SCOPE_TERM =
  Object.entries(AXIS_TERMS).find(([, axis]) => axis === AXIS_SCOPE)?.[0] ?? "";

/** REQ-TRE-6 S1 conflict copy — verbatim, taller names interpolated via
 *  OPERATIONAL_TALLER_LABELS (Taller de Mundo / Taller de Ideas). */
const BLOCKED_COPY =
  "Esta skill es transversal de Taller de Mundo pero su taller primario (Taller de Ideas) ya tiene una skill activa en este mundo. Adapta la skill para resolver el conflicto o actívala en otro mundo.";

/** A transversal skill of the active taller "Mundo" (own taller Ideas) that
 *  is NOT active and NOT blocked — the scope block surface. */
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

/** Blocked scenario (REQ-TRE-5): the Ideas slot in world "nec" is taken by
 *  sk-ideas-activa, so the Ideas-transversal sk-ideas-bloqueada is blocked
 *  for the active taller "Mundo". */
const blockedStatus: MethodologyStatus = {
  published: [
    {
      skill_id: "sk-ideas-activa",
      version: "1.0.0",
      name: "Skill ideas activa",
      description: "",
      digest: "f",
      published_at: "2026-01-01",
      taller: "Ideas",
      talleres_compatibles: ["Mundo"],
    },
    {
      skill_id: "sk-ideas-bloqueada",
      version: "1.0.0",
      name: "Skill ideas bloqueada",
      description: "",
      digest: "g",
      published_at: "2026-01-01",
      taller: "Ideas",
      talleres_compatibles: ["Mundo"],
    },
  ],
  activations: {
    nec: {
      world: "nec",
      skill_id: "sk-ideas-activa",
      version: "1.0.0",
      digest: "f",
      activated_at: "2026-01-01",
    },
  },
  drafts: [],
};

const blockedSelected = { skill_id: "sk-ideas-bloqueada", version: "1.0.0" };

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
    onActivate: vi.fn(),
    onDeactivate: vi.fn(),
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
    // 1.3.0 is published but NOT the world activation — Activar stays enabled.
    const props = renderPanel({
      selected: { skill_id: "eneagrama", version: "1.3.0" },
    });

    const activar = screen.getByRole("button", { name: "Activar" });
    const adaptar = screen.getByRole("button", { name: "Adaptar" });
    expect(activar).toBeInTheDocument();
    expect(adaptar).toBeInTheDocument();
    expect(activar).toBeEnabled();

    fireEvent.click(activar);
    expect(props.onActivate).toHaveBeenCalledWith("eneagrama", "1.3.0");
  });

  it("shows an enabled Desactivar button for the active version and fires onDeactivate (REQ-TRE-7)", () => {
    // Default fixture: eneagrama@1.2.0 IS activations.nec — the action slot
    // carries the real deactivate affordance instead of a dead-end "Activada".
    const props = renderPanel();

    const desactivar = screen.getByRole("button", { name: "Desactivar" });
    expect(desactivar).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Activar" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Activada" }),
    ).not.toBeInTheDocument();

    fireEvent.click(desactivar);
    expect(props.onDeactivate).toHaveBeenCalledWith("eneagrama", "1.2.0");
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
      screen.getByText(/Selecciona una metodología para ver su estado/),
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

  it("surfaces an inline export error when onExportar rejects (REQ-IMP-1 feedback in the right panel)", async () => {
    const onExportar = vi.fn().mockRejectedValue(new Error("boom"));
    renderPanel({ lens: "catalogo-total" as const, onExportar });

    fireEvent.click(screen.getByRole("button", { name: "Exportar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se pudo exportar la metodología.",
    );
  });

  it("shows consequence tooltips on the Activar and Adaptar actions (UC-6)", () => {
    renderPanel({ selected: { skill_id: "eneagrama", version: "1.3.0" } });

    expect(screen.getByRole("button", { name: "Activar" })).toHaveAttribute(
      "title",
      "Activa esta versión para nuevas sesiones en el mundo seleccionado.",
    );
    expect(screen.getByRole("button", { name: "Adaptar" })).toHaveAttribute(
      "title",
      "Deriva una versión editable de esta publicación.",
    );
  });

  it("reflects a companion chip ON from status and lists the ON entry (R-UI chips)", () => {
    const props = renderPanel({ status: companionStatus });

    const chip = screen.getByRole("switch", { name: "Metodología de chat en nec" });
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

    expect(screen.getByRole("switch", { name: "Metodología de chat en nec" })).toHaveAttribute(
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

describe("axis-binding-ui panel blocks (R3 / REQ-TRE-6)", () => {
  it("shows the registry scope term in the Alcance de taller block for a transversal skill (R3)", () => {
    renderPanel({
      status: transversalStatus,
      selected: { skill_id: "sk-trans", version: "1.0.0" },
      activeTaller: "Mundo",
    });

    // Registry-sourced (R3): the visible term is the AXIS_TERMS scope value
    // and the chip carries the scope axis attribution — the panel surface.
    const block = screen.getByText("Alcance de taller").closest("div")!;
    const chip = within(block).getByText(SCOPE_TERM).closest("[data-axis]");
    expect(chip).toHaveAttribute("data-axis", AXIS_SCOPE);
  });

  it("renders the blocked explanation verbatim in the Conflicto block (S1 — Blocked explanation rendered)", () => {
    renderPanel({
      status: blockedStatus,
      selected: blockedSelected,
      activeTaller: "Mundo",
    });

    const block = screen.getByText("Conflicto").closest("div")!;
    expect(
      within(block).getByText(BLOCKED_COPY, { selector: "p" }),
    ).toBeInTheDocument();
  });

  it("renders the conflict copy only inside the panel tooltip — no Bloqueada badge (Blocked conflict via tooltip)", () => {
    renderPanel({
      status: blockedStatus,
      selected: blockedSelected,
      activeTaller: "Mundo",
    });

    const block = screen.getByText("Conflicto").closest("div")!;
    // Conflict vocabulary lives in the block tooltip — never a badge (R3).
    expect(within(block).queryByText("Bloqueada")).not.toBeInTheDocument();

    const tooltip = within(block).getByRole("tooltip");
    expect(within(tooltip).getByText(BLOCKED_COPY)).toBeInTheDocument();
  });

  it("exposes the conflict copy to keyboard-only authors via the panel tooltip (Keyboard-only conflict access)", () => {
    renderPanel({
      status: blockedStatus,
      selected: blockedSelected,
      activeTaller: "Mundo",
    });

    const block = screen.getByText("Conflicto").closest("div")!;
    const trigger = block.querySelector(
      '[aria-describedby^="conflicto-panel-"]',
    ) as HTMLElement | null;
    expect(trigger).not.toBeNull();
    expect(trigger).toHaveAttribute("tabindex", "0");

    // The trigger's aria-describedby points at the sr-only accessible copy —
    // assistive tech reads it regardless of the CSS reveal state (R5).
    const accessible = document.getElementById(
      trigger!.getAttribute("aria-describedby")!,
    );
    expect(accessible).not.toBeNull();
    expect(accessible).toHaveAttribute("role", "tooltip");
    expect(
      within(accessible as HTMLElement).getByText(BLOCKED_COPY),
    ).toBeInTheDocument();
  });

  it("labels the slot display from flow_type at model level — zero per-flow copy (R6)", () => {
    renderPanel({
      status: {
        ...status,
        activations: {
          nec: {
            world: "nec",
            skill_id: "eneagrama",
            version: "1.2.0",
            digest: "abc",
            activated_at: "2026-01-02",
            flow_type: "guided-character",
          },
        },
      },
    });

    const slot = screen.getByText("Activa en nec");
    expect(slot).toHaveAttribute("data-flow-type", "guided-character");
    // Model-level attribution only — never committed as display copy (R6).
    expect(screen.queryByText("guided-character")).not.toBeInTheDocument();
  });
});