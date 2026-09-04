import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ManualSkillCreator } from "@/components/organisms/ManualSkillCreator";

const mockCreateDraft = vi.hoisted(() => vi.fn());
const mockPublish = vi.hoisted(() => vi.fn());

vi.mock("@/api/methodologies", () => ({
  createMethodologyDraft: mockCreateDraft,
  publishMethodologyDraft: mockPublish,
}));

describe("ManualSkillCreator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCreateDraft.mockResolvedValue({ draft_id: "draft-1" });
    mockPublish.mockResolvedValue({});
  });

  it("publishes a draft through create + publish and clears the form", async () => {
    const user = userEvent.setup();
    render(<ManualSkillCreator />);

    await user.type(screen.getByLabelText("Skill ID"), "guided-character-v1");
    await user.type(screen.getByLabelText("Versión"), "1.3.0");
    await user.type(screen.getByLabelText("Nombre"), "Nueva metodología");
    await user.type(screen.getByLabelText(/Fuente/), "## Seguro\n");
    await user.click(screen.getByRole("button", { name: "Publicar borrador" }));

    await waitFor(() => {
      expect(mockCreateDraft).toHaveBeenCalledWith({
        skill_id: "guided-character-v1",
        version: "1.3.0",
        name: "Nueva metodología",
        source: "## Seguro\n",
      });
    });
    expect(mockPublish).toHaveBeenCalledWith("draft-1");

    await waitFor(() => {
      expect(screen.getByLabelText("Skill ID")).toHaveValue("");
    });
  });

  it("does not call the API when required fields are empty", async () => {
    const user = userEvent.setup();
    render(<ManualSkillCreator />);

    await user.click(screen.getByRole("button", { name: "Publicar borrador" }));

    expect(mockCreateDraft).not.toHaveBeenCalled();
    expect(mockPublish).not.toHaveBeenCalled();
  });

  it("shows the compiler-validation error when publishing fails", async () => {
    mockCreateDraft.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    render(<ManualSkillCreator />);

    await user.type(screen.getByLabelText("Skill ID"), "guided-character-v1");
    await user.type(screen.getByLabelText("Versión"), "1.3.0");
    await user.type(screen.getByLabelText("Nombre"), "Nueva metodología");
    await user.type(screen.getByLabelText(/Fuente/), "## Seguro\n");
    await user.click(screen.getByRole("button", { name: "Publicar borrador" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /no pasó la validación del compilador/,
    );
  });
});