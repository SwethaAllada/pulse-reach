import { Surface } from "@/components/ui/surface";
import { StatusGlyph, StatusLabel, statusLabel, type EvaluationStatus } from "@/components/ui/status-glyph";
import { pathwayLabel } from "@/lib/population/filters";
import { asEvaluationStatus, historyMeta, type ProgrammeAssessment } from "@/lib/people/person";
import { ProfileSection } from "./profile-section";

const SERVICE_ORDER: (EvaluationStatus | "other")[] = [
  "due",
  "upcoming",
  "completed",
  "eligible",
  "unknown",
  "insufficient_information",
  "requires_clinical_review",
  "not_eligible",
  "other",
];

export function AssessmentSection({ assessment, openGaps }: { assessment: ProgrammeAssessment[]; openGaps: number }) {
  const members = assessment.filter((a) => a.isMember);
  const gateSummary = members
    .map((a) => {
      const elig = a.gates.filter((g) => g.evaluation_status === "eligible").length;
      return `${pathwayLabel(a.pathway, true)}: ${elig} of ${a.gates.length} programme rules eligible`;
    })
    .join(" · ");
  const inScope = members.reduce((n, a) => n + a.servicesInScope, 0);

  const distinctions: { label: string; value: string; note: string }[] = [
    {
      label: "Elevated health risk",
      value: "Not assessed",
      note: "No approved, validated risk method is configured. PulseReach does not estimate risk or imply any condition.",
    },
    {
      label: "Programme eligibility",
      value: gateSummary || "No programme membership",
      note: "Results of the programme-level rules (eligibility, scope, in-force status).",
    },
    {
      label: "Preventive-care eligibility",
      value: `${inScope} preventive-care rules in scope`,
      note: "Package, visit and developmental-screening rules whose result is anything other than “outside rule scope”.",
    },
    {
      label: "Documented care gaps",
      value: `${openGaps} open`,
      note: "Care-gap records produced by the deterministic engine — not a diagnosis or urgency level.",
    },
    {
      label: "Operational follow-up",
      value: "See Care Coordination",
      note: "Follow-ups, outreach reviews, appointments and referrals are coordination records, not part of this assessment.",
    },
  ];

  return (
    <ProfileSection
      id="assessment"
      title="Prevention Assessment"
      description="Current deterministic evaluation results, kept as separate questions rather than combined into a score."
    >
      <div className="flex flex-col gap-4">
        <Surface className="p-5">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-5">
            {distinctions.map((d) => (
              <div key={d.label} className="min-w-0">
                <dt className="text-xs font-medium text-faint">{d.label}</dt>
                <dd className="mt-1 text-sm font-semibold text-foreground">{d.value}</dd>
                <dd className="mt-0.5 text-xs leading-snug text-muted">{d.note}</dd>
              </div>
            ))}
          </dl>
        </Surface>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {assessment.map((a) => (
            <Surface key={a.pathway} className="p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold text-foreground">{pathwayLabel(a.pathway)}</h3>
                <span className="text-xs text-muted">
                  {a.isMember ? "Programme member" : "Not a programme member"} · {historyMeta(a.history).label}
                </span>
              </div>

              <h4 className="mt-4 text-xs font-medium text-faint">Programme rules</h4>
              {a.gates.length === 0 ? (
                <p className="mt-1 text-sm text-muted">No programme-level evaluations returned.</p>
              ) : (
                <ul className="mt-2 flex flex-col gap-1.5">
                  {a.gates.map((g) => {
                    const s = asEvaluationStatus(g.evaluation_status);
                    return (
                      <li key={g.evaluation_id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-sm">
                        <span className="font-mono text-xs text-muted">{g.rule_id}</span>
                        {s ? <StatusLabel status={s} /> : <span className="text-muted">Unrecognised status “{g.evaluation_status}”</span>}
                      </li>
                    );
                  })}
                </ul>
              )}

              <h4 className="mt-4 text-xs font-medium text-faint">Preventive-care rules</h4>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
                {SERVICE_ORDER.filter((k) => a.serviceCounts[k]).map((k) => (
                  <li key={k} className="inline-flex items-center gap-1.5 text-sm">
                    {k !== "other" && <StatusGlyph status={k} />}
                    <span className="text-muted">{k === "other" ? "Unrecognised status" : statusLabel(k)}</span>
                    <span className="font-mono tabular-nums text-foreground">{a.serviceCounts[k]}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted">
                {a.openGaps} open and {a.closedGaps} closed care-gap records in this programme.
              </p>
            </Surface>
          ))}
        </div>
      </div>
    </ProfileSection>
  );
}
