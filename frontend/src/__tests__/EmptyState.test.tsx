import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EmptyState } from "@/components/organisms/EmptyState";

/**
 * Locks the "optional and self-consistent" contract (actionable-empty-states
 * spec): the action control renders only when BOTH `actionLabel` and
 * `onAction` are present, and the component degrades to message-only without
 * error otherwise.
 */
describe("EmptyState", () => {
  it("renders the message", () => {
    render(<EmptyState message="No hay nada por aquí" />);
    expect(screen.getByText("No hay nada por aquí")).toBeInTheDocument();
  });

  it("renders the action control when label and handler are both present", () => {
    render(
      <EmptyState message="Mensaje" actionLabel="Crear" onAction={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Crear" })).toBeInTheDocument();
  });

  it("renders no action control when only a label is present", () => {
    render(<EmptyState message="Mensaje" actionLabel="Crear" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders no action control when only a handler is present", () => {
    render(<EmptyState message="Mensaje" onAction={vi.fn()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("degrades to message-only without error when the action is missing", () => {
    render(<EmptyState message="Solo mensaje" />);
    expect(screen.getByText("Solo mensaje")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("fires the action handler when the action control is clicked", async () => {
    const onAction = vi.fn();
    const user = userEvent.setup();
    render(
      <EmptyState
        message="Mensaje"
        actionLabel="Crear"
        onAction={onAction}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Crear" }));
    expect(onAction).toHaveBeenCalledTimes(1);
  });
});