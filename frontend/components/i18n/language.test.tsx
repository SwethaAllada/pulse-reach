import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MANAGER_PERMISSIONS, me } from "@/test/fixtures";
import type { MeOut } from "@/lib/api/types";

vi.mock("next/navigation", () => ({
  usePathname: () => "/programmes",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  default: ({ href, children, transitionTypes, ...rest }: { href: string; children: React.ReactNode; transitionTypes?: string[] }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { AuthProvider } from "@/lib/auth/auth-context";
import { resetSessionCache } from "@/lib/auth/session";
import { LOCALE_STORAGE_KEY, LOCALE_UNSYNCED_KEY } from "@/lib/i18n/config";
import { AppShell } from "@/components/shell/app-shell";
import { LocaleSync } from "./language-switcher";

let account: MeOut;
let signedIn: boolean;
let preferencesStatus: number;
const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const path = new URL(String(input)).pathname.replace("/api/v1", "");
  const ok = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
  if (path === "/auth/login") {
    signedIn = true;
    return ok({ access_token: "pra_x", refresh_token: "prr_x", expires_in: 900 });
  }
  if (!signedIn) return ok({ error: { code: "unauthorized" } }, 401);
  if (path === "/me") return ok(account);
  if (path === "/me/preferences") {
    const lang = JSON.parse(String(init?.body)).preferred_language;
    return ok({ preferred_language: lang, locale: lang, direction: lang === "ar" ? "rtl" : "ltr", supported_locales: ["en", "ar"], default_locale: "en" }, preferencesStatus);
  }
  return ok({ total: 0, items: [] });
});
const preferenceCalls = () =>
  fetchMock.mock.calls.filter(([u, init]) => String(u).endsWith("/me/preferences") && init?.method === "PATCH").map(([, init]) => JSON.parse(String(init?.body)));

function renderApp() {
  return render(
    <AuthProvider>
      <LocaleSync />
      <AppShell>
        <p>Workspace</p>
      </AppShell>
    </AuthProvider>
  );
}

async function signIn() {
  fireEvent.change(await screen.findByLabelText(/E-mail|البريد الإلكتروني/), { target: { value: "manager.a@demo.pulsereach.invalid" } });
  fireEvent.change(screen.getByLabelText(/^(Password|كلمة المرور)$/), { target: { value: "correct horse battery" } });
  fireEvent.click(screen.getByRole("button", { name: /^(Sign in|تسجيل الدخول)/ }));
}

beforeEach(() => {
  signedIn = false;
  preferencesStatus = 200;
  account = me("POPULATION_HEALTH_MANAGER", MANAGER_PERMISSIONS);
  window.sessionStorage.clear();
  resetSessionCache();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  fetchMock.mockClear();
  vi.unstubAllGlobals();
});

describe("Language selection", () => {
  it("defaults to English, left-to-right", async () => {
    renderApp();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(document.documentElement.lang).toBe("en");
    expect(document.documentElement.dir).toBe("ltr");
  });

  it("switches the signed-out screen to Arabic and RTL without losing typed input", async () => {
    renderApp();
    const email = await screen.findByLabelText("E-mail");
    fireEvent.change(email, { target: { value: "typed@example.invalid" } });
    fireEvent.click(screen.getByRole("button", { name: "العربية" }));

    expect(await screen.findByRole("heading", { name: "تسجيل الدخول" })).toBeTruthy();
    expect(document.documentElement.lang).toBe("ar");
    expect(document.documentElement.dir).toBe("rtl");
    expect((screen.getByLabelText("البريد الإلكتروني") as HTMLInputElement).value).toBe("typed@example.invalid");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("ar");
    expect(window.localStorage.getItem(LOCALE_UNSYNCED_KEY)).toBe("1");
  });

  it("saves a signed-out choice to the account at sign-in and localizes the shell", async () => {
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "العربية" }));
    await signIn();

    const nav = await screen.findByRole("navigation", { name: "التنقل الرئيسي" });
    expect(within(nav).getByRole("link", { name: "نظرة عامة على السكان" })).toBeTruthy();
    expect(preferenceCalls()).toEqual([{ preferred_language: "ar" }]);
    expect(window.localStorage.getItem(LOCALE_UNSYNCED_KEY)).toBeNull();
    // Every API request now asks the backend for Arabic labels and messages.
    const meCall = fetchMock.mock.calls.findLast(([u]) => String(u).endsWith("/me"))!;
    expect(new Headers(meCall[1]?.headers).get("Accept-Language")).toBe("ar");
  });

  it("applies the account's saved preference at sign-in", async () => {
    account = { ...account, user: { ...account.user, preferred_language: "ar" } };
    renderApp();
    await signIn();
    expect(await screen.findByRole("navigation", { name: "التنقل الرئيسي" })).toBeTruthy();
    expect(document.documentElement.dir).toBe("rtl");
    expect(preferenceCalls()).toEqual([]);
  });

  it("switches while signed in: saves the preference, keeps the session and the workspace", async () => {
    renderApp();
    await signIn();
    await screen.findByRole("navigation", { name: "Primary" });
    fireEvent.click(screen.getByRole("button", { name: "User menu" }));
    fireEvent.click(screen.getByRole("button", { name: "العربية" }));

    expect(await screen.findByRole("navigation", { name: "التنقل الرئيسي" })).toBeTruthy();
    expect(screen.getByText("Workspace")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "تسجيل الدخول" })).toBeNull();
    await vi.waitFor(() => expect(preferenceCalls()).toEqual([{ preferred_language: "ar" }]));

    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(await screen.findByRole("navigation", { name: "Primary" })).toBeTruthy();
    expect(document.documentElement.dir).toBe("ltr");
  });

  it("keeps the choice locally and retries later when saving fails", async () => {
    preferencesStatus = 500;
    renderApp();
    await signIn();
    await screen.findByRole("navigation", { name: "Primary" });
    fireEvent.click(screen.getByRole("button", { name: "User menu" }));
    fireEvent.click(screen.getByRole("button", { name: "العربية" }));
    expect(await screen.findByRole("navigation", { name: "التنقل الرئيسي" })).toBeTruthy();
    await vi.waitFor(() => expect(window.localStorage.getItem(LOCALE_UNSYNCED_KEY)).toBe("1"));
    expect(screen.queryByRole("heading", { name: "تسجيل الدخول" })).toBeNull();
  });
});
