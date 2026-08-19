import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { useState } from "react";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { WorldSelector } from "@/components/molecules/WorldSelector";
import { CreateWorldModal } from "@/components/organisms/CreateWorldModal";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { ACTIVE_WORLD_STORAGE_KEY } from "@/lib/currentWorld";
import type { WorldInfo } from "@/api/types";

vi.mock("@/api/onboarding", () => ({
  createWorld: vi.fn(),
}));

import { createWorld } from "@/api/onboarding";
import type { Mock } from "vitest";

const initialWorlds: WorldInfo[] = [
  {
    name: "Vibrantes",
    path: "/vibrantes",
    lore_count: 77,
    character_count: 10,
    saga_count: 4,
  },
];

const NEW_WORLD: WorldInfo = {
  name: "mi-mundo",
  path: "/mi-mundo",
  lore_count: 0,
  character_count: 0,
  saga_count: 0,
};

/**
 * End-to-end TestHarness: WorldSelector + CreateWorldModal + ConfirmDialog
 * composed exactly the way the parents (Navbar, ToolWorkshop) wire them.
 * The selector opens via the dropdown trigger; the modal closes the
 * dropdown and opens the labelled dialog; on success the world is appended
 * and the existing switch-confirm flow is reused.
 */
function TestHarness({ initial }: { initial: WorldInfo[] }) {
  const [worlds, setWorlds] = useState<WorldInfo[]>(initial);
  const [creating, setCreating] = useState(false);
  const [pendingWorld, setPendingWorld] = useState<string | null>(null);

  return (
    <MemoryRouter initialEntries={["/wiki"]}>
      <WorldSelector
        worlds={worlds}
        onRequestCreate={() => setCreating(true)}
        onWorldChange={() => {}}
      />
      <CreateWorldModal
        isOpen={creating}
        onClose={() => setCreating(false)}
        onCreated={(created) => {
          setWorlds((prev) => [...prev, created]);
          setCreating(false);
          setPendingWorld(created.name);
        }}
      />
      {pendingWorld && (
        <ConfirmDialog
          title="Cambiar mundo activo"
          message={`¿Cambiar a ${pendingWorld}?`}
          onConfirm={() => setPendingWorld(null)}
          onClose={() => setPendingWorld(null)}
        />
      )}
    </MemoryRouter>
  );
}

describe("WorldSelector integration", () => {
  beforeEach(() => {
    (createWorld as Mock).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("clicking + Nuevo mundo opens the modal", async () => {
    (createWorld as Mock).mockResolvedValue({
      kind: "created",
      name: NEW_WORLD.name,
      path: NEW_WORLD.path,
      message: "",
    });

    const user = userEvent.setup();
    render(<TestHarness initial={initialWorlds} />);

    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("menuitem", { name: /nuevo mundo/i }));

    expect(
      screen.getByRole("dialog", { name: /nuevo mundo/i }),
    ).toBeInTheDocument();
    // Dropdown closed underneath the modal.
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("submitting a valid name closes the modal and appends the world to the list", async () => {
    (createWorld as Mock).mockResolvedValue({
      kind: "created",
      name: NEW_WORLD.name,
      path: NEW_WORLD.path,
      message: "",
    });

    const user = userEvent.setup();
    render(<TestHarness initial={initialWorlds} />);

    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("menuitem", { name: /nuevo mundo/i }));
    await user.type(screen.getByLabelText(/nombre del mundo/i), NEW_WORLD.name);
    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    await waitFor(() =>
      expect(createWorld).toHaveBeenCalledWith(NEW_WORLD.name, false),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /nuevo mundo/i })).not.toBeInTheDocument(),
    );

    // Reopen the dropdown to see the appended world.
    await user.click(screen.getByRole("button", { name: /vibrantes|mundos/i }));
    expect(
      screen.getByRole("option", { name: NEW_WORLD.name }),
    ).toBeInTheDocument();
  });

  it("a successful creation triggers the post-creation switch-confirm dialog", async () => {
    (createWorld as Mock).mockResolvedValue({
      kind: "created",
      name: NEW_WORLD.name,
      path: NEW_WORLD.path,
      message: "",
    });

    const user = userEvent.setup();
    render(<TestHarness initial={initialWorlds} />);

    await user.click(screen.getByRole("button", { name: "Mundos" }));
    await user.click(screen.getByRole("menuitem", { name: /nuevo mundo/i }));
    await user.type(screen.getByLabelText(/nombre del mundo/i), NEW_WORLD.name);
    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    const switchDialog = await screen.findByRole("dialog", {
      name: /cambiar mundo activo/i,
    });
    expect(switchDialog).toBeInTheDocument();
    expect(within(switchDialog).getByText(/mi-mundo/i)).toBeInTheDocument();

    // Dismissing the switch confirmation does not write the active world.
    await user.click(within(switchDialog).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(localStorage.getItem(ACTIVE_WORLD_STORAGE_KEY)).toBeNull();
  });
});
