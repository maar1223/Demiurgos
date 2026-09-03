import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { diffLines, splitLines, mergeChangedRows, type DiffRow } from "@/lib/diff";

/**
 * Single grid template shared by the header row and every diff row, so the
 * headers align with the content by construction:
 *
 *   gutter A | content A | divider (1px) | content B | gutter B
 *
 * `minmax(0, 1fr)` content tracks allow pre-wrap text to wrap and shrink
 * without forcing a horizontal scrollbar.
 */
const GRID_TEMPLATE = "grid-cols-[auto_minmax(0,1fr)_1px_minmax(0,1fr)_auto]";

/**
 * Runs of consecutive unchanged lines shorter than this stay fully expanded
 * (rendered line by line, exactly like a plain diff). Only runs of at least
 * this many unchanged lines collapse into the "N líneas sin cambios" band.
 * Kept small so tiny documents — and the "everything unchanged" case — keep
 * the full writing surface visible without any clicking.
 */
const COLLAPSE_THRESHOLD = 4;

/**
 * Lock icon (lucide "lock" path) — used in the read-only header.
 * Inline SVG because lucide-react is not a dependency.
 */
function LockIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

/**
 * Pencil icon (lucide "pencil" path) — used in the edited header.
 * Inline SVG because lucide-react is not a dependency.
 */
function PencilIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" />
      <path d="m15 5 4 4" />
    </svg>
  );
}

export interface LiveDiffEditorHandle {
  /**
   * Insert `text` at the caret of the last focused side-B line. The DOM
   * keeps the selection after blur, so the caret survives focus loss.
   * When no line has ever been focused, append `text` at the end of the
   * document. Used by WikiEditor for wikilink insertion while the preview
   * is open.
   */
  insertText(text: string): void;
}

interface LiveDiffEditorProps {
  /** Original (read-only) content — left pane. */
  original: string;
  /** Edited content — right pane; this is the writing surface. */
  value: string;
  /** Called with the new document after every right-pane edit. */
  onChange: (value: string) => void;
}

/** Caret to restore on a specific right line after the doc re-renders. */
interface PendingCaret {
  /** 1-based line number (same numbering as the right gutter). */
  line: number;
  /** Character offset inside that line. */
  col: number;
}

/** One thing rendered in the row grid: a diff row or a collapsed band. */
type VisibleItem =
  | { kind: "row"; row: DiffRow; index: number }
  | { kind: "band"; start: number; length: number };

interface EditableCellProps {
  /** Line text. */
  text: string;
  /** 1-based line number (matches the right gutter). */
  lineNumber: number;
  /** True when this row is an addition (green highlight). */
  isAdded: boolean;
  /** Pending caret to apply (focus + setSelectionRange), then clear. */
  pendingCaret: PendingCaret | null;
  /** Clear the pending caret once this cell has applied it. */
  onClearPendingCaret: () => void;
  /** Register/unregister the textarea in the parent map keyed by line number. */
  register: (line: number, el: HTMLTextAreaElement | null) => void;
  /** Track the last focused line for the imperative insertText handle. */
  onCellFocus: (line: number) => void;
  /** Replace this line's text in the document. */
  onLineChange: (line: number, nextLine: string) => void;
  /** Split this line at `col` (Enter). */
  onSplitLine: (line: number, col: number) => void;
  /** Merge this line into the previous one (Backspace at column 0). */
  onJoinLines: (line: number) => void;
}

/**
 * One editable line of side B: a controlled, auto-resized textarea. It IS
 * the right grid cell (padding and borders live on the textarea itself), so
 * the shared row keeps both panes aligned as the text wraps.
 */
function EditableCell({
  text,
  lineNumber,
  isAdded,
  pendingCaret,
  onClearPendingCaret,
  register,
  onCellFocus,
  onLineChange,
  onSplitLine,
  onJoinLines,
}: EditableCellProps) {
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  // Auto-resize the textarea to its content so wrapped lines grow the cell
  // and the shared grid row keeps both panes aligned. Guarded: jsdom
  // reports scrollHeight 0, which would collapse the box to "auto".
  useLayoutEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    if (ta.scrollHeight > 0) {
      ta.style.height = `${ta.scrollHeight}px`;
    }
  }, [text]);

  // Apply a pending caret (after insertText / Enter / Backspace) once this
  // line re-renders with the committed text.
  useLayoutEffect(() => {
    if (pendingCaret && pendingCaret.line === lineNumber) {
      const ta = taRef.current;
      if (ta) {
        ta.focus();
        ta.setSelectionRange(pendingCaret.col, pendingCaret.col);
      }
      onClearPendingCaret();
    }
  }, [pendingCaret, lineNumber, onClearPendingCaret]);

  return (
    <textarea
      ref={(el) => {
        taRef.current = el;
        register(lineNumber, el);
      }}
      value={text}
      aria-label={`Editar línea ${lineNumber}`}
      onChange={(e) => onLineChange(lineNumber, e.target.value)}
      onFocus={() => onCellFocus(lineNumber)}
      onKeyDown={(e) => {
        const ta = e.currentTarget;
        if (e.key === "Enter") {
          e.preventDefault();
          onSplitLine(lineNumber, ta.selectionStart);
        } else if (
          e.key === "Backspace" &&
          lineNumber > 1 &&
          ta.selectionStart === 0 &&
          ta.selectionEnd === 0
        ) {
          e.preventDefault();
          onJoinLines(lineNumber);
        }
      }}
      className={`min-h-[1.6rem] min-w-0 max-w-full box-border w-full resize-none overflow-hidden whitespace-pre-wrap overflow-wrap-anywhere border-l-2 border-t-0 border-r-0 border-b-0 px-3 py-0.5 font-mono text-small text-primary outline-none rounded-none focus:ring-1 focus:ring-action/50 ring-offset-0 ${
        isAdded ? "border-status-success bg-status-success/30" : "border-transparent bg-transparent"
      }`}
    />
  );
}

/**
 * Live side-by-side diff rendered as paired grid rows.
 *
 * Each document line is ONE grid row: `[gutterA | contentA | divider |
 * contentB | gutterB]`. Both cells live in the same grid row, so the row
 * auto-grows to the height of the tallest cell and the NEXT row starts at
 * the same Y on both sides — alignment is a CSS guarantee, not JS math.
 * Text wraps INSIDE each cell, so the full document is visible with no
 * horizontal scroll.
 *
 * Modified lines render as a single row with the old text on the left and
 * the new text on the right (status "changed"); pure insertions and pure
 * deletions keep their single-side rows, so the "removed" rows in the diff
 * still show the empty counterpart cell.
 *
 * Side A is read-only. Side B is the writing surface: every right line is a
 * controlled textarea that reports edits back through `onChange` line by
 * line, so the diff recomputes on every keystroke. Enter splits a line,
 * Backspace at column 0 joins with the previous line, and the imperative
 * `insertText` handle splices text at the caret of the last focused line —
 * used by WikiEditor for wikilink insertion.
 */
export const LiveDiffEditor = forwardRef<LiveDiffEditorHandle, LiveDiffEditorProps>(
  function LiveDiffEditor({ original, value, onChange }, ref) {
    const rows = useMemo(
      () => mergeChangedRows(diffLines(splitLines(original), splitLines(value))),
      [original, value],
    );

    // True when the document differs from the original at all. A fully
    // unchanged document keeps every line expanded — the diff pane IS the
    // writing surface there, and collapsing the whole doc into one band
    // would leave nothing to edit.
    const hasChanges = useMemo(
      () => rows.some((row) => row.status !== "same"),
      [rows],
    );

    // Unchanged runs the user has expanded (keyed by run start index). Runs
    // below COLLAPSE_THRESHOLD are never collapsible and never stored here.
    const [expandedRuns, setExpandedRuns] = useState<Set<number>>(() => new Set());

    // Flat render list: changed rows always render; unchanged runs render as
    // individual rows when small/expanded, or as one band when collapsed.
    const visibleItems = useMemo<VisibleItem[]>(() => {
      const items: VisibleItem[] = [];
      let i = 0;
      while (i < rows.length) {
        if (rows[i].status !== "same") {
          items.push({ kind: "row", row: rows[i], index: i });
          i++;
          continue;
        }
        const start = i;
        while (i < rows.length && rows[i].status === "same") i++;
        const length = i - start;
        const collapsed = length >= COLLAPSE_THRESHOLD && hasChanges && !expandedRuns.has(start);
        if (collapsed) {
          items.push({ kind: "band", start, length });
        } else {
          for (let k = start; k < start + length; k++) {
            items.push({ kind: "row", row: rows[k], index: k });
          }
        }
      }
      return items;
    }, [rows, hasChanges, expandedRuns]);

    // Side-B textareas keyed by 1-based line number.
    const textareaRefs = useRef(new Map<number, HTMLTextAreaElement>());

    // Last focused side-B line; the DOM keeps the selection after blur, so
    // insertText can still splice at the exact caret.
    const focusedLineRef = useRef<number | null>(null);

    // Caret to restore after a re-render (insertText / Enter / Backspace).
    const [pendingCaret, setPendingCaret] = useState<PendingCaret | null>(null);

    const registerTextarea = useCallback(
      (line: number, el: HTMLTextAreaElement | null) => {
        if (el) textareaRefs.current.set(line, el);
        else textareaRefs.current.delete(line);
      },
      [],
    );

    const handleCellFocus = useCallback((line: number) => {
      focusedLineRef.current = line;
    }, []);

    const clearPendingCaret = useCallback(() => setPendingCaret(null), []);

    // Expand an unchanged run: the band button is only rendered while the
    // run is collapsed, so clicking it always expands. Expanded runs render
    // as plain rows (the full writing surface), so no collapse affordance
    // is needed.
    const expandRun = useCallback((start: number) => {
      setExpandedRuns((prev) => {
        const next = new Set(prev);
        next.add(start);
        return next;
      });
    }, []);

    // Replace one document line, preserving the exact byte layout (plain
    // split/join, NOT splitLines — that strips a trailing newline).
    const handleLineChange = useCallback(
      (line: number, nextLine: string) => {
        const lines = value.split("\n");
        lines[line - 1] = nextLine;
        onChange(lines.join("\n"));
      },
      [value, onChange],
    );

    // Enter: split the line at the caret. Line numbers shift by +1 — the
    // new line is `line + 1` (rightNumber is 1-based and contiguous).
    const handleSplitLine = useCallback(
      (line: number, col: number) => {
        const lines = value.split("\n");
        const current = lines[line - 1];
        lines.splice(line - 1, 1, current.slice(0, col), current.slice(col));
        onChange(lines.join("\n"));
        setPendingCaret({ line: line + 1, col: 0 });
      },
      [value, onChange],
    );

    // Backspace at column 0: merge this line into the previous one.
    const handleJoinLines = useCallback(
      (line: number) => {
        const lines = value.split("\n");
        const merged = lines[line - 2] + lines[line - 1];
        lines.splice(line - 2, 2, merged);
        onChange(lines.join("\n"));
        setPendingCaret({ line: line - 1, col: merged.length });
      },
      [value, onChange],
    );

    useImperativeHandle(
      ref,
      () => ({
        insertText(text: string) {
          const focused = focusedLineRef.current;
          const ta =
            focused != null ? textareaRefs.current.get(focused) : undefined;
          if (!ta || focused == null) {
            // No focused line — append at the end of the document.
            onChange(value + text);
            const parts = value.split("\n");
            const lastLine = Math.max(parts.length, 1);
            setPendingCaret({ line: lastLine, col: parts[lastLine - 1].length });
            return;
          }
          const start = ta.selectionStart;
          const end = ta.selectionEnd;
          const lines = value.split("\n");
          const line = lines[focused - 1];
          lines[focused - 1] = line.slice(0, start) + text + line.slice(end);
          onChange(lines.join("\n"));
          setPendingCaret({ line: focused, col: start + text.length });
        },
      }),
      [value, onChange],
    );

    return (
      <div
        data-testid="live-diff-editor"
        className="mx-auto flex min-h-[24vh] max-h-[70vh] w-full max-w-7xl flex-col overflow-hidden rounded-lg border border-edge bg-surface-raised"
      >
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
          {/* Header row — same grid template as the diff rows, so titles sit
              exactly above their content columns. Sticky so it stays
              visible while the diff scrolls. The gutter cells are plain
              empty backgrounds (no bottom border), and the divider column
              continues the vertical line from the header into the rows. */}
          <div
            data-testid="diff-headers"
            className={`sticky top-0 z-10 grid text-xs ${GRID_TEMPLATE}`}
          >
            <div aria-hidden="true" className="min-w-12 bg-diff-gutter" />
            <div
              data-testid="diff-header-a"
              className="min-w-0 flex items-center gap-1.5 overflow-hidden whitespace-nowrap border-b border-edge bg-surface-raised px-3 py-1.5 text-muted"
            >
              <LockIcon className="h-3.5 w-3.5 shrink-0" />
              <span className="min-w-0 overflow-hidden text-ellipsis">
                Original · solo lectura
              </span>
            </div>
            <div aria-hidden="true" className="bg-edge" />
            <div
              data-testid="diff-header-b"
              className="min-w-0 flex items-center gap-1.5 overflow-hidden whitespace-nowrap border-b border-edge bg-diff-gutter px-3 py-1.5 text-primary"
            >
              <PencilIcon className="h-3.5 w-3.5 shrink-0 text-action" />
              <span className="min-w-0 overflow-hidden text-ellipsis">
                Editado · hacé clic y escribí
              </span>
            </div>
            <div aria-hidden="true" className="min-w-12 bg-surface-raised" />
          </div>

          {rows.length === 0 ? (
            <div className="px-4 py-8 text-center text-small text-muted">
              Sin diferencias
            </div>
          ) : (
            visibleItems.map((item) =>
              item.kind === "band" ? (
                /* Collapsed unchanged run — one discreet band spanning both
                   panes. Clicking it expands the run back into individual
                   (editable) rows. */
                <button
                  type="button"
                  key={`same-run-${item.start}`}
                  onClick={() => expandRun(item.start)}
                  aria-expanded={false}
                  aria-label={`Mostrar ${item.length} líneas sin cambios`}
                  className={`grid w-full cursor-pointer font-mono text-small text-left ${GRID_TEMPLATE} transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50`}
                >
                  <div className="min-w-12 select-none bg-diff-gutter px-2 py-0.5 text-right text-muted" />
                  <div className="min-w-0 whitespace-pre-wrap overflow-wrap-anywhere border-l-2 border-transparent px-3 py-1 text-muted">
                    ··· {item.length} líneas sin cambios ···
                  </div>
                  <div aria-hidden="true" className="bg-edge" />
                  <div className="min-w-0 whitespace-pre-wrap overflow-wrap-anywhere border-l-2 border-transparent px-3 py-1 text-muted">
                    ··· {item.length} líneas sin cambios ···
                  </div>
                  <div className="min-w-12 select-none bg-surface-raised px-2 py-0.5 text-right text-muted" />
                </button>
              ) : (
                <div
                  key={item.index}
                  className={`grid font-mono text-small ${GRID_TEMPLATE}`}
                >
                  {/* Left gutter — line number only when the left side has a line */}
                  <div className="min-w-12 select-none bg-diff-gutter px-2 py-0.5 text-right text-muted">
                    {item.row.leftNumber ?? ""}
                  </div>
                  {/* Left content — read-only */}
                  <div
                    className={`min-h-[1.6rem] min-w-0 whitespace-pre-wrap overflow-wrap-anywhere border-l-2 px-3 py-0.5 text-primary ${
                      item.row.status === "removed" || item.row.status === "changed"
                        ? "border-status-error bg-status-error/30"
                        : item.row.status === "added"
                          ? "border-status-success/10 bg-status-success/10"
                          : "border-transparent"
                    }`}
                  >
                    {item.row.left}
                  </div>
                  {/* Divider — dedicated 1px column, contiguous across header and rows */}
                  <div aria-hidden="true" className="bg-edge" />
                  {/* Right content — editable textarea (the writing surface) */}
                  {item.row.right !== null && item.row.rightNumber !== null ? (
                    <EditableCell
                      text={item.row.right}
                      lineNumber={item.row.rightNumber}
                      isAdded={item.row.status === "added" || item.row.status === "changed"}
                      pendingCaret={pendingCaret}
                      onClearPendingCaret={clearPendingCaret}
                      register={registerTextarea}
                      onCellFocus={handleCellFocus}
                      onLineChange={handleLineChange}
                      onSplitLine={handleSplitLine}
                      onJoinLines={handleJoinLines}
                    />
                  ) : (
                    <div
                      className={`min-h-[1.6rem] whitespace-pre-wrap overflow-wrap-anywhere border-l-2 px-3 py-0.5 text-primary ${
                        item.row.status === "removed"
                          ? "border-status-error/10 bg-status-error/10"
                          : "border-transparent"
                      }`}
                    />
                  )}
                  {/* Right gutter — line number only when the right side has a line */}
                  <div className="min-w-12 select-none bg-surface-raised px-2 py-0.5 text-right text-muted">
                    {item.row.rightNumber ?? ""}
                  </div>
                </div>
              ),
            )
          )}
        </div>
      </div>
    );
  },
);

export default LiveDiffEditor;
