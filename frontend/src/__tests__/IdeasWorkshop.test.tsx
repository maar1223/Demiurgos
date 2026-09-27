import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { SWRConfig } from "swr";
import IdeasWorkshop from "@/pages/IdeasWorkshop";
import App from "@/App";
import * as ideasApi from "@/api/ideas";
import * as wikiApi from "@/api/wiki";
import type { FileNode } from "@/api/types";
import type { IdeaDetail } from "@/api/ideas";
import { useFileTree } from "@/hooks/useFileTree";
import { getErrorMessage } from "@/lib/utils";
import { DEFAULT_LOCALE } from "@/hooks/useAppLocale";
import { tEn, tEs } from "@/__tests__/i18nTestUtils";
import type { Mock } from "vitest";

vi.mock("@/api/ideas", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/ideas")>();
  return {
    ...actual,
    listIdeas: vi.fn(),
    getIdea: vi.fn(),
    getIdeaVersions: vi.fn(),
    createIdea: vi.fn(),
    updateIdea: vi.fn(),
    deleteIdea: vi.fn(),
    materializeIdea: vi.fn(),
    previewMaterialize: vi.fn(),
    previewMaterializeTarget: vi.fn(),
    exportIdeaDocx: vi.fn(),
    attachIdeaMedia: vi.fn(),
    listPendingCaptures: vi.fn(),
    confirmCapture: vi.fn(),
    discardCapture: vi.fn(),
  };
});

// The wiki module is spread so the REAL MarkdownViewer keeps working (its
// getMediaUrl import must stay live); only the gated-create seam is mocked.
vi.mock("@/api/wiki", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/wiki")>();
  return {
    ...actual,
    requestConfirmation: vi.fn(),
    createFileConfirmed: vi.fn(),
  };
});

vi.mock("@/hooks/useFileTree", () => ({
  useFileTree: vi.fn(),
}));

vi.mock("@/components/organisms/Navbar", () => ({
  Navbar: () => <div aria-label="navbar" />,
}));

vi.mock("@/components/organisms/AIAssistantSidebar", () => ({
  AIAssistantSidebar: () => <div data-testid="assistant-sidebar" />,
}));

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: () => ({
    worlds: [{ name: "vibrantes", path: "/vibrantes" }],
    isLoading: false,
    isValidating: false,
    error: null,
    mutate: vi.fn(),
  }),
}));

vi.mock("@/hooks/useAuthGate", () => ({
  useAuthGate: () => ({
    loading: false,
    needsLogin: false,
    authEnabled: false,
  }),
}));

vi.mock("@/hooks/useOnboardingGate", () => ({
  useOnboardingGate: () => ({ loading: false, needsOnboarding: false }),
}));

const listIdeasMock = vi.mocked(ideasApi.listIdeas);
const getIdeaMock = vi.mocked(ideasApi.getIdea);
const getIdeaVersionsMock = vi.mocked(ideasApi.getIdeaVersions);
const createIdeaMock = vi.mocked(ideasApi.createIdea);
const updateIdeaMock = vi.mocked(ideasApi.updateIdea);
const deleteIdeaMock = vi.mocked(ideasApi.deleteIdea);
const materializeIdeaMock = vi.mocked(ideasApi.materializeIdea);
const previewMaterializeMock = vi.mocked(ideasApi.previewMaterialize);
const previewMaterializeTargetMock = vi.mocked(
  ideasApi.previewMaterializeTarget,
);
const exportIdeaDocxMock = vi.mocked(ideasApi.exportIdeaDocx);
const attachIdeaMediaMock = vi.mocked(ideasApi.attachIdeaMedia);
const listPendingCapturesMock = vi.mocked(ideasApi.listPendingCaptures);
const confirmCaptureMock = vi.mocked(ideasApi.confirmCapture);
const discardCaptureMock = vi.mocked(ideasApi.discardCapture);
const requestConfirmationMock = vi.mocked(wikiApi.requestConfirmation);
const createFileConfirmedMock = vi.mocked(wikiApi.createFileConfirmed);
const useFileTreeMock = useFileTree as Mock;

const summary: ideasApi.IdeaSummary = {
  id: "a1",
  slug: "arquero-ciego",
  timestamp: "2026-08-25T15:00:00Z",
  updated_at: "2026-08-25T15:00:00Z",
  source: "manual",
  type: "personaje",
  title: "El Arquero Ciego",
  tags: ["arquero"],
  status: "fresh",
  used_in: [],
  based_on: null,
  media_path: null,
};

const detail: IdeaDetail = { ...summary, body: "Un arquero que no ve." };

const pendingCapture: ideasApi.PendingCapture = {
  capture_id: "cap-1",
  slug: "2026-08-27-idea-pendiente",
  raw_text: "Una idea que quedó en pausa.",
  created_at: "2026-08-27T13:00:00Z",
  event_ts: "",
  media_kind: "text",
};

/** Folder tree fixture for the mocked useFileTree hook (AD7 picker). */
const mockTreeNodes: FileNode[] = [
  {
    name: "sistema-stal",
    path: "sistema-stal",
    is_dir: true,
    children: [
      {
        name: "poderes",
        path: "sistema-stal/poderes",
        is_dir: true,
        children: [],
      },
      { name: "inicio.md", path: "sistema-stal/inicio.md", is_dir: false },
    ],
  },
  { name: "guerras", path: "guerras", is_dir: true, children: [] },
];

/** Full 200 preview envelope for the happy-path materialize tests. */
const previewResult: ideasApi.IdeaMaterializePreviewResult = {
  proposal_id: "materialize-abc",
  target: {
    world: "vibrantes",
    section: "lore",
    folder: "sistema-stal",
    slug: "arquero-ciego",
    path: "sistema-stal/arquero-ciego.md",
  },
  content:
    "---\ntype: concepto\n---\n# El arquero ciego\n\nUn arquero que no ve.",
  proposed_relations: [
    { target_id: "Vibrantes::Stal", title: "Stal", rel_type: "involucra" },
  ],
  discarded_relations: [{ target_id: "Fantasma", reason: "target_not_found" }],
};

/** Instant target-resolution result for step 1 of the two-step flow. */
const targetResult: ideasApi.IdeaMaterializeTarget = previewResult.target;

/**
 * Preview envelope for an idea that carries an image (CI-2). The body
 * references the FINAL world path (`media/…`, bytes copied only on confirm),
 * while `media.src` is the idea URL readable during preview.
 */
const previewWithMedia: ideasApi.IdeaMaterializePreviewResult = {
  ...previewResult,
  content:
    "---\ntype: concepto\n---\n# El arquero ciego\n\n![El arquero ciego](media/arquero-ciego.jpg)\n\nUn arquero que no ve.",
  media: {
    src: "/api/ideas/media/2026-08-28-524e8b9c9770.jpg",
    dest: "media/arquero-ciego.jpg",
  },
};

function renderPage() {
  // Fresh SWR cache per render — SWR's module-level cache would otherwise
  // leak stale list/detail responses between tests (order-dependent).
  return render(
    <MemoryRouter>
      <SWRConfig value={{ provider: () => new Map() }}>
        <IdeasWorkshop />
      </SWRConfig>
    </MemoryRouter>,
  );
}

/**
 * Drive the two-step flow to destination mode: open the picker, pick a world,
 * click "Previsualizar" (instant target resolution) and return the dialog.
 */
async function openDestinationDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
  await user.click(
    screen.getByRole("button", { name: tEs("ideas.materialize.button") }),
  );
  await user.selectOptions(
    screen.getByLabelText(tEs("ideas.materialize.worldLabel")),
    "vibrantes",
  );
  await user.click(
    screen.getByRole("button", { name: tEs("ideas.materialize.preview") }),
  );
  return screen.findByRole("dialog", { name: tEs("ideas.preview.title") });
}

/**
 * Drive the full flow to the generated preview dialog: render, select the
 * idea, open the picker, pick a world, resolve the target and generate.
 */
async function openGeneratedPreview(
  user: ReturnType<typeof userEvent.setup>,
  result: ideasApi.IdeaMaterializePreviewResult,
) {
  getIdeaMock.mockResolvedValue(detail);
  previewMaterializeTargetMock.mockResolvedValue(targetResult);
  previewMaterializeMock.mockResolvedValue(result);
  renderPage();
  await openDestinationDialog(user);
  await user.click(
    screen.getByRole("button", { name: tEs("ideas.materialize.generate") }),
  );
  return screen.findByRole("dialog", { name: tEs("ideas.preview.title") });
}

/**
 * Edit the materialize filename input and fire its ~400 ms resolve debounce.
 * Fake timers are scoped to the timer advance; real timers are restored so
 * Testing Library's async utilities can settle the resolve promise.
 */
function debouncedFilenameEdit(input: HTMLElement, value: string) {
  vi.useFakeTimers();
  try {
    fireEvent.change(input, { target: { value } });
    act(() => {
      vi.advanceTimersByTime(400);
    });
  } finally {
    vi.useRealTimers();
  }
}

/** jsdom lacks URL.createObjectURL; define it for the blob-download path. */
function stubObjectUrl() {
  const createObjectURL = vi.fn(() => "blob:mock");
  const revokeObjectURL = vi.fn();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: revokeObjectURL,
  });
  return { createObjectURL, revokeObjectURL };
}

function unstubObjectUrl() {
  const urlApi = URL as unknown as {
    createObjectURL?: unknown;
    revokeObjectURL?: unknown;
  };
  delete urlApi.createObjectURL;
  delete urlApi.revokeObjectURL;
}

/** ISO timestamps for the archived-version fixtures (DM-2 date label). */
const V1_DATE = "2026-08-25T15:00:00+00:00";
const V2_DATE = "2026-08-26T09:00:00+00:00";

/** The locale-aware `dd/mm/aaaa` label the UI renders for the es default. */
function esVersionDate(iso: string): string {
  return new Intl.DateTimeFormat("es", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(iso));
}

/** Open the `⋯` options menu for the selected idea. */
async function openActionsMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", {
      name: tEs("ideas.detail.actionsMenuAria"),
    }),
  );
  return screen.findByRole("menu", {
    name: tEs("ideas.detail.actionsMenuAria"),
  });
}

/** Expand the `Detalles de la idea` collapsible. */
async function expandDetails(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    screen.getByRole("button", { name: tEs("ideas.detail.detailsHeading") }),
  );
}

describe("IdeasWorkshop", () => {
  beforeEach(() => {
    listIdeasMock.mockReset();
    getIdeaMock.mockReset();
    getIdeaVersionsMock.mockReset();
    createIdeaMock.mockReset();
    updateIdeaMock.mockReset();
    deleteIdeaMock.mockReset();
    materializeIdeaMock.mockReset();
    previewMaterializeMock.mockReset();
    previewMaterializeTargetMock.mockReset();
    exportIdeaDocxMock.mockReset();
    attachIdeaMediaMock.mockReset();
    listPendingCapturesMock.mockReset();
    confirmCaptureMock.mockReset();
    discardCaptureMock.mockReset();
    requestConfirmationMock.mockReset();
    createFileConfirmedMock.mockReset();
    useFileTreeMock.mockReset();
    listIdeasMock.mockResolvedValue({ ideas: [summary], total: 1 });
    getIdeaVersionsMock.mockResolvedValue({ slug: "arquero-ciego", versions: [] });
    listPendingCapturesMock.mockResolvedValue({ captures: [], count: 0 });
    useFileTreeMock.mockReturnValue({
      nodes: mockTreeNodes,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the two-panel structure: filterable list + detail + assistant", async () => {
    renderPage();

    // Left panel: filter controls + idea list
    expect(screen.getByRole("heading", { name: "Ideas" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filtrar por tipo" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filtrar por estado" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filtrar por origen" })).toBeInTheDocument();
    // The list shows the human-readable title (falls back to slug).
    expect(await screen.findByRole("button", { name: /El Arquero Ciego/ })).toBeInTheDocument();

    // Right panel: persistent assistant (null-mundo)
    expect(screen.getByTestId("assistant-sidebar")).toBeInTheDocument();

    // Empty detail state before a selection
    expect(screen.getByText("Banco global de ideas")).toBeInTheDocument();
  });

  it("falls back to the slug when the title is empty (list + detail header)", async () => {
    const user = userEvent.setup();
    listIdeasMock.mockResolvedValue({
      ideas: [{ ...summary, title: "" }],
      total: 1,
    });
    getIdeaMock.mockResolvedValue({ ...detail, title: "" });
    renderPage();

    // List item primary line shows the slug when title is empty.
    expect(await screen.findByRole("button", { name: /arquero-ciego/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /arquero-ciego/ }));
    // Detail header falls back to the slug too.
    expect(
      await screen.findByRole("heading", { name: "arquero-ciego" }),
    ).toBeInTheDocument();
  });

  it("filters the list by type when the filter changes", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("button", { name: /El Arquero Ciego/ });

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Filtrar por tipo" }),
      "personaje",
    );

    await waitFor(() =>
      expect(listIdeasMock).toHaveBeenCalledWith({
        type: "personaje",
        status: undefined,
        source: undefined,
      }),
    );
  });

  it("filters the list when typing in the search box (title/slug/tags)", async () => {
    const user = userEvent.setup();
    listIdeasMock.mockResolvedValue({
      ideas: [
        summary,
        { ...summary, slug: "el-otro", title: "El Otro", tags: [], timestamp: "2026-08-20T10:00:00Z", updated_at: "2026-08-20T10:00:00Z" },
      ],
      total: 2,
    });
    renderPage();

    await screen.findByRole("button", { name: /El Arquero Ciego/ });
    expect(screen.getByRole("button", { name: /El Otro/ })).toBeInTheDocument();

    // "arquero" matches title/slug/tags of the first idea only.
    await user.type(screen.getByRole("textbox", { name: "Buscar ideas" }), "arquero");

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /El Otro/ })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /El Arquero Ciego/ })).toBeInTheDocument();
  });

  it("shows the no-match state when the search filters everything out", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("button", { name: /El Arquero Ciego/ });

    await user.type(screen.getByRole("textbox", { name: "Buscar ideas" }), "zzz");

    expect(await screen.findByText("No hay ideas que coincidan.")).toBeInTheDocument();
  });

  it("sorts by most recent by default (Recientes)", async () => {
    listIdeasMock.mockResolvedValue({
      ideas: [
        { ...summary, slug: "vieja", title: "Idea Vieja", timestamp: "2026-08-01T10:00:00Z", updated_at: "2026-08-01T10:00:00Z" },
        { ...summary, slug: "nueva", title: "Idea Nueva", timestamp: "2026-08-25T15:00:00Z", updated_at: "2026-08-26T09:00:00Z" },
      ],
      total: 2,
    });
    renderPage();

    const list = await screen.findByRole("list", { name: "Lista de ideas" });
    await waitFor(() => expect(within(list).getAllByRole("button")).toHaveLength(2));

    const buttons = within(list).getAllByRole("button");
    // Default "Recientes" uses the latest of created/updated → Idea Nueva first.
    expect(buttons[0].textContent).toContain("Idea Nueva");
    expect(buttons[1].textContent).toContain("Idea Vieja");
  });

  it("creates a manual idea from the form", async () => {
    const user = userEvent.setup();
    createIdeaMock.mockResolvedValue({ ...detail, slug: "nueva-idea" });
    renderPage();

    await user.click(screen.getByRole("button", { name: "Nueva idea" }));

    const form = screen.getByRole("group", { name: "Crear idea" });
    await user.type(within(form).getByLabelText("Slug"), "nueva-idea");
    await user.type(
      within(form).getByLabelText("Etiquetas (separadas por coma)"),
      "arquetipo",
    );
    await user.type(within(form).getByLabelText("Cuerpo"), "Una idea nueva.");
    await user.click(within(form).getByRole("button", { name: "Crear idea" }));

    await waitFor(() =>
      expect(createIdeaMock).toHaveBeenCalledWith({
        slug: "nueva-idea",
        type: "sin_clasificar",
        body: "Una idea nueva.",
        tags: ["arquetipo"],
      }),
    );
  });

  it("creates a manual idea with an optional title", async () => {
    const user = userEvent.setup();
    createIdeaMock.mockResolvedValue({ ...detail, slug: "prototipo", title: "Prototipo de diosa" });
    renderPage();

    await user.click(screen.getByRole("button", { name: "Nueva idea" }));

    const form = screen.getByRole("group", { name: "Crear idea" });
    await user.type(within(form).getByLabelText("Slug"), "prototipo");
    await user.type(within(form).getByLabelText("Título (opcional)"), "Prototipo de diosa");
    await user.type(within(form).getByLabelText("Cuerpo"), "Una idea nueva.");
    await user.click(within(form).getByRole("button", { name: "Crear idea" }));

    await waitFor(() =>
      expect(createIdeaMock).toHaveBeenCalledWith({
        slug: "prototipo",
        type: "sin_clasificar",
        body: "Una idea nueva.",
        tags: [],
        title: "Prototipo de diosa",
      }),
    );
  });

  it("loads the detail and creates the ficha through preview → gated confirm", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    previewMaterializeMock.mockResolvedValue(previewResult);
    requestConfirmationMock.mockResolvedValue({
      token: "token-1",
      expires_at: "2026-08-26T00:00:00Z",
      proposed_digest: "digest-1",
    });
    createFileConfirmedMock.mockResolvedValue({
      success: true,
      path: "lore/sistema-stal/arquero-ciego.md",
      index_status: "indexed",
      retryable: false,
    } as Awaited<ReturnType<typeof wikiApi.createFileConfirmed>> & {
      index_status?: string;
      retryable?: boolean;
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));

    expect(getIdeaMock).toHaveBeenCalledWith("arquero-ciego");
    expect(
      await screen.findByRole("heading", { name: "El Arquero Ciego" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Un arquero que no ve.")).toBeInTheDocument();

    // Open the picker and select a world + a folder from the tree.
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.button") }),
    );
    await user.selectOptions(
      screen.getByLabelText(tEs("ideas.materialize.worldLabel")),
      "vibrantes",
    );
    await user.click(screen.getByRole("button", { name: "sistema-stal" }));

    // Step 1: "Previsualizar" resolves the target instantly (no AI).
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.preview") }),
    );
    await waitFor(() =>
      expect(previewMaterializeTargetMock).toHaveBeenCalledWith("arquero-ciego", {
        world: "vibrantes",
        section: "personajes",
        folder: "sistema-stal",
      }),
    );

    // Step 2: the explicit generation posts the same picker payload.
    await user.click(
      await screen.findByRole("button", {
        name: tEs("ideas.materialize.generate"),
      }),
    );
    await waitFor(() =>
      expect(previewMaterializeMock).toHaveBeenCalledWith(
        "arquero-ciego",
        {
          world: "vibrantes",
          section: "personajes",
          folder: "sistema-stal",
          // The generation uses the same server-resolved filename.
          slug: "arquero-ciego",
        },
        expect.any(AbortSignal),
      ),
    );

    // Read-only dialog: content + relations render (AD8).
    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.preview.title"),
    });
    expect(
      within(dialog).getByRole("heading", { name: "El arquero ciego" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("involucra")).toBeInTheDocument();
    expect(within(dialog).getByText("Stal")).toBeInTheDocument();
    expect(within(dialog).getByText("Fantasma")).toBeInTheDocument();
    expect(within(dialog).getByText("target_not_found")).toBeInTheDocument();

    // Confirm issues the single-use token (kind=new, edit_id=proposal_id)
    // and creates through the gated pipeline with digest+token (R-IM-05).
    await user.click(
      within(dialog).getByRole("button", { name: tEs("ideas.preview.create") }),
    );

    await waitFor(() =>
      expect(requestConfirmationMock).toHaveBeenCalledWith(
        "vibrantes",
        "lore",
        "sistema-stal/arquero-ciego.md",
        {
          edit_id: "materialize-abc",
          kind: "new",
          proposed_content: previewResult.content,
        },
      ),
    );
    expect(createFileConfirmedMock).toHaveBeenCalledWith(
      "vibrantes",
      "lore",
      "sistema-stal/arquero-ciego.md",
      {
        content: previewResult.content,
        edit_id: "materialize-abc",
        proposed_digest: "digest-1",
        token: "token-1",
      },
    );

    // index_status from the create response is surfaced (R-IM-06).
    expect(
      await screen.findByText(
        tEs("ideas.materialize.toast.createdIndex", { status: "indexed" }),
      ),
    ).toBeInTheDocument();
  });

  it("renders the carried idea image from the idea URL while previewing (CI-2)", async () => {
    const user = userEvent.setup();
    const dialog = await openGeneratedPreview(user, previewWithMedia);

    // The not-yet-copied world path is substituted for display only, so the
    // preview image loads from the idea-bank URL instead of a broken world one.
    const image = within(dialog).getByRole("img", { name: "El arquero ciego" });
    expect(image.getAttribute("src")).toContain("/api/ideas/media/");
    expect(image.getAttribute("src")).not.toContain("media/arquero-ciego.jpg");
  });

  it("confirms with the original world-path content, not the display substitution (CI-2)", async () => {
    const user = userEvent.setup();
    requestConfirmationMock.mockResolvedValue({
      token: "token-media",
      expires_at: "2026-08-26T00:00:00Z",
      proposed_digest: "digest-media",
    });
    createFileConfirmedMock.mockResolvedValue({
      success: true,
      path: "lore/sistema-stal/arquero-ciego.md",
      index_status: "indexed",
      retryable: false,
    } as Awaited<ReturnType<typeof wikiApi.createFileConfirmed>> & {
      index_status?: string;
      retryable?: boolean;
    });
    const dialog = await openGeneratedPreview(user, previewWithMedia);

    await user.click(
      within(dialog).getByRole("button", { name: tEs("ideas.preview.create") }),
    );

    // The digest binds the previewed content, so confirm must carry the
    // unsubstituted `media/<dest>` reference byte-for-byte.
    await waitFor(() =>
      expect(requestConfirmationMock).toHaveBeenCalledWith(
        "vibrantes",
        "lore",
        "sistema-stal/arquero-ciego.md",
        {
          edit_id: "materialize-abc",
          kind: "new",
          proposed_content: previewWithMedia.content,
        },
      ),
    );
    expect(createFileConfirmedMock).toHaveBeenCalledWith(
      "vibrantes",
      "lore",
      "sistema-stal/arquero-ciego.md",
      {
        content: previewWithMedia.content,
        edit_id: "materialize-abc",
        proposed_digest: "digest-media",
        token: "token-media",
      },
    );
    expect(
      requestConfirmationMock.mock.calls[0][3].proposed_content,
    ).toContain("media/arquero-ciego.jpg");
  });

  it("preselects the section from the idea type (personaje → personajes) with override", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail); // type: personaje
    previewMaterializeMock.mockResolvedValue(previewResult);
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await user.click(screen.getByRole("button", { name: tEs("ideas.materialize.button") }));

    // personaje → personajes suggested (R-IM-01 scenario), author can change.
    const sectionSelect = screen.getByLabelText(tEs("ideas.materialize.sectionLabel"));
    expect(sectionSelect).toHaveValue("personajes");

    await user.selectOptions(sectionSelect, "referencias");
    expect(sectionSelect).toHaveValue("referencias");
  });

  it("suggests lore for a non-character idea type", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue({ ...detail, type: "concepto" });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await user.click(screen.getByRole("button", { name: tEs("ideas.materialize.button") }));

    expect(screen.getByLabelText(tEs("ideas.materialize.sectionLabel"))).toHaveValue("lore");
  });

  it("no longer renders the suggested-title field in the materialize picker (DM-1)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await user.click(screen.getByRole("button", { name: tEs("ideas.materialize.button") }));

    // The picker is open (world control present) but the removed
    // "Título sugerido (opcional)" input is gone: the idea title is the single
    // source of truth for the ficha name.
    expect(
      screen.getByLabelText(tEs("ideas.materialize.worldLabel")),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/Título sugerido/)).not.toBeInTheDocument();
    expect(document.querySelector("#materialize-title-hint")).toBeNull();
  });

  it("derives the destination file name from the idea title without a hint (DM-1)", async () => {
    const user = userEvent.setup();
    const silpah: IdeaDetail = {
      ...detail,
      slug: "silpah-lince-de-chaae",
      title: "Silpah — Lince de Chaae",
    };
    listIdeasMock.mockResolvedValue({ ideas: [silpah], total: 1 });
    getIdeaMock.mockResolvedValue(silpah);
    // The server derives the slug from the idea title. If the client still sent
    // a `title_hint`, this mock would echo it and the assertions below would
    // fail — so this proves the picker no longer sends one.
    previewMaterializeTargetMock.mockImplementation((_ideaSlug, input) => {
      const slug = input.title_hint ? "from-title-hint" : "silpah-lince-de-chaae";
      return Promise.resolve({
        ...targetResult,
        slug,
        path: `sistema-stal/${slug}.md`,
      });
    });
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: /Silpah — Lince de Chaae/ }),
    );
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.button") }),
    );
    await user.selectOptions(
      screen.getByLabelText(tEs("ideas.materialize.worldLabel")),
      "vibrantes",
    );
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.preview") }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.preview.title"),
    });
    // The payload carries no title_hint: the idea title drives the name.
    await waitFor(() =>
      expect(previewMaterializeTargetMock).toHaveBeenCalledWith(
        "silpah-lince-de-chaae",
        {
          world: "vibrantes",
          section: "personajes",
          folder: "",
        },
      ),
    );
    expect(
      within(dialog).getByLabelText(tEs("ideas.materialize.filenameLabel")),
    ).toHaveValue("silpah-lince-de-chaae");
    expect(
      within(dialog).getByText("sistema-stal/silpah-lince-de-chaae.md"),
    ).toBeInTheDocument();
  });

  it("shows the suggested slug when target resolution returns a 409 collision (AD5)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockRejectedValue({
      status: 409,
      detail: "El archivo ya existe",
      collision: {
        target: "lore/sistema-stal/arquero-ciego.md",
        suggested_slug: "arquero-ciego-2",
        suggested_target: "lore/sistema-stal/arquero-ciego-2.md",
      },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await user.click(screen.getByRole("button", { name: tEs("ideas.materialize.button") }));
    await user.selectOptions(screen.getByLabelText(tEs("ideas.materialize.worldLabel")), "vibrantes");

    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.preview") }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.preview.title"),
    });
    expect(
      within(dialog).getByText(tEs("ideas.preview.collisionTitle")),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("arquero-ciego-2")).toBeInTheDocument();
    expect(
      within(dialog).getByText("lore/sistema-stal/arquero-ciego-2.md"),
    ).toBeInTheDocument();
    // Collision mode is not a draft: no confirm button, no content editing,
    // and no generation (a new slug is required first).
    expect(
      within(dialog).queryByRole("button", { name: tEs("ideas.preview.create") }),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", {
        name: tEs("ideas.materialize.generate"),
      }),
    ).not.toBeInTheDocument();
    expect(previewMaterializeMock).not.toHaveBeenCalled();
  });

  it("reveals the destination path on Previsualizar without generating (WU-3 step 1)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    renderPage();

    const dialog = await openDestinationDialog(user);

    expect(
      within(dialog).getByText("sistema-stal/arquero-ciego.md"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: tEs("ideas.materialize.generate"),
      }),
    ).toBeInTheDocument();
    // Destination resolution never runs the (expensive) generation.
    expect(previewMaterializeMock).not.toHaveBeenCalled();
  });

  it("shows the progress dialog with honest copy while generating (WU-3 step 2)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    previewMaterializeMock.mockReturnValue(new Promise(() => {}));
    renderPage();

    await openDestinationDialog(user);
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.generate") }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.materialize.progressTitle"),
    });
    expect(
      within(dialog).getByText(tEs("ideas.materialize.progressBody")),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(tEs("ideas.materialize.elapsedLabel")),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        tEs("ideas.materialize.elapsedSeconds", { seconds: 0 }),
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: tEs("ideas.materialize.cancel") }),
    ).toBeInTheDocument();
    // No fake percentage and no confirm while the AI is still writing.
    expect(
      within(dialog).queryByRole("button", { name: tEs("ideas.preview.create") }),
    ).not.toBeInTheDocument();
  });

  it("advances the elapsed-seconds counter while generating (fake timers)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    previewMaterializeMock.mockReturnValue(new Promise(() => {}));
    renderPage();

    await openDestinationDialog(user);

    vi.useFakeTimers();
    try {
      fireEvent.click(
        screen.getByRole("button", { name: tEs("ideas.materialize.generate") }),
      );
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(
        screen.getByText(tEs("ideas.materialize.elapsedSeconds", { seconds: 1 })),
      ).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(4000);
      });
      expect(
        screen.getByText(tEs("ideas.materialize.elapsedSeconds", { seconds: 5 })),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("cancel aborts generation and returns to destination mode with no error (WU-3)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    previewMaterializeMock.mockImplementation(
      (_slug, _input, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener("abort", () => {
            const abortError = new Error("Aborted");
            abortError.name = "AbortError";
            reject(abortError);
          });
        }),
    );
    renderPage();

    await openDestinationDialog(user);
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.generate") }),
    );

    const progressDialog = await screen.findByRole("dialog", {
      name: tEs("ideas.materialize.progressTitle"),
    });
    await user.click(
      within(progressDialog).getByRole("button", {
        name: tEs("ideas.materialize.cancel"),
      }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.preview.title"),
    });
    expect(
      within(dialog).getByText("sistema-stal/arquero-ciego.md"),
    ).toBeInTheDocument();
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: tEs("ideas.materialize.generate"),
      }),
    ).toBeInTheDocument();
  });

  it("renders a generation error inside the dialog with retry available (WU-3)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    previewMaterializeMock.mockRejectedValue({ status: 500, detail: "boom" });
    renderPage();

    await openDestinationDialog(user);
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.generate") }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.preview.title"),
    });
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      getErrorMessage(500),
    );
    // The destination stays visible and the failure never leaks to a page
    // banner (the modal would hide it anyway).
    expect(
      within(dialog).getByText("sistema-stal/arquero-ciego.md"),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(
      within(dialog).getByRole("button", {
        name: tEs("ideas.materialize.generateAgain"),
      }),
    ).toBeInTheDocument();
  });

  it("reveals the generated content, relations and Crear ficha on success (WU-3)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    previewMaterializeMock.mockResolvedValue(previewResult);
    renderPage();

    await openDestinationDialog(user);
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.generate") }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.preview.title"),
    });
    expect(
      within(dialog).getByRole("heading", { name: "El arquero ciego" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("involucra")).toBeInTheDocument();
    expect(within(dialog).getByText("Stal")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: tEs("ideas.preview.create") }),
    ).toBeInTheDocument();
  });

  it("shows an editable filename field prefilled with the resolved slug (WU-7)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    renderPage();

    const dialog = await openDestinationDialog(user);
    const input = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );

    expect(input).toHaveValue("arquero-ciego");
    expect(
      within(dialog).getByText("sistema-stal/arquero-ciego.md"),
    ).toBeInTheDocument();
  });

  it("re-resolves the destination when the filename is edited (debounced, WU-7)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    renderPage();

    const dialog = await openDestinationDialog(user);
    const input = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );

    previewMaterializeTargetMock.mockResolvedValueOnce({
      ...targetResult,
      slug: "arquero-nuevo",
      path: "sistema-stal/arquero-nuevo.md",
    });

    debouncedFilenameEdit(input, "arquero-nuevo");

    await waitFor(() =>
      expect(
        within(dialog).getByText("sistema-stal/arquero-nuevo.md"),
      ).toBeInTheDocument(),
    );
    expect(previewMaterializeTargetMock).toHaveBeenLastCalledWith(
      "arquero-ciego",
      {
        world: "vibrantes",
        section: "personajes",
        folder: "",
        slug: "arquero-nuevo",
      },
    );
  });

  it("snaps the filename field to the server-normalized slug on blur (WU-7)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    renderPage();

    const dialog = await openDestinationDialog(user);
    const input = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );

    previewMaterializeTargetMock.mockResolvedValueOnce({
      ...targetResult,
      slug: "mi-nombre-normalizado",
      path: "sistema-stal/mi-nombre-normalizado.md",
    });

    vi.useFakeTimers();
    try {
      fireEvent.focus(input);
      fireEvent.change(input, { target: { value: "Mi Nombre Raro!" } });
      act(() => {
        vi.advanceTimersByTime(400);
      });
    } finally {
      vi.useRealTimers();
    }

    // The server-normalized path lands, but the focused field keeps what the
    // author typed until it loses focus.
    await waitFor(() =>
      expect(
        within(dialog).getByText("sistema-stal/mi-nombre-normalizado.md"),
      ).toBeInTheDocument(),
    );
    expect(input).toHaveValue("Mi Nombre Raro!");

    fireEvent.blur(input);
    expect(input).toHaveValue("mi-nombre-normalizado");
  });

  it("sends the edited filename slug with the generation payload (WU-7)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    previewMaterializeMock.mockResolvedValue(previewResult);
    renderPage();

    const dialog = await openDestinationDialog(user);
    const input = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );

    previewMaterializeTargetMock.mockResolvedValueOnce({
      ...targetResult,
      slug: "arquero-nuevo",
      path: "sistema-stal/arquero-nuevo.md",
    });

    debouncedFilenameEdit(input, "arquero-nuevo");
    await waitFor(() =>
      expect(
        within(dialog).getByText("sistema-stal/arquero-nuevo.md"),
      ).toBeInTheDocument(),
    );

    await user.click(
      within(dialog).getByRole("button", {
        name: tEs("ideas.materialize.generate"),
      }),
    );

    await waitFor(() =>
      expect(previewMaterializeMock).toHaveBeenCalledWith(
        "arquero-ciego",
        expect.objectContaining({ slug: "arquero-nuevo" }),
        expect.any(AbortSignal),
      ),
    );
  });

  it("applies the suggested filename on collision and clears it (WU-7)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    renderPage();

    const dialog = await openDestinationDialog(user);
    const input = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );

    previewMaterializeTargetMock
      .mockRejectedValueOnce({
        status: 409,
        detail: "El archivo ya existe",
        collision: {
          target: "personajes/sistema-stal/arquero-nuevo.md",
          suggested_slug: "arquero-nuevo-2",
          suggested_target: "personajes/sistema-stal/arquero-nuevo-2.md",
        },
      })
      .mockResolvedValueOnce({
        ...targetResult,
        slug: "arquero-nuevo-2",
        path: "sistema-stal/arquero-nuevo-2.md",
      });

    debouncedFilenameEdit(input, "arquero-nuevo");

    // Collision mode keeps the warning and blocks generation.
    await waitFor(() =>
      expect(
        screen.getByText(tEs("ideas.preview.collisionTitle")),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("arquero-nuevo-2")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: tEs("ideas.materialize.generate") }),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: tEs("ideas.materialize.useSuggestedName"),
      }),
    );

    await waitFor(() =>
      expect(
        screen.getByText("sistema-stal/arquero-nuevo-2.md"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(tEs("ideas.preview.collisionTitle")),
    ).not.toBeInTheDocument();
    expect(previewMaterializeTargetMock).toHaveBeenLastCalledWith(
      "arquero-ciego",
      {
        world: "vibrantes",
        section: "personajes",
        folder: "",
        slug: "arquero-nuevo-2",
      },
    );
  });

  it("keeps the filename field editable while a collision persists (WU-7b)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    renderPage();

    const dialog = await openDestinationDialog(user);
    const input = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );

    previewMaterializeTargetMock.mockRejectedValueOnce({
      status: 409,
      detail: "El archivo ya existe",
      collision: {
        target: "personajes/sistema-stal/arquero-nuevo.md",
        suggested_slug: "arquero-nuevo-2",
        suggested_target: "personajes/sistema-stal/arquero-nuevo-2.md",
      },
    });
    debouncedFilenameEdit(input, "arquero-nuevo");

    await waitFor(() =>
      expect(
        screen.getByText(tEs("ideas.preview.collisionTitle")),
      ).toBeInTheDocument(),
    );

    // The same field is still there, holding the colliding name, and editable.
    const collisionInput = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );
    expect(collisionInput).toHaveValue("arquero-nuevo");

    fireEvent.change(collisionInput, { target: { value: "otro-libre" } });
    expect(collisionInput).toHaveValue("otro-libre");
  });

  it("typing a free name clears the collision and reveals generation (WU-7b)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    renderPage();

    const dialog = await openDestinationDialog(user);
    const input = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );

    previewMaterializeTargetMock
      .mockRejectedValueOnce({
        status: 409,
        detail: "El archivo ya existe",
        collision: {
          target: "personajes/sistema-stal/arquero-nuevo.md",
          suggested_slug: "arquero-nuevo-2",
          suggested_target: "personajes/sistema-stal/arquero-nuevo-2.md",
        },
      })
      .mockResolvedValueOnce({
        ...targetResult,
        slug: "otro-libre",
        path: "sistema-stal/otro-libre.md",
      });
    debouncedFilenameEdit(input, "arquero-nuevo");

    await waitFor(() =>
      expect(
        screen.getByText(tEs("ideas.preview.collisionTitle")),
      ).toBeInTheDocument(),
    );

    const collisionInput = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );
    debouncedFilenameEdit(collisionInput, "otro-libre");

    await waitFor(() =>
      expect(
        screen.getByText("sistema-stal/otro-libre.md"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(tEs("ideas.preview.collisionTitle")),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: tEs("ideas.materialize.generate") }),
    ).toBeInTheDocument();
    expect(previewMaterializeTargetMock).toHaveBeenLastCalledWith(
      "arquero-ciego",
      {
        world: "vibrantes",
        section: "personajes",
        folder: "",
        slug: "otro-libre",
      },
    );
  });

  it("keeps the collision warning and the suggested name action while colliding (WU-7b)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    renderPage();

    const dialog = await openDestinationDialog(user);
    const input = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );

    previewMaterializeTargetMock.mockRejectedValueOnce({
      status: 409,
      detail: "El archivo ya existe",
      collision: {
        target: "personajes/sistema-stal/arquero-nuevo.md",
        suggested_slug: "arquero-nuevo-2",
        suggested_target: "personajes/sistema-stal/arquero-nuevo-2.md",
      },
    });
    debouncedFilenameEdit(input, "arquero-nuevo");

    await waitFor(() =>
      expect(
        screen.getByText(tEs("ideas.preview.collisionTitle")),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("arquero-nuevo-2")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: tEs("ideas.materialize.useSuggestedName"),
      }),
    ).toBeInTheDocument();
    // Generation stays blocked while the collision persists.
    expect(
      screen.queryByRole("button", { name: tEs("ideas.materialize.generate") }),
    ).not.toBeInTheDocument();
  });

  it("prefills the filename field with the colliding derived name on the first resolve (WU-7c)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockRejectedValueOnce({
      status: 409,
      detail: "El archivo ya existe",
      collision: {
        target: "personajes/sistema-stal/arquero-ciego.md",
        suggested_slug: "arquero-ciego-2",
        suggested_target: "personajes/sistema-stal/arquero-ciego-2.md",
      },
    });
    renderPage();

    const dialog = await openDestinationDialog(user);

    await waitFor(() =>
      expect(
        within(dialog).getByText(tEs("ideas.preview.collisionTitle")),
      ).toBeInTheDocument(),
    );
    // The derived name collided, so the field is prefilled with the taken
    // basename (without `.md`) instead of rendering empty.
    const input = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );
    expect(input).toHaveValue("arquero-ciego");
    // Warning and suggestion action remain available.
    expect(screen.getByText("arquero-ciego-2")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: tEs("ideas.materialize.useSuggestedName"),
      }),
    ).toBeInTheDocument();
  });

  it("ignores a stale target resolution that resolves after a newer one (WU-7)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValueOnce(targetResult);
    renderPage();

    const dialog = await openDestinationDialog(user);
    const input = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );

    let resolveA: (value: ideasApi.IdeaMaterializeTarget) => void = () => {};
    let resolveB: (value: ideasApi.IdeaMaterializeTarget) => void = () => {};
    previewMaterializeTargetMock
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveA = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveB = resolve;
          }),
      )
      .mockResolvedValue(targetResult);

    vi.useFakeTimers();
    try {
      fireEvent.change(input, { target: { value: "nombre-a" } });
      act(() => {
        vi.advanceTimersByTime(400);
      });
      fireEvent.change(input, { target: { value: "nombre-b" } });
      act(() => {
        vi.advanceTimersByTime(400);
      });
    } finally {
      vi.useRealTimers();
    }

    // B (newer) resolves first, A (older) resolves last and must not win.
    await act(async () => {
      resolveB({
        ...targetResult,
        slug: "nombre-b",
        path: "sistema-stal/nombre-b.md",
      });
    });
    await act(async () => {
      resolveA({
        ...targetResult,
        slug: "nombre-a",
        path: "sistema-stal/nombre-a.md",
      });
    });

    expect(
      within(dialog).getByText("sistema-stal/nombre-b.md"),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByText("sistema-stal/nombre-a.md"),
    ).not.toBeInTheDocument();
  });

  it("does not leak a previous filename edit into the next resolve (WU-7)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    // The mock echoes the requested slug, so a leaked edit would produce a
    // different prefilled value than the fresh derived resolve — the test
    // fails if resetFilenameState never runs.
    previewMaterializeTargetMock.mockImplementation((_ideaSlug, input) => {
      const name = input.slug?.trim() || targetResult.slug;
      return Promise.resolve({
        ...targetResult,
        slug: name,
        path: `sistema-stal/${name}.md`,
      });
    });
    renderPage();

    const dialog = await openDestinationDialog(user);
    const input = within(dialog).getByLabelText(
      tEs("ideas.materialize.filenameLabel"),
    );

    debouncedFilenameEdit(input, "otro-nombre");
    await waitFor(() =>
      expect(
        within(dialog).getByText("sistema-stal/otro-nombre.md"),
      ).toBeInTheDocument(),
    );

    // Close the destination step (it returns to the picker step), then
    // resolve again from the picker.
    await user.click(
      within(dialog).getAllByRole("button", {
        name: tEs("ideas.preview.close"),
      })[0],
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: tEs("ideas.preview.title") }),
      ).not.toBeInTheDocument(),
    );

    const callsBeforeReopen = previewMaterializeTargetMock.mock.calls.length;
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.preview") }),
    );

    const reopened = await screen.findByRole("dialog", {
      name: tEs("ideas.preview.title"),
    });
    expect(
      within(reopened).getByLabelText(tEs("ideas.materialize.filenameLabel")),
    ).toHaveValue("arquero-ciego");
    // The reopened resolve must not carry the discarded edit's slug.
    const reopenedCalls = previewMaterializeTargetMock.mock.calls.slice(
      callsBeforeReopen,
    );
    expect(
      reopenedCalls.some(([, reopenInput]) => reopenInput.slug === "otro-nombre"),
    ).toBe(false);
  });

  it("legacy fallback marks the idea as used without creating a ficha (R-IM-10)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    materializeIdeaMock.mockResolvedValue({
      ok: true,
      used_in: ["vibrantes"],
      canon_path: null,
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await user.click(screen.getByRole("button", { name: tEs("ideas.materialize.button") }));
    await user.selectOptions(screen.getByLabelText(tEs("ideas.materialize.worldLabel")), "vibrantes");

    await user.click(
      screen.getByRole("button", {
        name: tEs("ideas.materialize.markUsedOnly"),
      }),
    );

    await waitFor(() =>
      expect(materializeIdeaMock).toHaveBeenCalledWith(
        "arquero-ciego",
        "vibrantes",
      ),
    );
    // The legacy path never touches the preview pipeline.
    expect(previewMaterializeMock).not.toHaveBeenCalled();
  });

  it("renders the idea body as markdown with frontmatter hidden (R-1, S-1.1)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue({
      ...detail,
      body: "---\ntype: personaje\n---\n## Summary\n\nThis is a **test** idea.",
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));

    // Markdown structure renders (heading from `## Summary`).
    expect(
      await screen.findByRole("heading", { name: "Summary" }),
    ).toBeInTheDocument();
    // Raw markdown syntax must NOT leak.
    expect(screen.queryByText("**test**")).not.toBeInTheDocument();
    // YAML frontmatter must stay hidden.
    expect(screen.queryByText(/type: personaje/)).not.toBeInTheDocument();
  });

  it("renders embedded idea images from the media API (R-1, S-1.2)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue({
      ...detail,
      body: "---\nmedia_path: media/arquero-ciego.png\n---\n![idea image](/api/ideas/media/arquero-ciego.png)\n\nUn arquero ciego.",
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));

    // The /api/ path passes through as-is (no mundo prop → default <img>).
    expect(
      await screen.findByRole("img", { name: "idea image" }),
    ).toHaveAttribute("src", "/api/ideas/media/arquero-ciego.png");
    // Frontmatter (media_path line) stays hidden.
    expect(screen.queryByText(/media_path:/)).not.toBeInTheDocument();
  });

  it("edits the idea title from the `⋯` menu dialog (DM-2)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    updateIdeaMock.mockResolvedValue({ ...detail, title: "Nuevo Título" });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    // The title input no longer lives inline; it opens from the options menu.
    const menu = await openActionsMenu(user);
    await user.click(
      within(menu).getByRole("menuitem", { name: tEs("ideas.detail.titleHeading") }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.detail.titleHeading"),
    });
    const titleInput = within(dialog).getByPlaceholderText(
      "Sin título — se muestra el slug",
    );
    await user.clear(titleInput);
    await user.type(titleInput, "Nuevo Título");
    await user.click(
      within(dialog).getByRole("button", { name: tEs("ideas.detail.saveTitle") }),
    );

    await waitFor(() =>
      expect(updateIdeaMock).toHaveBeenCalledWith("arquero-ciego", { title: "Nuevo Título" }),
    );
  });

  it("reclassifies the idea type from the collapsible metadata section (DM-2)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    updateIdeaMock.mockResolvedValue({ ...detail, type: "concepto" });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    // Classification lives inside the default-collapsed details section.
    await expandDetails(user);
    await user.selectOptions(screen.getByLabelText("Tipo de la idea"), "concepto");
    await user.click(screen.getByRole("button", { name: "Guardar tipo" }));

    await waitFor(() =>
      expect(updateIdeaMock).toHaveBeenCalledWith("arquero-ciego", { type: "concepto" }),
    );
  });

  it("deletes the idea after confirmation", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    deleteIdeaMock.mockResolvedValue({ ok: true, slug: "arquero-ciego" });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    await user.click(screen.getByRole("button", { name: "Eliminar idea arquero-ciego" }));

    await waitFor(() => expect(deleteIdeaMock).toHaveBeenCalledWith("arquero-ciego"));
  });

  it("shows the version history inside the details section with readable labels (DM-2)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    getIdeaVersionsMock.mockResolvedValue({
      slug: "arquero-ciego",
      versions: [
        { version: 1, path: "/ideas/versions/arquero-ciego-v1.md", created_at: V1_DATE },
        { version: 2, path: "/ideas/versions/arquero-ciego-v2.md", created_at: V2_DATE },
      ],
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));

    expect(getIdeaVersionsMock).toHaveBeenCalledWith("arquero-ciego");
    await expandDetails(user);
    const section = await screen.findByRole("region", {
      name: "Historial de versiones",
    });
    // Rows are readable `Versión N · dd/mm/aaaa` labels.
    expect(
      within(section).getByText(
        `Versión 1 · ${esVersionDate(V1_DATE)}`,
      ),
    ).toBeInTheDocument();
    expect(
      within(section).getByText(
        `Versión 2 · ${esVersionDate(V2_DATE)}`,
      ),
    ).toBeInTheDocument();
    // The absolute disk path must NOT be rendered as text (DM-2).
    expect(
      within(section).queryByText("/ideas/versions/arquero-ciego-v1.md"),
    ).not.toBeInTheDocument();
    // The live frontmatter version never leaks as plain user text (R-1).
    expect(screen.queryByText(/version: \d/)).not.toBeInTheDocument();
  });

  it("keeps the copy-path capability as an icon-only action (DM-2)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    getIdeaVersionsMock.mockResolvedValue({
      slug: "arquero-ciego",
      versions: [
        { version: 1, path: "/ideas/versions/arquero-ciego-v1.md", created_at: V1_DATE },
      ],
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await expandDetails(user);

    const copy = await screen.findByRole("button", {
      name: tEs("ideas.detail.copyPathAria", { version: 1 }),
    });
    await user.click(copy);

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("/ideas/versions/arquero-ciego-v1.md"),
    );
    // The path is not visible as text; only the accessible label exposes it.
    expect(
      screen.queryByText("/ideas/versions/arquero-ciego-v1.md"),
    ).not.toBeInTheDocument();
  });

  it("shows the empty state when the idea has no archived versions", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    getIdeaVersionsMock.mockResolvedValue({ slug: "arquero-ciego", versions: [] });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));

    await expandDetails(user);
    const section = await screen.findByRole("region", {
      name: "Historial de versiones",
    });
    expect(
      within(section).getByText(/Sin versiones archivadas/),
    ).toBeInTheDocument();
  });

  it("shows the pending-queue counter in the header (S-8.1)", async () => {
    listPendingCapturesMock.mockResolvedValue({
      captures: [
        pendingCapture,
        { ...pendingCapture, capture_id: "cap-2", raw_text: "Segunda." },
        { ...pendingCapture, capture_id: "cap-3", raw_text: "Tercera." },
      ],
      count: 3,
    });
    renderPage();

    expect(
      await screen.findByText("Ideas por confirmar (3)"),
    ).toBeInTheDocument();
  });

  it("confirms a parked capture from the review panel (S-8.2)", async () => {
    const user = userEvent.setup();
    listPendingCapturesMock
      .mockResolvedValueOnce({ captures: [pendingCapture], count: 1 })
      .mockResolvedValue({ captures: [], count: 0 });
    confirmCaptureMock.mockResolvedValue({ ok: true });
    renderPage();

    // Review panel shows the parked capture with its raw text.
    expect(await screen.findByText(pendingCapture.raw_text)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Guardar como idea" }));

    await waitFor(() =>
      expect(confirmCaptureMock).toHaveBeenCalledWith(pendingCapture.capture_id),
    );
    // mutate() re-fetches the queue: the resolved capture leaves the panel.
    await waitFor(() =>
      expect(screen.queryByText(pendingCapture.raw_text)).not.toBeInTheDocument(),
    );
  });

  it("discards a parked capture from the review panel (S-8.3)", async () => {
    const user = userEvent.setup();
    listPendingCapturesMock
      .mockResolvedValueOnce({ captures: [pendingCapture], count: 1 })
      .mockResolvedValue({ captures: [], count: 0 });
    discardCaptureMock.mockResolvedValue({ ok: true });
    renderPage();

    expect(await screen.findByText(pendingCapture.raw_text)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Descartar" }));

    await waitFor(() =>
      expect(discardCaptureMock).toHaveBeenCalledWith(pendingCapture.capture_id),
    );
    await waitFor(() =>
      expect(screen.queryByText(pendingCapture.raw_text)).not.toBeInTheDocument(),
    );
  });

  it("`⋯` menu opens, lists the four items in order, and closes on Escape (DM-2)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    // The primary action is visible next to the menu trigger.
    expect(
      screen.getByRole("button", { name: tEs("ideas.materialize.button") }),
    ).toBeInTheDocument();

    const trigger = screen.getByRole("button", {
      name: tEs("ideas.detail.actionsMenuAria"),
    });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    const menu = await openActionsMenu(user);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    // Four items, in the approved order (Título · Imagen · ─── · DOCX · PDF).
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((item) => item.textContent),
    ).toEqual([
      tEs("ideas.detail.titleHeading"),
      tEs("ideas.detail.imageHeading"),
      tEs("ideas.detail.exportDocxAria"),
      tEs("ideas.detail.exportPdfAria"),
    ]);

    // The separator sits between `Imagen` and `Exportar idea a DOCX` (Fix 4).
    const separator = within(menu).getByRole("separator");
    expect(separator.previousElementSibling).toHaveTextContent(
      tEs("ideas.detail.imageHeading"),
    );
    expect(separator.nextElementSibling).toHaveTextContent(
      tEs("ideas.detail.exportDocxAria"),
    );

    // Escape closes the menu.
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("`⋯` menu closes on an outside click (DM-2)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    await openActionsMenu(user);
    await user.click(document.body);

    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
  });

  it("`Imagen` menu item opens the image dialog and attaches via the API (DM-2)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    attachIdeaMediaMock.mockResolvedValue({
      ...detail,
      media_path: "media/arquero-ciego.png",
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    const menu = await openActionsMenu(user);
    await user.click(
      within(menu).getByRole("menuitem", { name: tEs("ideas.detail.imageHeading") }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.detail.imageHeading"),
    });
    // The dialog states that attaching replaces + versions the idea.
    expect(
      within(dialog).getByText(tEs("ideas.detail.imageDialogReplaceNote")),
    ).toBeInTheDocument();

    const file = new File(["fakedata"], "img.png", { type: "image/png" });
    const input = dialog.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input as HTMLInputElement, {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(attachIdeaMediaMock).toHaveBeenCalledWith("arquero-ciego", file),
    );
  });

  it("`⋯` menu item exports the idea to DOCX (DM-2)", async () => {
    listIdeasMock.mockResolvedValue({ ideas: [summary], total: 1 });
    getIdeaMock.mockResolvedValue(detail);
    exportIdeaDocxMock.mockResolvedValue(
      new Blob(["docx-bytes"], {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      }),
    );
    const { createObjectURL, revokeObjectURL } = stubObjectUrl();

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    const menu = await openActionsMenu(user);
    await user.click(
      within(menu).getByRole("menuitem", {
        name: tEs("ideas.detail.exportDocxAria"),
      }),
    );

    // DOCX fetches the idea through the export endpoint and drives the
    // blob-download flow (createObjectURL → anchor click → revoke).
    await waitFor(() => {
      expect(exportIdeaDocxMock).toHaveBeenCalledWith("arquero-ciego");
    });
    expect(createObjectURL).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalled();

    unstubObjectUrl();
  });

  it("`⋯` menu item opens the ExportPdfDialog (mundo='') (DM-2)", async () => {
    listIdeasMock.mockResolvedValue({ ideas: [summary], total: 1 });
    getIdeaMock.mockResolvedValue(detail);

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    const menu = await openActionsMenu(user);
    await user.click(
      within(menu).getByRole("menuitem", {
        name: tEs("ideas.detail.exportPdfAria"),
      }),
    );

    // The dialog renders with the idea body; mundo="" keeps the absolute
    // /api/ideas/... image URLs untouched.
    expect(
      screen.getByRole("dialog", { name: /exportar ficha a pdf/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Un arquero que no ve.")).toBeInTheDocument();
  });

  it("details collapsible starts collapsed, toggles and exposes aria-expanded (DM-2)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    const toggle = screen.getByRole("button", {
      name: tEs("ideas.detail.detailsHeading"),
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Collapsed by default: the classification control is not rendered.
    expect(screen.queryByLabelText("Tipo de la idea")).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Tipo de la idea")).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Tipo de la idea")).not.toBeInTheDocument();
  });

  it("`Usar en un mundo` opens the materialize dialog in picker mode (DM-2)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.button") }),
    );

    // The picker is now the dialog's initial mode (no stacked modals).
    const picker = await screen.findByRole("dialog", {
      name: tEs("ideas.materialize.heading"),
    });
    expect(
      within(picker).getByLabelText(tEs("ideas.materialize.worldLabel")),
    ).toBeInTheDocument();
    expect(
      within(picker).getByRole("button", { name: tEs("ideas.materialize.preview") }),
    ).toBeInTheDocument();
    // Legacy fallback stays reachable in the picker step.
    expect(
      within(picker).getByRole("button", {
        name: tEs("ideas.materialize.markUsedOnly"),
      }),
    ).toBeInTheDocument();

    // Previsualizar advances the same dialog to destination mode.
    await user.selectOptions(
      within(picker).getByLabelText(tEs("ideas.materialize.worldLabel")),
      "vibrantes",
    );
    await user.click(
      within(picker).getByRole("button", { name: tEs("ideas.materialize.preview") }),
    );
    expect(
      await screen.findByRole("dialog", { name: tEs("ideas.preview.title") }),
    ).toBeInTheDocument();
  });

  // ── Fix 1 — modal-scoped failure surface ────────────────────────────────

  it("shows a title-save failure INSIDE the dialog and clears it on reopen (Fix 1)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    updateIdeaMock.mockRejectedValue({ status: 500, detail: "boom" });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    const menu = await openActionsMenu(user);
    await user.click(
      within(menu).getByRole("menuitem", { name: tEs("ideas.detail.titleHeading") }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.detail.titleHeading"),
    });

    const input = within(dialog).getByPlaceholderText(
      "Sin título — se muestra el slug",
    );
    await user.clear(input);
    await user.type(input, "Nuevo Título");
    await user.click(
      within(dialog).getByRole("button", { name: tEs("ideas.detail.saveTitle") }),
    );

    // Visible inside the modal, not hidden behind the overlay.
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      getErrorMessage(500),
    );
    // Retry stays available from where the author is.
    expect(
      within(dialog).getByRole("button", { name: tEs("ideas.detail.saveTitle") }),
    ).toBeInTheDocument();
    // Only one alert: the page banner never mirrors a modal-scoped failure.
    expect(screen.getAllByRole("alert")).toHaveLength(1);

    // Close + reopen clears the modal-scoped error.
    await user.click(
      within(dialog).getAllByRole("button", {
        name: tEs("ideas.preview.close"),
      })[0],
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: tEs("ideas.detail.titleHeading") }),
      ).not.toBeInTheDocument(),
    );
    const menuAgain = await openActionsMenu(user);
    await user.click(
      within(menuAgain).getByRole("menuitem", {
        name: tEs("ideas.detail.titleHeading"),
      }),
    );
    const reopened = await screen.findByRole("dialog", {
      name: tEs("ideas.detail.titleHeading"),
    });
    expect(within(reopened).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an image-attach failure INSIDE the dialog and keeps retry available (Fix 1)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    attachIdeaMediaMock.mockRejectedValue({
      status: 400,
      detail: "El archivo está vacío.",
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    const menu = await openActionsMenu(user);
    await user.click(
      within(menu).getByRole("menuitem", { name: tEs("ideas.detail.imageHeading") }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.detail.imageHeading"),
    });

    const file = new File(["fakedata"], "img.png", { type: "image/png" });
    const input = dialog.querySelector<HTMLInputElement>('input[type="file"]');
    fireEvent.change(input as HTMLInputElement, { target: { files: [file] } });

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      getErrorMessage(400, "El archivo está vacío."),
    );
    // The dialog stays open with the attach control so the author can retry.
    expect(
      within(dialog).getByText(tEs("ideas.detail.imageDialogReplaceNote")),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("shows a target-resolve failure INSIDE the materialize dialog (Fix 1)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockRejectedValue({ status: 500, detail: "boom" });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.button") }),
    );
    const picker = await screen.findByRole("dialog", {
      name: tEs("ideas.materialize.heading"),
    });
    await user.selectOptions(
      within(picker).getByLabelText(tEs("ideas.materialize.worldLabel")),
      "vibrantes",
    );
    await user.click(
      within(picker).getByRole("button", { name: tEs("ideas.materialize.preview") }),
    );

    expect(await within(picker).findByRole("alert")).toHaveTextContent(
      getErrorMessage(500),
    );
    // Still on the picker step; Previsualizar can be retried.
    expect(
      within(picker).getByRole("button", { name: tEs("ideas.materialize.preview") }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("shows a legacy mark-as-used failure INSIDE the picker dialog (Fix 1)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    materializeIdeaMock.mockRejectedValue({ status: 400, detail: "boom" });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.button") }),
    );
    const picker = await screen.findByRole("dialog", {
      name: tEs("ideas.materialize.heading"),
    });
    await user.selectOptions(
      within(picker).getByLabelText(tEs("ideas.materialize.worldLabel")),
      "vibrantes",
    );
    await user.click(
      within(picker).getByRole("button", {
        name: tEs("ideas.materialize.markUsedOnly"),
      }),
    );

    expect(await within(picker).findByRole("alert")).toHaveTextContent(
      getErrorMessage(400),
    );
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  // ── Fix 2 — single derived modal guard ──────────────────────────────────

  it("disables the `⋯` menu while each modal surface is open (Fix 2)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    const trigger = () =>
      screen.getByRole("button", { name: tEs("ideas.detail.actionsMenuAria") });

    // Title dialog.
    let menu = await openActionsMenu(user);
    await user.click(
      within(menu).getByRole("menuitem", { name: tEs("ideas.detail.titleHeading") }),
    );
    await screen.findByRole("dialog", { name: tEs("ideas.detail.titleHeading") });
    expect(trigger()).toBeDisabled();
    await user.click(
      screen.getAllByRole("button", { name: tEs("ideas.preview.close") })[0],
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: tEs("ideas.detail.titleHeading") }),
      ).not.toBeInTheDocument(),
    );

    // Image dialog.
    menu = await openActionsMenu(user);
    await user.click(
      within(menu).getByRole("menuitem", { name: tEs("ideas.detail.imageHeading") }),
    );
    await screen.findByRole("dialog", { name: tEs("ideas.detail.imageHeading") });
    expect(trigger()).toBeDisabled();
    await user.click(
      screen.getAllByRole("button", { name: tEs("ideas.preview.close") })[0],
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: tEs("ideas.detail.imageHeading") }),
      ).not.toBeInTheDocument(),
    );

    // Materialize dialog (picker step).
    await user.click(
      screen.getByRole("button", { name: tEs("ideas.materialize.button") }),
    );
    await screen.findByRole("dialog", { name: tEs("ideas.materialize.heading") });
    expect(trigger()).toBeDisabled();
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: tEs("ideas.materialize.heading") }),
      ).not.toBeInTheDocument(),
    );

    // PDF dialog.
    menu = await openActionsMenu(user);
    await user.click(
      within(menu).getByRole("menuitem", { name: tEs("ideas.detail.exportPdfAria") }),
    );
    await screen.findByRole("dialog", { name: /exportar ficha a pdf/i });
    expect(trigger()).toBeDisabled();
  });

  // ── Fix 3 — focus management + Escape parity ────────────────────────────

  it("moves focus into the title dialog and restores it to the trigger on Escape (Fix 3)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    const menu = await openActionsMenu(user);
    await user.click(
      within(menu).getByRole("menuitem", { name: tEs("ideas.detail.titleHeading") }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: tEs("ideas.detail.titleHeading"),
    });
    // Focus moved into the dialog on open.
    expect(document.activeElement).toBe(dialog);

    const trigger = screen.getByRole("button", {
      name: tEs("ideas.detail.actionsMenuAria"),
    });
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: tEs("ideas.detail.titleHeading") }),
      ).not.toBeInTheDocument(),
    );
    // Focus returns to the `⋯` trigger.
    expect(document.activeElement).toBe(trigger);
  });

  it("Escape returns the materialize dialog to the picker, then closes it (Fix 3)", async () => {
    getIdeaMock.mockResolvedValue(detail);
    previewMaterializeTargetMock.mockResolvedValue(targetResult);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    const openButton = screen.getByRole("button", {
      name: tEs("ideas.materialize.button"),
    });
    await user.click(openButton);

    const picker = await screen.findByRole("dialog", {
      name: tEs("ideas.materialize.heading"),
    });
    // Focus moved into the dialog on open.
    expect(document.activeElement).toBe(picker);

    await user.selectOptions(
      within(picker).getByLabelText(tEs("ideas.materialize.worldLabel")),
      "vibrantes",
    );
    await user.click(
      within(picker).getByRole("button", { name: tEs("ideas.materialize.preview") }),
    );
    await screen.findByRole("dialog", { name: tEs("ideas.preview.title") });

    // Escape from the destination step returns to the picker (step close).
    await user.keyboard("{Escape}");
    expect(
      await screen.findByRole("dialog", { name: tEs("ideas.materialize.heading") }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: tEs("ideas.preview.title") }),
    ).not.toBeInTheDocument();

    // Escape from the picker closes the whole flow and restores focus.
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: tEs("ideas.materialize.heading") }),
      ).not.toBeInTheDocument(),
    );
    expect(document.activeElement).toBe(openButton);
  });

  it("renders the materialize preview chrome in English for the en locale (UI-REQ-2)", async () => {
    // Seed the cached locale so the hook fallback resolves `en` (renderPage
    // has no LocaleProvider). Cleaned up so later tests keep the es default.
    window.localStorage.setItem(
      "demiurgos-locale",
      JSON.stringify({ ...DEFAULT_LOCALE, ui: "en" }),
    );
    try {
      const user = userEvent.setup();
      getIdeaMock.mockResolvedValue(detail);
      previewMaterializeTargetMock.mockResolvedValue(targetResult);
      previewMaterializeMock.mockResolvedValue(previewResult);
      renderPage();

      await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
      await user.click(
        screen.getByRole("button", { name: tEn("ideas.materialize.button") }),
      );
      await user.selectOptions(
        screen.getByLabelText(tEn("ideas.materialize.worldLabel")),
        "vibrantes",
      );
      await user.click(
        screen.getByRole("button", { name: tEn("ideas.materialize.preview") }),
      );

      // Destination mode carries the English generate action.
      await user.click(
        await screen.findByRole("button", {
          name: tEn("ideas.materialize.generate"),
        }),
      );

      const dialog = await screen.findByRole("dialog", {
        name: tEn("ideas.preview.title"),
      });
      expect(
        within(dialog).getByRole("button", { name: tEn("ideas.preview.create") }),
      ).toBeInTheDocument();
      // Both the header icon button and the footer button carry this label.
      expect(
        within(dialog).getAllByRole("button", { name: tEn("ideas.preview.close") })
          .length,
      ).toBeGreaterThan(0);
    } finally {
      window.localStorage.removeItem("demiurgos-locale");
    }
  });
});

describe("IdeasWorkshop route", () => {
  beforeEach(() => {
    listIdeasMock.mockReset();
    listIdeasMock.mockResolvedValue({ ideas: [], total: 0 });
    listPendingCapturesMock.mockReset();
    listPendingCapturesMock.mockResolvedValue({ captures: [], count: 0 });
    useFileTreeMock.mockReset();
    useFileTreeMock.mockReturnValue({
      nodes: mockTreeNodes,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders at /ideas inside the auth and first-run gates", async () => {
    window.history.pushState({}, "", "/ideas");
    render(<App />);

    // The lazy route resolves through the Suspense boundary.
    expect(
      await screen.findByRole("heading", { name: "Ideas" }),
    ).toBeInTheDocument();
  });
});