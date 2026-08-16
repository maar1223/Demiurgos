import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Spinner } from "@/components/atoms/Spinner";

describe("Spinner", () => {
  it("renders with accessibility label", () => {
    render(<Spinner />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Cargando...")).toBeInTheDocument();
  });

  it("renders different sizes", () => {
    const { rerender } = render(<Spinner size="sm" />);
    expect(screen.getByRole("status").className).toContain("h-4");

    rerender(<Spinner size="lg" />);
    expect(screen.getByRole("status").className).toContain("h-12");
  });

  it("applies custom className", () => {
    render(<Spinner className="custom-spinner" />);
    expect(screen.getByRole("status").className).toContain("custom-spinner");
  });
});
