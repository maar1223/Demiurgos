import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExportPdfDialog } from "@/components/organisms/ExportPdfDialog";

function renderDialog(
  overrides: Partial<{
    open: boolean;
    content: string | null;
    fileName: string | null;
    mundo: string;
  }> = {},
) {
  const onClose = vi.fn();
  render(
    <ExportPdfDialog
      open={true}
      onClose={onClose}
      content="# Title\n\nBody"
      fileName="cap1.md"
      mundo="Vibrantes"
      {...overrides}
    />,
  );
  return { onClose };
}

// window.print is a shared spy from setup.ts — reset its call history so
// each test can assert exact call counts.
beforeEach(() => {
  vi.clearAllMocks();
});

describe("ExportPdfDialog", () => {
  it("renders the ficha name without .md extension", () => {
    renderDialog();

    expect(screen.getByText("cap1")).toBeInTheDocument();
    expect(screen.queryByText("cap1.md")).not.toBeInTheDocument();
  });

  it("does not expose a theme toggle", () => {
    renderDialog();

    expect(
      screen.queryByRole("button", { name: "Claro" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Oscuro" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "Tema de la ficha" }),
    ).not.toBeInTheDocument();
  });

  it("renders the print root with the light presentation", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Exportar" }));

    const printRoot = screen.getByTestId("print-root");
    expect(printRoot).not.toHaveAttribute("data-theme");
    expect(printRoot).toHaveClass("bg-white");
    expect(printRoot).toHaveClass("text-neutral-900");
  });

  it("Exportar button calls window.print", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Exportar" }));

    expect(window.print).toHaveBeenCalledTimes(1);
  });

  it("Cancelar button closes the dialog", async () => {
    const user = userEvent.setup();
    const { onClose } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("strips frontmatter from the rendered body", async () => {
    const user = userEvent.setup();
    renderDialog({
      content: "---\nstatus: canon\n---\n# Title\n\nBody",
    });

    await user.click(screen.getByRole("button", { name: "Exportar" }));

    const printRoot = screen.getByTestId("print-root");
    expect(within(printRoot).getByText("Title")).toBeInTheDocument();
    expect(within(printRoot).getByText("Body")).toBeInTheDocument();
    expect(
      within(printRoot).queryByText(/status: canon/i),
    ).not.toBeInTheDocument();
  });

  it("sets document.title to the ficha basename before printing and restores after", async () => {
    const originalTitle = document.title;
    const user = userEvent.setup();
    const { onClose } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Exportar" }));

    // While printing, the title carries the ficha basename so the browser's
    // default "Save as PDF" filename is sensible.
    expect(document.title).toBe("cap1 — Vibrantes");

    // Simulate the browser firing afterprint once the print dialog closes.
    act(() => {
      window.onafterprint?.(new Event("afterprint"));
    });

    expect(document.title).toBe(originalTitle);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(window.onafterprint).toBeNull();
  });
});
