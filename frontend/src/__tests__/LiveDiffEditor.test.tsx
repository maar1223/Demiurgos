import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import LiveDiffEditor, {
  type LiveDiffEditorHandle,
} from "@/components/organisms/LiveDiffEditor";

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
});
