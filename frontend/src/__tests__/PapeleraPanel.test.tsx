import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PapeleraPanel } from "@/components/organisms/PapeleraPanel";
import { emptyTrash, listTrash, purgeTrashItem } from "@/api/wiki";
import type { Mock } from "vitest";
import type { TrashEntry } from "@/api/types";

vi.mock("@/api/wiki", () => ({
  listTrash: vi.fn(),
  purgeTrashItem: vi.fn(),
  emptyTrash: vi.fn(),
  restoreFromTrash: vi.fn(),
}));

function entry(overrides: Partial<TrashEntry> = {}): TrashEntry {
  return {
    entry_id: "e1",
    section: "lore",
    original_path: "lore/ciudades/Avalor.md",
    kind: "file",
    deleted_at: "2026-09-01T10:00:00Z",
    size: 1024,
    ...overrides,
  };
}

function renderPanel() {
  return render(
    <PapeleraPanel
      mundo="mundo"
      open
      onClose={vi.fn()}
      onRestored={vi.fn()}
      onPurged={vi.fn()}
      onTtlPurged={vi.fn()}
    />,
  );
}

// REQ-PIA-08 (destructive confirm): purge and empty-trash are irreversible, so
// their confirm action must use the danger treatment, not the primary style.
describe("PapeleraPanel destructive confirms (REQ-PIA-08)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (listTrash as Mock).mockResolvedValue({ entries: [entry()], purged: 0 });
    (purgeTrashItem as Mock).mockResolvedValue(undefined);
    (emptyTrash as Mock).mockResolvedValue(undefined);
  });

  it("uses the danger treatment for the per-entry purge confirm", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Purgar" }));

    const dialog = screen.getByRole("dialog", { name: "Purgar" });
    const confirm = within(dialog).getByRole("button", { name: "Purgar" });
    expect(confirm.className).toContain("bg-status-error");
    expect(confirm.className).not.toContain("bg-action");
  });

  it("uses the danger treatment for the empty-trash confirm", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", { name: "Vaciar papelera" }),
    );

    const dialog = screen.getByRole("dialog", { name: "Vaciar papelera" });
    const confirm = within(dialog).getByRole("button", {
      name: "Vaciar papelera",
    });
    expect(confirm.className).toContain("bg-status-error");
    expect(confirm.className).not.toContain("bg-action");
  });
});
