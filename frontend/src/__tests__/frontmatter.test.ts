import { describe, it, expect } from "vitest";
import {
  splitFrontmatter,
  mergeFrontmatter,
  setPortada,
} from "@/lib/frontmatter";

const WITH_FRONTMATTER =
  "---\ntype: Personaje\ntitle: Anisa\n---\n# Anisa\n\nVive en el valle.\n";

describe("splitFrontmatter", () => {
  it("splits content with a frontmatter block", () => {
    const result = splitFrontmatter(WITH_FRONTMATTER);

    expect(result.frontmatter).toBe("---\ntype: Personaje\ntitle: Anisa\n---\n");
    expect(result.body).toBe("# Anisa\n\nVive en el valle.\n");
  });

  it("returns content untouched when there is no frontmatter", () => {
    const content = "# Capítulo 1\n\nContenido sin metadatos.";
    const result = splitFrontmatter(content);

    expect(result.frontmatter).toBeNull();
    expect(result.body).toBe(content);
  });

  it("treats a body starting with '---' as regular content", () => {
    const content = "# Título\n\n---\nseparador";
    const result = splitFrontmatter(content);

    expect(result.frontmatter).toBeNull();
    expect(result.body).toBe(content);
  });

  it("detects CRLF line endings and preserves them byte-for-byte", () => {
    const content = "---\r\ntype: Personaje\r\ntitle: Anisa\r\n---\r\n# Anisa\r\n";
    const result = splitFrontmatter(content);

    expect(result.frontmatter).toBe("---\r\ntype: Personaje\r\ntitle: Anisa\r\n---\r\n");
    expect(result.body).toBe("# Anisa\r\n");
  });

  it("handles empty content", () => {
    const result = splitFrontmatter("");

    expect(result.frontmatter).toBeNull();
    expect(result.body).toBe("");
  });

  it("closes the block at EOF without a trailing newline", () => {
    const result = splitFrontmatter("---\ntype: X\n---");

    expect(result.frontmatter).toBe("---\ntype: X\n---");
    expect(result.body).toBe("");
  });

  it("allows trailing spaces on the closing delimiter", () => {
    const result = splitFrontmatter("---\ntype: X\n---   \nbody");

    expect(result.frontmatter).toBe("---\ntype: X\n---   \n");
    expect(result.body).toBe("body");
  });

  it("does not treat an unclosed opening delimiter as frontmatter", () => {
    const content = "---\ntype: X\nsin cierre";
    const result = splitFrontmatter(content);

    expect(result.frontmatter).toBeNull();
    expect(result.body).toBe(content);
  });

  it("closes at the FIRST '---' line, leaving later ones in the body", () => {
    const result = splitFrontmatter("---\na: 1\n---\n---\nbody");

    expect(result.frontmatter).toBe("---\na: 1\n---\n");
    expect(result.body).toBe("---\nbody");
  });

  it("supports an empty frontmatter block", () => {
    const result = splitFrontmatter("---\n---\nbody");

    expect(result.frontmatter).toBe("---\n---\n");
    expect(result.body).toBe("body");
  });

  it("treats a lone '---' without a newline as plain content", () => {
    const result = splitFrontmatter("---");

    expect(result.frontmatter).toBeNull();
    expect(result.body).toBe("---");
  });

  it("ignores a frontmatter-looking block that is not at the start", () => {
    const content = "intro\n---\ntype: X\n---\nresto";
    const result = splitFrontmatter(content);

    expect(result.frontmatter).toBeNull();
    expect(result.body).toBe(content);
  });
});

describe("mergeFrontmatter", () => {
  it("preserves the exact frontmatter block and body", () => {
    const frontmatter = "---\ntype: Personaje\ntitle: Anisa\n---\n";
    const body = "# Anisa\n\nCuerpo editado.";

    expect(mergeFrontmatter(frontmatter, body)).toBe(frontmatter + body);
  });

  it("returns the body unchanged when frontmatter is null", () => {
    const body = "# Nota\n\nSin metadatos.";

    expect(mergeFrontmatter(null, body)).toBe(body);
  });

  it("round-trips split -> merge to the original content", () => {
    const contents = [
      WITH_FRONTMATTER,
      "# Capítulo 1\n\nSin frontmatter.",
      "---\r\ntype: X\r\n---\r\nbody crlf",
      "---\ntype: X\n---",
      "",
      "---\n---\n",
      "---",
    ];

    for (const content of contents) {
      const { frontmatter, body } = splitFrontmatter(content);
      expect(mergeFrontmatter(frontmatter, body)).toBe(content);
    }
  });

  it("inserts a newline when the block has no trailing newline and body is non-empty", () => {
    // Safety net: EOF-closed block + user appends body → never glue onto "---"
    expect(mergeFrontmatter("---\ntype: X\n---", "cuerpo")).toBe(
      "---\ntype: X\n---\ncuerpo",
    );
  });
});

describe("setPortada", () => {
  it("S32: inserts a leading block when the file has no frontmatter", () => {
    const content = "# Anisa\n\nVive en el valle.\n";
    expect(setPortada(content, "wiki/media/x.jpg")).toBe(
      "---\nportada: wiki/media/x.jpg\n---\n# Anisa\n\nVive en el valle.\n",
    );
  });

  it("replaces an existing portada line, keeping every other key byte-identical", () => {
    const content =
      "---\ntype: Personaje\ntitle: Anisa\nportada: wiki/media/vieja.jpg\n---\n# Anisa\n";
    expect(setPortada(content, "wiki/media/nueva.jpg")).toBe(
      "---\ntype: Personaje\ntitle: Anisa\nportada: wiki/media/nueva.jpg\n---\n# Anisa\n",
    );
  });

  it("inserts the portada line before the closing delimiter when absent", () => {
    const content = "---\ntype: Personaje\ntitle: Anisa\n---\n# Anisa\n";
    expect(setPortada(content, "wiki/media/nueva.jpg")).toBe(
      "---\ntype: Personaje\ntitle: Anisa\nportada: wiki/media/nueva.jpg\n---\n# Anisa\n",
    );
  });

  it("preserves CRLF line endings when inserting the portada line", () => {
    const content = "---\r\ntype: Personaje\r\n---\r\n# Anisa\r\n";
    expect(setPortada(content, "wiki/media/nueva.jpg")).toBe(
      "---\r\ntype: Personaje\r\nportada: wiki/media/nueva.jpg\r\n---\r\n# Anisa\r\n",
    );
  });

  it("preserves CRLF on an existing portada line", () => {
    const content = "---\r\ntype: X\r\nportada: wiki/media/vieja.jpg\r\n---\r\ncuerpo";
    expect(setPortada(content, "wiki/media/nueva.jpg")).toBe(
      "---\r\ntype: X\r\nportada: wiki/media/nueva.jpg\r\n---\r\ncuerpo",
    );
  });

  it("handles a block closed at EOF without a trailing newline", () => {
    const content = "---\ntype: X\n---";
    expect(setPortada(content, "wiki/media/nueva.jpg")).toBe(
      "---\ntype: X\nportada: wiki/media/nueva.jpg\n---",
    );
  });

  it("works on an empty frontmatter block", () => {
    expect(setPortada("---\n---\nbody", "wiki/media/x.jpg")).toBe(
      "---\nportada: wiki/media/x.jpg\n---\nbody",
    );
  });

  it("quotes a path that would break a plain YAML scalar", () => {
    const content = "---\ntype: X\n---\n";
    expect(setPortada(content, "wiki/media/El Bosque #1.jpg")).toBe(
      '---\ntype: X\nportada: "wiki/media/El Bosque #1.jpg"\n---\n',
    );
  });

  it("leaves the body untouched", () => {
    const content =
      "---\ntitle: X\n---\n# Capítulo\n\n![alt](wiki/media/body.jpg)\n";
    expect(setPortada(content, "wiki/media/cover.jpg")).toContain(
      "\n# Capítulo\n\n![alt](wiki/media/body.jpg)\n",
    );
  });
});
