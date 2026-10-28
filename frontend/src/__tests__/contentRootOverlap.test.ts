import { describe, expect, it } from "vitest";

import {
  normalizeFolderPath,
  overlapsContentRoot,
} from "@/lib/contentRootOverlap";

/**
 * The picker's pre-check must say the same thing the server refuses, before the
 * request leaves. The server stays the authority; this keeps the 400 from
 * arriving as a surprise on a folder that looks fine.
 */

const ROOT = "/home/autora/Documentos/Demiurgos";

describe("normalizeFolderPath", () => {
  it("collapses separators and a trailing slash", () => {
    expect(normalizeFolderPath("/home/autora/Documentos/Demiurgos/")).toBe(ROOT);
    expect(normalizeFolderPath("  /home//autora/Documentos/Demiurgos  ")).toBe(ROOT);
  });

  it("keeps the filesystem root comparable", () => {
    expect(normalizeFolderPath("/")).toBe("/");
    expect(normalizeFolderPath("C:\\")).toBe("c:/");
  });

  it("folds case only for Windows paths", () => {
    expect(normalizeFolderPath("C:\\Users\\Autora\\Documents")).toBe(
      "c:/users/autora/documents",
    );
    expect(normalizeFolderPath("/home/Autora")).toBe("/home/Autora");
  });

  it("treats a blank path as no path", () => {
    expect(normalizeFolderPath("")).toBe("");
    expect(normalizeFolderPath(null)).toBe("");
    expect(normalizeFolderPath("   ")).toBe("");
  });
});

describe("overlapsContentRoot", () => {
  it("flags the content root itself", () => {
    expect(overlapsContentRoot(ROOT, ROOT)).toBe(true);
    expect(overlapsContentRoot(`${ROOT}/`, ROOT)).toBe(true);
  });

  it("flags a folder inside the content root", () => {
    expect(overlapsContentRoot(`${ROOT}/copias`, ROOT)).toBe(true);
    expect(overlapsContentRoot(`${ROOT}/a/b/c`, ROOT)).toBe(true);
  });

  it("flags a folder that contains the content root", () => {
    expect(overlapsContentRoot("/home/autora/Documentos", ROOT)).toBe(true);
    expect(overlapsContentRoot("/", ROOT)).toBe(true);
  });

  it("does not flag a sibling", () => {
    expect(overlapsContentRoot("/home/autora/Documentos/Copias", ROOT)).toBe(false);
    expect(overlapsContentRoot("/mnt/discos/copias", ROOT)).toBe(false);
  });

  it("does not flag a shared prefix that is not a path boundary", () => {
    expect(overlapsContentRoot("/home/autora/Documentos/DemiurgosViejo", ROOT)).toBe(
      false,
    );
  });

  it("never flags when a side is missing", () => {
    expect(overlapsContentRoot(ROOT, null)).toBe(false);
    expect(overlapsContentRoot("", ROOT)).toBe(false);
  });

  it("compares Windows paths case-insensitively", () => {
    const root = "C:\\Users\\Autora\\Documents\\Demiurgos";
    expect(overlapsContentRoot("c:\\users\\autora\\documents\\demiurgos\\backups", root)).toBe(
      true,
    );
  });
});
