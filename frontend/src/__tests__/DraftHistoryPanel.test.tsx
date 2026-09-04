import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DraftHistoryPanel } from "@/components/organisms/CoCreation/DraftHistoryPanel";
import type { DraftHistoryEntry } from "@/api/types";

const entries: DraftHistoryEntry[] = [
  { revision: 1, source: "chat", ts: "2026-09-03T10:00:00Z" },
  { revision: 2, source: "autosave", ts: "2026-09-03T10:05:00Z" },
  { revision: 3, source: "author", ts: "2026-09-03T10:10:00Z" },
];

function renderPanel(
  overrides: Partial<Parameters<typeof DraftHistoryPanel>[0]> = {},
) {
  const props = {
    entries,
    currentRevision: 3,
    isOpen: true,
    onClose: vi.fn(),
    onRestore: vi.fn().mockResolvedValue(undefined),
    isRestoring: false,
    isLoading: false,
    error: null,
    onRefresh: vi.fn(),
    ...overrides,
  };
  render(<DraftHistoryPanel {...props} />);
  return props;
}

describe("DraftHistoryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists snapshots with revision, source and timestamp (REQ-CC-15)", () => {
    renderPanel();

    expect(screen.getByText("Revisión 1 · Chat")).toBeInTheDocument();
    expect(screen.getByText("Revisión 2 · Autoguardado")).toBeInTheDocument();
    expect(screen.getByText("Revisión 3 · Autor")).toBeInTheDocument();
  });

  it("marks the current revision and hides its restore button", () => {
    renderPanel();

    expect(screen.getByText("Versión actual")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Restaurar" })).toHaveLength(2);
  });

  it("restores only through the confirmation dialog (REQ-CC-15)", async () => {
    const user = userEvent.setup();
    const props = renderPanel();

    await user.click(screen.getAllByRole("button", { name: "Restaurar" })[0]);
    expect(
      screen.getByText(/¿Restaurar el autoguardado de la revisión 1\?/),
    ).toBeInTheDocument();

    // The dialog's confirm button renders last (portal).
    const restoreButtons = screen.getAllByRole("button", { name: "Restaurar" });
    await user.click(restoreButtons[restoreButtons.length - 1]);
    expect(props.onRestore).toHaveBeenCalledWith(1);
    expect(props.onClose).toHaveBeenCalled();
  });

  it("keeps the dialog open and surfaces the error when restore fails", async () => {
    const user = userEvent.setup();
    const props = renderPanel({
      onRestore: vi.fn().mockRejectedValue(new Error("conflict")),
    });

    await user.click(screen.getAllByRole("button", { name: "Restaurar" })[0]);
    const restoreButtons = screen.getAllByRole("button", { name: "Restaurar" });
    await user.click(restoreButtons[restoreButtons.length - 1]);

    expect(props.onRestore).toHaveBeenCalledWith(1);
    expect(props.onClose).not.toHaveBeenCalled();
    // The panel body alert AND the dialog error alert both surface.
    expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
  });

  it("cancelling the confirmation keeps the panel open", async () => {
    const user = userEvent.setup();
    const props = renderPanel();

    await user.click(screen.getAllByRole("button", { name: "Restaurar" })[0]);
    await user.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(props.onRestore).not.toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("shows an honest empty state", () => {
    renderPanel({ entries: [] });

    expect(
      screen.getByText(/Todavía no hay autoguardados/),
    ).toBeInTheDocument();
  });
});