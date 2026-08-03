/**
 * Client-side line diff — LCS (longest common subsequence) dynamic
 * programming.
 *
 * Replaces the old @codemirror/merge dependency in LiveDiffEditor. The DP
 * table is O(n·m) in time and memory, which is fine for narrative files
 * (hundreds of lines).
 */

export type DiffLineStatus = "same" | "added" | "removed";

export interface DiffRow {
  /** Classification of this row: matched, present only on the right, or only on the left. */
  status: DiffLineStatus;
  /** Original-side line content; null when the row is an addition. */
  left: string | null;
  /** Edited-side line content; null when the row is a deletion. */
  right: string | null;
  /** 1-based line number on the original side; null when the row is an addition. */
  leftNumber: number | null;
  /** 1-based line number on the edited side; null when the row is a deletion. */
  rightNumber: number | null;
}

/**
 * Split text into lines without creating a phantom empty line from a
 * trailing newline: `"a\n"` → `["a"]`, `"a\n\n"` → `["a", ""]`, `""` → `[]`.
 * An empty string is zero lines, so an empty side renders as "everything
 * added/removed" instead of one fake empty row.
 */
export function splitLines(text: string): string[] {
  if (text === "") return [];
  const lines = text.split("\n");
  if (lines[lines.length - 1] === "") {
    lines.pop();
  }
  return lines;
}

/**
 * Pair up `a` (original) and `b` (edited) into aligned rows. Every returned
 * row maps one index of the row grid: both sides share the same vertical
 * position by construction, no matter how many visual lines either side
 * wraps to.
 *
 * Matching is exact (`===` on the raw line strings). When both sides have a
 * candidate line, the tie prefers a removal before an addition, which keeps
 * the common sequence anchored.
 */
export function diffLines(a: string[], b: string[]): DiffRow[] {
  const n = a.length;
  const m = b.length;
  const width = m + 1;
  // dp[i * width + j] = length of the LCS of a[i..] and b[j..]
  const dp = new Uint32Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i * width + j] =
        a[i] === b[j]
          ? dp[(i + 1) * width + j + 1] + 1
          : Math.max(dp[(i + 1) * width + j], dp[i * width + j + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) {
      rows.push({
        status: "same",
        left: a[i],
        right: b[j],
        leftNumber: i + 1,
        rightNumber: j + 1,
      });
      i++;
      j++;
    } else if (j >= m || (i < n && dp[(i + 1) * width + j] >= dp[i * width + j + 1])) {
      rows.push({
        status: "removed",
        left: a[i],
        right: null,
        leftNumber: i + 1,
        rightNumber: null,
      });
      i++;
    } else {
      rows.push({
        status: "added",
        left: null,
        right: b[j],
        leftNumber: null,
        rightNumber: j + 1,
      });
      j++;
    }
  }
  return rows;
}
