import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Mock } from "vitest";
import { executeMigration } from "@/api/migration";
import { MigrationPanel } from "@/components/organisms/MigrationPanel";
import {
  ApiError,
  type LegacyFinding,
  type MigrationExecuteResult,
} from "@/api/types";

vi.mock("@/api/migration", () => ({ executeMigration: vi.fn() }));

const mocked = { executeMigration: executeMigration as Mock };

/** Two legacy worlds: one with Lore+Personajes, one with only Lore. */
const findings: LegacyFinding[] = [
  { world: "legacy-x", folders: ["Lore", "Personajes"] },
  { world: "legacy-y", folders: ["Lore"] },
];

const completed: MigrationExecuteResult = {
  status: "completed",
  transaction_id: "mig-20260818-abc123",
  world: "legacy-x",
  restore_verified: true,
  started_at: "2026-08-18T12:00:00Z",
  finished_at: "2026-08-18T12:00:01Z",
  error: null,
  steps: [
    {
      folder: "Lore",
      source: "/tmp/sandbox/mundos/legacy-x/Lore",
      destination: "/tmp/sandbox/mundos/legacy-x/lore",
      source_hash: "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      destination_hash: "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      restored: false,
      is_noop: false,
    },
  ],
};

const rolledBack: MigrationExecuteResult = {
  ...completed,
  status: "rolled_back",
  error: "el destino 'lore' se ocupó antes de migrar",
  steps: [{ ...completed.steps[0], restored: true }],
};

describe("MigrationPanel (ONB-4.3, WU-4c2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders every finding with its folders and never auto-migrates on mount", () => {
    render(<MigrationPanel findings={findings} />);

    expect(screen.getByText("legacy-x")).toBeInTheDocument();
    expect(screen.getByText("legacy-y")).toBeInTheDocument();
    // Folder names are visible as badges; the case-sensitive risk is stated.
    expect(screen.getAllByText("Lore").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Personajes")).toBeInTheDocument();
    expect(screen.getByText(/distinguen mayúsculas y minúsculas/i)).toBeInTheDocument();
    // Mounting the panel never triggers a migration (no auto-rename).
    expect(mocked.executeMigration).not.toHaveBeenCalled();
  });

  it("requires an explicit confirmation before calling the migration API", async () => {
    const user = userEvent.setup();
    render(<MigrationPanel findings={findings} />);

    await user.click(screen.getByRole("button", { name: "Migrar carpetas de legacy-x" }));
    // The confirm dialog appears; the API has NOT been called yet.
    const dialog = await screen.findByRole("dialog", { name: "Migrar carpetas legacy" });
    expect(within(dialog).getByText(/legacy-x/)).toBeInTheDocument();
    expect(mocked.executeMigration).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Migrar" }));
    expect(mocked.executeMigration).toHaveBeenCalledTimes(1);
    expect(mocked.executeMigration).toHaveBeenCalledWith("legacy-x", ["Lore", "Personajes"]);
  });

  it("cancel closes the dialog without calling the migration API", async () => {
    const user = userEvent.setup();
    render(<MigrationPanel findings={findings} />);

    await user.click(screen.getByRole("button", { name: "Migrar carpetas de legacy-x" }));
    await screen.findByRole("dialog", { name: "Migrar carpetas legacy" });
    await user.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mocked.executeMigration).not.toHaveBeenCalled();
  });

  it("completed outcome is honest: shows the transaction id and refreshes readiness", async () => {
    const user = userEvent.setup();
    const onMigrated = vi.fn();
    mocked.executeMigration.mockResolvedValue(completed);
    render(<MigrationPanel findings={findings} onMigrated={onMigrated} />);

    await user.click(screen.getByRole("button", { name: "Migrar carpetas de legacy-x" }));
    await user.click(screen.getByRole("button", { name: "Migrar" }));

    // Success is explicit, never generic: transaction id + canonical tree.
    expect(await screen.findByText(/Migración completada/i)).toBeInTheDocument();
    expect(screen.getByText(/mig-20260818-abc123/)).toBeInTheDocument();
    // Readiness refresh fires so the Center re-reads the canonical tree.
    expect(onMigrated).toHaveBeenCalledTimes(1);
  });

  it("rolled_back outcome is honest: reports the revert and never claims completion", async () => {
    const user = userEvent.setup();
    const onMigrated = vi.fn();
    mocked.executeMigration.mockResolvedValue(rolledBack);
    render(<MigrationPanel findings={findings} onMigrated={onMigrated} />);

    await user.click(screen.getByRole("button", { name: "Migrar carpetas de legacy-x" }));
    await user.click(screen.getByRole("button", { name: "Migrar" }));

    expect(await screen.findByText(/se revirtió/i)).toBeInTheDocument();
    expect(screen.getByText(/fueron restaurados/i)).toBeInTheDocument();
    expect(screen.getByText(/mig-20260818-abc123/)).toBeInTheDocument();
    // A rolled-back migration moved nothing: readiness does not change.
    expect(screen.queryByText(/Migración completada/i)).not.toBeInTheDocument();
    expect(onMigrated).not.toHaveBeenCalled();
  });

  it("maps server error codes to retryable guidance without claiming success", async () => {
    const user = userEvent.setup();
    const onMigrated = vi.fn();
    mocked.executeMigration.mockRejectedValue(
      new ApiError(409, "El destino 'lore' se ocupó antes de migrar", "El destino se ocupó", "collision"),
    );
    render(<MigrationPanel findings={findings} onMigrated={onMigrated} />);

    await user.click(screen.getByRole("button", { name: "Migrar carpetas de legacy-x" }));
    await user.click(screen.getByRole("button", { name: "Migrar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/destino ya está ocupado/i);
    expect(onMigrated).not.toHaveBeenCalled();
    // Retryable: the dialog stays open with the confirm action available.
    expect(screen.getByRole("button", { name: "Migrar" })).toBeInTheDocument();
    // No fake vocabulary anywhere.
    expect(screen.queryByText(/Migración completada/i)).not.toBeInTheDocument();
  });

  it("never renders raw filesystem paths or content hashes from the response", async () => {
    const user = userEvent.setup();
    mocked.executeMigration.mockResolvedValue(completed);
    render(<MigrationPanel findings={findings} />);

    await user.click(screen.getByRole("button", { name: "Migrar carpetas de legacy-x" }));
    await user.click(screen.getByRole("button", { name: "Migrar" }));
    await screen.findByText(/Migración completada/i);

    const text = document.body.textContent ?? "";
    // The evidence payload carries absolute paths and sha256 digests, but the
    // UI only renders folder names + the transaction id — no path/hash leak.
    expect(text).not.toContain("/tmp/sandbox/mundos/legacy-x/Lore");
    expect(text).not.toContain("source_hash");
    expect(text).not.toContain("1111111111111111111111111111111111111111111111111111111111111111");
    expect(screen.getAllByText("Lore").length).toBeGreaterThanOrEqual(1);
  });

  it("confirmation dialog is modal and its controls are disabled while migrating", async () => {
    const user = userEvent.setup();
    let resolveRun: (value: MigrationExecuteResult) => void = () => undefined;
    mocked.executeMigration.mockImplementation(
      () =>
        new Promise<MigrationExecuteResult>((resolve) => {
          resolveRun = resolve;
        }),
    );
    render(<MigrationPanel findings={findings} />);

    await user.click(screen.getByRole("button", { name: "Migrar carpetas de legacy-x" }));
    const dialog = await screen.findByRole("dialog", { name: "Migrar carpetas legacy" });
    expect(dialog).toHaveAttribute("aria-modal", "true");

    await user.click(within(dialog).getByRole("button", { name: "Migrar" }));
    // While the migration runs, both actions are disabled (no double-run).
    expect(within(dialog).getByRole("button", { name: "Migrar" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Cancelar" })).toBeDisabled();

    resolveRun(completed);
    await waitFor(() => expect(screen.getByText(/Migración completada/i)).toBeInTheDocument());
  });

  it("renders nothing actionable when there are no legacy findings", () => {
    render(<MigrationPanel findings={[]} />);
    expect(screen.queryByRole("button", { name: /migrar/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
