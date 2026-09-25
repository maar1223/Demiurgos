import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LocaleProvider, useLocale } from "@/i18n/LocaleProvider";
import { messages } from "@/i18n/messages";
import { getLocale } from "@/api/config";
import type { LocaleSettings } from "@/api/types";
import type { Mock } from "vitest";

vi.mock("@/api/config", () => ({ getLocale: vi.fn() }));

const EN_LOCALE: LocaleSettings = {
  ui: "en",
  conversation: "en",
  content: "en",
  region: null,
  region_explicit: false,
  iana_timezone: "UTC",
};

const ES_LOCALE: LocaleSettings = {
  ui: "es",
  conversation: "es",
  content: "es",
  region: null,
  region_explicit: false,
  iana_timezone: "UTC",
};

function Probe() {
  const { language, t, applyLocale, refreshLocale } = useLocale();
  return (
    <div>
      <span data-testid="lang">{language}</span>
      <span data-testid="nav-label">{t("nav.links.tallerMundo")}</span>
      <button
        type="button"
        onClick={() => applyLocale(EN_LOCALE)}
      >
        apply-en
      </button>
      <button type="button" onClick={() => void refreshLocale()}>
        refresh
      </button>
    </div>
  );
}

describe("LocaleProvider (UI-REQ-3/4/5)", () => {
  beforeEach(() => {
    (getLocale as Mock).mockReset();
    (getLocale as Mock).mockResolvedValue(ES_LOCALE);
  });

  it("seeds from the cached locale on first paint (UI-SCN-3.3)", () => {
    window.localStorage.setItem("demiurgos-locale", JSON.stringify(EN_LOCALE));
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    // The first render already matches the persisted locale — no "es" flash.
    expect(screen.getByTestId("lang")).toHaveTextContent("en");
    expect(screen.getByTestId("nav-label")).toHaveTextContent(
      messages.en["nav.links.tallerMundo"],
    );
  });

  it("refines to the backend-authoritative locale once loaded (UI-SCN-3.3)", async () => {
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("es");
    await waitFor(() => expect(screen.getByTestId("nav-label")).toHaveTextContent(
      messages.es["nav.links.tallerMundo"],
    ));
  });

  it("switches the whole tree instantly on applyLocale without a reload (UI-SCN-4.1)", async () => {
    const user = userEvent.setup();
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("es");

    await user.click(screen.getByRole("button", { name: "apply-en" }));

    expect(screen.getByTestId("lang")).toHaveTextContent("en");
    expect(screen.getByTestId("nav-label")).toHaveTextContent(
      messages.en["nav.links.tallerMundo"],
    );
  });

  it("keeps <html lang> and the document title in sync (UI-SCN-5.1, UI-SCN-5.2)", async () => {
    const user = userEvent.setup();
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    expect(document.documentElement.lang).toBe("es");
    expect(document.title).toBe(messages.es["document.title"]);

    await user.click(screen.getByRole("button", { name: "apply-en" }));

    expect(document.documentElement.lang).toBe("en");
    expect(document.title).toBe(messages.en["document.title"]);
  });

  it("re-fetches the backend locale via refreshLocale and applies it", async () => {
    (getLocale as Mock).mockResolvedValueOnce(ES_LOCALE);
    const user = userEvent.setup();
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );

    (getLocale as Mock).mockResolvedValueOnce(EN_LOCALE);
    await user.click(screen.getByRole("button", { name: "refresh" }));

    await waitFor(() => expect(screen.getByTestId("lang")).toHaveTextContent("en"));
    expect(getLocale).toHaveBeenCalledTimes(2);
  });

  it("falls back to the cached/default locale outside the provider (isolated tests)", () => {
    render(<Probe />);
    expect(screen.getByTestId("lang")).toHaveTextContent("es");
  });
});