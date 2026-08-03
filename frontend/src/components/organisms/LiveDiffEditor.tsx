import { forwardRef, useImperativeHandle, useMemo } from "react";
import { diffLines, splitLines } from "@/lib/diff";

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
   * Insert text at the current cursor position.
   *
   * The diff view is read-only — editing happens in the textarea of
   * WikiEditor — so this is intentionally a no-op. It stays in the handle
   * to keep the external API stable (WikiEditor calls it for wikilink
   * insertion while the preview is open).
   */
  insertText(_text: string): void;
}

interface LiveDiffEditorProps {
  /** Original (read-only) content — left pane. */
  original: string;
  /** Edited content — right pane. */
  value: string;
  /** Kept for API compatibility; the diff view is read-only and never calls it. */
  onChange: (value: string) => void;
  /** Kept for API compatibility; the diff view is always read-only. */
  readOnly?: boolean;
}

/**
 * Live side-by-side diff rendered as paired grid rows.
 *
 * Each document line is ONE grid row: `[gutterA | contentA | divider |
 * contentB | gutterB]`. Both cells live in the same grid row, so the row
 * auto-grows to the height of the tallest cell and the NEXT row starts at
 * the same Y on both sides — alignment is a CSS guarantee, not JS math.
 * Text wraps INSIDE each cell (`pre-wrap` + `overflow-wrap: anywhere`), so
 * the full document is visible with no horizontal scroll.
 *
 * The diff is computed client-side (LCS) in a useMemo over
 * `[original, value]`: typing in the WikiEditor textarea updates `value`,
 * which recomputes the diff — live updates come for free.
 */
export const LiveDiffEditor = forwardRef<LiveDiffEditorHandle, LiveDiffEditorProps>(
  function LiveDiffEditor({ original, value }, ref) {
    const rows = useMemo(
      () => diffLines(splitLines(original), splitLines(value)),
      [original, value],
    );

    useImperativeHandle(ref, () => ({
      insertText() {
        // No-op: the diff view is read-only by design.
      },
    }));

    return (
      <div
        data-testid="live-diff-editor"
        className="mx-auto flex h-[70vh] w-full max-w-7xl flex-col overflow-hidden rounded-lg border border-filio bg-madero"
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
            <div aria-hidden="true" className="bg-lecho" />
            <div
              data-testid="diff-header-a"
              className="flex items-center gap-1.5 overflow-hidden whitespace-nowrap border-b border-filio bg-piedra px-3 py-1.5 text-tinta-desvaida"
            >
              <LockIcon className="h-3.5 w-3.5 shrink-0" />
              <span className="min-w-0 overflow-hidden text-ellipsis">
                Original · solo lectura
              </span>
            </div>
            <div aria-hidden="true" className="bg-filio" />
            <div
              data-testid="diff-header-b"
              className="flex items-center gap-1.5 overflow-hidden whitespace-nowrap border-b border-filio bg-lecho px-3 py-1.5 text-pergamino"
            >
              <PencilIcon className="h-3.5 w-3.5 shrink-0 text-llamita" />
              <span className="min-w-0 overflow-hidden text-ellipsis">
                Editado
              </span>
            </div>
            <div aria-hidden="true" className="bg-piedra" />
          </div>

          {rows.length === 0 ? (
            <div className="px-4 py-8 text-center text-small text-tinta-desvaida">
              Sin diferencias
            </div>
          ) : (
            rows.map((row, index) => (
              <div
                key={index}
                className={`grid font-mono text-small ${GRID_TEMPLATE}`}
              >
                {/* Left gutter — line number only when the left side has a line */}
                <div className="select-none bg-lecho px-2 py-0.5 text-right text-tinta-desvaida">
                  {row.leftNumber ?? ""}
                </div>
                {/* Left content */}
                <div
                  className={`min-h-[1.6rem] whitespace-pre-wrap overflow-wrap-anywhere border-l-2 px-3 py-0.5 text-pergamino ${
                    row.status === "removed"
                      ? "border-sangre bg-sangre/30"
                      : "border-transparent"
                  }`}
                >
                  {row.left}
                </div>
                {/* Divider — dedicated 1px column, contiguous across header and rows */}
                <div aria-hidden="true" className="bg-filio" />
                {/* Right content */}
                <div
                  className={`min-h-[1.6rem] whitespace-pre-wrap overflow-wrap-anywhere border-l-2 px-3 py-0.5 text-pergamino ${
                    row.status === "added"
                      ? "border-musgo bg-musgo/30"
                      : "border-transparent"
                  }`}
                >
                  {row.right}
                </div>
                {/* Right gutter — line number only when the right side has a line */}
                <div className="select-none bg-piedra px-2 py-0.5 text-right text-tinta-desvaida">
                  {row.rightNumber ?? ""}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    );
  },
);

export default LiveDiffEditor;
