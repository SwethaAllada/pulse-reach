import { AlertTriangle, BarChart3 } from "lucide-react";
import type { DashboardSummaryOut, HistoryStatus } from "@/lib/api/types";
import type { LoadState } from "@/lib/population/use-population-data";
import type { PopulationModel, SegmentId } from "@/lib/population/model";
import { PATHWAY_OPTIONS, pathwayLabel } from "@/lib/population/filters";
import { SectionHeader } from "@/components/ui/section-header";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusGlyph, statusColor, statusLabel, type EvaluationStatus } from "@/components/ui/status-glyph";
import { PROGRAMME_COLOR, SEGMENT_COLOR, SegmentGlyph } from "./segment-glyph";

const HISTORY_SEGMENT: Record<HistoryStatus, SegmentId> = {
  available: "available",
  partial: "partial",
  not_available: "not_available",
};
const HISTORY_LABEL: Record<HistoryStatus, string> = {
  available: "Available",
  partial: "Partial",
  not_available: "Unavailable",
};

/** Dashboard card. */
function Card({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <section aria-label={label} className="reveal min-w-0 rounded-xl border border-border bg-surface-raised p-5">
      {children}
    </section>
  );
}

function Footnote({ children }: { children: React.ReactNode }) {
  return <p className="mt-5 text-[11px] leading-relaxed text-faint">{children}</p>;
}

function ProgrammeDot({ pathway }: { pathway: "ifhas" | "well_child" }) {
  return (
    <span
      aria-hidden="true"
      className="inline-block size-2 shrink-0 rounded-full"
      style={{ backgroundColor: PROGRAMME_COLOR[pathway].paper }}
    />
  );
}

export function GapsByRuleCard({ model }: { model: PopulationModel }) {
  const rows = model.gapsByRule.slice(0, 8);
  const max = rows[0]?.count ?? 0;
  return (
    <Card label="Documented care gaps by rule">
      <SectionHeader
        eyebrow="Documented care gaps"
        title="Where open gaps sit"
        description="Open care-gap records per rule for the people in the current filter set."
      />
      {rows.length === 0 ? (
        <EmptyState icon={BarChart3} title="No open documented gaps" description="No open care-gap records exist for the people in this filter set." />
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map((r) => (
            <li key={r.key}>
              <div className="flex items-baseline justify-between gap-3 text-xs">
                <span className="flex min-w-0 items-center gap-2">
                  <ProgrammeDot pathway={r.pathway} />
                  <span className="truncate text-muted" title={`${r.label} (${r.key})`}>
                    {r.label}
                  </span>
                </span>
                <span className="font-mono tabular-nums text-foreground">{r.count}</span>
              </div>
              <div className="mt-1 h-1.5 rounded-full bg-surface-sunken">
                <div
                  className="grow-x h-1.5 rounded-full"
                  style={{ width: `${(r.count / max) * 100}%`, backgroundColor: "var(--segment-gap)" }}
                />
              </div>
              <p className="mt-0.5 font-mono text-[10px] text-faint">{r.key}</p>
            </li>
          ))}
        </ul>
      )}
      <Footnote>
        {model.gapsByRule.length > rows.length && `${model.gapsByRule.length - rows.length} more rules not shown. `}
        Counts are gap records — one person can have gaps under several rules. Gap types:{" "}
        {model.gapsByType.map((t, i) => (
          <span key={t.key}>
            {i > 0 && " · "}
            {t.label} {t.count}
          </span>
        ))}
        {model.gapsByType.length === 0 && "none"}.
      </Footnote>
    </Card>
  );
}

export function EvidenceCard({ model }: { model: PopulationModel }) {
  return (
    <Card label="Evidence completeness">
      <SectionHeader
        eyebrow="Evidence completeness"
        title="Is screening history on record?"
        description="People per programme by availability of their screening or visit history."
      />
      <div className="flex flex-col gap-5">
        {model.programmes.map((prog) => {
          const total = prog.people;
          return (
            <div key={prog.id}>
              <div className="mb-1.5 flex items-baseline justify-between text-sm">
                <span className="flex items-center gap-2 font-medium text-foreground">
                  <ProgrammeDot pathway={prog.pathway} />
                  {pathwayLabel(prog.pathway)}
                </span>
                <span className="font-mono text-xs tabular-nums text-muted">{total} people</span>
              </div>
              {total === 0 ? (
                <p className="text-xs text-faint">No people in this filter set.</p>
              ) : (
                <>
                  <div
                    className="flex h-3 w-full gap-px overflow-hidden rounded-sm bg-surface-sunken"
                    role="img"
                    aria-label={`${pathwayLabel(prog.pathway)} history: ${(Object.keys(prog.history) as HistoryStatus[])
                      .map((h) => `${HISTORY_LABEL[h]} ${prog.history[h]}`)
                      .join(", ")}`}
                  >
                    {(Object.keys(prog.history) as HistoryStatus[]).map((h) =>
                      prog.history[h] > 0 ? (
                        <div
                          key={h}
                          className="grow-x"
                          style={{
                            width: `${(prog.history[h] / total) * 100}%`,
                            backgroundColor: SEGMENT_COLOR[HISTORY_SEGMENT[h]].paper,
                          }}
                        />
                      ) : null
                    )}
                  </div>
                  <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                    {(Object.keys(prog.history) as HistoryStatus[]).map((h) => (
                      <li key={h} className="flex items-center gap-1.5 text-muted">
                        <SegmentGlyph segment={HISTORY_SEGMENT[h]} />
                        {HISTORY_LABEL[h]}
                        <span className="font-mono tabular-nums text-foreground">{prog.history[h]}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          );
        })}
      </div>
      <Footnote>
        From each person’s <span className="font-mono">history_by_pathway</span>. Unavailable history
        evaluates to “unknown”; partial history routes to clinical review.
      </Footnote>
    </Card>
  );
}

export function SegmentationCard({ model }: { model: PopulationModel }) {
  const max = Math.max(...model.byRegion.map((r) => r.total), 1);
  return (
    <Card label="Population segmentation">
      <SectionHeader
        eyebrow="Population segmentation"
        title="Where people live"
        description="People per region, split by programme."
      />
      <ul className="flex flex-col gap-3">
        {model.byRegion.map((r) => (
          <li key={r.regionId}>
            <div className="flex items-baseline justify-between text-sm">
              <span className="text-foreground">{r.label}</span>
              <span className="font-mono text-xs tabular-nums text-muted">{r.total}</span>
            </div>
            <div
              className="mt-1 flex h-2 gap-px"
              role="img"
              aria-label={`${r.label}: ${PATHWAY_OPTIONS.map((o) => `${o.short} ${r.byPathway[o.value]}`).join(", ")}`}
            >
              {PATHWAY_OPTIONS.map((o) =>
                r.byPathway[o.value] > 0 ? (
                  <div
                    key={o.value}
                    className="grow-x h-2 first:rounded-l-sm last:rounded-r-sm"
                    style={{ width: `${(r.byPathway[o.value] / max) * 100}%`, backgroundColor: PROGRAMME_COLOR[o.value].paper }}
                  />
                ) : null
              )}
            </div>
            <p className="mt-0.5 text-[11px] text-faint">
              {PATHWAY_OPTIONS.map((o) => `${o.short} ${r.byPathway[o.value]}`).join(" · ")}
            </p>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        {PATHWAY_OPTIONS.map((o) => (
          <span key={o.value} className="flex items-center gap-1.5">
            <ProgrammeDot pathway={o.value} /> {o.label}
          </span>
        ))}
      </div>
      <Footnote>
        Sex:{" "}
        {model.bySex.map((s, i) => (
          <span key={s.key}>
            {i > 0 && " · "}
            {s.label} <span className="font-mono">{s.count}</span>
          </span>
        ))}
        {model.bySex.length === 0 && "none"}. Age groups per programme are on each programme page.
      </Footnote>
    </Card>
  );
}

const STATUS_ORDER: EvaluationStatus[] = [
  "due",
  "upcoming",
  "eligible",
  "completed",
  "requires_clinical_review",
  "insufficient_information",
  "unknown",
  "not_eligible",
];

export function EvaluationStatusCard({ summary }: { summary: LoadState<DashboardSummaryOut> }) {
  return (
    <Card label="Rule evaluation outcomes">
      <SectionHeader
        eyebrow="Whole population · filters not applied"
        title="Rule evaluation outcomes"
        description="Deterministic evaluations of every rule for every person (people × rules), from the dashboard summary."
      />
      {summary.status === "loading" && <LoadingState rows={3} />}
      {summary.status === "error" && (
        <p role="alert" className="flex items-start gap-2 text-sm text-muted">
          <AlertTriangle size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-status-error" />
          Evaluation outcomes are unavailable: {summary.message}
        </p>
      )}
      {summary.status === "ready" && <StatusSpectrum data={summary.data} />}
    </Card>
  );
}

function StatusSpectrum({ data }: { data: DashboardSummaryOut }) {
  const counts = data.evaluation_status_counts;
  const known = STATUS_ORDER.filter((s) => (counts[s] ?? 0) > 0);
  const total = Object.values(counts).reduce((n, c) => n + c, 0);
  const knownTotal = known.reduce((n, s) => n + counts[s], 0);
  if (knownTotal === 0)
    return <EmptyState icon={BarChart3} title="No evaluations" description="The evaluation run returned no results." />;
  return (
    <>
      <div
        className="flex h-4 w-full gap-px overflow-hidden rounded-sm"
        role="img"
        aria-label={`Rule evaluation statuses: ${known.map((s) => `${statusLabel(s)} ${counts[s]}`).join(", ")}`}
      >
        {known.map((s) => (
          <div key={s} className="grow-x" style={{ width: `${(counts[s] / knownTotal) * 100}%`, backgroundColor: statusColor(s) }} />
        ))}
      </div>
      <ul className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {known.map((s) => (
          <li key={s} className="flex items-center gap-2 text-xs">
            <StatusGlyph status={s} size={12} />
            <span className="flex-1 text-muted">{statusLabel(s)}</span>
            <span className="font-mono tabular-nums text-foreground">{counts[s]}</span>
          </li>
        ))}
      </ul>
      <Footnote>
        {total} evaluations · run {data.evaluation_run_id} · reference date {data.reference_date}. Rules:{" "}
        {data.rules_summary.total_rules} ({data.rules_summary.review_flagged_rules} review-flagged,{" "}
        {data.rules_summary.unresolved_rules} unresolved) · clinical review status:{" "}
        {data.rules_summary.clinical_review_status.replace("_", " ")}.
      </Footnote>
    </>
  );
}
