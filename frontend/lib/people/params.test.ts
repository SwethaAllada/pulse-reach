import { englishT } from "@/lib/i18n/translate";
import { describe, expect, it } from "vitest";
import {
  activeFilterCount,
  careFilterChips,
  peopleFiltersHref,
  peopleQuery,
  listHrefFromProfile,
  normalizeIdQuery,
  parsePeopleState,
  peopleListHref,
  profileHref,
} from "./params";

const parse = (qs: string) => parsePeopleState(new URLSearchParams(qs));

describe("people URL state", () => {
  it("parses supported filters, page and ID; drops invalid values", () => {
    expect(parse("pathway=ifhas&region_id=2&sex=male&page=3&id=synth-pat-000003")).toEqual({
      filters: { pathway: "ifhas", region_id: 2, sex: "male" },
      page: 3,
      id: "SYNTH-PAT-000003",
      sort: null,
    });
    expect(parse("pathway=dental&region_id=7&sex=x&page=-2&id=%3Cscript%3E&age=40")).toEqual({
      filters: {},
      page: 1,
      id: null,
      sort: null,
    });
    expect(parse("page=1.5").page).toBe(1);
  });

  it("normalises ID input to the backend form", () => {
    expect(normalizeIdQuery(" 3 ")).toBe("SYNTH-PAT-000003");
    expect(normalizeIdQuery("synth-pat-000120")).toBe("SYNTH-PAT-000120");
    expect(normalizeIdQuery("Latifa Al")).toBeNull();
    expect(normalizeIdQuery("")).toBeNull();
    expect(normalizeIdQuery("1234567")).toBe("1234567");
  });

  it("serialises canonically and counts active criteria", () => {
    const s = parse("sex=female&page=2&pathway=well_child");
    expect(peopleListHref(s)).toBe("/people?pathway=well_child&sex=female&page=2");
    expect(peopleListHref(parse("page=1"))).toBe("/people");
    expect(activeFilterCount(s)).toBe(2);
    expect(activeFilterCount(parse("id=3&region_id=1"))).toBe(2);
  });

  it("round-trips list state through a profile link", () => {
    const s = parse("pathway=ifhas&region_id=1&page=4");
    const href = profileHref("SYNTH-PAT-000009", s);
    expect(href).toBe("/people/SYNTH-PAT-000009?from=pathway%3Difhas%26region_id%3D1%26page%3D4");
    const from = new URL(href, "http://x").searchParams.get("from");
    expect(listHrefFromProfile(from)).toBe("/people?pathway=ifhas&region_id=1&page=4");
    expect(listHrefFromProfile(null)).toBe("/people");
    expect(listHrefFromProfile("https://evil.example/?pathway=ifhas")).toBe("/people");
  });

  it("parses backend-supported care filters and sort, dropping unknown values", () => {
    const s = parse("pathway=ifhas&has_open_care_gaps=true&history_status=partial&age_band=adult_40_59&sort=open_gaps");
    expect(s.filters).toEqual({ pathway: "ifhas", has_open_care_gaps: true, history_status: "partial", age_band: "adult_40_59" });
    expect(s.sort).toBe("open_gaps");
    expect(peopleQuery(s)).toMatchObject({ has_open_care_gaps: true, sort_by: "open_gaps", sort_dir: "desc" });
    expect(activeFilterCount(s)).toBe(4);
    expect(careFilterChips(s.filters, englishT).map((c) => c.label)).toEqual(["With open care gaps", "History partial", "Age: 40–59"]);

    const bad = parse("has_open_care_gaps=yes&history_status=none&age_band=40s&sort=age");
    expect(bad.filters).toEqual({});
    expect(bad.sort).toBeNull();
    expect(parse("has_open_care_gaps=false").filters.has_open_care_gaps).toBe(false);
  });

  it("serialises drill-down links with backend parameter names", () => {
    expect(peopleFiltersHref({ pathway: "well_child", has_open_care_gaps: false, history_status: "not_available" }, "open_gaps")).toBe(
      "/people?pathway=well_child&has_open_care_gaps=false&history_status=not_available&sort=open_gaps"
    );
  });
});
