import { describe, expect, it } from "vitest";
import { CARE_GAPS, EVALUATIONS, PATIENTS, RULES, RULE_DETAILS } from "@/test/fixtures";
import type { CareGapOut } from "@/lib/api/types";
import {
  ageInMonths,
  ageLabel,
  buildAssessment,
  buildPathways,
  buildTrace,
  gapStatusMeta,
  openGapCountByPatient,
  ruleCriteria,
  ruleServices,
  traceReasons,
} from "./person";

const P = (id: string) => PATIENTS.find((p) => p.patient_id === id)!;
const rules = new Map(RULES.map((r) => [r.rule_id, r]));
const gapsOf = (id: string, extra: CareGapOut[] = []) => [...CARE_GAPS, ...extra].filter((g) => g.patient_id === id);

describe("age", () => {
  it("computes whole months/years at the reference date, never guessing", () => {
    expect(ageInMonths("1980-05-20", "2026-11-16")).toBe(557);
    expect(ageLabel("1980-05-20", "2026-11-16")).toBe("46 years");
    expect(ageLabel("1960-11-16", "2026-11-16")).toBe("66 years");
    expect(ageLabel("1960-11-17", "2026-11-16")).toBe("65 years");
    expect(ageLabel("2026-05-10", "2026-11-16")).toBe("6 months");
    expect(ageLabel("2026-10-17", "2026-11-16")).toBe("0 months");
    expect(ageLabel(null, "2026-11-16")).toBe("Date of birth not recorded");
    expect(ageLabel("2027-01-01", "2026-11-16")).toBe("Not available");
  });
});

describe("care-gap status mapping", () => {
  it("only closed_completed counts as completed", () => {
    const statuses = ["open", "closed_completed", "closed_refused", "suppressed", "superseded", "scheduled", "cancelled", "weird"];
    expect(statuses.filter((s) => gapStatusMeta(s).isCompleted)).toEqual(["closed_completed"]);
  });

  it("keeps scheduled and cancelled referrals open and not completed", () => {
    expect(gapStatusMeta("scheduled")).toMatchObject({ isOpen: true, isCompleted: false, label: "Scheduled — not completed" });
    expect(gapStatusMeta("cancelled")).toMatchObject({ isOpen: true, isCompleted: false, label: "Cancelled — not completed" });
  });

  it("leaves unrecognised statuses unknown and uninterpreted", () => {
    expect(gapStatusMeta("pending_review")).toMatchObject({ isOpen: false, isCompleted: false, glyph: "unknown" });
    expect(gapStatusMeta("pending_review").label).toContain("pending_review");
  });

  it("counts open gaps per person from every gap record", () => {
    const counts = openGapCountByPatient(CARE_GAPS);
    expect(counts.get("SYNTH-PAT-1")).toBe(2);
    expect(counts.get("SYNTH-PAT-4")).toBeUndefined();
  });
});

describe("assessment", () => {
  it("separates programme gates from preventive services and counts gaps by programme", () => {
    const [ifhas] = buildAssessment(P("SYNTH-PAT-1"), EVALUATIONS["SYNTH-PAT-1"], gapsOf("SYNTH-PAT-1"));
    expect(ifhas.pathway).toBe("ifhas");
    expect(ifhas.gates.map((g) => g.rule_id)).toEqual(["IFHAS-PROG-ELIG-MIN-AGE"]);
    expect(ifhas.serviceCounts).toEqual({ due: 2, requires_clinical_review: 1 });
    expect(ifhas.servicesInScope).toBe(3);
    expect(ifhas.openGaps).toBe(2);
  });
});

describe("evidence trace", () => {
  it("groups gap, person-evidence and rule-review results and skips plain eligibility", () => {
    const t1 = buildTrace(P("SYNTH-PAT-1"), EVALUATIONS["SYNTH-PAT-1"], gapsOf("SYNTH-PAT-1"));
    expect(t1.map((t) => [t.evaluation.rule_id, t.origin])).toEqual([
      ["IFHAS-PKG-ORAL", "care_gap"],
      ["IFHAS-PKG-FIT", "care_gap"],
      ["IFHAS-PKG-LUNG", "rule_review"],
    ]);
    const t2 = buildTrace(P("SYNTH-PAT-2"), EVALUATIONS["SYNTH-PAT-2"], []);
    expect(t2.map((t) => t.origin)).toEqual(["person_evidence"]);
  });

  it("explains results from returned codes and configured definitions", () => {
    const [unknown] = buildTrace(P("SYNTH-PAT-2"), EVALUATIONS["SYNTH-PAT-2"], []);
    const reasons = traceReasons(unknown);
    expect(reasons[0]).toBe("GUARD-MISSING-HISTORY fired — Eligibility is established but screening history is missing.");
    expect(reasons[1]).toContain("completion cannot be determined");

    const unlisted = traceReasons({
      evaluation: { ...EVALUATIONS["SYNTH-PAT-2"][1], reasons: [{ reason_ordinal: 1, reason_code: "x", guard_id: "GUARD-NEW", item_category: null, item_code: null }] },
      gaps: [],
      origin: "person_evidence",
    });
    expect(unlisted[0]).toBe("GUARD-NEW fired (no definition available in PulseReach)");
  });

  it("reads criteria from the configured rule spec", () => {
    expect(ruleCriteria(RULE_DETAILS["IFHAS-PKG-ORAL"].spec)).toEqual([
      { label: "Target age", value: "18-75 years (configured)", note: undefined },
      { label: "Frequency", value: "Every 3 years (configured)", note: undefined },
      { label: "Sex in scope", value: "Female, Male" },
    ]);
    expect(
      ruleCriteria({ eligibility: { conditions: [{ kind: "inclusion", as_printed: "30 pack-years", machine_evaluable: false }] } })
    ).toEqual([{ label: "Conditions (inclusion)", value: "30 pack-years", note: "Not machine-evaluable — not checked by the engine" }]);
    expect(ruleServices(RULE_DETAILS["IFHAS-PKG-ORAL"])).toEqual([
      { category: "Package component", items: [{ description: "Dental examination", verified: true }] },
    ]);
  });
});

describe("recommended pathway", () => {
  it("offers a pathway only for open, due gaps under verified authoritative rules", () => {
    const lungGap = { ...CARE_GAPS[0], care_gap_id: "GL", rule_id: "IFHAS-PKG-LUNG", evaluation_id: "EV-SYNTH-PAT-1-IFHAS-PKG-LUNG" };
    const entries = buildPathways(gapsOf("SYNTH-PAT-1", [lungGap]), EVALUATIONS["SYNTH-PAT-1"], rules);
    expect(entries.map((e) => [e.gap.care_gap_id, e.offered])).toEqual([
      ["G1", true],
      ["G2", true],
      ["GL", false],
    ]);
    expect(entries[2].blocked).toBe("Evaluation result is “requires_clinical_review”, not due.");

    const dueUnderFlaggedRule = EVALUATIONS["SYNTH-PAT-1"].map((e) =>
      e.rule_id === "IFHAS-PKG-LUNG" ? { ...e, evaluation_status: "due" } : e
    );
    const [flagged] = buildPathways([lungGap], dueUnderFlaggedRule, rules);
    expect(flagged).toMatchObject({ offered: false });
    expect(flagged.blocked).toContain("flagged for clinical review");
  });

  it("never offers a pathway for closed gaps or rules missing from the rules API", () => {
    const refused = buildPathways(gapsOf("SYNTH-PAT-4"), EVALUATIONS["SYNTH-PAT-4"], rules);
    expect(refused[0]).toMatchObject({ offered: false, blocked: "Gap is closed — documented refusal — no pathway is offered." });
    const unlisted = buildPathways(
      [{ ...CARE_GAPS[0], rule_id: "IFHAS-UNLISTED", evaluation_id: "EV-SYNTH-PAT-3-IFHAS-UNLISTED" }],
      EVALUATIONS["SYNTH-PAT-3"],
      rules
    );
    expect(unlisted[0].blocked).toBe("Rule definition was not returned by the rules API.");
  });
});
