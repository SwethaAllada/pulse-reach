import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect, useState } from "react";
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
import { api } from "@/lib/api/client";
import { resetSessionCache } from "@/lib/auth/session";
import { AppShell } from "./app-shell";

/** A workspace that loads data on mount, like every real workspace does. */
function Probe() {
  const [n, setN] = useState<number | null>(null);
  useEffect(() => {
    api.rules().then((r) => setN(r.total), () => setN(-1));
  }, []);
  return <p>Rules loaded: {n ?? "…"}</p>;
}

type Mode = "users" | "legacy";
let mode: Mode;
let account: MeOut;
let signedIn: boolean;
const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const path = new URL(String(input)).pathname.replace("/api/v1", "");
  const auth = new Headers(init?.headers).get("Authorization");
  const ok = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
  if (mode === "legacy") return path === "/me" ? ok({ detail: "Not Found" }, 404) : ok({ total: 7, items: [] });
  if (path === "/auth/login") {
    const body = JSON.parse(String(init?.body));
    if (body.password !== "correct horse battery") return ok({ error: { code: "unauthorized", message: "Invalid e-mail or password." } }, 401);
    signedIn = true;
    return ok({ access_token: "pra_x", refresh_token: "prr_x", expires_in: 900, user: account.user, role: account.role, permissions: account.permissions });
  }
  if (path === "/auth/logout") {
    signedIn = false;
    return new Response(null, { status: 204 });
  }
  if (auth !== "Bearer pra_x" || !signedIn) return ok({ error: { code: "unauthorized" } }, 401);
  if (path === "/me") return ok(account);
  return ok({ total: 54, items: [] });
});
const dataCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/rules"));

function renderApp() {
  return render(
    <AuthProvider>
      <AppShell>
        <Probe />
      </AppShell>
    </AuthProvider>
  );
}

async function signIn(password = "correct horse battery") {
  fireEvent.change(await screen.findByLabelText("E-mail"), { target: { value: "manager.a@demo.pulsereach.invalid" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: /Sign in/ }));
}

beforeEach(() => {
  mode = "users";
  signedIn = false;
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

describe("AppShell authentication gate", () => {
  it("shows sign-in and holds workspace requests until a staff session exists", async () => {
    renderApp();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(dataCalls()).toHaveLength(0);

    await signIn("wrong password here");
    expect((await screen.findByRole("alert")).textContent).toContain("Invalid e-mail or password.");
    expect(dataCalls()).toHaveLength(0);

    await signIn();
    expect(await screen.findByText("Rules loaded: 54")).toBeTruthy();
    expect(dataCalls().every(([, init]) => new Headers(init?.headers).get("Authorization") === "Bearer pra_x")).toBe(true);
    const login = fetchMock.mock.calls.findLast(([u]) => String(u).endsWith("/auth/login"))!;
    expect(JSON.parse(String(login[1]?.body))).toEqual({ email: "manager.a@demo.pulsereach.invalid", password: "correct horse battery" });
  });

  it("shows only the navigation the role can use, and the role in the user menu", async () => {
    account = me("SYSTEM_ADMIN", ["rules.read", "facilities.read"]);
    renderApp();
    await signIn();
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await waitFor(() => expect(within(nav).getByRole("link", { name: /Programmes/ })).toBeTruthy());
    expect(within(nav).queryByRole("link", { name: /People/ })).toBeNull();
    expect(within(nav).queryByRole("link", { name: /Population/ })).toBeNull();
    expect(screen.getAllByText("System administrator").length).toBeGreaterThan(0);
  });

  it("keeps patients out of the staff workspace without loading any data", async () => {
    account = me("PATIENT", ["patients.read_self", "followups.respond", "patient_requests.create", "facilities.read"]);
    renderApp();
    await signIn();
    expect(await screen.findByRole("heading", { name: "This workspace is for care teams" })).toBeTruthy();
    await new Promise((r) => setTimeout(r, 20));
    expect(dataCalls()).toHaveLength(0);
  });

  it("signs out through the API and returns to sign-in", async () => {
    renderApp();
    await signIn();
    await screen.findByText("Rules loaded: 54");
    fireEvent.click(screen.getByRole("button", { name: "User menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    expect(await screen.findByText("You have signed out.")).toBeTruthy();
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/auth/logout"))).toBe(true);
    expect(window.sessionStorage.getItem("pulsereach-session")).toBeNull();
  });

  it("works without sign-in against a legacy backend (no identity layer)", async () => {
    mode = "legacy";
    renderApp();
    expect(await screen.findByText("Rules loaded: 7")).toBeTruthy();
    expect(new Headers(dataCalls()[0][1]?.headers).get("Authorization")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
  });
});
