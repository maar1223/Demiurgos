import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import { errorKey, localizeApiError, localizeErrorCode } from "@/i18n/errors";
import { translate, type TFunction } from "@/i18n/messages";

const tEs: TFunction = (key, params) => translate("es", key, params);
const tEn: TFunction = (key, params) => translate("en", key, params);

describe("errorKey", () => {
  it("maps a backend code to its catalogue key", () => {
    expect(errorKey("import.job_not_found")).toBe("error.import.job_not_found");
  });

  it("returns null for codes the catalogue does not define", () => {
    expect(errorKey("unknown.thing")).toBeNull();
    expect(errorKey("")).toBeNull();
  });
});

describe("localizeApiError", () => {
  it("renders a known code in Spanish (ERR-SCN-2.1)", () => {
    const error = new ApiError(404, "Import job not found", "Import job not found", "import.job_not_found");
    expect(localizeApiError(error, tEs)).toBe("El trabajo de importación no existe.");
  });

  it("renders the same code in English (ERR-SCN-2.2)", () => {
    const error = new ApiError(404, "Import job not found", "Import job not found", "import.job_not_found");
    expect(localizeApiError(error, tEn)).toBe("The import job was not found.");
  });

  it("fills structured params into the localized template", () => {
    const error = new ApiError(
      400,
      "Invalid section",
      "Invalid section for lore/a.md: 'personajes'",
      "import.invalid_section",
      { relative: "lore/a.md", section: "personajes" },
    );
    expect(localizeApiError(error, tEs)).toBe(
      "Sección inválida para lore/a.md: personajes.",
    );
    expect(localizeApiError(error, tEn)).toBe(
      "Invalid section for lore/a.md: personajes.",
    );
  });

  it("falls back to a generic localized message for unknown codes (ERR-SCN-4.1)", () => {
    const error = new ApiError(418, "teapot", "I am a teapot", "no.such_code");
    expect(localizeApiError(error, tEs)).toBe("Ocurrió un error inesperado.");
    expect(localizeApiError(error, tEn)).toBe("An unexpected error occurred.");
  });

  it("falls back to status-based copy when no code is present", () => {
    const error = new ApiError(404, "Mundo no encontrado", "Mundo no encontrado");
    expect(localizeApiError(error, tEs)).toBe("Recurso no encontrado.");
    expect(localizeApiError(error, tEn)).toBe("Resource not found.");
  });

  it("never returns the raw backend detail (ERR-REQ-4)", () => {
    const error = new ApiError(404, "Import job not found", "Import job not found");
    const esText = localizeApiError(error, tEs);
    expect(esText).not.toContain("Import job not found");
    const enText = localizeApiError(error, tEn);
    expect(enText).not.toContain("Import job not found");
  });

  it("maps bare transport failures to the network copy", () => {
    const unreachable = new ApiError(0, "network down", undefined, "network.unreachable");
    expect(localizeApiError(unreachable, tEs)).toBe(
      "No se pudo conectar al servidor. Verifica que esté corriendo.",
    );
    const timeout = new ApiError(0, "timed out", undefined, "network.timeout");
    expect(localizeApiError(timeout, tEn)).toBe("The request took too long. Try again.");
  });

  it("follows the language switch because resolution happens at render time", () => {
    const error = new ApiError(409, "Job busy (lease held)", "Job busy (lease held)", "import.job_busy");
    expect(localizeApiError(error, tEs)).toBe(
      "El trabajo de importación está ocupado en este momento.",
    );
    expect(localizeApiError(error, tEn)).toBe("The import job is busy right now.");
  });
});

describe("localizeErrorCode", () => {
  it("resolves a bare code + params without an ApiError", () => {
    expect(localizeErrorCode("import.not_owner", 403, undefined, tEs)).toBe(
      "No eres el propietario de este trabajo de importación.",
    );
    expect(localizeErrorCode(undefined, 500, undefined, tEs)).toBe(
      "Error interno del servidor. Revisa los logs del backend.",
    );
    expect(localizeErrorCode(undefined, 0, undefined, tEs)).toBe(
      "No se pudo conectar al servidor. Verifica que esté corriendo.",
    );
  });
});