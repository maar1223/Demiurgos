import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Tooltip } from "@/components/atoms/Tooltip";

const CONFLICT_COPY =
  "Esta skill es transversal de Taller de Mundo pero su taller primario (Taller de Ideas) ya tiene una skill activa en este mundo.";

function renderTooltip() {
  render(
    <Tooltip id="conflict-tip" content={CONFLICT_COPY}>
      <span data-testid="trigger">!</span>
    </Tooltip>,
  );
}

describe("Tooltip atom (axis-binding-ui R5)", () => {
  it("links the trigger to the accessible copy via aria-describedby", () => {
    renderTooltip();

    const trigger = screen.getByTestId("trigger").closest(
      "[aria-describedby]",
    ) as HTMLElement;
    expect(trigger).not.toBeNull();
    expect(trigger).toHaveAttribute("aria-describedby", "conflict-tip");

    const accessible = document.getElementById("conflict-tip");
    expect(accessible).not.toBeNull();
    expect(accessible).toHaveAttribute("role", "tooltip");
    expect(accessible).toHaveClass("sr-only");
  });

  it("renders the copy twice: the sr-only accessible copy and the visible bubble", () => {
    renderTooltip();

    expect(screen.getAllByText(CONFLICT_COPY)).toHaveLength(2);
    expect(screen.getByText(CONFLICT_COPY, { selector: ".sr-only" }))
      .toBeInTheDocument();
  });

  it("reveals the bubble on hover and focus-visible via CSS classes (no JS)", () => {
    renderTooltip();

    const bubble = screen.getByText(CONFLICT_COPY, {
      selector: "[aria-hidden=true]",
    });
    expect(bubble).toHaveAttribute("aria-hidden", "true");
    expect(bubble).toHaveClass("opacity-0");
    expect(bubble).toHaveClass("group-hover:opacity-100");
    expect(bubble).toHaveClass("group-focus-within:opacity-100");
  });
});