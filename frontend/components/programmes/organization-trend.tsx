import { ArrowDownRight, ArrowRight, ArrowUpRight, CircleHelp } from "lucide-react";
import type { PopulationSummaryOut, ProgrammeSummaryOut } from "@/lib/api/types";
import { Footnote } from "@/components/ui/plate";
import { cn } from "@/lib/cn";

const TREND: Record<string, { label: string; icon: typeof ArrowRight }> = {
  INCREASING: { label: "Increasing", icon: ArrowUpRight },
  DECREASING: { label: "Decreasing", icon: ArrowDownRight },
  STABLE: { label: "Stable", icon: ArrowRight },
  INSUFFICIENT_DATA: { label: "Not enough history to call a trend", icon: CircleHelp },
};

const REASONS: Record<string, string> = {
  history_incomplete: "the comparison period starts before care-gap history begins",
  evaluation_history_incomplete: "no persisted evaluation run covers the previous period, so it was not observed",
};

function Compare({
  label,
  current,
  previous,
  i,
  previousText = "Suppressed",
  window = "90 days",
}: {
  label: string;
  current: number | null;
  previous: number | null;
  i: number;
  previousText?: string;
  window?: string;
}) {
  const max = Math.max(1, current ?? 0, previous ?? 0);
  return (
    <div className="reveal" style={{ "--i": i } as React.CSSProperties}>
      <p className="text-xs font-medium text-faint">{label}</p>
      <dl className="mt-2 flex flex-col gap-1.5">
        {(
          [
            [`Last ${window}`, current, "var(--accent)", "Suppressed"],
            [`Previous ${window}`, previous, "var(--border-strong)", previousText],
          ] as const
        ).map(([name, v, color, empty]) => (
          <div key={name} className="grid grid-cols-[110px_minmax(0,1fr)_80px] items-center gap-3 text-xs">
            <dt className="text-muted">{name}</dt>
            <dd className="h-2 rounded-full bg-surface-sunken">
              {v !== null && (
                <span
                  className="grow-x block h-2 rounded-full"
                  style={{ width: `${(v / max) * 100}%`, backgroundColor: color } as React.CSSProperties}
                />
              )}
            </dd>
            <dd className="text-right font-mono tabular-nums text-foreground">{v ?? empty}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/**
 * Organization-wide preventive-care signal from `GET /population/summary`. It spans
 * every programme — the API exposes no per-programme trend — and says so.
 */
export function OrganizationTrend({ data }: { data: PopulationSummaryOut }) {
  const pc = data.preventive_care;
  const pm = pc.period_metrics;
  const coverage = pc.preventive_coverage;
  const trend = pm ? TREND[pm.care_gap_trend.direction] ?? { label: pm.care_gap_trend.direction, icon: CircleHelp } : null;
  const TrendIcon = trend?.icon ?? CircleHelp;
  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <div className="reveal">
        <p className="text-xs font-medium text-faint">Preventive coverage · all programmes</p>
        <p className="figure mt-2 text-[40px] text-foreground">
          {coverage === null ? "—" : `${Math.round(coverage * 100)}`}
          {coverage !== null && <span className="text-3xl text-muted">%</span>}
        </p>
        <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted">
          Backend definition: <span className="text-foreground">{pc.preventive_coverage_definition}</span>.
        </p>
        <p className="mt-2 text-xs text-faint">
          {pc.in_scope_patients ?? "Suppressed"} in-scope people · {pc.in_scope_patients_with_open_gap ?? "suppressed"} with an
          open gap · as of {data.as_of}
        </p>
      </div>
      {pm ? (
        <div className="flex flex-col gap-5">
          <Compare label="Documented screening completions" current={pm.screening_completions} previous={pm.previous_screening_completions} i={1} />
          <Compare label="Care gaps identified" current={pm.care_gaps_identified} previous={pm.previous_care_gaps_identified} i={2} />
          <p className={cn("reveal flex items-start gap-2 text-sm", "text-foreground")} style={{ "--i": 3 } as React.CSSProperties}>
            <TrendIcon size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-accent" />
            <span>
              Care-gap trend: {trend?.label}
              {pm.care_gap_trend.reason_codes.length > 0 && (
                <span className="text-muted">
                  {" "}
                  — {pm.care_gap_trend.reason_codes.map((c) => REASONS[c] ?? c).join("; ")}
                  {pc.care_gap_history_start ? ` (history from ${pc.care_gap_history_start})` : ""}.
                </span>
              )}
            </span>
          </p>
        </div>
      ) : (
        <p className="text-sm text-muted">No period comparison was returned.</p>
      )}
      <Footnote className="lg:col-span-2">
        {pm && `${pm.current_start} – ${pm.current_end} vs ${pm.previous_start} – ${pm.previous_end}. `}
        {[...pc.suppressed, ...(pm?.suppressed ?? [])].length > 0 &&
          `Suppressed for privacy (small cells): ${[...pc.suppressed, ...(pm?.suppressed ?? [])].map((s) => s.replace(/_/g, " ")).join(", ")}. `}
        {data.disclaimer}
      </Footnote>
    </div>
  );
}

const WINDOW_LABEL: Record<string, string> = { "7d": "7 days", "30d": "30 days", "90d": "90 days", "6m": "6 months", "12m": "12 months" };

/**
 * Programme-specific period comparison from `GET /programmes/{pathway}/summary`. The backend
 * reports the previous window only when persisted evaluation runs cover it; otherwise it is
 * "not observed" (never zero) and no direction is drawn.
 */
export function ProgrammeTrend({ data, name }: { data: ProgrammeSummaryOut; name: string }) {
  const t = data.trend;
  const window = WINDOW_LABEL[t.period] ?? t.period;
  const trend = TREND[t.care_gap_trend.direction] ?? { label: t.care_gap_trend.direction, icon: CircleHelp };
  const TrendIcon = trend.icon;
  const notObserved = t.previous_period_observed ? "Suppressed" : "Not observed";
  return (
    <div className="flex flex-col gap-5">
      <Compare label={`${name} care gaps identified`} current={t.care_gaps_identified} previous={t.previous_care_gaps_identified} previousText={notObserved} window={window} i={0} />
      <Compare label={`${name} gaps closed by documented completion`} current={t.gaps_closed_completed} previous={t.previous_gaps_closed_completed} previousText={notObserved} window={window} i={1} />
      <p className="reveal flex items-start gap-2 text-sm text-foreground" style={{ "--i": 2 } as React.CSSProperties}>
        <TrendIcon size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-accent" />
        <span>
          {name} care-gap trend: {trend.label}
          {t.care_gap_trend.reason_codes.length > 0 && (
            <span className="text-muted"> — {t.care_gap_trend.reason_codes.map((c) => REASONS[c] ?? c.replace(/_/g, " ")).join("; ")}.</span>
          )}
        </span>
      </p>
      <Footnote>
        {t.current_start} – {t.current_end} vs {t.previous_start} – {t.previous_end}. Care-gap records come from{" "}
        {t.evaluation_runs} persisted evaluation run{t.evaluation_runs === 1 ? "" : "s"}
        {t.evaluation_history_start ? `, the earliest on ${t.evaluation_history_start}` : ""}
        {t.previous_period_observed ? "." : "; earlier periods are unobserved, not zero, so no historical trend is drawn."}
      </Footnote>
    </div>
  );
}
