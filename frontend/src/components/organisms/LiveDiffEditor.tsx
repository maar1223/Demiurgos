import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { Compartment } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, highlightActiveLine, drawSelection } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { MergeView } from "@codemirror/merge";
import { oneDark } from "@codemirror/theme-one-dark";

/**
 * Safe minimal extensions shared by both sides of the MergeView.
 *
 * IMPORTANT: do NOT use the full `basicSetup` from the `codemirror` meta
 * package inside a MergeView — it bundles gutters/lineNumbers/history that
 * conflict with the merge view's own gutter and change tracking, which
 * crashes at runtime (white screen + Vite full reload). Keep only the
 * extensions that are safe per-side. Editability is applied separately via
 * a Compartment so it can toggle at runtime.
 */
const sideExtensions = () => [
  lineNumbers(),
  highlightActiveLine(),
  drawSelection(),
  history(),
  keymap.of([...defaultKeymap, ...historyKeymap]),
  EditorView.theme({
    "&": { height: "100%" },
    ".cm-scroller": { overflow: "auto", fontFamily: "inherit" },
    ".cm-gutters": { backgroundColor: "transparent" },
  }),
  oneDark,
];

export interface LiveDiffEditorHandle {
  /** Insert text at the current cursor position of editor B (the editable side). */
  insertText(text: string): void;
}

interface LiveDiffEditorProps {
  /** Original (read-only) content — editor A, left side. */
  original: string;
  /** Edited content — editor B, right side. */
  value: string;
  /** Called with the new content whenever editor B changes. */
  onChange: (value: string) => void;
  /** When true, editor B is also read-only. */
  readOnly?: boolean;
}

/**
 * Live side-by-side diff editor built on CodeMirror's MergeView.
 *
 * Editor A (left, red) shows the original file, read-only. Editor B (right,
 * green) is the editable draft. The merge view recomputes the red/green
 * highlighting client-side on every keystroke — no backend diff calls.
 *
 * Uses the imperative `new MergeView({...})` API appended to a container div.
 * External `value`/`original` changes are synced into the editors with a
 * full-document dispatch, but ONLY when the incoming string differs from the
 * current document, so typing inside editor B never jumps the cursor.
 *
 * StrictMode double-mounts effects in dev: cleanup calls `destroy()`, which
 * removes the view's DOM, so the second mount creates a fresh view on the
 * same node. No dataset guard is needed (and it would break the destroy path).
 */
export const LiveDiffEditor = forwardRef<
  LiveDiffEditorHandle,
  LiveDiffEditorProps
>(function LiveDiffEditor({ original, value, onChange, readOnly = false }, ref) {  const containerRef = useRef<HTMLDivElement>(null);
  const mergeViewRef = useRef<MergeView | null>(null);
  const onChangeRef = useRef(onChange);
  const readOnlyRef = useRef(readOnly);
  const editableCompartmentRef = useRef(new Compartment());

  // Keep the latest callbacks without recreating the MergeView
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  // Toggle editability of editor B without recreating the view
  useEffect(() => {
    readOnlyRef.current = readOnly;
    const view = mergeViewRef.current;
    if (view) {
      view.b.dispatch({
        effects: editableCompartmentRef.current.reconfigure(
          EditorView.editable.of(!readOnly),
        ),
      });
    }
  }, [readOnly]);

  // Create the merge view once on mount; destroy on unmount
  useEffect(() => {
    if (mergeViewRef.current) return;
    const editable = !readOnlyRef.current;

    const view = new MergeView({
      a: {
        doc: original,
        extensions: [...sideExtensions(), EditorView.editable.of(false)],
      },
      b: {
        doc: value,
        extensions: [
          ...sideExtensions(),
          editableCompartmentRef.current.of(EditorView.editable.of(editable)),
          EditorView.contentAttributes.of({ "aria-label": "Editor de contenido" }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              onChangeRef.current(update.state.doc.toString());
            }
          }),
        ],
      },
      parent: containerRef.current as HTMLDivElement,
      orientation: "a-b",
      highlightChanges: true,
      gutter: true,
      collapseUnchanged: { margin: 3, minSize: 4 },
    });
    mergeViewRef.current = view;

    return () => {
      view.destroy();
      mergeViewRef.current = null;
    };
    // Create only once — later prop changes flow through the sync effects
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync external value changes into editor B (skip when identical, so
  // keystrokes inside the editor never trigger a redundant dispatch)
  useEffect(() => {
    const view = mergeViewRef.current;
    if (!view) return;
    const bDoc = view.b.state.doc.toString();
    if (value !== bDoc) {
      view.b.dispatch({
        changes: { from: 0, to: bDoc.length, insert: value },
      });
    }
  }, [value]);

  // Sync external original changes into editor A (read-only side)
  useEffect(() => {
    const view = mergeViewRef.current;
    if (!view) return;
    const aDoc = view.a.state.doc.toString();
    if (original !== aDoc) {
      view.a.dispatch({
        changes: { from: 0, to: aDoc.length, insert: original },
      });
    }
  }, [original]);

  useImperativeHandle(
    ref,
    () => ({
      insertText(text: string) {
        const view = mergeViewRef.current;
        if (!view) return;
        const b = view.b;
        const { from, to } = b.state.selection.main;
        b.dispatch({
          changes: { from, to, insert: text },
          selection: { anchor: from + text.length },
          scrollIntoView: true,
        });
        b.focus();
      },
    }),
    [],
  );

  return (
    <div
      ref={containerRef}
      data-testid="live-diff-editor"
      className="h-[70vh] w-full overflow-hidden rounded-lg border border-filio bg-madero"
    />
  );
});

export default LiveDiffEditor;
