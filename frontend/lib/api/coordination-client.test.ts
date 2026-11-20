import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, apiErrorMessage } from "./client";
import { setSession } from "@/lib/auth/session";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>();
const urlOf = (call: number) => new URL(String(fetchMock.mock.calls[call][0]));
const initOf = (call: number) => fetchMock.mock.calls[call][1]!;

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("coordination API methods", () => {
  it("sends PATCH writes as JSON with the bearer token", async () => {
    fetchMock.mockResolvedValue(json({ task_id: "T-1" }));
    await api.updateTask("T 1", { status: "in_progress", priority: "urgent" });
    expect(urlOf(0).pathname).toBe("/api/v1/follow-up-tasks/T%201");
    const init = initOf(0);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ status: "in_progress", priority: "urgent" });
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Authorization")).toBe("Bearer pra_test");
  });

  it("posts task actions to their own endpoints", async () => {
    fetchMock.mockImplementation(async () => json({}));
    await api.addTaskNote("T-1", "Called twice", false);
    await api.recordContactAttempt("T-1", { channel: "phone", outcome: "no_answer", note: null });
    await api.completeTask("T-1", "FU-1");
    await api.createCareGapFollowUp("G1", { event_type: "completion_documented", close_gap: true, documented_evidence: true, evidence_reference: "SYNTH-SCR-1" });
    expect(fetchMock.mock.calls.map((_, i) => `${initOf(i).method} ${urlOf(i).pathname}`)).toEqual([
      "POST /api/v1/follow-up-tasks/T-1/notes",
      "POST /api/v1/follow-up-tasks/T-1/contact-attempts",
      "POST /api/v1/follow-up-tasks/T-1/complete",
      "POST /api/v1/care-gaps/G1/follow-ups",
    ]);
    expect(JSON.parse(String(initOf(0).body))).toEqual({ text: "Called twice", patient_visible: false });
    expect(JSON.parse(String(initOf(2).body))).toEqual({ completion_follow_up_id: "FU-1" });
  });

  it("reads exact appointment totals from one-row pages and unwraps the care team", async () => {
    fetchMock.mockImplementation(async (input) =>
      new URL(String(input)).pathname.endsWith("/care-team") ? json({ items: [{ user_id: "U-1" }] }) : json({ total: 17, limit: 1, offset: 0, items: [] })
    );
    expect(await api.appointmentsTotal({ status_group: "active", scheduled_from: "2026-11-16T00:00:00.000Z" })).toBe(17);
    const q = urlOf(0).searchParams;
    expect(q.get("limit")).toBe("1");
    expect(q.get("offset")).toBe("0");
    expect(q.get("status_group")).toBe("active");
    expect(await api.careTeam("SYNTH-PAT-1")).toEqual([{ user_id: "U-1" }]);
    expect(urlOf(1).searchParams.get("patient_id")).toBe("SYNTH-PAT-1");
    await api.careTeam();
    expect(urlOf(2).searchParams.has("patient_id")).toBe(false);
  });

  it("rotates the session once on 401 and repeats the same write", async () => {
    setSession({ access_token: "pra_1", refresh_token: "prr_1", expires_in: 900 });
    fetchMock.mockImplementation(async (input, init) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith("/auth/refresh")) return json({ access_token: "pra_2", refresh_token: "prr_2", expires_in: 900 });
      return new Headers(init?.headers).get("Authorization") === "Bearer pra_2" ? json({ request_id: "R-1" }) : json({ error: { code: "unauthorized" } }, 401);
    });
    await api.updatePatientRequest("R-1", { status: "acknowledged", staff_response: "Hi" });
    const writes = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/patient-requests/R-1"));
    expect(writes).toHaveLength(2);
    expect(writes.map(([, init]) => init!.body)).toEqual([writes[0][1]!.body, writes[0][1]!.body]);
    expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/auth/refresh"))).toHaveLength(1);
  });
});

describe("apiErrorMessage", () => {
  it("prefers the backend's localized reason for refused writes", async () => {
    fetchMock.mockResolvedValue(json({ error: { code: "contact_not_permitted", message: "Contact consent was withdrawn." } }, 422));
    const err = await api.recordContactAttempt("T-1", { channel: "sms", outcome: "reached" }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(apiErrorMessage(err)).toBe("Contact consent was withdrawn.");
  });

  it("keeps role and session messages and falls back for unknown errors", () => {
    expect(apiErrorMessage(new ApiError("Your role does not have access to /x (403).", 403, "/x", "forbidden", "Forbidden"))).toBe(
      "Your role does not have access to /x (403)."
    );
    expect(apiErrorMessage(new ApiError("Session not valid.", 401, "/x", "unauthorized", "Unauthorized"))).toBe("Session not valid.");
    expect(apiErrorMessage(new ApiError("The API responded 500 for /x.", 500, "/x"))).toBe("The API responded 500 for /x.");
    expect(apiErrorMessage(new Error("boom"))).toBe("The request failed.");
    expect(apiErrorMessage("nope", "Could not save.")).toBe("Could not save.");
  });
});
