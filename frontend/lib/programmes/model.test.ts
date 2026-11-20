import { describe, expect, it } from "vitest";
import { CARE_GAPS, fakeBackend, fakeSummaryConfig, OPEN_QUESTIONS, RULES } from "@/test/fixtures";
import type { ProgrammeSummaryOut } from "@/lib/api/types";
import {
  buildProgrammeModel,
  evidenceFigures,
  summaryBand,
  pathwayFromSlug,
  programmeHref,
  ruleHref,
  ruleStanding,
  segmentPeopleFilters,
} from "./model";

describe("programme model", () => {
  it("derives rule standing only from verification fields", () => {
    expect(ruleStanding({ verification_status: "verified", is_authoritative: true, requires_clinical_review: false })).toBe("authoritative");
    expect(ruleStanding({ verification_status: "verified", is_authoritative: false, requires_clinical_review: true })).toBe("review");
    expect(ruleStanding({ verification_status: "verified", is_authoritative: true, requires_clinical_review: true })).toBe("review");
    expect(ruleStanding({ verification_status: "unresolved", is_authoritative: true, requires_clinical_review: false })).toBe("unresolved");
  });

  it("counts gap records by status per rule and programme, and people with open gaps", () => {
    const m = buildProgrammeModel("ifhas", RULES, CARE_GAPS, OPEN_QUESTIONS);
    expect(m.rules.map((r) => r.rule.rule_id).sort()).toEqual(
      ["IFHAS-PKG-FIT", "IFHAS-PKG-LUNG", "IFHAS-PKG-ORAL", "IFHAS-PROG-ELIG-MIN-AGE"]
    );
    expect(m.gaps).toMatchObject({ open: 2, closed_refused: 1, closed_completed: 0, total: 3 });
    expect(m.peopleWithOpenGap).toBe(1);
    const oral = m.rules.find((r) => r.rule.rule_id === "IFHAS-PKG-ORAL")!;
    expect(oral.gaps).toMatchObject({ open: 1, closed_refused: 1 });
    expect(oral.group).toBe("service");
    expect(m.rules.find((r) => r.rule.rule_id === "IFHAS-PROG-ELIG-MIN-AGE")!.group).toBe("programme");
    expect(m.standing).toEqual({ authoritative: 3, review: 1, unresolved: 0 });
    expect(m.gapTypes.map((t) => t.key).sort()).toEqual(["no_documented_screening", "partial_completion"]);
    expect(m.openQuestions.map((q) => q.oq_id)).toEqual(["OQ-LUNG"]);
    expect(m.rules.find((r) => r.rule.rule_id === "IFHAS-PKG-LUNG")!.openQuestionIds).toEqual(["OQ-LUNG"]);
  });

  it("limits gap counts to the filtered member set and keeps programmes apart", () => {
    const m = buildProgrammeModel("ifhas", RULES, CARE_GAPS, [], new Set(["SYNTH-PAT-4"]));
    expect(m.gaps).toMatchObject({ open: 0, closed_refused: 1, total: 1 });
    const wcv = buildProgrammeModel("well_child", RULES, CARE_GAPS, OPEN_QUESTIONS);
    expect(wcv.gaps.open).toBe(1);
    expect(wcv.openQuestions).toEqual([]);
  });

  it("takes evidence figures from the server-side summary, keeping evidence classes apart", () => {
    const s = fakeBackend("http://api/api/v1/programmes/ifhas/summary") as ProgrammeSummaryOut;
    const byCls = Object.fromEntries(evidenceFigures(s).map((f) => [f.cls, f.value]));
    expect(byCls).toEqual({ calculated: 3, recorded_gap: 2, completed: 0, missing_history: 1 });
    expect(evidenceFigures(s)[0].detail).toContain("filters applied");
  });

  it("reports an unavailable summary and suppressed cells as null, never as zero", () => {
    expect(evidenceFigures(null).every((f) => f.value === null && f.detail === "Programme summary not available")).toBe(true);
    fakeSummaryConfig.minCellSize = 5;
    try {
      const s = fakeBackend("http://api/api/v1/programmes/ifhas/summary") as ProgrammeSummaryOut;
      expect(s.members).toBeNull();
      const f = evidenceFigures(s);
      expect(f.map((x) => x.value)).toEqual([null, null, 0, null]);
      expect(f[0].detail).toMatch(/Suppressed for privacy/);
      expect(summaryBand(s)).toBeNull();
    } finally {
      fakeSummaryConfig.minCellSize = 1;
    }
  });

  it("builds a composition band from summary segments", () => {
    const s = fakeBackend("http://api/api/v1/programmes/ifhas/summary") as ProgrammeSummaryOut;
    const band = summaryBand(s)!;
    expect(band.people).toBe(4);
    expect(band.segments.map((x) => [x.segment, x.people])).toEqual([
      ["open_gap", 1],
      ["available", 1],
      ["partial", 1],
      ["not_available", 1],
    ]);
  });

  it("maps segments to the closest backend People filters", () => {
    expect(segmentPeopleFilters("ifhas", "open_gap", { region_id: 1 })).toEqual({
      region_id: 1,
      sex: undefined,
      age_band: undefined,
      pathway: "ifhas",
      has_open_care_gaps: true,
    });
    expect(segmentPeopleFilters("well_child", "partial", {})).toMatchObject({
      pathway: "well_child",
      history_status: "partial",
      has_open_care_gaps: false,
    });
    expect(segmentPeopleFilters("ifhas", null, { sex: "female" })).toMatchObject({ pathway: "ifhas", sex: "female" });
  });

  it("round-trips programme slugs and builds encoded links", () => {
    expect(pathwayFromSlug("well-child")).toBe("well_child");
    expect(pathwayFromSlug("well_child")).toBeNull();
    expect(programmeHref("well_child", "segment=open_gap")).toBe("/programmes/well-child?segment=open_gap");
    expect(ruleHref("ifhas", "A B")).toBe("/programmes/ifhas/rules/A%20B");
  });
});
