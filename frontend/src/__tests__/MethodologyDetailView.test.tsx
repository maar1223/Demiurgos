import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MethodologyDetailView } from "@/components/organisms/MethodologyDetailView";
import { ApiError } from "@/api/types";
import type { PublishedMethodologyDetail } from "@/api/types";

const mockGetPublishedDetail = vi.hoisted(() => vi.fn());
const mockGetAdjuntoContent = vi.hoisted(() => vi.fn());

vi.mock("@/api/coCreation", () => ({
  getPublishedDetail: mockGetPublishedDetail,
}));

vi.mock("@/api/methodologies", () => ({
  getAdjuntoContent: mockGetAdjuntoContent,
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

const detailWithAdjuntos: PublishedMethodologyDetail = {
  ...detail,
  adjuntos: [
    {
      path: "ejemplos/Axill.md",
      sha256: "a".repeat(64),
      bytes: 2048,
      nivel: "ejemplo",
    },
    {
      path: "referencias/Fuente.md",
      sha256: "b".repeat(64),
      bytes: 512,
      nivel: "referencia",
    },
  ],
};

const selected = { skill_id: "eneagrama", version: "1.2.0" };

const otherDetail: PublishedMethodologyDetail = {
  ...detail,
  skill_id: "otro-taller",
  version: "2.0.0",
  name: "Otro taller",
  source: "# Otro taller",
  adjuntos: [],
};

describe("MethodologyDetailView (SC-SB-3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetAdjuntoContent.mockReset();
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

  it("renders the metadata-only attachments block when adjuntos are present (R23)", async () => {
    mockGetPublishedDetail.mockResolvedValue(detailWithAdjuntos);
    render(<MethodologyDetailView selected={selected} />);

    expect(
      await screen.findByRole("heading", { level: 3, name: "Adjuntos" }),
    ).toBeInTheDocument();
    // Path + nivel + bytes are listed per entry.
    expect(screen.getByText("ejemplos/Axill.md")).toBeInTheDocument();
    expect(screen.getByText("ejemplo")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
    expect(screen.getByText("referencias/Fuente.md")).toBeInTheDocument();
    expect(screen.getByText("referencia")).toBeInTheDocument();
    expect(screen.getByText("512 B")).toBeInTheDocument();
    // Metadata only: the sha256 is never rendered, and no bytes are fetched.
    expect(screen.queryByText("a".repeat(64))).not.toBeInTheDocument();
  });

  it("hides the attachments block when adjuntos is empty (R23)", async () => {
    mockGetPublishedDetail.mockResolvedValue({ ...detail, adjuntos: [] });
    render(<MethodologyDetailView selected={selected} />);

    expect(
      await screen.findByText(/Modelar los nueve eneatipos/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 3, name: "Adjuntos" }),
    ).not.toBeInTheDocument();
  });

  it("renders no attachments block when adjuntos is absent (R22 old payload)", async () => {
    mockGetPublishedDetail.mockResolvedValue(detail);
    render(<MethodologyDetailView selected={selected} />);

    expect(
      await screen.findByText(/Modelar los nueve eneatipos/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 3, name: "Adjuntos" }),
    ).not.toBeInTheDocument();
  });
});

describe("MethodologyDetailView → Adjunto viewer (PR5)", () => {
  it("renders each adjunto as an actionable full-width button", async () => {
    mockGetPublishedDetail.mockResolvedValue(detailWithAdjuntos);
    render(<MethodologyDetailView selected={selected} />);

    const axill = await screen.findByRole("button", {
      name: /ejemplos\/Axill\.md/,
    });
    expect(axill).toHaveClass("w-full", "text-left");
    expect(axill).toHaveAttribute("aria-haspopup", "dialog");

    // Every row is a control; metadata (nivel + bytes) stays visible.
    expect(
      screen.getByRole("button", { name: /referencias\/Fuente\.md/ }),
    ).toBeInTheDocument();

    // Inert until activated: no dialog and no carrier fetched.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mockGetAdjuntoContent).not.toHaveBeenCalled();
  });

  it("opens the viewer and fetches the activated exemplar", async () => {
    mockGetPublishedDetail.mockResolvedValue(detailWithAdjuntos);
    mockGetAdjuntoContent.mockResolvedValue("# Axill\n\nContenido del ejemplo.\n");
    const user = userEvent.setup();
    render(<MethodologyDetailView selected={selected} />);

    await user.click(
      await screen.findByRole("button", { name: /ejemplos\/Axill\.md/ }),
    );

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { level: 1, name: "Axill" }),
    ).toBeInTheDocument();
    expect(mockGetAdjuntoContent).toHaveBeenCalledWith(
      "eneagrama",
      "1.2.0",
      "ejemplos/Axill.md",
    );
  });

  it("closes the viewer when the page selection changes", async () => {
    mockGetPublishedDetail.mockResolvedValue(detailWithAdjuntos);
    mockGetAdjuntoContent.mockResolvedValue("# Axill\n");
    const user = userEvent.setup();
    const { rerender } = render(<MethodologyDetailView selected={selected} />);

    await user.click(
      await screen.findByRole("button", { name: /ejemplos\/Axill\.md/ }),
    );
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    mockGetPublishedDetail.mockResolvedValue(otherDetail);
    rerender(
      <MethodologyDetailView
        selected={{ skill_id: "otro-taller", version: "2.0.0" }}
      />,
    );

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });
});
