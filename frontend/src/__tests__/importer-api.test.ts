import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api/client", () => ({
  apiFetch: vi.fn(),
}));

// The REAL importer module runs against the mocked transport: the tests
// prove URLs, payloads, chunk offsets, and progress without a server.
import { apiFetch } from "@/api/client";
import {
  analyzeImportJob,
  approveImportGroups,
  bytesToBase64,
  createImportJob,
  executeImport,
  IMPORT_CHUNK_BYTES,
  postReviewDecisions,
  streamImportChunk,
  streamImportFile,
  waitForJobTerminal,
} from "@/api/importer";

const mockApiFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

/** Minimal File-shaped source (jsdom Blob lacks arrayBuffer on slices). */
class ChunkSource {
  size: number;

  constructor(private readonly bytes: Uint8Array) {
    this.size = bytes.length;
  }

  slice(start: number, end: number): { arrayBuffer(): Promise<ArrayBuffer> } {
    return {
      arrayBuffer: () =>
        Promise.resolve(this.bytes.slice(start, end).buffer as ArrayBuffer),
    };
  }
}

describe("importer API — world-importer slice 3 contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("createImportJob posts the source kind and relative paths to /api/{mundo}/imports", async () => {
    mockApiFetch.mockResolvedValue({ job: { job_id: "job1", state: "pending" } });
    await createImportJob("mundo", {
      source_kind: "loose",
      files: ["a.md", "b.md"],
    });
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/mundo/imports",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ source_kind: "loose", files: ["a.md", "b.md"] }),
      }),
    );
  });

  it("createImportJob forwards the classifier sections map when provided (BLOQUE 1 piece 1)", async () => {
    mockApiFetch.mockResolvedValue({ job: { job_id: "job1", state: "pending" } });
    await createImportJob("mundo", {
      source_kind: "loose",
      files: ["a.md", "b.md"],
      sections: { "a.md": "personajes", "b.md": "referencias" },
    });
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/mundo/imports",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          source_kind: "loose",
          files: ["a.md", "b.md"],
          sections: { "a.md": "personajes", "b.md": "referencias" },
        }),
      }),
    );
  });

  it("streamImportChunk targets the job-scoped URL with offset and base64 payload", async () => {
    mockApiFetch.mockResolvedValue({ job_id: "job1", offset: 3 });
    await streamImportChunk("mundo", "job1", "a.md", 0, "YWJj");
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/mundo/imports/job1/stream",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          relative: "a.md",
          offset: 0,
          data_b64: "YWJj",
        }),
      }),
    );
  });

  it("bytesToBase64 encodes binary buffers as base64", () => {
    const buffer = new Uint8Array([97, 98, 99]).buffer as ArrayBuffer;
    expect(bytesToBase64(buffer)).toBe("YWJj");
  });

  it("streamImportFile sends contiguous chunks and reports progress", async () => {
    // 2 full chunks + a 7-byte tail → 3 streamed chunks with advancing offsets.
    const payload = new Uint8Array(IMPORT_CHUNK_BYTES * 2 + 7);
    for (let i = 0; i < payload.length; i += 1) payload[i] = i % 251;
    const file = new ChunkSource(payload);

    mockApiFetch.mockImplementation(
      async (_url: string, options?: RequestInit) => {
        const body = JSON.parse(String(options?.body)) as {
          offset: number;
          data_b64: string;
        };
        // Server contract: returns offset + decoded bytes written.
        const bytes = atob(body.data_b64).length;
        return { job_id: "job1", offset: body.offset + bytes };
      },
    );

    const progress: Array<{ streamed: number; total: number }> = [];
    const finalOffset = await streamImportFile(
      "mundo",
      "job1",
      file as unknown as File,
      "grande.md",
      (streamed, total) => progress.push({ streamed, total }),
    );

    expect(finalOffset).toBe(file.size);
    expect(mockApiFetch).toHaveBeenCalledTimes(3);
    expect(mockApiFetch).toHaveBeenNthCalledWith(
      1,
      "/api/mundo/imports/job1/stream",
      expect.objectContaining({
        body: expect.stringContaining('"relative":"grande.md"'),
      }),
    );
    expect(progress[progress.length - 1]).toEqual({
      streamed: file.size,
      total: file.size,
    });
  });

  it("streamImportFile never sends a chunk for an empty file (no whole-job buffer)", async () => {
    const empty = new ChunkSource(new Uint8Array(0));
    const finalOffset = await streamImportFile(
      "mundo",
      "job1",
      empty as unknown as File,
      "vacio.md",
    );
    expect(finalOffset).toBe(0);
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it("analyzeImportJob omits the body when enrich is absent (legacy deterministic)", async () => {
    mockApiFetch.mockResolvedValue({ job: { job_id: "job1" }, candidates: 0 });
    await analyzeImportJob("mundo", "job1");
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/mundo/imports/job1/analyze",
      expect.objectContaining({ method: "POST", body: undefined }),
    );
  });

  it("analyzeImportJob sends { enrich: true } when opt-in is requested (slice 2)", async () => {
    mockApiFetch.mockResolvedValue({
      job: { job_id: "job1" },
      candidates: 1,
      enrichment_status: "ok",
    });
    await analyzeImportJob("mundo", "job1", { enrich: true });
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/mundo/imports/job1/analyze",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ enrich: true }),
      }),
    );
  });

  it("analyzeImportJob omits the body when enrich=false (no Hermes call)", async () => {
    mockApiFetch.mockResolvedValue({ job: { job_id: "job1" }, candidates: 0 });
    await analyzeImportJob("mundo", "job1", { enrich: false });
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/mundo/imports/job1/analyze",
      expect.objectContaining({ body: undefined }),
    );
  });

  it("postReviewDecisions POSTs the decisions array to /review/decisions", async () => {
    mockApiFetch.mockResolvedValue({ accepted: 2 });
    await postReviewDecisions("mundo", "job1", [
      { suggestion_id: "s1", decision: "approve" },
      { suggestion_id: "s2", decision: "reject" },
    ]);
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/mundo/imports/job1/review/decisions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          decisions: [
            { suggestion_id: "s1", decision: "approve" },
            { suggestion_id: "s2", decision: "reject" },
          ],
        }),
      }),
    );
  });

  it("approveImportGroups omits suggestion_ids when no suggestions approved", async () => {
    mockApiFetch.mockResolvedValue({ approval_id: "a1", token: "t", digest: "d", expires_at: "" });
    await approveImportGroups("mundo", "job1", ["fichas"]);
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/mundo/imports/job1/approve",
      expect.objectContaining({
        body: JSON.stringify({ group_ids: ["fichas"] }),
      }),
    );
  });

  it("approveImportGroups binds suggestion_ids when provided (slice 2)", async () => {
    mockApiFetch.mockResolvedValue({ approval_id: "a1", token: "t", digest: "d", expires_at: "" });
    await approveImportGroups("mundo", "job1", ["fichas"], ["s1", "s2"]);
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/mundo/imports/job1/approve",
      expect.objectContaining({
        body: JSON.stringify({ group_ids: ["fichas"], suggestion_ids: ["s1", "s2"] }),
      }),
    );
  });

  it("executeImport omits suggestion_ids when none provided", async () => {
    mockApiFetch.mockResolvedValue({ job: { job_id: "job1" }, outcomes: [] });
    await executeImport("mundo", "job1", "digest1", "tok");
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/mundo/imports/job1/execute",
      expect.objectContaining({
        body: JSON.stringify({ digest: "digest1", token: "tok" }),
      }),
    );
  });

  it("executeImport forwards suggestion_ids when provided (slice 2)", async () => {
    mockApiFetch.mockResolvedValue({ job: { job_id: "job1" }, outcomes: [] });
    await executeImport("mundo", "job1", "digest1", "tok", ["s1"]);
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/mundo/imports/job1/execute",
      expect.objectContaining({
        body: JSON.stringify({
          digest: "digest1",
          token: "tok",
          suggestion_ids: ["s1"],
        }),
      }),
    );
  });

  it("waitForJobTerminal polls while analyzing and stops at review, reporting progress", async () => {
    mockApiFetch
      .mockResolvedValueOnce({
        job: { job_id: "job1", state: "analyzing", progress_stage: "Analizando fuentes", progress_pct: 30 },
      })
      .mockResolvedValueOnce({
        job: { job_id: "job1", state: "analyzing", progress_stage: "Construyendo fichas", progress_pct: 60 },
      })
      .mockResolvedValueOnce({
        job: { job_id: "job1", state: "review", progress_stage: "", progress_pct: null },
      });
    const seen: Array<{ stage: string; pct: number | null }> = [];
    const job = await waitForJobTerminal("mundo", "job1", (j) => {
      seen.push({ stage: j.progress_stage ?? "", pct: j.progress_pct ?? null });
    }, { intervalMs: 1, maxWaitMs: 10_000 });

    expect(job.state).toBe("review");
    expect(seen.map((s) => s.stage)).toEqual([
      "Analizando fuentes",
      "Construyendo fichas",
    ]);
    // Three polls total: two processing + one terminal.
    expect(mockApiFetch).toHaveBeenCalledTimes(3);
    expect(mockApiFetch).toHaveBeenCalledWith("/api/mundo/imports/job1");
  });

  it("waitForJobTerminal surfaces the failed job instead of declaring a false outage", async () => {
    mockApiFetch.mockResolvedValueOnce({
      job: { job_id: "job1", state: "analyzing", progress_stage: "Analizando", progress_pct: 5 },
    }).mockResolvedValueOnce({
      job: { job_id: "job1", state: "failed", error: "conversion failed" },
    });
    const job = await waitForJobTerminal("mundo", "job1", undefined, {
      intervalMs: 1,
      maxWaitMs: 10_000,
    });
    expect(job.state).toBe("failed");
    expect(job.error).toBe("conversion failed");
  });
});