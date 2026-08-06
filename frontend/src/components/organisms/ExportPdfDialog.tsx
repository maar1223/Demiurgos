import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { splitFrontmatter } from "@/lib/frontmatter";
import { MarkdownBody } from "@/components/organisms/MarkdownViewer";

interface ExportPdfDialogProps {
  open: boolean;
  onClose: () => void;
  /** The full file content (frontmatter included) — split here before render. */
  content: string | null;
  /** e.g. "cap1.md" — the .md extension is stripped for display + the title. */
  fileName: string | null;
  /** Current world name — passed through so image paths resolve to the media API. */
  mundo: string;
}

/**
 * "Exportar Ficha a PDF" dialog (⋯ menu flow): exports the ficha through the
 * browser's native print dialog using the light print presentation.
 *
 * Zero-dependency design: "Exportar" renders the ficha body (frontmatter
 * stripped, via the shared `MarkdownBody`) into a hidden `#print-root`
 * portal on `document.body`, sets `document.title` to the ficha basename so
 * the browser's default "Save as PDF" filename is sensible, and calls
 * `window.print()`. An `@media print` block in globals.css hides the whole
 * app (`#root`) and shows only the print root. The title is restored when
 * printing finishes — via `window.onafterprint` when the event is supported
 * (all modern browsers; jsdom exposes the handler as null so the tests
 * exercise this path), else a short timeout fallback.
 *
 * Overlay pattern mirrors MoveToSectionDialog / ConfirmDialog (fixed inset-0
 * z-50, role dialog, aria-modal, Escape/overlay click).
 */
export function ExportPdfDialog({
  open,
  onClose,
  content,
  fileName,
  mundo,
}: ExportPdfDialogProps) {
  const [printing, setPrinting] = useState(false);

  // Latest onClose in a ref — the print effect runs once per `printing`
  // transition, so a re-created parent callback never re-fires window.print.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  const fileNameWithoutExt = fileName?.replace(/\.md$/i, "") ?? "";
  const { body } = splitFrontmatter(content ?? "");

  // Close on Escape key
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  // Trigger the browser print flow once the print root is mounted (the
  // portal renders in the same commit as `printing` flipping true, so the
  // print dialog sees the ficha content). Effect depends ONLY on `printing`
  // — stable props are captured from this render; onClose goes through the
  // ref — so StrictMode update semantics can never call window.print twice.
  useEffect(() => {
    if (!printing) return;
    const originalTitle = document.title;
    document.title = `${fileNameWithoutExt} — ${mundo}`;

    const restore = () => {
      document.title = originalTitle;
      setPrinting(false);
      onCloseRef.current();
    };

    let timer: ReturnType<typeof setTimeout> | undefined;
    if (typeof window.onafterprint !== "undefined") {
      window.onafterprint = restore;
    } else {
      timer = setTimeout(restore, 500);
    }

    window.print();

    return () => {
      if (timer !== undefined) clearTimeout(timer);
      if (window.onafterprint === restore) window.onafterprint = null;
    };
  }, [printing]);

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-cripta/80 backdrop-blur-sm"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        <div
          className="mx-4 w-full max-w-md rounded-xl border border-filio bg-madero shadow-2xl"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="export-pdf-dialog-title"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-filio px-6 py-4">
            <h2
              id="export-pdf-dialog-title"
              className="font-heading text-h4 text-pergamino"
            >
              Exportar Ficha a PDF
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1 text-plata transition-colors hover:bg-piedra hover:text-pergamino"
              aria-label="Cerrar"
            >
              <Icon name="close" size={20} />
            </button>
          </div>

          {/* Body */}
          <div className="px-6 py-4">
            <p className="text-body text-pergamino">
              Se exportará la ficha{" "}
              <span className="font-medium text-llamita">
                {fileNameWithoutExt}
              </span>{" "}
              a PDF desde el diálogo de impresión del navegador.
            </p>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 border-t border-filio px-6 py-4">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => setPrinting(true)}
            >
              Exportar
            </Button>
          </div>
        </div>
      </div>

      {/* Print container — portal to document.body, OUTSIDE #root so the
          print CSS can hide the entire app and show only the ficha. Hidden
          on screen (`hidden`), forced to display by the @media print block.
          Always renders the light print presentation (ink on paper). */}
      {printing &&
        createPortal(
          <div
            id="print-root"
            data-testid="print-root"
            className="hidden bg-white text-neutral-900"
          >
            <MarkdownBody content={body} mundo={mundo} />
          </div>,
          document.body,
        )}
    </>
  );
}
