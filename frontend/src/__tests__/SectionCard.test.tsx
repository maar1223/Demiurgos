import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SectionCard } from "@/components/molecules/SectionCard";

describe("SectionCard", () => {
  it("renders label and file count", () => {
    render(
      <SectionCard section="lore" label="Lore" fileCount={77} onClick={vi.fn()} />,
    );
    expect(screen.getByText("Lore")).toBeInTheDocument();
    expect(screen.getByText("77 archivos")).toBeInTheDocument();
  });

  it("shows 'vacío' when the count is 0", () => {
    render(
      <SectionCard section="sagas" label="Sagas" fileCount={0} onClick={vi.fn()} />,
    );
    expect(screen.getByText("vacío")).toBeInTheDocument();
  });

  it("renders the description for known sections", () => {
    render(
      <SectionCard
        section="personajes"
        label="Personajes"
        fileCount={3}
        onClick={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Fichas de personajes y desarrollo"),
    ).toBeInTheDocument();
  });

  it("fires onClick when clicked", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(
      <SectionCard section="lore" label="Lore" fileCount={1} onClick={onClick} />,
    );

    await user.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders as a button element", () => {
    render(
      <SectionCard section="lore" label="Lore" fileCount={1} onClick={vi.fn()} />,
    );
    expect(screen.getByRole("button").tagName).toBe("BUTTON");
  });
});
