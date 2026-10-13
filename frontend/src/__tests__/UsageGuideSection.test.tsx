import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { UsageGuideSection } from "@/components/organisms/UsageGuideSection";
import { tEs } from "@/__tests__/i18nTestUtils";

/**
 * Perfil → Guía de uso — the in-app usage guide. The component renders purely
 * from the i18n catalogue, so this suite asserts through catalogue keys (AD-11)
 * and never through bare literals.
 */

const TOPIC_TITLE_KEYS = [
  "profile.guide.firstSteps.title",
  "profile.guide.import.title",
  "profile.guide.workshop.title",
  "profile.guide.report.title",
  "profile.guide.updates.title",
] as const;

describe("UsageGuideSection — Perfil → Guía de uso", () => {
  it("renders the guide title and intro", () => {
    render(<UsageGuideSection />);

    expect(
      screen.getByRole("heading", {
        name: tEs("profile.guide.panelTitle"),
        level: 3,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(tEs("profile.guide.intro"))).toBeInTheDocument();
  });

  it("renders the five topic headings as accessible h4 blocks", () => {
    render(<UsageGuideSection />);

    const headings = TOPIC_TITLE_KEYS.map((key) =>
      screen.getByRole("heading", { name: tEs(key), level: 4 }),
    );
    expect(headings).toHaveLength(5);
  });

  it("renders every topic as a labelled block with an ordered list of steps", () => {
    render(<UsageGuideSection />);

    for (const key of TOPIC_TITLE_KEYS) {
      const heading = screen.getByRole("heading", { name: tEs(key), level: 4 });
      const topic = heading.closest("article") as HTMLElement;
      expect(topic).not.toBeNull();
      // Each block is labelled by its own heading.
      expect(topic).toHaveAttribute("aria-labelledby", heading.id);
      expect(within(topic).getByRole("list")).toBeInTheDocument();
      expect(within(topic).getAllByRole("listitem").length).toBeGreaterThan(0);
    }
  });

  it("does not include an installation topic (scoped out by the Owner)", () => {
    render(<UsageGuideSection />);

    expect(
      screen.queryByRole("heading", { name: /instalaci/i }),
    ).not.toBeInTheDocument();
  });
});
