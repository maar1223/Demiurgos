import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MethodologyLibrary } from "@/components/organisms/MethodologyLibrary";
import type { MethodologyStatus } from "@/api/types";

const status: MethodologyStatus = {
  published: [
    {
      skill_id: "guided-character-v1",
      version: "1.2.0",
      name: "Guided character methodology",
      description: "",
      digest: "abc",
      published_at: "2026-01-01",
      taller: "Mundo",
    },
  ],
  activations: {},
  drafts: [],
  companions: {},
};

/** Multi-version fixture (REQ-TRE-9/10): one skill published at 1.0/1.1/1.2
 *  — the explorer must render a single row @1.2 (latest). */
const multiVersionStatus: MethodologyStatus = {
  published: [
    {
      skill_id: "multi-skill",
      version: "1.0",
      name: "Multi skill",
      description: "",
      digest: "a",
      published_at: "2026-01-01",
      taller: "Mundo",
      talleres_compatibles: [],
    },
    {
      skill_id: "multi-skill",
      version: "1.1",
      name: "Multi skill",
      description: "",
      digest: "b",
      published_at: "2026-01-01",
      taller: "Mundo",
      talleres_compatibles: [],
    },
    {
      skill_id: "multi-skill",
      version: "1.2",
      name: "Multi skill",
      description: "",
      digest: "c",
      published_at: "2026-01-01",
      taller: "Mundo",
      talleres_compatibles: [],
    },
  ],
  activations: {},
  drafts: [],
  companions: {
    nec: [
      {
        world: "nec",
        skill_id: "multi-skill",
        version: "1.2",
        description: "",
        activated_at: "2026-01-01",
      },
    ],
  },
};

function renderLibrary(
  overrides: Partial<Parameters<typeof MethodologyLibrary>[0]> = {},
) {
  const props = {
    world: "nec",
    activeTaller: "Mundo",
    status,
    selected: null,
    onSelect: vi.fn(),
  };
  render(<MethodologyLibrary {...props} {...overrides} />);
  return props;
}

describe("MethodologyLibrary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders published versions from the library status", async () => {
    renderLibrary();
    await waitFor(() => {
      expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    });
    expect(screen.getByText(/guided-character-v1@1\.2\.0/)).toBeInTheDocument();
  });

  it("shows the empty state when nothing is published", async () => {
    renderLibrary({
      status: { published: [], activations: {}, drafts: [], companions: {} },
    });
    await waitFor(() => {
      expect(screen.getByText(/Todavía no hay metodologías publicadas/)).toBeInTheDocument();
    });
  });

  it("never renders activation state or 'Activa en' copy (S1/S2)", async () => {
    renderLibrary({
      status: {
        ...status,
        activations: {
          nec: {
            world: "nec",
            skill_id: "guided-character-v1",
            version: "1.2.0",
            digest: "abc",
            activated_at: "2026-01-01",
          },
        },
      },
    });
    await waitFor(() => {
      expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    });
    expect(screen.queryByText(/Activa en/)).not.toBeInTheDocument();
    expect(screen.queryByText("Activa")).not.toBeInTheDocument();
    expect(screen.queryByText("Inactiva")).not.toBeInTheDocument();
  });

  it("groups by chat availability in order (S1)", async () => {
    const fullStatus: MethodologyStatus = {
      published: [
        {
          skill_id: "sk-en-chat",
          version: "1.0.0",
          name: "Skill en chat",
          description: "",
          digest: "a",
          published_at: "2026-01-01",
          taller: "Mundo",
          talleres_compatibles: [],
        },
        {
          skill_id: "sk-fuera",
          version: "1.0.0",
          name: "Skill fuera del chat",
          description: "",
          digest: "b",
          published_at: "2026-01-01",
          taller: "Mundo",
          talleres_compatibles: [],
        },
        {
          skill_id: "sk-trans",
          version: "1.0.0",
          name: "Skill transversal",
          description: "",
          digest: "c",
          published_at: "2026-01-01",
          taller: "Ideas",
          talleres_compatibles: ["Mundo"],
        },
        {
          skill_id: "sk-heredada-herramientas",
          version: "1.0.0",
          name: "Skill heredada herramientas",
          description: "",
          digest: "d",
          published_at: "2026-01-01",
          taller: "Herramientas",
          talleres_compatibles: [],
        },
        {
          skill_id: "sk-sin-taller",
          version: "1.0.0",
          name: "Skill sin taller",
          description: "",
          digest: "e",
          published_at: "2026-01-01",
        },
      ],
      activations: {},
      drafts: [],
      companions: {
        nec: [
          {
            world: "nec",
            skill_id: "sk-en-chat",
            version: "1.0.0",
            description: "",
            activated_at: "2026-01-01",
          },
        ],
      },
    };
    renderLibrary({ status: fullStatus });

    await waitFor(() => {
      expect(screen.getByText("Skill en chat")).toBeInTheDocument();
    });

    const headings = screen.getAllByRole("heading", {
      name: /En el chat|Fuera del chat|Sin taller/,
    });
    expect(headings.map((h) => h.textContent)).toEqual([
      "En el chat",
      "Fuera del chat",
      "Sin taller",
    ]);

    // A legacy Herramientas-tagged record lands in "Sin taller", never hidden.
    expect(screen.getByText("Skill heredada herramientas")).toBeInTheDocument();

    const chatRow = screen.getByText("Skill en chat").closest("li") as HTMLElement;
    expect(within(chatRow).getByText("En el chat")).toHaveClass(
      "text-status-success",
    );
    expect(within(chatRow).getByText("En el chat").closest("[data-axis]")).toHaveAttribute(
      "data-axis",
      "companion",
    );

    const transRow = screen.getByText("Skill transversal").closest("li") as HTMLElement;
    expect(within(transRow).getByText("Transversal")).toBeInTheDocument();
    expect(within(transRow).queryByText("En el chat")).not.toBeInTheDocument();
  });

  it("renders no action buttons on rows (actions live in the right panel)", async () => {
    renderLibrary();
    await waitFor(() => {
      expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: "Adaptar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activar" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Añadir al chat" }),
    ).not.toBeInTheDocument();
  });

  it("preserves the selection while the filtered row stays visible (SC-SB-2.3)", async () => {
    const user = userEvent.setup();
    const props = renderLibrary({
      selected: { skill_id: "guided-character-v1", version: "1.2.0" },
    });
    await waitFor(() => {
      expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    });

    await user.type(screen.getByRole("searchbox"), "Guided");
    expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("clears the selection when the query filters the selected row out (SC-SB-2.3)", async () => {
    const user = userEvent.setup();
    const props = renderLibrary({
      selected: { skill_id: "guided-character-v1", version: "1.2.0" },
    });
    await waitFor(() => {
      expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    });

    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(await screen.findByText("Sin resultados")).toBeInTheDocument();
    await waitFor(() => {
      expect(props.onSelect).toHaveBeenCalledWith(null);
    });
  });

  it("renders exactly one row per skill_id with the latest version (REQ-TRE-9/10)", async () => {
    renderLibrary({ status: multiVersionStatus });

    await waitFor(() => {
      expect(screen.getByText("Multi skill")).toBeInTheDocument();
    });

    expect(screen.getAllByText("Multi skill")).toHaveLength(1);
    const row = screen.getByText("Multi skill").closest("li") as HTMLElement;
    expect(within(row).getByText(/multi-skill@1\.2/)).toBeInTheDocument();
    expect(within(row).getByText("En el chat")).toBeInTheDocument();
  });

  it("keeps a non-representative selection and its row highlight while filtered in (REQ-TRE-12 S8)", async () => {
    const user = userEvent.setup();
    const props = renderLibrary({
      status: multiVersionStatus,
      selected: { skill_id: "multi-skill", version: "1.0" },
    });
    await waitFor(() => {
      expect(screen.getByText("Multi skill")).toBeInTheDocument();
    });

    await user.type(screen.getByRole("searchbox"), "Multi");
    const row = screen.getByText("Multi skill").closest("li") as HTMLElement;
    expect(row).toHaveClass("border-action");
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("clears a filtered-out multi-version selection (REQ-TRE-12 S9)", async () => {
    const user = userEvent.setup();
    const props = renderLibrary({
      status: multiVersionStatus,
      selected: { skill_id: "multi-skill", version: "1.0" },
    });
    await waitFor(() => {
      expect(screen.getByText("Multi skill")).toBeInTheDocument();
    });

    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(await screen.findByText("Sin resultados")).toBeInTheDocument();
    await waitFor(() => {
      expect(props.onSelect).toHaveBeenCalledWith(null);
    });
  });

  it("keeps the single-version selection behavior unchanged (REQ-TRE-12 S10)", async () => {
    const user = userEvent.setup();
    const props = renderLibrary({
      selected: { skill_id: "guided-character-v1", version: "1.2.0" },
    });
    await waitFor(() => {
      expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    });

    await user.type(screen.getByRole("searchbox"), "Guided");
    const row = screen.getByText("Guided character methodology").closest(
      "li",
    ) as HTMLElement;
    expect(row).toHaveClass("border-action");
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("renders the empty-state CTA wired to onGoToCoCrear (UL-5)", async () => {
    const user = userEvent.setup();
    const onGoToCoCrear = vi.fn();
    renderLibrary({
      status: { published: [], activations: {}, drafts: [], companions: {} },
      onGoToCoCrear,
    });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Crear tu primera skill" }),
      ).toBeInTheDocument();
    });
    await user.click(
      screen.getByRole("button", { name: "Crear tu primera skill" }),
    );
    expect(onGoToCoCrear).toHaveBeenCalledTimes(1);
  });
});
