import { describe, expect, it } from "vitest";

/**
 * Hardcoded user-visible literal guard (UI-REQ-2/UI-REQ-7 extension).
 *
 * The parity/voseo/mojibake guard cannot see a literal that was never put in
 * the catalogue, so a green build could still ship mixed language. This guard
 * is a heuristic scan of the app chrome (`frontend/src`) for JSX text nodes
 * and user-facing attributes (`aria-label`, `title`, `placeholder`, `alt`)
 * whose literal value looks like user copy — it contains a Spanish-accented
 * character or a curated Spanish/English UI word — and is not resolved through
 * `t(...)`.
 *
 * It is intentionally conservative: identifiers, routes, URLs, slugs, CSS
 * classes, `data-testid`, backend enum/keyword tables and technical values are
 * filtered out, so a legitimate literal never fails the gate. Product content
 * (`skills/`, `mundos/`, `plantillas/`, `ideas/`) is never scanned.
 *
 * Known limitation (documented, not a silent hole): the scan is line-based, so
 * a JSX text node split across multiple source lines is not detected; multi-
 * line copy is normally wrapped in `t(...)` anyway.
 */

const APP_SOURCE = import.meta.glob("/src/**/*.{ts,tsx}", {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;

/** Files that are never app-chrome copy: the catalogue itself and tests. */
const IGNORED_SEGMENTS = ["/src/i18n/", "/src/__tests__/"];
const IGNORED_SUFFIXES = [".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"];

const ACCENT = new Set("áéíóúñüÁÉÍÓÚÑÜ¿¡".split(""));

/**
 * Curated Spanish/English UI words that indicate untranslated copy. Kept
 * deliberately small: a hit here is a strong signal, not a guess.
 */
const UI_WORDS = new Set([
  "cargando", "guardar", "guardando", "cancelar", "cerrar", "abrir", "crear",
  "eliminar", "buscar", "seleccionar", "selecciona", "nombre", "mundo",
  "archivo", "carpeta", "perfil", "idioma", "importar", "exportar",
  "historial", "contenido", "estado", "tipo", "error", "imagen", "grupo",
  "chat", "token", "asistente", "modelo", "prueba", "configuración",
  "ajustes", "activo", "inactivo", "nuevo", "nueva", "todos", "todas",
  "ninguna", "ninguno", "sin", "con", "para", "desde",
  "loading", "save", "saving", "cancel", "close", "open", "create", "delete",
  "search", "select", "name", "world", "file", "folder", "profile",
  "import", "export", "history", "content", "status", "type", "image",
  "group", "assistant", "model", "probe", "settings", "active", "new",
  "all", "none", "copy", "show", "hide", "back", "next", "continue",
  "retry", "reload", "worlds", "workshop",
]);

/** Attribute names whose literal value is user-visible copy. */
const USER_FACING_ATTRS = ["aria-label", "title", "placeholder", "alt"];

/**
 * Explicit allowlist of legitimate literals. Each entry is an exact literal
 * value that is intentionally NOT catalogue copy (technical identifiers,
 * backend enum/keyword tables, product/brand names). Add here only after
 * confirming the literal is not user-facing chrome copy.
 */
const ALLOWED_LITERALS = new Set<string>([
  "Demiurgos",
  "BotFather",
  "OpenCode Go",
  "OpenAI",
  "OpenRouter",
  "OpenAI-compatible",
  "Ollama (local)",
  "LM Studio (local)",
  "spool",
  "Skill ID",
]);

/** Technical values that are never copy: URLs, routes, slugs, constants, keys. */
const TECHNICAL_RE = /^(?:https?:\/\/|\/|#|\.|@|data:|--|image\/|application\/|text\/|video\/|audio\/|[A-Z0-9_]+$|[a-z0-9_.\-/:]+$)/;

function isCopy(value: string): boolean {
  const text = value.trim();
  if (text.length < 3) return false;
  if (ALLOWED_LITERALS.has(text)) return false;
  if (TECHNICAL_RE.test(text)) return false;
  if (!/[a-záéíóúñü]/.test(text)) return false;
  return true;
}

function looksUserFacing(value: string): boolean {
  for (const char of value) {
    if (ACCENT.has(char)) return true;
  }
  const tokens = value.toLowerCase().match(/[a-záéíóúñü]+/g) ?? [];
  return tokens.some((token) => UI_WORDS.has(token));
}

interface Offender {
  file: string;
  line: number;
  kind: string;
  text: string;
}

function scanSource(file: string, content: string): Offender[] {
  const offenders: Offender[] = [];
  const lines = content.split("\n");
  let inBlockComment = false;
  lines.forEach((line, index) => {
    const stripped = line.trim();
    if (stripped.startsWith("/*")) inBlockComment = true;
    if (inBlockComment) {
      if (stripped.includes("*/")) inBlockComment = false;
      return;
    }
    if (stripped.startsWith("//") || stripped.startsWith("*")) return;

    for (const match of line.matchAll(/>\s*([^<>{}]{3,}?)\s*</g)) {
      const text = match[1].trim();
      if (isCopy(text) && looksUserFacing(text)) {
        offenders.push({ file, line: index + 1, kind: "jsx", text });
      }
    }
    for (const attr of USER_FACING_ATTRS) {
      const re = new RegExp(`${attr}="([^"]{3,})"`, "g");
      for (const match of line.matchAll(re)) {
        const text = match[1].trim();
        if (isCopy(text) && looksUserFacing(text)) {
          offenders.push({ file, line: index + 1, kind: attr, text });
        }
      }
    }
  });
  return offenders;
}

describe("hardcoded user-visible literal guard", () => {
  it("finds no hardcoded app-chrome copy outside the catalogue", () => {
    const offenders: Offender[] = [];
    for (const [file, content] of Object.entries(APP_SOURCE)) {
      if (IGNORED_SEGMENTS.some((segment) => file.includes(segment))) continue;
      if (IGNORED_SUFFIXES.some((suffix) => file.endsWith(suffix))) continue;
      offenders.push(...scanSource(file, content));
    }
    const report = offenders
      .map((o) => `${o.file}:${o.line} [${o.kind}] "${o.text}"`)
      .join("\n");
    expect(offenders, `hardcoded user-visible literals:\n${report}`).toEqual([]);
  });

  it("never scans product-content paths", () => {
    const productSegments = ["/skills/", "/mundos/", "/plantillas/", "/ideas/"];
    for (const file of Object.keys(APP_SOURCE)) {
      for (const segment of productSegments) {
        expect(file, `scan touched product content: ${file}`).not.toContain(
          segment,
        );
      }
    }
  });
});
