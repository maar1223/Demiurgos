import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Icon } from "@/components/atoms/Icon";

interface DropZoneProps {
  onFile: (file: File) => void;
}

/**
 * Visual drag-and-drop area for image files.
 *
 * Shows "Arrastrá una imagen o hacé clic para seleccionar" when empty.
 * Accents border on drag-over. Accepts only image files (accept="image/*").
 * Shows file name preview after selection.
 *
 * Emits `onFile(file: File)` callback when a file is selected/dropped.
 */
export function DropZone({ onFile }: DropZoneProps) {
  const [preview, setPreview] = useState<string | null>(null);

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      if (acceptedFiles.length === 0) return;
      const file = acceptedFiles[0];
      setPreview(file.name);
      onFile(file);
    },
    [onFile],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "image/*": [] },
    maxFiles: 1,
    multiple: false,
  });

  return (
    <div
      {...getRootProps()}
      className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
        isDragActive
          ? "border-llamita bg-llamita/5"
          : "border-filio bg-madero hover:border-llamita/50 hover:bg-piedra"
      }`}
      role="button"
      tabIndex={0}
      aria-label="Arrastrá una imagen o hacé clic para seleccionar"
    >
      <input {...getInputProps()} />

      {preview ? (
        <div className="flex flex-col items-center gap-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-musgo/20 text-musgo">
            <Icon name="check" size={24} />
          </div>
          <p className="text-body text-pergamino">{preview}</p>
          <p className="text-small text-tinta-desvaida">
            Arrastrá otra imagen o hacé clic para cambiar
          </p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3">
          <div
            className={`flex h-14 w-14 items-center justify-center rounded-full transition-colors ${
              isDragActive
                ? "bg-llamita/20 text-llamita"
                : "bg-filio/50 text-plata"
            }`}
          >
            <Icon name="upload" size={28} />
          </div>
          <div>
            <p className="text-body text-pergamino">
              Arrastrá una imagen o hacé clic para seleccionar
            </p>
            <p className="mt-1 text-small text-tinta-desvaida">
              JPG, PNG, GIF, WebP — máximo 10 MB
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
