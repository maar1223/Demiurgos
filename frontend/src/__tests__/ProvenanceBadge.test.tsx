import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProvenanceBadge } from "@/components/organisms/CoCreation/ProvenanceBadge";
import { tEs } from "@/__tests__/i18nTestUtils";

describe("ProvenanceBadge", () => {
  it("renders 'Deriva de {skill_id}@{version}' from a session-derivedFrom (TW14)", () => {
    render(<ProvenanceBadge derivedFrom={{ skill_id: "eneagrama", version: "1.2.0" }} />);

    expect(
      screen.getByText(
        tEs("cocreation.provenance", { skillId: "eneagrama", version: "1.2.0" }),
      ),
    ).toBeInTheDocument();
  });

  it("renders from parent fields on a published/draft record (REQ-CC-21)", () => {
    render(
      <ProvenanceBadge parentSkillId="eneagrama" parentVersion="1.1.0" />,
    );

    expect(
      screen.getByText(
        tEs("cocreation.provenance", { skillId: "eneagrama", version: "1.1.0" }),
      ),
    ).toBeInTheDocument();
  });

  it("prefers the session-derived provenance over parent fields", () => {
    render(
      <ProvenanceBadge
        derivedFrom={{ skill_id: "session", version: "2.0.0" }}
        parentSkillId="record"
        parentVersion="1.0.0"
      />,
    );

    expect(
      screen.getByText(
        tEs("cocreation.provenance", { skillId: "session", version: "2.0.0" }),
      ),
    ).toBeInTheDocument();
  });

  it("renders nothing when no provenance is present", () => {
    const { container } = render(<ProvenanceBadge derivedFrom={null} />);

    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when only one parent field is present", () => {
    const { container } = render(<ProvenanceBadge parentSkillId="eneagrama" />);

    expect(container.firstChild).toBeNull();
  });
});