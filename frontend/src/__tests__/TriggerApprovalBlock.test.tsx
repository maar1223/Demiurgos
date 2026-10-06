import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TriggerApprovalBlock } from "@/components/organisms/TriggerApprovalBlock";
import type { TriggerApproval } from "@/api/types";
import { tEs } from "@/__tests__/i18nTestUtils";

const approval = (text: string): TriggerApproval => ({
  text,
  digest: `digest-${text.length}`,
  approved_by: "author-1",
  approved_at: "2026-10-05T00:00:00Z",
});

/** Controlled harness: value is local state so edit-after-approve can be
 *  exercised against a fixed (server-recorded) approval prop. */
function Harness({
  initialValue,
  initialApproval = null,
  onApprove = vi.fn(),
  approveDisabled = false,
  disabled = false,
}: {
  initialValue: string;
  initialApproval?: TriggerApproval | null;
  onApprove?: (description: string) => void | Promise<unknown>;
  approveDisabled?: boolean;
  disabled?: boolean;
}) {
  const [value, setValue] = useState(initialValue);
  return (
    <TriggerApprovalBlock
      value={value}
      onChange={setValue}
      approval={initialApproval}
      onApprove={onApprove}
      approveDisabled={approveDisabled}
      disabled={disabled}
    />
  );
}

describe("TriggerApprovalBlock", () => {
  it("renders the trigger editable and approves the edited value", async () => {
    const onApprove = vi.fn();
    const user = userEvent.setup();
    render(
      <Harness initialValue="Perfil de eneatipos" onApprove={onApprove} />,
    );

    const block = screen.getByTestId("trigger-approval-block");
    const input = within(block).getByLabelText(
      tEs("triggerApproval.inputAria"),
    );
    expect(input).toHaveValue("Perfil de eneatipos");
    expect(
      within(block).getByTestId("trigger-approval-badge"),
    ).toHaveTextContent(tEs("triggerApproval.badgePending"));

    await user.clear(input);
    await user.type(input, "Cuando el autor pide un perfil");
    await user.click(within(block).getByTestId("trigger-approve"));

    expect(onApprove).toHaveBeenCalledWith("Cuando el autor pide un perfil");
  });

  it("shows the ≤60 authored counter and refuses to approve over the bound", async () => {
    const user = userEvent.setup();
    render(<Harness initialValue="" />);

    const block = screen.getByTestId("trigger-approval-block");
    const input = within(block).getByLabelText(
      tEs("triggerApproval.inputAria"),
    );
    await user.type(input, "x".repeat(61));

    expect(
      within(block).getByTestId("trigger-approval-counter"),
    ).toHaveTextContent(
      tEs("triggerApproval.counter", { count: 61, limit: 60 }),
    );
    expect(within(block).getByTestId("trigger-approval-over")).toHaveTextContent(
      tEs("triggerApproval.overBound", { limit: 60 }),
    );
    expect(within(block).getByTestId("trigger-approve")).toBeDisabled();
  });

  it("bounds the preview to ≤57 with a visible truncation marker (58–60 admissible)", () => {
    render(<Harness initialValue={"a".repeat(58)} />);

    const block = screen.getByTestId("trigger-approval-block");
    const preview = within(block).getByTestId("trigger-approval-preview");
    expect(preview.textContent).toHaveLength(57);
    expect(preview.textContent?.endsWith("…")).toBe(true);
    expect(
      within(block).getByTestId("trigger-approval-truncated"),
    ).toHaveTextContent(tEs("triggerApproval.truncated", { limit: 57 }));
  });

  it("keeps the preview verbatim at or below 57 with no truncation marker", () => {
    render(<Harness initialValue={"b".repeat(57)} />);
    const block = screen.getByTestId("trigger-approval-block");
    expect(
      within(block).getByTestId("trigger-approval-preview").textContent,
    ).toBe("b".repeat(57));
    expect(
      within(block).queryByTestId("trigger-approval-truncated"),
    ).not.toBeInTheDocument();
  });

  it("presents exactly one approve affordance — never a batch (D6)", () => {
    render(
      <Harness initialValue="Gatillo" initialApproval={approval("Gatillo")} />,
    );
    const block = screen.getByTestId("trigger-approval-block");
    const buttons = within(block).getAllByRole("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toBe(screen.getByTestId("trigger-approve"));
  });

  it("renders the approved badge when the approval matches the current value", () => {
    render(
      <Harness initialValue="Gatillo" initialApproval={approval("Gatillo")} />,
    );
    expect(screen.getByTestId("trigger-approval-badge")).toHaveTextContent(
      tEs("triggerApproval.badgeApproved"),
    );
  });

  it("reverts to pending when the trigger is edited after approval (D7)", async () => {
    const user = userEvent.setup();
    render(
      <Harness initialValue="Gatillo" initialApproval={approval("Gatillo")} />,
    );

    const block = screen.getByTestId("trigger-approval-block");
    expect(
      within(block).getByTestId("trigger-approval-badge"),
    ).toHaveTextContent(tEs("triggerApproval.badgeApproved"));

    const input = within(block).getByLabelText(
      tEs("triggerApproval.inputAria"),
    );
    await user.type(input, " editado");

    expect(
      within(block).getByTestId("trigger-approval-badge"),
    ).toHaveTextContent(tEs("triggerApproval.badgePending"));
  });

  it("disables approve when empty and while approveDisabled is set", () => {
    const { rerender } = render(<Harness initialValue="" />);
    expect(screen.getByTestId("trigger-approve")).toBeDisabled();

    rerender(<Harness initialValue="Gatillo" approveDisabled />);
    expect(screen.getByTestId("trigger-approve")).toBeDisabled();
  });
});
