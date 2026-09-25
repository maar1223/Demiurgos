import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LocaleProvider } from "@/i18n/LocaleProvider";
import { LocaleForm } from "@/components/organisms/LocaleForm";
import { getLocale } from "@/api/config";
import { submitStep0 } from "@/api/onboarding";
import { tEs } from "@/__tests__/i18nTestUtils";
import type { LocaleSettings } from "@/api/types";
import type { Mock } from "vitest";

vi.mock("@/api/config", () => ({ getLocale: vi.fn() }));
vi.mock("@/api/onboarding", () => ({ submitStep0: vi.fn() }));

const ES_LOCALE: LocaleSettings = {
  ui: "es",
  conversation: "es",
  content: "es",
  region: null,
  region_explicit: false,
  iana_timezone: "UTC",
};

const SAVED_STATUS = {
  completed: false,
  current_step: "account",
  completed_steps: ["step0"],
  pending_steps: ["account"],
  remote_pending: [],
  blocking_pending: ["account"],
};

function renderForm() {
  return render(
    <LocaleProvider>
      <LocaleForm />
    </LocaleProvider>,
  );
}

describe("LocaleForm (AD-7 inherit semantics, UI-REQ-3)", () => {
  beforeEach(() => {
    (getLocale as Mock).mockReset();
    (getLocale as Mock).mockResolvedValue(ES_LOCALE);
    (submitStep0 as Mock).mockReset();
    (submitStep0 as Mock).mockResolvedValue(SAVED_STATUS);
  });

  it("offers the inherit option first on the conversation and content selects", async () => {
    renderForm();

    const conversation = await screen.findByLabelText(tEs("locale.conversation"));
    const options = within(conversation).getAllByRole("option");
    expect(options[0]).toHaveValue("");
    expect(options[0]).toHaveTextContent(tEs("locale.inherit"));

    const content = screen.getByLabelText(tEs("locale.content"));
    const contentOptions = within(content).getAllByRole("option");
    expect(contentOptions[0]).toHaveValue("");
    expect(contentOptions[0]).toHaveTextContent(tEs("locale.inherit"));
  });

  it("defaults domains to inherit and persists explicit=false with the ui value", async () => {
    const user = userEvent.setup();
    renderForm();

    const conversation = await screen.findByLabelText(tEs("locale.conversation"));
    expect(conversation).toHaveValue("");
    expect(screen.getByLabelText(tEs("locale.content"))).toHaveValue("");

    await user.click(screen.getByRole("button", { name: tEs("common.save") }));

    await waitFor(() =>
      expect(submitStep0).toHaveBeenCalledWith({
        ui: "es",
        conversation: "es",
        content: "es",
        conversation_explicit: false,
        content_explicit: false,
        region: null,
        region_explicit: false,
        iana_timezone: "UTC",
      }),
    );
  });

  it("persists an explicit domain override when a language is selected", async () => {
    const user = userEvent.setup();
    renderForm();

    const conversation = await screen.findByLabelText(tEs("locale.conversation"));
    await user.selectOptions(conversation, "en");

    await user.click(screen.getByRole("button", { name: tEs("common.save") }));

    await waitFor(() =>
      expect(submitStep0).toHaveBeenCalledWith(
        expect.objectContaining({
          conversation: "en",
          conversation_explicit: true,
          content: "es",
          content_explicit: false,
        }),
      ),
    );
  });

  it("refreshes the backend-authoritative locale after a successful save", async () => {
    const user = userEvent.setup();
    renderForm();

    await screen.findByLabelText(tEs("locale.conversation"));
    await user.click(screen.getByRole("button", { name: tEs("common.save") }));

    // Provider refine + form prefill + refreshLocale after save.
    await waitFor(() => expect(getLocale).toHaveBeenCalledTimes(3));
  });

  it("routes every label through the catalogue (UI-REQ-2)", async () => {
    renderForm();

    expect(await screen.findByLabelText(tEs("locale.ui"))).toBeInTheDocument();
    expect(screen.getByLabelText(tEs("locale.conversation"))).toBeInTheDocument();
    expect(screen.getByLabelText(tEs("locale.content"))).toBeInTheDocument();
    expect(screen.getByLabelText(tEs("locale.region"))).toBeInTheDocument();
    expect(screen.getByLabelText(tEs("locale.regionExplicit"))).toBeInTheDocument();
    expect(screen.getByLabelText(tEs("locale.timezone"))).toBeInTheDocument();
    expect(screen.getByText(tEs("locale.form.intro"))).toBeInTheDocument();
  });
});