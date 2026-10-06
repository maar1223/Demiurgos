import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ManualSkillCreator } from "@/components/organisms/ManualSkillCreator";
import { tEs } from "@/__tests__/i18nTestUtils";

const mockCreateDraft = vi.hoisted(() => vi.fn());
const mockApproveTrigger = vi.hoisted(() => vi.fn());
const mockPublish = vi.hoisted(() => vi.fn());

vi.mock("@/api/methodologies", () => ({
  createMethodologyDraft: mockCreateDraft,
  approveDraftTrigger: mockApproveTrigger,
  publishMethodologyDraft: mockPublish,
}));

const approveResult = (text: string) => ({
  trigger_approval: {
    text,
    digest: `digest-${text.length}`,
    approved_by: "author-1",
    approved_at: "2026-10-05T00:00:00Z",
  },
});

async function fillForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Skill ID"), "guided-character-v1");
  await user.type(screen.getByLabelText("Versión"), "1.3.0");
  await user.type(screen.getByLabelText("Nombre"), "Nueva metodología");
  await user.type(screen.getByLabelText(/Fuente/), "## Seguro\n");
  await user.type(
    screen.getByLabelText(tEs("triggerApproval.inputAria")),
    "Perfil de eneatipos",
  );
}

describe("ManualSkillCreator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCreateDraft.mockResolvedValue({ draft_id: "draft-1" });
    mockApproveTrigger.mockImplementation((_id: string, text: string) =>
      Promise.resolve(approveResult(text)),
    );
    mockPublish.mockResolvedValue({});
  });

  it("creates the draft on approve, then publishes and clears the form", async () => {
    const user = userEvent.setup();
    render(<ManualSkillCreator />);

    await fillForm(user);

    // Publish is refused until the trigger is approved (D2/D4).
    expect(
      screen.getByRole("button", { name: tEs("skillCreate.submit") }),
    ).toBeDisabled();

    await user.click(screen.getByTestId("trigger-approve"));

    await waitFor(() => {
      expect(mockCreateDraft).toHaveBeenCalledWith({
        skill_id: "guided-character-v1",
        version: "1.3.0",
        name: "Nueva metodología",
        source: "## Seguro\n",
        description: "Perfil de eneatipos",
      });
    });
    expect(mockApproveTrigger).toHaveBeenCalledWith(
      "draft-1",
      "Perfil de eneatipos",
    );

    const publish = screen.getByRole("button", { name: tEs("skillCreate.submit") });
    await waitFor(() => expect(publish).toBeEnabled());
    await user.click(publish);

    await waitFor(() => expect(mockPublish).toHaveBeenCalledWith("draft-1"));

    await waitFor(() => {
      expect(screen.getByLabelText("Skill ID")).toHaveValue("");
    });
  });

  it("does not call the API when required fields are empty", async () => {
    const user = userEvent.setup();
    render(<ManualSkillCreator />);

    await user.click(screen.getByRole("button", { name: tEs("skillCreate.submit") }));
    expect(screen.getByTestId("trigger-approve")).toBeDisabled();

    expect(mockCreateDraft).not.toHaveBeenCalled();
    expect(mockApproveTrigger).not.toHaveBeenCalled();
    expect(mockPublish).not.toHaveBeenCalled();
  });

  it("shows the compiler-validation error when publishing fails", async () => {
    mockPublish.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    render(<ManualSkillCreator />);

    await fillForm(user);
    await user.click(screen.getByTestId("trigger-approve"));

    const publish = screen.getByRole("button", { name: tEs("skillCreate.submit") });
    await waitFor(() => expect(publish).toBeEnabled());
    await user.click(publish);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /no pasó la validación del compilador/,
    );
  });
});
