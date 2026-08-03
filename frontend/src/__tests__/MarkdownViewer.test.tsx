import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";

describe("MarkdownViewer", () => {
  it("renders markdown body without YAML frontmatter", () => {
    render(
      <MarkdownViewer
        content={
          "---\ntype: Personaje\ntitle: Anisa\n---\n# Anisa\n\nVive en el valle.\n"
        }
      />,
    );

    // Frontmatter keys must never leak into the rendered output
    expect(screen.queryByText(/type: Personaje/)).not.toBeInTheDocument();
    expect(screen.queryByText(/title: Anisa/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^---$/)).not.toBeInTheDocument();

    // The body renders normally
    expect(screen.getByRole("heading", { level: 1, name: "Anisa" })).toBeInTheDocument();
    expect(screen.getByText(/Vive en el valle/)).toBeInTheDocument();
  });

  it("renders plain content without frontmatter unchanged", () => {
    render(<MarkdownViewer content={"# Título\n\nSin metadatos."} />);

    expect(screen.getByRole("heading", { level: 1, name: "Título" })).toBeInTheDocument();
    expect(screen.getByText(/Sin metadatos/)).toBeInTheDocument();
  });
});
