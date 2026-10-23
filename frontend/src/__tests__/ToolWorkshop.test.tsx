import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ToolWorkshop from "@/pages/ToolWorkshop";
import {
  ACTIVE_TALLER_STORAGE_KEY,
  OPERATIONAL_TALLERES,
} from "@/lib/constants";
import {
  ACTIVE_WORLD_STORAGE_KEY,
  setCurrentWorld,
} from "@/lib/currentWorld";
import { tEs } from "@/__tests__/i18nTestUtils";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

vi.mock("@/api/methodologies", () => ({
  getMethodologyStatus: vi.fn(),
  createMethodologyDraft: vi.fn(),
  publishMethodologyDraft: vi.fn(),
  activateMethodology: vi.fn(),
  activateCompanion: vi.fn(),
  deactivateCompanion: vi.fn(),
  deactivateMethodology: vi.fn(),
  getMethodologyInventory: vi.fn(),
  exportPublished: vi.fn(),
}));

/** Partial mock: `getPublishedDetail` is controllable for the selection
 *  integration tests; the co-creation session APIs stay REAL (the page's
 *  useCoCreation hook recovers nothing with an empty localStorage hint). */
const mockGetPublishedDetail = vi.hoisted(() => vi.fn());

vi.mock("@/api/coCreation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/coCreation")>();
  return { ...actual, getPublishedDetail: mockGetPublishedDetail };
});

import { useWorlds } from "@/hooks/useWorlds";
import {
  activateCompanion,
  deactivateCompanion,
  getMethodologyInventory,
  getMethodologyStatus,
} from "@/api/methodologies";
import type { Mock } from "vitest";
import type { WorldInfo } from "@/api/types";

const worlds: WorldInfo[] = [
  {
    name: "Vibrantes",
    path: "/vibrantes",
    lore_count: 77,
    character_count: 10, reference_count: 0,
  },
];

const status = {
  published: [
    {
      skill_id: "guided-character-v1",
      version: "1.2.0",
      name: "Guided character methodology",
      description: "",
      digest: "abc",
      published_at: "2026-01-01",
    },
  ],
  activations: {},
  drafts: [],
};

/** Published detail served by the center `MethodologyDetailView` once a row
 *  is selected (SC-SB-3.1). */
const detail = {
  skill_id: "guided-character-v1",
  version: "1.2.0",
  name: "Guided character methodology",
  description: "",
  digest: "abc",
  published_at: "2026-01-01",
  phases: [],
  language: "es",
  source: "# Guided character\n\nContenido publicado.",
  taller: "Mundo",
  etiquetas: [],
  parent_skill_id: null,
  parent_version: null,
};

function renderToolWorkshop() {
  return render(
    <MemoryRouter initialEntries={["/taller-herramientas"]}>
      <Routes>
        <Route path="/taller-herramientas" element={<ToolWorkshop />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ToolWorkshop", () => {
  beforeEach(() => {
    window.localStorage.clear();
    (useWorlds as Mock).mockReturnValue({
      worlds,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    (getMethodologyStatus as Mock).mockResolvedValue(status);
    (getMethodologyInventory as Mock).mockResolvedValue({ items: [] });
    (activateCompanion as Mock).mockResolvedValue({
      world: "Vibrantes",
      companion: {
        world: "Vibrantes",
        skill_id: "guided-character-v1",
        version: "1.2.0",
        description: "",
        activated_at: "2026-01-01",
      },
    });
    mockGetPublishedDetail.mockReset();
    mockGetPublishedDetail.mockResolvedValue(detail);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the shared header, exactly two tabs, and the methodology library", async () => {
    renderToolWorkshop();

    // REQ-TAB-1 (SC-TAB-1.1): exactly 2 top-level tabs; the previous
    // "Biblioteca global" tab no longer exists (it became the lens toggle).
    expect(screen.getByRole("tab", { name: "Biblioteca" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Crear skill" })).toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "Biblioteca global" }),
    ).not.toBeInTheDocument();

    // REQ-TAB-2 (SC-TAB-2.1): the page header has no <h1> — the subtitle
    // and the tablist live in the shared ToolWorkshopHeader.
    expect(
      screen.queryByRole("heading", { name: "Taller de Herramientas" }),
    ).not.toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
  });

  it("gates chat actions on the world chosen in the selector", async () => {
    const user = userEvent.setup();
    renderToolWorkshop();

    // No world selected → selecting a row shows the right panel with a
    // disabled "Añadir al chat" action.
    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    await user.click(screen.getByText("Guided character methodology"));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Añadir al chat" }),
      ).toBeDisabled();
    });

    // The selectors now live in the EditorLayout sidebar header (SC-SB-1.1) —
    // still reachable through the top-level queries.
    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("option", { name: "Vibrantes" }));
    // Selecting a different world asks for confirmation before applying
    await user.click(screen.getByRole("button", { name: "Cambiar" }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Añadir al chat" }),
      ).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "Añadir al chat" }));

    await waitFor(() => {
      expect(activateCompanion).toHaveBeenCalledWith(
        "Vibrantes",
        "guided-character-v1",
        "1.2.0",
      );
    });
  });

  it("adopts the Navbar-persisted world on first render and follows live switches", async () => {
    // The right panel's chat target must reflect the persisted world
    // immediately, without a manual switch.
    window.localStorage.setItem(ACTIVE_WORLD_STORAGE_KEY, "Vibrantes");
    const user = userEvent.setup();
    renderToolWorkshop();

    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    await user.click(screen.getByText("Guided character methodology"));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Añadir al chat" }),
      ).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "Añadir al chat" }));
    await waitFor(() => {
      expect(activateCompanion).toHaveBeenCalledWith(
        "Vibrantes",
        "guided-character-v1",
        "1.2.0",
      );
    });

    // Live sync: a Navbar switch (storage write + custom event) follows the
    // workshop without another manual selection.
    vi.mocked(activateCompanion).mockClear();
    setCurrentWorld("OtroMundo");
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Añadir al chat" }),
      ).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "Añadir al chat" }));
    await waitFor(() => {
      expect(activateCompanion).toHaveBeenCalledWith(
        "OtroMundo",
        "guided-character-v1",
        "1.2.0",
      );
    });
  });

  it("removes a skill from the chat and refetches status", async () => {
    window.localStorage.setItem(ACTIVE_WORLD_STORAGE_KEY, "Vibrantes");
    (getMethodologyStatus as Mock).mockResolvedValue({
      ...status,
      companions: {
        Vibrantes: [
          {
            world: "Vibrantes",
            skill_id: "guided-character-v1",
            version: "1.2.0",
            description: "",
            activated_at: "2026-01-01",
          },
        ],
      },
    });
    (deactivateCompanion as Mock).mockResolvedValue({ world: "Vibrantes" });
    const user = userEvent.setup();
    renderToolWorkshop();

    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    await user.click(screen.getByText("Guided character methodology"));
    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: "Quitar del chat" })[0],
      ).toBeEnabled();
    });
    (getMethodologyStatus as Mock).mockClear();

    await user.click(
      screen.getAllByRole("button", { name: "Quitar del chat" })[0],
    );
    await waitFor(() => {
      expect(deactivateCompanion).toHaveBeenCalledWith(
        "Vibrantes",
        "guided-character-v1",
      );
    });
    // The shared status refetch keeps the tree and the right panel in sync.
    await waitFor(() => {
      expect(getMethodologyStatus).toHaveBeenCalled();
    });
  });

  it("updates a drifted chat companion to the published version", async () => {
    window.localStorage.setItem(ACTIVE_WORLD_STORAGE_KEY, "Vibrantes");
    (getMethodologyStatus as Mock).mockResolvedValue({
      ...status,
      companions: {
        Vibrantes: [
          {
            world: "Vibrantes",
            skill_id: "guided-character-v1",
            version: "1.0.0",
            description: "",
            activated_at: "2026-01-01",
          },
        ],
      },
    });
    (activateCompanion as Mock).mockResolvedValue({ world: "Vibrantes" });
    const user = userEvent.setup();
    renderToolWorkshop();

    const update = await screen.findByRole("button", {
      name: "Actualizar chat",
    });
    await user.click(update);

    await waitFor(() => {
      expect(activateCompanion).toHaveBeenCalledWith(
        "Vibrantes",
        "guided-character-v1",
        "1.2.0",
      );
    });
    await waitFor(() => {
      expect(getMethodologyStatus).toHaveBeenCalled();
    });
  });

  it("shows an honest loading state while worlds load", () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: true,
      error: null,
      mutate: vi.fn(),
    });

    renderToolWorkshop();
    // Both the EditorLayout body and the sidebar tree can spin while their
    // independent fetches are in flight — at least one honest spinner shows.
    expect(
      screen.getAllByRole("status", { name: "Cargando" }).length,
    ).toBeGreaterThan(0);
  });

  it("shows an honest error state when worlds fail to load", () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: false,
      error: new Error("boom"),
      mutate: vi.fn(),
    });

    renderToolWorkshop();
    expect(
      screen.getByText(/No se pudo cargar la lista de mundos/),
    ).toBeInTheDocument();
  });

  it("still shows publications but forbids chat actions when no worlds exist", async () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    const user = userEvent.setup();

    renderToolWorkshop();

    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    await user.click(screen.getByText("Guided character methodology"));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Añadir al chat" }),
      ).toBeDisabled();
    });
    expect(
      screen.getByText(/No hay mundos disponibles/),
    ).toBeInTheDocument();
  });

  it("renders the taller selector with the default Taller de Mundo", () => {
    renderToolWorkshop();

    // Default active taller (REQ-TRE-1 S1) displayed via OPERATIONAL_TALLER_LABELS.
    expect(
      screen.getByRole("button", { name: "Taller de Mundo" }),
    ).toBeInTheDocument();
  });

  it("offers exactly the operational taller options in the selector (OC-2 S4)", async () => {
    const user = userEvent.setup();
    renderToolWorkshop();

    await user.click(screen.getByRole("button", { name: "Taller de Mundo" }));
    const options = screen.getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "Taller de Mundo",
      "Taller de Ideas",
    ]);
    expect(options).toHaveLength(OPERATIONAL_TALLERES.length);
    expect(
      screen.queryByRole("option", { name: "Taller de Herramientas" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Sin taller" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Todos" }),
    ).not.toBeInTheDocument();
  });

  it("remembers the last selected taller across visits (OC-3 S2)", () => {
    window.localStorage.setItem(ACTIVE_TALLER_STORAGE_KEY, "Ideas");
    renderToolWorkshop();

    // A valid stored short key is preserved: the trigger shows the Ideas
    // label and the tree computes for the Ideas context.
    expect(
      screen.getByRole("button", { name: "Taller de Ideas" }),
    ).toBeInTheDocument();
  });

  it("recomputes the tree when the taller selector changes (REQ-TRE-1 S2)", async () => {
    const user = userEvent.setup();
    const multiTallerStatus = {
      published: [
        {
          skill_id: "mundo-core",
          version: "1.0.0",
          name: "Mundo core skill",
          description: "",
          digest: "m",
          published_at: "2026-01-01",
          taller: "Mundo",
          talleres_compatibles: [],
        },
        {
          skill_id: "ideas-core",
          version: "1.0.0",
          name: "Ideas core skill",
          description: "",
          digest: "i",
          published_at: "2026-01-01",
          taller: "Ideas",
          talleres_compatibles: [],
        },
        {
          skill_id: "herramientas-core",
          version: "1.0.0",
          name: "Herramientas core skill",
          description: "",
          digest: "h",
          published_at: "2026-01-01",
          taller: "Herramientas",
          talleres_compatibles: [],
        },
      ],
      activations: {},
      drafts: [],
    };
    (getMethodologyStatus as Mock).mockResolvedValue(multiTallerStatus);

    renderToolWorkshop();

    // Default active taller is Mundo → the Mundo skill is part of its
    // context; the Ideas skill is not a transversal → hidden; the legacy
    // Herramientas-tagged record lands in the "Sin taller" bucket, NOT hidden
    // (REQ-TRE-5 S8 / OC-4 S3).
    await waitFor(() => {
      expect(screen.getByText("Mundo core skill")).toBeInTheDocument();
    });
    expect(screen.queryByText("Ideas core skill")).not.toBeInTheDocument();
    expect(screen.getByText("Herramientas core skill")).toBeInTheDocument();

    // Switch to Taller de Ideas → the contextual tree recomputes.
    await user.click(
      screen.getByRole("button", { name: "Taller de Mundo" }),
    );
    await user.click(screen.getByRole("option", { name: "Taller de Ideas" }));

    await waitFor(() => {
      expect(screen.getByText("Ideas core skill")).toBeInTheDocument();
    });
    expect(screen.queryByText("Mundo core skill")).not.toBeInTheDocument();
    expect(screen.getByText("Herramientas core skill")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Taller de Ideas" }),
    ).toBeInTheDocument();
  });

  it("shows the no-world prompt without touching the selection (SC-SB-5.3)", async () => {
    const user = userEvent.setup();
    renderToolWorkshop();

    // No world selected → the mi-mundo explorer shows the no-world prompt.
    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Elegí un mundo para poder activar versiones/),
    ).toBeInTheDocument();

    // Selection still works without a world...
    await user.click(screen.getByText("Guided character methodology"));
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Guided character methodology",
      }),
    ).toBeInTheDocument();

    // ...and the no-world state does NOT clear or mutate the selection.
    expect(
      screen.getByText(/Elegí un mundo para poder activar versiones/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Guided character methodology",
      }),
    ).toBeInTheDocument();
  });

  it("preserves the page-level selection across a lens switch (SC-SB-5.1)", async () => {
    const user = userEvent.setup();
    renderToolWorkshop();

    // Select M1 in "Mi mundo" — the center detail pane reflects it.
    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    await user.click(screen.getByText("Guided character methodology"));
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Guided character methodology",
      }),
    ).toBeInTheDocument();

    // Switch to "Catálogo total": the inventory explorer mounts (read GET)
    // and `selected` survives — the center pane still reflects M1.
    await user.click(screen.getByRole("tab", { name: "Catálogo total" }));
    await waitFor(() => {
      expect(getMethodologyInventory).toHaveBeenCalled();
    });
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Guided character methodology",
      }),
    ).toBeInTheDocument();

    // Switch back — selection preserved again.
    await user.click(screen.getByRole("tab", { name: "Mi mundo" }));
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Guided character methodology",
      }),
    ).toBeInTheDocument();
  });

  it("preserves the page-level selection across a tab switch (SC-SB-5.2)", async () => {
    const user = userEvent.setup();
    renderToolWorkshop();

    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    await user.click(screen.getByText("Guided character methodology"));
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Guided character methodology",
      }),
    ).toBeInTheDocument();

    // Switch to "Crear skill" and back — selection restored.
    await user.click(screen.getByRole("tab", { name: "Crear skill" }));
    expect(
      screen.getByText(
        tEs("toolworkshop.subtitle.coCrear"),
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Biblioteca" }));
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Guided character methodology",
      }),
    ).toBeInTheDocument();
  });

  it("performs no API mutation when the lens is toggled (SC-LEN-1.4)", async () => {
    const user = userEvent.setup();
    renderToolWorkshop();

    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    // Baseline: the page-level status fetch happened on mount.
    expect(getMethodologyStatus).toHaveBeenCalled();
    (getMethodologyStatus as Mock).mockClear();
    (activateCompanion as Mock).mockClear();

    await user.click(screen.getByRole("tab", { name: "Catálogo total" }));
    await waitFor(() => {
      expect(getMethodologyInventory).toHaveBeenCalled();
    });
    await user.click(screen.getByRole("tab", { name: "Mi mundo" }));

    // Lens toggling is pure client-side state presentation: no status
    // refetch, no activation, no derivation — NO mutation of any kind.
    expect(getMethodologyStatus).not.toHaveBeenCalled();
    expect(activateCompanion).not.toHaveBeenCalled();
  });

  it("shows the Biblioteca subtitle in the taller view (UC-2 S1 / TAB-2 S1)", () => {
    renderToolWorkshop();

    // The default view is "taller" (Biblioteca tab): the shared header must
    // carry the exploration subtitle, exactly per spec UC-2 S1 / TAB-2 S1.
    expect(screen.getByRole("tab", { name: "Biblioteca" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.getByText(tEs("toolworkshop.subtitle.library")),
    ).toBeInTheDocument();
  });

  it("shows the Co-creador subtitle in the co-crear view (TAB-2 S2)", async () => {
    const user = userEvent.setup();
    renderToolWorkshop();

    await user.click(screen.getByRole("tab", { name: "Crear skill" }));

    expect(
      screen.getByText(
        tEs("toolworkshop.subtitle.coCrear"),
      ),
    ).toBeInTheDocument();
  });

  it("labels the top-level tablist with the library-views aria-label (TAB-1 S2)", () => {
    renderToolWorkshop();

    expect(
      screen.getByRole("tablist", {
        name: "Vistas de la biblioteca de herramientas",
      }),
    ).toBeInTheDocument();
  });

  it("labels the lens toggle with the library aria-label (LEN-1 S1)", () => {
    renderToolWorkshop();

    // LensToggle is the internal segmented control of the taller view; its
    // aria-label must reference the biblioteca, not the taller (spec LEN-1).
    expect(
      screen.getByRole("tablist", { name: "Lente de la biblioteca" }),
    ).toBeInTheDocument();
  });

  it("renders the Mundo/Taller control labels and the self-labeling lens toggle (UL-1 S1 / SB-1 S1)", async () => {
    renderToolWorkshop();

    // Let the initial status fetch settle so the assertions run inside act().
    await screen.findByText("Guided character methodology");

    // Mundo/Taller are dropdowns and keep a visible label; the lens toggle is
    // self-labeling (its segments state the lens), so it carries no heading —
    // only its accessible name.
    expect(screen.getByText("Mundo")).toBeInTheDocument();
    expect(screen.getByText("Taller")).toBeInTheDocument();
    expect(
      screen.getByRole("tablist", { name: "Lente de la biblioteca" }),
    ).toBeInTheDocument();
  });

  it("suppresses the World and Taller selectors in catalogo-total, keeping the lens toggle (UL-2 S1)", async () => {
    const user = userEvent.setup();
    renderToolWorkshop();

    // mi-mundo: Mundo + Taller labels and the self-labeling lens toggle.
    expect(screen.getByText("Mundo")).toBeInTheDocument();
    expect(screen.getByText("Taller")).toBeInTheDocument();
    expect(
      screen.getByRole("tablist", { name: "Lente de la biblioteca" }),
    ).toBeInTheDocument();

    // Switch to the read-only catalog lens (the empty inventory fixture).
    await user.click(screen.getByRole("tab", { name: "Catálogo total" }));
    await waitFor(() => {
      expect(getMethodologyInventory).toHaveBeenCalled();
    });

    // catalogo-total: WorldSelector and TallerSelector (and their labels) are
    // suppressed; the LensToggle escape hatch stays rendered (spec UL-2 S1).
    expect(screen.queryByText("Mundo")).not.toBeInTheDocument();
    expect(screen.queryByText("Taller")).not.toBeInTheDocument();
    expect(
      screen.getByRole("tablist", { name: "Lente de la biblioteca" }),
    ).toBeInTheDocument();
  });

  it("navigates from the empty-state CTA to the Crear skill tab (UL-5 S1)", async () => {
    const user = userEvent.setup();
    (getMethodologyStatus as Mock).mockResolvedValue({
      published: [],
      activations: {},
      drafts: [],
    });

    renderToolWorkshop();

    // Zero published skills in mi-mundo → the empty state offers the CTA.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Crear tu primera skill" }),
      ).toBeInTheDocument();
    });

    await user.click(
      screen.getByRole("button", { name: "Crear tu primera skill" }),
    );

    // The page switches to the "Crear skill" tab (spec UL-5 S1).
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Crear skill" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    });
    expect(
      screen.getByText(
        tEs("toolworkshop.subtitle.coCrear"),
      ),
    ).toBeInTheDocument();
  });

  it("adds a skill to the chat, refetches status and shows the latency notice (S5)", async () => {
    const user = userEvent.setup();
    renderToolWorkshop();

    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    // Select the world, then the published row, so the right panel renders.
    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("option", { name: "Vibrantes" }));
    await user.click(screen.getByRole("button", { name: "Cambiar" }));
    await user.click(screen.getByText("Guided character methodology"));
    const add = await screen.findByRole("button", { name: "Añadir al chat" });

    const statusCallsBefore = (getMethodologyStatus as Mock).mock.calls.length;
    await user.click(add);

    await waitFor(() => {
      expect(activateCompanion).toHaveBeenCalledWith(
        "Vibrantes",
        "guided-character-v1",
        "1.2.0",
      );
    });
    await waitFor(() => {
      expect((getMethodologyStatus as Mock).mock.calls.length).toBeGreaterThan(
        statusCallsBefore,
      );
    });
    // First-ever activation in the world → one-time latency notice.
    expect(
      await screen.findByText(
        /Las charlas de IA en este mundo pueden tardar un poco más/,
      ),
    ).toBeInTheDocument();
  });

  it("surfaces the Spanish error banner when adding to the chat fails (S5)", async () => {
    const user = userEvent.setup();
    (activateCompanion as Mock).mockRejectedValue(new Error("boom"));
    renderToolWorkshop();

    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("option", { name: "Vibrantes" }));
    await user.click(screen.getByRole("button", { name: "Cambiar" }));
    await user.click(screen.getByText("Guided character methodology"));
    await user.click(screen.getByRole("button", { name: "Añadir al chat" }));

    await waitFor(() => {
      expect(
        screen.getByText(/No se pudo actualizar la skill de metodología de chat/),
      ).toBeInTheDocument();
    });
  });
});