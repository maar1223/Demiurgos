import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getFileContent, listHistory, restoreFile } from "@/api/wiki";
import type {
  FileContent,
  HistoryListResponse,
  RestoreFileRequest,
  SuccessResponse,
} from "@/api/types";
import { useFileContent } from "@/hooks/useFileContent";
import { useFileHistory } from "@/hooks/useFileHistory";

vi.mock("@/api/wiki", () => ({
  getFileContent: vi.fn(),
  listHistory: vi.fn(),
  restoreFile: vi.fn(),
}));

const getFileContentMock = vi.mocked(getFileContent);
const listHistoryMock = vi.mocked(listHistory);
const restoreFileMock = vi.mocked(restoreFile);

function wrapper({ children }: { children: React.ReactNode }) {
  return <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>;
}

const backendFile: FileContent = {
  path: "draft.md",
  content: "# Draft",
  size: 7,
  revision: "sha256-revision",
};

const history: HistoryListResponse = {
  target: "lore/draft.md",
  entries: [
    {
      id: "entry-1",
      snapshot_id: "snapshot-1",
      target: "lore/draft.md",
      created_at: "2026-08-07T19:00:00Z",
      content: "# Previous draft",
      revision: "sha256-previous",
      size: 16,
    },
  ],
};

const restoreRequest: RestoreFileRequest = {
  path: "lore/draft.md",
  snapshot_id: "snapshot-1",
  content: "# Previous draft",
  base_revision: "sha256-current",
  proposed_digest: "sha256-previous",
  edit_id: "restore-1",
  token: "restore-token",
};

describe("PR4 file hooks and response contracts", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("accepts the current file response and exposes its revision", async () => {
    getFileContentMock.mockResolvedValue(backendFile);

    const { result } = renderHook(
      () => useFileContent("vibrantes", "lore", "draft.md"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.file).toEqual(backendFile));

    expect(getFileContentMock).toHaveBeenCalledWith(
      "vibrantes",
      "lore",
      "draft.md",
    );
    expect(result.current.revision).toBe("sha256-revision");
    expect(result.current.file?.size).toBe(7);
    expect(result.current.file?.name).toBeUndefined();
  });

  it("loads history and revalidates after a gated restore", async () => {
    const restored: SuccessResponse = {
      success: true,
      path: restoreRequest.path,
    };
    listHistoryMock.mockResolvedValue(history);
    restoreFileMock.mockResolvedValue(restored);

    const { result } = renderHook(
      () => useFileHistory("vibrantes", restoreRequest.path),
      { wrapper },
    );

    await waitFor(() => expect(result.current.entries).toEqual(history.entries));

    await act(async () => {
      await result.current.restore(restoreRequest);
    });

    expect(listHistoryMock).toHaveBeenCalledTimes(2);
    expect(listHistoryMock).toHaveBeenNthCalledWith(
      1,
      "vibrantes",
      restoreRequest.path,
    );
    expect(restoreFileMock).toHaveBeenCalledWith("vibrantes", restoreRequest);
    expect(result.current.isRestoring).toBe(false);
    expect(result.current.restoreError).toBeNull();
  });
});
