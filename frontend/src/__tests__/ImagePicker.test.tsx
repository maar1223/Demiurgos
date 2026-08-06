import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImagePicker } from "@/components/organisms/ImagePicker";

// Mock the image hooks and the media URL builder — the real ones fetch
// from the network.
vi.mock("@/hooks/useImages", () => ({
  useImages: vi.fn(),
  useImageDelete: vi.fn(),
}));

vi.mock("@/api/wiki", () => ({
  getMediaUrl: vi.fn(
    (mundo: string, path: string) =>
      `/api/${encodeURIComponent(mundo)}/media?path=${encodeURIComponent(path)}`,
  ),
}));

import { useImages, useImageDelete } from "@/hooks/useImages";
import type { Mock } from "vitest";

const mockImages = [
  {
    path: "wiki/media/foto.jpg",
    name: "foto.jpg",
    size_bytes: 2048,
    extension: ".jpg",
  },
  {
    path: "wiki/media/retrato.png",
    name: "retrato.png",
    size_bytes: 5120,
    extension: ".png",
  },
];

function mockGallery(overrides: Record<string, unknown> = {}) {
  (useImages as Mock).mockReturnValue({
    images: mockImages,
    total: mockImages.length,
    isLoading: false,
    error: null,
    mutate: vi.fn(),
    ...overrides,
  });
}

function mockDelete(remove: Mock = vi.fn().mockResolvedValue({ success: true })) {
  (useImageDelete as Mock).mockReturnValue({ remove });
  return remove;
}

function renderPicker(onSelect = vi.fn(), onClose = vi.fn()) {
  const view = render(
    <ImagePicker mundo="Vibrantes" onSelect={onSelect} onClose={onClose} />,
  );
  return { onSelect, onClose, rerender: view.rerender };
}

describe("ImagePicker", () => {
  beforeEach(() => {
    mockGallery();
    mockDelete();
  });

  it("renders the image grid from the useImages mock", () => {
    renderPicker();

    expect(screen.getByText("foto.jpg")).toBeInTheDocument();
    expect(screen.getByText("retrato.png")).toBeInTheDocument();
    // Header shows the count of images
    expect(screen.getByText(/2 imágenes/)).toBeInTheDocument();
  });

  it("renders a loading spinner while images load", () => {
    mockGallery({ isLoading: true, images: [], total: 0 });
    renderPicker();

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders the empty state when the world has no images", () => {
    mockGallery({ images: [], total: 0 });
    renderPicker();

    expect(
      screen.getByText(/No hay imágenes en este mundo/i),
    ).toBeInTheDocument();
  });

  it("selects an image on click: highlights it and does NOT emit onSelect yet", async () => {
    const { onSelect } = renderPicker();
    const user = userEvent.setup();

    const foto = screen.getByRole("button", { name: /foto\.jpg/i });
    await user.click(foto);

    expect(foto).toHaveAttribute("aria-pressed", "true");
    expect(onSelect).not.toHaveBeenCalled();

    // Only one image selected at a time
    const retrato = screen.getByRole("button", { name: /retrato\.png/i });
    await user.click(retrato);

    expect(foto).toHaveAttribute("aria-pressed", "false");
    expect(retrato).toHaveAttribute("aria-pressed", "true");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("disables Aceptar until an image is selected, then enables it", async () => {
    renderPicker();
    const user = userEvent.setup();

    const accept = screen.getByRole("button", { name: /aceptar/i });
    expect(accept).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));

    expect(accept).toBeEnabled();
  });

  it("emits the plain path with no suffix by default (md + auto)", async () => {
    const { onSelect } = renderPicker();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.click(screen.getByRole("button", { name: /aceptar/i }));

    expect(onSelect).toHaveBeenCalledWith("wiki/media/foto.jpg");
  });

  it("appends #left when Izquierda alignment is chosen", async () => {
    const { onSelect } = renderPicker();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: /alineación/i }),
      "left",
    );
    await user.click(screen.getByRole("button", { name: /aceptar/i }));

    expect(onSelect).toHaveBeenCalledWith("wiki/media/foto.jpg#left");
  });

  it("appends size-only suffixes without an alignment (#sm, #lg)", async () => {
    const { onSelect } = renderPicker();
    const user = userEvent.setup();
    const sizeSelect = screen.getByRole("combobox", { name: /tamaño/i });

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.selectOptions(sizeSelect, "sm");
    await user.click(screen.getByRole("button", { name: /aceptar/i }));
    expect(onSelect).toHaveBeenCalledWith("wiki/media/foto.jpg#sm");

    await user.click(screen.getByRole("button", { name: /retrato\.png/i }));
    await user.selectOptions(sizeSelect, "lg");
    await user.click(screen.getByRole("button", { name: /aceptar/i }));
    expect(onSelect).toHaveBeenCalledWith("wiki/media/retrato.png#lg");
  });

  it("combines alignment and size suffixes (right + lg → #right-lg)", async () => {
    const { onSelect } = renderPicker();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: /alineación/i }),
      "right",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: /tamaño/i }),
      "lg",
    );
    await user.click(screen.getByRole("button", { name: /aceptar/i }));

    expect(onSelect).toHaveBeenCalledWith("wiki/media/foto.jpg#right-lg");
  });

  it("combines center alignment with sm size (→ #center-sm)", async () => {
    const { onSelect } = renderPicker();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: /alineación/i }),
      "center",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: /tamaño/i }),
      "sm",
    );
    await user.click(screen.getByRole("button", { name: /aceptar/i }));

    expect(onSelect).toHaveBeenCalledWith("wiki/media/foto.jpg#center-sm");
  });

  it("resets to no suffix when Automática and Mediana are selected", async () => {
    const { onSelect } = renderPicker();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: /alineación/i }),
      "right",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: /tamaño/i }),
      "lg",
    );
    // Reset both selectors back to defaults
    await user.selectOptions(
      screen.getByRole("combobox", { name: /alineación/i }),
      "",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: /tamaño/i }),
      "",
    );
    await user.click(screen.getByRole("button", { name: /aceptar/i }));

    expect(onSelect).toHaveBeenCalledWith("wiki/media/foto.jpg");
  });

  it("Cancelar calls onClose and NOT onSelect", async () => {
    const { onSelect, onClose } = renderPicker();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.click(screen.getByRole("button", { name: /cancelar/i }));

    expect(onClose).toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("calls onClose when the close button is clicked", async () => {
    const { onClose } = renderPicker();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /cerrar/i }));

    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when Escape is pressed", async () => {
    const { onClose } = renderPicker();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when the overlay outside the dialog is clicked", async () => {
    const { onClose } = renderPicker();
    const user = userEvent.setup();

    const overlay = document.querySelector(".fixed.inset-0");
    expect(overlay).not.toBeNull();
    await user.click(overlay as HTMLElement);

    expect(onClose).toHaveBeenCalled();
  });

  // ── delete flow ────────────────────────────────────────────────────────

  it("shows the delete button only on the selected image", async () => {
    const user = userEvent.setup();
    renderPicker();

    // Nothing to delete until an image is selected.
    expect(
      screen.queryByRole("button", { name: /eliminar/i }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));

    expect(
      screen.getByRole("button", { name: "Eliminar foto.jpg" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Eliminar retrato.png" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /eliminar/i })).toHaveLength(1);

    // Switching the selection moves the delete button to the new image.
    await user.click(screen.getByRole("button", { name: /retrato\.png/i }));

    expect(
      screen.getByRole("button", { name: "Eliminar retrato.png" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Eliminar foto.jpg" }),
    ).not.toBeInTheDocument();
  });

  it("clicking delete opens the confirmation dialog with the image name", async () => {
    const user = userEvent.setup();
    renderPicker();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.click(screen.getByRole("button", { name: "Eliminar foto.jpg" }));

    const dialog = screen.getByRole("dialog", { name: /eliminar/i });
    expect(dialog).toHaveTextContent(
      /¿Eliminar "foto\.jpg"\? Se moverá a la papelera\./,
    );
    expect(
      within(dialog).getByRole("button", { name: "Eliminar" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Cancelar" }),
    ).toBeInTheDocument();
  });

  it("confirming delete calls remove with the path and refreshes the list", async () => {
    const user = userEvent.setup();
    const remove = mockDelete(
      vi.fn().mockResolvedValue({ success: true, path: "wiki/media/foto.jpg" }),
    );
    const { rerender } = renderPicker();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.click(screen.getByRole("button", { name: "Eliminar foto.jpg" }));
    await user.click(screen.getByRole("button", { name: "Eliminar" }));

    await waitFor(() => expect(remove).toHaveBeenCalledTimes(1));
    expect(remove).toHaveBeenCalledWith("wiki/media/foto.jpg");

    // Success feedback shows while the picker stays open.
    await waitFor(() =>
      expect(screen.getByText("Imagen eliminada")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("dialog", { name: /eliminar/i })).not.toBeInTheDocument();

    // Simulate the SWR mutate re-fetch: the deleted image drops out.
    (useImages as Mock).mockReturnValue({
      images: [mockImages[1]],
      total: 1,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    rerender(
      <ImagePicker
        mundo="Vibrantes"
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() =>
      expect(screen.queryByText("foto.jpg")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("retrato.png")).toBeInTheDocument();
  });

  it("cancelar closes the dialog without deleting anything", async () => {
    const user = userEvent.setup();
    const remove = mockDelete(vi.fn());
    renderPicker();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.click(screen.getByRole("button", { name: "Eliminar foto.jpg" }));
    const dialog = screen.getByRole("dialog", { name: /eliminar/i });
    expect(dialog).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Cancelar" }));

    expect(remove).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("dialog", { name: /eliminar/i }),
    ).not.toBeInTheDocument();
    // The image is still in the grid and still selected.
    expect(screen.getByText("foto.jpg")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Eliminar foto.jpg" }),
    ).toBeInTheDocument();
  });

  it("shows the delete error inside the dialog and keeps it open", async () => {
    const user = userEvent.setup();
    mockDelete(vi.fn().mockRejectedValue(new Error("No autorizado")));
    renderPicker();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.click(screen.getByRole("button", { name: "Eliminar foto.jpg" }));
    await user.click(screen.getByRole("button", { name: "Eliminar" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/no autorizado/i),
    );
    // The dialog stays open so the user can retry or cancel.
    expect(
      screen.getByRole("dialog", { name: /eliminar/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Eliminar" })).toBeInTheDocument();
  });

  // ── rawMode (cover selection) ───────────────────────────────────────

  it("rawMode hides the alignment/size dropdowns", () => {
    render(
      <ImagePicker
        mundo="Vibrantes"
        onSelect={vi.fn()}
        onClose={vi.fn()}
        rawMode
      />,
    );

    expect(
      screen.queryByRole("combobox", { name: /alineación/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: /tamaño/i }),
    ).not.toBeInTheDocument();
  });

  it("rawMode emits the BARE path with no #align-size suffix", async () => {
    const onSelect = vi.fn();
    render(
      <ImagePicker
        mundo="Vibrantes"
        onSelect={onSelect}
        onClose={vi.fn()}
        rawMode
      />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.click(screen.getByRole("button", { name: /aceptar/i }));

    expect(onSelect).toHaveBeenCalledWith("wiki/media/foto.jpg");
  });

  it("rawMode shows the cover hint text", () => {
    render(
      <ImagePicker
        mundo="Vibrantes"
        onSelect={vi.fn()}
        onClose={vi.fn()}
        rawMode
      />,
    );

    expect(
      screen.getByText(/selecciona la imagen que será la portada/i),
    ).toBeInTheDocument();
  });
});
