/**
 * Split/merge helpers for the YAML frontmatter block at the top of wiki
 * ficha files.
 *
 * The frontmatter is agent-only metadata: it must never surface in the
 * editor, the live diff, or the rendered markdown, and it must survive
 * saves byte-for-byte. These helpers implement the display/save split:
 * - `splitFrontmatter` strips the block for display, returning the raw
 *   block (delimiters included) aside from the body.
 * - `mergeFrontmatter` re-joins them on save so the on-disk file is
 *   restored exactly.
 *
 * Files without a frontmatter block (CHANGELOG.md, Catalogo, _README,
 * _atlas, plain notes) are a no-op: `splitFrontmatter` returns the content
 * untouched as body and `mergeFrontmatter(null, body)` returns the body.
 */

export interface SplitFrontmatterResult {
  /**
   * The FULL raw frontmatter block INCLUDING delimiters, e.g.
   * `"---\ntype: Personaje\ntitle: Anisa\n---\n"` (with the newline after
   * the closing delimiter when one exists), or `null` when no block is
   * present. CRLF line endings are preserved as-is.
   */
  frontmatter: string | null;
  /** Everything after the closing delimiter — the displayable content. */
  body: string;
}

/**
 * Matches a leading frontmatter block: a `---` line at the very start of
 * the file, followed by anything, closed by the first line that is exactly
 * `---` (optionally with trailing spaces/tabs) followed by a newline or EOF.
 *
 * The match (index 0) ends right after the closing `---`; the newline after
 * it (when present) is handled separately so the returned block includes it.
 */
const FRONTMATTER_PATTERN = /^---\r?\n([\s\S]*?)^---[ \t]*(?=\r?\n|$)/m;

/**
 * Splits raw file content into its frontmatter block and body.
 *
 * Detects a leading `---`-delimited YAML block (opening `---` + newline at
 * position 0, closing `---` line followed by a newline or EOF). Returns the
 * full raw block including both delimiters, or `null` when absent. The body
 * is everything after the closing delimiter — no leading newline carried
 * over from the delimiter line.
 *
 * Edge cases: empty content → `{ frontmatter: null, body: "" }`; an
 * unclosed opening `---` (no closing delimiter) → treated as body;
 * CRLF delimiters are detected and preserved byte-for-byte.
 */
export function splitFrontmatter(content: string): SplitFrontmatterResult {
  const match = FRONTMATTER_PATTERN.exec(content);
  // The `m` flag makes `^` match after any newline — a match must start at
  // position 0 or it is not a LEADING block and the file has no frontmatter.
  if (!match || match.index !== 0) {
    return { frontmatter: null, body: content };
  }

  // `match[0]` ends at the closing `---` (blockEnd). If a newline follows
  // the closing delimiter, it belongs to the block, not the body.
  const blockEnd = match.index + match[0].length;
  const rest = content.slice(blockEnd);
  let bodyStart = blockEnd;
  if (rest.startsWith("\r\n")) {
    bodyStart += 2;
  } else if (rest.startsWith("\n")) {
    bodyStart += 1;
  }

  return {
    frontmatter: content.slice(0, bodyStart),
    body: content.slice(bodyStart),
  };
}

/**
 * Re-joins a frontmatter block and a body into full file content for saving.
 *
 * `null` frontmatter (no block on disk) returns `body` unchanged. Otherwise
 * returns `frontmatter + body` — the block already includes its trailing
 * newline. Safety net: when the block lacks a trailing newline (closing
 * delimiter at EOF, no line break), a newline is inserted before a non-empty
 * body so the YAML never glues onto the first body line.
 */
export function mergeFrontmatter(
  frontmatter: string | null,
  body: string,
): string {
  if (frontmatter === null) return body;
  if (body.length === 0) return frontmatter;
  return frontmatter.endsWith("\n")
    ? frontmatter + body
    : frontmatter + "\n" + body;
}

// ---------------------------------------------------------------------------
// setPortada — line-preserving cover edit
// ---------------------------------------------------------------------------

/**
 * Splits text into lines keeping each line's terminator (`\r\n`, `\n`, or
 * nothing at EOF) attached to the line, so a re-join is byte-identical.
 * Drops the trailing empty match the regex produces at EOF.
 */
function splitLinesKeepEnds(text: string): string[] {
  const lines = text.match(/[^\r\n]*(?:\r\n|\n|$)/g) ?? [];
  if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

/**
 * Quotes a YAML scalar value only when needed (spaces, `:`, `#`, quotes…),
 * leaving plain-safe paths (letters, digits, `_ . / -`) untouched so the
 * on-disk value stays readable and the backend's quote-stripping read
 * accepts it either way.
 */
function yamlQuote(value: string): string {
  if (/^[A-Za-z0-9_./-]+$/.test(value)) return value;
  return `"${value.replace(/"/g, '\\"')}"`;
}

/**
 * Sets (or inserts) the `portada:` line in the raw file content, preserving
 * every other byte: the rest of the frontmatter block, the body, and the
 * block's line endings (CRLF blocks stay CRLF).
 *
 * Pattern of `_sync_updated_at_in_file` (backend): edit only the target
 * line, never rewrite the YAML. Operates on the RAW content (frontmatter
 * included) — the caller passes the file content from getFileContent.
 *
 * - No frontmatter block → a leading `---\nportada: {path}\n---\n` block is
 *   inserted before the body (S32).
 * - Existing block: an existing `portada:` line is replaced in place;
 *   otherwise the new line is inserted right before the closing `---`.
 */
export function setPortada(content: string, portadaPath: string): string {
  const { frontmatter, body } = splitFrontmatter(content);

  if (frontmatter === null) {
    return `---\nportada: ${yamlQuote(portadaPath)}\n---\n${body}`;
  }

  const eol = frontmatter.includes("\r\n") ? "\r\n" : "\n";
  const lines = splitLinesKeepEnds(frontmatter);
  // The block always ends right after the closing delimiter — the LAST line
  // is the closing `---` (possibly with trailing spaces and/or at EOF).
  const closeIdx = lines.length - 1;

  // Look for an existing `portada:` line BEFORE the closing delimiter.
  let portadaIdx = -1;
  for (let i = 1; i < closeIdx; i++) {
    if (/^portada:[ \t]*/.test(lines[i])) {
      portadaIdx = i;
      break;
    }
  }

  if (portadaIdx >= 0) {
    const terminator = lines[portadaIdx].match(/(?:\r\n|\n|$)/)?.[0] ?? eol;
    lines[portadaIdx] = `portada: ${yamlQuote(portadaPath)}${terminator}`;
  } else {
    lines.splice(closeIdx, 0, `portada: ${yamlQuote(portadaPath)}${eol}`);
  }

  return lines.join("") + body;
}
