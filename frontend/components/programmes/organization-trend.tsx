"use client";

import { ArrowDownRight, ArrowRight, ArrowUpRight, CircleHelp } from "lucide-react";
import type { PopulationSummaryOut, ProgrammeSummaryOut } from "@/lib/api/types";
import { Footnote } from "@/components/ui/plate";
import { cn } from "@/lib/cn";
import type { MessageKey, Translate } from "@/lib/i18n/translate";
import { useLocale } from "@/lib/i18n/use-locale";

/* Trend glyphs describe the value's direction, not reading order: they are not mirrored in RTL. */
const TREND: Record<string, { label: MessageKey; icon: typeof ArrowRight }> = {
  INCREASING: { label: "prog.trend.increasing", icon: ArrowUpRight },
  DECREASING: { label: "prog.trend.decreasing", icon: ArrowDownRight },
  STABLE: { label: "prog.trend.stable", icon: ArrowRight },
  INSUFFICIENT_DATA: { label: "prog.trend.insufficient", icon: CircleHelp },
};

const REASONS: Record<string, MessageKey> = {
  history_incomplete: "prog.trend.reason_history",
  evaluation_history_incomplete: "prog.trend.reason_evaluation",
};

const trendLabel = (direction: string, t: Translate) => (TREND[direction] ? t(TREND[direction].label) : direction);
const reasonText = (code: string, t: Translate) => (REASONS[code] ? t(REASONS[code]) : code.replace(/_/g, " "));

function Compare({
  label,
  current,
  previous,
  i,
  previousText,
  window,
}: {
  label: string;
  current: number | null;
  previous: number | null;
  i: number;
  previousText?: string;
  window?: string;
}) {
  const { t, number } = useLocale();
  const win = window ?? t("prog.window.90d");
  const max = Math.max(1, current ?? 0, previous ?? 0);
  return (
    <div className="reveal" style={{ "--i": i } as React.CSSProperties}>
      <p className="text-xs font-medium text-faint">{label}</p>
      <dl className="mt-2 flex flex-col gap-1.5">
        {(
          [
            [t("prog.trend.last", { window: win }), current, "var(--accent)", t("prog.trend.suppressed")],
            [t("prog.trend.previous", { window: win }), previous, "var(--border-strong)", previousText ?? t("prog.trend.suppressed")],
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
            <dd className="text-end font-mono tabular-nums text-foreground">{v === null ? empty : number(v)}</dd>
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
  const { t, rich, number } = useLocale();
  const pc = data.preventive_care;
  const pm = pc.period_metrics;
  const coverage = pc.preventive_coverage;
  const TrendIcon = (pm && TREND[pm.care_gap_trend.direction]?.icon) || CircleHelp;
  const suppressed = [...pc.suppressed, ...(pm?.suppressed ?? [])];
  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <div className="reveal">
        <p className="text-xs font-medium text-faint">{t("prog.org.coverage")}</p>
        <p className="figure mt-2 text-[40px] text-foreground">
          {coverage === null ? "—" : `${Math.round(coverage * 100)}`}
          {coverage !== null && <span className="text-3xl text-muted">%</span>}
        </p>
        <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted">
          {rich("prog.org.definition", { definition: <span className="text-foreground">{pc.preventive_coverage_definition}</span> })}
        </p>
        <p className="mt-2 text-xs text-faint">
          {t("prog.org.in_scope", {
            people: pc.in_scope_patients === null ? t("prog.trend.suppressed") : number(pc.in_scope_patients),
            with_gap: pc.in_scope_patients_with_open_gap === null ? t("prog.trend.suppressed") : number(pc.in_scope_patients_with_open_gap),
            date: data.as_of,
          })}
        </p>
      </div>
      {pm ? (
        <div className="flex flex-col gap-5">
          <Compare label={t("prog.org.completions")} current={pm.screening_completions} previous={pm.previous_screening_completions} i={1} />
          <Compare label={t("prog.org.identified")} current={pm.care_gaps_identified} previous={pm.previous_care_gaps_identified} i={2} />
          <p className={cn("reveal flex items-start gap-2 text-sm", "text-foreground")} style={{ "--i": 3 } as React.CSSProperties}>
            <TrendIcon size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-accent" />
            <span>
              {t("prog.org.trend", { trend: trendLabel(pm.care_gap_trend.direction, t) })}
              {pm.care_gap_trend.reason_codes.length > 0 && (
                <span className="text-muted">
                  {" "}
                  — {pm.care_gap_trend.reason_codes.map((c) => reasonText(c, t)).join(t("list.sep_strong"))}
                  {pc.care_gap_history_start ? ` ${t("prog.org.history_from", { date: pc.care_gap_history_start })}` : ""}.
                </span>
              )}
            </span>
          </p>
        </div>
      ) : (
        <p className="text-sm text-muted">{t("prog.org.no_comparison")}</p>
      )}
      <Footnote className="lg:col-span-2">
        {pm && `${t("prog.trend.periods", { cs: pm.current_start, ce: pm.current_end, ps: pm.previous_start, pe: pm.previous_end })} `}
        {suppressed.length > 0 && `${t("prog.org.suppressed", { fields: suppressed.map((s) => s.replace(/_/g, " ")).join(t("list.sep")) })} `}
        {data.disclaimer}
      </Footnote>
    </div>
  );
}

const WINDOW_LABEL: Record<string, MessageKey> = {
  "7d": "prog.window.7d",
  "30d": "prog.window.30d",
  "90d": "prog.window.90d",
  "6m": "prog.window.6m",
  "12m": "prog.window.12m",
};

/**
 * Programme-specific period comparison from `GET /programmes/{pathway}/summary`. The backend
 * reports the previous window only when persisted evaluation runs cover it; otherwise it is
 * "not observed" (never zero) and no direction is drawn.
 */
export function ProgrammeTrend({ data, name }: { data: ProgrammeSummaryOut; name: string }) {
  const { t, tp } = useLocale();
  const tr = data.trend;
  const window = WINDOW_LABEL[tr.period] ? t(WINDOW_LABEL[tr.period]) : tr.period;
  const TrendIcon = TREND[tr.care_gap_trend.direction]?.icon ?? CircleHelp;
  const notObserved = t(tr.previous_period_observed ? "prog.trend.suppressed" : "prog.trend.not_observed");
  return (
    <div className="flex flex-col gap-5">
      <Compare label={t("prog.trend.identified", { programme: name })} current={tr.care_gaps_identified} previous={tr.previous_care_gaps_identified} previousText={notObserved} window={window} i={0} />
      <Compare label={t("prog.trend.closed", { programme: name })} current={tr.gaps_closed_completed} previous={tr.previous_gaps_closed_completed} previousText={notObserved} window={window} i={1} />
      <p className="reveal flex items-start gap-2 text-sm text-foreground" style={{ "--i": 2 } as React.CSSProperties}>
        <TrendIcon size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-accent" />
        <span>
          {t("prog.trend.programme", { programme: name, trend: trendLabel(tr.care_gap_trend.direction, t) })}
          {tr.care_gap_trend.reason_codes.length > 0 && (
            <span className="text-muted"> — {tr.care_gap_trend.reason_codes.map((c) => reasonText(c, t)).join(t("list.sep_strong"))}.</span>
          )}
        </span>
      </p>
      <Footnote>
        {t("prog.trend.periods", { cs: tr.current_start, ce: tr.current_end, ps: tr.previous_start, pe: tr.previous_end })}{" "}
        {tp("prog.trend.runs", tr.evaluation_runs)}
        {tr.evaluation_history_start ? t("prog.trend.earliest", { date: tr.evaluation_history_start }) : ""}
        {tr.previous_period_observed ? "." : t("prog.trend.unobserved")}
      </Footnote>
    </div>
  );
}
