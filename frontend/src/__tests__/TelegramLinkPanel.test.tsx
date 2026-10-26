import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TelegramLinkPanel } from "@/components/organisms/TelegramLinkPanel";
import {
  revokeTelegramLink,
  startTelegramLink,
  telegramLinkStatus,
} from "@/api/bugReports";
import { tEs } from "@/__tests__/i18nTestUtils";
import type { Mock } from "vitest";

vi.mock("@/api/bugReports", () => ({
  startTelegramLink: vi.fn(),
  telegramLinkStatus: vi.fn(),
  revokeTelegramLink: vi.fn(),
}));

// The QR is drawn by `qrcode`; the markup itself is not what these tests are
// about, so it is stubbed to keep the assertions deterministic.
vi.mock("qrcode", () => ({
  default: { toString: vi.fn().mockResolvedValue("<svg data-testid=\"qr-svg\"></svg>") },
}));

const TICKET = "ABCD2345";
const URL = `https://t.me/ReportesDemiurgosBot?start=${TICKET}`;

function ticketResponse(overrides: Record<string, unknown> = {}) {
  return {
    ticket: TICKET,
    expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
    reused: false,
    telegram_url: URL,
    ...overrides,
  };
}

function renderPanel() {
  return render(<TelegramLinkPanel pollIntervalMs={10} />);
}

describe("TelegramLinkPanel — linking surface (S8–S11)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (startTelegramLink as Mock).mockResolvedValue(ticketResponse());
    (telegramLinkStatus as Mock).mockResolvedValue({
      state: "pending",
      expires_at: ticketResponse().expires_at,
    });
  });

  it("mints a ticket, then shows the QR, the link and the code", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.telegramConnect") }),
    );

    await screen.findByTestId("bugreport-qr");
    expect(screen.getByTestId("bugreport-telegram-ticket")).toHaveTextContent(TICKET);
    expect(screen.getByTestId("bugreport-telegram-link")).toHaveAttribute("href", URL);
    expect(screen.getByTestId("bugreport-telegram-countdown")).toHaveTextContent(
      tEs("profile.bugreport.telegramExpiresIn", { time: "10:00" }),
    );
    expect(startTelegramLink).toHaveBeenCalledWith({
      report_identity: true,
      notify_releases: true,
    });
  });

  it("closes the loop when the phone confirms, naming the handle", async () => {
    (telegramLinkStatus as Mock)
      .mockResolvedValueOnce({ state: "pending", expires_at: null })
      .mockResolvedValue({
        state: "linked",
        username: "brook",
        display_name: "Brook",
        permissions: { report_identity: true, notify_releases: false },
      });
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.telegramConnect") }),
    );

    await screen.findByText(
      tEs("profile.bugreport.telegramConnected", { user: "@brook" }),
    );
    // The two permissions are shown separately, and the second one as declined.
    expect(
      screen.getByTestId("bugreport-telegram-permission-report"),
    ).toHaveTextContent(
      `✓ ${tEs("profile.bugreport.telegramPermReport")}`,
    );
    expect(
      screen.getByTestId("bugreport-telegram-permission-releases"),
    ).toHaveTextContent(
      `✕ ${tEs("profile.bugreport.telegramPermReleases")}`,
    );
    expect(
      screen.queryByTestId("bugreport-telegram-ticket"),
    ).not.toBeInTheDocument();
  });

  it("stops polling and offers a new link when the ticket expired", async () => {
    (telegramLinkStatus as Mock).mockResolvedValue({ state: "expired" });
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.telegramConnect") }),
    );

    await screen.findByText(tEs("profile.bugreport.telegramExpired"));
    const calls = (telegramLinkStatus as Mock).mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 40));
    // The expired state ends the loop instead of hammering a dead ticket.
    expect((telegramLinkStatus as Mock).mock.calls.length).toBe(calls);
  });

  it("copies the code for a phone that cannot open the link", async () => {
    const user = userEvent.setup();
    // userEvent installs its own clipboard stub, so the spy goes on top of it.
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    renderPanel();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.telegramConnect") }),
    );
    await screen.findByTestId("bugreport-telegram-ticket");
    await user.click(
      screen.getByRole("button", {
        name: tEs("profile.bugreport.telegramCopyCode"),
      }),
    );

    expect(writeText).toHaveBeenCalledWith(TICKET);
    await screen.findByRole("button", {
      name: tEs("profile.bugreport.telegramCopied"),
    });
  });

  it("states a permission separately: turning one off mints again with it", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.telegramConnect") }),
    );
    await screen.findByTestId("bugreport-telegram-ticket");
    (startTelegramLink as Mock).mockClear();

    await user.click(
      screen.getByLabelText(tEs("profile.bugreport.telegramPermReleases")),
    );

    await waitFor(() => expect(startTelegramLink).toHaveBeenCalledTimes(1));
    expect(startTelegramLink).toHaveBeenCalledWith({
      report_identity: true,
      notify_releases: false,
    });
  });

  it("unlinks and forgets the ticket when disconnected", async () => {
    (telegramLinkStatus as Mock).mockResolvedValue({
      state: "linked",
      username: null,
      display_name: null,
      permissions: { report_identity: true, notify_releases: true },
    });
    (revokeTelegramLink as Mock).mockResolvedValue({ revoked: true });
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.telegramConnect") }),
    );
    await screen.findByText(tEs("profile.bugreport.telegramConnectedAnon"));
    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.telegramDisconnect") }),
    );

    await waitFor(() => expect(revokeTelegramLink).toHaveBeenCalledTimes(1));
    expect(
      screen.getByRole("button", { name: tEs("profile.bugreport.telegramConnect") }),
    ).toBeInTheDocument();
  });

  it("reports a failed start instead of pretending a link exists", async () => {
    (startTelegramLink as Mock).mockRejectedValue(new Error("offline"));
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      screen.getByRole("button", { name: tEs("profile.bugreport.telegramConnect") }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      tEs("profile.bugreport.telegramError"),
    );
    expect(screen.queryByTestId("bugreport-telegram-ticket")).not.toBeInTheDocument();
  });
});
