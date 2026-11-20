import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect, useState } from "react";
import { MANAGER_PERMISSIONS, me, ROLE_PERMISSIONS } from "@/test/fixtures";
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

/**
 * - `users`:    current backend (`AUTH_MODE=users`).
 * - `legacy`:   older backend without any identity layer: `/me` and `/auth/*` are 404, reads are public.
 * - `no_login`: `/me` answers 401 but `/auth/login` and `/auth/refresh` do not exist.
 */
type Mode = "users" | "legacy" | "no_login";
let mode: Mode;
let account: MeOut;
let signedIn: boolean;
let refresh: "ok" | "refused" | "missing";
let accessToken: string;
const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const path = new URL(String(input)).pathname.replace("/api/v1", "");
  const auth = new Headers(init?.headers).get("Authorization");
  const ok = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
  const notFound = () => ok({ detail: "Not Found" }, 404);
  if (mode === "legacy") return path === "/me" || path.startsWith("/auth/") ? notFound() : ok({ total: 7, items: [] });
  if (mode === "no_login" && path.startsWith("/auth/")) return notFound();
  if (path === "/auth/login") {
    const body = JSON.parse(String(init?.body));
    if (body.password !== "correct horse battery") return ok({ error: { code: "unauthorized", message: "Invalid e-mail or password." } }, 401);
    signedIn = true;
    return ok({ access_token: accessToken, refresh_token: "prr_x", expires_in: 900, user: account.user, role: account.role, permissions: account.permissions });
  }
  if (path === "/auth/refresh") {
    if (refresh === "missing") return notFound();
    if (refresh === "refused") return ok({ error: { code: "unauthorized" } }, 401);
    accessToken = "pra_y";
    return ok({ access_token: accessToken, refresh_token: "prr_y", expires_in: 900 });
  }
  if (path === "/auth/logout") {
    signedIn = false;
    return new Response(null, { status: 204 });
  }
  if (auth !== `Bearer ${accessToken}` || !signedIn) return ok({ error: { code: "unauthorized" } }, 401);
  if (path === "/me") return ok(account);
  return ok({ total: 54, items: [] });
});
const dataCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/rules"));
const unauthenticatedDataCalls = () =>
  fetchMock.mock.calls.filter(([u, init]) => !/\/(me|auth\/.*)$/.test(new URL(String(u)).pathname) && !new Headers(init?.headers).get("Authorization"));

/** A data request issued now is neither sent nor answered (held, then refused without a token). */
async function expectNothingSent() {
  const sent = fetchMock.mock.calls.length;
  const ctrl = new AbortController();
  const pending = api.rules(ctrl.signal);
  await new Promise((r) => setTimeout(r, 20));
  ctrl.abort();
  await expect(pending).rejects.toBeTruthy();
  expect(fetchMock.mock.calls.length).toBe(sent);
}

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
  refresh = "ok";
  accessToken = "pra_x";
  account = me("POPULATION_HEALTH_MANAGER", MANAGER_PERMISSIONS);
  window.sessionStorage.clear();
  resetSessionCache();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  fetchMock.mockClear();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
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
    expect(unauthenticatedDataCalls()).toHaveLength(0);
  });

  it("signs out through the API, clears the browser session and returns to sign-in", async () => {
    renderApp();
    await signIn();
    await screen.findByText("Rules loaded: 54");
    expect(window.sessionStorage.getItem("pulsereach-session")).toContain("pra_x");
    fireEvent.click(screen.getByRole("button", { name: "User menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    expect(await screen.findByText("You have signed out.")).toBeTruthy();
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/auth/logout"))).toBe(true);
    expect(window.sessionStorage.length).toBe(0);
    expect(screen.queryByText("Rules loaded: 54")).toBeNull();
    await expectNothingSent();
  });
});

describe("Token expiry and refresh failure", () => {
  it("rotates an expired access token without leaving the workspace", async () => {
    renderApp();
    await signIn();
    await screen.findByText("Rules loaded: 54");
    accessToken = "pra_rotated_by_server";
    refresh = "ok";
    expect((await api.rules()).total).toBe(54);
    expect(window.sessionStorage.getItem("pulsereach-session")).toContain("pra_y");
  });

  it("clears the session and returns to sign-in when the refresh is refused; nothing else is sent", async () => {
    renderApp();
    await signIn();
    await screen.findByText("Rules loaded: 54");
    accessToken = "pra_revoked";
    refresh = "refused";
    await expect(api.rules()).rejects.toMatchObject({ status: 401 });
    expect(await screen.findByText(/Your session ended or was revoked/)).toBeTruthy();
    expect(window.sessionStorage.getItem("pulsereach-session")).toBeNull();
    await expectNothingSent();
    expect(unauthenticatedDataCalls()).toHaveLength(0);
  });

  it("reports a backend that lost /auth/refresh as unsupported instead of falling back", async () => {
    renderApp();
    await signIn();
    await screen.findByText("Rules loaded: 54");
    accessToken = "pra_expired";
    refresh = "missing";
    await expect(api.rules()).rejects.toMatchObject({ status: 401 });
    expect(await screen.findByRole("heading", { name: "This API does not support sign-in" })).toBeTruthy();
    expect(screen.getByText("/auth/refresh")).toBeTruthy();
    expect(unauthenticatedDataCalls()).toHaveLength(0);
  });
});

describe("Older backend without authentication", () => {
  it("is reported as unsupported and no data request is sent", async () => {
    mode = "legacy";
    renderApp();
    expect(await screen.findByRole("heading", { name: "This API does not support sign-in" })).toBeTruthy();
    await new Promise((r) => setTimeout(r, 30));
    expect(dataCalls()).toHaveLength(0);
    expect(screen.queryByText(/Rules loaded: 7/)).toBeNull();
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
  });

  it("is unsupported when sign-in endpoints are missing, even if /me exists", async () => {
    mode = "no_login";
    renderApp();
    await signIn();
    expect(await screen.findByRole("heading", { name: "This API does not support sign-in" })).toBeTruthy();
    expect(screen.getByText("/auth/login")).toBeTruthy();
    expect(dataCalls()).toHaveLength(0);
  });

  it("is accepted only with the explicit local-development setting", async () => {
    vi.stubEnv("NEXT_PUBLIC_ALLOW_LEGACY_BACKEND", "true");
    mode = "legacy";
    renderApp();
    expect(await screen.findByText("Rules loaded: 7")).toBeTruthy();
    expect(new Headers(dataCalls()[0][1]?.headers).get("Authorization")).toBeNull();
  });

  it("is never accepted by a production build, even with the setting", async () => {
    vi.stubEnv("NEXT_PUBLIC_ALLOW_LEGACY_BACKEND", "true");
    vi.stubEnv("NODE_ENV", "production");
    mode = "legacy";
    renderApp();
    expect(await screen.findByRole("heading", { name: "This API does not support sign-in" })).toBeTruthy();
    await new Promise((r) => setTimeout(r, 30));
    expect(dataCalls()).toHaveLength(0);
  });
});

describe("Role access to staff workspaces", () => {
  const NAV = ["Population", "Programmes", "People"] as const;
  const EXPECTED: Record<keyof typeof ROLE_PERMISSIONS, readonly (typeof NAV)[number][] | null> = {
    SYSTEM_ADMIN: ["Programmes"],
    POPULATION_HEALTH_MANAGER: ["Population", "Programmes", "People"],
    CARE_COORDINATOR: ["Population", "Programmes", "People"],
    CLINICIAN: ["Population", "Programmes", "People"],
    PATIENT: null,
  };

  it.each(Object.keys(EXPECTED) as (keyof typeof ROLE_PERMISSIONS)[])("%s sees only the workspaces its permissions allow", async (role) => {
    account = me(role, ROLE_PERMISSIONS[role], role === "POPULATION_HEALTH_MANAGER" ? "organization" : "assigned");
    renderApp();
    await signIn();
    const expected = EXPECTED[role];
    if (expected === null) {
      expect(await screen.findByRole("heading", { name: "This workspace is for care teams" })).toBeTruthy();
      await new Promise((r) => setTimeout(r, 20));
      expect(dataCalls()).toHaveLength(0);
      return;
    }
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await waitFor(() => expect(within(nav).getByRole("link", { name: new RegExp(expected[0]) })).toBeTruthy());
    for (const item of NAV)
      expect(!!within(nav).queryByRole("link", { name: new RegExp(`^.*${item}`) }), `${role} ${item}`).toBe(expected.includes(item));
  });

  it("keeps a patient account out even if it carried a staff permission", async () => {
    account = me("PATIENT", [...ROLE_PERMISSIONS.PATIENT, "rules.read"]);
    renderApp();
    await signIn();
    expect(await screen.findByRole("heading", { name: "This workspace is for care teams" })).toBeTruthy();
    await new Promise((r) => setTimeout(r, 20));
    expect(dataCalls()).toHaveLength(0);
  });
});
