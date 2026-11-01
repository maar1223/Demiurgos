import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProposalsPanel from "@/components/organisms/ProposalsPanel";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { translate } from "@/i18n/messages";
import {
  acceptRelationProposal,
  fetchRelationCandidates,
  fetchRelationProposals,
  muteRelationCandidate,
  rejectRelationProposal,
  sweepRelations,
  unmuteRelationCandidate,
} from "@/api/graph";
import type { RelationCandidate, RelationSweepResponse } from "@/api/types";

vi.mock("@/hooks/useAppLanguage", () => ({ useAppLanguage: vi.fn() }));

vi.mock("@/api/graph", () => ({
  fetchRelationCandidates: vi.fn(),
  fetchRelationProposals: vi.fn(),
  sweepRelations: vi.fn(),
  acceptRelationProposal: vi.fn(),
  rejectRelationProposal: vi.fn(),
  muteRelationCandidate: vi.fn(),
  unmuteRelationCandidate: vi.fn(),
}));

const useAppLanguageMock = vi.mocked(useAppLanguage);

/** The hook returns `{ language, t }`; `t` resolves the real catalogue. */
const lang = (language: "es" | "en") => ({
  language,
  t: (key: Parameters<typeof translate>[1], params?: Parameters<typeof translate>[2]) =>
    translate(language, key, params),
});

function candidate(index: number): RelationCandidate {
  return {
    path: `lore/ficha-${index}.md`,
    id: `lore::ficha-${index}`,
    title: `Ficha ${index}`,
    digest: `digest-${index}`,
    mentions: ["lore::target"],
    missing: ["lore::target"],
  };
}

function seedCandidates(count: number): void {
  const items = Array.from({ length: count }, (_, index) => candidate(index + 1));
  vi.mocked(fetchRelationCandidates).mockResolvedValue({
    count,
    muted: [],
    items,
  });
}

function sweptResponse(overrides: Partial<RelationSweepResponse> = {}): RelationSweepResponse {
  return {
    status: "swept",
    swept: 5,
    created: 7,
    pending: 7,
    paths: [
      "lore/ficha-1.md",
      "lore/ficha-2.md",
      "lore/ficha-3.md",
      "lore/ficha-4.md",
      "lore/ficha-5.md",
    ],
    message: "",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useAppLanguageMock.mockReturnValue(lang("es"));
  seedCandidates(5);
  vi.mocked(fetchRelationProposals).mockResolvedValue({
    count: 1,
    items: [
      {
        id: "proposal-1",
        source_path: "lore/alpha.md",
        source_key: "lore::alpha",
        target_id: "lore::beta",
        relationship_type: "aliado-de",
        confidence: 0.9,
        evidence: "Alpha served Beta.",
        created_at: "2026-10-31T20:00:00",
      },
    ],
  });
  vi.mocked(sweepRelations).mockResolvedValue(sweptResponse());
  vi.mocked(acceptRelationProposal).mockResolvedValue({ success: true });
  vi.mocked(rejectRelationProposal).mockResolvedValue({ success: true });
  vi.mocked(muteRelationCandidate).mockResolvedValue({ success: true, muted: true });
  vi.mocked(unmuteRelationCandidate).mockResolvedValue({ success: true, muted: false });
});

describe("ProposalsPanel", () => {
  it("names the batch cost and the remaining count, with no instruction paragraph", async () => {
    render(<ProposalsPanel mundo="mundo" />);

    const button = await screen.findByTestId("sweep-button");
    expect(button).toHaveTextContent("Revisar 5 fichas");
    expect(screen.getByTestId("candidate-remaining")).toHaveTextContent(
      "5 fichas por revisar",
    );
    expect(
      screen.queryByText(/Una ficha por vez/),
    ).not.toBeInTheDocument();
  });

  it("names a single-ficha batch in the singular", async () => {
    seedCandidates(1);
    render(<ProposalsPanel mundo="mundo" />);

    expect(await screen.findByTestId("sweep-button")).toHaveTextContent(
      "Revisar 1 ficha",
    );
    expect(screen.getByTestId("candidate-remaining")).toHaveTextContent(
      "1 ficha por revisar",
    );
  });

  it("shows progress while the batch runs and a summary after", async () => {
    let resolveSweep!: (value: RelationSweepResponse) => void;
    vi.mocked(sweepRelations).mockReturnValue(
      new Promise<RelationSweepResponse>((resolve) => {
        resolveSweep = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<ProposalsPanel mundo="mundo" />);

    await user.click(await screen.findByTestId("sweep-button"));

    expect(sweepRelations).toHaveBeenCalledWith("mundo");
    expect(await screen.findByTestId("sweep-button")).toHaveTextContent(
      "Revisando 5 fichas…",
    );

    resolveSweep(sweptResponse());

    expect(await screen.findByTestId("sweep-notice")).toHaveTextContent(
      "5 fichas · 7 propuestas",
    );
  });

  it("shows the evidence quote on each proposal", async () => {
    render(<ProposalsPanel mundo="mundo" />);

    const evidence = await screen.findByTestId("proposal-evidence");
    expect(evidence).toHaveTextContent("Alpha served Beta.");
  });

  it("reports an unavailable provider without pretending work happened", async () => {
    vi.mocked(sweepRelations).mockResolvedValue(
      sweptResponse({ status: "unavailable", swept: 0, created: 0, paths: [] }),
    );
    const user = userEvent.setup();
    render(<ProposalsPanel mundo="mundo" />);

    await user.click(await screen.findByTestId("sweep-button"));

    expect(await screen.findByTestId("sweep-notice")).toHaveTextContent(
      "El proveedor semántico no respondió. Intenta de nuevo.",
    );
  });

  it("reports when there is nothing left to review", async () => {
    vi.mocked(sweepRelations).mockResolvedValue(
      sweptResponse({ status: "done", swept: 0, created: 0, paths: [] }),
    );
    const user = userEvent.setup();
    render(<ProposalsPanel mundo="mundo" />);

    await user.click(await screen.findByTestId("sweep-button"));

    expect(await screen.findByTestId("sweep-notice")).toHaveTextContent(
      "No quedan fichas por revisar.",
    );
  });

  it("keeps the candidate and muted sections", async () => {
    vi.mocked(fetchRelationCandidates).mockResolvedValue({
      count: 1,
      muted: ["lore/muted.md"],
      items: [candidate(1)],
    });
    render(<ProposalsPanel mundo="mundo" />);

    expect(await screen.findByText("Fichas candidatas")).toBeInTheDocument();
    expect(screen.getByText("Dejadas así")).toBeInTheDocument();
    expect(screen.getByText("lore/muted.md")).toBeInTheDocument();
  });
});
