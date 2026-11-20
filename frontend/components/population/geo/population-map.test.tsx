import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { evict } from "@/lib/api/cache";
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
    return { governance_notice: "", source_layers: ["hospitals"], total: 2, excluded_without_coordinates: 1, ...(register ? { register } : {}), items: POINTS };
  if (path === "/facilities/F1") return FACILITY;
  if (path.startsWith("/facilities/")) return NOT_FOUND;
  throw new Error(`unexpected ${path}`);
}

const NOT_FOUND = Symbol("404");
const point = (id: string, name: string) => ({
  ch_fid: id, name, source_layer: "hospitals", facility_type: "Hospital", region_id: 1, city: "Abu Dhabi", is_public: true,
  license_status: "Active", latitude: 24.4539, longitude: 54.3773, geo_quality: "ok",
});
const POINTS = [point("F1", "Sheikh Khalifa Medical City"), point("F2", "Unlisted Clinic")];
const FACILITY = {
  ch_fid: "F1", facility_name: "Sheikh Khalifa Medical City", facility_name_ar: "مدينة الشيخ خليفة الطبية", source_layer: "hospitals",
  facility_type: "Hospital", subtype: "General", category: null, region_id: 1, city: "Abu Dhabi", is_public: true,
  license_status: "Active", license_no: "MF-123", latitude: 24.453912, longitude: 54.377301, geo_quality: "ok", has_insurance: null,
  inpatient_bed_capacity: 586, specialities_raw: null, emergency_department: true, pediatric_emergency_department: null,
  maternity_emergency_care: false, home_care_services: null, source_effective_date: "2025-06-30", capability_basis: "published_flags",
  governance_notice: "Department of Health SDI open data; published facts only.",
};
let register: Record<string, unknown> | null = null;

const fetchMock = vi.fn(async (url: string) => {
  const u = new URL(url);
  const body = backend(u.pathname.replace("/api/v1", ""), u.searchParams);
  if (body === NOT_FOUND) return new Response(JSON.stringify({ detail: "Not found" }), { status: 404, headers: { "Content-Type": "application/json" } });
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
});

afterEach(cleanup);

beforeEach(() => {
  search = "";
  register = null;
  evict("facility-points");
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
    expect(screen.queryByTestId("map-canvas")).toBeNull();
    const before = canvasProps.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Retry map" }));
    expect(await screen.findByTestId("map-canvas")).toBeTruthy();
    expect(screen.queryByText(/base map could not be loaded/)).toBeNull();
    expect(canvasProps.mock.calls.length).toBeGreaterThan(before);
  });

  it("opens a deep-linked facility with published facts only, and closing clears the param", async () => {
    search = "facility=F1&tab=x";
    render(<PopulationMap />);
    expect(await screen.findByRole("heading", { name: "Sheikh Khalifa Medical City" })).toBeTruthy();
    const ar = screen.getByText("مدينة الشيخ خليفة الطبية");
    expect(ar.getAttribute("dir")).toBe("rtl");
    expect(ar.getAttribute("lang")).toBe("ar");
    expect(screen.getByText("Hospital · General")).toBeTruthy();
    expect(screen.getByText(/Abu Dhabi · /)).toBeTruthy();
    expect(screen.getByText("Public")).toBeTruthy();
    expect(screen.getByText("MF-123")).toBeTruthy();
    const coords = screen.getByText("24.45391, 54.37730");
    expect(coords.getAttribute("dir")).toBe("ltr");
    expect(screen.getByText("Emergency department")).toBeTruthy();
    expect(screen.getByText("Maternity emergency")).toBeTruthy();
    expect(screen.getByText("586")).toBeTruthy();
    expect(screen.queryByText("Paediatric emergency")).toBeNull(); // null flag = not published, omitted
    expect(screen.queryByText("Home care")).toBeNull();
    expect(screen.getByText("2025-06-30")).toBeTruthy();
    expect(screen.getByText(/published facts only/)).toBeTruthy();
    expect(screen.getByText(/opening hours, contact details, appointment availability and referral acceptance are not published/)).toBeTruthy();
    expect(screen.queryByText(/phone|telephone|email|open now|opening hours:/i)).toBeNull();
    expect(screen.getByRole("link", { name: /Open in facility directory/ }).getAttribute("href")).toBe("/facilities?facility=F1");
    await waitFor(() => expect(canvasProps).toHaveBeenLastCalledWith(expect.objectContaining({ selectedFacilityId: "F1" })));
    fireEvent.click(screen.getByRole("button", { name: "Clear facility selection" }));
    expect(replace).toHaveBeenLastCalledWith("/?tab=x", { scroll: false });
  });

  it("reports a facility that is not in the published register", async () => {
    search = "facility=F9";
    render(<PopulationMap />);
    expect(await screen.findByText("Facility not found in the published register")).toBeTruthy();
    search = "facility=F2"; // in the points, but the detail endpoint 404s
    cleanup();
    render(<PopulationMap />);
    expect(await screen.findByText("Facility not found in the published register")).toBeTruthy();
  });

  it("selecting a facility clears the area and selecting an area clears the facility", async () => {
    search = "area=A-MUS";
    render(<PopulationMap />);
    await screen.findByRole("heading", { name: "Mussafah" });
    const { onSelectFacility } = canvasProps.mock.calls.at(-1)![0] as { onSelectFacility: (id: string) => void };
    onSelectFacility("F1");
    expect(replace).toHaveBeenLastCalledWith("/?facility=F1", { scroll: false });
    cleanup();
    search = "facility=F1";
    render(<PopulationMap />);
    await screen.findByRole("heading", { name: "Sheikh Khalifa Medical City" });
    const { onSelect } = canvasProps.mock.calls.at(-1)![0] as { onSelect: (id: string) => void };
    onSelect("A-KC");
    expect(replace).toHaveBeenLastCalledWith("/?area=A-KC", { scroll: false });
  });

  it("shows the area's period, provenance, marker kind and suppressed fields", async () => {
    search = "area=A-MUS";
    render(<PopulationMap />);
    expect(await screen.findByText(/Last 90 days · as of 2026-11-16/)).toBeTruthy();
    expect(screen.getByText("Approximate area position: median of 12 published facility locations.")).toBeTruthy();
    expect(screen.getByText(/Synthetic patient records, aggregated server-side/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Back to all areas/ }));
    expect(replace).toHaveBeenLastCalledWith("/", { scroll: false });
    cleanup();
    search = "area=A-JIMI";
    render(<PopulationMap />);
    expect(await screen.findByText("Not mapped — fewer than 3 published facility locations.")).toBeTruthy();
    expect(screen.getByText("Suppressed: Registered population")).toBeTruthy();
  });

  it("legend names the measure and period, a selected swatch and the register counts", async () => {
    register = {
      register_total: 2010, in_layers: 1900, excluded_unidentified: 5, excluded_license_status: 200,
      excluded_invalid_coordinates: 70, mappable: 1625, license_statuses_included: ["Active"],
    };
    render(<PopulationMap />);
    await screen.findByRole("list", { name: /Areas ranked/ });
    expect(await screen.findByText("Size: Open care gaps · last 90 days")).toBeTruthy();
    expect(screen.getByText("Selected area or facility")).toBeTruthy();
    const count = await screen.findByText("1,625 mapped of 2,010 published records");
    expect(count.getAttribute("title")).toMatch(/200 by licence status.*70 with missing or invalid coordinates/);
  });
});
