import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HistoryPanel from "@/components/organisms/HistoryPanel";
import type { HistoryEntry } from "@/api/types";

vi.mock("@/hooks/useFileHistory", () => ({
  useFileHistory: vi.fn(),
}));

vi.mock("@/api/wiki", () => ({
  requestConfirmation: vi.fn(),
  suggestEdit: vi.fn(),
  saveFile: vi.fn(),
  createFile: vi.fn(),
  restoreFile: vi.fn(),
}));

import { useFileHistory } from "@/hooks/useFileHistory";
import {
  createFile,
  requestConfirmation,
  restoreFile,
  saveFile,
} from "@/api/wiki";

const historyEntries: HistoryEntry[] = [
  {
    id: "entry-current",
    snapshot_id: "snapshot-current",
    target: "lore/chapter.md",
    created_at: "2026-08-07T20:00:00Z",
    content: "# Current",
    revision: "current-revision",
    size: 9,
  },
  {
    id: "entry-old",
    snapshot_id: "snapshot-old",
    target: "lore/chapter.md",
    created_at: "2026-08-07T18:00:00Z",
    content: "# Old",
    revision: "old-revision",
    size: 6,
  },
  {
    id: "entry-middle",
    snapshot_id: "snapshot-middle",
    target: "lore/chapter.md",
    created_at: "2026-08-07T19:00:00Z",
    content: "# Middle",
    revision: "middle-revision",
    size: 9,
  },
];

const restore = vi.fn();
const mutate = vi.fn();
const onClose = vi.fn();
const onRestored = vi.fn();

function renderPanel(
  overrides: Partial<{
    entries: HistoryEntry[];
    isLoading: boolean;
    error: Error | undefined;
    restoreError: Error | null;
    currentRevision: string | null;
    currentContent: string;
    open: boolean;
  }> = {},
) {
  const history = {
    target: "lore/chapter.md",
    entries: overrides.entries ?? historyEntries,
    isLoading: overrides.isLoading ?? false,
    isValidating: false,
    isRestoring: false,
    error: overrides.error,
    restoreError: overrides.restoreError ?? null,
    mutate,
    restore,
  };
  vi.mocked(useFileHistory).mockReturnValue(history);

  return render(
    <HistoryPanel
      mundo="vibrantes"
      section="lore"
      path="chapter.md"
      currentRevision={
        overrides.currentRevision === undefined
          ? "current-revision"
          : overrides.currentRevision
      }
      currentContent={overrides.currentContent ?? "# Current"}
      open={overrides.open ?? true}
      onClose={onClose}
      onRestored={onRestored}
    />,
  );
}

describe("HistoryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    restore.mockResolvedValue({ success: true, path: "chapter.md" });
    mutate.mockResolvedValue(undefined);
    onRestored.mockResolvedValue(undefined);
    vi.mocked(requestConfirmation).mockResolvedValue({
      token: "restore-token",
      expires_at: "2026-08-08T00:00:00Z",
      proposed_digest: "old-revision",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders loading, error, and empty states", () => {
    const { unmount } = renderPanel({ isLoading: true });
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    unmount();

    renderPanel({ error: new Error("History unavailable") });
    expect(screen.getByRole("alert")).toHaveTextContent("History unavailable");
    unmount();

    renderPanel({ entries: [] });
    expect(screen.getByText("No history available.")).toBeInTheDocument();
  });

  it("orders snapshots newest-first and protects the current version", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-07T21:00:00Z"));
    renderPanel();

    const list = screen.getByRole("list");
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("Saved 1 hour ago"),
      expect.stringContaining("Saved 2 hours ago"),
      expect.stringContaining("Saved 3 hours ago"),
    ]);
    expect(within(rows[0]).getByText("Current version")).toBeInTheDocument();
    expect(within(rows[0]).queryByRole("button", { name: "Restore" })).toBeNull();
    expect(within(rows[2]).getByRole("button", { name: "Restore" })).toBeInTheDocument();
  });

  it("labels snapshots with the saved-on timestamp, never the raw hash", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-07T21:00:00Z"));
    renderPanel();

    const list = screen.getByRole("list");
    const rows = within(list).getAllByRole("listitem");

    // The raw snapshot hash is never rendered as a label in the panel.
    expect(screen.queryByText(/snapshot-/)).not.toBeInTheDocument();
    expect(rows[0]).not.toHaveTextContent("snapshot-current");

    // The primary label is the localized save timestamp.
    expect(rows[0]).toHaveTextContent("Version saved on");

    // Relative time and size are retained as human-readable metadata.
    expect(rows[0]).toHaveTextContent("Saved 1 hour ago · 9 bytes");
    expect(rows[2]).toHaveTextContent("Saved 3 hours ago · 6 bytes");
  });

  it("requests history with the canonical mundo-relative target", () => {
    renderPanel();
    // The history API resolves a mundo-relative path with the section prefix
    // (`lore/chapter.md`), not the section-relative `path` prop (`chapter.md`).
    expect(useFileHistory).toHaveBeenCalledWith("vibrantes", "lore/chapter.md");
  });

  it("confirms restore and uses only the gated restore contract", async () => {
    const user = userEvent.setup();
    renderPanel();

    const oldRow = within(screen.getByRole("list")).getAllByRole("listitem")[2];
    await user.click(within(oldRow).getByRole("button", { name: "Restore" }));
    const confirmation = screen.getByRole("dialog", { name: "Restore version" });
    expect(confirmation).toHaveTextContent("snapshot-old");
    await user.click(within(confirmation).getByRole("button", { name: "Restore" }));

    await waitFor(() => {
      expect(requestConfirmation).toHaveBeenCalledWith(
        "vibrantes",
        "lore",
        "chapter.md",
        expect.objectContaining({
          edit_id: "restore-snapshot-old",
          kind: "restore",
          base_revision: "current-revision",
          snapshot_id: "snapshot-old",
        }),
      );
      expect(restore).toHaveBeenCalledWith({
        path: "lore/chapter.md",
        snapshot_id: "snapshot-old",
        content: "# Old",
        base_revision: "current-revision",
        proposed_digest: "old-revision",
        edit_id: "restore-snapshot-old",
        token: "restore-token",
      });
      expect(onRestored).toHaveBeenCalled();
    });
    expect(saveFile).not.toHaveBeenCalled();
    expect(createFile).not.toHaveBeenCalled();
    expect(restoreFile).not.toHaveBeenCalled();
  });

  it("reloads history after a stale restore without retrying an unsafe write", async () => {
    const user = userEvent.setup();
    restore.mockRejectedValue({ status: 409, detail: "stale_base" });
    renderPanel();

    const oldRow = within(screen.getByRole("list")).getAllByRole("listitem")[2];
    await user.click(within(oldRow).getByRole("button", { name: "Restore" }));
    await user.click(
      within(screen.getByRole("dialog", { name: "Restore version" })).getByRole(
        "button",
        { name: "Restore" },
      ),
    );

    expect(
      (await screen.findAllByText(
        "The file changed. History was reloaded; review the restore again.",
      )).length,
    ).toBeGreaterThan(0);
    expect(mutate).toHaveBeenCalled();
    expect(onRestored).not.toHaveBeenCalled();
  });

  it("does not render or write while closed", () => {
    renderPanel({ open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(requestConfirmation).not.toHaveBeenCalled();
    expect(restore).not.toHaveBeenCalled();
  });
});
