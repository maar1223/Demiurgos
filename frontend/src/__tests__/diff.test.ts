import { describe, it, expect } from "vitest";
import { splitLines, diffLines, mergeChangedRows } from "@/lib/diff";

describe("splitLines", () => {
  it("returns [] for an empty string", () => {
    expect(splitLines("")).toEqual([]);
  });

  it("splits plain text without a trailing newline", () => {
    expect(splitLines("a\nb")).toEqual(["a", "b"]);
  });

  it("drops the phantom empty line from a trailing newline", () => {
    expect(splitLines("a\nb\n")).toEqual(["a", "b"]);
  });

  it("keeps real empty lines in the middle", () => {
    expect(splitLines("a\n\nb")).toEqual(["a", "", "b"]);
    expect(splitLines("a\n\n")).toEqual(["a", ""]);
  });

  it("treats a lone newline as one empty line", () => {
    expect(splitLines("\n")).toEqual([""]);
  });
});

describe("diffLines", () => {
  it("marks every line as same when the documents are identical", () => {
    const rows = diffLines(["a", "b", "c"], ["a", "b", "c"]);
    expect(rows.map((r) => r.status)).toEqual(["same", "same", "same"]);
    expect(rows.map((r) => r.leftNumber)).toEqual([1, 2, 3]);
    expect(rows.map((r) => r.rightNumber)).toEqual([1, 2, 3]);
  });

  it("marks all rows as added when the original is empty", () => {
    const rows = diffLines([], ["x", "y"]);
    expect(rows.map((r) => r.status)).toEqual(["added", "added"]);
    expect(rows.every((r) => r.left === null)).toBe(true);
    expect(rows.map((r) => r.rightNumber)).toEqual([1, 2]);
  });

  it("marks all rows as removed when the edited text is empty", () => {
    const rows = diffLines(["x", "y"], []);
    expect(rows.map((r) => r.status)).toEqual(["removed", "removed"]);
    expect(rows.every((r) => r.right === null)).toBe(true);
    expect(rows.map((r) => r.leftNumber)).toEqual([1, 2]);
  });

  it("pairs a changed line as removal followed by addition", () => {
    const rows = diffLines(["a", "b", "c"], ["a", "X", "c"]);
    expect(rows.map((r) => r.status)).toEqual([
      "same",
      "removed",
      "added",
      "same",
    ]);
    expect(rows[1]).toMatchObject({ left: "b", right: null, leftNumber: 2, rightNumber: null });
    expect(rows[2]).toMatchObject({ left: null, right: "X", leftNumber: null, rightNumber: 2 });
  });

  it("anchors the common sequence around an insertion", () => {
    const rows = diffLines(["a", "c"], ["a", "b", "c"]);
    expect(rows.map((r) => r.status)).toEqual(["same", "added", "same"]);
    expect(rows[1].right).toBe("b");
  });

  it("anchors the common sequence around a deletion", () => {
    const rows = diffLines(["a", "b", "c"], ["a", "c"]);
    expect(rows.map((r) => r.status)).toEqual(["same", "removed", "same"]);
    expect(rows[1].left).toBe("b");
  });

  it("keeps the longest common subsequence, not just the first match", () => {
    const rows = diffLines(["a", "b", "c", "d"], ["b", "c", "x"]);
    const statuses = rows.map((r) => r.status);
    // "b" and "c" must survive as same; "a" removed, "d" removed, "x" added
    expect(statuses).toEqual(["removed", "same", "same", "removed", "added"]);
  });

  it("compares lines exactly, so trailing whitespace counts", () => {
    const rows = diffLines(["a "], ["a"]);
    expect(rows.map((r) => r.status)).toEqual(["removed", "added"]);
  });

  it("produces no phantom row for a trailing-newline difference", () => {
    // "a\n" and "a" split to the same single line → everything same
    expect(diffLines(["a"], ["a"])).toHaveLength(1);
  });
});

describe("mergeChangedRows", () => {
  it("merges a changed line into a single changed row", () => {
    const rows = mergeChangedRows(diffLines(["a", "b", "c"], ["a", "X", "c"]));
    expect(rows.map((r) => r.status)).toEqual(["same", "changed", "same"]);
    expect(rows[1]).toMatchObject({
      status: "changed",
      left: "b",
      right: "X",
      leftNumber: 2,
      rightNumber: 2,
    });
  });

  it("pairs multi-line blocks by index", () => {
    const rows = mergeChangedRows(
      diffLines(["a", "b", "c", "d"], ["a", "X", "Y", "d"]),
    );
    expect(rows.map((r) => r.status)).toEqual([
      "same",
      "changed",
      "changed",
      "same",
    ]);
    expect(rows[1]).toMatchObject({ left: "b", right: "X" });
    expect(rows[2]).toMatchObject({ left: "c", right: "Y" });
  });

  it("keeps surplus removals as pure deletions", () => {
    const rows = mergeChangedRows(diffLines(["a", "b", "c"], ["a", "X"]));
    expect(rows.map((r) => r.status)).toEqual(["same", "changed", "removed"]);
    expect(rows[1]).toMatchObject({ left: "b", right: "X" });
    expect(rows[2]).toMatchObject({ status: "removed", left: "c", right: null });
  });

  it("keeps surplus additions as pure insertions", () => {
    const rows = mergeChangedRows(diffLines(["a", "b"], ["a", "X", "Y"]));
    expect(rows.map((r) => r.status)).toEqual(["same", "changed", "added"]);
    expect(rows[1]).toMatchObject({ left: "b", right: "X" });
    expect(rows[2]).toMatchObject({ status: "added", left: null, right: "Y" });
  });

  it("leaves pure insertions and pure deletions untouched", () => {
    expect(
      mergeChangedRows(diffLines([], ["x"])).map((r) => r.status),
    ).toEqual(["added"]);
    expect(
      mergeChangedRows(diffLines(["x"], [])).map((r) => r.status),
    ).toEqual(["removed"]);
  });

  it("merges a trailing-whitespace change", () => {
    const rows = mergeChangedRows(diffLines(["a "], ["a"]));
    expect(rows.map((r) => r.status)).toEqual(["changed"]);
    expect(rows[0]).toMatchObject({ left: "a ", right: "a" });
  });
});
