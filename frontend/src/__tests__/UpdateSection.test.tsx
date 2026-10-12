import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UpdateSection } from "@/components/organisms/UpdateSection";
import { getUpdateStatus, setUpdateChannel } from "@/api/updates";
import { ApiError } from "@/api/types";
import type { Mock } from "vitest";

vi.mock("@/api/updates", () => ({
  getUpdateStatus: vi.fn(),
  setUpdateChannel: vi.fn(),
}));

const baseStatus = {
  current_version: "0.2.0",
  channel: "Beta" as const,
  url_base: "https://example.test/channel",
  latest: "0.2.1",
  update_available: true,
  advisory_unavailable: false,
};

// The panel is manual-only (spec: "Read-only frontend update panel"): nothing
// is fetched on mount and nothing polls. These tests pin that contract.
describe("UpdateSection — Perfil → Actualizaciones (read-only check)", () => {
  beforeEach(() => {
    (getUpdateStatus as Mock).mockReset();
    (setUpdateChannel as Mock).mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("issues no request on mount (manual-only, no background check)", async () => {
    render(<UpdateSection />);
    // Give any accidental effect / microtask a chance to fire.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(getUpdateStatus).not.toHaveBeenCalled();
    expect(setUpdateChannel).not.toHaveBeenCalled();
  });

  it("renders the version and channel only after the manual check", async () => {
    (getUpdateStatus as Mock).mockResolvedValue(baseStatus);
    const user = userEvent.setup();
    render(<UpdateSection />);

    // Before the check the version is honestly unknown.
    expect(screen.getByTestId("update-current-version")).toHaveTextContent(
      "Sin verificar",
    );

    await user.click(
      screen.getByRole("button", { name: "Buscar actualizaciones" }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("update-current-version")).toHaveTextContent(
        "0.2.0",
      ),
    );
    expect(screen.getByTestId("update-channel-value")).toHaveTextContent("Beta");
    expect(getUpdateStatus).toHaveBeenCalledTimes(1);
  });

  it("fetches once per explicit click and never in the background", async () => {
    (getUpdateStatus as Mock).mockResolvedValue(baseStatus);
    const user = userEvent.setup();
    render(<UpdateSection />);

    expect(getUpdateStatus).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: "Buscar actualizaciones" }),
    );
    await waitFor(() => expect(getUpdateStatus).toHaveBeenCalledTimes(1));
    // Still exactly one request once the response settles — no timer/poll.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(getUpdateStatus).toHaveBeenCalledTimes(1);
  });

  it("switching the channel PUTs the new value and reflects it", async () => {
    (setUpdateChannel as Mock).mockResolvedValue({ channel: "Beta" });
    const user = userEvent.setup();
    render(<UpdateSection />);

    expect(screen.getByRole("radio", { name: "Estable" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.click(screen.getByRole("radio", { name: "Beta" }));

    expect(setUpdateChannel).toHaveBeenCalledWith("Beta");
    await waitFor(() =>
      expect(screen.getByTestId("update-channel-value")).toHaveTextContent(
        "Beta",
      ),
    );
    expect(screen.getByRole("radio", { name: "Beta" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("reverts the channel and surfaces an error when the PUT is rejected", async () => {
    (setUpdateChannel as Mock).mockRejectedValue(new ApiError(400, "invalid"));
    const user = userEvent.setup();
    render(<UpdateSection />);

    await user.click(screen.getByRole("radio", { name: "Beta" }));

    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Estable" })).toHaveAttribute(
        "aria-checked",
        "true",
      ),
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("reports an unavailable advisory without fabricating a version", async () => {
    (getUpdateStatus as Mock).mockResolvedValue({
      ...baseStatus,
      latest: null,
      update_available: false,
      advisory_unavailable: true,
    });
    const user = userEvent.setup();
    render(<UpdateSection />);

    await user.click(
      screen.getByRole("button", { name: "Buscar actualizaciones" }),
    );

    expect(
      await screen.findByText(/No se pudo consultar el canal/),
    ).toBeInTheDocument();
  });
});
