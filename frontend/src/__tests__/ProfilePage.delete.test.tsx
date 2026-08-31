import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SWRConfig } from "swr";
import ProfilePage from "@/pages/ProfilePage";
import { useWorlds } from "@/hooks/useWorlds";
import { deleteWorld, listTrash, permanentDelete, restoreWorld } from "@/api/worlds";
import { getIdeaCaptureStatus } from "@/api/ideaCapture";
import { getReadiness } from "@/api/onboarding";
import { ACTIVE_WORLD_STORAGE_KEY } from "@/lib/currentWorld";
import { ApiError, type IdeaCaptureStatus, type WorldInfo, type WorldTrashEntry } from "@/api/types";
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
const deleteWorldMock = vi.mocked(deleteWorld);
const listTrashMock = vi.mocked(listTrash);
const restoreWorldMock = vi.mocked(restoreWorld);
const permanentDeleteMock = vi.mocked(permanentDelete);
const getIdeaCaptureStatusMock = vi.mocked(getIdeaCaptureStatus);

const worlds: WorldInfo[] = [
  { name: "Avalor", path: "mundos/Avalor", lore_count: 42, character_count: 15, reference_count: 0 },
  { name: "Vibrantes", path: "mundos/Vibrantes", lore_count: 7, character_count: 2, reference_count: 0 },
];

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
    <MemoryRouter>
      <SWRConfig value={{ provider: () => new Map() }}>
        <ProfilePage />
      </SWRConfig>
    </MemoryRouter>,
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
    worlds,
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
  deleteWorldMock.mockResolvedValue(trashEntry);
  listTrashMock.mockResolvedValue([]);
  restoreWorldMock.mockResolvedValue(undefined);
  permanentDeleteMock.mockResolvedValue(undefined);
});

describe("ProfilePage — Mundos tab / 3-step delete flow (W-4)", () => {
  it("adds a Mundos tab listing the worlds with a delete action per world", async () => {
    renderProfile();
    await openMundosTab();

    expect(screen.getByRole("heading", { name: "Mundos" })).toBeInTheDocument();
    expect(screen.getByText("Avalor")).toBeInTheDocument();
    expect(screen.getByText("Vibrantes")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Borrar" })).toHaveLength(2);
  });

  it("requires all three gates before calling deleteWorld with the typed confirm_name", async () => {
    renderProfile();
    await openMundosTab();

    // Open the modal for the first world.
    fireEvent.click(screen.getAllByRole("button", { name: "Borrar" })[0]);
    const dialog = screen.getByRole("dialog");

    // Step 1 — consequence warning: name, counts, 30-day notice.
    expect(within(dialog).getByText("Avalor")).toBeInTheDocument();
    expect(within(dialog).getByText("Lore 42")).toBeInTheDocument();
    expect(within(dialog).getByText("Personajes 15")).toBeInTheDocument();
    expect(within(dialog).getByText(/recuperable durante 30 días/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Entiendo, continuar" }));

    // Step 2 — scope checkboxes: Continuar only enables with all three checked.
    const continueButton = within(dialog).getByRole("button", { name: "Continuar" });
    expect(continueButton).toBeDisabled();
    const checkboxes = within(dialog).getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(3);
    checkboxes.forEach((cb) => fireEvent.click(cb));
    await waitFor(() => expect(continueButton).toBeEnabled());
    fireEvent.click(continueButton);

    // Step 3 — name gate: wrong name keeps the button disabled; a
    // case-insensitive exact match enables it.
    const input = within(dialog).getByLabelText("Nombre del mundo a eliminar");
    const confirmButton = within(dialog).getByRole("button", { name: "Borrar definitivamente" });
    expect(confirmButton).toBeDisabled();

    fireEvent.change(input, { target: { value: "WRONG" } });
    expect(confirmButton).toBeDisabled();

    fireEvent.change(input, { target: { value: "avalor" } });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    fireEvent.click(confirmButton);

    await waitFor(() =>
      expect(deleteWorldMock).toHaveBeenCalledWith("Avalor", "avalor"),
    );
    // Modal closes and the worlds list is refreshed.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mutateSpy).toHaveBeenCalled();
  });

  it("clears the active world from the selector when the deleted world was active", async () => {
    // Regression: deleting the world the selector points at must not leave it
    // showing a deleted world. localStorage holds the persisted active world.
    window.localStorage.setItem(ACTIVE_WORLD_STORAGE_KEY, "Avalor");
    renderProfile();
    await openMundosTab();

    fireEvent.click(screen.getAllByRole("button", { name: "Borrar" })[0]);
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Entiendo, continuar" }));
    const continueButton = within(dialog).getByRole("button", { name: "Continuar" });
    within(dialog).getAllByRole("checkbox").forEach((cb) => fireEvent.click(cb));
    await waitFor(() => expect(continueButton).toBeEnabled());
    fireEvent.click(continueButton);
    const input = within(dialog).getByLabelText("Nombre del mundo a eliminar");
    fireEvent.change(input, { target: { value: "avalor" } });
    const confirmButton = within(dialog).getByRole("button", { name: "Borrar definitivamente" });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    fireEvent.click(confirmButton);

    await waitFor(() => expect(deleteWorldMock).toHaveBeenCalledWith("Avalor", "avalor"));
    // The active world that no longer exists must be cleared so the selector
    // no longer points at a deleted world.
    await waitFor(() =>
      expect(window.localStorage.getItem(ACTIVE_WORLD_STORAGE_KEY)).toBeNull(),
    );
    // And the world picker opens right away so the user is steered to another.
    await waitFor(() =>
      expect(screen.getByText("Elegí un mundo")).toBeInTheDocument(),
    );
  });

  it("cancels at step 1 without deleting", async () => {
    renderProfile();
    await openMundosTab();

    fireEvent.click(screen.getAllByRole("button", { name: "Borrar" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(deleteWorldMock).not.toHaveBeenCalled();
  });

  it("cancels at step 2 without deleting", async () => {
    renderProfile();
    await openMundosTab();

    fireEvent.click(screen.getAllByRole("button", { name: "Borrar" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Entiendo, continuar" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(deleteWorldMock).not.toHaveBeenCalled();
  });

  it("cancels at step 3 without deleting", async () => {
    renderProfile();
    await openMundosTab();

    fireEvent.click(screen.getAllByRole("button", { name: "Borrar" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Entiendo, continuar" }));
    screen.getAllByRole("checkbox").forEach((cb) => fireEvent.click(cb));
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(deleteWorldMock).not.toHaveBeenCalled();
  });

  it("keeps the final button disabled until the typed name matches case-insensitively", async () => {
    renderProfile();
    await openMundosTab();

    fireEvent.click(screen.getAllByRole("button", { name: "Borrar" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Entiendo, continuar" }));
    screen.getAllByRole("checkbox").forEach((cb) => fireEvent.click(cb));
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

    const input = screen.getByLabelText("Nombre del mundo a eliminar");
    const confirmButton = screen.getByRole("button", { name: "Borrar definitivamente" });

    fireEvent.change(input, { target: { value: "WRONG" } });
    expect(confirmButton).toBeDisabled();
    expect(screen.getByText("El nombre no coincide.")).toBeInTheDocument();

    // Lowercase is a case-insensitive match → enables.
    fireEvent.change(input, { target: { value: "AVALOR" } });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    expect(screen.queryByText("El nombre no coincide.")).not.toBeInTheDocument();

    // Exact-cased match too.
    fireEvent.change(input, { target: { value: "Avalor" } });
    await waitFor(() => expect(confirmButton).toBeEnabled());
  });

  it("disables the delete button for the active world with a tooltip", async () => {
    getIdeaCaptureStatusMock.mockResolvedValue({
      config: { active_world: "Avalor" },
    } as unknown as IdeaCaptureStatus);

    renderProfile();
    await openMundosTab();

    await waitFor(() => {
      const avalorButton = screen.getAllByRole("button", { name: "Borrar" })[0];
      expect(avalorButton).toBeDisabled();
      expect(avalorButton).toHaveAttribute("title", "No se puede eliminar el mundo activo");
    });
    expect(screen.getAllByRole("button", { name: "Borrar" })[1]).toBeEnabled();
  });

  it("disables every delete button with a tooltip when only one world exists", async () => {
    useWorldsMock.mockReturnValue({
      worlds: [worlds[0]],
      isLoading: false,
      isValidating: false,
      error: undefined,
      mutate: mutateSpy,
    });

    renderProfile();
    await openMundosTab();

    const button = screen.getByRole("button", { name: "Borrar" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Debe existir al menos un mundo");
  });

  it("shows the API error inside the modal and keeps it open", async () => {
    deleteWorldMock.mockRejectedValue(new ApiError(409, "El mundo está activo"));
    renderProfile();
    await openMundosTab();

    fireEvent.click(screen.getAllByRole("button", { name: "Borrar" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Entiendo, continuar" }));
    screen.getAllByRole("checkbox").forEach((cb) => fireEvent.click(cb));
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));
    fireEvent.change(screen.getByLabelText("Nombre del mundo a eliminar"), {
      target: { value: "Avalor" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Borrar definitivamente" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(deleteWorldMock).toHaveBeenCalledWith("Avalor", "Avalor");
  });
});