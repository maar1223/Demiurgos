import { describe, it, expect, vi } from "vitest";
import { render, screen, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Breadcrumb } from "@/components/molecules/Breadcrumb";

// jsdom has no layout engine (clientWidth/scrollWidth are 0) and no
// ResizeObserver — stub the observer so tests can drive the measurement
// callback manually after faking the widths.
const { roCallback } = vi.hoisted(() => ({
  roCallback: { current: null as null | ResizeObserverCallback },
}));

class ResizeObserverStub {
  constructor(cb: ResizeObserverCallback) {
    roCallback.current = cb;
  }
  observe() {}
  disconnect() {}
  unobserve() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

const shortSegments = ["Vibrantes", "lore", "notas.md"];
const deepSegments = [
  "Vibrantes",
  "personajes",
  "aliados",
  "elite",
  "guardia",
  "Bira.md",
];

function forceOverflow(container: HTMLElement, measure: HTMLElement) {
  Object.defineProperty(container, "clientWidth", {
    value: 200,
    configurable: true,
  });
  Object.defineProperty(measure, "scrollWidth", {
    value: 1000,
    configurable: true,
  });
  // The measurement callback calls setState — flush it inside act() so the
  // re-render happens before the assertions.
  act(() => {
    roCallback.current?.([] as ResizeObserverEntry[], {} as ResizeObserver);
  });
}

describe("Breadcrumb", () => {
  it("renders every segment when everything fits", () => {
    render(<Breadcrumb segments={deepSegments} onSegmentClick={vi.fn()} />);

    // No forced widths: 0 > 0 is false, so no overflow — full list shows
    expect(
      screen.getByRole("button", { name: "Vibrantes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "aliados" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "elite" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Mostrar todos los niveles" }),
    ).not.toBeInTheDocument();
  });

  it("last segment is the active chip, not a button", () => {
    render(<Breadcrumb segments={shortSegments} onSegmentClick={vi.fn()} />);

    expect(
      screen.queryByRole("button", { name: "notas.md" }),
    ).not.toBeInTheDocument();
  });

  it("collapses to head + ellipsis + tail when the list overflows", () => {
    const { container } = render(
      <Breadcrumb segments={deepSegments} onSegmentClick={vi.fn()} />,
    );
    const nav = container.querySelector('[data-testid="breadcrumb-nav"]')!;
    const measure = container.querySelector(
      '[data-testid="breadcrumb-measure"]',
    )!;
    forceOverflow(nav as HTMLElement, measure as HTMLElement);

    // Head kept
    expect(
      screen.getByRole("button", { name: "Vibrantes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "personajes" }),
    ).toBeInTheDocument();
    // Tail kept (last two): "guardia" as button, "Bira.md" as active chip
    expect(
      screen.getByRole("button", { name: "guardia" }),
    ).toBeInTheDocument();
    expect(
      within(nav as HTMLElement).getByText("Bira.md"),
    ).toBeInTheDocument();
    // Hidden middle segments + expandable ellipsis
    expect(
      screen.queryByRole("button", { name: "aliados" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "elite" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Mostrar todos los niveles" }),
    ).toBeInTheDocument();
  });

  it("does not collapse short routes even when overflowing", () => {
    const { container } = render(
      <Breadcrumb segments={shortSegments} onSegmentClick={vi.fn()} />,
    );
    const nav = container.querySelector('[data-testid="breadcrumb-nav"]')!;
    const measure = container.querySelector(
      '[data-testid="breadcrumb-measure"]',
    )!;
    forceOverflow(nav as HTMLElement, measure as HTMLElement);

    // 3 segments < 5: collapsing would hide almost everything — keep all
    expect(
      screen.getByRole("button", { name: "Vibrantes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "lore" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Mostrar todos los niveles" }),
    ).not.toBeInTheDocument();
  });

  it("ellipsis expands to the full list and collapses back", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <Breadcrumb segments={deepSegments} onSegmentClick={vi.fn()} />,
    );
    const nav = container.querySelector('[data-testid="breadcrumb-nav"]')!;
    const measure = container.querySelector(
      '[data-testid="breadcrumb-measure"]',
    )!;
    forceOverflow(nav as HTMLElement, measure as HTMLElement);

    await user.click(
      screen.getByRole("button", { name: "Mostrar todos los niveles" }),
    );

    // Expanded: every segment visible again
    expect(
      screen.getByRole("button", { name: "aliados" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "elite" }),
    ).toBeInTheDocument();

    // Collapse back
    await user.click(
      screen.getByRole("button", { name: "Ocultar niveles intermedios" }),
    );
    expect(
      screen.queryByRole("button", { name: "aliados" }),
    ).not.toBeInTheDocument();
  });

  it("clicking a segment reports its original index", async () => {
    const user = userEvent.setup();
    const onSegmentClick = vi.fn();
    render(<Breadcrumb segments={deepSegments} onSegmentClick={onSegmentClick} />);

    await user.click(screen.getByRole("button", { name: "aliados" }));
    expect(onSegmentClick).toHaveBeenCalledWith(2);
  });
});
