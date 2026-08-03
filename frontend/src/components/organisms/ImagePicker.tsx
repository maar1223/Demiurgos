import { useEffect, useRef, useState } from "react";
import { useImages } from "@/hooks/useImages";
import { getMediaUrl } from "@/api/wiki";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { Button } from "@/components/atoms/Button";
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
}

/**
 * Modal dialog that overlays the editor to pick an image from the gallery.
 *
 * Flow: select an image first, then configure alignment/size via dropdowns,
 * then confirm with Aceptar (emits `onSelect`) or dismiss with Cancelar.
 * Click outside, the close button, or Escape dismisses the modal.
 */
export function ImagePicker({ mundo, onSelect, onClose }: ImagePickerProps) {
  const { images, total, isLoading, error, mutate } = useImages(mundo);
  const overlayRef = useRef<HTMLDivElement>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedAlign, setSelectedAlign] = useState<"left" | "right" | "center" | null>(null);
  const [selectedSize, setSelectedSize] = useState<"sm" | "lg" | null>(null);

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

  const handleAccept = () => {
    if (!selectedPath) return;
    onSelect(selectedPath + buildImageSuffix(selectedAlign, selectedSize));
  };

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const selectClasses =
    "rounded-md border border-filio bg-piedra px-2 py-1.5 text-small text-pergamino " +
    "transition-colors focus:border-llamita focus:outline-none focus:ring-2 focus:ring-llamita/50";

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-cripta/80 backdrop-blur-sm"
      onClick={handleOverlayClick}
    >
      <div
        className="mx-4 flex max-h-[80vh] w-full max-w-3xl flex-col rounded-xl border border-filio bg-madero shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="image-picker-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-filio px-6 py-4">
          <h2
            id="image-picker-title"
            className="font-heading text-h4 text-pergamino"
          >
            Seleccionar imagen
            {total > 0 && (
              <span className="ml-2 text-small text-tinta-desvaida font-normal">
                ({total} {total === 1 ? "imagen" : "imágenes"})
              </span>
            )}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-plata hover:text-pergamino hover:bg-piedra transition-colors"
            aria-label="Cerrar"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Content */}
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
                    <button
                      key={img.path}
                      type="button"
                      aria-pressed={isSelected}
                      onClick={() => setSelectedPath(img.path)}
                      className={cn(
                        "group flex flex-col overflow-hidden rounded-lg border bg-piedra transition-all hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50",
                        isSelected
                          ? "border-llamita ring-2 ring-llamita/50"
                          : "border-filio hover:border-llamita/50",
                      )}
                    >
                      {/* Thumbnail */}
                      <div className="aspect-[4/3] w-full overflow-hidden bg-cripta">
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
                        <p className="truncate text-small text-pergamino">
                          {img.name}
                        </p>
                        <p className="text-xs text-tinta-desvaida">
                          {formatSize(img.size_bytes)}
                        </p>
                      </div>
                    </button>
                  );
                })}
              </div>

              <p className="mt-4 text-small text-tinta-desvaida">
                Selecciona una imagen y configura su posición.
              </p>

              {/* Footer: alignment/size dropdowns + actions */}
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-filio pt-4">
                <div className="flex flex-wrap items-center gap-3">
                  <label className="flex items-center gap-2 text-small text-tinta-desvaida">
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
                  <label className="flex items-center gap-2 text-small text-tinta-desvaida">
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
          )}
        </div>
      </div>
    </div>
  );
}
