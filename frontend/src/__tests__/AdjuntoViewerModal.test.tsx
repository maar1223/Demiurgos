import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AdjuntoViewerModal } from "@/components/organisms/AdjuntoViewerModal";
import { ApiError } from "@/api/types";
import type { MethodologyAdjunto } from "@/api/types";

const getAdjuntoContent = vi.hoisted(() => vi.fn());
vi.mock("@/api/methodologies", () => ({ getAdjuntoContent }));

const ADJUNTO: MethodologyAdjunto = {
  path: "anexos/guia-narrativa.md",
  sha256: "a".repeat(64),
  bytes: 2048,
  nivel: "N2",
};

type Overrides = Partial<{
  open: boolean;
  skillId: string;
  version: string;
  adjunto: MethodologyAdjunto | null;
  onClose: () => void;
}>;

function renderModal(overrides: Overrides = {}) {
  const onClose = vi.fn();
  const utils = render(
    <AdjuntoViewerModal
      open
      skillId="guided-character-v1"
      version="1.2.0"
      adjunto={ADJUNTO}
      onClose={onClose}
      {...overrides}
    />,
  );
  return { onClose, ...utils };
}

/** A promise that never settles — pins the component in its loading state. */
const pending = () => new Promise<string>(() => {});

beforeEach(() => {
  getAdjuntoContent.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("AdjuntoViewerModal render state", () => {
  it("renders nothing when open is false", () => {
    getAdjuntoContent.mockReturnValue(pending());
    renderModal({ open: false });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("AdjuntoViewerModal fetch states", () => {
  it("shows a spinner while the carrier is loading", () => {
    getAdjuntoContent.mockReturnValue(pending());
    renderModal();

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("requests the exact pinned exemplar and renders its markdown", async () => {
    getAdjuntoContent.mockResolvedValue("# Guía\n\nContenido del anexo.\n");
    renderModal();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Guía" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Contenido del anexo/)).toBeInTheDocument();
    expect(getAdjuntoContent).toHaveBeenCalledWith(
      "guided-character-v1",
      "1.2.0",
      "anexos/guia-narrativa.md",
    );
  });

  it("shows an error banner with Retry that refetches", async () => {
    getAdjuntoContent
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce("# Recuperado\n");
    const user = userEvent.setup();
    renderModal();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /no se pudo cargar el adjunto/i,
    );

    await user.click(screen.getByRole("button", { name: "Reintentar" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Recuperado" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(getAdjuntoContent).toHaveBeenCalledTimes(2));
  });

  it("renders a muted auth note on 401 — never an error banner", async () => {
    getAdjuntoContent.mockRejectedValue(
      new ApiError(401, "Authentication required."),
    );
    renderModal();

    expect(await screen.findByTestId("adjunto-unauthorized")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("adjunto-unavailable")).not.toBeInTheDocument();
  });

  it.each([404, 422])(
    "renders an unavailable note on %i, distinguishable from the auth note",
    async (status) => {
      getAdjuntoContent.mockRejectedValue(
        new ApiError(status, "A pinned attachment is unavailable or has drifted."),
      );
      renderModal();

      expect(await screen.findByTestId("adjunto-unavailable")).toBeInTheDocument();
      expect(screen.queryByTestId("adjunto-unauthorized")).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );
});

describe("AdjuntoViewerModal header identity", () => {
  it("shows the basename without .md, the nivel badge, and the formatted bytes", () => {
    getAdjuntoContent.mockReturnValue(pending());
    renderModal();

    expect(
      screen.getByRole("heading", { level: 2, name: "guia-narrativa" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("guia-narrativa.md")).not.toBeInTheDocument();
    expect(screen.getByText("N2")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
  });
});

describe("AdjuntoViewerModal scroll", () => {
  it("renders the full long markdown and keeps the body scrollable", async () => {
    const longContent = Array.from(
      { length: 60 },
      (_, index) => `## Sección ${index}\n\nPárrafo ${index}.`,
    ).join("\n\n");
    getAdjuntoContent.mockResolvedValue(longContent);
    renderModal();

    await screen.findByRole("heading", { level: 2, name: "Sección 59" });

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveClass("max-h-[80vh]", "flex-col");

    const body = screen.getByTestId("adjunto-viewer-body");
    expect(body).toHaveClass("min-h-0", "flex-1", "overflow-y-auto");

    // Every section renders inside the scroll container — nothing is clipped
    // or truncated by the layout.
    expect(within(body).getAllByRole("heading", { level: 2 })).toHaveLength(60);
    expect(screen.getByText("Párrafo 59.")).toBeInTheDocument();
  });
});

describe("AdjuntoViewerModal dismissal", () => {
  it("closes when the X button is clicked", async () => {
    getAdjuntoContent.mockReturnValue(pending());
    const user = userEvent.setup();
    const { onClose } = renderModal();

    await user.click(screen.getByRole("button", { name: "Cerrar" }));

    expect(onClose).toHaveBeenCalled();
  });

  it("closes on Escape", () => {
    getAdjuntoContent.mockReturnValue(pending());
    const { onClose } = renderModal();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalled();
  });

  it("closes when the backdrop overlay is clicked", async () => {
    getAdjuntoContent.mockReturnValue(pending());
    const user = userEvent.setup();
    const { onClose } = renderModal();

    const overlay = document.querySelector(".fixed.inset-0.z-50");
    expect(overlay).not.toBeNull();
    await user.click(overlay as HTMLElement);

    expect(onClose).toHaveBeenCalled();
  });
});

describe("AdjuntoViewerModal accessibility", () => {
  it("exposes a labelled dialog with aria-modal", () => {
    getAdjuntoContent.mockReturnValue(pending());
    renderModal();

    const dialog = screen.getByRole("dialog", { name: "guia-narrativa" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby", "adjunto-viewer-title");
  });

  it("moves initial focus to the close button", () => {
    getAdjuntoContent.mockReturnValue(pending());
    renderModal();

    expect(screen.getByRole("button", { name: "Cerrar" })).toHaveFocus();
  });

  it("traps Tab focus inside the dialog and wraps with Shift+Tab", async () => {
    getAdjuntoContent.mockRejectedValue(new Error("boom"));
    renderModal();

    await screen.findByRole("alert");
    const dialog = screen.getByRole("dialog");
    const focusables = dialog.querySelectorAll<HTMLElement>(
      "input, button, [href], select, textarea, [tabindex]:not([tabindex='-1'])",
    );
    expect(focusables.length).toBeGreaterThanOrEqual(2);

    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    // Tab from the last focusable wraps to the first
    last.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(first).toHaveFocus();

    // Shift+Tab from the first focusable wraps to the last
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });
});
