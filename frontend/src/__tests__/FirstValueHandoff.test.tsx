import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FirstValueHandoff } from "@/components/organisms/FirstValueHandoff";
import { tEs } from "@/__tests__/i18nTestUtils";

describe("FirstValueHandoff", () => {
  const props = {
    worldName: "mi-mundo",
    onImport: vi.fn(),
    onWriteNote: vi.fn(),
    onSetupAssistant: vi.fn(),
    onDismiss: vi.fn(),
  };

  it("renders the accessible title, intro and the world name", () => {
    render(<FirstValueHandoff {...props} />);

    expect(
      screen.getByRole("region", { name: tEs("firstValueHandoff.aria") }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: tEs("firstValueHandoff.title") }),
    ).toBeInTheDocument();
    expect(screen.getByText(tEs("firstValueHandoff.intro"))).toBeInTheDocument();
    expect(screen.getByText("mi-mundo")).toBeInTheDocument();
  });

  it("renders the three action buttons with their hints and a dismiss control", () => {
    render(<FirstValueHandoff {...props} />);

    expect(
      screen.getByRole("button", { name: tEs("firstValueHandoff.import") }),
    ).toBeInTheDocument();
    expect(screen.getByText(tEs("firstValueHandoff.importHint"))).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: tEs("firstValueHandoff.writeNote") }),
    ).toBeInTheDocument();
    expect(screen.getByText(tEs("firstValueHandoff.writeNoteHint"))).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: tEs("firstValueHandoff.setupAssistant") }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(tEs("firstValueHandoff.setupAssistantHint")),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: tEs("firstValueHandoff.dismiss") }),
    ).toBeInTheDocument();
  });

  it("fires each callback when its control is activated", async () => {
    const user = userEvent.setup();
    render(<FirstValueHandoff {...props} />);

    await user.click(
      screen.getByRole("button", { name: tEs("firstValueHandoff.import") }),
    );
    await user.click(
      screen.getByRole("button", { name: tEs("firstValueHandoff.writeNote") }),
    );
    await user.click(
      screen.getByRole("button", { name: tEs("firstValueHandoff.setupAssistant") }),
    );
    await user.click(
      screen.getByRole("button", { name: tEs("firstValueHandoff.dismiss") }),
    );

    expect(props.onImport).toHaveBeenCalledTimes(1);
    expect(props.onWriteNote).toHaveBeenCalledTimes(1);
    expect(props.onSetupAssistant).toHaveBeenCalledTimes(1);
    expect(props.onDismiss).toHaveBeenCalledTimes(1);
  });
});