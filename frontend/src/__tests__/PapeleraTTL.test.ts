import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { Mock } from "vitest";
import { apiFetch } from "@/api/client";
import { listTrash } from "@/api/wiki";

vi.mock("@/api/client", () => ({
  apiFetch: vi.fn(),
}));

const entries = [
  {
    entry_id: "e1",
    section: "lore",
    original_path: "lore/old.md",
    kind: "file" as const,
    deleted_at: "2026-01-01T10:00:00Z",
    size: 128,
  },
  {
    entry_id: "e2",
    section: "personajes",
    original_path: "personajes/draft.md",
    kind: "file" as const,
    deleted_at: "2026-02-01T10:00:00Z",
    size: 256,
  },
];

describe("listTrash", () => {
  beforeEach(() => {
    (apiFetch as Mock).mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns entries plus the purged count when the TTL purge removed entries", async () => {
    (apiFetch as Mock).mockResolvedValue({ entries, purged: 2 });

    const result = await listTrash("vibrantes");

    expect(result).toEqual({ entries, purged: 2 });
    expect(apiFetch).toHaveBeenCalledWith("/api/vibrantes/papelera");
  });

  it("normalizes a missing purged field to 0", async () => {
    (apiFetch as Mock).mockResolvedValue({ entries });

    const result = await listTrash("vibrantes");

    expect(result).toEqual({ entries, purged: 0 });
  });
});
