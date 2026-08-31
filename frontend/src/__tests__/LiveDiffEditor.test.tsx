import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef, useState } from "react";
import type { Ref } from "react";
import LiveDiffEditor, {
  type LiveDiffEditorHandle,
} from "@/components/organisms/LiveDiffEditor";

/**
 * Controlled harness: holds `value` in local state exactly like WikiEditor
 * does, so split/join/insertText go through the full diff recompute instead
 * of ending at a bare onChange spy. This also lets tests observe the caret
 * restoration (focus + selection) the pending-caret mechanism performs after
 * a re-render.
 */
function StatefulHarness({
  original,
  editorRef,
}: {
  original: string;
  editorRef?: Ref<LiveDiffEditorHandle>;
}) {
  const [value, setValue] = useState(original);
  return (
    <LiveDiffEditor
      original={original}
      value={value}
      onChange={setValue}
      ref={editorRef}
    />
  );
}

describe("LiveDiffEditor", () => {
  it("typing in side B replaces the line in the document", async () => {
    const original = "linea uno\nlinea dos\nlinea tres";
    const value = "linea uno\nlinea X\nlinea tres";
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LiveDiffEditor original={original} value={value} onChange={onChange} />,
    );

    const ta = screen.getByLabelText("Editar línea 2") as HTMLTextAreaElement;
    ta.setSelectionRange(ta.value.length, ta.value.length);
    await user.type(ta, "2");

    expect(onChange).toHaveBeenCalledWith("linea uno\nlinea X2\nlinea tres");
  });

  it("Enter splits the line at the caret", () => {
    const original = "linea uno\nlinea dos\nlinea tres";
    const value = "linea uno\nlinea X\nlinea tres";
    const onChange = vi.fn();

    render(
      <LiveDiffEditor original={original} value={value} onChange={onChange} />,
    );

    const ta = screen.getByLabelText("Editar línea 2") as HTMLTextAreaElement;
    ta.setSelectionRange(5, 5);
    fireEvent.keyDown(ta, { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith("linea uno\nlinea\n X\nlinea tres");
  });

  it("Backspace at column 0 joins with the previous line", () => {
    const original = "linea uno\nlinea dos\nlinea tres";
    const value = "linea uno\nlinea X\nlinea tres";
    const onChange = vi.fn();

    render(
      <LiveDiffEditor original={original} value={value} onChange={onChange} />,
    );

    const ta = screen.getByLabelText("Editar línea 2") as HTMLTextAreaElement;
    ta.setSelectionRange(0, 0);
    fireEvent.keyDown(ta, { key: "Backspace" });

    expect(onChange).toHaveBeenCalledWith("linea unolinea X\nlinea tres");
  });

  it("insertText inserts at the caret of the focused line", () => {
    const original = "linea uno\nlinea dos\nlinea tres";
    const value = original;
    const onChange = vi.fn();
    const ref = createRef<LiveDiffEditorHandle>();

    render(
      <LiveDiffEditor
        original={original}
        value={value}
        onChange={onChange}
        ref={ref}
      />,
    );

    const ta = screen.getByLabelText("Editar línea 2") as HTMLTextAreaElement;
    fireEvent.focus(ta);
    ta.setSelectionRange(6, 6);

    act(() => {
      ref.current?.insertText("[[X]]");
    });

    expect(onChange).toHaveBeenCalledWith("linea uno\nlinea [[X]]dos\nlinea tres");
  });

  it("insertText appends at the end of the document when no line is focused", () => {
    const original = "linea uno\nlinea dos\nlinea tres";
    const onChange = vi.fn();
    const ref = createRef<LiveDiffEditorHandle>();

    render(
      <LiveDiffEditor
        original={original}
        value={original}
        onChange={onChange}
        ref={ref}
      />,
    );

    act(() => {
      ref.current?.insertText(" fin");
    });

    expect(onChange).toHaveBeenCalledWith("linea uno\nlinea dos\nlinea tres fin");
  });

  describe("controlled editing (caret restoration + live recompute)", () => {
    it("Enter split restores focus and caret to the new line", () => {
      const original = "linea uno\nlinea dos\nlinea tres";

      render(<StatefulHarness original={original} />);

      const ta = screen.getByLabelText("Editar línea 2") as HTMLTextAreaElement;
      ta.setSelectionRange(5, 5);
      fireEvent.keyDown(ta, { key: "Enter" });

      const newLine = screen.getByLabelText("Editar línea 3") as HTMLTextAreaElement;
      expect(newLine).toHaveValue(" dos");
      expect(newLine).toHaveFocus();
      expect(newLine.selectionStart).toBe(0);
    });

    it("Backspace at column 0 joins lines and restores the caret at the join point", () => {
      const original = "linea uno\nlinea dos\nlinea tres";

      render(<StatefulHarness original={original} />);

      const ta = screen.getByLabelText("Editar línea 3") as HTMLTextAreaElement;
      ta.setSelectionRange(0, 0);
      fireEvent.keyDown(ta, { key: "Backspace" });

      const joined = screen.getByLabelText("Editar línea 2") as HTMLTextAreaElement;
      expect(joined).toHaveValue("linea doslinea tres");
      expect(joined).toHaveFocus();
      expect(joined.selectionStart).toBe("linea doslinea tres".length);
    });

    it("editing a line recomputes the diff highlight in place", () => {
      const original = "linea uno\nlinea dos\nlinea tres";

      render(<StatefulHarness original={original} />);

      const ta = screen.getByLabelText("Editar línea 2") as HTMLTextAreaElement;
      fireEvent.change(ta, { target: { value: "linea dos!" } });

      // The old text now shows as removed (left) and the new text as added
      // (right) on the SAME row — recomputed from the props, not a stale snapshot
      expect(screen.getByText("linea dos", { selector: "div" })).toHaveClass(
        "border-status-error",
        "bg-status-error/30",
      );
      const edited = screen.getByLabelText("Editar línea 2") as HTMLTextAreaElement;
      expect(edited).toHaveValue("linea dos!");
      expect(edited).toHaveClass("border-status-success", "bg-status-success/30");
    });

    it("insertText replaces the current selection of the focused line", () => {
      const original = "linea uno\nlinea dos\nlinea tres";
      const ref = createRef<LiveDiffEditorHandle>();

      render(<StatefulHarness original={original} editorRef={ref} />);

      const ta = screen.getByLabelText("Editar línea 2") as HTMLTextAreaElement;
      fireEvent.focus(ta);
      ta.setSelectionRange(6, 9); // selects "dos"

      act(() => {
        ref.current?.insertText("[[X]]");
      });

      const updated = screen.getByLabelText("Editar línea 2") as HTMLTextAreaElement;
      expect(updated).toHaveValue("linea [[X]]");
      expect(updated).toHaveFocus();
      expect(updated.selectionStart).toBe(11);
      expect(updated.selectionEnd).toBe(11);
    });
  });

  describe("rendering", () => {
    const LINE_ONE = "uno";
    const LINE_TWO = "dos";
    const LINE_THREE = "tres";

    it("shows 'Sin diferencias' for an empty diff", () => {
      render(<LiveDiffEditor original="" value="" onChange={vi.fn()} />);

      expect(screen.getByText("Sin diferencias")).toBeInTheDocument();
      expect(screen.queryByLabelText(/Editar línea/)).not.toBeInTheDocument();
    });

    it("renders the read-only and edited column headers", () => {
      render(
        <LiveDiffEditor
          original={LINE_ONE}
          value={LINE_ONE}
          onChange={vi.fn()}
        />,
      );

      expect(screen.getByText("Original · solo lectura")).toBeInTheDocument();
      expect(
        screen.getByText("Editado · hacé clic y escribí"),
      ).toBeInTheDocument();
    });

    it("renders unchanged rows with neutral cells", () => {
      render(
        <LiveDiffEditor
          original={LINE_ONE}
          value={LINE_ONE}
          onChange={vi.fn()}
        />,
      );

      // The line appears twice: the read-only left cell and the editable
      // right textarea — both must be neutral (no diff highlight)
      const [leftCell, rightCell] = screen.getAllByText(LINE_ONE);
      expect(leftCell.tagName).toBe("DIV");
      expect(leftCell).toHaveClass("border-transparent");
      expect(rightCell.tagName).toBe("TEXTAREA");
      expect(rightCell).toHaveClass("border-transparent", "bg-transparent");
    });

    it("highlights added lines green and numbers the right gutter", () => {
      const original = [LINE_ONE, LINE_TWO, LINE_THREE].join("\n");
      const value = original + "\ncuatro";

      render(
        <LiveDiffEditor original={original} value={value} onChange={vi.fn()} />,
      );

      // The added line is editable with the green highlight
      const textarea = screen.getByLabelText("Editar línea 4");
      expect(textarea).toHaveClass("border-status-success", "bg-status-success/30");
      // Right gutter shows the added line number
      expect(screen.getByText("4")).toBeInTheDocument();
    });

    it("highlights removed lines red with no editable counterpart", () => {
      const original = [LINE_ONE, "borrada", LINE_THREE].join("\n");
      const value = [LINE_ONE, LINE_THREE].join("\n");

      render(
        <LiveDiffEditor original={original} value={value} onChange={vi.fn()} />,
      );

      const removed = screen.getByText("borrada");
      expect(removed).toHaveClass("border-status-error", "bg-status-error/30");
      // Only the two surviving lines are editable
      expect(screen.queryAllByLabelText(/Editar línea/)).toHaveLength(2);
      // Left gutter keeps the removed line number; the right gutter of the
      // same row is empty and the following row re-numbers to 2 — both "2"s
      // prove the row alignment
      expect(screen.getAllByText("2")).toHaveLength(2);
    });

    it("renders changed lines as old text (red) on the left and new text (green) on the right", () => {
      const original = [LINE_ONE, "vieja", LINE_THREE].join("\n");
      const value = [LINE_ONE, "nueva", LINE_THREE].join("\n");

      render(
        <LiveDiffEditor original={original} value={value} onChange={vi.fn()} />,
      );

      expect(screen.getByText("vieja")).toHaveClass(
        "border-status-error",
        "bg-status-error/30",
      );
      const textarea = screen.getByLabelText("Editar línea 2");
      expect(textarea).toHaveValue("nueva");
      expect(textarea).toHaveClass("border-status-success", "bg-status-success/30");
      // Both gutters are numbered 2 — old and new line share the grid row
      expect(screen.getAllByText("2")).toHaveLength(2);
    });

    it("escapes raw HTML in line content (no script execution)", () => {
      const xss = "<script>alert('xss')</script>";
      const { container } = render(
        <LiveDiffEditor original={xss} value={xss} onChange={vi.fn()} />,
      );

      // Rendered as plain text (left cell), never as an injected element
      expect(
        screen.getAllByText(xss).some((el) => el.tagName === "DIV"),
      ).toBe(true);
      expect(container.querySelector("script")).toBeNull();
    });
  });
});
