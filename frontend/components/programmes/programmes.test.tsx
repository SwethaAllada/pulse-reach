import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { fakeFetchResponse, MANAGER_PERMISSIONS, me } from "@/test/fixtures";
import type { MeOut } from "@/lib/api/types";

const nav = vi.hoisted(() => {
  let search = "";
  const listeners = new Set<() => void>();
  return {
    params: {} as Record<string, string>,
    pathname: "/programmes",
    get: () => search,
    set: (s: string) => {
      search = s;
      listeners.forEach((l) => l());
    },
    subscribe: (l: () => void) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    replace: vi.fn(),
  };
});

vi.mock("next/navigation", async () => {
  const React = await import("react");
  return {
    usePathname: () => nav.pathname,
    useParams: () => nav.params,
    useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
    useSearchParams: () => {
      const s = React.useSyncExternalStore(nav.subscribe, nav.get, nav.get);
      return React.useMemo(() => new URLSearchParams(s), [s]);
    },
  };
});

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
import { ProgrammesOverview } from "./programmes-overview";
import { ProgrammeDetail } from "./programme-detail";
import { RuleDetailView } from "./rule-detail-view";

let identity: MeOut;
let override: (url: string) => Response | null;
const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input);
  if (new URL(url).pathname.endsWith("/me")) return new Response(JSON.stringify(identity));
  return override(url) ?? fakeFetchResponse(url, init);
});
const calls = (suffix: string) =>
  fetchMock.mock.calls.map(([u]) => new URL(String(u))).filter((u) => u.pathname.endsWith(suffix));

function renderWithAuth(ui: React.ReactNode) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

beforeEach(() => {
  clearApiCache();
  identity = me("POPULATION_HEALTH_MANAGER", MANAGER_PERMISSIONS);
  override = () => null;
  nav.set("");
  nav.params = {};
  nav.pathname = "/programmes";
  nav.replace.mockImplementation((href: string) => act(() => nav.set(href.split("?")[1] ?? "")));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  fetchMock.mockClear();
  nav.replace.mockReset();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
});

const plate = (name: string) => screen.findByRole("article", { name });
const figure = (root: HTMLElement, label: string) =>
  within(root).getByText(label).closest("div")!.querySelector("dd")!.textContent;

describe("Programmes overview", () => {
  it("shows each programme from backend records, with scope and source", async () => {
    renderWithAuth(<ProgrammesOverview />);
    const ifhas = await plate("IFHAS");
    await waitFor(() => expect(figure(ifhas, "Members")).toBe("4"));
    expect(figure(ifhas, "Due or upcoming")).toBe("2");
    expect(figure(ifhas, "Open gaps")).toBe("2");
    expect(figure(ifhas, "Completed")).toBe("0");
    expect(within(ifhas).getByText(/IFHAS Standard \(V10\)/)).toBeTruthy();
    expect(within(ifhas).getByRole("link", { name: /Explore IFHAS/ }).getAttribute("href")).toBe("/programmes/ifhas");
    expect(figure(await plate("Well-Child"), "Members")).toBe("2");
    expect(screen.getByText(/Scope: All patients of your organization/)).toBeTruthy();
    // Every request carried through the session-gated client.
    expect(calls("/rules").length).toBeGreaterThan(0);
  });

  it("explains ledger measures and shows organization-wide coverage with its backend definition", async () => {
    renderWithAuth(<ProgrammesOverview />);
    const ledger = await screen.findByRole("region", { name: "What the engine counts, per programme" });
    await within(ledger).findByText("Touched by a rule under review");
    expect(within(ledger).getByText(/Not “people needing review”/)).toBeTruthy();
    const trend = screen.getByRole("region", { name: "Preventive care across your organization" });
    await within(trend).findByText("67");
    expect(within(trend).getByText(/in-scope patients without an open preventive-care gap/)).toBeTruthy();
    expect(within(trend).getByText(/Not enough history to call a trend/)).toBeTruthy();
  });

  it("applies region/sex filters through the patients API and the URL", async () => {
    renderWithAuth(<ProgrammesOverview />);
    await plate("IFHAS");
    fireEvent.change(await screen.findByLabelText("Region"), { target: { value: "2" } });
    expect(nav.get()).toBe("region_id=2");
    await waitFor(async () => expect(figure(await plate("IFHAS"), "Members")).toBe("1"));
    expect(calls("/patients").at(-1)!.searchParams.get("region_id")).toBe("2");
    expect(figure(await plate("IFHAS"), "Open gaps")).toBe("0");
    expect(within(await plate("IFHAS")).getByRole("link", { name: /Explore IFHAS/ }).getAttribute("href")).toBe(
      "/programmes/ifhas?region_id=2"
    );
  });

  it("never shows zero for data the role cannot read", async () => {
    identity = me("SYSTEM_ADMIN", ["rules.read", "facilities.read"]);
    renderWithAuth(<ProgrammesOverview />);
    const ifhas = await plate("IFHAS");
    await waitFor(() => expect(within(ifhas).getByText(/29|4 rules/)).toBeTruthy());
    expect(figure(ifhas, "Open gaps")).toBe("—");
    expect(figure(ifhas, "Completed")).toBe("—");
    expect(within(ifhas).getByText(/Member segments need patient access/)).toBeTruthy();
    expect(screen.getByText("Care-gap records are not available for your role")).toBeTruthy();
    expect(screen.getByText("Programme breakdowns are not available for your role")).toBeTruthy();
    expect(calls("/care-gaps")).toHaveLength(0);
    expect(calls("/patients")).toHaveLength(0);
  });

  it("treats a backend 403 as a permission state, not an error", async () => {
    override = (url) => (url.includes("/population/summary") ? new Response("{}", { status: 403 }) : null);
    renderWithAuth(<ProgrammesOverview />);
    expect(await screen.findByText("Organization surveillance aggregates are not available for your role")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("Programme detail", () => {
  beforeEach(() => {
    nav.params = { programme: "ifhas" };
    nav.pathname = "/programmes/ifhas";
  });

  it("separates evidence classes and links people to their evidence trace", async () => {
    renderWithAuth(<ProgrammeDetail />);
    const ledger = await screen.findByRole("region", { name: "Why people appear in this programme" });
    await within(ledger).findByText("Missing history is never evidence that care did not happen.");
    expect(within(ledger).getByText("Backend-calculated eligibility")).toBeTruthy();
    expect(within(ledger).getByText("Completed care")).toBeTruthy();
    const people = screen.getByRole("region", { name: "Members who need attention first" });
    const first = (await within(people).findAllByRole("link"))[0];
    expect(first.textContent).toContain("SYNTH-PAT-1");
    const href = new URL(first.getAttribute("href")!, "http://x");
    expect(href.pathname).toBe("/people/SYNTH-PAT-1");
    expect(href.hash).toBe("#evidence");
    expect(href.searchParams.get("from")).toBe("pathway=ifhas");
  });

  it("focuses a lattice segment via the URL and drills into backend-filtered People", async () => {
    renderWithAuth(<ProgrammeDetail />);
    const block = await screen.findByRole("button", { name: /History unavailable: 1 people/ });
    fireEvent.click(block);
    expect(nav.get()).toBe("segment=not_available");
    const focus = screen.getByRole("complementary", { name: "Segment focus" });
    await waitFor(() => expect(within(focus).getByRole("heading", { name: /History unavailable/ })).toBeTruthy());
    expect(within(focus).getByRole("link", { name: /Open in People workspace/ }).getAttribute("href")).toBe(
      "/people?pathway=ifhas&has_open_care_gaps=false&history_status=not_available&sort=open_gaps"
    );
    const people = screen.getByRole("region", { name: "History unavailable" });
    await waitFor(() => expect(within(people).getAllByRole("link").map((a) => a.textContent)).toEqual([expect.stringContaining("SYNTH-PAT-2")]));
  });

  it("explores rules by care-gap state and standing, linking each rule", async () => {
    nav.set("gaps=closed_refused&standing=review");
    renderWithAuth(<ProgrammeDetail />);
    const oral = await screen.findByRole("link", { name: /Oral Health Package \(IFHAS-PKG-ORAL\): 1 refused gap records/ });
    expect(oral.getAttribute("href")).toBe("/programmes/ifhas/rules/IFHAS-PKG-ORAL");
    expect(screen.getByRole("button", { name: /Needs clinical review/ }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(nav.get()).toBe("standing=review");
  });

  it("sends age-group filters to the backend and discloses missing dates of birth", async () => {
    renderWithAuth(<ProgrammeDetail />);
    const dist = await screen.findByRole("region", { name: "Who the programme reaches" });
    await within(dist).findByText(/1 members have no recorded date of birth/);
    expect(calls("/patients").some((u) => u.searchParams.get("age_band") === "adult_40_59")).toBe(true);
  });

  it("reports an unknown programme instead of guessing", async () => {
    nav.params = { programme: "dental" };
    renderWithAuth(<ProgrammeDetail />);
    expect(await screen.findByRole("heading", { name: /No programme “dental”/ })).toBeTruthy();
  });

  it.each(["light", "dark"])("renders the %s theme with semantic tokens only", async (theme) => {
    document.documentElement.dataset.theme = theme;
    const { container } = renderWithAuth(<ProgrammeDetail />);
    await screen.findByRole("button", { name: /Open documented care gap: 1 people/ });
    const inline = [...container.querySelectorAll<HTMLElement | SVGElement>("[style],[fill],[stroke]")]
      .flatMap((el) => [el.getAttribute("style"), el.getAttribute("fill"), el.getAttribute("stroke")])
      .filter(Boolean)
      .join(" ");
    expect(inline).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
  });
});

describe("Rule detail", () => {
  it("shows the printed definition, gap records and linked open questions", async () => {
    nav.params = { programme: "ifhas", ruleId: "IFHAS-PKG-ORAL" };
    renderWithAuth(<RuleDetailView />);
    expect(await screen.findByText("18-75 years (configured)")).toBeTruthy();
    expect(screen.getByText("Dental examination")).toBeTruthy();
    const gaps = screen.getByRole("region", { name: "Where this rule opened gaps" });
    const link = await within(gaps).findByRole("link", { name: /SYNTH-PAT-1/ });
    expect(link.getAttribute("href")).toContain("/people/SYNTH-PAT-1?");
    fireEvent.click(within(gaps).getByRole("button", { name: /Refused/ }));
    expect(await within(gaps).findByRole("link", { name: /SYNTH-PAT-4/ })).toBeTruthy();
    expect(calls("/care-gaps").at(-1)!.searchParams.get("rule_id")).toBe("IFHAS-PKG-ORAL");
  });

  it("marks review-flagged rules and lists their open questions", async () => {
    nav.params = { programme: "ifhas", ruleId: "IFHAS-PKG-LUNG" };
    renderWithAuth(<RuleDetailView />);
    expect(await screen.findByText("Needs clinical review")).toBeTruthy();
    expect(await screen.findByText("Lung screening high-risk criteria")).toBeTruthy();
    expect(await screen.findByText(/That is not evidence that everyone completed it/)).toBeTruthy();
  });
});
