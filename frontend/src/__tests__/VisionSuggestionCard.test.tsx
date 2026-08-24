import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { VisionSuggestionCard } from "@/components/molecules/VisionSuggestionCard";
import type { VisionSuggestion } from "@/api/types";

function visionSuggestion(
  overrides: Partial<VisionSuggestion> = {},
): VisionSuggestion {
  return {
    id: "vision:abc",
    candidate_id: "c1",
    relative_media_path: "media/Enciclopedia/portada.png",
    description: "Retrato de la reina en claroscuro",
    verdict: "confirma",
    analysis: "La imagen coincide con la descripción del texto.",
    tags: ["retrato", "claroscuro"],
    confidence: 0.0,
    provenance: { provider: "vision", capability: "multimodal" },
    evidence: "image:media/Enciclopedia/portada.png",
    review_state: "pending",
    ...overrides,
  };
}

describe("VisionSuggestionCard — media review (sync-lore-in-importer PR4)", () => {
  it("renders all advisory fields: verdict, description, path, tags, provenance", () => {
    render(
      <VisionSuggestionCard
        candidateId="c1"
        suggestion={visionSuggestion()}
        decision={null}
        busy={false}
        onDecision={vi.fn()}
      />,
    );

    const card = screen.getByTestId("suggestion-vision:abc");
    expect(card).toHaveAttribute("data-suggestion-state", "pending");

    // Verdict badge + family badge.
    expect(screen.getByText("confirma")).toBeInTheDocument();
    expect(screen.getByText("visión")).toBeInTheDocument();

    // Description (alt-text candidate), spool path, analysis, tags.
    expect(
      screen.getByText("Retrato de la reina en claroscuro"),
    ).toBeInTheDocument();
    expect(screen.getByText("media/Enciclopedia/portada.png")).toBeInTheDocument();
    expect(
      screen.getByText("La imagen coincide con la descripción del texto."),
    ).toBeInTheDocument();
    expect(screen.getByText("#retrato")).toBeInTheDocument();
    expect(screen.getByText("#claroscuro")).toBeInTheDocument();

    // Provenance + evidence.
    expect(screen.getByText(/Origen: vision/)).toBeInTheDocument();
    expect(
      screen.getByText("image:media/Enciclopedia/portada.png"),
    ).toBeInTheDocument();
  });

  it("renders a thumbnail when the server provides a servable preview URL", () => {
    render(
      <VisionSuggestionCard
        candidateId="c1"
        suggestion={visionSuggestion({
          thumbnail_url: "/api/mundo/media?path=wiki/media/portada.jpg",
        })}
        decision={null}
        busy={false}
        onDecision={vi.fn()}
      />,
    );

    const img = screen.getByRole("img", {
      name: "Retrato de la reina en claroscuro",
    });
    expect(img).toHaveAttribute(
      "src",
      "/api/mundo/media?path=wiki/media/portada.jpg",
    );
    // No placeholder when a real thumbnail is present.
    expect(
      screen.queryByLabelText("Imagen sin vista previa disponible"),
    ).not.toBeInTheDocument();
  });

  it("shows a placeholder instead of a broken image when no preview URL exists", () => {
    render(
      <VisionSuggestionCard
        candidateId="c1"
        suggestion={visionSuggestion()}
        decision={null}
        busy={false}
        onDecision={vi.fn()}
      />,
    );

    expect(
      screen.getByLabelText("Imagen sin vista previa disponible"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("approve/reject fire the decision callback with the suggestion id", () => {
    const onDecision = vi.fn();
    render(
      <VisionSuggestionCard
        candidateId="c1"
        suggestion={visionSuggestion()}
        decision={null}
        busy={false}
        onDecision={onDecision}
      />,
    );

    fireEvent.click(screen.getByTestId("suggestion-approve-vision:abc"));
    expect(onDecision).toHaveBeenCalledWith("c1", "vision:abc", "approve");

    fireEvent.click(screen.getByTestId("suggestion-reject-vision:abc"));
    expect(onDecision).toHaveBeenCalledWith("c1", "vision:abc", "reject");
  });

  it("locks the buttons once a decision is committed (approved/rejected)", () => {
    const onDecision = vi.fn();
    const { rerender } = render(
      <VisionSuggestionCard
        candidateId="c1"
        suggestion={visionSuggestion()}
        decision="approved"
        busy={false}
        onDecision={onDecision}
      />,
    );

    const card = screen.getByTestId("suggestion-vision:abc");
    expect(card).toHaveAttribute("data-suggestion-state", "approved");
    // The committed button locks; the opposite action stays available so
    // the reviewer can still flip the decision (existing slice-2 pattern).
    expect(
      screen.getByTestId("suggestion-approve-vision:abc"),
    ).toBeDisabled();
    expect(
      screen.getByTestId("suggestion-reject-vision:abc"),
    ).toBeEnabled();

    // Approved copy explains the gallery outcome.
    expect(
      screen.getByText(/se usará como texto alternativo/),
    ).toBeInTheDocument();

    rerender(
      <VisionSuggestionCard
        candidateId="c1"
        suggestion={visionSuggestion()}
        decision="rejected"
        busy={false}
        onDecision={onDecision}
      />,
    );
    expect(screen.getByTestId("suggestion-vision:abc")).toHaveAttribute(
      "data-suggestion-state",
      "rejected",
    );
    expect(
      screen.getByTestId("suggestion-reject-vision:abc"),
    ).toBeDisabled();
    expect(
      screen.getByTestId("suggestion-approve-vision:abc"),
    ).toBeEnabled();
    expect(
      screen.getByText(/no se registrará en la galería/),
    ).toBeInTheDocument();
  });

  it("shows all verdict labels for the closed vocabulary", () => {
    const { rerender } = render(
      <VisionSuggestionCard
        candidateId="c1"
        suggestion={visionSuggestion({ verdict: "contradice" })}
        decision={null}
        busy={false}
        onDecision={vi.fn()}
      />,
    );
    expect(screen.getByText("contradice")).toBeInTheDocument();

    rerender(
      <VisionSuggestionCard
        candidateId="c1"
        suggestion={visionSuggestion({ verdict: "no_aplica" })}
        decision={null}
        busy={false}
        onDecision={vi.fn()}
      />,
    );
    expect(screen.getByText("no aplica")).toBeInTheDocument();

    rerender(
      <VisionSuggestionCard
        candidateId="c1"
        suggestion={visionSuggestion({ verdict: "rechaza" })}
        decision={null}
        busy={false}
        onDecision={vi.fn()}
      />,
    );
    expect(screen.getByText("rechaza")).toBeInTheDocument();
  });
});