import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { PatientPortal } from "./patient-portal";

const L = { locale: "en", direction: "ltr" };
const SUMMARY = { ...L, patient_id: "SYNTH-PAT-000001", given_name: "Noora", family_name: "Test", date_of_birth: "1980-01-01", date_of_birth_display: "1 January 1980", sex: "female", preferred_language: "en", preferred_channel: "sms", region_id: 1, is_synthetic: true, open_recommendations: 1, upcoming_appointments: 1, open_follow_ups: 1, awaiting_your_reply: 1, open_requests: 0 };
const REC = { recommendation_id: "G1", rule_id: "IFHAS-1", programme: "ifhas", programme_label: "Adult preventive screening", gap_type: "no_documented_screening", title: "Preventive check recommended", description: "No screening is recorded.", status: "open", status_label: "Open", identified_date: "2026-11-01", identified_date_display: "1 Nov 2026", next_step: null, next_step_text: "Contact your provider." };
const APPT = { appointment_id: "A1", appointment_type: "ifhas_screening", appointment_type_label: "Preventive screening visit", scheduled_datetime: "2099-01-01T09:00:00Z", scheduled_display: "1 January 2099 09:00", status: "scheduled", status_label: "Scheduled", recommendation_id: "G1", can_request_change: true };
const FU = { follow_up_id: "T1", recommendation_id: "G1", status: "awaiting_patient", status_label: "Awaiting your reply", message: "Please book your screening.", due_date: null, due_date_display: null, is_overdue: false, reported_completion_pending_verification: false, created_at: "2026-11-10T00:00:00Z", updated_at: "2026-11-10T00:00:00Z", status_hint: "Please reply to let your care team know.", updated_display: "10 November 2026 00:00 UTC" };
const REQ = { request_id: "R9", request_type: "appointment_change", request_type_label: "Appointment change request", status: "acknowledged", status_label: "Received by your care team", status_hint: "Your care team is working on your request and will contact you.", follow_up_id: null, recommendation_id: null, appointment_id: "A1", change_action: "reschedule", change_action_label: "Reschedule", preferred_dates: [], preferred_time_of_day: null, message: "Evenings please", staff_response: "We will offer an evening slot.", created_at: "2026-11-10T00:00:00Z", created_display: "10 November 2026 00:00 UTC", updated_at: "2026-11-11T00:00:00Z", updated_display: "11 November 2026 00:00 UTC" };
const ANSWER = { ...L, recommendation_id: "G1", topic: "why", topic_label: "Why this is recommended", answer: ["Our records do not show this check.", "It was identified on 1 Nov 2026."], generation_mode: "deterministic_fallback", source_note: "Standard explanation built from the information in your record.", escalation: "If anything is unclear, please contact your care team.", disclaimer: "Not a diagnosis." };

const posts: { path: string; body: unknown }[] = [];
let linked = true;
let requests: unknown[] = [];
let assistantFails = 0;
let answer: Record<string, unknown> = ANSWER;

function backend(path: string, method: string, body: unknown): unknown {
  if (method === "POST") {
    posts.push({ path, body });
    if (path === "/portal/link") return { linked: true, patient_id: "SYNTH-PAT-000001", message: "Linked" };
    if (path.endsWith("/assistant")) {
      if (assistantFails > 0) {
        assistantFails -= 1;
        return { __status: 503, detail: "The service is temporarily unavailable." };
      }
      return answer;
    }
    if (path.endsWith("/cancel")) return { ...L, ...REQ, status: "cancelled", status_label: "Cancelled" };
    if (path.endsWith("/responses")) return { ...L, ...FU, history: [], confirmation: "Your reply was sent." };
    return { ...L, request_id: "R1", request_type: "appointment", request_type_label: "Appointment", status: "submitted", status_label: "Submitted", confirmation: "Request sent to your care team." };
  }
  if (path === "/portal/summary") return SUMMARY;
  if (path === "/portal/recommendations") return { ...L, total: 1, items: [REC] };
  if (path === "/portal/recommendations/G1") return { ...L, ...REC, evidence: ["No screening is recorded."], history: [], related_follow_up_ids: [], disclaimer: "Synthetic." };
  if (path === "/portal/appointments") return { ...L, total: 1, items: [APPT] };
  if (path === "/portal/referrals") return { ...L, total: 0, items: [] };
  if (path === "/portal/follow-ups") return { ...L, total: 1, items: [FU] };
  if (path === "/portal/follow-ups/T1") return { ...L, ...FU, history: [{ event_id: "E1", event_type: "created", label: "Message", created_at: FU.created_at, created_display: "10 Nov", message: "Please book your screening.", from_care_team: true }] };
  if (path === "/portal/requests") return { ...L, total: requests.length, items: requests };
  if (path === "/portal/health-summary") return { ...L, patient_id: "SYNTH-PAT-000001", history: [], events: [], is_synthetic: true, disclaimer: "Synthetic." };
  throw new Error(`unexpected ${method} ${path}`);
}

const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
  const u = new URL(url);
  const path = u.pathname.replace("/api/v1", "");
  const body = init?.body ? JSON.parse(String(init.body)) : undefined;
  const out = backend(path, init?.method ?? "GET", body) as { __status?: number };
  return new Response(JSON.stringify(out), { status: out.__status ?? 200, headers: { "Content-Type": "application/json" } });
});

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    state: { status: "signed_in", me: { user: { user_id: "U-P", full_name: "Demo Patient" }, patient_linked: linked, role: "PATIENT", permissions: ["patients.read_self"] } },
    signOut: vi.fn(),
    retry: vi.fn(),
  }),
}));

beforeEach(() => {
  posts.length = 0;
  linked = true;
  requests = [];
  assistantFails = 0;
  answer = ANSWER;
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(cleanup);

describe("PatientPortal", () => {
  it("greets the patient, shows their summary and calls only /portal endpoints", async () => {
    render(<PatientPortal />);
    expect(await screen.findByRole("heading", { name: "Hello, Noora" })).toBeTruthy();
    expect(await screen.findByText("Preventive check recommended")).toBeTruthy();
    expect(screen.getByText("1 January 2099 09:00")).toBeTruthy();
    expect(fetchMock.mock.calls.every(([u]) => new URL(String(u)).pathname.startsWith("/api/v1/portal/"))).toBe(true);
  });

  it("requests an appointment for a recommendation", async () => {
    render(<PatientPortal />);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Portal" })).getByRole("button", { name: /Recommended care/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Preventive check recommended/ }));
    expect(await screen.findByText("Contact your provider.", { exact: false })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Request an appointment for this/ }));
    const form = screen.getByRole("form", { name: "Appointment request" });
    fireEvent.change(within(form).getByLabelText("Preferred time of day"), { target: { value: "morning" } });
    fireEvent.click(within(form).getByRole("button", { name: "Send request" }));
    expect(await screen.findByText("Request sent to your care team.")).toBeTruthy();
    expect(posts).toEqual([{ path: "/portal/appointment-requests", body: { recommendation_id: "G1", follow_up_id: null, preferred_dates: [], preferred_time_of_day: "morning", message: null } }]);
  });

  it("replies to a care-team message", async () => {
    render(<PatientPortal />);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Portal" })).getByRole("button", { name: /Messages/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Please book your screening/ }));
    const form = await screen.findByRole("form", { name: "Reply" });
    expect((within(form).getByRole("button", { name: "Send reply" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(form).getByLabelText("I will book it"));
    fireEvent.click(within(form).getByRole("button", { name: "Send reply" }));
    expect(await screen.findByText("Your reply was sent.")).toBeTruthy();
    expect(posts).toEqual([{ path: "/portal/follow-ups/T1/responses", body: { response: "will_book", message: null } }]);
  });

  it("asks to reschedule an appointment", async () => {
    render(<PatientPortal />);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Portal" })).getByRole("button", { name: /Appointments/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Reschedule" }));
    fireEvent.click(screen.getByRole("button", { name: "Ask to reschedule" }));
    await waitFor(() => expect(posts).toEqual([{ path: "/portal/appointments/A1/change-requests", body: { action: "reschedule", message: null } }]));
  });

  it("explains a recommendation on a fixed topic and escalates to the care team", async () => {
    render(<PatientPortal />);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Portal" })).getByRole("button", { name: /Recommended care/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Preventive check recommended/ }));
    const panel = await screen.findByRole("region", { name: "Understand this recommendation" });
    fireEvent.click(within(panel).getByRole("button", { name: "Why is this recommended?" }));
    expect(await within(panel).findByText("Our records do not show this check.")).toBeTruthy();
    expect(within(panel).getByText("If anything is unclear, please contact your care team.")).toBeTruthy();
    expect(within(panel).getByText(/Standard explanation/)).toBeTruthy();
    expect(posts).toEqual([{ path: "/portal/recommendations/G1/assistant", body: { topic: "why" } }]);
    fireEvent.click(within(panel).getByRole("button", { name: /Ask your care team/ }));
    const form = within(panel).getByRole("form", { name: "Ask for help" });
    expect((within(form).getByLabelText("How can your care team help?") as HTMLTextAreaElement).value).toBe("Why this is recommended: ");
    fireEvent.click(within(form).getByRole("button", { name: "Send" }));
    expect(await within(panel).findByText("Request sent to your care team.")).toBeTruthy();
    expect(posts[1]).toEqual({ path: "/portal/assistance", body: { message: "Why this is recommended:", preferred_time_of_day: null } });
  });

  it("shows an error with retry when the assistant fails, and renders Arabic answers right-to-left", async () => {
    assistantFails = 1;
    answer = { ...ANSWER, locale: "ar", direction: "rtl", topic: "prepare_questions", topic_label: "أسئلة لمقدّم الرعاية الصحية", answer: ["هل هناك ما ينبغي أن أفعله للاستعداد؟"] };
    render(<PatientPortal />);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Portal" })).getByRole("button", { name: /Recommended care/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Preventive check recommended/ }));
    const panel = await screen.findByRole("region", { name: "Understand this recommendation" });
    fireEvent.click(within(panel).getByRole("button", { name: "Questions for my clinician" }));
    fireEvent.click(await within(panel).findByRole("button", { name: "Try again" }));
    const q = await within(panel).findByText("هل هناك ما ينبغي أن أفعله للاستعداد؟");
    expect(q.tagName).toBe("LI");
    const block = q.closest("[dir]") as HTMLElement;
    expect(block.getAttribute("dir")).toBe("rtl");
    expect(block.getAttribute("lang")).toBe("ar");
  });

  it("shows request status, care-team reply and what happens next, and withdraws inline", async () => {
    requests = [REQ];
    render(<PatientPortal />);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Portal" })).getByRole("button", { name: /My requests/ }));
    expect(await screen.findByText("Appointment change request · Reschedule")).toBeTruthy();
    expect(screen.getByText("We will offer an evening slot.")).toBeTruthy();
    expect(screen.getByText("Your care team is working on your request and will contact you.")).toBeTruthy();
    expect(screen.getByText(/Sent 10 November 2026 00:00 UTC · Updated 11 November 2026/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    expect(posts).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Yes, withdraw" }));
    await waitFor(() => expect(posts).toEqual([{ path: "/portal/requests/R9/cancel", body: undefined }]));
  });

  it("shows a useful empty state for requests and keeps navigation scrollable on small screens", async () => {
    render(<PatientPortal />);
    const nav = screen.getByRole("navigation", { name: "Portal" });
    expect(nav.className).toContain("overflow-x-auto");
    fireEvent.click(within(nav).getByRole("button", { name: /My requests/ }));
    expect(await screen.findByText("No requests yet")).toBeTruthy();
    expect(within(nav).getByRole("button", { name: /My requests/ }).getAttribute("aria-current")).toBe("page");
  });

  it("links an unlinked account with an invitation code and date of birth", async () => {
    linked = false;
    render(<PatientPortal />);
    const form = screen.getByRole("form", { name: "Link your record" });
    expect(within(screen.queryAllByRole("navigation")[0] ?? document.body).queryByRole("button", { name: /Recommended care/ })).toBeNull();
    fireEvent.change(within(form).getByLabelText("Invitation code"), { target: { value: "ABCD-1234" } });
    fireEvent.change(within(form).getByLabelText("Date of birth"), { target: { value: "1980-01-01" } });
    fireEvent.click(within(form).getByRole("button", { name: "Link my record" }));
    await waitFor(() => expect(posts).toEqual([{ path: "/portal/link", body: { invitation_code: "ABCD-1234", date_of_birth: "1980-01-01" } }]));
  });
});
