import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  WizardProgress,
  type WizardProgressStep,
} from "@/components/molecules/WizardProgress";

const STEPS: WizardProgressStep[] = [
  { id: "one", label: "Paso uno" },
  { id: "two", label: "Paso dos" },
  { id: "three", label: "Paso tres" },
];

/** The step column that wraps the given label. */
function columnFor(label: string): HTMLElement {
  return screen.getByText(label).parentElement as HTMLElement;
}

describe("WizardProgress", () => {
  it("renders a check for done steps and the 1-based number otherwise", () => {
    render(<WizardProgress steps={STEPS} current={1} />);

    const done = columnFor("Paso uno");
    expect(within(done).queryByText("1")).not.toBeInTheDocument();
    expect(done.querySelector("svg")).not.toBeNull();

    const current = columnFor("Paso dos");
    expect(within(current).getByText("2")).toBeInTheDocument();
    expect(current.querySelector("svg")).toBeNull();

    const todo = columnFor("Paso tres");
    expect(within(todo).getByText("3")).toBeInTheDocument();
    expect(todo.querySelector("svg")).toBeNull();
  });

  it("marks only the current step with aria-current", () => {
    render(<WizardProgress steps={STEPS} current={1} />);

    expect(columnFor("Paso uno")).not.toHaveAttribute("aria-current");
    expect(columnFor("Paso dos")).toHaveAttribute("aria-current", "step");
    expect(columnFor("Paso tres")).not.toHaveAttribute("aria-current");
  });

  it("renders one connector per gap, painted only before the current step", () => {
    const { container } = render(
      <WizardProgress steps={STEPS} current={1} />,
    );

    const connectors = container.querySelectorAll<HTMLElement>(
      'div[aria-hidden="true"]',
    );
    expect(connectors).toHaveLength(STEPS.length - 1);
    expect(connectors[0].className).toContain("bg-status-success/50");
    expect(connectors[1].className).toContain("bg-surface-raised");
    expect(connectors[1].className).not.toContain("bg-status-success/50");
  });

  it("uses the default landmark label", () => {
    render(<WizardProgress steps={STEPS} current={0} />);

    expect(
      screen.getByRole("navigation", { name: "Progreso de la configuración" }),
    ).toBeInTheDocument();
  });

  it("accepts a custom landmark label", () => {
    render(
      <WizardProgress
        steps={STEPS}
        current={0}
        ariaLabel="Pasos de configuración"
      />,
    );

    expect(
      screen.getByRole("navigation", { name: "Pasos de configuración" }),
    ).toBeInTheDocument();
  });

  it("renders no buttons at all without onSelect", () => {
    render(<WizardProgress steps={STEPS} current={0} />);

    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("renders buttons only for selectable steps and calls onSelect on click", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <WizardProgress
        steps={STEPS}
        current={1}
        onSelect={onSelect}
        canSelect={(index) => index !== 2}
      />,
    );

    // Only the two selectable steps (0 and 1) are buttons.
    expect(screen.queryAllByRole("button")).toHaveLength(2);
    expect(columnFor("Paso uno").tagName).toBe("BUTTON");
    expect(columnFor("Paso dos").tagName).toBe("BUTTON");

    // A non-selectable step stays static, so it is not clickable.
    expect(columnFor("Paso tres").tagName).toBe("DIV");

    // aria-current still lands on the step, here via the button.
    expect(
      screen.getByRole("button", { name: /Paso dos/ }),
    ).toHaveAttribute("aria-current", "step");

    await user.click(screen.getByRole("button", { name: /Paso uno/ }));
    expect(onSelect).toHaveBeenCalledWith(0);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("treats every step as selectable when canSelect is omitted", () => {
    render(<WizardProgress steps={STEPS} current={0} onSelect={vi.fn()} />);

    expect(screen.queryAllByRole("button")).toHaveLength(STEPS.length);
  });

  it("honours explicit states over the derived current-relative completion", () => {
    // `current` says step one is done, but the caller knows from real data that
    // only step two is. Explicit states must win so `done` stays honest.
    render(
      <WizardProgress
        steps={STEPS}
        current={0}
        states={["todo", "done", "todo"]}
      />,
    );

    expect(columnFor("Paso uno").querySelector("svg")).toBeNull();
    expect(within(columnFor("Paso uno")).getByText("1")).toBeInTheDocument();
    expect(columnFor("Paso dos").querySelector("svg")).not.toBeNull();
    expect(columnFor("Paso tres").querySelector("svg")).toBeNull();
  });

  it("paints connectors from explicit states, not from the walked index", () => {
    const { container } = render(
      <WizardProgress
        steps={STEPS}
        current={0}
        states={["done", "todo", "todo"]}
      />,
    );

    const connectors = container.querySelectorAll<HTMLElement>(
      'div[aria-hidden="true"]',
    );
    expect(connectors[0].className).toContain("bg-status-success/50");
    expect(connectors[1].className).not.toContain("bg-status-success/50");
  });
});
