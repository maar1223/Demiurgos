import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { Mock } from "vitest";
import WorldImporter from "@/pages/WorldImporter";
import type {
  ImportApprovalResponse,
  ImportCandidate,
  ImportJob,
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
  approveImportGroups: vi.fn(),
  executeImport: vi.fn(),
  cancelImportJob: vi.fn(),
  resumeImportJob: vi.fn(),
  rollbackImportJob: vi.fn(),
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

import { useWorlds } from "@/hooks/useWorlds";
import {
  analyzeImportJob,
  approveImportGroups,
  cancelImportJob,
  createImportJob,
  getImportReview,
  streamImportFile,
} from "@/api/importer";

const world = { name: "mundo", path: "/mundo", lore_count: 1, character_count: 0, saga_count: 0 };

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
    status: "pending",
    okf_issues: [],
    size_bytes: 1024,
    images: [],
    merge: null,
    replacement: null,
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
  await screen.findByRole("heading", { name: "Revisión e aprobación" });
}

describe("WorldImporter — accessible, preservation-first workflow (slice 3)", () => {
  beforeEach(() => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [world],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
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
      "Revisión e aprobación",
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
});