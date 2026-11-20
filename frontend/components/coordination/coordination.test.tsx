import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import {
  coordinationState,
  errorBody,
  fakeBackend,
  fakeFetchResponse,
  me,
  OUTREACH_DRAFT_BODY,
  resetCoordinationFixtures,
  ROLE_PERMISSIONS,
} from "@/test/fixtures";
import type { CareGapDetailOut, MeOut } from "@/lib/api/types";

const nav = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), personId: "SYNTH-PAT-1" }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/follow-up",
  useRouter: () => ({ push: nav.push, replace: nav.replace }),
  useParams: () => ({ personId: nav.personId }),
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
import { clearApiCache } from "@/lib/api/cache";
import { addDays, isoDate } from "@/lib/coordination/model";
import { clearRuleDetailCache } from "@/lib/people/use-people-data";
import { AppShell } from "@/components/shell/app-shell";
import { PersonProfile } from "@/components/people/profile/person-profile";
import { FollowUpWorkspace } from "./follow-up-workspace";
import { TaskDetail } from "./task-detail";
import { OutreachPanel } from "./outreach-panel";
import { AppointmentsWorkspace } from "./appointments-workspace";

type Role = keyof typeof ROLE_PERMISSIONS;
type Override = (u: URL, method: string, init?: RequestInit) => Response | null;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const pathOf = (u: URL) => decodeURIComponent(u.pathname.replace("/api/v1", ""));

let identity: MeOut;
let override: Override;
const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input);
  const u = new URL(url);
  const o = override(u, (init?.method ?? "GET").toUpperCase(), init);
  if (o) return o;
  if (pathOf(u) === "/me") return json(identity);
  return fakeFetchResponse(url, init);
});

/** Requests sent with `method` to exactly `path` (no query). */
const sent = (method: string, path: string) =>
  fetchMock.mock.calls.filter(([u, init]) => (init?.method ?? "GET").toUpperCase() === method && pathOf(new URL(String(u))) === path);
const bodies = (method: string, path: string) => sent(method, path).map(([, init]) => JSON.parse(String(init!.body)));
const reads = (path: string) => sent("GET", path).map(([u]) => new URL(String(u)).searchParams);
const lastRead = (path: string) => reads(path).at(-1)!;
/** Value of a `<Figure>` / count (`dt` label → first `dd`). */
const figure = (root: HTMLElement, label: string) => within(root).getAllByText(label)[0].closest("div")!.querySelector("dd")!.textContent;
const gapDetail = (id: string) => fakeBackend(`http://localhost:8000/api/v1/care-gaps/${id}`) as CareGapDetailOut;

function asRole(role: Role, ui: React.ReactNode) {
  identity = me(role, ROLE_PERMISSIONS[role], role === "POPULATION_HEALTH_MANAGER" ? "organization" : "assigned");
  return render(<AuthProvider>{ui}</AuthProvider>);
}

beforeEach(() => {
  resetCoordinationFixtures();
  clearApiCache();
  clearRuleDetailCache();
  override = () => null;
  identity = me("CARE_COORDINATOR", ROLE_PERMISSIONS.CARE_COORDINATOR, "assigned");
  nav.personId = "SYNTH-PAT-1";
  nav.push.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => setTimeout(cb, 0));
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  fetchMock.mockClear();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
});

/* ── Follow-up workspace ─────────────────────────────────────────────────────── */

describe("Follow-up workspace", () => {
  it("shows server-side counts and the active queue with overdue and internal-only states", async () => {
    render(<FollowUpWorkspace />);
    const overview = await screen.findByRole("region", { name: "Follow-up overview" });
    expect(figure(overview, "Active follow-ups")).toBe("3");
    expect(figure(overview, "Overdue")).toBe("1");
    expect(figure(overview, "Unassigned")).toBe("1");
    expect(within(overview).getByText("of 4 in scope · 1 completed · 0 cancelled")).toBeTruthy();

    const list = await screen.findByRole("list", { name: "Follow-up tasks" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    // Ordered by due date: the overdue, internal-only T-2 first.
    expect(rows[0].textContent).toMatch(/SYNTH-PAT-1.*Complete outstanding parts/);
    expect(within(rows[0]).getByText(/^\d+ days overdue$/)).toBeTruthy();
    expect(within(rows[0]).getByText("Internal only")).toBeTruthy();
    expect(within(rows[0]).getByText("Unassigned")).toBeTruthy();
    expect(within(rows[1]).getByRole("link").getAttribute("href")).toBe("/follow-up/T-1");
    expect(within(rows[1]).queryByText("Internal only")).toBeNull();
    expect(await within(rows[1]).findByText("Amal Coordinator (synthetic) (you)")).toBeTruthy();
    expect(lastRead("/follow-up-tasks").get("active")).toBe("true");
  });

  it("lists closed follow-ups as completed, never overdue", async () => {
    render(<FollowUpWorkspace />);
    await screen.findByRole("list", { name: "Follow-up tasks" });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "closed" } });
    await waitFor(() => expect(lastRead("/follow-up-tasks").get("active")).toBe("false"));
    const list = await screen.findByRole("list", { name: "Follow-up tasks" });
    await within(list).findByText("SYNTH-PAT-4");
    const [row] = within(list).getAllByRole("listitem");
    expect(within(row).getByText("Completed")).toBeTruthy();
    expect(within(row).getByText("Due 1 Oct 2026")).toBeTruthy();
    expect(row.textContent).not.toMatch(/overdue/);
  });

  it("sends each filter to the API as the backend parameter", async () => {
    render(<FollowUpWorkspace />);
    await screen.findByRole("list", { name: "Follow-up tasks" });
    const today = isoDate(new Date());
    const change = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

    change("Priority", "urgent");
    await waitFor(() => expect(lastRead("/follow-up-tasks").get("priority")).toBe("urgent"));
    await waitFor(() => expect(lastRead("/follow-up-tasks/summary").get("priority")).toBe("urgent"));

    change("Assigned to", "unassigned");
    await waitFor(() => expect(lastRead("/follow-up-tasks").get("assigned_to")).toBe("unassigned"));

    change("Programme", "ifhas");
    await waitFor(() => expect(lastRead("/follow-up-tasks").get("pathway")).toBe("ifhas"));

    change("Region", "1");
    await waitFor(() => expect(lastRead("/follow-up-tasks").get("region_id")).toBe("1"));

    change("Due", "soon");
    await waitFor(() => expect(lastRead("/follow-up-tasks").get("due_before")).toBe(addDays(today, 7)));
    expect(lastRead("/follow-up-tasks").get("due_after")).toBe(today);
    expect(lastRead("/follow-up-tasks").get("overdue")).toBeNull();

    change("Due", "overdue");
    await waitFor(() => expect(lastRead("/follow-up-tasks").get("overdue")).toBe("true"));
    expect(lastRead("/follow-up-tasks").get("due_after")).toBeNull();

    change("Status", "in_progress");
    await waitFor(() => expect(lastRead("/follow-up-tasks").get("status")).toBe("in_progress"));
    expect(lastRead("/follow-up-tasks").get("active")).toBeNull();

    // The overview counts follow the scope filters only, never the status or due window.
    const summary = lastRead("/follow-up-tasks/summary");
    expect(summary.get("region_id")).toBe("1");
    expect(summary.get("pathway")).toBe("ifhas");
    expect(summary.get("assigned_to")).toBe("unassigned");
    for (const key of ["status", "active", "overdue", "due_after", "due_before"]) expect(summary.get(key)).toBeNull();

    expect(await screen.findByText("No follow-ups match")).toBeTruthy();
    expect(screen.getByText("Try widening the filters.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Reset filters/ }));
    await waitFor(() => expect([...lastRead("/follow-up-tasks").keys()].sort()).toEqual(["active", "limit", "offset"]));
  });

  it("filters the queue from the overview figures", async () => {
    render(<FollowUpWorkspace />);
    let overview = await screen.findByRole("region", { name: "Follow-up overview" });
    await screen.findByRole("list", { name: "Follow-up tasks" });

    fireEvent.click(within(overview).getByRole("button", { name: /Overdue/ }));
    await waitFor(() => expect(lastRead("/follow-up-tasks").get("overdue")).toBe("true"));
    expect(lastRead("/follow-up-tasks").get("active")).toBe("true");
    expect(within(overview).getByRole("button", { name: /Overdue/ }).getAttribute("aria-pressed")).toBe("true");
    expect((screen.getByLabelText("Due") as HTMLSelectElement).value).toBe("overdue");
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Follow-up tasks" })).getAllByRole("listitem")).toHaveLength(1));

    fireEvent.click(within(overview).getByRole("button", { name: /^Unassigned/ }));
    await waitFor(() => expect(lastRead("/follow-up-tasks").get("assigned_to")).toBe("unassigned"));

    fireEvent.click(within(overview).getByRole("button", { name: /^Urgent/ }));
    await waitFor(() => expect(lastRead("/follow-up-tasks/summary").get("priority")).toBe("urgent"));
    expect(lastRead("/follow-up-tasks").get("priority")).toBe("urgent");

    overview = await screen.findByRole("region", { name: "Follow-up overview" });
    fireEvent.click(within(overview).getByRole("button", { name: /^Completed/ }));
    await waitFor(() => expect(lastRead("/follow-up-tasks").get("status")).toBe("completed"));
    expect(lastRead("/follow-up-tasks").get("overdue")).toBeNull();
    expect(lastRead("/follow-up-tasks").get("active")).toBeNull();
  });

  it("creates a follow-up with priority, internal note and portal visibility, then opens it", async () => {
    render(<FollowUpWorkspace />);
    await screen.findByRole("list", { name: "Follow-up tasks" });
    fireEvent.click(screen.getByRole("button", { name: /New follow-up/ }));
    const form = screen.getByRole("form", { name: "New follow-up" });
    fireEvent.change(within(form).getByLabelText("Synthetic person ID"), { target: { value: "SYNTH-PAT-1" } });
    fireEvent.click(within(form).getByRole("button", { name: /Look up/ }));

    fireEvent.change(await within(form).findByLabelText(/^Care gap/), { target: { value: "G1" } });
    const assignee = within(form).getByLabelText(/^Assigned coordinator/) as HTMLSelectElement;
    expect(assignee.value).toBe("U-COORD");
    // Only members the backend says can be assigned are offered.
    expect(within(assignee).queryByRole("option", { name: /Sara Manager/ })).toBeNull();
    fireEvent.change(assignee, { target: { value: "U-CLIN" } });
    fireEvent.change(within(form).getByLabelText("Due date"), { target: { value: "2099-03-01" } });
    fireEvent.click(within(within(form).getByRole("group", { name: "Coordination priority" })).getByRole("button", { name: "Urgent" }));
    expect((within(form).getByLabelText("Approved message template") as HTMLSelectElement).value).toBe("screening_invitation");
    fireEvent.click(within(form).getByLabelText(/Show in the patient portal/));
    fireEvent.change(within(form).getByLabelText(/Internal note \(staff only\)/), { target: { value: "Call after 5pm" } });
    fireEvent.click(within(form).getByRole("button", { name: "Create follow-up" }));

    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/follow-up/T-NEW-1"));
    expect(bodies("POST", "/follow-up-tasks")).toEqual([
      {
        patient_id: "SYNTH-PAT-1",
        care_gap_id: "G1",
        assigned_to_user_id: "U-CLIN",
        due_date: "2099-03-01",
        message_key: "screening_invitation",
        priority: "urgent",
        patient_visible: false,
        staff_note: "Call after 5pm",
        language: null,
      },
    ]);
    expect(reads("/care-team").some((q) => q.get("patient_id") === "SYNTH-PAT-1")).toBe(true);
  });

  it("refetches the queue and the counts after a write", async () => {
    render(<FollowUpWorkspace />);
    await screen.findByRole("list", { name: "Follow-up tasks" });
    const summaries = reads("/follow-up-tasks/summary").length;
    const lists = reads("/follow-up-tasks").length;

    fireEvent.click(screen.getByRole("button", { name: /New follow-up/ }));
    const form = screen.getByRole("form", { name: "New follow-up" });
    fireEvent.change(within(form).getByLabelText("Synthetic person ID"), { target: { value: "SYNTH-PAT-2" } });
    fireEvent.click(within(form).getByRole("button", { name: /Look up/ }));
    fireEvent.click(await within(form).findByRole("button", { name: "Create follow-up" }));

    await waitFor(() => expect(reads("/follow-up-tasks/summary").length).toBeGreaterThan(summaries));
    await waitFor(() => expect(reads("/follow-up-tasks").length).toBeGreaterThan(lists));
    const list = await screen.findByRole("list", { name: "Follow-up tasks" });
    expect(await within(list).findByText("SYNTH-PAT-2")).toBeTruthy();
    const overview = await screen.findByRole("region", { name: "Follow-up overview" });
    await waitFor(() => expect(figure(overview, "Active follow-ups")).toBe("4"));
  });

  it("shows permission notices for 403 responses, never zero counts", async () => {
    override = (u) => (/\/follow-up-tasks(\/summary)?$/.test(u.pathname) ? json(errorBody("forbidden", "Forbidden."), 403) : null);
    render(<FollowUpWorkspace />);
    expect(await screen.findByText("Follow-up counts are not available for your role")).toBeTruthy();
    expect(await screen.findByText("Follow-up tasks are not available for your role")).toBeTruthy();
    expect(screen.getByText("Workload figures are not available for your role")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Follow-up overview" })).toBeNull();
    expect(screen.queryByText("Active follow-ups")).toBeNull();
    expect(screen.queryByText("No follow-ups match")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

/* ── Follow-up detail ────────────────────────────────────────────────────────── */

describe("Follow-up detail", () => {
  const actions = () => screen.getByRole("group", { name: "Follow-up action" });

  it("changes the status, then assignment, due date and priority through PATCH", async () => {
    render(<TaskDetail taskId="T-1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Screening invitation" })).toBeTruthy();
    fireEvent.click(within(actions()).getByRole("button", { name: "Status & assignment" }));
    // Already awaiting the patient: that move is not offered again.
    expect(screen.queryByRole("button", { name: "Awaiting patient" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Start working (in progress)" }));
    await waitFor(() => expect(bodies("PATCH", "/follow-up-tasks/T-1")).toEqual([{ status: "in_progress" }]));

    // The write invalidates coordination reads: the task is fetched again and shows the new status.
    await waitFor(() => expect(reads("/follow-up-tasks/T-1").length).toBeGreaterThanOrEqual(2));
    const status = await screen.findByRole("region", { name: "Follow-up status" });
    expect(await within(status).findByText("In progress")).toBeTruthy();

    fireEvent.click(within(actions()).getByRole("button", { name: "Status & assignment" }));
    const form = screen.getByRole("form", { name: "Assignment, due date and priority" });
    expect(within(form).getByRole("button", { name: "Save changes" })).toHaveProperty("disabled", true);
    await within(form).findByRole("option", { name: /Omar Clinician/ });
    fireEvent.change(within(form).getByLabelText("Assigned coordinator"), { target: { value: "U-CLIN" } });
    fireEvent.change(within(form).getByLabelText("Due date"), { target: { value: "2099-05-05" } });
    fireEvent.change(within(form).getByLabelText("Priority"), { target: { value: "urgent" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(bodies("PATCH", "/follow-up-tasks/T-1")).toHaveLength(2));
    expect(bodies("PATCH", "/follow-up-tasks/T-1")[1]).toEqual({ assigned_to_user_id: "U-CLIN", due_date: "2099-05-05", priority: "urgent" });
  });

  it("records a contact attempt and shows it in the history", async () => {
    render(<TaskDetail taskId="T-1" />);
    const form = await screen.findByRole("form", { name: "Record contact attempt" });
    fireEvent.change(within(form).getByLabelText("Channel"), { target: { value: "sms" } });
    fireEvent.change(within(form).getByLabelText("Outcome"), { target: { value: "left_message" } });
    fireEvent.change(within(form).getByLabelText(/Note \(internal\)/), { target: { value: "Left voicemail" } });
    fireEvent.click(within(form).getByRole("button", { name: "Record contact attempt" }));
    await waitFor(() =>
      expect(bodies("POST", "/follow-up-tasks/T-1/contact-attempts")).toEqual([{ channel: "sms", outcome: "left_message", note: "Left voicemail" }])
    );
    expect(await screen.findByText("Contact attempt · SMS · Left a message")).toBeTruthy();
  });

  it("shows the backend's reason when a contact attempt is refused for consent (422)", async () => {
    const reason = "Contact is not permitted: the patient withdrew contact consent.";
    override = (u, method) =>
      method === "POST" && u.pathname.endsWith("/contact-attempts") ? json(errorBody("contact_not_permitted", reason), 422) : null;
    render(<TaskDetail taskId="T-1" />);
    const form = await screen.findByRole("form", { name: "Record contact attempt" });
    fireEvent.click(within(form).getByRole("button", { name: "Record contact attempt" }));
    const alert = await within(form).findByRole("alert");
    expect(alert.textContent).toContain(reason);
    expect(alert.textContent).not.toContain("422");
    // A refused write invalidates nothing.
    expect(reads("/follow-up-tasks/T-1")).toHaveLength(1);
  });

  it("completes only with documented evidence: completion_documented first, then /complete", async () => {
    render(<TaskDetail taskId="T-1" />);
    await screen.findByRole("heading", { level: 1, name: "Screening invitation" });
    fireEvent.click(within(actions()).getByRole("button", { name: "Complete" }));
    const form = await screen.findByRole("form", { name: "Document completion" });
    const submit = within(form).getByRole("button", { name: "Document completion and close" });
    expect(submit).toHaveProperty("disabled", true);
    fireEvent.change(within(form).getByLabelText(/^Evidence record ID/), { target: { value: "SYNTH-SCR-77" } });
    fireEvent.change(within(form).getByLabelText("Note (internal)"), { target: { value: "Verified record" } });
    fireEvent.click(submit);

    await waitFor(() => expect(sent("POST", "/follow-up-tasks/T-1/complete")).toHaveLength(1));
    expect(bodies("POST", "/care-gaps/G1/follow-ups")).toEqual([
      { event_type: "completion_documented", close_gap: true, documented_evidence: true, evidence_reference: "SYNTH-SCR-77", note: "Verified record" },
    ]);
    expect(bodies("POST", "/follow-up-tasks/T-1/complete")).toEqual([{ completion_follow_up_id: "FU-NEW-1" }]);
    const order = fetchMock.mock.calls.map(([u]) => pathOf(new URL(String(u))));
    expect(order.indexOf("/follow-up-tasks/T-1/complete")).toBeGreaterThan(order.indexOf("/care-gaps/G1/follow-ups"));
    expect(await screen.findByText("This follow-up is closed")).toBeTruthy();
  });

  it("does not complete the task when the backend refuses the evidence", async () => {
    const reason = "The evidence record does not satisfy the rule for this care gap.";
    override = (u, method) => (method === "POST" && u.pathname.endsWith("/care-gaps/G1/follow-ups") ? json(errorBody("evidence_mismatch", reason), 422) : null);
    render(<TaskDetail taskId="T-1" />);
    await screen.findByRole("heading", { level: 1, name: "Screening invitation" });
    fireEvent.click(within(actions()).getByRole("button", { name: "Complete" }));
    const form = await screen.findByRole("form", { name: "Document completion" });
    fireEvent.change(within(form).getByLabelText(/^Evidence record ID/), { target: { value: "SYNTH-SCR-WRONG" } });
    fireEvent.click(within(form).getByRole("button", { name: "Document completion and close" }));
    expect(await screen.findByText(reason)).toBeTruthy();
    expect(sent("POST", "/follow-up-tasks/T-1/complete")).toHaveLength(0);
  });

  it("completes a follow-up without a care gap directly", async () => {
    render(<TaskDetail taskId="T-4" />);
    await screen.findByRole("heading", { level: 1, name: "General check-in" });
    fireEvent.click(within(actions()).getByRole("button", { name: "Complete" }));
    expect(screen.getByText(/completing it closes only the task/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Complete follow-up" }));
    await waitFor(() => expect(bodies("POST", "/follow-up-tasks/T-4/complete")).toEqual([{ completion_follow_up_id: null }]));
  });

  it("renders an overdue internal-only follow-up", async () => {
    render(<TaskDetail taskId="T-2" />);
    const status = await screen.findByRole("region", { name: "Follow-up status" });
    expect(within(status).getByText(/^\d+ days overdue$/)).toBeTruthy();
    expect(within(status).getByText("Internal only")).toBeTruthy();
    expect(within(status).getByText("Open")).toBeTruthy();
    expect(screen.getByText("Internal follow-up — nothing appears in the patient portal.")).toBeTruthy();
    expect(within(actions()).queryByRole("button", { name: "Message patient" })).toBeNull();
  });

  it("renders a completed follow-up as closed, with its documented completion", async () => {
    render(<TaskDetail taskId="T-3" />);
    expect(await screen.findByText("This follow-up is closed")).toBeTruthy();
    expect(screen.getByText(/with documented completion FU-DONE-1\./)).toBeTruthy();
    const status = screen.getByRole("region", { name: "Follow-up status" });
    expect(within(status).getByText("Completed")).toBeTruthy();
    expect(within(status).getByText("Due 1 Oct 2026")).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Follow-up action" })).toBeNull();
    expect(await screen.findByText("Drafting is available only while the care gap and the follow-up are open.")).toBeTruthy();
  });
});

/* ── Outreach ────────────────────────────────────────────────────────────────── */

describe("Outreach draft review", () => {
  it("drafts, lets a person edit and approve, and reports a simulated attempt — never sent", async () => {
    const { container } = render(
      <OutreachPanel patientId="SYNTH-PAT-1" gap={gapDetail("G1")} preferredChannel="sms" preferredLanguage="en" team={null} open />
    );
    expect(screen.getByText(/Approved · Simulated — not sent/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Prepare draft/ }));
    const message = (await screen.findByLabelText(/Message for review/)) as HTMLTextAreaElement;
    expect(bodies("POST", "/outreach/draft")).toEqual([
      { patient_id: "SYNTH-PAT-1", rule_id: "IFHAS-PKG-ORAL", care_gap_id: "G1", channel: "sms", language: "en", tone: "supportive" },
    ]);
    expect(message.value).toBe(OUTREACH_DRAFT_BODY);
    expect(screen.getByText("Draft · awaiting human review")).toBeTruthy();

    fireEvent.change(message, { target: { value: "Edited: please book your oral health check." } });
    fireEvent.click(screen.getByRole("button", { name: "Approve (simulated, not sent)" }));
    const done = await screen.findByText(/Approved by you \(edited\)/);
    expect(bodies("POST", "/outreach/draft/review")).toEqual([
      {
        draft_audit_id: "AUD-DRAFT-1",
        patient_id: "SYNTH-PAT-1",
        rule_id: "IFHAS-PKG-ORAL",
        care_gap_id: "G1",
        channel: "sms",
        language: "en",
        decision: "approved",
        final_message: "Edited: please book your oral health check.",
      },
    ]);
    const confirmation = done.closest("[role=status]") as HTMLElement;
    expect(within(confirmation).getByText("Simulated — not sent")).toBeTruthy();
    expect(confirmation.textContent).toMatch(/Delivered: no/);
    expect(container.textContent).not.toMatch(/\bSent\b/);
    expect(container.textContent).not.toMatch(/Delivered: yes/);
    expect(screen.queryByLabelText(/Message for review/)).toBeNull();
  });

  it("sends the chosen channel, language and tone", async () => {
    render(<OutreachPanel patientId="SYNTH-PAT-1" gap={gapDetail("G1")} preferredChannel="email" preferredLanguage="ar" team={null} open />);
    expect((screen.getByLabelText("Channel") as HTMLSelectElement).value).toBe("email");
    fireEvent.click(within(screen.getByRole("group", { name: "Draft tone" })).getByRole("button", { name: "Neutral" }));
    fireEvent.click(screen.getByRole("button", { name: /Prepare draft/ }));
    await waitFor(() => expect(bodies("POST", "/outreach/draft")).toHaveLength(1));
    expect(bodies("POST", "/outreach/draft")[0]).toMatchObject({ channel: "email", language: "ar", tone: "neutral" });
  });

  it("explains a blocked draft and offers no approval", async () => {
    render(<OutreachPanel patientId="SYNTH-PAT-1" gap={gapDetail("G2")} preferredChannel="sms" preferredLanguage="en" team={null} open />);
    fireEvent.click(screen.getByRole("button", { name: /Prepare draft/ }));
    expect(await screen.findByText("No draft — outreach is blocked.")).toBeTruthy();
    expect(screen.getByText(/No current contact consent is recorded for this programme\./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
    expect(screen.queryByLabelText(/Message for review/)).toBeNull();
    expect(sent("POST", "/outreach/draft/review")).toHaveLength(0);
  });
});

/* ── Appointments & referrals ────────────────────────────────────────────────── */

describe("Appointments workspace", () => {
  const tab = (name: string) => fireEvent.click(within(screen.getByRole("group", { name: "Coordination view" })).getByRole("button", { name }));

  it("shows exact counts from one-row queries", async () => {
    render(<AppointmentsWorkspace />);
    const overview = await screen.findByRole("region", { name: "Appointments overview" });
    expect(figure(overview, "Upcoming appointments")).toBe("1");
    expect(figure(overview, "Pending requests")).toBe("2");
    expect(figure(overview, "Attended")).toBe("1");
    expect(figure(overview, "Awaiting outcome")).toBe("0");
    const counts = reads("/appointments");
    expect(counts.length).toBeGreaterThanOrEqual(9);
    expect(counts.every((q) => q.get("limit") === "1")).toBe(true);
  });

  it("acknowledges a request with a patient-visible reply and an internal note", async () => {
    render(<AppointmentsWorkspace />);
    const list = await screen.findByRole("list", { name: "Patient requests" });
    fireEvent.click(within(list).getByRole("button", { name: /SYNTH-PAT-1/ }));
    fireEvent.change(within(list).getByLabelText(/Reply to the patient/), { target: { value: "We will call you tomorrow." } });
    fireEvent.change(within(list).getByLabelText(/Internal note \(staff only\)/), { target: { value: "Prefers mornings" } });
    fireEvent.click(within(list).getByRole("button", { name: "Acknowledge & reply" }));
    await waitFor(() =>
      expect(bodies("PATCH", "/patient-requests/R-1")).toEqual([
        { status: "acknowledged", staff_response: "We will call you tomorrow.", internal_note: "Prefers mornings" },
      ])
    );
    // Refetched after the write: the request has left the "New" queue.
    expect(await screen.findByText("No new requests are waiting.")).toBeTruthy();
  });

  it("records an appointment from a request, then marks the request scheduled with it", async () => {
    render(<AppointmentsWorkspace />);
    const list = await screen.findByRole("list", { name: "Patient requests" });
    fireEvent.click(within(list).getByRole("button", { name: /SYNTH-PAT-1/ }));
    fireEvent.click(within(list).getByRole("button", { name: "Record appointment" }));
    const form = within(list).getByRole("form", { name: "Record appointment" });
    await within(form).findByRole("option", { name: /Synthetic Health Centre A/ });
    await within(form).findByRole("option", { name: /IFHAS-PKG-ORAL · No documented screening/ });
    expect((within(form).getByLabelText("Date and time (UTC)") as HTMLInputElement).value).toBe("2026-12-03T09:00");
    fireEvent.change(within(form).getByLabelText(/Facility service profile/), { target: { value: "FSP-1" } });
    fireEvent.click(within(form).getByRole("button", { name: /Record appointment and update request/ }));

    await waitFor(() => expect(bodies("PATCH", "/patient-requests/R-1")).toEqual([{ status: "scheduled", appointment_id: "APT-NEW-1" }]));
    expect(bodies("POST", "/appointments")).toEqual([
      {
        patient_id: "SYNTH-PAT-1",
        profile_id: "FSP-1",
        care_gap_id: "G1",
        appointment_type: "ifhas_screening",
        scheduled_datetime: "2026-12-03T09:00:00.000Z",
        slot_type: "weekday",
        note: null,
      },
    ]);
    const order = fetchMock.mock.calls.map(([u, init]) => `${(init?.method ?? "GET").toUpperCase()} ${pathOf(new URL(String(u)))}`);
    expect(order.indexOf("PATCH /patient-requests/R-1")).toBeGreaterThan(order.indexOf("POST /appointments"));
    expect(coordinationState().requests.find((r) => r.request_id === "R-1")!.status).toBe("scheduled");
  });

  it("reschedules and then records attendance with the right PATCH bodies", async () => {
    render(<AppointmentsWorkspace />);
    tab("Appointments");
    const list = await screen.findByRole("list", { name: "Appointments" });
    const listQuery = reads("/appointments").filter((q) => q.get("limit") !== "1").at(-1)!;
    expect(listQuery.get("status_group")).toBe("active");
    expect(listQuery.get("order")).toBe("asc");
    expect(listQuery.get("scheduled_from")).toBeTruthy();

    fireEvent.click(within(list).getByRole("button", { name: /SYNTH-PAT-1/ }));
    expect(await within(list).findByText("Created · Recorded")).toBeTruthy();
    expect(within(list).getByText("Booked by phone")).toBeTruthy();
    let form = within(list).getByRole("form", { name: "Update appointment" });
    fireEvent.change(within(form).getByLabelText("New status"), { target: { value: "rescheduled" } });
    fireEvent.change(within(form).getByLabelText("New date and time (UTC)"), { target: { value: "2099-12-05T14:30" } });
    fireEvent.change(within(form).getByLabelText("Note (staff history)"), { target: { value: "Patient asked for afternoon" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(bodies("PATCH", "/appointments/A-1")).toEqual([
        { status: "rescheduled", scheduled_datetime: "2099-12-05T14:30:00.000Z", note: "Patient asked for afternoon" },
      ])
    );

    await waitFor(() =>
      expect(within(screen.getByRole("list", { name: "Appointments" })).getByRole("button", { name: /SYNTH-PAT-1.*Rescheduled/ })).toBeTruthy()
    );
    // The row stays expanded across the refetch (last data kept while reloading).
    const refreshed = screen.getByRole("list", { name: "Appointments" });
    form = await within(refreshed).findByRole("form", { name: "Update appointment" });
    fireEvent.change(within(form).getByLabelText("New status"), { target: { value: "attended" } });
    expect(within(form).getByText(/Attendance does not close the care gap/)).toBeTruthy();
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(bodies("PATCH", "/appointments/A-1")).toHaveLength(2));
    expect(bodies("PATCH", "/appointments/A-1")[1]).toEqual({ status: "attended", note: null });
  });

  it("requires the initiated and completed dates for referral updates", async () => {
    render(<AppointmentsWorkspace />);
    tab("Referrals");
    const list = await screen.findByRole("list", { name: "Referrals" });
    fireEvent.click(within(list).getByRole("button", { name: /REF-1/ }));
    let form = within(list).getByRole("form", { name: "Update referral" });
    expect(within(form).queryByLabelText("Initiated on")).toBeNull();
    fireEvent.change(within(form).getByLabelText("New status"), { target: { value: "initiated" } });
    const initiated = within(form).getByLabelText("Initiated on") as HTMLInputElement;
    expect(initiated.required).toBe(true);
    expect(initiated.min).toBe("2026-11-01");
    expect(within(form).queryByLabelText("Completed on")).toBeNull();
    fireEvent.change(initiated, { target: { value: "2026-11-20" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(bodies("PATCH", "/referrals/REF-1")).toEqual([{ status: "initiated", initiated_date: "2026-11-20", note: null }]));

    await waitFor(() =>
      expect(within(screen.getByRole("list", { name: "Referrals" })).getByRole("button", { name: /REF-1.*Initiated/ })).toBeTruthy()
    );
    // The row stays expanded across the refetch (last data kept while reloading).
    const refreshed = screen.getByRole("list", { name: "Referrals" });
    form = await within(refreshed).findByRole("form", { name: "Update referral" });
    fireEvent.change(within(form).getByLabelText("New status"), { target: { value: "completed" } });
    expect((within(form).getByLabelText("Initiated on") as HTMLInputElement).value).toBe("2026-11-20");
    const completed = within(form).getByLabelText("Completed on") as HTMLInputElement;
    expect(completed.required).toBe(true);
    expect(completed.min).toBe("2026-11-20");
    fireEvent.change(completed, { target: { value: "2026-11-25" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(bodies("PATCH", "/referrals/REF-1")).toHaveLength(2));
    expect(bodies("PATCH", "/referrals/REF-1")[1]).toEqual({ status: "completed", initiated_date: "2026-11-20", completed_date: "2026-11-25", note: null });
  });

  it("shows a permission notice when the appointments API answers 403", async () => {
    override = (u) => (u.pathname.endsWith("/appointments") ? json(errorBody("forbidden", "Forbidden."), 403) : null);
    render(<AppointmentsWorkspace />);
    expect(await screen.findByText("Appointment counts are not available for your role")).toBeTruthy();
    expect(screen.queryByText("Upcoming appointments")).toBeNull();
    expect(screen.queryByRole("region", { name: "Appointments overview" })).toBeNull();
  });
});

/* ── Patient profile ─────────────────────────────────────────────────────────── */

describe("Profile coordination section", () => {
  const coordination = async () => {
    render(<PersonProfile />);
    await screen.findByRole("heading", { name: "Overview", level: 2 });
    return screen.getByRole("region", { name: "Care Coordination" });
  };

  it("shows one dated timeline with Internal badges and the not-proof-of-completion note", async () => {
    const section = await coordination();
    const timeline = await within(section).findByRole("list", { name: "Coordination timeline" });
    const entry = (title: string | RegExp) => within(timeline).getByText(title).closest("li")!;

    expect(within(entry("Internal note")).getByText("Internal")).toBeTruthy();
    expect(within(entry("Internal note")).getByText("Prefers evening calls")).toBeTruthy();
    expect(within(entry("Contact attempt · Phone call · No answer")).getByText("Internal")).toBeTruthy();
    expect(within(entry("Outreach reviewed and approved · Simulated — not sent")).getByText("Internal")).toBeTruthy();
    expect(within(entry("Appointment request · New")).getByText("Visible to patient")).toBeTruthy();
    const appointment = entry(/^Appointment recorded · Recorded/);
    expect(within(appointment).queryByText("Internal")).toBeNull();
    expect(within(appointment).queryByText("Visible to patient")).toBeNull();
    expect(within(timeline).getByText("Referral to Gastroenterology · Pending")).toBeTruthy();
    expect(within(timeline).getByText("Care gap identified · IFHAS-PKG-ORAL")).toBeTruthy();
    expect(within(timeline).queryByText(/care gap closed/)).toBeNull();
    expect(within(section).getByText(/not proof that preventive care was completed/)).toBeTruthy();

    expect(figure(section, "Active follow-ups")).toBe("2");
    expect(figure(section, "Open requests")).toBe("1");
    expect(figure(section, "Upcoming appointments")).toBe("1");
    expect(figure(section, "Active referrals")).toBe("1");
    expect(reads("/follow-up-tasks").at(-1)!.get("patient_id")).toBe("SYNTH-PAT-1");
    expect(reads("/follow-up-tasks/T-1")).toHaveLength(1);
    expect(reads("/follow-up-tasks/T-2")).toHaveLength(1);

    fireEvent.click(within(within(section).getByRole("group", { name: "Timeline lane" })).getByRole("button", { name: "Outreach" }));
    const lane = within(section).getByRole("list", { name: "Coordination timeline" });
    expect(within(lane).getAllByRole("listitem")).toHaveLength(1);
  });

  it("creates a follow-up for the person and refreshes the section", async () => {
    const section = await coordination();
    await within(section).findByRole("list", { name: "Coordination timeline" });
    fireEvent.click(within(section).getByRole("button", { name: /New follow-up/ }));
    const form = within(section).getByRole("form", { name: "New follow-up" });
    expect((within(form).getByLabelText("Synthetic person ID") as HTMLInputElement).readOnly).toBe(true);
    fireEvent.click(await within(form).findByRole("button", { name: "Create follow-up" }));
    expect(await within(section).findByText(/Follow-up created\./)).toBeTruthy();
    expect(within(section).getByRole("link", { name: "Open it" }).getAttribute("href")).toBe("/follow-up/T-NEW-1");
    await waitFor(() => expect(figure(section, "Active follow-ups")).toBe("3"));
    expect(bodies("POST", "/follow-up-tasks")[0]).toMatchObject({ patient_id: "SYNTH-PAT-1", priority: "routine", patient_visible: true });
  });
});

/* ── Roles ───────────────────────────────────────────────────────────────────── */

describe("Role-based coordination views", () => {
  it("POPULATION_HEALTH_MANAGER cannot record appointments or draft outreach", async () => {
    asRole("POPULATION_HEALTH_MANAGER", <AppointmentsWorkspace />);
    await screen.findByRole("region", { name: "Appointments overview" });
    const tabs = screen.getByRole("group", { name: "Coordination view" });
    expect(within(tabs).getAllByRole("button").map((b) => b.textContent)).toEqual(["Patient requests", "Appointments", "Referrals"]);

    fireEvent.click(within(tabs).getByRole("button", { name: "Appointments" }));
    const list = await screen.findByRole("list", { name: "Appointments" });
    expect(screen.queryByRole("button", { name: /Record appointment/ })).toBeNull();
    fireEvent.click(within(list).getByRole("button", { name: /SYNTH-PAT-1/ }));
    expect(await within(list).findByText("Updating appointments is not available for your role")).toBeTruthy();

    fireEvent.click(within(tabs).getByRole("button", { name: "Patient requests" }));
    const requests = await screen.findByRole("list", { name: "Patient requests" });
    fireEvent.click(within(requests).getByRole("button", { name: /SYNTH-PAT-1/ }));
    expect(within(requests).getByRole("button", { name: "Acknowledge" })).toBeTruthy();
    expect(within(requests).queryByRole("button", { name: "Record appointment" })).toBeNull();
  });

  it("POPULATION_HEALTH_MANAGER sees no outreach drafting and cannot document completion", async () => {
    asRole("POPULATION_HEALTH_MANAGER", <TaskDetail taskId="T-1" />);
    const actions = await screen.findByRole("group", { name: "Follow-up action" });
    expect(await screen.findByText("Outreach drafting is not available for your role")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Prepare draft/ })).toBeNull();
    fireEvent.click(within(actions).getByRole("button", { name: "Complete" }));
    expect(await screen.findByText("Documenting completion needs clinical completion rights")).toBeTruthy();
    expect(screen.queryByRole("form", { name: "Document completion" })).toBeNull();
  });

  it("CLINICIAN has no Patient requests tab and reads follow-ups without update actions", async () => {
    asRole("CLINICIAN", <AppointmentsWorkspace />);
    const overview = await screen.findByRole("region", { name: "Appointments overview" });
    expect(figure(overview, "Pending requests")).toBe("—");
    expect(within(overview).getByText("needs patient_requests.manage")).toBeTruthy();
    const tabs = screen.getByRole("group", { name: "Coordination view" });
    expect(within(tabs).getAllByRole("button").map((b) => b.textContent)).toEqual(["Appointments", "Referrals"]);
    expect(sent("GET", "/patient-requests")).toHaveLength(0);
    cleanup();

    asRole("CLINICIAN", <TaskDetail taskId="T-1" />);
    expect(await screen.findByText("Updating follow-ups is not available for your role")).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Follow-up action" })).toBeNull();
    expect(await screen.findByText("Outreach drafting is not available for your role")).toBeTruthy();
  });

  it("CARE_COORDINATOR sees every coordination action", async () => {
    asRole("CARE_COORDINATOR", <TaskDetail taskId="T-1" />);
    const actions = await screen.findByRole("group", { name: "Follow-up action" });
    expect(within(actions).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Contact attempt",
      "Status & assignment",
      "Internal note",
      "Message patient",
      "Escalate",
      "Complete",
    ]);
    expect(await screen.findByRole("button", { name: /Prepare draft/ })).toBeTruthy();
    cleanup();

    asRole("CARE_COORDINATOR", <AppointmentsWorkspace />);
    await screen.findByRole("region", { name: "Appointments overview" });
    const tabs = screen.getByRole("group", { name: "Coordination view" });
    expect(within(tabs).getAllByRole("button").map((b) => b.textContent)).toEqual(["Patient requests", "Appointments", "Referrals"]);
    fireEvent.click(within(tabs).getByRole("button", { name: "Appointments" }));
    expect(await screen.findByRole("button", { name: /Record appointment/ })).toBeTruthy();
    fireEvent.click(within(tabs).getByRole("button", { name: "Patient requests" }));
    const requests = await screen.findByRole("list", { name: "Patient requests" });
    fireEvent.click(within(requests).getByRole("button", { name: /SYNTH-PAT-1/ }));
    expect(within(requests).getByRole("button", { name: "Record appointment" })).toBeTruthy();
  });
});

/* ── Session expiry ──────────────────────────────────────────────────────────── */

describe("Session expiry on coordination requests", () => {
  let accepted: string;
  let refresh: "ok" | "refused";

  beforeEach(() => {
    override = (u, _method, init) => {
      const path = pathOf(u);
      if (path === "/auth/refresh")
        return refresh === "ok"
          ? json({ access_token: "pra_rotated", refresh_token: "prr_rotated", expires_in: 900 })
          : json(errorBody("unauthorized", "Refresh refused."), 401);
      const auth = new Headers(init?.headers).get("Authorization");
      if (path.startsWith("/follow-up-tasks") && auth !== `Bearer ${accepted}`) return json(errorBody("unauthorized", "Token expired."), 401);
      return null;
    };
  });

  const renderShell = () =>
    render(
      <AuthProvider>
        <AppShell>
          <FollowUpWorkspace />
        </AppShell>
      </AuthProvider>
    );
  const unauthenticatedDataCalls = () =>
    fetchMock.mock.calls.filter(([u, init]) => !/\/(me|auth\/.*)$/.test(new URL(String(u)).pathname) && !new Headers(init?.headers).get("Authorization"));

  it("rotates the token on 401 and loads the queue", async () => {
    accepted = "pra_rotated";
    refresh = "ok";
    renderShell();
    expect(await screen.findByRole("list", { name: "Follow-up tasks" })).toBeTruthy();
    expect(sent("POST", "/auth/refresh").length).toBeGreaterThanOrEqual(1);
    expect(window.sessionStorage.getItem("pulsereach-session")).toContain("pra_rotated");
    expect(unauthenticatedDataCalls()).toHaveLength(0);
  });

  it("returns to sign-in when the refresh is refused, without showing stale data", async () => {
    accepted = "pra_never";
    refresh = "refused";
    renderShell();
    expect(await screen.findByText(/Your session ended or was revoked/)).toBeTruthy();
    expect(window.sessionStorage.getItem("pulsereach-session")).toBeNull();
    expect(screen.queryByRole("list", { name: "Follow-up tasks" })).toBeNull();
    expect(unauthenticatedDataCalls()).toHaveLength(0);
  });
});

/* ── Theme ───────────────────────────────────────────────────────────────────── */

describe("Coordination theming", () => {
  it.each(["light", "dark"])("renders the %s theme with semantic tokens only", async (theme) => {
    document.documentElement.dataset.theme = theme;
    const { container } = render(
      <>
        <FollowUpWorkspace />
        <AppointmentsWorkspace />
        <TaskDetail taskId="T-1" />
      </>
    );
    await screen.findByRole("list", { name: "Follow-up tasks" });
    await screen.findByRole("region", { name: "Appointments overview" });
    await screen.findByRole("heading", { level: 1, name: "Screening invitation" });
    await screen.findByRole("button", { name: /Prepare draft/ });
    await act(async () => {});
    const inline = [...container.querySelectorAll("[style]")].map((el) => el.getAttribute("style")).join(" ");
    expect(inline).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
    const paint = [...container.querySelectorAll("[fill],[stroke]")].flatMap((el) => [el.getAttribute("fill"), el.getAttribute("stroke")]).join(" ");
    expect(paint).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
    expect(document.documentElement.dataset.theme).toBe(theme);
  });
});
