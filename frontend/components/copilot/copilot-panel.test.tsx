import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { errorBody, fakeFetchResponse, me, ROLE_PERMISSIONS } from "@/test/fixtures";
import type { MeOut } from "@/lib/api/types";
import type { CopilotOut, CopilotTask } from "@/lib/copilot/api";

const route = vi.hoisted(() => ({ personId: "SYNTH-PAT-1" }));

vi.mock("next/navigation", () => ({
  useParams: () => ({ personId: route.personId }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
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
import { clearRuleDetailCache } from "@/lib/people/use-people-data";
import { applyLocale } from "@/lib/i18n/store";
import { PersonProfile } from "@/components/people/profile/person-profile";
import { PopulationWorkspace } from "@/components/population/population-workspace";
import { CopilotPanel, draftText } from "./copilot-panel";

/* ── Copilot fixtures (`CopilotOut`, backend contract) ── */
const AR_TEXT = {
  summary: "لدى الشخص متابعتان نشطتان وموعد قادم.",
  points: ["متابعة واحدة متأخرة."],
  questions: ["هل تم التواصل مع الشخص؟"],
  steps: [{ code: "review_follow_up", label: "مراجعة المتابعة" }],
  sources: ["المتابعات", "المواعيد"],
  notice: "مسودة مُنشأة بالذكاء الاصطناعي — راجعها قبل الاستخدام",
  disclaimer: "بيانات اصطناعية.",
};

function copilotOut(task: CopilotTask, language: "en" | "ar", patch: Partial<CopilotOut> = {}): CopilotOut {
  const ar = language === "ar";
  return {
    task,
    locale: language,
    direction: ar ? "rtl" : "ltr",
    summary: ar ? AR_TEXT.summary : `Summary for ${task}: two active follow-ups and one upcoming appointment.`,
    points: ar ? AR_TEXT.points : ["One follow-up is overdue.", "Preferred channel is SMS."],
    questions: ar ? AR_TEXT.questions : ["Has the person been contacted this week?"],
    suggested_next_steps: ar ? AR_TEXT.steps : [{ code: "review_follow_up", label: "Review the overdue follow-up" }],
    generation_mode: "llm_grounded",
    ai_available: true,
    draft_notice: ar ? AR_TEXT.notice : "AI-generated draft - review before use",
    disclaimer: ar ? AR_TEXT.disclaimer : "Synthetic data. Not clinical advice.",
    sources: ar ? AR_TEXT.sources : ["Follow-up tasks", "Appointments"],
    ai: {
      generation_mode: "llm_grounded",
      prompt_version: "copilot-v1",
      provider: "openai_compatible",
      model: "test-model",
      fallback_reason: null,
      violations: [],
      audit_id: `AIA-${task}-${language}`,
    },
    ...patch,
  };
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const pathOf = (url: string) => decodeURIComponent(new URL(url).pathname.replace("/api/v1", ""));
const TASK_BY_PATH: [RegExp, CopilotTask][] = [
  [/^\/ai\/copilot\/patients\/[^/]+\/coordination$/, "coordination_summary"],
  [/^\/ai\/copilot\/patients\/[^/]+\/clinical-review$/, "clinical_review"],
  [/^\/ai\/copilot\/population$/, "population_briefing"],
];

let identity: MeOut;
let copilot: (task: CopilotTask, body: { language?: "en" | "ar" }) => Response;
const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input);
  const path = pathOf(url);
  if (path === "/me") return json(identity);
  const hit = TASK_BY_PATH.find(([re]) => re.test(path));
  if (hit) return copilot(hit[1], JSON.parse(String(init?.body ?? "{}")));
  return fakeFetchResponse(url, init);
});
const copilotCalls = () => fetchMock.mock.calls.filter(([u]) => pathOf(String(u)).startsWith("/ai/copilot"));

type Role = keyof typeof ROLE_PERMISSIONS;
const asRole = (role: Role, ui: React.ReactNode, permissions = ROLE_PERMISSIONS[role]) => {
  identity = me(role, permissions, role === "POPULATION_HEALTH_MANAGER" ? "organization" : "assigned");
  return render(<AuthProvider>{ui}</AuthProvider>);
};
const panel = (kind: string) => document.querySelector<HTMLElement>(`[data-copilot="${kind}"]`);
const profileLoaded = () => screen.findByRole("heading", { name: "Overview", level: 2 });
const generate = (root: HTMLElement = document.body) => fireEvent.click(within(root).getByRole("button", { name: /Generate summary/ }));

beforeEach(() => {
  route.personId = "SYNTH-PAT-1";
  clearApiCache();
  clearRuleDetailCache();
  identity = me("CARE_COORDINATOR", ROLE_PERMISSIONS.CARE_COORDINATOR, "assigned");
  copilot = (task, body) => json(copilotOut(task, body.language ?? "en"));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => setTimeout(cb, 0));
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  fetchMock.mockClear();
  vi.unstubAllGlobals();
});

describe("copilot panels by role", () => {
  it.each([
    ["CARE_COORDINATOR", true, true],
    ["CLINICIAN", true, true],
    ["POPULATION_HEALTH_MANAGER", true, true],
    ["SYSTEM_ADMIN", false, false],
  ] as [Role, boolean, boolean][])("%s on the person profile", async (role, coordination, clinical) => {
    asRole(role, <PersonProfile />);
    await profileLoaded();
    await waitFor(() => expect(screen.getByRole("region", { name: "Care Coordination" })).toBeTruthy());
    expect(!!panel("coordination")).toBe(coordination);
    expect(!!panel("clinical_review")).toBe(clinical);
    expect(panel("population")).toBeNull();
    if (coordination) expect(within(screen.getByRole("region", { name: "Care Coordination" })).getByRole("region", { name: "Coordination summary" })).toBeTruthy();
    if (clinical) expect(within(screen.getByRole("region", { name: "Care Gaps" })).getByRole("region", { name: "Clinical review summary" })).toBeTruthy();
    expect(copilotCalls()).toHaveLength(0);
  });

  it("hides the clinical review without ai.explain and the coordination summary without followups.read", async () => {
    const perms = ROLE_PERMISSIONS.CLINICIAN.filter((p) => p !== "ai.explain" && p !== "followups.read");
    asRole("CLINICIAN", <PersonProfile />, perms);
    await profileLoaded();
    expect(panel("coordination")).toBeNull();
    expect(panel("clinical_review")).toBeNull();
  });

  it.each([
    ["POPULATION_HEALTH_MANAGER", true],
    ["CLINICIAN", true],
    ["CARE_COORDINATOR", true],
    ["SYSTEM_ADMIN", false],
  ] as [Role, boolean][])("%s on the population workspace", async (role, shown) => {
    asRole(role, <PopulationWorkspace />);
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => pathOf(String(u)) === "/me")).toBe(true));
    await waitFor(() => expect(!!panel("population")).toBe(shown));
    expect(panel("coordination")).toBeNull();
    expect(panel("clinical_review")).toBeNull();
  });

  it("a coordinator generates the coordination summary for the profile's patient", async () => {
    asRole("CARE_COORDINATOR", <PersonProfile />);
    await profileLoaded();
    const root = await waitFor(() => panel("coordination")!);
    generate(root);
    expect(await within(root).findByText(/Summary for coordination_summary/)).toBeTruthy();
    const [url, init] = copilotCalls()[0];
    expect(pathOf(String(url))).toBe("/ai/copilot/patients/SYNTH-PAT-1/coordination");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ language: "en" });
  });
});

describe("CopilotPanel", () => {
  it("renders an English draft: notice, summary, points, questions, next steps as labels and sources", async () => {
    render(<CopilotPanel target={{ kind: "clinical_review", patientId: "SYNTH-PAT-1" }} />);
    expect(screen.getByText(/Nothing is generated until you ask/)).toBeTruthy();
    generate();
    expect(screen.getByLabelText("Generating the summary").getAttribute("aria-busy")).toBe("true");
    expect((screen.getByRole("button", { name: /Generating summary/ }) as HTMLButtonElement).disabled).toBe(true);
    const draft = await screen.findByRole("article", { name: "Generated draft" });
    expect(draft.getAttribute("dir")).toBe("ltr");
    expect(draft.getAttribute("lang")).toBe("en");
    expect(screen.getByText("AI-generated draft - review before use")).toBeTruthy();
    expect(within(draft).getByText("One follow-up is overdue.")).toBeTruthy();
    expect(within(draft).getByText("Has the person been contacted this week?")).toBeTruthy();
    const step = within(draft).getByText("Review the overdue follow-up");
    expect(step.tagName).toBe("LI");
    expect(step.closest("button, a")).toBeNull();
    expect(within(draft).getByText("Follow-up tasks")).toBeTruthy();
    expect(within(draft).getByText("Synthetic data. Not clinical advice.")).toBeTruthy();
    expect(screen.queryByText("AI unavailable — standard summary shown")).toBeNull();
    const audit = screen.getByText("AIA-clinical_review-en");
    expect(audit.getAttribute("dir")).toBe("ltr");
    expect(pathOf(String(copilotCalls()[0][0]))).toBe("/ai/copilot/patients/SYNTH-PAT-1/clinical-review");
  });

  it("offers no action buttons — only generate, copy, edit and discard", async () => {
    render(<CopilotPanel target={{ kind: "coordination", patientId: "SYNTH-PAT-1" }} />);
    generate();
    await screen.findByRole("article", { name: "Generated draft" });
    const names = screen.getAllByRole("button").map((b) => b.textContent?.trim());
    expect(names).toEqual(["Generate again", "Copy", "Edit", "Discard"]);
    for (const verb of [/send/i, /book/i, /complete/i, /approve/i, /schedule/i]) expect(screen.queryByRole("button", { name: verb })).toBeNull();
  });

  it("renders Arabic right-to-left and asks the backend in the UI language", async () => {
    act(() => applyLocale("ar", { persist: false }));
    render(<CopilotPanel target={{ kind: "population" }} />);
    fireEvent.click(screen.getByRole("button", { name: /إنشاء الملخص/ }));
    const draft = await screen.findByRole("article", { name: "المسودة المُنشأة" });
    expect(draft.getAttribute("dir")).toBe("rtl");
    expect(draft.getAttribute("lang")).toBe("ar");
    expect(within(draft).getByText(AR_TEXT.summary)).toBeTruthy();
    expect(within(draft).getByText("مراجعة المتابعة")).toBeTruthy();
    expect(screen.getByText(AR_TEXT.notice).getAttribute("dir")).toBe("rtl");
    expect(screen.getByRole("heading", { name: "إحاطة السكان" })).toBeTruthy();
    expect(screen.getByText("AIA-population_briefing-ar").getAttribute("dir")).toBe("ltr");
    const [url, init] = copilotCalls()[0];
    expect(pathOf(String(url))).toBe("/ai/copilot/population");
    expect(JSON.parse(String(init?.body))).toEqual({ language: "ar" });
  });

  it.each([
    [{ ai_available: false, generation_mode: "deterministic_fallback" as const }],
    [{ ai_available: true, generation_mode: "deterministic_fallback" as const }],
    [{ ai_available: false, generation_mode: "llm_grounded" as const }],
  ])("shows the standard-summary state when AI is unavailable (%o)", async (patch) => {
    copilot = (task, body) =>
      json(copilotOut(task, body.language ?? "en", { ...patch, ai: { ...copilotOut(task, "en").ai, fallback_reason: "llm_disabled", provider: null, model: null } }));
    render(<CopilotPanel target={{ kind: "population" }} />);
    generate();
    expect(await screen.findByText("AI unavailable — standard summary shown")).toBeTruthy();
    expect(screen.queryByText("AI-generated draft - review before use")).toBeNull();
    expect(screen.getByText(/Summary for population_briefing/)).toBeTruthy();
    expect(screen.getByText("llm_disabled")).toBeTruthy();
  });

  it.each([
    [403, "forbidden", "Your role cannot generate this summary", false],
    [404, "not_found", "This person is not available in your scope", false],
    [429, "rate_limited", "Too many summary requests", true],
    [503, "unavailable", "The summary could not be generated", true],
  ] as const)("shows a %i error state", async (status, code, title, retry) => {
    copilot = () => json(errorBody(code, `Server says ${code}.`), status);
    render(<CopilotPanel target={{ kind: "coordination", patientId: "SYNTH-PAT-9" }} />);
    generate();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(title)).toBeTruthy();
    expect(alert.textContent).toContain(status === 403 ? "403" : `Server says ${code}.`);
    expect(!!within(alert).queryByRole("button", { name: /Retry/ })).toBe(retry);
  });

  it("retries after a server error", async () => {
    let fail = true;
    copilot = (task, body) => (fail ? json(errorBody("internal", "Boom."), 500) : json(copilotOut(task, body.language ?? "en")));
    render(<CopilotPanel target={{ kind: "coordination", patientId: "SYNTH-PAT-1" }} />);
    generate();
    const alert = await screen.findByRole("alert");
    fail = false;
    fireEvent.click(within(alert).getByRole("button", { name: /Retry/ }));
    expect(await screen.findByRole("article", { name: "Generated draft" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(copilotCalls()).toHaveLength(2);
  });

  it("edits a draft locally, copies the edit and discards it without any request", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<CopilotPanel target={{ kind: "coordination", patientId: "SYNTH-PAT-1" }} />);
    generate();
    await screen.findByRole("article", { name: "Generated draft" });
    const callsBefore = fetchMock.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: /Edit/ }));
    const box = screen.getByRole("textbox", { name: /Edit the draft/ }) as HTMLTextAreaElement;
    expect(box.value).toBe(draftText(copilotOut("coordination_summary", "en")));
    expect(box.getAttribute("dir")).toBe("ltr");
    fireEvent.change(box, { target: { value: "My reviewed note." } });
    fireEvent.click(screen.getByRole("button", { name: /Done/ }));
    expect(screen.getByText("My reviewed note.")).toBeTruthy();
    expect(screen.getByText("Edited locally — not saved or sent")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Copy/ }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("My reviewed note."));
    expect(await screen.findByText("Copied to the clipboard.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Discard/ }));
    expect(screen.queryByRole("article")).toBeNull();
    expect(screen.queryByText("My reviewed note.")).toBeNull();
    expect(screen.getByText(/Nothing is generated until you ask/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Generate summary/ })).toBeTruthy();
    expect(fetchMock.mock.calls.length).toBe(callsBefore);
  });

  it("renders on a narrow viewport with wrapping controls", async () => {
    vi.stubGlobal("innerWidth", 360);
    window.dispatchEvent(new Event("resize"));
    const { container } = render(<CopilotPanel target={{ kind: "coordination", patientId: "SYNTH-PAT-1" }} />);
    generate();
    await screen.findByRole("article", { name: "Generated draft" });
    const section = container.querySelector("section")!;
    expect(section.className).toContain("min-w-0");
    expect(screen.getByRole("group", { name: "Draft actions" }).className).toContain("flex-wrap");
    expect(screen.getByRole("article").className).toContain("break-words");
    expect(screen.getAllByRole("button")).toHaveLength(4);
  });
});
