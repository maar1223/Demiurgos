import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FolderTreeNode } from "@/components/molecules/FolderTreeNode";
import type { FolderNode } from "@/lib/graphFilters";

/** Minimal folder tree fixture: `lore` with a `historia` subfolder. */
const tree: FolderNode = {
  path: "lore",
  name: "lore",
  children: [
    { path: "lore/historia", name: "historia", children: [] },
  ],
};

describe("FolderTreeNode", () => {
  it("renders the folder name with a checkbox and an expand/collapse chevron", () => {
    render(
      <FolderTreeNode node={tree} selectedFolders={[]} onToggle={vi.fn()} />,
    );

    expect(screen.getByText("lore")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "lore" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expandir lore" })).toBeInTheDocument();
  });

  it("collapses children by default (not visible until expanded)", () => {
    render(
      <FolderTreeNode node={tree} selectedFolders={[]} onToggle={vi.fn()} />,
    );

    expect(screen.queryByText("historia")).not.toBeInTheDocument();
  });

  it("expands and collapses children via the chevron button", async () => {
    const user = userEvent.setup();
    render(
      <FolderTreeNode node={tree} selectedFolders={[]} onToggle={vi.fn()} />,
    );

    // Expand
    await user.click(screen.getByRole("button", { name: "Expandir lore" }));
    expect(screen.getByText("historia")).toBeInTheDocument();

    // Collapse
    await user.click(screen.getByRole("button", { name: "Contraer lore" }));
    expect(screen.queryByText("historia")).not.toBeInTheDocument();
  });

  it("sets aria-expanded on the expand/collapse button", async () => {
    const user = userEvent.setup();
    render(
      <FolderTreeNode node={tree} selectedFolders={[]} onToggle={vi.fn()} />,
    );

    const toggle = screen.getByRole("button", { name: "Expandir lore" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Contraer lore" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("calls onToggle with the folder path when the checkbox is toggled", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();
    render(
      <FolderTreeNode node={tree} selectedFolders={[]} onToggle={onToggle} />,
    );

    await user.click(screen.getByRole("checkbox", { name: "lore" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onToggle).toHaveBeenCalledWith("lore");
  });

  it("checks the checkbox when the folder path is selected", () => {
    render(
      <FolderTreeNode
        node={tree}
        selectedFolders={["lore"]}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByRole("checkbox", { name: "lore" })).toBeChecked();
  });

  it("does not check the checkbox when the folder is not selected", () => {
    render(
      <FolderTreeNode node={tree} selectedFolders={[]} onToggle={vi.fn()} />,
    );

    expect(screen.getByRole("checkbox", { name: "lore" })).not.toBeChecked();
  });

  it("marks the parent checkbox indeterminate when only a descendant is checked", () => {
    render(
      <FolderTreeNode
        node={tree}
        selectedFolders={["lore/historia"]}
        onToggle={vi.fn()}
      />,
    );

    const loreCheckbox = screen.getByRole("checkbox", {
      name: "lore",
    }) as HTMLInputElement;
    // Partial selection is expressed via the DOM `indeterminate` property.
    expect(loreCheckbox.indeterminate).toBe(true);
  });

  it("is not indeterminate when the folder itself is checked", () => {
    render(
      <FolderTreeNode
        node={tree}
        selectedFolders={["lore"]}
        onToggle={vi.fn()}
      />,
    );

    const loreCheckbox = screen.getByRole("checkbox", {
      name: "lore",
    }) as HTMLInputElement;
    expect(loreCheckbox.indeterminate).toBe(false);
  });

  it("applies depth-based padding to nested children", async () => {
    const user = userEvent.setup();
    render(
      <FolderTreeNode node={tree} selectedFolders={[]} onToggle={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: "Expandir lore" }));
    const child = screen.getByText("historia");
    // The child row is nested one level deeper (16px per level).
    const row = child.closest("div");
    expect(row).toHaveStyle("padding-left: 20px");
  });
});
