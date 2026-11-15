import { beforeEach, describe, expect, it } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { EditorLayout } from "@/components/templates/EditorLayout";
import { TabBar } from "@/components/molecules/TabBar";
import {
  AUTO_WIDEN_MIN_VIEWPORT,
  MAIN_CONTENT_MIN_PX,
  PANEL_AUTO_WIDEN_STORAGE_KEY,
  activeRightPanelWidth,
  collapsedRightPanelWidth,
  readAutoWidenPreference,
  rightPanelBounds,
  setAutoWidenPreference,
  supportsAutoWiden,
} from "@/lib/panelAutoWiden";

/** Left panel width as `EditorLayout` clamps it today (20%–40%, default 240). */
const leftFor = (viewportWidth: number) =>
  Math.min(
    Math.round(viewportWidth * 0.4),
    Math.max(Math.round(viewportWidth * 0.2), 240),
  );

const setViewport = (width: number) => {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    writable: true,
    value: width,
  });
};

const renderLayout = (
  props: Partial<React.ComponentProps<typeof EditorLayout>> = {},
) =>
  render(
    <EditorLayout
      sidebar={<div>files</div>}
      rightPanel={<div>panel content</div>}
      assistantPanel
      {...props}
    >
      <div>article</div>
    </EditorLayout>,
  );

const panelAside = () =>
  screen.getByText("panel content").closest("aside") as HTMLElement;

describe("panelAutoWiden preference", () => {
  it("defaults to enabled when nothing was stored", () => {
    expect(readAutoWidenPreference()).toBe(true);
  });

  it("persists the opt-out and the explicit opt-in", () => {
    setAutoWidenPreference(false);
    expect(window.localStorage.getItem(PANEL_AUTO_WIDEN_STORAGE_KEY)).toBe("off");
    expect(readAutoWidenPreference()).toBe(false);

    setAutoWidenPreference(true);
    expect(window.localStorage.getItem(PANEL_AUTO_WIDEN_STORAGE_KEY)).toBe("on");
    expect(readAutoWidenPreference()).toBe(true);
  });

  it("falls back to enabled for an unknown stored value", () => {
    window.localStorage.setItem(PANEL_AUTO_WIDEN_STORAGE_KEY, "garbage");
    expect(readAutoWidenPreference()).toBe(true);
  });
});

describe("right panel geometry", () => {
  it("keeps the expanded width between the collapsed width and the cap", () => {
    for (const viewport of [1024, 1280, 1366, 1920, 2560] as const) {
      const left = leftFor(viewport);
      const collapsed = collapsedRightPanelWidth(viewport, left);
      const active = activeRightPanelWidth(viewport, left);
      const { min, max } = rightPanelBounds(viewport, left);

      expect(min).toBeLessThanOrEqual(collapsed);
      expect(collapsed).toBeLessThanOrEqual(active);
      expect(active).toBeLessThanOrEqual(max);
    }
  });

  it("keeps a real difference between both states on wide screens", () => {
    const viewport = 2560;
    const left = leftFor(viewport);
    expect(
      activeRightPanelWidth(viewport, left) -
        collapsedRightPanelWidth(viewport, left),
    ).toBeGreaterThanOrEqual(120);
  });

  it("never takes the article below its minimum where auto-widen applies", () => {
    for (const viewport of [1024, 1280, 1366, 1920, 2560, 3440] as const) {
      const left = leftFor(viewport);
      const { max } = rightPanelBounds(viewport, left);
      expect(viewport - left - max).toBeGreaterThanOrEqual(MAIN_CONTENT_MIN_PX);
    }
  });

  it("applies auto-widen only from the desktop threshold up", () => {
    // Below 1280 the article floor eats almost the whole third, so the jump
    // would not be worth the article space it takes.
    expect(AUTO_WIDEN_MIN_VIEWPORT).toBe(1280);
    expect(supportsAutoWiden(AUTO_WIDEN_MIN_VIEWPORT - 1)).toBe(false);
    expect(supportsAutoWiden(AUTO_WIDEN_MIN_VIEWPORT)).toBe(true);
  });
});

describe("EditorLayout auto-widen", () => {
  beforeEach(() => {
    setViewport(1366);
  });

  it("starts collapsed and widens on interaction with the assistant", () => {
    renderLayout();
    expect(panelAside().style.width).toBe("342px");

    fireEvent.pointerDown(screen.getByText("panel content"));
    expect(panelAside().style.width).toBe("455px");
  });

  it("widens when focus enters the assistant panel", () => {
    renderLayout();
    fireEvent.focusIn(screen.getByText("panel content"));
    expect(panelAside().style.width).toBe("455px");
  });

  it("collapses on the next interaction outside the assistant", () => {
    renderLayout();
    fireEvent.pointerDown(screen.getByText("panel content"));
    expect(panelAside().style.width).toBe("455px");

    fireEvent.pointerDown(screen.getByText("article"));
    expect(panelAside().style.width).toBe("342px");
  });

  it("collapses when keyboard focus leaves the assistant", () => {
    renderLayout();
    const panel = screen.getByText("panel content");
    fireEvent.focusIn(panel);
    expect(panelAside().style.width).toBe("455px");

    fireEvent.focusOut(panel, { relatedTarget: screen.getByText("article") });
    expect(panelAside().style.width).toBe("342px");
  });

  it("holds the expanded width while the assistant is responding", () => {
    const view = renderLayout({ assistantBusy: true });
    fireEvent.pointerDown(screen.getByText("panel content"));
    fireEvent.pointerDown(screen.getByText("article"));
    expect(panelAside().style.width).toBe("455px");

    view.rerender(
      <EditorLayout sidebar={<div>files</div>} rightPanel={<div>panel content</div>} assistantPanel>
        <div>article</div>
      </EditorLayout>,
    );
    expect(panelAside().style.width).toBe("342px");
  });

  it("does not resize when the preference is off", () => {
    act(() => setAutoWidenPreference(false));
    renderLayout();

    fireEvent.pointerDown(screen.getByText("panel content"));
    expect(panelAside().style.width).toBe("342px");
  });

  it("collapses to the panel resting width when it stops hosting the assistant", () => {
    const view = renderLayout();
    fireEvent.pointerDown(screen.getByText("panel content"));
    expect(panelAside().style.width).toBe("455px");

    view.rerender(
      <EditorLayout sidebar={<div>files</div>} rightPanel={<div>panel content</div>}>
        <div>article</div>
      </EditorLayout>,
    );
    // A fifth of the viewport: the unassisted panel keeps its previous size.
    expect(panelAside().style.width).toBe("273px");
  });

  it("keeps a non-assistant right panel at its resting width", () => {
    render(
      <EditorLayout sidebar={null} rightPanel={<div>methodology panel</div>}>
        <div>article</div>
      </EditorLayout>,
    );

    const aside = screen
      .getByText("methodology panel")
      .closest("aside") as HTMLElement;
    expect(aside.style.width).toBe("273px");

    fireEvent.pointerDown(screen.getByText("methodology panel"));
    expect(aside.style.width).toBe("273px");
  });

  it("turns the automatic behavior off when the divider is dragged", () => {
    renderLayout();

    const divider = screen.getByRole("separator", {
      name: "Redimensionar panel",
    });
    fireEvent.mouseDown(divider, { clientX: 1000 });
    fireEvent.mouseMove(document, { clientX: 940 });
    fireEvent.mouseUp(document);

    expect(readAutoWidenPreference()).toBe(false);
    expect(panelAside().style.width).toBe("402px");
  });
});

describe("TabBar auto-widen toggle", () => {
  it("renders pressed, disables the behavior and explains itself", () => {
    render(<TabBar />);

    const toggle = screen.getByLabelText(
      "Ensanchado automático del asistente",
    );
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "El asistente se ensancha al usarlo",
    );

    fireEvent.click(toggle);

    expect(readAutoWidenPreference()).toBe(false);
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Ancho fijo del asistente",
    );
  });
});
