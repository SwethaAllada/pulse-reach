"use client";

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
import { useLocale } from "@/lib/i18n/use-locale";

const HISTORY_SEGMENT: Record<HistoryStatus, SegmentId> = {
  available: "available",
  partial: "partial",
  not_available: "not_available",
};
const HISTORY_LABEL: Record<HistoryStatus, "pop.history.available" | "pop.history.partial" | "pop.history.not_available"> = {
  available: "pop.history.available",
  partial: "pop.history.partial",
  not_available: "pop.history.not_available",
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
  const { t, number } = useLocale();
  const rows = model.gapsByRule.slice(0, 8);
  const max = rows[0]?.count ?? 0;
  return (
    <Card label={t("pop.rules.label")}>
      <SectionHeader eyebrow={t("pop.rules.eyebrow")} title={t("pop.rules.title")} description={t("pop.rules.desc")} />
      {rows.length === 0 ? (
        <EmptyState icon={BarChart3} title={t("pop.rules.empty_title")} description={t("pop.rules.empty_desc")} />
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map((r) => (
            <li key={r.key}>
              <div className="flex items-baseline justify-between gap-3 text-xs">
                <span className="flex min-w-0 items-center gap-2">
                  <ProgrammeDot pathway={r.pathway} />
                  <span className="truncate text-muted" title={`${r.label} (${r.key})`} dir="auto">
                    {r.label}
                  </span>
                </span>
                <span className="font-mono tabular-nums text-foreground">{number(r.count)}</span>
              </div>
              <div className="mt-1 h-1.5 rounded-full bg-surface-sunken">
                <div
                  className="grow-x h-1.5 rounded-full"
                  style={{ width: `${(r.count / max) * 100}%`, backgroundColor: "var(--segment-gap)" }}
                />
              </div>
              <p className="mt-0.5 font-mono text-[10px] text-faint">
                <span className="ltr-value">{r.key}</span>
              </p>
            </li>
          ))}
        </ul>
      )}
      <Footnote>
        {model.gapsByRule.length > rows.length && `${t("pop.rules.more", { count: model.gapsByRule.length - rows.length })} `}
        {t("pop.rules.footnote")}{" "}
        {model.gapsByType.map((g, i) => (
          <span key={g.key}>
            {i > 0 && " · "}
            {g.label} {number(g.count)}
          </span>
        ))}
        {model.gapsByType.length === 0 && t("pop.none")}.
      </Footnote>
    </Card>
  );
}

export function EvidenceCard({ model }: { model: PopulationModel }) {
  const { t, rich, number } = useLocale();
  return (
    <Card label={t("pop.evidence.eyebrow")}>
      <SectionHeader eyebrow={t("pop.evidence.eyebrow")} title={t("pop.evidence.title")} description={t("pop.evidence.desc")} />
      <div className="flex flex-col gap-5">
        {model.programmes.map((prog) => {
          const total = prog.people;
          return (
            <div key={prog.id}>
              <div className="mb-1.5 flex items-baseline justify-between text-sm">
                <span className="flex items-center gap-2 font-medium text-foreground">
                  <ProgrammeDot pathway={prog.pathway} />
                  {pathwayLabel(prog.pathway, t)}
                </span>
                <span className="font-mono text-xs tabular-nums text-muted">{t("pop.people_n", { count: total })}</span>
              </div>
              {total === 0 ? (
                <p className="text-xs text-faint">{t("pop.evidence.none")}</p>
              ) : (
                <>
                  <div
                    className="flex h-3 w-full gap-px overflow-hidden rounded-sm bg-surface-sunken"
                    role="img"
                    aria-label={t("pop.evidence.aria", {
                      programme: pathwayLabel(prog.pathway, t),
                      values: (Object.keys(prog.history) as HistoryStatus[]).map((h) => `${t(HISTORY_LABEL[h])} ${prog.history[h]}`).join(t("list.sep")),
                    })}
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
                        {t(HISTORY_LABEL[h])}
                        <span className="font-mono tabular-nums text-foreground">{number(prog.history[h])}</span>
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
        {rich("pop.evidence.footnote", { field: <span className="font-mono">history_by_pathway</span> })}
      </Footnote>
    </Card>
  );
}

export function SegmentationCard({ model }: { model: PopulationModel }) {
  const { t, number } = useLocale();
  const max = Math.max(...model.byRegion.map((r) => r.total), 1);
  return (
    <Card label={t("pop.segmentation.eyebrow")}>
      <SectionHeader eyebrow={t("pop.segmentation.eyebrow")} title={t("pop.segmentation.title")} description={t("pop.segmentation.desc")} />
      <ul className="flex flex-col gap-3">
        {model.byRegion.map((r) => (
          <li key={r.regionId}>
            <div className="flex items-baseline justify-between text-sm">
              <span className="text-foreground">{r.label}</span>
              <span className="font-mono text-xs tabular-nums text-muted">{number(r.total)}</span>
            </div>
            <div
              className="mt-1 flex h-2 gap-px"
              role="img"
              aria-label={`${r.label}: ${PATHWAY_OPTIONS.map((o) => `${t(o.short)} ${r.byPathway[o.value]}`).join(t("list.sep"))}`}
            >
              {PATHWAY_OPTIONS.map((o) =>
                r.byPathway[o.value] > 0 ? (
                  <div
                    key={o.value}
                    className="grow-x h-2 first:rounded-s-sm last:rounded-e-sm"
                    style={{ width: `${(r.byPathway[o.value] / max) * 100}%`, backgroundColor: PROGRAMME_COLOR[o.value].paper }}
                  />
                ) : null
              )}
            </div>
            <p className="mt-0.5 text-[11px] text-faint">
              {PATHWAY_OPTIONS.map((o) => `${t(o.short)} ${number(r.byPathway[o.value])}`).join(" · ")}
            </p>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        {PATHWAY_OPTIONS.map((o) => (
          <span key={o.value} className="flex items-center gap-1.5">
            <ProgrammeDot pathway={o.value} /> {t(o.label)}
          </span>
        ))}
      </div>
      <Footnote>
        {t("pop.segmentation.sex")}{" "}
        {model.bySex.map((s, i) => (
          <span key={s.key}>
            {i > 0 && " · "}
            {s.label} <span className="font-mono">{number(s.count)}</span>
          </span>
        ))}
        {model.bySex.length === 0 && t("pop.none")}. {t("pop.segmentation.age_note")}
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
  const { t } = useLocale();
  return (
    <Card label={t("pop.outcomes.title")}>
      <SectionHeader eyebrow={t("pop.outcomes.eyebrow")} title={t("pop.outcomes.title")} description={t("pop.outcomes.desc")} />
      {summary.status === "loading" && <LoadingState rows={3} />}
      {summary.status === "error" && (
        <p role="alert" className="flex items-start gap-2 text-sm text-muted">
          <AlertTriangle size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-status-error" />
          {t("pop.outcomes.unavailable", { message: summary.message })}
        </p>
      )}
      {summary.status === "ready" && <StatusSpectrum data={summary.data} />}
    </Card>
  );
}

function StatusSpectrum({ data }: { data: DashboardSummaryOut }) {
  const { t: tr, number } = useLocale();
  const counts = data.evaluation_status_counts;
  const known = STATUS_ORDER.filter((s) => (counts[s] ?? 0) > 0);
  const total = Object.values(counts).reduce((n, c) => n + c, 0);
  const knownTotal = known.reduce((n, s) => n + counts[s], 0);
  if (knownTotal === 0)
    return <EmptyState icon={BarChart3} title={tr("pop.outcomes.empty_title")} description={tr("pop.outcomes.empty_desc")} />;
  return (
    <>
      <div
        className="flex h-4 w-full gap-px overflow-hidden rounded-sm"
        role="img"
        aria-label={tr("pop.outcomes.aria", { values: known.map((s) => `${statusLabel(s, tr)} ${counts[s]}`).join(tr("list.sep")) })}
      >
        {known.map((s) => (
          <div key={s} className="grow-x" style={{ width: `${(counts[s] / knownTotal) * 100}%`, backgroundColor: statusColor(s) }} />
        ))}
      </div>
      <ul className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {known.map((s) => (
          <li key={s} className="flex items-center gap-2 text-xs">
            <StatusGlyph status={s} size={12} />
            <span className="flex-1 text-muted">{statusLabel(s, tr)}</span>
            <span className="font-mono tabular-nums text-foreground">{number(counts[s])}</span>
          </li>
        ))}
      </ul>
      <Footnote>
        {tr("pop.outcomes.footnote", {
          total,
          run: data.evaluation_run_id,
          date: data.reference_date,
          rules: data.rules_summary.total_rules,
          flagged: data.rules_summary.review_flagged_rules,
          unresolved: data.rules_summary.unresolved_rules,
          review: data.rules_summary.clinical_review_status,
        })}
      </Footnote>
    </>
  );
}
