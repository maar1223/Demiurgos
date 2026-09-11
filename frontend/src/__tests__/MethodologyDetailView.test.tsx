import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MethodologyDetailView } from "@/components/organisms/MethodologyDetailView";
import { ApiError } from "@/api/types";
import type { PublishedMethodologyDetail } from "@/api/types";

const mockGetPublishedDetail = vi.hoisted(() => vi.fn());

vi.mock("@/api/coCreation", () => ({
  getPublishedDetail: mockGetPublishedDetail,
}));

const detail: PublishedMethodologyDetail = {
  skill_id: "eneagrama",
  version: "1.2.0",
  name: "Eneagrama",
  description: "Tipos de personalidad",
  digest: "abc",
  published_at: "2026-01-01",
  phases: [],
  language: "es",
  source: "# Eneagrama\n\nModelar los nueve eneatipos.",
  taller: "Mundo",
  etiquetas: ["personalidad"],
  parent_skill_id: null,
  parent_version: null,
};

const selected = { skill_id: "eneagrama", version: "1.2.0" };

describe("MethodologyDetailView (SC-SB-3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the metadata header card + source markdown (SC-SB-3.1)", async () => {
    mockGetPublishedDetail.mockResolvedValue(detail);
    render(<MethodologyDetailView selected={selected} />);

    // Metadata header card: name as h2 (distinct from the h1 the markdown
    // source renders), identity line, description.
    expect(
      await screen.findByRole("heading", { level: 2, name: "Eneagrama" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/eneagrama@1\.2\.0/)).toBeInTheDocument();
    expect(screen.getByText("Tipos de personalidad")).toBeInTheDocument();
    // Source body rendered via MarkdownViewer.
    expect(screen.getByText(/Modelar los nueve eneatipos/)).toBeInTheDocument();
    expect(mockGetPublishedDetail).toHaveBeenCalledWith("eneagrama", "1.2.0");
  });

  it("falls back to a metadata-only card on 401 — no error, no source (SC-SB-3.2)", async () => {
    mockGetPublishedDetail.mockRejectedValue(new ApiError(401, "Unauthorized"));
    render(<MethodologyDetailView selected={selected} />);

    // Identity card renders; the source body must NOT render.
    expect(
      await screen.findByText(/eneagrama@1\.2\.0/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Modelar los nueve eneatipos/)).not.toBeInTheDocument();
    // No error banner and no retry copy.
    expect(
      screen.queryByText("No se pudo cargar el detalle de la metodología."),
    ).not.toBeInTheDocument();
  });

  it("renders the empty state when selected is null (SC-SB-3.3)", () => {
    render(<MethodologyDetailView selected={null} />);

    expect(
      screen.getByText(/Seleccioná una metodología en el explorador/),
    ).toBeInTheDocument();
    expect(mockGetPublishedDetail).not.toHaveBeenCalled();
  });
});