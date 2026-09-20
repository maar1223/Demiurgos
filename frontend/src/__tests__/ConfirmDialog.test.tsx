import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";

function renderDialog(props: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  return render(
    <ConfirmDialog
      title="Eliminar permanentemente"
      message="¿Eliminar permanentemente el mundo «Avalor»? Esta acción no se puede deshacer."
      confirmLabel="Eliminar permanentemente"
      onConfirm={vi.fn()}
      onClose={vi.fn()}
      {...props}
    />,
  );
}

describe("ConfirmDialog", () => {
  it("uses the primary treatment for the confirm action by default", () => {
    renderDialog();
    const confirm = screen.getByRole("button", {
      name: "Eliminar permanentemente",
    });
    // Default must preserve the historical dialog for every existing caller.
    expect(confirm.className).toContain("bg-action");
    expect(confirm.className).not.toContain("bg-status-error");
  });

  it("uses the danger treatment when confirmVariant is danger (REQ-PIA-08)", () => {
    renderDialog({ confirmVariant: "danger" });
    const confirm = screen.getByRole("button", {
      name: "Eliminar permanentemente",
    });
    expect(confirm.className).toContain("bg-status-error");
    expect(confirm.className).not.toContain("bg-action");
  });

  it("keeps the cancel action non-destructive regardless of confirmVariant", () => {
    renderDialog({ confirmVariant: "danger" });
    const cancel = screen.getByRole("button", { name: "Cancelar" });
    expect(cancel.className).not.toContain("bg-status-error");
  });
});
