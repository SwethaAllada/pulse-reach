import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { FacilityRegister } from "./facility-register";
import { clearApiCache } from "@/lib/api/cache";
import { AuthProvider } from "@/lib/auth/auth-context";
import { ROLE_PERMISSIONS, errorBody, me } from "@/test/fixtures";
import type { FacilityDetailOut, FacilityPointOut } from "@/lib/api/geo-types";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/facilities",
  useSearchParams: () => new URLSearchParams(search),
}));

const point = (ch_fid: string, name: string, source_layer: string, city: string, region_id: number, is_public: boolean | null = true): FacilityPointOut => ({
  ch_fid,
  name,
  source_layer,
  facility_type: source_layer,
  region_id,
  city,
  is_public,
  license_status: "Active",
  latitude: 24.4,
  longitude: 54.5,
  geo_quality: "valid",
});

const POINTS = {
  governance_notice: "Published SDI licence records.",
  source_layers: ["hospitals", "health_centres", "clinics"],
  total: 4,
  excluded_without_coordinates: 7,
  register: {
    register_total: 5339,
    in_layers: 1700,
    excluded_unidentified: 0,
    excluded_license_status: 60,
    excluded_invalid_coordinates: 15,
    mappable: 4,
    license_statuses_included: ["Active"],
  },
  items: [
    point("F-ZAH", "Zahra Hospital", "hospitals", "Abu Dhabi", 1),
    point("F-BAR", "Baraka Clinic", "clinics", "Al Ain", 2, false),
    point("F-MUS", "Mussafah Health Centre", "health_centres", "Mussafah", 1),
    point("F-DHA", "Dhafra Hospital", "hospitals", "Madinat Zayed", 3, null),
  ],
};

const DETAIL: FacilityDetailOut = {
  ch_fid: "F-ZAH",
  facility_name: "Zahra Hospital",
  facility_name_ar: "مستشفى الزهراء",
  source_layer: "hospitals",
  facility_type: "Hospital",
  subtype: "General hospital",
  category: null,
  region_id: 1,
  city: "Abu Dhabi",
  is_public: true,
  license_status: "Active",
  license_no: "MF-1234",
  latitude: 24.4539123,
  longitude: 54.3773456,
  geo_quality: "valid",
  has_insurance: null,
  inpatient_bed_capacity: 120,
  specialities_raw: "Cardiology; Paediatrics",
  emergency_department: true,
  pediatric_emergency_department: null,
  maternity_emergency_care: false,
  home_care_services: null,
  source_effective_date: "2025-06-30",
  capability_basis: "published",
  governance_notice: "Licence data only.",
};

let identity = me("POPULATION_HEALTH_MANAGER", ROLE_PERMISSIONS.POPULATION_HEALTH_MANAGER);
let override: ((path: string) => Response | null) | null = null;
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

const fetchMock = vi.fn(async (url: string) => {
  const path = new URL(url).pathname.replace("/api/v1", "");
  const o = override?.(path);
  if (o) return o;
  if (path === "/me") return json(identity);
  if (path === "/facilities/points") return json(POINTS);
  if (path === "/facilities/F-ZAH") return json(DETAIL);
  return json(errorBody("not_found", "Not found"), 404);
});

const lastUrl = () => String(replace.mock.calls.at(-1)?.[0] ?? "");
const rowNames = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("cell")[0].textContent);

afterEach(cleanup);

beforeEach(() => {
  search = "";
  override = null;
  identity = me("POPULATION_HEALTH_MANAGER", ROLE_PERMISSIONS.POPULATION_HEALTH_MANAGER);
  replace.mockReset();
  fetchMock.mockClear();
  clearApiCache();
  vi.stubGlobal("fetch", fetchMock);
});

describe("FacilityRegister", () => {
  it("shows register vs mappable counts, filtered count and data-driven exclusions", async () => {
    render(<FacilityRegister />);
    await screen.findByText("Zahra Hospital");
    expect(screen.getByText("Published register").nextElementSibling?.textContent).toBe("5,339");
    expect(screen.getByText("Listed & mapped").nextElementSibling?.textContent).toBe("4");
    expect(screen.getByText("Active licence · valid coordinates")).toBeTruthy();
    expect(screen.getByText("Hospitals", { selector: "dt" }).nextElementSibling?.textContent).toBe("2");
    expect(screen.getByText("Showing 4 of 4")).toBeTruthy();
    expect(
      screen.getByText(/1,700 hospital\/health-centre\/clinic records: 60 without an Active licence and 15 without valid coordinates are not listed\./)
    ).toBeTruthy();
    expect(document.body.textContent).not.toContain("5,339 records");
  });

  it("hides the register card when the summary is absent", async () => {
    override = (p) => (p === "/facilities/points" ? json({ ...POINTS, register: undefined }) : null);
    render(<FacilityRegister />);
    await screen.findByText("Zahra Hospital");
    expect(screen.queryByText("Published register")).toBeNull();
    expect(screen.getByText(/7 records without usable coordinates are not listed/)).toBeTruthy();
  });

  it("searches by name or city (case-insensitive) and writes the URL", async () => {
    render(<FacilityRegister />);
    await screen.findByText("Zahra Hospital");
    fireEvent.change(screen.getByLabelText("Search by name or city"), { target: { value: "BARAKA" } });
    expect(rowNames()).toEqual(["Baraka Clinic"]);
    expect(lastUrl()).toBe("/facilities?q=BARAKA");
    expect(replace.mock.calls.at(-1)?.[1]).toEqual({ scroll: false });
    fireEvent.change(screen.getByLabelText("Search by name or city"), { target: { value: "mussafah" } });
    expect(rowNames()).toEqual(["Mussafah Health Centre"]);
    expect(screen.getByText("Showing 1 of 4")).toBeTruthy();
  });

  it("filters by type and region and sorts by name, city and type", async () => {
    render(<FacilityRegister />);
    await screen.findByText("Zahra Hospital");
    expect(rowNames()).toEqual(["Baraka Clinic", "Dhafra Hospital", "Mussafah Health Centre", "Zahra Hospital"]);
    fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "city" } });
    expect(rowNames()).toEqual(["Zahra Hospital", "Baraka Clinic", "Dhafra Hospital", "Mussafah Health Centre"]);
    expect(lastUrl()).toBe("/facilities?sort=city");
    fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "type" } });
    expect(rowNames()).toEqual(["Baraka Clinic", "Mussafah Health Centre", "Dhafra Hospital", "Zahra Hospital"]);
    fireEvent.change(screen.getByLabelText("Facility type"), { target: { value: "hospitals" } });
    expect(rowNames()).toEqual(["Dhafra Hospital", "Zahra Hospital"]);
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "3" } });
    expect(rowNames()).toEqual(["Dhafra Hospital"]);
    expect(lastUrl()).toBe("/facilities?type=hospitals&region=3&sort=type");
  });

  it("restores filters from the URL", async () => {
    search = "type=clinics&q=al";
    render(<FacilityRegister />);
    await screen.findByText("Baraka Clinic");
    expect(rowNames()).toEqual(["Baraka Clinic"]);
    expect((screen.getByLabelText("Facility type") as HTMLSelectElement).value).toBe("clinics");
  });

  it("shows an empty state and clears filters", async () => {
    render(<FacilityRegister />);
    await screen.findByText("Zahra Hospital");
    fireEvent.change(screen.getByLabelText("Search by name or city"), { target: { value: "nowhere" } });
    expect(screen.getByText("No facilities match these filters")).toBeTruthy();
    expect(screen.getByText("Showing 0 of 4")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(rowNames()).toHaveLength(4);
    expect(lastUrl()).toBe("/facilities");
  });

  it("opens published facts from a row, with the not-published disclaimer and a map link", async () => {
    render(<FacilityRegister />);
    fireEvent.click(await screen.findByRole("button", { name: "Zahra Hospital" }));
    expect(lastUrl()).toBe("/facilities?facility=F-ZAH");
    const panel = await screen.findByRole("region", { name: "Facility details" });
    await within(panel).findByText("MF-1234", { exact: false });
    const ar = within(panel).getByText("مستشفى الزهراء");
    expect(ar.getAttribute("dir")).toBe("rtl");
    expect(ar.getAttribute("lang")).toBe("ar");
    expect(within(panel).getByText("Hospital · General hospital")).toBeTruthy();
    const coords = within(panel).getByText("24.45391, 54.37735");
    expect(coords.getAttribute("dir")).toBe("ltr");
    expect(within(panel).getByText("Emergency department").nextElementSibling?.textContent).toBe("Yes");
    expect(within(panel).getByText("Maternity emergency care").nextElementSibling?.textContent).toBe("No");
    expect(within(panel).queryByText("Paediatric emergency")).toBeNull();
    expect(within(panel).queryByText("Home care services")).toBeNull();
    expect(within(panel).getByText("Inpatient beds").nextElementSibling?.textContent).toBe("120");
    expect(within(panel).getByText("Published specialities (unverified)")).toBeTruthy();
    expect(within(panel).getByText("2025-06-30")).toBeTruthy();
    expect(within(panel).getByText("Licence data only.")).toBeTruthy();
    expect(
      within(panel).getByText(
        "Published licence record — opening hours, contact details, appointment availability and referral acceptance are not published and are not shown."
      )
    ).toBeTruthy();
    expect(panel.textContent).not.toMatch(/opening hours:|\b\d{1,2}:\d{2}\b|phone|tel:|book now/i);
    expect(within(panel).getByRole("link", { name: /Show on map/ }).getAttribute("href")).toBe("/population?facility=F-ZAH");
    fireEvent.click(within(panel).getByRole("button", { name: "Close facility details" }));
    expect(screen.queryByRole("region", { name: "Facility details" })).toBeNull();
    expect(lastUrl()).toBe("/facilities");
  });

  it("opens the detail panel from a ?facility= deep link", async () => {
    search = "facility=F-ZAH&sort=city";
    render(<FacilityRegister />);
    const panel = await screen.findByRole("region", { name: "Facility details" });
    expect(await within(panel).findByRole("heading", { name: "Zahra Hospital" })).toBeTruthy();
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/facilities/F-ZAH"))).toBe(true);
  });

  it("links each row to the population map", async () => {
    render(<FacilityRegister />);
    const link = await screen.findByRole("link", { name: "Show Baraka Clinic on map" });
    expect(link.getAttribute("href")).toBe("/population?facility=F-BAR");
  });

  it("hides map links without population.read", async () => {
    identity = me("CARE_COORDINATOR", ROLE_PERMISSIONS.CARE_COORDINATOR, "assigned");
    search = "facility=F-ZAH";
    render(
      <AuthProvider>
        <FacilityRegister />
      </AuthProvider>
    );
    const panel = await screen.findByRole("region", { name: "Facility details" });
    await within(panel).findByText("MF-1234", { exact: false });
    await screen.findByText("Zahra Hospital", { selector: "button" });
    expect(screen.queryAllByRole("link", { name: /on map/i })).toHaveLength(0);
    expect(within(panel).getByText("The map is available to roles with population access.")).toBeTruthy();
  });

  it("shows map links for a role with population.read", async () => {
    identity = me("CLINICIAN", ROLE_PERMISSIONS.CLINICIAN, "assigned");
    render(
      <AuthProvider>
        <FacilityRegister />
      </AuthProvider>
    );
    expect(await screen.findByRole("link", { name: "Show Zahra Hospital on map" })).toBeTruthy();
  });

  it("reports a backend error without substituting values", async () => {
    override = (p) => (p === "/facilities/points" ? json(errorBody("internal", "Server error"), 500) : null);
    render(<FacilityRegister />);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/Facilities are unavailable/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("explains a 403 as a role limit", async () => {
    override = (p) => (p === "/facilities/points" ? json(errorBody("forbidden", "Forbidden"), 403) : null);
    render(<FacilityRegister />);
    expect(await screen.findByText("Facilities are not available for your role")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("reports a failing detail request inside the panel", async () => {
    search = "facility=F-NOPE";
    override = (p) => (p === "/facilities/F-NOPE" ? json(errorBody("internal", "Server error"), 500) : null);
    render(<FacilityRegister />);
    const panel = await screen.findByRole("region", { name: "Facility details" });
    expect(await within(panel).findByText(/Facility details are unavailable/)).toBeTruthy();
  });
});
