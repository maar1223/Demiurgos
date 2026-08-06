import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MoveToSectionDialog } from "@/components/organisms/MoveToSectionDialog";

function renderDialog(
  source: { section: string; path: string } = { section: "lore", path: "notas.md" },
) {
  const onConfirm = vi.fn();
  const onClose = vi.fn();
  render(
    <MoveToSectionDialog source={source} onConfirm={onConfirm} onClose={onClose} />,
  );
  return { onConfirm, onClose };
}

describe("MoveToSectionDialog", () => {
  it("lists every destination section except the current one", () => {
    renderDialog({ section: "lore", path: "notas.md" });

    const dialog = screen.getByRole("dialog", { name: /mover a sección/i });
    expect(
      screen.getByRole("radio", { name: "Personajes" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Sagas" })).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Referencias" }),
    ).toBeInTheDocument();
    // The current section is never offered as a destination
    expect(
      screen.queryByRole("radio", { name: "Lore" }),
    ).not.toBeInTheDocument();
    expect(dialog).toHaveTextContent(/notas\.md/);
  });

  it("excludes whatever the current section is", () => {
    renderDialog({ section: "personajes", path: "anisa.md" });

    expect(
      screen.queryByRole("radio", { name: "Personajes" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Lore" })).toBeInTheDocument();
  });

  it("keeps Confirmar disabled until a section is chosen", async () => {
    const user = userEvent.setup();
    renderDialog();

    const confirm = screen.getByRole("button", { name: "Confirmar" });
    expect(confirm).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: "Sagas" }));
    expect(confirm).toBeEnabled();
  });

  it("confirms with the chosen section only", async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderDialog();

    await user.click(screen.getByRole("radio", { name: "Personajes" }));
    await user.click(screen.getByRole("button", { name: "Confirmar" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledWith("personajes");
  });

  it("switching the selection replaces the previous choice", async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderDialog();

    await user.click(screen.getByRole("radio", { name: "Personajes" }));
    await user.click(screen.getByRole("radio", { name: "Referencias" }));
    await user.click(screen.getByRole("button", { name: "Confirmar" }));

    expect(onConfirm).toHaveBeenCalledWith("referencias");
  });

  it("Cancelar closes without confirming", async () => {
    const user = userEvent.setup();
    const { onConfirm, onClose } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(onClose).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("closes on Escape", () => {
    const { onClose } = renderDialog();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("closes when the overlay outside the dialog is clicked", async () => {
    const user = userEvent.setup();
    const { onClose } = renderDialog();

    const overlay = document.querySelector(".fixed.inset-0");
    expect(overlay).not.toBeNull();
    await user.click(overlay as HTMLElement);
    expect(onClose).toHaveBeenCalled();
  });

  it("warns that the section change is irreversible", () => {
    renderDialog();

    expect(screen.getByRole("alert")).toHaveTextContent(
      /no se puede deshacer/i,
    );
  });
});
