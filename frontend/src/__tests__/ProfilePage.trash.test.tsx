import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import ProfilePage from "@/pages/ProfilePage";
import { useWorlds } from "@/hooks/useWorlds";
import { listTrash, permanentDelete, restoreWorld } from "@/api/worlds";
import { getIdeaCaptureStatus } from "@/api/ideaCapture";
import { getReadiness } from "@/api/onboarding";
import type { IdeaCaptureStatus, WorldInfo, WorldTrashEntry } from "@/api/types";
import type { Mock } from "vitest";

vi.mock("@/hooks/useWorlds", () => ({ useWorlds: vi.fn() }));
vi.mock("@/api/worlds", () => ({
  deleteWorld: vi.fn(),
  listTrash: vi.fn(),
  restoreWorld: vi.fn(),
  permanentDelete: vi.fn(),
}));
vi.mock("@/api/ideaCapture", () => ({ getIdeaCaptureStatus: vi.fn() }));
vi.mock("@/api/onboarding", () => ({ getReadiness: vi.fn() }));

vi.mock("@/hooks/useLocalDevAuth", () => ({
  useLocalDevAuth: () => ({
    status: {
      mode: "local-dev",
      enabled: true,
      authenticated: true,
      label: "Local development user",
    },
    isLoading: false,
    error: undefined,
    start: vi.fn(),
    logout: vi.fn(),
  }),
}));

vi.mock("@/hooks/useAuthSession", () => ({
  useAuthSession: () => ({
    status: {
      mode: "local-dev",
      enabled: true,
      authenticated: true,
      label: "Local development user",
    },
    isLoading: false,
    error: null,
  }),
}));

vi.mock("@/components/organisms/Navbar", () => ({
  Navbar: () => <div aria-label="navbar" />,
}));
vi.mock("@/components/organisms/IdeaCapturePanel", () => ({
  IdeaCapturePanel: () => <div>idea capture</div>,
}));
vi.mock("@/components/organisms/AssistantSettingsPanel", () => ({
  AssistantSettingsPanel: () => <div>assistant settings panel</div>,
}));

const useWorldsMock = vi.mocked(useWorlds);
const listTrashMock = vi.mocked(listTrash);
const restoreWorldMock = vi.mocked(restoreWorld);
const permanentDeleteMock = vi.mocked(permanentDelete);
const getIdeaCaptureStatusMock = vi.mocked(getIdeaCaptureStatus);

// "Avalor" is deleted — it only appears in the recycle bin, not in the
// worlds list (Vibrantes is the only remaining world).
const remainingWorld: WorldInfo = {
  name: "Vibrantes",
  path: "mundos/Vibrantes",
  lore_count: 7,
  character_count: 2, reference_count: 0,
};

const trashEntry: WorldTrashEntry = {
  world_name: "Avalor",
  deleted_at: "2026-08-22T10:00:00Z",
  size_bytes: 1024000,
  lore_count: 42,
  character_count: 15,
  days_remaining: 28,
};

let mutateSpy = vi.fn();

function renderProfile() {
  return render(
    <SWRConfig value={{ provider: () => new Map() }}>
      <ProfilePage />
    </SWRConfig>,
  );
}

async function openMundosTab() {
  fireEvent.click(screen.getByRole("button", { name: "Mundos" }));
  await screen.findByText("Zona peligrosa");
}

beforeEach(() => {
  vi.clearAllMocks();
  mutateSpy = vi.fn();
  useWorldsMock.mockReturnValue({
    worlds: [remainingWorld],
    isLoading: false,
    isValidating: false,
    error: undefined,
    mutate: mutateSpy,
  });
  getIdeaCaptureStatusMock.mockResolvedValue({
    config: { active_world: "" },
  } as unknown as IdeaCaptureStatus);
  (getReadiness as Mock).mockResolvedValue({
    local_editor: { probe: "local_editor", ok: true, detail: "ok" },
    cards: {},
    offline: { local_ready: true, remote_pending: [] },
    legacy: [],
  });
  listTrashMock.mockResolvedValue([trashEntry]);
  restoreWorldMock.mockResolvedValue(undefined);
  permanentDeleteMock.mockResolvedValue(undefined);
});

describe("ProfilePage — Papelera de mundos (W-5)", () => {
  it("lists trashed worlds with metadata and action buttons", async () => {
    renderProfile();
    await openMundosTab();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Restaurar" })).toBeInTheDocument(),
    );
    expect(screen.getByText("Avalor")).toBeInTheDocument();
    expect(screen.getByText(/eliminado el 22 ago 2026/)).toBeInTheDocument();
    expect(screen.getByText("28 días")).toBeInTheDocument();
    expect(screen.getByText("Lore 42")).toBeInTheDocument();
    expect(screen.getByText("Personajes 15")).toBeInTheDocument();
    expect(screen.getByText(/1000\.0 KB/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Eliminar permanentemente" })).toBeInTheDocument();
  });

  it("shows the empty state when the recycle bin has no entries", async () => {
    listTrashMock.mockResolvedValue([]);
    renderProfile();
    await openMundosTab();

    await waitFor(() => expect(screen.getByText("La papelera está vacía")).toBeInTheDocument());
  });

  it("restores a world, refetches the trash list and refreshes the worlds list", async () => {
    listTrashMock
      .mockResolvedValueOnce([trashEntry]) // initial load
      .mockResolvedValueOnce([]); // refetch after restore
    renderProfile();
    await openMundosTab();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Restaurar" })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Restaurar" }));

    await waitFor(() => expect(restoreWorldMock).toHaveBeenCalledWith("Avalor"));
    await waitFor(() => expect(screen.getByText("La papelera está vacía")).toBeInTheDocument());
    expect(listTrashMock).toHaveBeenCalledTimes(2);
    expect(mutateSpy).toHaveBeenCalled();
  });

  it("permanently deletes a world only after confirming the dialog", async () => {
    listTrashMock
      .mockResolvedValueOnce([trashEntry]) // initial load
      .mockResolvedValueOnce([]); // refetch after purge
    renderProfile();
    await openMundosTab();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Eliminar permanentemente" })).toBeInTheDocument(),
    );
    const rowButton = screen.getByRole("button", { name: "Eliminar permanentemente" });

    // Cancel first — nothing is purged.
    fireEvent.click(rowButton);
    let dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/Avalor/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(permanentDeleteMock).not.toHaveBeenCalled();

    // Confirm — permanent delete + list/worlds refresh.
    fireEvent.click(rowButton);
    dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Eliminar permanentemente" }));

    await waitFor(() => expect(permanentDeleteMock).toHaveBeenCalledWith("Avalor"));
    await waitFor(() => expect(screen.getByText("La papelera está vacía")).toBeInTheDocument());
    expect(mutateSpy).toHaveBeenCalled();
  });
});