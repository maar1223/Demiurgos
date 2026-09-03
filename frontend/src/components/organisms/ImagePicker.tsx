import { useEffect, useRef, useState } from "react";
import { useImages, useImageDelete } from "@/hooks/useImages";
import { getMediaUrl } from "@/api/wiki";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { Button } from "@/components/atoms/Button";
import { Toast } from "@/components/atoms/Toast";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { cn } from "@/lib/utils";

export type Align = "left" | "right" | "center" | null;
export type Size = "sm" | "lg" | null;

/**
 * Builds the markdown alignment/size suffix for an image path.
 *
 * - md + auto -> "" (no suffix)
 * - align only -> "#left" | "#right" | "#center"
 * - size only -> "#sm" | "#lg"
 * - combined -> "#left-sm" | "#right-lg" | "#center-sm" | ...
 */
export function buildImageSuffix(align: Align, size: Size): string {
  let suffix = "";
  if (align) suffix += `#${align}`;
  if (size === "sm") suffix += align ? "-sm" : "#sm";
  if (size === "lg") suffix += align ? "-lg" : "#lg";
  return suffix;
}

interface ImagePickerProps {
  mundo: string;
  onSelect: (path: string) => void;
  onClose: () => void;
  /**
   * Cover-selection mode ("Establecer portada…"): hides the alignment/size
   * dropdowns and emits the BARE path (no `#align-size` suffix), so the
   * value written to `portada:` is a clean mundo-relative media path.
   */
  rawMode?: boolean;
}

/**
 * Modal dialog that overlays the editor to pick an image from the gallery.
 *
 * Flow: select an image first, then configure alignment/size via dropdowns,
 * then confirm with Aceptar (emits `onSelect`) or dismiss with Cancelar.
 * Click outside, the close button, or Escape dismisses the modal.
 *
 * Deleting: the SELECTED thumbnail shows a trash button; clicking it opens a
 * ConfirmDialog and confirming sends the image + thumbnail to the world's
 * papelera (`useImageDelete.remove`), then refreshes the grid via SWR mutate.
 *
 * In `rawMode` the dropdowns are hidden and Aceptar emits the bare path —
 * used by the "Set cover…" card action (S11/S32).
 */
export function ImagePicker({
  mundo,
  onSelect,
  onClose,
  rawMode = false,
}: ImagePickerProps) {
  const { images, total, isLoading, error, mutate } = useImages(mundo);
  const { remove } = useImageDelete(mundo);
  const overlayRef = useRef<HTMLDivElement>(null);
  const deleteTimerRef = useRef<number | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedAlign, setSelectedAlign] = useState<"left" | "right" | "center" | null>(null);
  const [selectedSize, setSelectedSize] = useState<"sm" | "lg" | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deletedMessage, setDeletedMessage] = useState<string | null>(null);

  // Close on Escape key (ignored while the delete confirmation is open —
  // the dialog handles Escape itself, so it closes before the picker).
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !deleteTarget) onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose, deleteTarget]);

  // Clear the success-toast timer on unmount so it never fires on a
  // stale component between tests.
  useEffect(() => {
    return () => {
      if (deleteTimerRef.current) window.clearTimeout(deleteTimerRef.current);
    };
  }, []);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose();
  };

  const handleAccept = () => {
    if (!selectedPath) return;
    // rawMode emits the bare path — no alignment/size suffix (cover value).
    if (rawMode) {
      onSelect(selectedPath);
      return;
    }
    onSelect(selectedPath + buildImageSuffix(selectedAlign, selectedSize));
  };

  const openDeleteDialog = (path: string) => {
    setDeleteTarget(path);
    setDeleteError(null);
  };

  const closeDeleteDialog = () => {
    setDeleteTarget(null);
    setDeleteError(null);
  };

  const showDeleteSuccess = () => {
    setDeletedMessage("Imagen eliminada");
    if (deleteTimerRef.current) window.clearTimeout(deleteTimerRef.current);
    deleteTimerRef.current = window.setTimeout(
      () => setDeletedMessage(null),
      2500,
    );
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await remove(deleteTarget);
      closeDeleteDialog();
      // Clear the stale selection — the deleted image is gone from the grid.
      setSelectedPath(null);
      showDeleteSuccess();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "No se pudo eliminar la imagen.";
      setDeleteError(message);
    } finally {
      setIsDeleting(false);
    }
  };

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const selectClasses =
    "rounded-md border border-edge bg-surface-raised px-2 py-1.5 text-small text-primary " +
    "transition-colors focus:border-action focus:outline-none focus:ring-2 focus:ring-action/50";

  return (
    <>
      <div
        ref={overlayRef}
        className="fixed inset-0 z-50 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
        onClick={handleOverlayClick}
      >
        <div
          className="mx-4 flex max-h-[80vh] w-full max-w-3xl flex-col rounded-xl border border-edge bg-surface-raised shadow-2xl"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="image-picker-title"
        >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <h2
            id="image-picker-title"
            className="font-heading text-h4 text-primary"
          >
            Seleccionar imagen
            {total > 0 && (
              <span className="ml-2 text-small text-muted font-normal">
                ({total} {total === 1 ? "imagen" : "imágenes"})
              </span>
            )}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-icon-muted hover:text-primary hover:bg-surface-hover transition-colors"
            aria-label="Cerrar"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Content — scrollable region: image grid + hint text only */}
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          {isLoading && (
            <div className="flex items-center justify-center py-16">
              <Spinner size="lg" />
            </div>
          )}

          {error && !isLoading && (
            <ErrorBanner
              message={error.message || "Error al cargar imágenes."}
              onRetry={() => mutate()}
            />
          )}

          {!isLoading && !error && images.length === 0 && (
            <EmptyState
              icon="empty"
              message="No hay imágenes en este mundo."
            />
          )}

          {!isLoading && !error && images.length > 0 && (
            <div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {images.map((img) => {
                  const isSelected = img.path === selectedPath;
                  return (
                    <div key={img.path} className="relative w-full">
                      <button
                        type="button"
                        aria-pressed={isSelected}
                        onClick={() => setSelectedPath(img.path)}
                        className={cn(
                          "group flex w-full flex-col overflow-hidden rounded-lg border bg-surface-raised transition-all hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50",
                          isSelected
                            ? "border-action ring-2 ring-action/50"
                            : "border-edge hover:border-action/50",
                        )}
                      >
                        {/* Thumbnail */}
                        <div className="aspect-[4/3] w-full overflow-hidden bg-surface">
                          <img
                            src={getMediaUrl(
                              mundo,
                              img.thumbnail_path ?? img.path,
                            )}
                            alt={img.name}
                            className="h-full w-full object-cover transition-transform group-hover:scale-105"
                            loading="lazy"
                          />
                        </div>
                        {/* Info */}
                        <div className="px-2 py-2 text-left">
                          <p className="truncate text-small text-primary">
                            {img.name}
                          </p>
                          <p className="text-xs text-muted">
                            {formatSize(img.size_bytes)}
                          </p>
                        </div>
                      </button>
                      {/* Delete affordance — only on the selected image, so a
                          first click never destroys anything by accident. */}
                      {isSelected && (
                        <button
                          type="button"
                          aria-label={`Eliminar ${img.name}`}
                          title={`Eliminar ${img.name}`}
                          onClick={() => openDeleteDialog(img.path)}
                          className="absolute right-2 top-2 rounded-md bg-surface/80 p-1.5 text-icon-muted shadow-md backdrop-blur-sm transition-colors hover:bg-status-error hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
                        >
                          <Icon name="trash" size={16} />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>

              <p className="mt-4 text-small text-muted">
                {rawMode
                  ? "Selecciona la imagen que será la portada."
                  : "Selecciona una imagen y configura su posición."}
              </p>
            </div>
          )}
        </div>

        {/* Footer — fixed bar below the scroll region, always visible */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-edge px-6 py-4">
          {!rawMode && (
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-small text-muted">
                Alineación:
                <select
                  value={selectedAlign ?? ""}
                  onChange={(e) =>
                    setSelectedAlign(
                      e.target.value === ""
                        ? null
                        : (e.target.value as "left" | "right" | "center"),
                    )
                  }
                  className={selectClasses}
                >
                  <option value="">Automática</option>
                  <option value="left">← Izquierda</option>
                  <option value="right">→ Derecha</option>
                  <option value="center">↔ Centro</option>
                </select>
              </label>
              <label className="flex items-center gap-2 text-small text-muted">
                Tamaño:
                <select
                  value={selectedSize ?? ""}
                  onChange={(e) =>
                    setSelectedSize(
                      e.target.value === ""
                        ? null
                        : (e.target.value as "sm" | "lg"),
                    )
                  }
                  className={selectClasses}
                >
                  <option value="">Mediana</option>
                  <option value="sm">Chica</option>
                  <option value="lg">Grande</option>
                </select>
              </label>
            </div>
          )}

          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={!selectedPath}
              onClick={handleAccept}
            >
              Aceptar
            </Button>
          </div>
        </div>
      </div>
    </div>

    {/* Delete confirmation (S12 pattern) — cancel aborts, confirm moves
        the image + thumbnail to the world's papelera via the API. */}
      {deleteTarget && (
        <ConfirmDialog
          title="Eliminar"
          message={`¿Eliminar "${deleteTarget.split("/").pop()}"? Se moverá a la papelera.`}
          confirmLabel="Eliminar"
          isBusy={isDeleting}
          error={deleteError}
          onConfirm={handleConfirmDelete}
          onClose={closeDeleteDialog}
        />
      )}

      {deletedMessage && <Toast message={deletedMessage} kind="success" />}
    </>
  );
}