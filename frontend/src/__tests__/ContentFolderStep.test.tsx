import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  commitContentFolderStep,
  getContentRoot,
  setContentRoot,
} from "@/api/contentRoot";
import type { ContentRootInfo } from "@/api/contentRoot";
import { systemControlAction } from "@/api/wiki";
import {
  ContentFolderStep,
  formatBytes,
} from "@/components/organisms/ContentFolderStep";

vi.mock("@/api/contentRoot", () => ({
  getContentRoot: vi.fn(),
  setContentRoot: vi.fn(),
  commitContentFolderStep: vi.fn(),
}));

vi.mock("@/api/wiki", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/wiki")>();
  return { ...actual, systemControlAction: vi.fn() };
});

const INFO: ContentRootInfo = {
  path: "/home/autora/Documentos/Demiurgos",
  origin: "pointer",
  configured: true,
  recorded_path: "/home/autora/Documentos/Demiurgos",
  pending_restart: false,
  pinned: false,
  usable: true,
  worlds: 3,
  disk: { free_bytes: 52_428_800_000, total_bytes: 512_000_000_000, volume: null },
  mode: "unknown",
  warning: null,
  reason: null,
};

const mocked = {
  get: vi.mocked(getContentRoot),
  set: vi.mocked(setContentRoot),
  commit: vi.mocked(commitContentFolderStep),
  restart: vi.mocked(systemControlAction),
};

beforeEach(() => {
  vi.clearAllMocks();
  mocked.get.mockResolvedValue(INFO);
  mocked.commit.mockResolvedValue({} as never);
});

describe("ContentFolderStep", () => {
  it("shows the folder in use, how many worlds it holds and the free space", async () => {
    render(<ContentFolderStep onDone={vi.fn()} />);

    expect(await screen.findByTestId("content-folder-path")).toHaveTextContent(
      "/home/autora/Documentos/Demiurgos",
    );
    expect(screen.getByTestId("content-folder-worlds")).toHaveTextContent("3");
    expect(screen.getByTestId("content-folder-free")).toHaveTextContent("48.8 GB");
  });

  it("accepting the folder commits the step and moves on", async () => {
    const onDone = vi.fn();
    render(<ContentFolderStep onDone={onDone} />);
    await screen.findByTestId("content-folder-path");

    await userEvent.click(
      screen.getByRole("button", { name: /usar esta carpeta|use this folder/i }),
    );

    await waitFor(() => expect(mocked.commit).toHaveBeenCalledTimes(1));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("changing the folder records it and asks for a restart instead of continuing", async () => {
    const onDone = vi.fn();
    mocked.set.mockResolvedValue({
      ...INFO,
      path: "/mnt/discos/mundos",
      recorded_path: "/mnt/discos/mundos",
      restart_required: true,
    });
    render(<ContentFolderStep onDone={onDone} />);
    await screen.findByTestId("content-folder-path");

    await userEvent.click(
      screen.getByRole("button", { name: /cambiar carpeta|change folder/i }),
    );
    const input = screen.getByLabelText(/nueva carpeta|new folder/i);
    await userEvent.clear(input);
    await userEvent.type(input, "/mnt/discos/mundos");
    await userEvent.click(
      screen.getByRole("button", { name: /guardar carpeta|save folder/i }),
    );

    await waitFor(() =>
      expect(mocked.set).toHaveBeenCalledWith("/mnt/discos/mundos"),
    );
    expect(await screen.findByTestId("content-folder-restart")).toBeInTheDocument();
    // The world must NOT be offered yet: it would land in the folder the app
    // still has open.
    expect(onDone).not.toHaveBeenCalled();
    expect(mocked.commit).not.toHaveBeenCalled();
  });

  it("asks for a restart on load when a recorded folder already differs", async () => {
    mocked.get.mockResolvedValue({ ...INFO, pending_restart: true });
    render(<ContentFolderStep onDone={vi.fn()} />);

    expect(await screen.findByTestId("content-folder-restart")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /usar esta carpeta|use this folder/i }),
    ).not.toBeInTheDocument();
  });

  it("restarts the app from the restart panel", async () => {
    mocked.get.mockResolvedValue({ ...INFO, pending_restart: true });
    render(<ContentFolderStep onDone={vi.fn()} />);
    await screen.findByTestId("content-folder-restart");

    await userEvent.click(
      screen.getByRole("button", { name: /reiniciar demiurgos|restart demiurgos/i }),
    );

    expect(mocked.restart).toHaveBeenCalledWith("restart");
  });

  it("offers the change when the launcher merely echoed the pointer", async () => {
    mocked.get.mockResolvedValue({ ...INFO, origin: "env", pinned: false });
    render(<ContentFolderStep onDone={vi.fn()} />);
    await screen.findByTestId("content-folder-path");

    expect(
      screen.getByRole("button", { name: /cambiar carpeta|change folder/i }),
    ).toBeInTheDocument();
  });

  it("does not offer a change when the environment pins the folder", async () => {
    mocked.get.mockResolvedValue({ ...INFO, origin: "env", pinned: true });
    render(<ContentFolderStep onDone={vi.fn()} />);

    expect(await screen.findByTestId("content-folder-env")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /cambiar carpeta|change folder/i }),
    ).not.toBeInTheDocument();
    // The step can still be accepted: the folder is configured, just not here.
    expect(
      screen.getByRole("button", { name: /usar esta carpeta|use this folder/i }),
    ).toBeInTheDocument();
  });

  it("reports a refusal from the API instead of pretending it saved", async () => {
    mocked.set.mockRejectedValue({
      detail: "the content folder must be an existing directory: /nope",
    });
    render(<ContentFolderStep onDone={vi.fn()} />);
    await screen.findByTestId("content-folder-path");

    await userEvent.click(
      screen.getByRole("button", { name: /cambiar carpeta|change folder/i }),
    );
    const input = screen.getByLabelText(/nueva carpeta|new folder/i);
    await userEvent.clear(input);
    await userEvent.type(input, "/nope");
    await userEvent.click(
      screen.getByRole("button", { name: /guardar carpeta|save folder/i }),
    );

    expect(await screen.findByText(/existing directory/)).toBeInTheDocument();
    expect(screen.queryByTestId("content-folder-restart")).not.toBeInTheDocument();
  });
});

describe("formatBytes", () => {
  it("never invents a number", () => {
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(undefined)).toBe("—");
    expect(formatBytes(-1)).toBe("—");
  });

  it("scales to a short human figure", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1024)).toBe("1 KB");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(52_428_800_000)).toBe("48.8 GB");
  });
});
