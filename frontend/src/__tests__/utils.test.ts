import { describe, it, expect } from "vitest";
import { cn, encodePathSegment, decodePathSegment, getErrorMessage } from "@/lib/utils";

describe("cn", () => {
  it("joins class names", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("filters falsy values", () => {
    expect(cn("a", false, null, undefined, "b")).toBe("a b");
  });

  it("returns empty string for no truthy inputs", () => {
    expect(cn(false, null)).toBe("");
  });
});

describe("encodePathSegment", () => {
  it("encodes spaces", () => {
    expect(encodePathSegment("mi archivo.md")).toBe("mi%20archivo.md");
  });

  it("encodes hash characters", () => {
    expect(encodePathSegment("#notas.md")).toBe("%23notas.md");
  });

  it("encodes question marks", () => {
    expect(encodePathSegment("¿qué?.md")).toBe("%C2%BFqu%C3%A9%3F.md");
  });

  it("preserves slashes and returns segments encoded", () => {
    expect(encodePathSegment("cap1/historia.md")).toBe("cap1/historia.md");
  });
});

describe("decodePathSegment", () => {
  it("decodes spaces", () => {
    expect(decodePathSegment("mi%20archivo.md")).toBe("mi archivo.md");
  });

  it("decodes special characters", () => {
    expect(decodePathSegment("%23notas.md")).toBe("#notas.md");
  });

  it("preserves slashes", () => {
    expect(decodePathSegment("cap1/historia.md")).toBe("cap1/historia.md");
  });
});

describe("getErrorMessage", () => {
  it("returns network error for status 0", () => {
    const msg = getErrorMessage(0);
    expect(msg).toContain("No se pudo conectar");
  });

  it("returns path traversal message for 400 with matching detail", () => {
    expect(getErrorMessage(400, "Path traversal detectado")).toBe(
      "Ruta inválida: acceso fuera del directorio permitido",
    );
  });

  it("returns section not found for 404 with matching detail", () => {
    expect(getErrorMessage(404, "Sección inválida")).toBe(
      "Sección no encontrada. Secciones válidas: Lore, Personajes, Sagas",
    );
  });

  it("returns file not found for 404 with detail", () => {
    expect(getErrorMessage(404, "Archivo no encontrado")).toBe(
      "Archivo no encontrado",
    );
  });

  it("returns file exists for 409 with matching detail", () => {
    expect(getErrorMessage(409, "El archivo ya existe")).toBe(
      "El archivo ya existe",
    );
  });

  it("returns encoding error for 422", () => {
    const msg = getErrorMessage(422);
    expect(msg).toContain("Error de codificación");
  });

  it("returns server error for 500", () => {
    const msg = getErrorMessage(500);
    expect(msg).toContain("Error interno del servidor");
  });

  it("returns default for unknown status", () => {
    expect(getErrorMessage(999)).toBe("Error inesperado");
  });

  it("returns detail when available for 404", () => {
    expect(getErrorMessage(404, "Custom detail")).toBe("Custom detail");
  });
});
