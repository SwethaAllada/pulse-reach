import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  allowPortalRequests,
  allowUnauthenticatedRequests,
  api,
  ApiError,
  holdRequests,
  identityEndpointMissing,
  portalApi,
  releaseRequests,
  resetIdentityProbe,
} from "./client";
import { clearSession, getSession, resetSessionCache, setSession } from "@/lib/auth/session";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const tokens = (n: number) => ({ access_token: `pra_${n}`, refresh_token: `prr_${n}`, expires_in: 900 });

const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>();
const authOf = (call: number) => new Headers(fetchMock.mock.calls[call][1]?.headers).get("Authorization");
const pathOf = (call: number) => new URL(String(fetchMock.mock.calls[call][0])).pathname;
const dataCalls = () => fetchMock.mock.calls.filter(([u]) => !String(u).includes("/auth/"));

beforeEach(() => {
  window.sessionStorage.clear();
  resetSessionCache();
  resetIdentityProbe();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  releaseRequests();
  allowUnauthenticatedRequests(false);
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("authenticated API client", () => {
  it("never sends a data request without an access token", async () => {
    fetchMock.mockResolvedValue(json({ total: 0, items: [] }));
    const err = (await api.rules().catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(401);
    expect(err.code).toBe("not_authenticated");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends unauthenticated reads only when a legacy backend was explicitly allowed", async () => {
    fetchMock.mockResolvedValue(json({ total: 0, items: [] }));
    allowUnauthenticatedRequests(true);
    await api.rules();
    expect(authOf(0)).toBeNull();
  });

  it("lets identity calls through without a token (they establish the session)", async () => {
    fetchMock.mockResolvedValue(json({ error: { code: "unauthorized" } }, 401));
    await api.me().catch(() => undefined);
    expect(pathOf(0)).toBe("/api/v1/me");
    expect(authOf(0)).toBeNull();
  });

  it("attaches the bearer token to every protected request and keeps the session per tab", async () => {
    setSession(tokens(1));
    fetchMock.mockImplementation(async () => json({ total: 0, items: [] }));
    await Promise.all([api.rules(), api.openQuestions(), api.patientsTotal({ pathway: "ifhas" }), api.programmeSummary("ifhas", {})]);
    expect(fetchMock.mock.calls.map((_, i) => authOf(i))).toEqual(Array(4).fill("Bearer pra_1"));
    // Tokens travel only in the Authorization header — never in a URL.
    expect(fetchMock.mock.calls.every(([u]) => !String(u).includes("pra_") && !String(u).includes("prr_"))).toBe(true);
    resetSessionCache();
    expect(getSession()?.refreshToken).toBe("prr_1");
  });

  it("rotates once on 401 and retries with the new token; concurrent calls share one refresh", async () => {
    setSession(tokens(1));
    fetchMock.mockImplementation(async (input, init) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith("/auth/refresh")) return json(tokens(2));
      const auth = new Headers(init?.headers).get("Authorization");
      return auth === "Bearer pra_2" ? json({ total: 0, items: [] }) : json({ error: { code: "unauthorized" } }, 401);
    });
    await Promise.all([api.rules(), api.openQuestions()]);
    const refreshes = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/auth/refresh"));
    expect(refreshes).toHaveLength(1);
    expect(JSON.parse(String(refreshes[0][1]?.body))).toEqual({ refresh_token: "prr_1" });
    expect(getSession()?.accessToken).toBe("pra_2");
  });

  it("clears the session when refresh is refused, and sends nothing further", async () => {
    setSession(tokens(1));
    fetchMock.mockImplementation(async (input) =>
      String(input).endsWith("/auth/refresh") ? json({}, 401) : json({ error: { code: "unauthorized", message: "Session expired" } }, 401)
    );
    const err = (await api.rules().catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(401);
    expect(err.code).toBe("unauthorized");
    expect(getSession()).toBeNull();
    expect(window.sessionStorage.getItem("pulsereach-session")).toBeNull();
    const sent = fetchMock.mock.calls.length;
    await expect(api.openQuestions()).rejects.toMatchObject({ code: "not_authenticated" });
    expect(fetchMock.mock.calls.length).toBe(sent);
  });

  it("refreshes an expired access token before use and never falls back to an unauthenticated request", async () => {
    setSession({ ...tokens(1), expires_in: 0 });
    fetchMock.mockImplementation(async (input) =>
      String(input).endsWith("/auth/refresh") ? json({ error: { code: "unauthorized" } }, 401) : json({ total: 0, items: [] })
    );
    await expect(api.rules()).rejects.toMatchObject({ status: 401, code: "not_authenticated" });
    expect(dataCalls()).toHaveLength(0);
    expect(getSession()).toBeNull();
  });

  it("records a backend without /auth/refresh as missing its identity layer", async () => {
    setSession({ ...tokens(1), expires_in: 0 });
    fetchMock.mockImplementation(async (input) =>
      String(input).endsWith("/auth/refresh") ? json({ detail: "Not Found" }, 404) : json({ total: 0, items: [] })
    );
    await expect(api.rules()).rejects.toMatchObject({ status: 401 });
    expect(identityEndpointMissing()).toBe("/auth/refresh");
    expect(dataCalls()).toHaveLength(0);
  });

  it("reports 403 as a role limit with the backend error code, without exposing the token", async () => {
    setSession(tokens(7));
    fetchMock.mockResolvedValue(json({ error: { code: "forbidden", message: "No" } }, 403));
    const err = (await api.populationSummary().catch((e) => e)) as ApiError;
    expect(err.status).toBe(403);
    expect(err.message).toContain("Your role does not have access");
    expect(`${err.message} ${err.serverMessage} ${err.path}`).not.toMatch(/pra_|prr_/);
  });

  it("holds data requests until released, but lets identity calls through", async () => {
    setSession(tokens(1));
    fetchMock.mockImplementation(async () => json({ total: 0, items: [] }));
    holdRequests();
    const pending = api.rules();
    await api.me().catch(() => undefined);
    await new Promise((r) => setTimeout(r, 10));
    expect(fetchMock.mock.calls.map((_, i) => pathOf(i))).toEqual(["/api/v1/me"]);
    releaseRequests();
    await pending;
    expect(pathOf(1)).toBe("/api/v1/rules");
  });

  it("sends portal requests issued before the patient session resolved, but never staff requests", async () => {
    setSession(tokens(1));
    fetchMock.mockImplementation(async () => json({}));
    holdRequests();
    // Child effects (portal views) run before the AuthProvider effect that allows the portal.
    const portal = portalApi.summary();
    const staff = api.rules();
    await new Promise((r) => setTimeout(r, 10));
    expect(fetchMock).not.toHaveBeenCalled();
    allowPortalRequests(true);
    await portal;
    await new Promise((r) => setTimeout(r, 10));
    expect(fetchMock.mock.calls.map((_, i) => pathOf(i))).toEqual(["/api/v1/portal/summary"]);
    allowPortalRequests(false);
    releaseRequests();
    await staff;
  });

  it("aborts a held request without sending it", async () => {
    holdRequests();
    const ctrl = new AbortController();
    const pending = api.rules(ctrl.signal);
    ctrl.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).not.toHaveBeenCalled();
    clearSession();
  });

  it("requests the programme summary with server-side filters", async () => {
    setSession(tokens(1));
    fetchMock.mockResolvedValue(json({}));
    await api.programmeSummary("well_child", { region_id: 2, sex: "female" });
    const u = new URL(String(fetchMock.mock.calls[0][0]));
    expect(u.pathname).toBe("/api/v1/programmes/well_child/summary");
    expect(Object.fromEntries(u.searchParams)).toEqual({ region_id: "2", sex: "female" });
  });
});
