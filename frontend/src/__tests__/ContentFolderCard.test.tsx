import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  cleanupOldContent,
  getContentDestinations,
  commitContentFolderStep,
  getContentRoot,
  getLastContentMove,
  setContentRoot,
  startContentMove,
} from "@/api/contentRoot";
import type { ContentMoveJob, ContentRootInfo } from "@/api/contentRoot";
import { systemControlAction } from "@/api/wiki";
import { ContentFolderCard } from "@/components/organisms/ContentFolderCard";

vi.mock("@/api/contentRoot", () => ({
  getContentRoot: vi.fn(),
  setContentRoot: vi.fn(),
  commitContentFolderStep: vi.fn(),
  startContentMove: vi.fn(),
  getContentMove: vi.fn(),
  cancelContentMove: vi.fn(),
  getLastContentMove: vi.fn(),
  cleanupOldContent: vi.fn(),
  getContentDestinations: vi.fn(),
}));

vi.mock("@/api/wiki", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/wiki")>();
  return { ...actual, systemControlAction: vi.fn() };
});

const ROOT = "/home/autora/Documentos/Demiurgos";

const INFO: ContentRootInfo = {
  path: ROOT,
  origin: "pointer",
  configured: true,
  recorded_path: ROOT,
  pending_restart: false,
  pinned: false,
  usable: true,
  worlds: 0,
  disk: { free_bytes: 52_428_800_000, total_bytes: 512_000_000_000, volume: null },
  mode: "unknown",
  warning: null,
  reason: null,
};

const JOB: ContentMoveJob = {
  id: "abc123",
  state: "done",
  source: ROOT,
  target: "/media/disco/MisMundos",
  total_files: 10,
  total_bytes: 1000,
  copied_files: 10,
  copied_bytes: 1000,
  skipped: [],
  error: null,
  pointer_written: true,
  cancel_requested: false,
  started_at: "2026-10-29T00:00:00Z",
  finished_at: "2026-10-29T00:01:00Z",
};

const mocked = {
  get: vi.mocked(getContentRoot),
  set: vi.mocked(setContentRoot),
  commit: vi.mocked(commitContentFolderStep),
  start: vi.mocked(startContentMove),
  lastMove: vi.mocked(getLastContentMove),
  cleanup: vi.mocked(cleanupOldContent),
  destinations: vi.mocked(getContentDestinations),
  restart: vi.mocked(systemControlAction),
};

beforeEach(() => {
  vi.clearAllMocks();
  mocked.get.mockResolvedValue(INFO);
  mocked.lastMove.mockResolvedValue({ last_move: null });
  mocked.destinations.mockResolvedValue({ candidates: [], picker: true, native_dialog: false });
});

describe("ContentFolderCard — one action per state", () => {
  it("offers the change when there is no content yet", async () => {
    render(<ContentFolderCard />);
    await screen.findByTestId("content-card-path");

    expect(
      screen.getByRole("button", { name: /cambiar carpeta|change folder/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /mover el contenido|move the content/i }),
    ).not.toBeInTheDocument();
  });

  it("offers the move when the folder already holds worlds", async () => {
    mocked.get.mockResolvedValue({ ...INFO, worlds: 3 });
    render(<ContentFolderCard />);
    await screen.findByTestId("content-card-path");

    expect(
      screen.getByRole("button", { name: /mover el contenido|move the content/i }),
    ).toBeInTheDocument();
    // Moving is the only safe action here: pointing at another folder without
    // copying would hide the worlds that already exist.
    expect(
      screen.queryByRole("button", { name: /cambiar carpeta|change folder/i }),
    ).not.toBeInTheDocument();
  });

  it("does not offer either action when the environment pins the folder", async () => {
    mocked.get.mockResolvedValue({ ...INFO, pinned: true, worlds: 3 });
    render(<ContentFolderCard />);
    await screen.findByTestId("content-card-pinned");

    expect(
      screen.queryByRole("button", { name: /cambiar carpeta|change folder/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /mover el contenido|move the content/i }),
    ).not.toBeInTheDocument();
  });
});

describe("ContentFolderCard — moving", () => {
  it("copies through the job and asks for a restart instead of continuing", async () => {
    mocked.get.mockResolvedValue({ ...INFO, worlds: 3 });
    mocked.start.mockResolvedValue({ job: JOB });
    render(<ContentFolderCard />);
    await screen.findByTestId("content-card-path");

    await userEvent.click(
      screen.getByRole("button", { name: /mover el contenido|move the content/i }),
    );
    const input = screen.getByLabelText(/carpeta destino|destination folder/i);
    await userEvent.type(input, "/media/disco/MisMundos");
    await userEvent.click(
      screen.getByRole("button", { name: /copiar y mover|copy and move/i }),
    );

    await waitFor(() =>
      expect(mocked.start).toHaveBeenCalledWith("/media/disco/MisMundos"),
    );
    expect(await screen.findByTestId("content-move-done")).toBeInTheDocument();
    // Nothing advanced: the app still uses the old folder until it restarts.
    expect(mocked.commit).not.toHaveBeenCalled();
  });

  it("reports the server's refusal instead of pretending it copied", async () => {
    mocked.get.mockResolvedValue({ ...INFO, worlds: 3 });
    mocked.start.mockRejectedValue({
      detail: "the destination folder must be empty: /media/disco already holds content",
    });
    render(<ContentFolderCard />);
    await screen.findByTestId("content-card-path");

    await userEvent.click(
      screen.getByRole("button", { name: /mover el contenido|move the content/i }),
    );
    await userEvent.type(
      screen.getByLabelText(/carpeta destino|destination folder/i),
      "/media/disco",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /copiar y mover|copy and move/i }),
    );

    expect(await screen.findByText(/must be empty/)).toBeInTheDocument();
    expect(screen.queryByTestId("content-move-done")).not.toBeInTheDocument();
    // The fourth row of the table: the content is already there, so the honest
    // action is to use that folder instead of moving.
    expect(await screen.findByTestId("content-move-use-instead")).toBeInTheDocument();
  });

  it("fills the path from a clickable suggestion instead of typing it", async () => {
    mocked.get.mockResolvedValue({ ...INFO, worlds: 3 });
    mocked.destinations.mockResolvedValue({
      candidates: [
        { path: "/media/disco-externo", free_bytes: 1024, is_empty: true, writable: true },
      ],
      picker: true,
      native_dialog: false,
    });
    render(<ContentFolderCard />);
    await screen.findByTestId("content-card-path");

    await userEvent.click(
      screen.getByRole("button", { name: /mover el contenido|move the content/i }),
    );
    const suggestion = await screen.findByTestId("content-suggestion-empty");
    await userEvent.click(suggestion);

    expect(
      screen.getByLabelText(/carpeta destino|destination folder/i),
    ).toHaveValue("/media/disco-externo");
    expect(mocked.start).not.toHaveBeenCalled();
  });

  it("never sends a destination that overlaps the content folder", async () => {
    mocked.get.mockResolvedValue({ ...INFO, worlds: 3 });
    render(<ContentFolderCard />);
    await screen.findByTestId("content-card-path");

    await userEvent.click(
      screen.getByRole("button", { name: /mover el contenido|move the content/i }),
    );
    await userEvent.type(
      screen.getByLabelText(/carpeta destino|destination folder/i),
      `${ROOT}/copias`,
    );
    await userEvent.click(
      screen.getByRole("button", { name: /copiar y mover|copy and move/i }),
    );

    expect(mocked.start).not.toHaveBeenCalled();
    expect(await screen.findByText(/solapa|overlaps/i)).toBeInTheDocument();
  });
});

describe("ContentFolderCard — deleting the old copy", () => {
  const record = {
    schema_version: 1,
    source: "/home/autora/Documentos/Viejo",
    target: ROOT,
    state: "done" as const,
    pointer_written: true,
    finished_at: "2026-10-29T00:01:00Z",
  };

  it("offers the cleanup only after a verified move that is already in use", async () => {
    mocked.lastMove.mockResolvedValue({ last_move: record });
    render(<ContentFolderCard />);

    expect(await screen.findByTestId("content-cleanup-offer")).toBeInTheDocument();
  });

  it("never offers it while the pointer still names the old folder", async () => {
    mocked.lastMove.mockResolvedValue({ last_move: record });
    mocked.get.mockResolvedValue({ ...INFO, path: record.source });
    render(<ContentFolderCard />);
    await screen.findByTestId("content-card-path");

    expect(screen.queryByTestId("content-cleanup-offer")).not.toBeInTheDocument();
  });

  it("needs the exact path typed back before deleting", async () => {
    mocked.lastMove.mockResolvedValue({ last_move: record });
    mocked.cleanup.mockResolvedValue({ removed: record.source, last_move: null });
    render(<ContentFolderCard />);
    await screen.findByTestId("content-cleanup-offer");
    const action = screen.getByRole("button", {
      name: /borrar la carpeta anterior|delete the previous folder/i,
    });
    expect(action).toBeDisabled();

    await userEvent.type(
      screen.getByLabelText(/escribe la ruta anterior|type the previous path/i),
      record.source,
    );
    expect(action).toBeEnabled();
    await userEvent.click(action);

    await waitFor(() =>
      expect(mocked.cleanup).toHaveBeenCalledWith(record.source),
    );
  });
});
