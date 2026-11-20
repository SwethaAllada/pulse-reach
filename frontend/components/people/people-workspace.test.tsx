import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { fakeFetchResponse, PATIENTS } from "@/test/fixtures";

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
    push: vi.fn(),
  };
});

vi.mock("next/navigation", async () => {
  const React = await import("react");
  return {
    usePathname: () => "/people",
    useRouter: () => ({ replace: nav.replace, push: nav.push }),
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

import { PeopleWorkspace } from "./people-workspace";

type Handler = (url: string, init?: RequestInit) => Promise<Response>;
let handler: Handler;
const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init));

beforeEach(() => {
  nav.set("");
  nav.replace.mockImplementation((href: string) => act(() => nav.set(href.split("?")[1] ?? "")));
  handler = fakeFetchResponse;
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  fetchMock.mockClear();
  nav.replace.mockReset();
  nav.push.mockReset();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
});

const table = () => screen.findByRole("table");
const rowIds = async () => within(await table()).getAllByRole("link").map((a) => a.textContent);
const matching = () => within(screen.getByLabelText("Result context")).getAllByRole("definition")[0].textContent;
const calls = (suffix: string) =>
  fetchMock.mock.calls.map(([u]) => new URL(String(u))).filter((u) => u.pathname.endsWith(suffix));

describe("PeopleWorkspace", () => {
  it("shows loading skeletons, then people from the API with backend totals", async () => {
    render(<PeopleWorkspace />);
    expect(screen.getByLabelText("Loading people")).toBeTruthy();
    expect(await rowIds()).toEqual(PATIENTS.map((p) => p.patient_id));
    expect(matching()).toBe("6");
    const first = within(await table()).getAllByRole("row")[1];
    expect(within(first).getByText("46 years")).toBeTruthy();
    expect(within(first).getByText("Abu Dhabi")).toBeTruthy();
    await waitFor(() => expect(within(first).getByText("2")).toBeTruthy());
    expect(calls("/patients").at(-1)!.searchParams.get("limit")).toBe("25");
  });

  it("shows an error without rows, then retries", async () => {
    handler = async (url, init) => (url.includes("/patients") ? new Response("x", { status: 503 }) : fakeFetchResponse(url, init));
    render(<PeopleWorkspace />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("503");
    expect(screen.queryByRole("table")).toBeNull();
    handler = fakeFetchResponse;
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await rowIds()).toHaveLength(6);
  });

  it("handles empty results and clears filters from the empty state", async () => {
    nav.set("region_id=3&sex=male");
    render(<PeopleWorkspace />);
    expect(await screen.findByText("No people match these filters")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear all filters" }));
    expect(nav.get()).toBe("");
    expect(await rowIds()).toHaveLength(6);
  });

  it("applies a single filter through the backend and resets the page", async () => {
    nav.set("page=1");
    render(<PeopleWorkspace />);
    await table();
    fireEvent.change(screen.getByLabelText("Programme"), { target: { value: "well_child" } });
    expect(nav.get()).toBe("pathway=well_child");
    await waitFor(async () => expect(await rowIds()).toEqual(["SYNTH-PAT-5", "SYNTH-PAT-6"]));
    expect(calls("/patients").at(-1)!.searchParams.get("pathway")).toBe("well_child");
    expect(screen.getByRole("button", { name: "Remove filter Programme: Well-Child visits" })).toBeTruthy();
  });

  it("restores combined filters from the URL, drops invalid values and clears all", async () => {
    nav.set("pathway=ifhas&region_id=1&sex=male&age_group=40-49&history=none&region_id=9");
    render(<PeopleWorkspace />);
    expect(await rowIds()).toEqual(["SYNTH-PAT-3", "SYNTH-PAT-4"]);
    const q = calls("/patients").at(-1)!.searchParams;
    expect([...q.keys()].sort()).toEqual(["limit", "offset", "pathway", "region_id", "sex"]);
    expect((screen.getByLabelText("Sex") as HTMLSelectElement).value).toBe("male");
    expect(within(screen.getByLabelText("Result context")).getAllByRole("definition")[1].textContent).toBe("3");

    fireEvent.click(screen.getByRole("button", { name: /Clear filters/ }));
    expect(nav.get()).toBe("");
    await waitFor(async () => expect(await rowIds()).toHaveLength(6));
  });

  it("paginates with the backend offset/limit contract", async () => {
    const many = Array.from({ length: 60 }, (_, i) => ({ ...PATIENTS[0], patient_id: `SYNTH-PAT-${100 + i}` }));
    handler = async (url, init) => {
      const u = new URL(url);
      if (u.pathname.endsWith("/patients")) {
        const offset = Number(u.searchParams.get("offset"));
        const limit = Number(u.searchParams.get("limit"));
        return new Response(JSON.stringify({ total: 60, limit, offset, items: many.slice(offset, offset + limit) }));
      }
      return fakeFetchResponse(url, init);
    };
    render(<PeopleWorkspace />);
    await table();
    const pager = screen.getByRole("navigation", { name: "Pagination" });
    expect(pager.textContent).toContain("Showing 1–25 of 60");
    expect((within(pager).getByRole("button", { name: /Previous/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(pager).getByRole("button", { name: /Next/ }));
    expect(nav.get()).toBe("page=2");
    await waitFor(() => expect(screen.getByRole("navigation", { name: "Pagination" }).textContent).toContain("Showing 26–50 of 60"));
    expect(calls("/patients").at(-1)!.searchParams.get("offset")).toBe("25");
    expect((await rowIds())[0]).toBe("SYNTH-PAT-125");
  });

  it("explains a page past the end instead of showing an empty list", async () => {
    nav.set("page=9");
    render(<PeopleWorkspace />);
    expect(await screen.findByText("Page 9 is past the last page")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Go to page 1" }));
    expect(nav.get()).toBe("");
  });

  it("looks up an exact synthetic ID after a debounce", async () => {
    render(<PeopleWorkspace />);
    await table();
    fireEvent.change(screen.getByLabelText("Find by synthetic ID"), { target: { value: "synth-pat-5" } });
    expect(calls("/patients/SYNTH-PAT-5")).toHaveLength(0);
    await waitFor(() => expect(nav.get()).toBe("id=SYNTH-PAT-5"));
    await waitFor(async () => expect(await rowIds()).toEqual(["SYNTH-PAT-5"]));
    expect(calls("/patients/SYNTH-PAT-5")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Clear ID search" }));
    expect(nav.get()).toBe("");
    await waitFor(async () => expect(await rowIds()).toHaveLength(6));
  });

  it("reports unknown IDs, invalid input and filter exclusions honestly", async () => {
    nav.set("id=SYNTH-PAT-404");
    render(<PeopleWorkspace />);
    expect(await screen.findByText("No synthetic person with ID SYNTH-PAT-404")).toBeTruthy();

    act(() => nav.set("id=SYNTH-PAT-5&pathway=ifhas"));
    expect(await screen.findByText("SYNTH-PAT-5 does not match the active filters")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters and show this person" }));
    expect(nav.get()).toBe("id=SYNTH-PAT-5");

    const before = fetchMock.mock.calls.length;
    fireEvent.change(screen.getByLabelText("Find by synthetic ID"), { target: { value: "Latifa Al" } });
    expect(screen.getByText(/Not a synthetic ID/)).toBeTruthy();
    await new Promise((r) => setTimeout(r, 500));
    expect(fetchMock.mock.calls.slice(before).some(([u]) => String(u).includes("Latifa"))).toBe(false);
  });

  it("opens a profile from a row, carrying the list state", async () => {
    nav.set("pathway=ifhas&page=1");
    render(<PeopleWorkspace />);
    const link = within(await table()).getByRole("link", { name: "SYNTH-PAT-3" });
    expect(link.getAttribute("href")).toBe("/people/SYNTH-PAT-3?from=pathway%3Difhas");
    fireEvent.click(within(await table()).getAllByRole("row")[3].querySelectorAll("td")[3]);
    expect(nav.push).toHaveBeenCalledWith("/people/SYNTH-PAT-3?from=pathway%3Difhas");
  });

  it("links back to Population with the shared filters", async () => {
    nav.set("region_id=2&page=1");
    render(<PeopleWorkspace />);
    await table();
    expect(screen.getByRole("link", { name: "Population" }).getAttribute("href")).toBe("/?region_id=2");
  });

  it("keeps rows when reference data fails and says what is missing", async () => {
    handler = async (url, init) => (url.includes("/care-gaps") ? new Response("x", { status: 500 }) : fakeFetchResponse(url, init));
    render(<PeopleWorkspace />);
    expect(await rowIds()).toHaveLength(6);
    expect((await screen.findByRole("status")).textContent).toContain("Open-gap counts and ages are unavailable");
    expect(within(await table()).getAllByText("Unavailable").length).toBe(6);
  });

  it.each(["light", "dark"])("renders the %s theme with semantic tokens and a mobile list", async (theme) => {
    document.documentElement.dataset.theme = theme;
    const { container } = render(<PeopleWorkspace />);
    await table();
    const inline = [...container.querySelectorAll("[style]")].map((el) => el.getAttribute("style")).join(" ");
    expect(inline).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
    const mobile = screen.getByRole("list", { name: "People" });
    expect(mobile.className).toContain("md:hidden");
    expect(within(mobile).getAllByRole("link")).toHaveLength(6);
  });
});
