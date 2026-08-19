import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api/client", () => ({
  apiFetch: vi.fn(),
}));

// The REAL importer module runs against the mocked transport: the tests
// prove URLs, payloads, chunk offsets, and progress without a server.
import { apiFetch } from "@/api/client";
import {
  bytesToBase64,
  createImportJob,
  IMPORT_CHUNK_BYTES,
  streamImportChunk,
  streamImportFile,
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
});