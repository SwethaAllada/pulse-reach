import { describe, expect, it } from "vitest";
import { CARE_GAPS, PATIENTS, RULES } from "@/test/fixtures";
import { buildPopulationModel, findCohort, isCohortId, ruleShortLabel } from "./model";

describe("buildPopulationModel", () => {
  const model = buildPopulationModel(PATIENTS, CARE_GAPS, RULES);

  it("counts people, open gaps and people with open gaps from records", () => {
    expect(model.totalPeople).toBe(6);
    expect(model.openGaps).toBe(3); // closed_refused G4 excluded
    expect(model.peopleWithOpenGap).toBe(2);
    expect(model.historyAvailablePeople).toBe(3);
  });

  it("places every programme member in exactly one segment (open gap first)", () => {
    const ifhas = model.programmes.find((p) => p.pathway === "ifhas")!;
    expect(ifhas.people).toBe(4);
    const seg = Object.fromEntries(ifhas.segments.map((s) => [s.segment, s.people]));
    expect(seg).toEqual({ open_gap: 1, available: 1, partial: 1, not_available: 1 });
    expect(ifhas.segments.reduce((n, s) => n + s.people, 0)).toBe(ifhas.people);
    const wcv = model.programmes.find((p) => p.pathway === "well_child")!;
    expect(Object.fromEntries(wcv.segments.map((s) => [s.segment, s.people]))).toEqual({
      open_gap: 1,
      available: 0,
      partial: 0,
      not_available: 1,
    });
  });

  it("breaks down documented gaps by rule and type per cohort", () => {
    const openGap = findCohort(model, "ifhas:open_gap")!;
    expect(openGap.openGaps).toBe(2);
    expect(openGap.gapsByRule.map((r) => r.key).sort()).toEqual(["IFHAS-PKG-FIT", "IFHAS-PKG-ORAL"]);
    expect(openGap.gapsByType).toEqual(
      expect.arrayContaining([
        { key: "no_documented_screening", label: "No documented screening", count: 1 },
        { key: "partial_completion", label: "Partial completion", count: 1 },
      ])
    );
  });

  it("only counts gaps for people in the (backend-filtered) patient set", () => {
    const onlyChildren = buildPopulationModel(
      PATIENTS.filter((p) => p.history_by_pathway.well_child),
      CARE_GAPS,
      RULES
    );
    expect(onlyChildren.openGaps).toBe(1);
    expect(onlyChildren.gapsByRule).toEqual([
      { key: "WCV-VISIT-06M", label: "Well-Child visit at 6 months", count: 1, pathway: "well_child" },
    ]);
  });

  it("produces zero cohorts for an empty population", () => {
    const empty = buildPopulationModel([], CARE_GAPS, RULES);
    expect(empty.totalPeople).toBe(0);
    expect(empty.openGaps).toBe(0);
    expect(empty.programmes.every((p) => p.people === 0)).toBe(true);
  });

  it("segments by region with programme split", () => {
    expect(model.byRegion.find((r) => r.regionId === 1)).toMatchObject({
      total: 4,
      byPathway: { ifhas: 3, well_child: 1 },
    });
  });
});

describe("cohort ids and labels", () => {
  it("validates cohort ids", () => {
    expect(isCohortId("ifhas")).toBe(true);
    expect(isCohortId("well_child:partial")).toBe(true);
    expect(isCohortId("ifhas:risky")).toBe(false);
    expect(isCohortId("other")).toBe(false);
    expect(isCohortId(null)).toBe(false);
  });

  it("derives short rule labels and falls back to the id", () => {
    expect(ruleShortLabel(RULES[0], RULES[0].rule_id)).toBe("Oral Health Package");
    expect(ruleShortLabel(undefined, "X-1")).toBe("X-1");
  });
});
