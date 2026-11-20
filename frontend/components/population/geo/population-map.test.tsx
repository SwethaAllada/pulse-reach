import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { PopulationMap } from "./population-map";

/* jsdom has no WebGL: the canvas is replaced; the panel, list and fallback are what is tested. */
const canvasProps = vi.fn();
vi.mock("next/dynamic", () => ({
  default: () => (props: Record<string, unknown>) => {
    canvasProps(props);
    return <div data-testid="map-canvas" />;
  },
}));

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(search),
}));

const EXT = { min_latitude: 24.3, max_latitude: 24.4, min_longitude: 54.4, max_longitude: 54.5 };
const area = (id: string, name: string, value: number | null, extent: typeof EXT | null, alerts = 0) => ({
  area: { area_id: id, level: "local_area", parent_area_id: "AE-AZ-AD", name, region_id: 1 },
  population: value === null ? null : 60,
  metric_value: value,
  disease: null,
  hotspot_classification: null,
  active_alerts: alerts,
  preventive_coverage: 0.35,
  open_care_gaps: value,
  care_facilities: extent ? 59 : null,
  facility_association: extent ? "matched" : "no_matching_facility_label",
  facility_point_extent: extent,
  representative_point: extent ? { latitude: 24.35, longitude: 54.45, facility_count: 12, kind: "median_of_published_care_facility_points_approximate" } : null,
  suppressed: value === null ? ["population"] : [],
});

function backend(path: string, q: URLSearchParams) {
  if (path === "/population/map")
    return {
      as_of: "2026-11-16",
      complete_through: "2026-11-02",
      period: "90d",
      geography: q.get("geography"),
      metric: q.get("metric"),
      condition: q.get("condition"),
      privacy: {},
      disclaimer: "",
      total: 3,
      items: [area("A-MUS", "Mussafah", 144, EXT, 2), area("A-KC", "Khalifa City", 242, EXT), area("A-JIMI", "Al Jimi", null, null)],
    };
  if (path === "/population/alerts")
    return {
      total: 1,
      items: [{ alert_id: "AL1", area_id: "A-MUS", area: null, category: "case_increase", condition_name: "Type 2 diabetes", severity: "HIGH", title: "Recorded cases increased in Mussafah", explanation: "Threshold signal.", status: "NEW", last_detected_at: "2026-11-16T00:00:00Z" }],
    };
  if (path === "/facilities/points")
    return { governance_notice: "", source_layers: ["hospitals"], total: 2, excluded_without_coordinates: 1, items: [] };
  throw new Error(`unexpected ${path}`);
}

const fetchMock = vi.fn(async (url: string) => {
  const u = new URL(url);
  return new Response(JSON.stringify(backend(u.pathname.replace("/api/v1", ""), u.searchParams)), { status: 200, headers: { "Content-Type": "application/json" } });
});

afterEach(cleanup);

beforeEach(() => {
  search = "";
  replace.mockReset();
  canvasProps.mockReset();
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
});

describe("PopulationMap", () => {
  it("lists every area with honest values, alert severity and missing-location notes", async () => {
    render(<PopulationMap />);
    const list = await screen.findByRole("list", { name: /Areas ranked/ });
    const rows = within(list).getAllByRole("button");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringMatching(/Mussafah.*High.*144/),
      expect.stringMatching(/Khalifa City.*242/),
      expect.stringMatching(/Al Jimi.*unmapped.*—/),
    ]);
    expect(screen.getByText(/1 with active alerts · 2 mapped/)).toBeTruthy();
    expect(screen.getByText(/Unmapped \(no reliable facility coordinates\): Al Jimi/)).toBeTruthy();
    expect(screen.getByText(/1 without usable coordinates not shown/)).toBeTruthy();
    expect(screen.getByText(/not where\s+patients live/)).toBeTruthy();
  });

  it("selects an area through the URL and shows its statistics and alerts", async () => {
    render(<PopulationMap />);
    fireEvent.click(await screen.findByRole("button", { name: /Mussafah/ }));
    expect(replace).toHaveBeenCalledWith("/?area=A-MUS", { scroll: false });
  });

  it("renders the selected area from the URL, and clearing restores the list", async () => {
    search = "area=A-MUS";
    render(<PopulationMap />);
    expect(await screen.findByRole("heading", { name: "Mussafah" })).toBeTruthy();
    expect(screen.getByText("Recorded cases increased in Mussafah")).toBeTruthy();
    await waitFor(() => expect(canvasProps).toHaveBeenLastCalledWith(expect.objectContaining({ selectedId: "A-MUS" })));
    fireEvent.click(screen.getByRole("button", { name: "Clear area selection" }));
    expect(replace).toHaveBeenCalledWith("/", { scroll: false });
  });

  it("asks the backend for a condition only with disease metrics, and switches geography", async () => {
    render(<PopulationMap />);
    await screen.findByRole("list", { name: /Areas ranked/ });
    fireEvent.change(screen.getByRole("combobox", { name: "Area metric" }), { target: { value: "new_cases" } });
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => /metric=new_cases.*condition=diabetes_type_2|condition=diabetes_type_2.*metric=new_cases/.test(String(u)))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Districts" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("geography=district"))).toBe(true));
    expect(fetchMock.mock.calls.filter(([u]) => /metric=(population|open_care_gaps)/.test(String(u)) && String(u).includes("condition=")).length).toBe(0);
  });

  it("passes layer toggles to the map", async () => {
    render(<PopulationMap />);
    await screen.findByRole("list", { name: /Areas ranked/ });
    fireEvent.click(screen.getByRole("checkbox", { name: /Care facilities/ }));
    await waitFor(() => expect(canvasProps).toHaveBeenLastCalledWith(expect.objectContaining({ showFacilities: false, showAlerts: true })));
  });

  it("falls back to the list when the map cannot load", async () => {
    render(<PopulationMap />);
    await screen.findByRole("list", { name: /Areas ranked/ });
    const { onError } = canvasProps.mock.calls.at(-1)![0] as { onError: (m: string) => void };
    onError("The base map could not be loaded. Facility and area data are still listed.");
    expect(await screen.findByText(/base map could not be loaded/)).toBeTruthy();
    expect(screen.getByRole("list", { name: /Areas ranked/ })).toBeTruthy();
  });
});
