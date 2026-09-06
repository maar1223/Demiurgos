import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getEntity } from "@/api/graph";
import type { Mock } from "vitest";
import { ApiError } from "@/api/types";
import { useEntity } from "@/hooks/useEntity";

vi.mock("@/api/graph", () => ({
  getEntity: vi.fn(),
}));

const validEntity = {
  id: "Stal::Rhyz",
  name: "Rhyz",
  type: "personaje",
  path: "personajes/Rhyz.md",
  status: "stable",
  content: "Body",
  forward_links: [],
  backlinks: [],
  relaciones: [],
};

describe("useEntity", () => {
  beforeEach(() => {
    (getEntity as Mock).mockReset();
  });

  it("returns the entity when the backend resolves it", async () => {
    (getEntity as Mock).mockResolvedValue(validEntity);

    const { result } = renderHook(() => useEntity("Vibrantes", "Rhyz"));

    await waitFor(() => expect(result.current.entity).toEqual(validEntity));
    expect(result.current.error).toBeUndefined();
  });

  it("treats a 200 {error} body as a 404 instead of returning a malformed entity", async () => {
    // The backend returns a 200 with `{error}` when the name is unresolved
    // (e.g. a path passed as a name). Previously this was returned as the
    // "entity", so EntityDetail crashed on `entity.forward_links.length`.
    (getEntity as Mock).mockResolvedValue({
      error: "Entidad no encontrada",
      name: "lore/…/dvex-del-stal-6.md",
    });

    const { result } = renderHook(() =>
      useEntity("Vibrantes", "lore/…/dvex-del-stal-6.md"),
    );

    await waitFor(() => expect(result.current.error).toBeInstanceOf(ApiError));
    expect((result.current.error as ApiError).status).toBe(404);
    expect(result.current.entity).toBeNull();
  });
});
