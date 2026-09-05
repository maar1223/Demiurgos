/**
 * Shared blob-download helper for the ficha/idea DOCX export wiring.
 *
 * Pattern: createObjectURL → anchor click → revokeObjectURL. The caller
 * fetches the binary (see `exportFichaDocx` / `exportIdeaDocx`) and hands
 * the resulting Blob here — this utility owns only the DOM download step.
 *
 * Scope guard: created for the NEW export code only. Existing inline
 * downloaders (ToolWorkshop, GlobalMethodologyLibrary) are intentionally
 * NOT refactored onto this helper in this change.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}