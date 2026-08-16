import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";

/**
 * The active-world selection (useCurrentWorld) and other features persist
 * to localStorage; tests must never inherit state written by a previous
 * test in the same file or suite.
 */
afterEach(() => {
  window.localStorage.clear();
});

/**
 * jsdom does not implement window.print — calling it throws
 * "Not implemented: window.print". The export-to-PDF flow
 * (ExportPdfDialog) relies on it, so a shared spy keeps it callable in
 * tests; tests assert on it directly (reset per test via vi.clearAllMocks).
 */
Object.defineProperty(window, "print", {
  writable: true,
  value: vi.fn(),
});

/**
 * jsdom does not implement the DataTransfer constructor, which the drag &
 * drop flows (FileTree / SectionCards) rely on. This minimal spec-shaped
 * stub lets tests carry a payload between dragStart and drop events.
 */
class DataTransferStub {
  private store = new Map<string, string>();
  dropEffect = "none";
  effectAllowed = "none";
  files = [] as unknown as FileList;
  items = [] as unknown as DataTransferItemList;

  get types(): string[] {
    return Array.from(this.store.keys());
  }

  setData(type: string, value: string): void {
    this.store.set(type.toLowerCase(), value);
  }

  getData(type: string): string {
    return this.store.get(type.toLowerCase()) ?? "";
  }

  clearData(type?: string): void {
    if (type) {
      this.store.delete(type.toLowerCase());
    } else {
      this.store.clear();
    }
  }

  setDragImage(_image: Element, _x: number, _y: number): void {}
}

Object.defineProperty(globalThis, "DataTransfer", {
  writable: true,
  value: DataTransferStub,
});
