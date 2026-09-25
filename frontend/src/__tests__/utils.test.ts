import { beforeEach, describe, it, expect } from "vitest";
import { cn, encodePathSegment, decodePathSegment, getErrorMessage } from "@/lib/utils";
import { CATALOGUE, type MessageKey } from "@/i18n/messages";

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

const es = (key: MessageKey) => CATALOGUE.es[key];

describe("getErrorMessage", () => {
  beforeEach(() => {
    // No cached locale → the es default (deterministic assertions).
    window.localStorage.clear();
  });

  it("returns network copy for status 0", () => {
    expect(getErrorMessage(0)).toBe(es("error.network.unreachable"));
  });

  it("resolves a known backend code through the catalogue", () => {
    expect(getErrorMessage(404, "Import job not found", "import.job_not_found")).toBe(
      es("error.import.job_not_found"),
    );
  });

  it("fills structured params into the localized template", () => {
    expect(
      getErrorMessage(400, "Invalid section", "import.invalid_section", {
        relative: "lore/a.md",
        section: "personajes",
      }),
    ).toBe("Sección inválida para lore/a.md: personajes.");
  });

  it("falls back to status-based copy when no code is present", () => {
    expect(getErrorMessage(404)).toBe(es("error.status.404"));
    expect(getErrorMessage(400)).toBe(es("error.status.400"));
    expect(getErrorMessage(409)).toBe(es("error.status.409"));
  });

  it("never leaks the raw backend detail (ERR-REQ-4)", () => {
    // The pre-fix behavior returned `detail` verbatim for 404s; now the raw
    // backend string must never surface as user-facing copy.
    expect(getErrorMessage(404, "Custom detail")).toBe(es("error.status.404"));
    expect(getErrorMessage(404, "Custom detail")).not.toContain("Custom detail");
  });

  it("returns the generic copy for unknown statuses", () => {
    expect(getErrorMessage(999)).toBe(es("error.unknown"));
  });
});