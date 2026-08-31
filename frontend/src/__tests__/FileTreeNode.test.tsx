import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileTreeNode } from "@/components/molecules/FileTreeNode";
import type { FileNode } from "@/api/types";

describe("FileTreeNode", () => {
  it("renders a file node with name", () => {
    const node: FileNode = {
      name: "historia.md",
      path: "historia.md",
      is_dir: false,
    };

    render(
      <FileTreeNode node={node} />,
    );

    expect(screen.getByText("historia.md")).toBeInTheDocument();
  });

  it("renders a directory node with expand/collapse chevron", () => {
    const node: FileNode = {
      name: "capitulos",
      path: "capitulos",
      is_dir: true,
      children: [],
    };

    render(
      <FileTreeNode node={node} />,
    );

    expect(screen.getByText("capitulos")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("shows children when directory is expanded", async () => {
    const node: FileNode = {
      name: "capitulos",
      path: "capitulos",
      is_dir: true,
      children: [
        { name: "cap1.md", path: "capitulos/cap1.md", is_dir: false },
        { name: "cap2.md", path: "capitulos/cap2.md", is_dir: false },
      ],
    };

    const user = userEvent.setup();
    render(
      <FileTreeNode node={node} />,
    );

    // Children should not be visible initially
    expect(screen.queryByText("cap1.md")).not.toBeInTheDocument();

    // Click to expand
    await user.click(screen.getByText("capitulos"));
    expect(screen.getByText("cap1.md")).toBeInTheDocument();
    expect(screen.getByText("cap2.md")).toBeInTheDocument();
  });

  it("calls onSelect when a file is clicked", async () => {
    const onSelect = vi.fn();
    const node: FileNode = {
      name: "notas.md",
      path: "notas.md",
      is_dir: false,
    };

    const user = userEvent.setup();
    render(
      <FileTreeNode node={node} onSelect={onSelect} />,
    );

    await user.click(screen.getByText("notas.md"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("notas.md");
  });

  it("toggles expand/collapse when directory is clicked", async () => {
    const node: FileNode = {
      name: "src",
      path: "src",
      is_dir: true,
      children: [
        { name: "main.ts", path: "src/main.ts", is_dir: false },
      ],
    };

    const user = userEvent.setup();
    render(
      <FileTreeNode node={node} />,
    );

    const toggle = screen.getByText("src");

    // Expand
    await user.click(toggle);
    expect(screen.getByText("main.ts")).toBeInTheDocument();

    // Collapse
    await user.click(toggle);
    expect(screen.queryByText("main.ts")).not.toBeInTheDocument();
  });

  it("applies selected styles to the selected file", () => {
    const node: FileNode = {
      name: "selected.md",
      path: "selected.md",
      is_dir: false,
    };

    render(
      <FileTreeNode node={node} selectedPath="selected.md" />,
    );

    const btn = screen.getByRole("button");
    expect(btn.className).toContain("border-action");
    expect(btn.className).toContain("bg-surface-active");
  });

  it("does not apply selected styles to non-selected file", () => {
    const node: FileNode = {
      name: "other.md",
      path: "other.md",
      is_dir: false,
    };

    render(
      <FileTreeNode node={node} selectedPath="selected.md" />,
    );

    const btn = screen.getByRole("button");
    expect(btn.className).not.toContain("border-action");
  });

  it("auto-expands directory containing the selected path", () => {
    const node: FileNode = {
      name: "docs",
      path: "docs",
      is_dir: true,
      children: [
        { name: "readme.md", path: "docs/readme.md", is_dir: false },
      ],
    };

    render(
      <FileTreeNode node={node} selectedPath="docs/readme.md" />,
    );

    // The child should be visible because the parent auto-expands
    expect(screen.getByText("readme.md")).toBeInTheDocument();
  });

  it("renders directory icon for directories", () => {
    const node: FileNode = {
      name: "folder",
      path: "folder",
      is_dir: true,
    };

    const { container } = render(
      <FileTreeNode node={node} />,
    );

    // Should have folder icons (chevron + folder)
    const dirIcons = container.querySelectorAll("svg");
    expect(dirIcons.length).toBeGreaterThanOrEqual(1);
  });

  it("renders markdown icon for .md files", () => {
    const node: FileNode = {
      name: "readme.md",
      path: "readme.md",
      is_dir: false,
    };

    const { container } = render(
      <FileTreeNode node={node} />,
    );

    const svgs = container.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThanOrEqual(1);
  });
});
