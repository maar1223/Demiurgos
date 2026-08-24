import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateWorldModal } from "@/components/organisms/CreateWorldModal";
import { ApiError } from "@/api/types";
import type { WorldInfo } from "@/api/types";
import type { Mock } from "vitest";

vi.mock("@/api/onboarding", () => ({
  createWorld: vi.fn(),
}));

import { createWorld } from "@/api/onboarding";

const CREATED_RESULT = {
  kind: "created",
  name: "mi-mundo",
  path: "/mi-mundo",
  message: "",
} as const;

function setup(isOpen = true) {
  const onClose = vi.fn();
  const onCreated = vi.fn();
  const utils = render(
    <CreateWorldModal isOpen={isOpen} onClose={onClose} onCreated={onCreated} />,
  );
  return { onClose, onCreated, ...utils };
}

function worldInfoOf(name: string, path: string): WorldInfo {
  return { name, path, lore_count: 0, character_count: 0 };
}

describe("CreateWorldModal render state", () => {
  it("renders nothing when isOpen is false", () => {
    setup(false);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/nombre del mundo/i)).not.toBeInTheDocument();
  });

  it("renders the form fields when isOpen is true", () => {
    setup(true);

    expect(screen.getByRole("dialog", { name: /nuevo mundo/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/nombre del mundo/i)).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Crear mundo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument();
  });
});

describe("CreateWorldModal accessibility", () => {
  it("exposes a labelled dialog with aria-modal", () => {
    setup(true);

    const dialog = screen.getByRole("dialog", { name: /nuevo mundo/i });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby", "create-world-title");
  });

  it("autofocuses the name input when the dialog opens", () => {
    setup(true);

    expect(screen.getByLabelText(/nombre del mundo/i)).toHaveFocus();
  });

  it("traps Tab focus inside the dialog and wraps with Shift+Tab", () => {
    setup(true);

    const dialog = screen.getByRole("dialog");
    const focusables = dialog.querySelectorAll<HTMLElement>(
      "input, button, [href], select, textarea, [tabindex]:not([tabindex='-1'])",
    );
    expect(focusables.length).toBeGreaterThanOrEqual(3);

    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    // Tab from the last focusable wraps to the first
    last.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(first).toHaveFocus();

    // Shift+Tab from the first focusable wraps to the last
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });
});

describe("CreateWorldModal validation", () => {
  beforeEach(() => {
    (createWorld as Mock).mockReset();
  });

  it("shows an inline error for an empty name and never calls the API", async () => {
    const user = userEvent.setup();
    const { onClose } = setup(true);

    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(createWorld).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("shows an inline error for a whitespace-only name and never calls the API", async () => {
    const user = userEvent.setup();
    const { onClose } = setup(true);

    await user.type(screen.getByLabelText(/nombre del mundo/i), "   ");
    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(createWorld).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("CreateWorldModal submit success", () => {
  beforeEach(() => {
    (createWorld as Mock).mockReset();
  });

  it("submits a valid name with lore skeleton false by default", async () => {
    (createWorld as Mock).mockResolvedValue(CREATED_RESULT);
    const user = userEvent.setup();
    setup(true);

    await user.type(screen.getByLabelText(/nombre del mundo/i), "mi-mundo");
    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    await waitFor(() => expect(createWorld).toHaveBeenCalledWith("mi-mundo", false));
  });

  it("forwards lore_skeleton true when the checkbox is checked", async () => {
    (createWorld as Mock).mockResolvedValue(CREATED_RESULT);
    const user = userEvent.setup();
    setup(true);

    await user.type(screen.getByLabelText(/nombre del mundo/i), "mi-mundo");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    await waitFor(() => expect(createWorld).toHaveBeenCalledWith("mi-mundo", true));
  });

  it("delivers the created world and closes on a created result", async () => {
    (createWorld as Mock).mockResolvedValue(CREATED_RESULT);
    const user = userEvent.setup();
    const { onClose, onCreated } = setup(true);

    await user.type(screen.getByLabelText(/nombre del mundo/i), "mi-mundo");
    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith(worldInfoOf("mi-mundo", "/mi-mundo")),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("treats already_exists as success: delivers the world and closes", async () => {
    (createWorld as Mock).mockResolvedValue({
      kind: "already_exists",
      name: "mi-mundo",
      path: "/mi-mundo",
      message: "",
    });
    const user = userEvent.setup();
    const { onClose, onCreated } = setup(true);

    await user.type(screen.getByLabelText(/nombre del mundo/i), "mi-mundo");
    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith(worldInfoOf("mi-mundo", "/mi-mundo")),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe("CreateWorldModal submit errors", () => {
  beforeEach(() => {
    (createWorld as Mock).mockReset();
  });

  it("keeps the modal open and shows the message on a collision", async () => {
    (createWorld as Mock).mockResolvedValue({
      kind: "collision",
      name: "mi-mundo",
      path: null,
      message: "Ya existe un mundo con ese nombre",
    });
    const user = userEvent.setup();
    const { onClose } = setup(true);

    await user.type(screen.getByLabelText(/nombre del mundo/i), "mi-mundo");
    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/ya existe/i));
    expect(screen.getByRole("dialog", { name: /nuevo mundo/i })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(createWorld).toHaveBeenCalledTimes(1);
  });

  it("keeps the modal open and shows the message on an invalid name", async () => {
    (createWorld as Mock).mockResolvedValue({
      kind: "invalid_name",
      name: "mi-mundo",
      path: null,
      message: "El nombre no es válido",
    });
    const user = userEvent.setup();
    const { onClose } = setup(true);

    await user.type(screen.getByLabelText(/nombre del mundo/i), "mi-mundo");
    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/no es válido/i));
    expect(screen.getByRole("dialog", { name: /nuevo mundo/i })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes the modal and surfaces the auth hint on HTTP 401", async () => {
    (createWorld as Mock).mockRejectedValue(new ApiError(401, "Authentication required."));
    const user = userEvent.setup();
    const { onClose } = setup(true);

    await user.type(screen.getByLabelText(/nombre del mundo/i), "mi-mundo");
    await user.click(screen.getByRole("button", { name: "Crear mundo" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(createWorld).toHaveBeenCalledTimes(1);
  });
});

describe("CreateWorldModal dismissal", () => {
  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const { onClose } = setup(true);

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalled();
  });

  it("closes when the backdrop overlay is clicked", async () => {
    const user = userEvent.setup();
    const { onClose } = setup(true);

    const overlay = document.querySelector(".fixed.inset-0.z-50");
    expect(overlay).not.toBeNull();
    await user.click(overlay as HTMLElement);

    expect(onClose).toHaveBeenCalled();
  });

  it("closes when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const { onClose } = setup(true);

    await user.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(onClose).toHaveBeenCalled();
  });
});

afterEach(() => {
  vi.clearAllMocks();
});