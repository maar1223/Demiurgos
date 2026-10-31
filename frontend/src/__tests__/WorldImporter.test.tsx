import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { Mock } from "vitest";
import WorldImporter from "@/pages/WorldImporter";
import { ApiError } from "@/api/types";
import type {
  ClassificationSuggestion,
  ImportApprovalResponse,
  ImportCandidate,
  ImportJob,
  ImportSuggestion,
  RelationshipSuggestion,
  VisionSuggestion,
} from "@/api/types";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

vi.mock("@/api/importer", () => ({
  createImportJob: vi.fn(),
  streamImportChunk: vi.fn(),
  streamImportFile: vi.fn(),
  analyzeImportJob: vi.fn(),
  getImportJob: vi.fn(),
  getImportReview: vi.fn(),
  listImportJobs: vi.fn(),
  approveImportGroups: vi.fn(),
  executeImport: vi.fn(),
  cancelImportJob: vi.fn(),
  resumeImportJob: vi.fn(),
  rollbackImportJob: vi.fn(),
  deleteImportJob: vi.fn(),
  postReviewDecisions: vi.fn(),
  IMPORT_CHUNK_BYTES: 512 * 1024,
  IMPORT_MAX_FILE_BYTES: 500 * 1024 * 1024,
  IMPORT_MAX_JOB_BYTES: 5 * 1024 * 1024 * 1024,
  IMPORT_SYSTEM_DIRS: [
    "_context",
    ".history",
    ".papelera",
    "relaciones",
    "canon",
    "conflictos",
    "propuestas",
  ],
}));

import { tEs } from "@/__tests__/i18nTestUtils";
import { useWorlds } from "@/hooks/useWorlds";
import {
  analyzeImportJob,
  approveImportGroups,
  cancelImportJob,
  createImportJob,
  deleteImportJob,
  executeImport,
  getImportReview,
  getImportJob,
  listImportJobs,
  postReviewDecisions,
  streamImportFile,
} from "@/api/importer";

const world = { name: "mundo", path: "/mundo", lore_count: 1, character_count: 0, reference_count: 0 };

function job(overrides: Partial<ImportJob> = {}): ImportJob {
  return {
    job_id: "job1",
    world: "mundo",
    owner_principal: "p",
    state: "review",
    source_kind: "loose",
    aggregate_uncompressed_bytes: 0,
    aggregate_compressed_bytes: 0,
    file_count: 1,
    revision: 1,
    error: "",
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-01-01T00:00:00",
    ...overrides,
  };
}

function candidate(overrides: Partial<ImportCandidate> = {}): ImportCandidate {
  return {
    candidate_id: "c1",
    job_id: "job1",
    world: "mundo",
    normalized_identity: "Planos",
    source_hash: "sha256:abc",
    provenance: {
      source_path: "carpeta/planos.md",
      source_kind: "loose",
      source_hash: "sha256:abc",
      heading_path: "## Ciudad Alta",
      source_sequence: 1,
      chunk_id: null,
      nearby_text_anchor: "las murallas",
      image_anchor: "",
      source_order: 0,
    },
    content_preview: "Las murallas de la Ciudad Alta…",
    // Importador-auto-frontmatter (Phase 4) — analyzed metadata. Default to
    // empty/no-analysis so existing assertions stay clean; per-test overrides
    // attach canonical identity, summaries, frontmatter, and media diagnostics.
    canonical_id: "",
    display_title: "",
    summary: "",
    frontmatter: null,
    media_diagnostics: [],
    status: "pending",
    okf_issues: [],
    size_bytes: 1024,
    images: [],
    merge: null,
    replacement: null,
    // Slice 2 — default to "no suggestions" so existing assertions stay
    // clean; per-test overrides attach enrichment payloads where relevant.
    enrichment_json: null,
    enrichment_status: "disabled",
    ...overrides,
  };
}

/** Wire the full analyze flow to land in the review step. */
function mockAnalyzeToReview(candidates: ImportCandidate[]) {
  (createImportJob as Mock).mockResolvedValue({ job: job({ state: "pending" }) });
  (streamImportFile as Mock).mockImplementation(
    async (
      _m: string,
      _j: string,
      file: File,
      _rel: string,
      onProgress?: (streamed: number, total: number) => void,
    ) => {
      onProgress?.(file.size, file.size);
      return file.size;
    },
  );
  (analyzeImportJob as Mock).mockResolvedValue({
    job: job({ state: "review" }),
    candidates: candidates.length,
  });
  (getImportReview as Mock).mockResolvedValue({
    job: job({ state: "review" }),
    digest: "digest1",
    candidates,
  });
}

function renderImporter() {
  return render(
    <MemoryRouter initialEntries={["/wiki/mundo/importer"]}>
      <Routes>
        <Route path="/wiki/:mundo/importer" element={<WorldImporter />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function selectFileAndAnalyze(fileName = "planos.md") {
  await screen.findByRole("heading", { name: "Importar contenido" });
  const input = screen.getByLabelText("Selección de fuentes");
  fireEvent.change(input, { target: { files: [new File(["abc"], fileName)] } });
  fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
  await screen.findByRole("heading", { name: tEs("importer.heading.review") });
}

describe("WorldImporter — accessible, preservation-first workflow (slice 3)", () => {
  beforeEach(() => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [world],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    // Default: no history. Slice 2 tests override per-case.
    (listImportJobs as Mock).mockResolvedValue({ jobs: [], next_cursor: null });
  });

  // The page persists the active job in sessionStorage for resume-after-
  // reload; tests must never inherit a job written by a previous test.
  afterEach(() => {
    window.sessionStorage.clear();
  });

  it("keeps the write action disabled until an explicit approval", async () => {
    mockAnalyzeToReview([candidate()]);
    renderImporter();

    // Select step: read-only action is labeled as such.
    const analyze = screen.getByRole("button", { name: /Analizar \(solo lectura\)/ });
    expect(analyze).toBeDisabled();

    await selectFileAndAnalyze();

    // Review step: approval is required and the write action does NOT
    // exist until an explicit approval binds the reviewed diagnosis.
    expect(
      screen.getByRole("button", { name: /Aprobar grupos seleccionados/ }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Importar" }),
    ).not.toBeInTheDocument();

    // Explicitly approve a group → the write action appears enabled.
    const approval: ImportApprovalResponse = {
      approval_id: "a1",
      token: "tok-1",
      digest: "digest1",
      expires_at: "2026-01-01T00:30:00",
    };
    (approveImportGroups as Mock).mockResolvedValue(approval);
    fireEvent.click(
      screen.getByRole("checkbox", { name: /Contenido de fichas/ }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Aprobar grupos seleccionados/ }),
    );

    await screen.findByText(/Aprobaste 1 grupo/);
    expect(screen.getByRole("button", { name: "Importar" })).toBeEnabled();
  });

  it("flags ambiguous image placements for review and excludes them from auto groups", async () => {
    mockAnalyzeToReview([
      candidate({
        images: [
          {
            gallery_asset_id: "g1",
            relative_media_path: "wiki/media/x.png#left",
            alt_text: "mapa",
            target_ficha: "",
            confidence: 0.4,
            placement_status: "ambiguous",
          },
        ],
      }),
    ]);
    renderImporter();
    await selectFileAndAnalyze();

    // Ambiguous placements are never auto-approved: they belong to the
    // explicit review group, not the contextual-images group.
    expect(
      screen.getByText(/Imágenes contextuales \(0\)/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Requiere tu decisión \(1\)/),
    ).toBeInTheDocument();
    expect(screen.getByText("requiere revisión")).toBeInTheDocument();

    // The review group is not selected by default.
    expect(
      screen.getByRole("checkbox", { name: /Requiere tu decisión/ }),
    ).not.toBeChecked();
    expect(
      screen.getByRole("button", { name: /Aprobar grupos seleccionados/ }),
    ).toBeDisabled();
  });

  it("surfaces DOCX position metadata and actionable warnings in image review (PR2)", async () => {
    mockAnalyzeToReview([
      candidate({
        images: [
          {
            gallery_asset_id: "g1",
            relative_media_path: "media/Enciclopedia/portada.png",
            alt_text: "retrato",
            target_ficha: "Origen",
            confidence: 1.0,
            placement_status: "proposed",
            document_order: 1,
            paragraph_index: 1,
            anchor_type: "inline",
            structural_path: "body/p[1]/r[0]/inline[0]",
            heading_path: "Origen",
            context_text: "La fundadora partió al exilio",
            warnings: [
              "header part 'word/_rels/header1.xml.rels' embeds 2 image(s) — headers are not supported; skipped",
            ],
          },
        ],
      }),
    ]);
    renderImporter();
    await selectFileAndAnalyze();

    // Source order, structural position, and anchor type are perceivable.
    expect(screen.getByLabelText("Orden de origen: 1")).toBeInTheDocument();
    expect(screen.getByText("alineada")).toBeInTheDocument();
    expect(
      screen.getByText("body/p[1]/r[0]/inline[0]"),
    ).toBeInTheDocument();
    expect(screen.getByText("Sección: Origen")).toBeInTheDocument();
    expect(
      screen.getByText(/Contexto: La fundadora partió al exilio/),
    ).toBeInTheDocument();

    // Warnings are actionable and exposed accessibly (labelled list).
    const warnings = screen.getByLabelText("Advertencias de imagen");
    expect(warnings).toBeInTheDocument();
    expect(
      within(warnings).getByText(/headers are not supported; skipped/),
    ).toBeInTheDocument();
  });

  it("renders placements without position data as before (legacy compatibility)", async () => {
    mockAnalyzeToReview([
      candidate({
        images: [
          {
            gallery_asset_id: "g1",
            relative_media_path: "img.png",
            alt_text: "foto",
            target_ficha: "",
            confidence: 1.0,
            placement_status: "proposed",
          },
        ],
      }),
    ]);
    renderImporter();
    await selectFileAndAnalyze();

    // No position metadata rendered, no anchor badge, no warnings block.
    expect(screen.getByText("img.png")).toBeInTheDocument();
    expect(screen.queryByText("alineada")).not.toBeInTheDocument();
    expect(screen.queryByText("anclada")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Advertencias de imagen"),
    ).not.toBeInTheDocument();
  });

  it("renders gallery-compatible Markdown and a live #align-size preview", async () => {
    mockAnalyzeToReview([
      candidate({
        images: [
          {
            gallery_asset_id: "g1",
            relative_media_path: "wiki/media/x.png#left",
            alt_text: "mapa",
            target_ficha: "ciudades/planos",
            confidence: 0.9,
            placement_status: "proposed",
          },
        ],
      }),
    ]);
    renderImporter();
    await selectFileAndAnalyze();

    // Exact picker-compatible Markdown line (keeps the #align-size suffix).
    expect(
      screen.getByText("![mapa](wiki/media/x.png#left)"),
    ).toBeInTheDocument();

    // Rendered previews (thumbnail + MarkdownViewer) resolve through the
    // media API on the CLEAN path — the #align-size suffix never leaks.
    await waitFor(() => {
      const previews = screen.getAllByAltText("mapa");
      expect(previews.length).toBeGreaterThan(0);
      for (const preview of previews) {
        expect(preview).toHaveAttribute(
          "src",
          "/api/mundo/media?path=wiki%2Fmedia%2Fx.png",
        );
      }
    });
  });

  it("announces progress through a polite aria-live region", async () => {
    (createImportJob as Mock).mockResolvedValue({ job: job({ state: "pending" }) });
    // The stream never resolves in this test so the analyzing panel (with
    // its live region) stays on screen long enough to be asserted.
    (streamImportFile as Mock).mockImplementation(
      async () => new Promise<number>(() => undefined),
    );
    renderImporter();

    await screen.findByRole("heading", { name: "Importar contenido" });
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, {
      target: { files: [new File(["abc"], "planos.md")] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));

    // The Spinner also exposes role="status" — pick the polite progress
    // region (the one carrying aria-live) and verify it announces the file.
    const status = (await screen.findAllByRole("status")).find(
      (el) => el.getAttribute("aria-live") === "polite",
    );
    expect(status).toBeTruthy();
    expect(status!.textContent).toMatch(/planos\.md/);
  });

  it("moves keyboard focus to the step heading after a transition", async () => {
    mockAnalyzeToReview([candidate()]);
    renderImporter();
    await selectFileAndAnalyze();

    expect(document.activeElement?.textContent).toContain(
      tEs("importer.heading.review"),
    );
  });

  it("shows an honest failure state — never a false success", async () => {
    (createImportJob as Mock).mockResolvedValue({ job: job({ state: "pending" }) });
    (streamImportFile as Mock).mockResolvedValue(3);
    (analyzeImportJob as Mock).mockResolvedValue({
      job: job({ state: "failed", error: "malformed provider output" }),
      candidates: 0,
    });
    renderImporter();

    await screen.findByRole("heading", { name: "Importar contenido" });
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, {
      target: { files: [new File(["abc"], "planos.md")] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));

    await screen.findByRole("heading", { name: "Resultado de la importación" });
    expect(screen.getByText("La importación no se completó")).toBeInTheDocument();
    expect(screen.queryByText("Importación completada")).not.toBeInTheDocument();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("malformed provider output");
  });

  it("cancel during analysis leaves canon untouched and offers resume", async () => {
    (createImportJob as Mock).mockResolvedValue({ job: job({ state: "pending" }) });
    (streamImportFile as Mock).mockImplementation(
      async (_m: string, _j: string) => new Promise<number>(() => undefined),
    );
    (cancelImportJob as Mock).mockResolvedValue({ job: job({ state: "cancelled" }) });
    renderImporter();

    await screen.findByRole("heading", { name: "Importar contenido" });
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, {
      target: { files: [new File(["abc"], "planos.md")] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));

    await screen.findByRole("heading", { name: "Analizando fuentes" });
    fireEvent.click(screen.getByRole("button", { name: /Cancelar análisis/ }));

    await screen.findByRole("heading", { name: "Resultado de la importación" });
    expect(screen.getByText("Importación cancelada")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Reanudar revisión/ }),
    ).toBeInTheDocument();
  });

  it("renders a section dropdown per selected file with the classifier options (BLOQUE 1 piece 1)", async () => {
    renderImporter();
    await screen.findByRole("heading", { name: "Importar contenido" });
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, {
      target: {
        files: [
          new File(["abc"], "planos.md"),
          new File(["def"], "personas.md"),
        ],
      },
    });

    const selects = await screen.findAllByRole("combobox");
    expect(selects).toHaveLength(2);
    const options = Array.from(selects[0].querySelectorAll("option")).map(
      (o) => o.value,
    );
    expect(options).toEqual(["lore", "personajes", "referencias"]);
    // ``sagas`` must NOT be offered (its retirement is a separate change).
    expect(options).not.toContain("sagas");
  });

  it("pre-fills the dropdown from the content heuristic (BLOQUE 1 piece 1)", async () => {
    renderImporter();
    await screen.findByRole("heading", { name: "Importar contenido" });
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, {
      target: {
        files: [new File(["El glosario de términos"], "referencias.md")],
      },
    });

    const dropdown = await screen.findByLabelText("Sección de referencias.md");
    await waitFor(() => expect(dropdown).toHaveValue("referencias"));
  });

  it("defaults the dropdown to lore when the content has no signal (BLOQUE 1 piece 1)", async () => {
    renderImporter();
    await screen.findByRole("heading", { name: "Importar contenido" });
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, {
      target: { files: [new File(["Un texto neutro"], "neutral.md")] },
    });

    const dropdown = await screen.findByLabelText("Sección de neutral.md");
    expect(dropdown).toHaveValue("lore");
  });

  it("keeps the author's manual override and sends it in the create body (BLOQUE 1 piece 1)", async () => {
    mockAnalyzeToReview([candidate()]);
    renderImporter();
    await screen.findByRole("heading", { name: "Importar contenido" });
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, {
      target: { files: [new File(["abc"], "planos.md")] },
    });

    const dropdown = await screen.findByLabelText("Sección de planos.md");
    fireEvent.change(dropdown, { target: { value: "personajes" } });
    expect(dropdown).toHaveValue("personajes");

    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });
    expect(createImportJob).toHaveBeenCalledWith(
      "mundo",
      expect.objectContaining({
        source_kind: "loose",
        files: ["planos.md"],
        sections: { "planos.md": "personajes" },
      }),
    );
  });

  it("sends the heuristic suggestion in the create body when the author keeps it (BLOQUE 1 piece 1)", async () => {
    mockAnalyzeToReview([candidate()]);
    renderImporter();
    await screen.findByRole("heading", { name: "Importar contenido" });
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, {
      target: { files: [new File(["El glosario"], "glosario.md")] },
    });

    const dropdown = await screen.findByLabelText("Sección de glosario.md");
    await waitFor(() => expect(dropdown).toHaveValue("referencias"));

    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });
    expect(createImportJob).toHaveBeenCalledWith(
      "mundo",
      expect.objectContaining({
        sections: { "glosario.md": "referencias" },
      }),
    );
  });
});

// ---------------------------------------------------------------------------
// Slice 2 — History endpoint + server-driven recovery (IM-2.5 / IM-2.7)
//
// The store-level contract lives in wiki/tests/test_import_store.py; here we
// pin what only the page can prove: history rendering, outage handling, the
// server-driven recovery flow from both sessionStorage and the history list.
// ---------------------------------------------------------------------------

describe("WorldImporter — history + recovery (slice 2)", () => {
  beforeEach(() => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [world],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    (listImportJobs as Mock).mockResolvedValue({ jobs: [], next_cursor: null });
  });

  afterEach(() => {
    window.sessionStorage.clear();
  });

  it("renders an empty state when the history is empty", async () => {
    renderImporter();
    await screen.findByRole("heading", { name: "Importar contenido" });
    expect(screen.getByTestId("history-empty")).toBeInTheDocument();
    expect(screen.getByText(/No hay importaciones previas/)).toBeInTheDocument();
  });

  it("renders each history row with date, state, candidate count and open action", async () => {
    // ``mockImplementation`` (not ``mockResolvedValueOnce``) so StrictMode's
    // double-mount of the initial fetch effect still gets a real response.
    (listImportJobs as Mock).mockImplementation(async () => ({
      jobs: [
        job({ job_id: "j1", state: "review", file_count: 5 }),
        job({ job_id: "j2", state: "completed", file_count: 0 }),
      ],
      next_cursor: null,
    }));

    renderImporter();
    await screen.findByRole("heading", { name: "Importar contenido" });

    const list = screen.getByTestId("history-list");
    expect(list).toBeInTheDocument();
    expect(list.children).toHaveLength(2);
    expect(screen.getByTestId("history-open-j1")).toBeInTheDocument();
    expect(screen.getByTestId("history-open-j2")).toBeInTheDocument();
    // The state badge label is honest — server enum, mapped to UI copy.
    expect(screen.getByText("en revisión")).toBeInTheDocument();
    expect(screen.getByText("completado")).toBeInTheDocument();
  });

  it("shows a stale indicator and retry button on outage, and clears it on success", async () => {
    // Initial fetch fails: the UI must surface the outage (banner + retry)
    // rather than silently dropping the user into an empty list.
    (listImportJobs as Mock).mockImplementation(async () => {
      throw new ApiError(0, "offline");
    });
    renderImporter();
    await screen.findByTestId("history-outage");
    expect(screen.getByText(/Datos en caché/)).toBeInTheDocument();
    // The empty list message must NOT render during outage — the user
    // sees "no se pudo actualizar", not "no hay historial" (which would
    // promote a connection error as a negative result).
    expect(screen.queryByTestId("history-empty")).not.toBeInTheDocument();

    // Retry succeeds: the banner clears and the list renders normally.
    (listImportJobs as Mock).mockImplementation(async () => ({
      jobs: [job({ job_id: "j1", state: "review" })],
      next_cursor: null,
    }));
    fireEvent.click(screen.getByRole("button", { name: /Reintentar/ }));
    await screen.findByTestId("history-open-j1");
    expect(screen.queryByTestId("history-outage")).not.toBeInTheDocument();
  });

  it("paginates via 'Cargar más' using the server cursor", async () => {
    // Cursor-driven mock: StrictMode's double mount of the initial effect
    // calls listImportJobs twice with no cursor; the click calls it once
    // with the server cursor.
    (listImportJobs as Mock).mockImplementation(
      async (_m: string, opts?: { cursor?: string | null }) => {
        if (opts?.cursor === "cursor-A") {
          return { jobs: [job({ job_id: "j3" })], next_cursor: null };
        }
        return {
          jobs: [job({ job_id: "j1" }), job({ job_id: "j2" })],
          next_cursor: "cursor-A",
        };
      },
    );

    renderImporter();
    await screen.findByTestId("history-open-j1");
    expect(screen.getByTestId("history-open-j2")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("history-load-more"));
    await screen.findByTestId("history-open-j3");
    // No more pages → button gone.
    expect(screen.queryByTestId("history-load-more")).not.toBeInTheDocument();
    // The cursor must be echoed back to the server untouched.
    expect(listImportJobs).toHaveBeenCalledWith(
      "mundo",
      expect.objectContaining({ cursor: "cursor-A" }),
    );
  });

  it("sessionStorage recovery surfaces a 404 and clears the stale pointer", async () => {
    window.sessionStorage.setItem(
      "demiurgos-importer-job:mundo",
      JSON.stringify({ jobId: "ghost", sourceKind: "loose" }),
    );
    (getImportJob as Mock).mockRejectedValueOnce(
      new ApiError(404, "not found"),
    );

    renderImporter();

    await screen.findByRole("heading", { name: "Importar contenido" });
    // The page must NOT silently swallow the 404: it tells the user the
    // saved job is gone and the local pointer is cleared.
    expect(
      screen.getByText(/ya no existe en el servidor/i),
    ).toBeInTheDocument();
    expect(window.sessionStorage.getItem("demiurgos-importer-job:mundo")).toBeNull();
  });

  it("'Open' from history restores a job in REVIEW state into the review step", async () => {
    (listImportJobs as Mock).mockImplementation(async () => ({
      jobs: [job({ job_id: "j-review", state: "review" })],
      next_cursor: null,
    }));
    (getImportReview as Mock).mockResolvedValue({
      job: job({ job_id: "j-review", state: "review" }),
      digest: "digest",
      candidates: [candidate({ candidate_id: "c-hist", job_id: "j-review" })],
    });

    renderImporter();
    await screen.findByTestId("history-open-j-review");
    fireEvent.click(screen.getByTestId("history-open-j-review"));

    // Drives the page to the review step with the server-side candidates.
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });
    expect(getImportReview).toHaveBeenCalledWith("mundo", "j-review");
  });

  it("'Open' from history surfaces a terminal job in the result step", async () => {
    (listImportJobs as Mock).mockImplementation(async () => ({
      jobs: [job({ job_id: "j-done", state: "completed" })],
      next_cursor: null,
    }));

    renderImporter();
    await screen.findByTestId("history-open-j-done");
    fireEvent.click(screen.getByTestId("history-open-j-done"));

    await screen.findByRole("heading", { name: "Resultado de la importación" });
    expect(screen.getByText("Importación completada")).toBeInTheDocument();
    // A terminal job must NOT keep the recovery pointer around.
    expect(window.sessionStorage.getItem("demiurgos-importer-job:mundo")).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Opción A — manual delete of terminal jobs (confirm-gated).
  // -------------------------------------------------------------------------

  it("shows an Eliminar button only for deletable history states", async () => {
    (listImportJobs as Mock).mockImplementation(async () => ({
      jobs: [
        job({ job_id: "j-completed", state: "completed" }),
        job({ job_id: "j-failed", state: "failed" }),
        job({ job_id: "j-empty-review", state: "review", file_count: 0 }),
        job({ job_id: "j-full-review", state: "review", file_count: 3 }),
        job({ job_id: "j-intaking", state: "intaking" }),
      ],
      next_cursor: null,
    }));

    renderImporter();
    await screen.findByTestId("history-delete-j-completed");
    // Deletable: completed, failed, empty review.
    expect(screen.getByTestId("history-delete-j-completed")).toBeInTheDocument();
    expect(screen.getByTestId("history-delete-j-failed")).toBeInTheDocument();
    expect(screen.getByTestId("history-delete-j-empty-review")).toBeInTheDocument();
    // NOT deletable: review with candidates, non-terminal states.
    expect(screen.queryByTestId("history-delete-j-full-review")).not.toBeInTheDocument();
    expect(screen.queryByTestId("history-delete-j-intaking")).not.toBeInTheDocument();
  });

  it("requires confirmation before deleting and then calls DELETE + reloads", async () => {
    (listImportJobs as Mock).mockImplementation(async () => ({
      jobs: [job({ job_id: "j1", state: "completed" })],
      next_cursor: null,
    }));
    (deleteImportJob as Mock).mockResolvedValue({ success: true });

    renderImporter();
    const delBtn = await screen.findByTestId("history-delete-j1");

    // No delete happens until the dialog is confirmed.
    fireEvent.click(delBtn);
    expect(deleteImportJob).not.toHaveBeenCalled();
    expect(
      screen.getByRole("dialog", { name: /Eliminar importación/i }),
    ).toBeInTheDocument();

    // Cancel closes without deleting.
    fireEvent.click(screen.getByRole("button", { name: /Cancelar/i }));
    expect(deleteImportJob).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("dialog", { name: /Eliminar importación/i }),
    ).not.toBeInTheDocument();

    // Reopen and confirm → DELETE called with the job id, history reloaded.
    fireEvent.click(screen.getByTestId("history-delete-j1"));
    // REQ-PIA-08: this deletion is irreversible, so its confirm action carries
    // the danger treatment instead of the primary style.
    const deleteConfirm = within(
      screen.getByRole("dialog", { name: /Eliminar importación/i }),
    ).getByRole("button", { name: "Eliminar" });
    expect(deleteConfirm.className).toContain("bg-status-error");
    expect(deleteConfirm.className).not.toContain("bg-action");
    fireEvent.click(deleteConfirm);
    await waitFor(() =>
      expect(deleteImportJob).toHaveBeenCalledWith("mundo", "j1"),
    );
    await waitFor(() => expect(listImportJobs).toHaveBeenCalled());
  });

  it("reloads and drops the local pointer when the deleted job was being viewed", async () => {
    // A job whose history row is also the currently open one (empty review).
    (listImportJobs as Mock).mockImplementation(async () => ({
      jobs: [job({ job_id: "j-empty", state: "review", file_count: 0 })],
      next_cursor: null,
    }));
    (getImportReview as Mock).mockResolvedValue({
      job: job({ job_id: "j-empty", state: "review", file_count: 0 }),
      digest: "digest",
      candidates: [],
    });
    (deleteImportJob as Mock).mockResolvedValue({ success: true });

    renderImporter();
    await screen.findByTestId("history-open-j-empty");
    fireEvent.click(screen.getByTestId("history-open-j-empty"));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    // Empty review shows the "Eliminar este job" button.
    fireEvent.click(screen.getByTestId("review-delete-job"));
    fireEvent.click(screen.getByRole("button", { name: "Eliminar" }));

    await waitFor(() =>
      expect(deleteImportJob).toHaveBeenCalledWith("mundo", "j-empty"),
    );
    // Returns to a fresh selection and clears the persisted pointer.
    await screen.findByRole("heading", { name: "Importar contenido" });
    expect(window.sessionStorage.getItem("demiurgos-importer-job:mundo")).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Slice 2 — Hermes advisory enrichment (opt-in, advisory only).
  // -------------------------------------------------------------------------

  function classificationSuggestion(
    overrides: Partial<ClassificationSuggestion> = {},
  ): ClassificationSuggestion & { __type__: "classification" } {
    return {
      id: "cls-1",
      candidate_id: "c1",
      type: "personaje",
      tags: ["mago"],
      confidence: 0.82,
      evidence: "Nombre propio y rasgos mágicos en el primer párrafo.",
      provenance: { provider: "hermes-gateway", model: "hermes-agent" },
      review_state: "pending",
      __type__: "classification",
      ...overrides,
    };
  }

  function relationshipSuggestion(
    overrides: Partial<RelationshipSuggestion> = {},
  ): RelationshipSuggestion & { __type__: "relationship" } {
    return {
      id: "rel-1",
      source_candidate_id: "c1",
      target_candidate_id: null,
      target_name: "Ciudad Alta",
      relationship_type: "habita-en",
      confidence: 0.71,
      evidence: "Menciones explícitas a la Ciudad Alta.",
      provenance: { provider: "hermes-gateway", model: "hermes-agent" },
      review_state: "pending",
      __type__: "relationship",
      ...overrides,
    };
  }

  // PR4 — vision suggestions ride in the same enrichment payload with
  // ``__type__: "vision"`` (server shape from PR3). The media path is the
  // spool-relative location; no thumbnail_url is servable during review.
  function visionSuggestion(
    overrides: Partial<VisionSuggestion> = {},
  ): VisionSuggestion & { __type__: "vision" } {
    return {
      id: "vision:abc",
      candidate_id: "c1",
      relative_media_path: "media/Enciclopedia/portada.png",
      description: "Retrato de la reina en claroscuro",
      verdict: "confirma",
      analysis: "La imagen coincide con la descripción del texto.",
      tags: ["retrato"],
      confidence: 0.0,
      provenance: { provider: "vision", capability: "multimodal" },
      evidence: "image:media/Enciclopedia/portada.png",
      review_state: "pending",
      __type__: "vision",
      ...overrides,
    };
  }

  /** Wire analyze→review for tests that need enrichment in the payload. */
  function mockAnalyzeWithEnrichment(
    candidates: ImportCandidate[],
    reviewEnrichmentStatus: "ok" | "no_suggestions" | "error" | "disabled" = "ok",
  ) {
    (createImportJob as Mock).mockResolvedValue({ job: job({ state: "pending" }) });
    (streamImportFile as Mock).mockImplementation(
      async (
        _m: string,
        _j: string,
        file: File,
        _rel: string,
        onProgress?: (streamed: number, total: number) => void,
      ) => {
        onProgress?.(file.size, file.size);
        return file.size;
      },
    );
    (analyzeImportJob as Mock).mockResolvedValue({
      job: job({ state: "review" }),
      candidates: candidates.length,
      enrichment_status: reviewEnrichmentStatus,
    });
    const suggestions: Record<string, ImportSuggestion[]> = {};
    for (const c of candidates) {
      suggestions[c.candidate_id] = c.enrichment_json ?? [];
    }
    (getImportReview as Mock).mockResolvedValue({
      job: job({ state: "review" }),
      digest: "digest1",
      candidates,
      enrichment_status: reviewEnrichmentStatus,
      suggestions,
    });
  }

  it("always sends the enrich flag (enrichment is not user-toggleable)", async () => {
    mockAnalyzeToReview([candidate()]);
    renderImporter();

    // There is no enrichment checkbox on the select step: enrichment always
    // runs (the graph needs the resulting type/relationships) and the user
    // cannot opt out by accident.
    expect(screen.queryByTestId("enrich-toggle")).not.toBeInTheDocument();

    await selectFileAndAnalyze();
    // The flag is explicit ``{enrich: true}`` — no toggle can send false.
    // Vision is a UX decision: never exposed, never requested.
    expect(analyzeImportJob).toHaveBeenCalledWith(
      "mundo",
      expect.any(String),
      { enrich: true, vision: false },
    );
  });

  it("renders advisory cards with provenance and confidence per suggestion", async () => {
    const enriched: ImportCandidate = candidate({
      enrichment_json: [
        classificationSuggestion(),
        relationshipSuggestion(),
      ],
      enrichment_status: "ok",
    });
    mockAnalyzeWithEnrichment([enriched]);

    renderImporter();
    await screen.findByRole("heading", { name: "Importar contenido" });
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, { target: { files: [new File(["abc"], "planos.md")] } });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    // Enrichment banner is shown when status is "ok".
    expect(screen.getByTestId("enrichment-banner")).toHaveAttribute(
      "data-enrichment-status",
      "ok",
    );

    // Both suggestion cards are present with their provenance + confidence.
    expect(screen.getByTestId("suggestion-cls-1")).toBeInTheDocument();
    expect(screen.getByTestId("suggestion-rel-1")).toBeInTheDocument();
    expect(screen.getByText(/confianza 82%/)).toBeInTheDocument();
    expect(screen.getByText(/confianza 71%/)).toBeInTheDocument();
    // Both suggestion cards carry the same provenance line; assert at
    // least one (not exactly one) is present so the test stays robust.
    expect(screen.getAllByText(/hermes-gateway/).length).toBeGreaterThan(0);
  });

  it("renders relationship suggestions with the readable name, not the hex id (target_name primary)", async () => {
    const enriched: ImportCandidate = candidate({
      enrichment_json: [
        relationshipSuggestion({
          target_candidate_id: "7d2078e270c244f78b6f740a517f2dc2",
          target_name: "Ciudad Alta",
        }),
      ],
      enrichment_status: "ok",
    });
    mockAnalyzeWithEnrichment([enriched]);

    renderImporter();
    await screen.findByRole("heading", { name: "Importar contenido" });
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, { target: { files: [new File(["abc"], "planos.md")] } });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    const card = screen.getByTestId("suggestion-rel-1");

    // The label prefers the readable name over the internal hex id.
    expect(card).toHaveTextContent("habita-en → Ciudad Alta");
    // The hex id must never be surfaced as the prominent relationship label.
    expect(card).not.toHaveTextContent("7d2078e270c244f78b6f740a517f2dc2");

    // The human-facing description (evidence) is the primary content.
    expect(card).toHaveTextContent("Menciones explícitas a la Ciudad Alta.");
  });

  it("falls back to the candidate id only when the readable name is blank", async () => {
    const enriched: ImportCandidate = candidate({
      enrichment_json: [
        relationshipSuggestion({
          target_candidate_id: "7d2078e270c244f78b6f740a517f2dc2",
          target_name: "   ",
        }),
      ],
      enrichment_status: "ok",
    });
    mockAnalyzeWithEnrichment([enriched]);

    renderImporter();
    await screen.findByRole("heading", { name: "Importar contenido" });
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, { target: { files: [new File(["abc"], "planos.md")] } });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    expect(screen.getByTestId("suggestion-rel-1")).toHaveTextContent(
      "habita-en → 7d2078e270c244f78b6f740a517f2dc2",
    );
  });

  it("approving a suggestion posts to decisions and binds the ID to execute (slice 2)", async () => {
    const enriched: ImportCandidate = candidate({
      enrichment_json: [classificationSuggestion({ id: "cls-1" })],
      enrichment_status: "ok",
    });
    mockAnalyzeWithEnrichment([enriched]);
    (postReviewDecisions as Mock).mockResolvedValue({ accepted: 1 });

    renderImporter();
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, { target: { files: [new File(["abc"], "planos.md")] } });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    // Approve the suggestion via the per-card button.
    fireEvent.click(screen.getByTestId("suggestion-approve-cls-1"));

    await waitFor(() => {
      expect(postReviewDecisions).toHaveBeenCalledWith(
        "mundo",
        expect.any(String),
        [{ suggestion_id: "cls-1", decision: "approve" }],
      );
    });

    // The summary surfaces the approved-IDs commitment so the reviewer
    // sees what the approval token will bind to.
    expect(screen.getByTestId("approved-suggestions-summary")).toHaveTextContent(
      "1 sugerencia aprobada",
    );

    // Approve the group → the suggestion_ids round-trip through approve
    // and execute (server-side they bind to the single-use token).
    const approval: ImportApprovalResponse = {
      approval_id: "a1",
      token: "tok-1",
      digest: "digest1",
      expires_at: "2026-01-01T00:30:00",
    };
    (approveImportGroups as Mock).mockResolvedValue(approval);
    (executeImport as Mock).mockResolvedValue({
      job: job({ state: "completed" }),
      outcomes: [],
    });

    fireEvent.click(
      screen.getByRole("checkbox", { name: /Contenido de fichas/ }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Aprobar grupos seleccionados/ }),
    );
    await waitFor(() => {
      expect(approveImportGroups).toHaveBeenCalledWith(
        "mundo",
        expect.any(String),
        ["fichas"],
        ["cls-1"],
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Importar" }));
    await waitFor(() => {
      expect(executeImport).toHaveBeenCalledWith(
        "mundo",
        expect.any(String),
        "digest1",
        "tok-1",
        ["cls-1"],
      );
    });
  });

  it("independent reject on one suggestion does not affect siblings (slice 2)", async () => {
    const enriched: ImportCandidate = candidate({
      enrichment_json: [
        classificationSuggestion({ id: "cls-keep" }),
        classificationSuggestion({ id: "cls-drop" }),
      ],
      enrichment_status: "ok",
    });
    mockAnalyzeWithEnrichment([enriched]);
    (postReviewDecisions as Mock).mockResolvedValue({ accepted: 1 });

    renderImporter();
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, { target: { files: [new File(["abc"], "planos.md")] } });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    fireEvent.click(screen.getByTestId("suggestion-reject-cls-drop"));

    await waitFor(() => {
      expect(postReviewDecisions).toHaveBeenCalledWith(
        "mundo",
        expect.any(String),
        [{ suggestion_id: "cls-drop", decision: "reject" }],
      );
    });

    // The sibling stays pending — independent decisions are per-suggestion.
    expect(screen.getByTestId("suggestion-cls-drop")).toHaveAttribute(
      "data-suggestion-state",
      "rejected",
    );
    expect(screen.getByTestId("suggestion-cls-keep")).toHaveAttribute(
      "data-suggestion-state",
      "pending",
    );

    // Approve the sibling → only its ID ends up in approvedSuggestionIds.
    fireEvent.click(screen.getByTestId("suggestion-approve-cls-keep"));
    await waitFor(() => {
      expect(postReviewDecisions).toHaveBeenCalledWith(
        "mundo",
        expect.any(String),
        [{ suggestion_id: "cls-keep", decision: "approve" }],
      );
    });
    expect(screen.getByTestId("approved-suggestions-summary")).toHaveTextContent(
      "1 sugerencia aprobada",
    );
  });

  it("renders vision suggestion cards with verdict, description, tags and advisory copy (PR4)", async () => {
    const enriched: ImportCandidate = candidate({
      enrichment_json: [
        classificationSuggestion(),
        visionSuggestion(),
      ],
      enrichment_status: "ok",
    });
    mockAnalyzeWithEnrichment([enriched]);
    renderImporter();
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, { target: { files: [new File(["abc"], "planos.md")] } });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    // The vision card renders inside the candidate detail with its own
    // section, alongside the text suggestion family.
    expect(screen.getByTestId("vision-suggestions-c1")).toBeInTheDocument();
    const card = screen.getByTestId("suggestion-vision:abc");
    expect(card).toHaveAttribute("data-suggestion-state", "pending");

    // Verdict badge + family badge + advisory copy.
    expect(screen.getByText("confirma")).toBeInTheDocument();
    expect(screen.getByText("visión")).toBeInTheDocument();
    expect(
      screen.getByText(/Imágenes analizadas con visión — orientativas/),
    ).toBeInTheDocument();

    // Description (alt-text), spool path, tags, provenance, evidence.
    expect(
      screen.getByText("Retrato de la reina en claroscuro"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("media/Enciclopedia/portada.png"),
    ).toBeInTheDocument();
    expect(screen.getByText("#retrato")).toBeInTheDocument();
    expect(screen.getByText(/Origen: vision/)).toBeInTheDocument();

    // Review-time images live in the spool (pre-gallery) — the card shows a
    // placeholder, never a broken <img>.
    expect(
      screen.getByLabelText("Imagen sin vista previa disponible"),
    ).toBeInTheDocument();

    // The text family still renders alongside (independent families).
    expect(screen.getByTestId("suggestion-cls-1")).toBeInTheDocument();
  });

  it("approving a vision suggestion posts the decision and binds the ID to execute (PR4)", async () => {
    const enriched: ImportCandidate = candidate({
      enrichment_json: [visionSuggestion()],
      enrichment_status: "ok",
    });
    mockAnalyzeWithEnrichment([enriched]);
    (postReviewDecisions as Mock).mockResolvedValue({ accepted: 1 });

    renderImporter();
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, { target: { files: [new File(["abc"], "planos.md")] } });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    // Approve the image via the per-card button (same decisions endpoint
    // as text suggestions — the vision id is just another suggestion id).
    fireEvent.click(screen.getByTestId("suggestion-approve-vision:abc"));

    await waitFor(() => {
      expect(postReviewDecisions).toHaveBeenCalledWith(
        "mundo",
        expect.any(String),
        [{ suggestion_id: "vision:abc", decision: "approve" }],
      );
    });
    expect(screen.getByTestId("suggestion-vision:abc")).toHaveAttribute(
      "data-suggestion-state",
      "approved",
    );
    expect(screen.getByTestId("approved-suggestions-summary")).toHaveTextContent(
      "1 sugerencia aprobada",
    );

    // The approved vision id round-trips through approve AND execute so the
    // executor registers the original in the gallery with alt-text.
    const approval: ImportApprovalResponse = {
      approval_id: "a1",
      token: "tok-1",
      digest: "digest1",
      expires_at: "2026-01-01T00:30:00",
    };
    (approveImportGroups as Mock).mockResolvedValue(approval);
    (executeImport as Mock).mockResolvedValue({
      job: job({ state: "completed" }),
      outcomes: [],
    });

    fireEvent.click(
      screen.getByRole("checkbox", { name: /Imágenes contextuales/ }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Aprobar grupos seleccionados/ }),
    );
    await waitFor(() => {
      expect(approveImportGroups).toHaveBeenCalledWith(
        "mundo",
        expect.any(String),
        ["imagenes"],
        ["vision:abc"],
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Importar" }));
    await waitFor(() => {
      expect(executeImport).toHaveBeenCalledWith(
        "mundo",
        expect.any(String),
        "digest1",
        "tok-1",
        ["vision:abc"],
      );
    });
  });

  it("rejecting a vision suggestion keeps it out of the approval commitment (PR4)", async () => {
    const enriched: ImportCandidate = candidate({
      enrichment_json: [
        visionSuggestion(),
        classificationSuggestion({ id: "cls-1" }),
      ],
      enrichment_status: "ok",
    });
    mockAnalyzeWithEnrichment([enriched]);
    (postReviewDecisions as Mock).mockResolvedValue({ accepted: 1 });

    renderImporter();
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, { target: { files: [new File(["abc"], "planos.md")] } });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    fireEvent.click(screen.getByTestId("suggestion-reject-vision:abc"));

    await waitFor(() => {
      expect(postReviewDecisions).toHaveBeenCalledWith(
        "mundo",
        expect.any(String),
        [{ suggestion_id: "vision:abc", decision: "reject" }],
      );
    });
    expect(screen.getByTestId("suggestion-vision:abc")).toHaveAttribute(
      "data-suggestion-state",
      "rejected",
    );
    // The text sibling stays pending — independent decisions.
    expect(screen.getByTestId("suggestion-cls-1")).toHaveAttribute(
      "data-suggestion-state",
      "pending",
    );
    // No approved suggestions → the summary stays hidden and no ID binds.
    expect(
      screen.queryByTestId("approved-suggestions-summary"),
    ).not.toBeInTheDocument();
  });

  it("shows the Hermes-unavailable banner when status is 'error' (fail-open)", async () => {
    mockAnalyzeWithEnrichment([candidate()], "error");
    renderImporter();
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, { target: { files: [new File(["abc"], "planos.md")] } });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    const banner = screen.getByTestId("enrichment-banner");
    expect(banner).toHaveAttribute("data-enrichment-status", "error");
    expect(banner).toHaveTextContent(/El asistente no respondió/);
    // Fail-open: analyze already succeeded — the page is still in review.
    expect(
      screen.getByRole("button", { name: /Aprobar grupos seleccionados/ }),
    ).toBeInTheDocument();
  });

  it("hides the enrichment banner when status is 'disabled' (legacy path)", async () => {
    mockAnalyzeWithEnrichment([candidate()], "disabled");
    renderImporter();
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, { target: { files: [new File(["abc"], "planos.md")] } });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    expect(screen.queryByTestId("enrichment-banner")).not.toBeInTheDocument();
  });

  it("reverts optimistic state when the decisions endpoint rejects (slice 2)", async () => {
    const enriched: ImportCandidate = candidate({
      enrichment_json: [classificationSuggestion({ id: "cls-1" })],
      enrichment_status: "ok",
    });
    mockAnalyzeWithEnrichment([enriched]);
    (postReviewDecisions as Mock).mockRejectedValueOnce(
      // Use a plain Error so importErrorMessage falls through to
      // ``err.message`` — the 409/422/500 cases in ``getErrorMessage``
      // overwrite the wire detail with a fixed copy.
      new Error("suggestion_digest_mismatch"),
    );

    renderImporter();
    const input = screen.getByLabelText("Selección de fuentes");
    fireEvent.change(input, { target: { files: [new File(["abc"], "planos.md")] } });
    fireEvent.click(screen.getByRole("button", { name: /Analizar/ }));
    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    fireEvent.click(screen.getByTestId("suggestion-approve-cls-1"));

    // Failure path: the card flips back to pending (server is the authority)
    // and the error banner surfaces the reason.
    await waitFor(() => {
      expect(screen.getByTestId("suggestion-cls-1")).toHaveAttribute(
        "data-suggestion-state",
        "pending",
      );
    });
    // The ErrorBanner renders role="alert"; assert the server's wire
    // detail round-trips into the banner copy.
    const alerts = screen.getAllByRole("alert");
    const alertTexts = alerts.map((a) => a.textContent ?? "");
    expect(
      alertTexts.some((t) => t.includes("suggestion_digest_mismatch")),
    ).toBe(true);
  });

  it("shows 'Continuar análisis' for an intaking job and skips create+stream", async () => {
    // Clear accumulated calls from prior tests so the assertion below is
    // scoped to THIS test's interactions only.
    vi.mocked(createImportJob).mockClear();
    vi.mocked(streamImportFile).mockClear();
    vi.mocked(analyzeImportJob).mockClear();
    vi.mocked(getImportReview).mockClear();

    // Simulate sessionStorage recovery of a job stuck in "intaking" state.
    window.sessionStorage.setItem(
      "demiurgos-importer-job:mundo",
      JSON.stringify({ jobId: "j-intaking", sourceKind: "loose" }),
    );
    (getImportJob as Mock).mockResolvedValue({
      job: job({ job_id: "j-intaking", state: "intaking" }),
    });
    // Wire analyze → review so the flow completes after the button click.
    (analyzeImportJob as Mock).mockResolvedValue({
      job: job({ job_id: "j-intaking", state: "review" }),
      candidates: 1,
    });
    (getImportReview as Mock).mockResolvedValue({
      job: job({ job_id: "j-intaking", state: "review" }),
      digest: "digest-intaking",
      candidates: [candidate({ job_id: "j-intaking" })],
    });

    renderImporter();

    // Wait for recovery to finish and the select step to render.
    await screen.findByRole("heading", { name: "Importar contenido" });

    // The resume notice explains the file is already uploaded.
    expect(
      screen.getByText(/El archivo ya está subido en el servidor/),
    ).toBeInTheDocument();

    // The "Continuar análisis" button is present and enabled (no files
    // selected locally — sources.length === 0).
    const resumeBtn = screen.getByTestId("resume-analyze-btn");
    expect(resumeBtn).toBeEnabled();
    expect(resumeBtn).toHaveTextContent("Continuar análisis");

    // Click it — the flow should skip createImportJob and streamImportFile
    // and go straight to analyzeImportJob.
    fireEvent.click(resumeBtn);

    await screen.findByRole("heading", { name: tEs("importer.heading.review") });

    // createImportJob and streamImportFile were NEVER called — the file
    // was already on the server spool.
    expect(createImportJob).not.toHaveBeenCalled();
    expect(streamImportFile).not.toHaveBeenCalled();
    // analyzeImportJob was called with the recovered job ID and the
    // explicit enrich flag (default ON). Vision never requested (UX).
    expect(analyzeImportJob).toHaveBeenCalledWith(
      "mundo", "j-intaking", { enrich: true, vision: false },
    );
  });
});

describe("WorldImporter — structured frontmatter review (Phase 4)", () => {
  beforeEach(() => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [world],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    (listImportJobs as Mock).mockResolvedValue({ jobs: [], next_cursor: null });
  });

  afterEach(() => {
    window.sessionStorage.clear();
  });

  it("shows the H1-H5 authoring guide with empty-section behavior in review", async () => {
    mockAnalyzeToReview([candidate()]);
    renderImporter();
    await selectFileAndAnalyze();

    const guide = screen.getByTestId("authoring-guide");
    expect(guide).toBeInTheDocument();
    expect(
      within(guide).getByText("Guía de estructura H1–H5"),
    ).toBeInTheDocument();
    // H1 maps to a root/índice folder.
    expect(within(guide).getByText(/raíz\/índice del mundo/)).toBeInTheDocument();
    // H2–H5 map to fichas.
    expect(within(guide).getByText(/se convierte en una/)).toBeInTheDocument();
    // Empty scaffolding is preserved, never deleted.
    expect(
      within(guide).getByText(/andamiaje intencional se preserva/),
    ).toBeInTheDocument();
    // Childless text folds into the parent ficha.
    expect(
      within(guide).getByText(/texto plano de un encabezado sin hijos/),
    ).toBeInTheDocument();
  });

  it("surfaces the relation-quality report on the candidate", async () => {
    mockAnalyzeToReview([
      candidate({ relation_quality: ["standalone"] }),
    ]);
    renderImporter();
    await selectFileAndAnalyze();

    const block = screen.getByTestId("relation-quality-c1");
    expect(block).toHaveTextContent("Relación con el grafo");
    expect(block).toHaveTextContent("Sin relaciones ni menciones");
  });

  it("renders the generated frontmatter state badge and canonical identity", async () => {
    mockAnalyzeToReview([
      candidate({
        canonical_id: "Ayagares::Descripción Física::Forma Base",
        display_title: "Forma Base",
        summary:
          "La Forma Base es la morfología corporal estándar de la especie.",
        frontmatter: {
          title: "Forma Base",
          type: "lore",
          description: "Morfología corporal estándar.",
          relaciones: ["Ayagares::Especies"],
          state: "generated",
        },
      }),
    ]);
    renderImporter();
    await selectFileAndAnalyze();

    // Display title labels the row; canonical identity is shown in the body.
    // (The title appears in the row header and again in the frontmatter block.)
    expect(screen.getAllByText("Forma Base").length).toBeGreaterThan(0);
    expect(screen.getByTestId("canonical-id-c1")).toHaveTextContent(
      "Ayagares::Descripción Física::Forma Base",
    );

    // State badge reads "generado" for the generated state.
    expect(screen.getByTestId("frontmatter-state-c1")).toHaveTextContent(
      "generado",
    );

    // The reviewed frontmatter (title/type/description/relaciones) is visible.
    const fm = screen.getByTestId("frontmatter-c1");
    expect(within(fm).getByText("lore")).toBeInTheDocument();
    expect(
      within(fm).getByText("Morfología corporal estándar."),
    ).toBeInTheDocument();
    expect(
      within(fm).getByText("Ayagares::Especies"),
    ).toBeInTheDocument();

    // The dense summary is surfaced.
    expect(screen.getByTestId("summary-c1")).toHaveTextContent(
      "morfología corporal",
    );
  });

  it("renders a fallback state badge when enrichment failed open", async () => {
    mockAnalyzeToReview([
      candidate({
        display_title: "Manual Ficha",
        frontmatter: {
          title: "Manual Ficha",
          type: null,
          description: "",
          relaciones: [],
          state: "fallback",
        },
      }),
    ]);
    renderImporter();
    await selectFileAndAnalyze();

    expect(screen.getByTestId("frontmatter-state-c1")).toHaveTextContent(
      "respaldo",
    );
  });

  it("isolates unresolved media as a non-blocking review warning", async () => {
    mockAnalyzeToReview([
      candidate({
        canonical_id: "Ayagares::Bestiario::Dragón",
        display_title: "Dragón",
        media_diagnostics: [
          {
            reference: "![][imagen1]",
            image_key: "imagen1",
            alt_text: "",
            status: "unresolved",
            target_path: "",
            target_ficha: "Ayagares::Bestiario::Dragón",
            message: "no hay definición para [imagen1]",
          },
          {
            reference: "![][mapa]",
            image_key: "mapa",
            alt_text: "",
            status: "resolved",
            target_path: "wiki/media/mapa.png",
            target_ficha: "Ayagares::Bestiario::Dragón",
            message: "",
          },
        ],
      }),
    ]);
    renderImporter();
    await selectFileAndAnalyze();

    // Header: the unresolved span is flagged for review.
    expect(screen.getByTestId("media-warning-c1")).toHaveTextContent(
      "1 media sin resolver",
    );

    // Body: both diagnostics render; the unresolved one explains the isolation.
    const diags = screen.getByTestId("media-diagnostics-c1");
    expect(within(diags).getByText("![][imagen1]")).toBeInTheDocument();
    expect(within(diags).getByText("![][mapa]")).toBeInTheDocument();
    expect(
      within(diags).getByText(/no hay definición/),
    ).toBeInTheDocument();
    expect(within(diags).getByText("wiki/media/mapa.png")).toBeInTheDocument();
  });
});
