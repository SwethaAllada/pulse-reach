import { Surface } from "@/components/ui/surface";
import { StatusGlyph, StatusLabel, statusLabel, type EvaluationStatus } from "@/components/ui/status-glyph";
import { pathwayLabel } from "@/lib/population/filters";
import { asEvaluationStatus, historyMeta, type ProgrammeAssessment } from "@/lib/people/person";
import { ProfileSection } from "./profile-section";
import { useT } from "@/lib/i18n/use-locale";

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
  const tr = useT();
  const members = assessment.filter((a) => a.isMember);
  const gateSummary = members
    .map((a) => {
      const elig = a.gates.filter((g) => g.evaluation_status === "eligible").length;
      return tr("assess.gate_summary", { programme: pathwayLabel(a.pathway, tr, true), elig, total: a.gates.length });
    })
    .join(" · ");
  const inScope = members.reduce((n, a) => n + a.servicesInScope, 0);

  const distinctions: { label: string; value: string; note: string }[] = [
    { label: tr("assess.risk"), value: tr("assess.risk_value"), note: tr("assess.risk_note") },
    { label: tr("assess.eligibility"), value: gateSummary || tr("assess.no_membership"), note: tr("assess.eligibility_note") },
    { label: tr("assess.preventive"), value: tr("assess.preventive_value", { count: inScope }), note: tr("assess.preventive_note") },
    { label: tr("assess.gaps"), value: tr("assess.gaps_value", { count: openGaps }), note: tr("assess.gaps_note") },
    { label: tr("assess.followup"), value: tr("assess.followup_value"), note: tr("assess.followup_note") },
  ];

  return (
    <ProfileSection
      id="assessment"
      title={tr("profile.sec.assessment")}
      description={tr("assess.desc")}
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
                <h3 className="text-sm font-semibold text-foreground">{pathwayLabel(a.pathway, tr)}</h3>
                <span className="text-xs text-muted">
                  {tr(a.isMember ? "assess.member" : "assess.not_member")} · {historyMeta(a.history, tr).label}
                </span>
              </div>

              <h4 className="mt-4 text-xs font-medium text-faint">{tr("assess.programme_rules")}</h4>
              {a.gates.length === 0 ? (
                <p className="mt-1 text-sm text-muted">{tr("assess.no_gates")}</p>
              ) : (
                <ul className="mt-2 flex flex-col gap-1.5">
                  {a.gates.map((g) => {
                    const s = asEvaluationStatus(g.evaluation_status);
                    return (
                      <li key={g.evaluation_id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-sm">
                        <span className="font-mono text-xs text-muted ltr-value">{g.rule_id}</span>
                        {s ? <StatusLabel status={s} /> : <span className="text-muted">{tr("assess.unrecognised_status", { status: g.evaluation_status })}</span>}
                      </li>
                    );
                  })}
                </ul>
              )}

              <h4 className="mt-4 text-xs font-medium text-faint">{tr("assess.preventive_rules")}</h4>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
                {SERVICE_ORDER.filter((k) => a.serviceCounts[k]).map((k) => (
                  <li key={k} className="inline-flex items-center gap-1.5 text-sm">
                    {k !== "other" && <StatusGlyph status={k} />}
                    <span className="text-muted">{k === "other" ? tr("assess.unrecognised") : statusLabel(k, tr)}</span>
                    <span className="font-mono tabular-nums text-foreground">{a.serviceCounts[k]}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted">
                {tr("assess.records", { open: a.openGaps, closed: a.closedGaps })}
              </p>
            </Surface>
          ))}
        </div>
      </div>
    </ProfileSection>
  );
}
