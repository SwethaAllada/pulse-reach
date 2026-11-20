import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, holdRequests, releaseRequests } from "./client";
import { clearSession, getSession, resetSessionCache, setSession } from "@/lib/auth/session";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const tokens = (n: number) => ({ access_token: `pra_${n}`, refresh_token: `prr_${n}`, expires_in: 900 });

const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>();
const authOf = (call: number) => new Headers(fetchMock.mock.calls[call][1]?.headers).get("Authorization");
const pathOf = (call: number) => new URL(String(fetchMock.mock.calls[call][0])).pathname;

beforeEach(() => {
  window.sessionStorage.clear();
  resetSessionCache();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  releaseRequests();
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("authenticated API client", () => {
  it("sends no Authorization header without a session (legacy backends)", async () => {
    fetchMock.mockResolvedValue(json({ total: 0, items: [] }));
    await api.rules();
    expect(authOf(0)).toBeNull();
  });

  it("attaches the bearer token and keeps the session per tab", async () => {
    setSession(tokens(1));
    fetchMock.mockResolvedValue(json({ total: 0, items: [] }));
    await api.rules();
    expect(authOf(0)).toBe("Bearer pra_1");
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

  it("clears the session when refresh is refused, and surfaces the 401", async () => {
    setSession(tokens(1));
    fetchMock.mockImplementation(async (input) =>
      String(input).endsWith("/auth/refresh") ? json({}, 401) : json({ error: { code: "unauthorized", message: "Session expired" } }, 401)
    );
    const err = (await api.rules().catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(401);
    expect(err.code).toBe("unauthorized");
    expect(getSession()).toBeNull();
  });

  it("reports 403 as a role limit with the backend error code", async () => {
    fetchMock.mockResolvedValue(json({ error: { code: "forbidden", message: "No" } }, 403));
    const err = (await api.populationSummary().catch((e) => e)) as ApiError;
    expect(err.status).toBe(403);
    expect(err.message).toContain("Your role does not have access");
  });

  it("holds data requests until released, but lets identity calls through", async () => {
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

  it("aborts a held request without sending it", async () => {
    holdRequests();
    const ctrl = new AbortController();
    const pending = api.rules(ctrl.signal);
    ctrl.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).not.toHaveBeenCalled();
    clearSession();
  });
});
