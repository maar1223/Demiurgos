/**
 * Locate a conflict quote inside a ficha body.
 *
 * The quote comes verbatim from the body the sweep saw, but it can carry
 * ellipses (an elided sentence) or typographic differences (accents, dashes,
 * punctuation). Exact match first, then the first non-elided fragment, then a
 * folded comparison (case/accents/punctuation ignored) with a map back to the
 * original offsets.
 */
export interface FragmentRange {
  start: number;
  end: number;
}

/** Fold case, accents and punctuation, keeping a map back to the original. */
function fold(text: string): { folded: string; map: number[] } {
  const map: number[] = [];
  let folded = "";
  for (let index = 0; index < text.length; index += 1) {
    const base = text[index]
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
    for (const char of base) {
      if (/[a-z0-9]/.test(char)) {
        folded += char;
        map.push(index);
      } else if (folded.length > 0 && !folded.endsWith(" ")) {
        folded += " ";
        map.push(index);
      }
    }
  }
  return { folded, map };
}

/** The range of ``quote`` inside ``text``, or null when it is not there. */
export function locateFragment(
  text: string,
  quote: string,
): FragmentRange | null {
  const clean = (quote ?? "").trim();
  if (!text || !clean) return null;

  const exact = text.indexOf(clean);
  if (exact >= 0) return { start: exact, end: exact + clean.length };

  const fragments = clean
    .split(/\.{3,}|…/)
    .map((part) => part.trim())
    .filter(Boolean);

  for (const fragment of fragments) {
    const found = text.indexOf(fragment);
    if (found >= 0) return { start: found, end: found + fragment.length };
  }

  const { folded, map } = fold(text);
  for (const fragment of fragments.length > 0 ? fragments : [clean]) {
    const target = fold(fragment).folded.trim();
    // A four-character floor: shorter fragments match half the corpus and
    // would point the Author at the wrong sentence.
    if (target.replace(/ /g, "").length < 4) continue;
    const at = folded.indexOf(target);
    if (at < 0) continue;
    const start = map[at] ?? 0;
    const end = (map[at + target.length - 1] ?? start) + 1;
    return { start, end };
  }
  return null;
}
