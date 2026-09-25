import { describe, expect, it } from "vitest";
import { messages, type MessageKey } from "@/i18n/messages";
import forbidden from "@/i18n/forbidden.json";

/**
 * Automated catalogue guard (AD-9, UI-REQ-7) — runs inside `npm test`
 * (`vitest run`), so it is a hard gate on the standard test command. It
 * enforces:
 *   1. 100% es/en key parity and non-empty values.
 *   2. Zero voseo/regionalism blocklist hits in the es catalogue.
 *   3. Zero mojibake in the catalogues AND in app source.
 *   4. The scan never touches product content (`skills/`, `mundos/`,
 *      `plantillas/`, `ideas/`).
 */

const ES_KEYS = Object.keys(messages.es) as MessageKey[];

const MOJIBAKE_SET = new Set(forbidden.mojibakeCodepoints);
const VERB_TOKENS = new Set(forbidden.verbs.map((token) => token.toLowerCase()));
const EXPRESSIONS = forbidden.expressions.map((token) => token.toLowerCase());
const IMPERATIVE_STEMS = new Set(forbidden.imperativeStems);

/**
 * Known mojibake defect owned by WU-2 (task 2.7): the double-encoded default
 * title at `useAIAssistantSessions.ts:102`/`:298` plus the leading BOM. It is
 * excluded from the source scan until 2.7 fixes it; remove this entry then.
 */
const MOJIBAKE_SOURCE_EXCLUSIONS = new Set([
  "/src/hooks/useAIAssistantSessions.ts",
]);

/** Every app-source file (raw text) plus frontend/index.html. */
const SOURCE_FILES = import.meta.glob("/src/**/*.{ts,tsx,json}", {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;

const INDEX_HTML_RAW = (await import("/index.html?raw")).default;

function tokensOf(value: string): string[] {
  return value
    .toLowerCase()
    .split(/[^a-záéíóúñü]+/)
    .filter(Boolean);
}

function blocklistHit(value: string): string | null {
  const lower = value.toLowerCase();
  for (const expression of EXPRESSIONS) {
    if (lower.includes(expression)) return expression;
  }
  for (const token of tokensOf(value)) {
    if (VERB_TOKENS.has(token)) return token;
    // Unambiguous first-conjugation voseo imperative: stem + "á" (hablá,
    // mirá, creá, iniciá…). Neutral forms never carry the accent, so this
    // cannot false-positive on "está" (stem "est" is not listed) or "papá"
    // ("pap" is not listed); "é"/"í" suffixes are skipped because they
    // collide with neutral past tenses (guardé, subí).
    if (token.endsWith("á") && IMPERATIVE_STEMS.has(token.slice(0, -1))) {
      return token;
    }
  }
  return null;
}

function mojibakeHit(text: string): string | null {
  for (const char of text) {
    if (MOJIBAKE_SET.has(char.codePointAt(0) as number)) {
      return `U+${(char.codePointAt(0) as number).toString(16).toUpperCase()} (${char})`;
    }
  }
  return null;
}

describe("catalogue guard (UI-REQ-7)", () => {
  it("enforces 100% es/en key parity with non-empty values (UI-SCN-7.1)", () => {
    const esKeys = Object.keys(messages.es).sort();
    const enKeys = Object.keys(messages.en).sort();
    expect(enKeys).toEqual(esKeys);
    for (const key of ES_KEYS) {
      expect(messages.es[key].trim().length, `es "${key}" is empty`).toBeGreaterThan(0);
      expect(messages.en[key].trim().length, `en "${key}" is empty`).toBeGreaterThan(0);
    }
  });

  it("rejects voseo/regionalism tokens in the es catalogue (UI-SCN-7.2)", () => {
    for (const key of ES_KEYS) {
      const hit = blocklistHit(messages.es[key]);
      expect(hit, `es "${key}" contains blocked token "${hit}"`).toBeNull();
    }
  });

  it("rejects mojibake in the catalogues (UI-SCN-7.3)", () => {
    for (const key of ES_KEYS) {
      const hit = mojibakeHit(messages.es[key]);
      expect(hit, `es "${key}" contains mojibake ${hit}`).toBeNull();
      const enHit = mojibakeHit(messages.en[key]);
      expect(enHit, `en "${key}" contains mojibake ${enHit}`).toBeNull();
    }
  });

  it("rejects mojibake in app source files (UI-SCN-7.3)", () => {
    const offenders: string[] = [];
    for (const [file, content] of Object.entries(SOURCE_FILES)) {
      if (MOJIBAKE_SOURCE_EXCLUSIONS.has(file)) continue;
      const hit = mojibakeHit(content);
      if (hit !== null) offenders.push(`${file}: ${hit}`);
    }
    const htmlHit = mojibakeHit(INDEX_HTML_RAW);
    if (htmlHit !== null) offenders.push(`/index.html: ${htmlHit}`);
    expect(offenders, `mojibake in app source:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("never scans product-content paths (UI-SCN-7.4)", () => {
    const productSegments = ["/skills/", "/mundos/", "/plantillas/", "/ideas/"];
    for (const file of Object.keys(SOURCE_FILES)) {
      for (const segment of productSegments) {
        expect(file, `scan touched product content: ${file}`).not.toContain(segment);
      }
    }
  });
});