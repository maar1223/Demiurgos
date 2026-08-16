/**
 * Merges class names, filtering out falsy values.
 * A lightweight alternative to clsx + tailwind-merge.
 */
export function cn(...inputs: (string | false | null | undefined)[]): string {
  return inputs.filter(Boolean).join(" ");
}

/**
 * Encodes a single path segment for use in URLs.
 * Preserves forward slashes if the segment contains them.
 */
export function encodePathSegment(segment: string): string {
  return segment
    .split("/")
    .map((s) => encodeURIComponent(s))
    .join("/");
}

/**
 * Decodes a single path segment from URL-encoded form.
 */
export function decodePathSegment(segment: string): string {
  return segment
    .split("/")
    .map((s) => decodeURIComponent(s))
    .join("/");
}

/**
 * Maps backend HTTP error codes to user-facing Spanish messages.
 */
export function getErrorMessage(status: number, detail?: string): string {
  if (status === 0) {
    return "No se pudo conectar al servidor. Verificá que esté corriendo.";
  }

  if (detail) {
    switch (detail) {
      case "Path traversal detectado":
        return "Ruta inválida: acceso fuera del directorio permitido";
      case "Sección inválida":
        return "Sección no encontrada. Secciones válidas: Lore, Personajes, Sagas";
      case "Archivo no encontrado":
        return "Archivo no encontrado";
      case "El archivo ya existe":
        return "El archivo ya existe";
      default:
        break;
    }
  }

  switch (status) {
    case 400:
      return "Solicitud inválida";
    case 404:
      return detail ?? "Recurso no encontrado";
    case 409:
      return "El archivo ya existe";
    case 422:
      return "Error de codificación: el archivo contiene bytes inválidos UTF-8";
    case 500:
      return "Error interno del servidor. Revisá los logs del backend.";
    default:
      return "Error inesperado";
  }
}
