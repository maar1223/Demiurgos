import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { Button } from "@/components/atoms/Button";
import { DropZone } from "@/components/atoms/DropZone";

interface ImportImageModalProps {
  onFile: (file: File) => void;
  isUploading: boolean;
  uploadError: Error | null;
  onClose: () => void;
}

/**
 * Modal that overlays the editor to upload an image to the world's gallery.
 *
 * Wraps the DropZone with the upload lifecycle: idle (drag & drop) →
 * uploading (spinner) → success (check + file name + Cerrar) or an error
 * banner. Dismissed via the close button, Escape, or clicking the overlay —
 * same pattern as ImagePicker. The upload logic itself lives in the parent
 * (`handleFileDrop` in WikiEditor); this modal only surfaces its state.
 */
export function ImportImageModal({
  onFile,
  isUploading,
  uploadError,
  onClose,
}: ImportImageModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  // Name of the file chosen in the current modal session — gates the
  // success/error banners so a stale uploadError from a previous session
  // never shows before the user actually drops a file.
  const [fileName, setFileName] = useState<string | null>(null);
  // Bumps on every drop to remount the DropZone clean (empty preview)
  const [attempt, setAttempt] = useState(0);

  // Close on Escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose();
  };

  const handleFile = (file: File) => {
    setFileName(file.name);
    setAttempt((n) => n + 1);
    onFile(file);
  };

  const succeeded = fileName !== null && !isUploading && !uploadError;
  const failed = fileName !== null && !isUploading && uploadError !== null;

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-cripta/80 backdrop-blur-sm"
      onClick={handleOverlayClick}
    >
      <div
        className="mx-4 flex w-full max-w-lg flex-col rounded-xl border border-filio bg-madero shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-image-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-filio px-6 py-4">
          <h2
            id="import-image-title"
            className="font-heading text-h4 text-pergamino"
          >
            Importar Imagen
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

        {/* Content */}
        <div className="flex flex-col gap-4 p-6">
          <DropZone key={attempt} onFile={handleFile} />

          {isUploading && (
            <div className="flex items-center gap-3 rounded-lg border border-llamita/40 bg-llamita/10 px-4 py-3 text-small text-pergamino">
              <Spinner size="sm" />
              <span>
                Subiendo imagen…
                {fileName && (
                  <span className="text-tinta-desvaida"> ({fileName})</span>
                )}
              </span>
            </div>
          )}

          {succeeded && (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-musgo/40 bg-musgo/10 px-4 py-3">
              <div className="flex min-w-0 items-center gap-3 text-small text-musgo">
                <Icon name="check" size={18} />
                <span>
                  Imagen subida ✓
                  {fileName && (
                    <span className="text-pergamino"> {fileName}</span>
                  )}
                </span>
              </div>
              <Button variant="primary" size="sm" onClick={onClose}>
                Cerrar
              </Button>
            </div>
          )}

          {failed && (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-sangre/50 bg-sangre/10 px-4 py-3">
              <div className="min-w-0 text-small text-sangre">
                <span>Error al subir imagen: {uploadError.message}</span>
                {fileName && (
                  <span className="block text-xs text-tinta-desvaida">
                    {fileName}
                  </span>
                )}
              </div>
              <Button variant="secondary" size="sm" onClick={onClose}>
                Cerrar
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
