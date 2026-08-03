import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileTree } from "@/components/organisms/FileTree";
import type { FileNode } from "@/api/types";

const nodes: FileNode[] = [
  { name: "Anisa.md", path: "Anisa.md", is_dir: false },
  { name: "Bira.md", path: "Bira.md", is_dir: false },
];

describe("FileTree", () => {
  it("renders the search input with placeholder", () => {
    render(<FileTree nodes={nodes} />);
    expect(
      screen.getByPlaceholderText("Buscar archivos…"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Buscar archivos")).toBeInTheDocument();
  });

  it("filters the rendered nodes as the user types", async () => {
    const user = userEvent.setup();
    render(<FileTree nodes={nodes} />);

    expect(screen.getByText("Anisa.md")).toBeInTheDocument();
    expect(screen.getByText("Bira.md")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Buscar archivos"), "anisa");

    expect(screen.getByText("Anisa.md")).toBeInTheDocument();
    expect(screen.queryByText("Bira.md")).not.toBeInTheDocument();
  });

  it("clear button restores all nodes", async () => {
    const user = userEvent.setup();
    render(<FileTree nodes={nodes} />);

    await user.type(screen.getByLabelText("Buscar archivos"), "anisa");
    expect(screen.queryByText("Bira.md")).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("Limpiar búsqueda"));

    expect(screen.getByText("Anisa.md")).toBeInTheDocument();
    expect(screen.getByText("Bira.md")).toBeInTheDocument();
  });

  it("shows 'Sin resultados' when the query matches nothing", async () => {
    const user = userEvent.setup();
    render(<FileTree nodes={nodes} />);

    await user.type(screen.getByLabelText("Buscar archivos"), "zzz");

    expect(screen.getByText("Sin resultados")).toBeInTheDocument();
    expect(screen.queryByText("Anisa.md")).not.toBeInTheDocument();
  });

  it("does not render the search input while loading", () => {
    render(<FileTree nodes={nodes} isLoading />);
    expect(
      screen.queryByPlaceholderText("Buscar archivos…"),
    ).not.toBeInTheDocument();
  });

  it("does not render the search input when there are no nodes", () => {
    render(<FileTree nodes={[]} />);
    expect(screen.getByText("Esta sección está vacía")).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Buscar archivos…"),
    ).not.toBeInTheDocument();
  });
});
