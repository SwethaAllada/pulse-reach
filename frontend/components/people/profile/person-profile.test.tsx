import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { fakeBackend, fakeFetchResponse } from "@/test/fixtures";
import { clearRuleDetailCache } from "@/lib/people/use-people-data";

const route = vi.hoisted(() => ({ personId: "SYNTH-PAT-1", search: "" }));

vi.mock("next/navigation", () => ({
  useParams: () => ({ personId: route.personId }),
  useSearchParams: () => new URLSearchParams(route.search),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { PersonProfile } from "./person-profile";

type Handler = (url: string, init?: RequestInit) => Promise<Response>;
let handler: Handler;
const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init));

beforeEach(() => {
  route.personId = "SYNTH-PAT-1";
  route.search = "";
  handler = fakeFetchResponse;
  clearRuleDetailCache();
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

const loaded = () => screen.findByRole("heading", { name: "Overview", level: 2 });
const section = (name: RegExp | string) => screen.getByRole("region", { name });

/** Replace the evaluations payload for one person while keeping the rest of the fake backend. */
function withEvaluations(id: string, patch: (body: Record<string, unknown>) => Record<string, unknown>): Handler {
  return async (url, init) => {
    if (new URL(url).pathname.endsWith(`/patients/${id}/evaluations`))
      return new Response(JSON.stringify(patch(fakeBackend(url, init) as Record<string, unknown>)));
    return fakeFetchResponse(url, init);
  };
}

describe("PersonProfile", () => {
  it("loads a profile and answers the four questions from API data", async () => {
    render(<PersonProfile />);
    expect(screen.getByLabelText("Loading person profile")).toBeTruthy();
    await loaded();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("SYNTH-PAT-1");
    const glance = screen.getByRole("region", { name: "At a glance" });
    expect(within(glance).getByText("46 years · Female · Abu Dhabi")).toBeTruthy();
    expect(within(glance).getByText("2 open documented gaps")).toBeTruthy();
    expect(within(glance).getByText("2 supported pathways")).toBeTruthy();
    const overview = section("Overview");
    expect(within(overview).getByText("SYNTH-EVR-000001 · 2026-11-16")).toBeTruthy();
    expect(overview.textContent).not.toMatch(/SYNTH-EID|Latifa/);
  });

  it("shows a not-found state for unknown IDs", async () => {
    route.personId = "SYNTH-PAT-404";
    render(<PersonProfile />);
    expect(await screen.findByRole("heading", { name: "Person not found" })).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /Back to People/ })[0].getAttribute("href")).toBe("/people");
  });

  it("shows an error and retries", async () => {
    let fail = true;
    handler = async (url, init) =>
      fail && url.endsWith("/evaluations") ? new Response("x", { status: 500 }) : fakeFetchResponse(url, init);
    render(<PersonProfile />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("500");
    expect(screen.queryByRole("region", { name: "Overview" })).toBeNull();
    fail = false;
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    await loaded();
  });

  it("keeps missing history unknown, never a negative result", async () => {
    route.personId = "SYNTH-PAT-2";
    render(<PersonProfile />);
    await loaded();
    const history = section("Screening & History");
    expect(within(history).getAllByText("History unavailable").length).toBeGreaterThan(0);
    expect(history.textContent).toContain("this is not evidence that screening did not happen");
    const trace = section(/Evidence Trace/);
    expect(within(trace).getByText("Evidence missing or conflicting for this person")).toBeTruthy();
    fireEvent.click(within(trace).getByRole("button", { name: /Oral Health Package/ }));
    expect(within(trace).getByText(/GUARD-MISSING-HISTORY fired/)).toBeTruthy();
    expect(within(section("Care Gaps")).getByText(/No care-gap records for this person/)).toBeTruthy();
  });

  it("shows documented history and the records gaps reference", async () => {
    render(<PersonProfile />);
    await loaded();
    const history = section("Screening & History");
    expect(within(history).getAllByText("History available").length).toBeGreaterThan(0);
    expect(within(history).getByText(/SYNTH-SCR-9/)).toBeTruthy();
    expect(within(history).getByText(/Screening and visit records are not available from the API/)).toBeTruthy();
  });

  it("lists open care gaps with type, status, evidence and next step", async () => {
    render(<PersonProfile />);
    await loaded();
    const gaps = section("Care Gaps");
    expect(within(gaps).getByRole("heading", { name: "Open (2)" })).toBeTruthy();
    expect(within(gaps).getAllByText("Open", { selector: "span" })).toHaveLength(2);
    expect(within(gaps).getByText(/IFHAS screening record/)).toBeTruthy();
    expect(within(gaps).getAllByText("Supported pathway available — see Recommended Pathway")).toHaveLength(2);
  });

  it("distinguishes completed from refused gaps and offers no pathway for either", async () => {
    route.personId = "SYNTH-PAT-4";
    render(<PersonProfile />);
    await loaded();
    const gaps = section("Care Gaps");
    expect(within(gaps).getByRole("heading", { name: "Closed or inactive (2)" })).toBeTruthy();
    expect(within(gaps).getByText("Closed — completed")).toBeTruthy();
    expect(within(gaps).getByText("Closed — documented refusal")).toBeTruthy();
    expect(within(gaps).getByText("Closed by a documented refusal. The service was not completed.")).toBeTruthy();
    expect(within(section("Recommended Pathway")).getByText("No supported pathway for this person")).toBeTruthy();
  });

  it("never treats scheduled or cancelled referral statuses as completed", async () => {
    handler = withEvaluations("SYNTH-PAT-1", (body) => ({
      ...body,
      care_gaps: (body.care_gaps as { status: string }[]).map((g, i) => ({ ...g, status: i === 0 ? "scheduled" : "cancelled" })),
    }));
    render(<PersonProfile />);
    await loaded();
    const gaps = section("Care Gaps");
    expect(within(gaps).getByText("Scheduled — not completed")).toBeTruthy();
    expect(within(gaps).getByText("Cancelled — not completed")).toBeTruthy();
    expect(within(gaps).queryByText("Closed — completed")).toBeNull();
    expect(within(gaps).getByRole("heading", { name: "Open (2)" })).toBeTruthy();
    const pathway = section("Recommended Pathway");
    expect(within(pathway).getByText("No supported pathway for this person")).toBeTruthy();
    expect(within(pathway).getByText(/Gap is scheduled — not completed/)).toBeTruthy();
  });

  it("renders the evidence trace from the rule definition and the engine explanation", async () => {
    render(<PersonProfile />);
    await loaded();
    const trace = section(/Evidence Trace/);
    const first = within(trace).getByRole("button", { name: /Oral Health Package/ });
    expect(first.getAttribute("aria-expanded")).toBe("true");
    expect(await within(trace).findByText("18-75 years (configured)")).toBeTruthy();
    expect(within(trace).getByText("Every 3 years (configured)")).toBeTruthy();
    expect(within(trace).getByText(/No documented screening: The person is in scope/)).toBeTruthy();
    expect(within(trace).getByText("Rule-level clinical review")).toBeTruthy();

    fireEvent.click(within(trace).getByRole("button", { name: /Show engine explanation/ }));
    expect(await within(trace).findByText("Template summary for IFHAS-PKG-ORAL")).toBeTruthy();
    expect(within(trace).getByText(/deterministic template/)).toBeTruthy();
    const post = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/explanations"))!;
    expect(JSON.parse(String(post[1]!.body))).toEqual({ patient_id: "SYNTH-PAT-1", rule_id: "IFHAS-PKG-ORAL" });
  });

  it("opens the matching trace from a care gap", async () => {
    render(<PersonProfile />);
    await loaded();
    const trace = section(/Evidence Trace/);
    const fit = within(trace).getByRole("button", { name: /Standalone FIT screening/ });
    expect(fit.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(within(section("Care Gaps")).getAllByRole("button", { name: /Trace the evidence/ })[1]);
    expect(fit.getAttribute("aria-expanded")).toBe("true");
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled());
  });

  it("states what is unavailable when a rule definition is missing", async () => {
    route.personId = "SYNTH-PAT-3";
    render(<PersonProfile />);
    await loaded();
    const trace = section(/Evidence Trace/);
    expect(within(trace).getByText(/did not return a definition for/)).toBeTruthy();
    expect(await within(trace).findByText(/Rule definition unavailable/)).toBeTruthy();
    expect(within(section("Recommended Pathway")).getByText("Rule definition was not returned by the rules API.")).toBeTruthy();
  });

  it("explains the unsupported-pathway state instead of inventing one", async () => {
    route.personId = "SYNTH-PAT-2";
    render(<PersonProfile />);
    await loaded();
    const pathway = section("Recommended Pathway");
    expect(within(pathway).getByText("No supported pathway for this person")).toBeTruthy();
    expect(within(pathway).getByText(/no rule-defined pathway applies/)).toBeTruthy();
    expect(within(pathway).getByText("Screening history missing")).toBeTruthy();
  });

  it("lists services from the configured rule for a supported pathway", async () => {
    render(<PersonProfile />);
    await loaded();
    const pathway = section("Recommended Pathway");
    fireEvent.click(within(pathway).getAllByRole("button", { name: /Services listed by the rule/ })[0]);
    expect(await within(pathway).findByText("Dental examination")).toBeTruthy();
  });

  it("links back to the filtered People list and Population", async () => {
    route.search = "from=pathway%3Difhas%26region_id%3D1%26page%3D2";
    render(<PersonProfile />);
    await loaded();
    expect(screen.getByRole("link", { name: /Back to People/ }).getAttribute("href")).toBe(
      "/people?pathway=ifhas&region_id=1&page=2"
    );
    const crumbs = within(screen.getByRole("navigation", { name: "Breadcrumb" })).getAllByRole("link");
    expect(crumbs.map((a) => a.getAttribute("href"))).toEqual(["/?pathway=ifhas&region_id=1", "/people?pathway=ifhas&region_id=1&page=2"]);
  });

  it("supports direct URL access with an encoded ID and no list context", async () => {
    route.personId = "SYNTH-PAT-5";
    render(<PersonProfile />);
    await loaded();
    expect(screen.getByRole("link", { name: /Back to People/ }).getAttribute("href")).toBe("/people");
    expect(within(screen.getByRole("region", { name: "At a glance" })).getByText("6 months · Female · Al Dhafra")).toBeTruthy();
  });

  it.each(["light", "dark"])("renders the %s theme with semantic tokens only", async (theme) => {
    document.documentElement.dataset.theme = theme;
    const { container } = render(<PersonProfile />);
    await loaded();
    await act(async () => {});
    const inline = [...container.querySelectorAll("[style]")].map((el) => el.getAttribute("style")).join(" ");
    expect(inline).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
    expect(screen.getByRole("navigation", { name: "Profile sections" }).className).toContain("overflow-x-auto");
  });
});
