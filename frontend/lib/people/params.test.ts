import { describe, expect, it } from "vitest";
import {
  activeFilterCount,
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
    });
    expect(parse("pathway=dental&region_id=7&sex=x&page=-2&id=%3Cscript%3E&age=40")).toEqual({
      filters: {},
      page: 1,
      id: null,
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
});
