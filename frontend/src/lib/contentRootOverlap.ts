/**
 * The two folders that must never overlap (step 4).
 *
 * The backup destination and the content root cannot be the same folder, one
 * inside the other, or one containing the other: the snapshot inventory takes
 * every top-level folder it does not recognise, and the backup's own layout is
 * one of those — so an overlapping destination copies each run into the next.
 *
 * This mirrors the server's refusal (`backup/state.py`,
 * `assert_destination_outside_content_root`) so the picker can say it BEFORE
 * sending, instead of surfacing a 400 as a surprise. The server stays the
 * authority: this is only the courtesy.
 */

/** A comparable form of a folder path: one separator style, no trailing slash. */
export function normalizeFolderPath(path: string | null | undefined): string {
  const trimmed = (path ?? "").trim();
  if (!trimmed) return "";
  let value = trimmed.replace(/\\/g, "/").replace(/\/{2,}/g, "/");
  // Keep a drive root path-like ("C:/"): stripping it would make "C:" a key
  // that no longer reads as a path, while both spellings must compare equal.
  const driveRoot = /^[a-z]:\/$/i.test(value);
  if (value.length > 1 && !driveRoot) value = value.replace(/\/+$/, "");
  if (!value) return "";
  // A Windows path compares case-insensitively; a POSIX one does not.
  const windows = /^[a-z]:\//i.test(value) || value.startsWith("//");
  return windows ? value.toLowerCase() : value;
}

/** Whether *child* is *parent* itself or lives inside it. */
function isWithin(child: string, parent: string): boolean {
  if (child === parent) return true;
  const prefix = parent.endsWith("/") ? parent : `${parent}/`;
  return child.startsWith(prefix);
}

/**
 * Whether the two folders overlap in ANY direction.
 *
 * An empty side never overlaps: without a configured root there is nothing to
 * compare, and guessing would refuse a legitimate folder.
 */
export function overlapsContentRoot(
  destination: string | null | undefined,
  contentRoot: string | null | undefined,
): boolean {
  const chosen = normalizeFolderPath(destination);
  const root = normalizeFolderPath(contentRoot);
  if (!chosen || !root) return false;
  return isWithin(chosen, root) || isWithin(root, chosen);
}
