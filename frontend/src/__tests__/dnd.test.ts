import { describe, it, expect } from "vitest";
import {
  DND_NODE_MIME,
  canDropToGridBackground,
  canDropToTreeBackground,
  hasDragPayload,
  isFolderDropValid,
  joinPath,
  parentPath,
  readDragPayload,
  resolveDragPayload,
  setDragPayload,
  upLevelTarget,
  type DragPayload,
} from "@/lib/dnd";

const file: DragPayload = { path: "capitulos/notas.md", is_dir: false };
const dir: DragPayload = { path: "capitulos", is_dir: true };

describe("parentPath / joinPath", () => {
  it("computes the parent of a nested path", () => {
    expect(parentPath("capitulos/notas.md")).toBe("capitulos");
    expect(parentPath("notas.md")).toBe("");
  });

  it("joins a dir and a name (name alone at the root)", () => {
    expect(joinPath("capitulos", "notas.md")).toBe("capitulos/notas.md");
    expect(joinPath("", "notas.md")).toBe("notas.md");
  });
});

describe("setDragPayload / readDragPayload", () => {
  it("round-trips the payload through a DataTransfer", () => {
    const dt = new DataTransfer();
    setDragPayload(dt, file);
    expect(readDragPayload(dt)).toEqual(file);
    expect(dt.getData(DND_NODE_MIME)).toBe(JSON.stringify(file));
    expect(dt.getData("text/plain")).toBe(file.path);
  });

  it("returns null for foreign drags (no custom MIME)", () => {
    const dt = new DataTransfer();
    dt.setData("text/plain", "whatever");
    expect(readDragPayload(dt)).toBeNull();
    expect(readDragPayload(null)).toBeNull();
  });
});

describe("hasDragPayload", () => {
  it("is true only when the custom MIME is advertised", () => {
    const ours = new DataTransfer();
    setDragPayload(ours, file);
    expect(hasDragPayload(ours)).toBe(true);

    const foreign = new DataTransfer();
    foreign.setData("text/plain", "whatever");
    expect(hasDragPayload(foreign)).toBe(false);

    expect(hasDragPayload(new DataTransfer())).toBe(false);
    expect(hasDragPayload(null)).toBe(false);
  });

  it("still detects our drag when the payload data is unreadable", () => {
    // Browsers run dragenter/dragover in protected mode (getData() === "")
    // and Chrome can also return "" during drop under memory pressure —
    // `types` stays enumerable, so the MIME is still visible.
    const protectedDt = new DataTransfer();
    protectedDt.setData(DND_NODE_MIME, "");
    expect(hasDragPayload(protectedDt)).toBe(true);
  });
});

describe("resolveDragPayload", () => {
  const fallback: DragPayload = { path: "capitulos/cap1.md", is_dir: false };

  it("prefers the dataTransfer payload when readable", () => {
    const dt = new DataTransfer();
    setDragPayload(dt, file);
    expect(resolveDragPayload(dt, fallback)).toEqual(file);
  });

  it("falls back to the drag state when the MIME is present but data is empty", () => {
    const protectedDt = new DataTransfer();
    protectedDt.setData(DND_NODE_MIME, "");
    expect(resolveDragPayload(protectedDt, fallback)).toEqual(fallback);
  });

  it("never applies the fallback to foreign drags", () => {
    const foreign = new DataTransfer();
    foreign.setData("text/plain", "external");
    expect(resolveDragPayload(foreign, fallback)).toBeNull();
    expect(resolveDragPayload(null, fallback)).toBeNull();
  });
});

describe("isFolderDropValid", () => {
  it("rejects dropping onto the node itself", () => {
    expect(isFolderDropValid(file, "capitulos/notas.md")).toBe(false);
    expect(isFolderDropValid(dir, "capitulos")).toBe(false);
  });

  it("rejects dropping onto the node's current parent (a no-op)", () => {
    expect(isFolderDropValid(file, "capitulos")).toBe(false);
  });

  it("rejects dropping a folder into its own descendant (a cycle)", () => {
    expect(isFolderDropValid(dir, "capitulos/viejos")).toBe(false);
    // Files have no subtree — a descendant path is not a cycle concern
    expect(isFolderDropValid(file, "capitulos/notas.md/x")).toBe(false);
  });

  it("accepts a sibling folder for files and folders", () => {
    expect(
      isFolderDropValid({ path: "notas.md", is_dir: false }, "otros"),
    ).toBe(true);
    expect(
      isFolderDropValid({ path: "capitulos", is_dir: true }, "otros"),
    ).toBe(true);
  });
});

describe("canDropToTreeBackground", () => {
  it("only allows root drops for nested nodes", () => {
    expect(canDropToTreeBackground(file)).toBe(true);
    expect(canDropToTreeBackground({ path: "notas.md", is_dir: false })).toBe(
      false,
    );
  });
});

describe("upLevelTarget", () => {
  it("moves a one-level-deep node to the section root", () => {
    expect(upLevelTarget("capitulos/cap1.md")).toBe("cap1.md");
  });

  it("moves a deeper node one level up (not all the way to root)", () => {
    expect(upLevelTarget("capitulos/viejos/cap0.md")).toBe("capitulos/cap0.md");
  });

  it("moves a folder one level up too", () => {
    expect(upLevelTarget("capitulos/viejos")).toBe("viejos");
  });

  it("leaves a root-level node unchanged", () => {
    expect(upLevelTarget("notas.md")).toBe("notas.md");
  });
});

describe("canDropToGridBackground", () => {
  it("is valid only while browsing a subdirectory", () => {
    expect(canDropToGridBackground(file, "capitulos")).toBe(true);
    expect(canDropToGridBackground(file, "capitulos/viejos")).toBe(true);
    // Section root has no parent to move up to
    expect(canDropToGridBackground(file, "")).toBe(false);
  });

  it("rejects dropping the browsed directory itself", () => {
    expect(canDropToGridBackground(dir, "capitulos")).toBe(false);
  });
});
