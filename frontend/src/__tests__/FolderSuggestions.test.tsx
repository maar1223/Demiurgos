import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { getContentDestinations, pickFolder } from "@/api/contentRoot";
import { FolderSuggestions } from "@/components/organisms/FolderSuggestions";

vi.mock("@/api/contentRoot", () => ({
  getContentDestinations: vi.fn(),
  pickFolder: vi.fn(),
}));

const mocked = {
  destinations: vi.mocked(getContentDestinations),
  pick: vi.mocked(pickFolder),
};

beforeEach(() => {
  vi.clearAllMocks();
  mocked.destinations.mockResolvedValue({ candidates: [], picker: true, native_dialog: true });
});

describe("FolderSuggestions", () => {
  it("opens the system dialog and hands the folder back", async () => {
    mocked.pick.mockResolvedValue({ cancelled: false, path: "/media/disco/MisMundos" });
    const onPick = vi.fn();
    render(<FolderSuggestions onPick={onPick} />);

    await userEvent.click(
      await screen.findByRole("button", { name: /elegir carpeta|choose folder/i }),
    );

    await waitFor(() => expect(mocked.pick).toHaveBeenCalled());
    expect(onPick).toHaveBeenCalledWith("/media/disco/MisMundos");
  });

  it("does not touch the form when the author cancels", async () => {
    mocked.pick.mockResolvedValue({ cancelled: true, path: null });
    const onPick = vi.fn();
    render(<FolderSuggestions onPick={onPick} />);

    await userEvent.click(
      await screen.findByRole("button", { name: /elegir carpeta|choose folder/i }),
    );

    await waitFor(() => expect(mocked.pick).toHaveBeenCalled());
    expect(onPick).not.toHaveBeenCalled();
  });

  it("reports a dialog that exists but could not open", async () => {
    mocked.pick.mockRejectedValue({ detail: "the folder dialog did not answer in time" });
    render(<FolderSuggestions onPick={vi.fn()} />);

    await userEvent.click(
      await screen.findByRole("button", { name: /elegir carpeta|choose folder/i }),
    );

    expect(await screen.findByTestId("content-folder-dialog-error")).toHaveTextContent(
      /did not answer/,
    );
  });

  it("hides the button when this host has no dialog", async () => {
    mocked.destinations.mockResolvedValue({ candidates: [], picker: true, native_dialog: false });
    render(<FolderSuggestions onPick={vi.fn()} />);

    await waitFor(() => expect(mocked.destinations).toHaveBeenCalled());
    expect(
      screen.queryByRole("button", { name: /elegir carpeta|choose folder/i }),
    ).not.toBeInTheDocument();
  });
});
