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

/**
 * Collapse `.` and `..` lexically.
 *
 * The server resolves real symlinks before comparing; a browser cannot, so this
 * is deliberately lexical. It only has to match the cases an author can type:
 * the `<root>/../copias` spelling is the one that would otherwise slip past the
 * pre-check and be refused by the API instead.
 */
function collapseDotSegments(value: string): string {
  const driveMatch = /^([a-z]:)\/?/i.exec(value);
  const prefix = driveMatch ? `${driveMatch[1]}/` : value.startsWith("/") ? "/" : "";
  const rest = value.slice(prefix.length);
  const segments: string[] = [];
  for (const segment of rest.split("/")) {
    if (!segment || segment === ".") continue;
    if (segment === "..") {
      segments.pop();
      continue;
    }
    segments.push(segment);
  }
  const joined = segments.join("/");
  if (!prefix) return joined;
  return joined ? `${prefix}${joined}` : prefix;
}

/** A comparable form of a folder path: one separator style, no trailing slash. */
export function normalizeFolderPath(path: string | null | undefined): string {
  const trimmed = (path ?? "").trim();
  if (!trimmed) return "";
  const slashed = collapseDotSegments(
    trimmed.replace(/\\/g, "/").replace(/\/{2,}/g, "/"),
  );
  if (!slashed) return "";
  // A Windows path compares case-insensitively; a POSIX one does not.
  const windows = /^[a-z]:\//i.test(slashed);
  return windows ? slashed.toLowerCase() : slashed;
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
