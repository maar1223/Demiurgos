import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CategoryCard } from "@/components/molecules/CategoryCard";
import type { WorldInfo } from "@/api/types";

const mockWorld: WorldInfo = {
  name: "Vibrantes",
  has_lore: true,
  has_personajes: true,
  has_sagas: false,
};

describe("CategoryCard", () => {
  it("renders world name", () => {
    render(
      <CategoryCard world={mockWorld} fileCount={2} onClick={vi.fn()} />,
    );
    expect(screen.getByText("Vibrantes")).toBeInTheDocument();
  });

  it("renders file count badge", () => {
    render(
      <CategoryCard world={mockWorld} fileCount={3} onClick={vi.fn()} />,
    );
    expect(screen.getByText("3 archivos")).toBeInTheDocument();
  });

  it("renders section labels based on available sections", () => {
    render(
      <CategoryCard world={mockWorld} fileCount={2} onClick={vi.fn()} />,
    );
    expect(screen.getByText("Lore")).toBeInTheDocument();
    expect(screen.getByText("Personajes")).toBeInTheDocument();
    expect(screen.queryByText("Sagas")).not.toBeInTheDocument();
  });

  it("calls onClick when clicked", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(
      <CategoryCard world={mockWorld} fileCount={1} onClick={onClick} />,
    );

    await user.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onClick).toHaveBeenCalledWith(mockWorld);
  });

  it("renders as a button element", () => {
    render(
      <CategoryCard world={mockWorld} fileCount={1} onClick={vi.fn()} />,
    );
    expect(screen.getByRole("button").tagName).toBe("BUTTON");
  });
});
