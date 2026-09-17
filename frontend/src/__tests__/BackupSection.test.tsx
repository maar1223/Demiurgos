import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Mock } from "vitest";
import {
  FORBIDDEN_DELIVERY_VOCABULARY,
  findForbiddenVocabulary,
  getBackupCandidates,
  getBackupRestoreStatus,
  getBackupSnapshots,
  getBackupStatus,
  previewBackupRestore,
  restoreBackup,
  runBackupNow,
  setBackupDestination,
} from "@/api/backup";
import {
  BackupSection,
  backupCardConfigured,
  backupCardState,
  backupWriteCopy,
  isSessionRequiredError,
  normalizeConflicts,
} from "@/components/organisms/BackupSection";
import type {
  BackupStatus,
  BackupCandidate,
  BackupRestorePreview,
  BackupSnapshot,
} from "@/api/types";
import { ApiError } from "@/api/types";
// Raw source of the organism under test — used by the honest-copy scan
// (REQ-BUI-3) so a literal that no rendered state reaches is still caught.
import backupSectionSource from "@/components/organisms/BackupSection.tsx?raw";

// Keep the real honest-copy helpers (the scan is the point of the suite) and
// mock only the network functions.
vi.mock("@/api/backup", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/backup")>();
  return {
    ...actual,
    getBackupStatus: vi.fn(),
    getBackupCandidates: vi.fn(),
    setBackupDestination: vi.fn(),
    runBackupNow: vi.fn(),
    getBackupSnapshots: vi.fn(),
    previewBackupRestore: vi.fn(),
    restoreBackup: vi.fn(),
    getBackupRestoreStatus: vi.fn(),
  };
});

const mocked = {
  getBackupStatus: getBackupStatus as Mock,
  getBackupCandidates: getBackupCandidates as Mock,
  setBackupDestination: setBackupDestination as Mock,
  runBackupNow: runBackupNow as Mock,
  getBackupSnapshots: getBackupSnapshots as Mock,
  previewBackupRestore: previewBackupRestore as Mock,
  restoreBackup: restoreBackup as Mock,
  getBackupRestoreStatus: getBackupRestoreStatus as Mock,
};

const MIRRORING_REMEDY = "switch Google Drive for Desktop to Mirroring";

const DESTINATION = {
  schema_version: 1,
  path: "/home/author/Demiurgos",
  provider: "google_drive",
  source: "heuristic" as const,
  confidence: "heuristic" as const,
  mode_hint: "mirrored" as const,
  updated_at: "2026-09-17T10:00:00Z",
};

const PENDING_STATUS: BackupStatus = {
  state: "pending",
  destination: null,
  mode: null,
  blocked: false,
  warning: null,
  last_write: null,
  copy: null,
};

const CHOSEN_STATUS: BackupStatus = {
  state: "pending",
  destination: DESTINATION,
  mode: "mirrored",
  blocked: false,
  warning: null,
  last_write: null,
  copy: null,
};

const WRITTEN_STATUS: BackupStatus = {
  state: "configured",
  destination: DESTINATION,
  mode: "mirrored",
  blocked: false,
  warning: null,
  last_write: {
    destination: "/home/author/Demiurgos",
    written_at: "2026-09-17T10:05:00Z",
    status: "ok",
    current_entries: 42,
  },
  copy: {
    en: "Written to /home/author/Demiurgos — 2026-09-17T10:05:00Z UTC",
    es: "Escrito en /home/author/Demiurgos — 2026-09-17T10:05:00Z UTC",
  },
};

// A verified streaming target: the API persists it WITH the verdict and a
// remedy. Note the payload still carries a stale last_write/copy — the warning
// MUST replace the success area, not accompany it.
const STREAMING_STATUS: BackupStatus = {
  state: "error",
  destination: { ...DESTINATION, mode_hint: "streaming" },
  mode: "streaming",
  blocked: true,
  warning: MIRRORING_REMEDY,
  last_write: {
    destination: "/home/author/Demiurgos",
    written_at: "2026-09-17T10:05:00Z",
    status: "ok",
    current_entries: 42,
  },
  copy: {
    en: "Written to /home/author/Demiurgos — 2026-09-17T10:05:00Z UTC",
    es: "Escrito en /home/author/Demiurgos — 2026-09-17T10:05:00Z UTC",
  },
};

const CANDIDATE: BackupCandidate = {
  path: "/home/author/OneDrive",
  provider: "onedrive",
  source: "env",
  confidence: "verified",
  confirmed: false,
};

const SNAPSHOTS: BackupSnapshot[] = [
  { snapshot_id: "2026-09-16T120530Z", complete: true, entries: 10, bytes: 1000 },
  { snapshot_id: "2026-09-15T120530Z", complete: false, entries: 5, bytes: 500 },
];

const CLEAN_PREVIEW: BackupRestorePreview = {
  validation: {
    snapshot_id: "2026-09-16T120530Z",
    schema_version: 1,
    complete: true,
    entries: 10,
    bytes: 1000,
    databases: ["idea-capture"],
    okf_documents: 4,
    worlds: ["Mundo"],
  },
  conflicts: {
    snapshot_id: "2026-09-16T120530Z",
    counts: { added: 2, modified: 1, removed: 0 },
    examples: [{ path: "ideas/a.md", change: "added" }],
    blockers: [],
  },
  blocked: false,
};

/** Wait for the initial status read to settle and the section to render. */
const renderSection = async (status: BackupStatus) => {
  mocked.getBackupStatus.mockResolvedValue(status);
  render(<BackupSection />);
  await screen.findByText("Estado del respaldo");
};

describe("BackupSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.getBackupStatus.mockResolvedValue(PENDING_STATUS);
    mocked.getBackupCandidates.mockResolvedValue({ candidates: [], picker: true });
    mocked.getBackupRestoreStatus.mockResolvedValue({
      pending: false,
      leftovers: [],
      last_write: null,
    });
    mocked.getBackupSnapshots.mockResolvedValue({ snapshots: [] });
    mocked.setBackupDestination.mockResolvedValue(CHOSEN_STATUS);
    mocked.runBackupNow.mockResolvedValue(WRITTEN_STATUS);
    mocked.previewBackupRestore.mockResolvedValue(CLEAN_PREVIEW);
    mocked.restoreBackup.mockResolvedValue({
      snapshot_id: "2026-09-16T120530Z",
      status: "ok",
      swapped: ["ideas", "mundos"],
      databases: ["idea-capture"],
      worlds: ["Mundo"],
      config_files: [],
      conflicts: {
        snapshot_id: "2026-09-16T120530Z",
        counts: { added: 2, modified: 1, removed: 0 },
        examples: [],
        blockers: [],
      },
      warnings: [],
    });
  });

  it("state 1: no folder yet shows the picker and the candidate list", async () => {
    mocked.getBackupCandidates.mockResolvedValue({ candidates: [CANDIDATE], picker: true });
    await renderSection(PENDING_STATUS);

    expect(screen.getByText(/Aún no elegiste una carpeta/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Elegir carpeta")).toBeInTheDocument();
    // A suggestion is offered but never auto-selected.
    expect(screen.getByText("/home/author/OneDrive")).toBeInTheDocument();
    expect(screen.getByText(/OneDrive ·/)).toBeInTheDocument();
    // No success claim and no run action with no folder.
    expect(screen.queryByText("Configurado")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Backup ahora" })).not.toBeInTheDocument();
  });

  it("state 1: choosing a folder persists the typed path", async () => {
    const user = userEvent.setup();
    await renderSection(PENDING_STATUS);

    await user.type(screen.getByLabelText("Elegir carpeta"), "/srv/datos");
    await user.click(screen.getByRole("button", { name: "Usar esta carpeta" }));

    expect(mocked.setBackupDestination).toHaveBeenCalledWith("/srv/datos");
    // The returned state now shows the chosen folder (state 2).
    expect(await screen.findByText(DESTINATION.path)).toBeInTheDocument();
  });

  it("state 1: a candidate is chosen explicitly through its own action", async () => {
    const user = userEvent.setup();
    mocked.getBackupCandidates.mockResolvedValue({ candidates: [CANDIDATE], picker: true });
    await renderSection(PENDING_STATUS);

    const list = screen.getByRole("list", { name: "Carpetas sugeridas" });
    const item = within(list).getByText("/home/author/OneDrive").closest("li");
    await user.click(within(item as HTMLElement).getByRole("button", { name: "Usar esta carpeta" }));

    expect(mocked.setBackupDestination).toHaveBeenCalledWith("/home/author/OneDrive");
  });

  it("state 2: a chosen folder shows path, provider, source and mode", async () => {
    await renderSection(CHOSEN_STATUS);

    expect(screen.getByTestId("backup-destination-path")).toHaveTextContent(DESTINATION.path);
    expect(screen.getByText("Google Drive")).toBeInTheDocument();
    expect(screen.getByText(/sugerida por proximidad · confianza heurística/i)).toBeInTheDocument();
    expect(screen.getByText("Copia local (espejo)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Backup ahora" })).toBeInTheDocument();
    expect(screen.queryByTestId("backup-last-write")).not.toBeInTheDocument();
  });

  it("state 3: the streaming warning REPLACES the success area and renders the API remedy", async () => {
    await renderSection(STREAMING_STATUS);

    // The warning and the server's remedy are visible.
    expect(screen.getByTestId("backup-warning")).toBeInTheDocument();
    expect(screen.getByTestId("backup-warning-remedy")).toHaveTextContent(MIRRORING_REMEDY);
    // The success area, the last-write copy and every run action are absent,
    // even though the payload still carries a stale successful write.
    expect(screen.queryByTestId("backup-success-area")).not.toBeInTheDocument();
    expect(screen.queryByTestId("backup-last-write")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Backup ahora" })).not.toBeInTheDocument();
    expect(screen.queryByText("Configurado")).not.toBeInTheDocument();
    expect(screen.getByText("Error")).toBeInTheDocument();
  });

  it("state 4: the last local write renders the API copy and offers Backup ahora", async () => {
    const user = userEvent.setup();
    await renderSection(WRITTEN_STATUS);

    expect(screen.getByTestId("backup-last-write")).toHaveTextContent(
      "Escrito en /home/author/Demiurgos — 2026-09-17T10:05:00Z UTC",
    );
    // Real evidence: the card shows Configurado only here.
    expect(screen.getByText("Configurado")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Backup ahora" }));
    expect(mocked.runBackupNow).toHaveBeenCalledTimes(1);
  });

  it("gates Configured on real evidence (folder AND a successful write)", async () => {
    // A stale claim: configured but no recorded write must not configure the card.
    await renderSection({ ...CHOSEN_STATUS, state: "configured" });

    expect(backupCardConfigured({ ...CHOSEN_STATUS, state: "configured" })).toBe(false);
    expect(screen.queryByText("Configurado")).not.toBeInTheDocument();
    expect(screen.getByText("Pendiente")).toBeInTheDocument();
    expect(screen.getByText(/Todavía no hay una escritura local registrada/i)).toBeInTheDocument();
    expect(backupCardConfigured(WRITTEN_STATUS)).toBe(true);
    expect(backupCardState(WRITTEN_STATUS)).toBe("configured");
  });

  it("state 5: restore walks list → preview → confirm → result", async () => {
    const user = userEvent.setup();
    mocked.getBackupSnapshots.mockResolvedValue({ snapshots: SNAPSHOTS });
    await renderSection(CHOSEN_STATUS);

    await user.click(screen.getByRole("button", { name: "Restaurar…" }));
    expect(await screen.findByText("2026-09-16T120530Z")).toBeInTheDocument();
    expect(screen.getByText(/Incompleta/)).toBeInTheDocument();

    const list = screen.getByRole("list", { name: "Copias disponibles" });
    const item = within(list).getByText("2026-09-16T120530Z").closest("li");
    await user.click(within(item as HTMLElement).getByRole("button", { name: "Previsualizar" }));
    expect(mocked.previewBackupRestore).toHaveBeenCalledWith("2026-09-16T120530Z");

    // Preview shows the diff counts, then requires an explicit confirmation.
    expect(await screen.findByText("Se agregan")).toBeInTheDocument();
    expect(screen.getByText(/ideas\/a\.md/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continuar" }));
    expect(screen.getByText(/¿Confirmás restaurar la copia/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Restaurar ahora" }));

    expect(mocked.restoreBackup).toHaveBeenCalledWith("2026-09-16T120530Z");
    expect(await screen.findByText(/Restauración terminada: ok/)).toBeInTheDocument();
  });

  it("state 5: preview blockers disable the confirm action", async () => {
    const user = userEvent.setup();
    mocked.getBackupSnapshots.mockResolvedValue({ snapshots: SNAPSHOTS });
    mocked.previewBackupRestore.mockResolvedValue({
      conflicts: {
        snapshot_id: "2026-09-16T120530Z",
        counts: { added: 0, modified: 0, removed: 1 },
        examples: [],
        blockers: ["conflicting type at member boundary: ideas"],
      },
      blocked: true,
    });
    await renderSection(CHOSEN_STATUS);

    await user.click(screen.getByRole("button", { name: "Restaurar…" }));
    const list = await screen.findByRole("list", { name: "Copias disponibles" });
    const item = within(list).getByText("2026-09-16T120530Z").closest("li");
    await user.click(within(item as HTMLElement).getByRole("button", { name: "Previsualizar" }));

    expect(await screen.findByText(/conflicting type at member boundary/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continuar" })).not.toBeInTheDocument();
  });

  it("surfaces an unresolved previous restore without hiding it", async () => {
    mocked.getBackupRestoreStatus.mockResolvedValue({
      pending: true,
      leftovers: ["ideas"],
      last_write: null,
    });
    await renderSection(CHOSEN_STATUS);

    expect(await screen.findByText(/quedó sin resolver/i)).toBeInTheDocument();
    expect(screen.getByText(/residuos: ideas/i)).toBeInTheDocument();
  });

  // WU-15's suite mocked the read as a resolved payload and never exercised the
  // unauthorised path, which is exactly how the raw "Autenticación requerida"
  // red line shipped. These tests pin the real 401 behavior.
  it("shows an actionable session-required state on a 401, not a generic error", async () => {
    const user = userEvent.setup();
    const onRequestSignIn = vi.fn();
    const unauthorised = new ApiError(401, "Autenticación requerida");
    mocked.getBackupStatus.mockRejectedValue(unauthorised);
    mocked.getBackupCandidates.mockRejectedValue(unauthorised);

    render(<BackupSection onRequestSignIn={onRequestSignIn} />);

    const state = await screen.findByTestId("backup-session-required");
    // Actionable copy and a concrete way forward — not the machine-ish detail.
    expect(
      within(state).getByText(/Necesitás iniciar sesión para configurar el respaldo/i),
    ).toBeInTheDocument();
    expect(within(state).getByText(/Iniciá sesión y volvé a esta tarjeta/i)).toBeInTheDocument();
    expect(within(state).queryByText("Autenticación requerida")).not.toBeInTheDocument();
    expect(findForbiddenVocabulary(state.textContent ?? "")).toEqual([]);

    await user.click(within(state).getByRole("button", { name: "Iniciar sesión" }));
    expect(onRequestSignIn).toHaveBeenCalledTimes(1);
  });

  it("treats the API's Autenticación requerida detail as session-required", async () => {
    const unauthorised = new Error("Autenticación requerida");
    mocked.getBackupStatus.mockRejectedValue(unauthorised);
    mocked.getBackupCandidates.mockRejectedValue(unauthorised);

    render(<BackupSection />);

    // No navigation callback here: the copy still states what to do.
    expect(await screen.findByTestId("backup-session-required")).toBeInTheDocument();
    expect(screen.getByText(/Iniciá sesión y volvé a esta tarjeta/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Iniciar sesión" }),
    ).not.toBeInTheDocument();
    expect(isSessionRequiredError(unauthorised)).toBe(true);
    expect(isSessionRequiredError(new ApiError(500, "Fallo interno"))).toBe(false);
  });

  it("keeps the honest error path for a non-session failure", async () => {
    mocked.getBackupStatus.mockRejectedValue(new ApiError(500, "Fallo interno del servidor"));

    render(<BackupSection />);

    expect(await screen.findByText("Fallo interno del servidor")).toBeInTheDocument();
    expect(screen.queryByTestId("backup-session-required")).not.toBeInTheDocument();
  });

  it("renders no forbidden delivery vocabulary in the component source", () => {
    // The raw source catches literals no rendered state reaches.
    expect(findForbiddenVocabulary(backupSectionSource)).toEqual([]);
  });

  it("mirrors the backend's forbidden vocabulary (es + en)", () => {
    for (const term of [
      "respaldado en la nube",
      "respaldado en Drive",
      "sincronizado con la nube",
      "sincronizado en la nube",
      "subido a Drive",
      "backed up to the cloud",
      "backed up to Drive",
      "synced to the cloud",
      "synced to Drive",
      "uploaded",
      "en la nube",
    ]) {
      expect(FORBIDDEN_DELIVERY_VOCABULARY).toContain(term);
    }
  });

  it("renders no forbidden delivery vocabulary in any of the five states", async () => {
    for (const status of [PENDING_STATUS, CHOSEN_STATUS, STREAMING_STATUS, WRITTEN_STATUS]) {
      mocked.getBackupStatus.mockResolvedValue(status);
      const { unmount } = render(<BackupSection />);
      await screen.findByText("Estado del respaldo");
      expect(findForbiddenVocabulary(document.body.textContent ?? "")).toEqual([]);
      unmount();
    }
  });

  it("normalizes a preview returned as a bare conflict report", () => {
    expect(
      normalizeConflicts({
        snapshot_id: "s",
        counts: { added: 1, modified: 0, removed: 0 },
        examples: [],
        blockers: [],
      }),
    ).toEqual({
      snapshot_id: "s",
      counts: { added: 1, modified: 0, removed: 0 },
      examples: [],
      blockers: [],
    });
    expect(backupWriteCopy(WRITTEN_STATUS)).toBe(
      "Escrito en /home/author/Demiurgos — 2026-09-17T10:05:00Z UTC",
    );
  });
});
