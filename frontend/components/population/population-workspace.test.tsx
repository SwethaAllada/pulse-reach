import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { fakeBackend } from "@/test/fixtures";

/* ── next/navigation: a reactive URL store so router.replace re-renders ── */
const nav = vi.hoisted(() => {
  let search = "";
  const listeners = new Set<() => void>();
  return {
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
    usePathname: () => "/",
    useRouter: () => ({ replace: nav.replace }),
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

import { PopulationWorkspace } from "./population-workspace";

type Handler = (url: string) => Promise<Response>;
const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
let handler: Handler;
const fetchMock = vi.fn((input: RequestInfo | URL) => handler(String(input)));

beforeEach(() => {
  nav.set("");
  nav.replace.mockImplementation((href: string) => act(() => nav.set(href.split("?")[1] ?? "")));
  handler = async (url) => ok(fakeBackend(url));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  fetchMock.mockClear();
  nav.replace.mockReset();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
});

const overview = () => screen.findByRole("region", { name: "Population overview" });
const metric = (root: HTMLElement, label: string) =>
  within(root).getByText(label).closest("div")!.querySelector("dd")!.textContent;
const patientCalls = () =>
  fetchMock.mock.calls.map(([u]) => new URL(String(u))).filter((u) => u.pathname.endsWith("/patients"));

describe("PopulationWorkspace", () => {
  it("shows a loading state, then data from the API", async () => {
    render(<PopulationWorkspace />);
    expect(screen.getByLabelText("Loading population data")).toBeTruthy();
    const ov = await overview();
    expect(metric(ov, "People represented")).toBe("6");
    expect(metric(ov, "With an open documented gap")).toBe("2");
    expect(metric(ov, "Open documented care gaps")).toBe("3");
    expect(within(ov).getByText("Not available")).toBeTruthy();
  });

  it("handles API errors without showing any figures, and retries", async () => {
    handler = async (url) =>
      url.includes("/care-gaps") ? new Response("boom", { status: 500 }) : ok(fakeBackend(url));
    render(<PopulationWorkspace />);
    /* The geographic overview reports its own (independent) API state; pick the workspace alert. */
    const alert = (await screen.findAllByRole("alert")).find((a) => a.textContent?.includes("Population data is unavailable"))!;
    expect(alert).toBeTruthy();
    expect(alert.textContent).toContain("500");
    expect(screen.queryByRole("region", { name: "Population overview" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Documented care gaps by rule" })).toBeNull();

    handler = async (url) => ok(fakeBackend(url));
    fireEvent.click(within(alert).getByRole("button", { name: /retry/i }));
    expect(metric(await overview(), "People represented")).toBe("6");
  });

  it("reports a network failure honestly", async () => {
    handler = async () => {
      throw new TypeError("Failed to fetch");
    };
    render(<PopulationWorkspace />);
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((a) => a.textContent?.includes("Could not reach the PulseReach API"))).toBe(true);
  });

  it("handles empty results and clears filters from the empty state", async () => {
    nav.set("pathway=well_child&region_id=2");
    render(<PopulationWorkspace />);
    expect(await screen.findByText("No people match these filters")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Clear all filters" })[0]);
    expect(metric(await overview(), "People represented")).toBe("6");
  });

  it("compares programme cohorts and selects a segment from the comparison bar", async () => {
    render(<PopulationWorkspace />);
    await overview();
    const table = screen.getByRole("table", { name: "Programme cohort comparison" });
    expect(within(table).getByRole("rowheader", { name: /With an open gap/ })).toBeTruthy();
    const bar = screen.getByRole("group", { name: "IFHAS adult screening evidence segments" });
    fireEvent.click(within(bar).getByRole("button", { name: /Open documented care gap: 1 people/ }));
    expect(nav.get()).toBe("cohort=ifhas%3Aopen_gap");
  });

  it("selects a cohort from the constellation and updates the detail panel", async () => {
    render(<PopulationWorkspace />);
    await overview();
    fireEvent.click(screen.getByRole("button", { name: "People view" }));
    const mark = screen.getByRole("button", { name: /IFHAS adult screening — Open documented care gap: 1 person/ });
    fireEvent.click(mark);
    expect(nav.get()).toBe("cohort=ifhas%3Aopen_gap");
    const panel = screen.getByRole("complementary", { name: "Cohort details" });
    expect(within(panel).getByRole("heading", { name: /Open documented care gap/ })).toBeTruthy();
    expect(within(panel).getByText("Oral Health Package")).toBeTruthy();
    expect(within(panel).getByRole("link", { name: /Open this segment in its programme/ }).getAttribute("href")).toBe(
      "/programmes/ifhas?segment=open_gap"
    );
    expect(mark.getAttribute("aria-pressed")).toBe("true");

    // Keyboard: select another cohort with Enter, clear with Escape.
    const noHistory = screen.getByRole("button", { name: /IFHAS adult screening — History unavailable: 1 person/ });
    fireEvent.keyDown(noHistory, { key: "Enter" });
    expect(within(panel).getByRole("heading", { name: /History unavailable/ })).toBeTruthy();
    expect(within(panel).getByText("No open documented care gaps in this cohort.")).toBeTruthy();
    fireEvent.keyDown(noHistory, { key: "Escape" });
    expect(within(screen.getByRole("complementary", { name: "Cohort details" })).getByText("Cohorts")).toBeTruthy();
  });

  it("applies a single filter through the backend query", async () => {
    render(<PopulationWorkspace />);
    await overview();
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "1" } });
    expect(nav.get()).toBe("region_id=1");
    await waitFor(async () => expect(metric(await overview(), "People represented")).toBe("4"));
    expect(patientCalls().at(-1)!.searchParams.get("region_id")).toBe("1");
    expect(screen.getByRole("button", { name: "Remove filter Region: Abu Dhabi" })).toBeTruthy();
  });

  it("combines filters, then clear-all resets them", async () => {
    nav.set("pathway=ifhas&region_id=1&sex=male");
    render(<PopulationWorkspace />);
    expect(metric(await overview(), "People represented")).toBe("2");
    const last = patientCalls().at(-1)!.searchParams;
    expect([last.get("pathway"), last.get("region_id"), last.get("sex")]).toEqual(["ifhas", "1", "male"]);

    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(nav.get()).toBe("");
    await waitFor(async () => expect(metric(await overview(), "People represented")).toBe("6"));
    expect(screen.getByText("Showing the whole synthetic population.")).toBeTruthy();
  });

  it("programme cohorts link to their programme and People, preserving supported filters", async () => {
    nav.set("region_id=1&sex=female&cohort=ifhas");
    render(<PopulationWorkspace />);
    await overview();
    expect(screen.getByRole("link", { name: /Explore 1 person/ }).getAttribute("href")).toBe(
      "/people?pathway=ifhas&region_id=1&sex=female&sort=open_gaps"
    );
    expect(screen.getByRole("link", { name: /Open the IFHAS programme/ }).getAttribute("href")).toBe(
      "/programmes/ifhas?region_id=1&sex=female"
    );
  });

  it("segment cohorts drill into the programme segment and backend-filtered People, disclosing semantics", async () => {
    nav.set("cohort=well_child:open_gap");
    render(<PopulationWorkspace />);
    await overview();
    expect(screen.getByRole("link", { name: /Open this segment in its programme/ }).getAttribute("href")).toBe(
      "/programmes/well-child?segment=open_gap"
    );
    expect(screen.getByRole("link", { name: /Explore 1 person/ }).getAttribute("href")).toBe(
      "/people?pathway=well_child&has_open_care_gaps=true&sort=open_gaps"
    );
    expect(screen.getByText(/scopes open-gap and history filters to this programme/)).toBeTruthy();
  });

  it.each(["light", "dark"])("renders in the %s theme using semantic tokens only", async (theme) => {
    document.documentElement.dataset.theme = theme;
    const { container } = render(<PopulationWorkspace />);
    await overview();
    const inline = [...container.querySelectorAll<HTMLElement | SVGElement>("[style],[fill],[stroke]")]
      .flatMap((el) => [el.getAttribute("style"), el.getAttribute("fill"), el.getAttribute("stroke")])
      .filter(Boolean)
      .join(" ");
    expect(inline).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
    expect(inline).toContain("var(--");
  });
});
