import { describe, expect, it } from "vitest";
import { filterChips, filtersToSearchParams, hasActiveFilters, parseFilters, peopleHref } from "./filters";

describe("population filters", () => {
  it("parses only backend-supported values", () => {
    const f = parseFilters(new URLSearchParams("pathway=ifhas&region_id=2&sex=female&cohort=ifhas"));
    expect(f).toEqual({ pathway: "ifhas", region_id: 2, sex: "female" });
  });

  it("drops unknown and out-of-range values", () => {
    expect(parseFilters(new URLSearchParams("pathway=oncology&region_id=9&sex=x"))).toEqual({});
  });

  it("round-trips through search params", () => {
    const f = { pathway: "well_child" as const, region_id: 3 as const };
    expect(parseFilters(filtersToSearchParams(f))).toEqual(f);
    expect(hasActiveFilters(f)).toBe(true);
    expect(hasActiveFilters({})).toBe(false);
  });

  it("builds People links carrying only supported filters", () => {
    expect(peopleHref({})).toBe("/people");
    expect(peopleHref({ pathway: "ifhas", region_id: 1, sex: "male" })).toBe(
      "/people?pathway=ifhas&region_id=1&sex=male"
    );
  });

  it("labels chips for display", () => {
    expect(filterChips({ region_id: 2, sex: "female" }).map((c) => c.label)).toEqual([
      "Region: Al Ain",
      "Sex: Female",
    ]);
  });
});
