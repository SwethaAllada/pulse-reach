"use client";

import { AlertTriangle, ChevronDown, FileText, LoaderCircle } from "lucide-react";
import type { RuleSummaryOut } from "@/lib/api/types";
import { StatusGlyph, StatusLabel } from "@/components/ui/status-glyph";
import { pathwayLabel } from "@/lib/population/filters";
import { ruleShortLabel } from "@/lib/population/model";
import {
  TRACE_ORIGIN_META,
  ageLabel,
  asEvaluationStatus,
  gapEvidenceRefs,
  gapStatusMeta,
  gapTypeMeta,
  historyMeta,
  reasonCodeLabel,
  ruleCriteria,
  sexLabel,
  traceReasons,
  type TraceItem,
  type TraceOrigin,
} from "@/lib/people/person";
import { useExplanation, useRuleDetail, type PersonProfileData } from "@/lib/people/use-people-data";
import { cn } from "@/lib/cn";
import { ProfileSection } from "./profile-section";
import { useLocale } from "@/lib/i18n/use-locale";

const ORIGINS: TraceOrigin[] = ["care_gap", "person_evidence", "rule_review", "documented"];

export function EvidenceTraceSection({
  data,
  items,
  expanded,
  onToggle,
}: {
  data: PersonProfileData;
  items: TraceItem[];
  expanded: Set<string>;
  onToggle: (evaluationId: string) => void;
}) {
  const { t } = useLocale();
  return (
    <ProfileSection
      id="evidence"
      title={t("trace.title")}
      description={t("trace.desc")}
    >
      {items.length === 0 ? (
        <p className="rounded-md border border-dashed border-border-strong px-4 py-3 text-sm text-muted">{t("trace.none")}</p>
      ) : (
        <div className="flex flex-col gap-8">
          {ORIGINS.map((origin) => {
            const group = items.filter((i) => i.origin === origin);
            if (group.length === 0) return null;
            return (
              <div key={origin}>
                <h3 className="text-sm font-semibold text-foreground">
                  {t(TRACE_ORIGIN_META[origin].title)} <span className="font-mono text-xs text-faint">({group.length})</span>
                </h3>
                <p className="mb-3 text-xs text-muted">{t(TRACE_ORIGIN_META[origin].description)}</p>
                <ul className="flex flex-col gap-2">
                  {group.map((item) => (
                    <li key={item.evaluation.evaluation_id}>
                      <TraceCard
                        item={item}
                        data={data}
                        rule={data.rules.get(item.evaluation.rule_id)}
                        open={expanded.has(item.evaluation.evaluation_id)}
                        onToggle={() => onToggle(item.evaluation.evaluation_id)}
                      />
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </ProfileSection>
  );
}

function TraceCard({
  item,
  data,
  rule,
  open,
  onToggle,
}: {
  item: TraceItem;
  data: PersonProfileData;
  rule: RuleSummaryOut | undefined;
  open: boolean;
  onToggle: () => void;
}) {
  const e = item.evaluation;
  const status = asEvaluationStatus(e.evaluation_status);
  const panelId = `trace-panel-${e.evaluation_id}`;
  const { t } = useLocale();
  return (
    <article
      id={`trace-${e.evaluation_id}`}
      className={cn(
        "scroll-mt-36 rounded-lg border bg-surface shadow-[var(--shadow-card)] transition-colors",
        open ? "border-border-strong" : "border-border"
      )}
    >
      <h4>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggle}
          className="flex w-full items-start gap-3 rounded-lg px-4 py-3 text-start transition-colors hover:bg-accent-soft"
        >
          <span className="mt-1">{status ? <StatusGlyph status={status} /> : <StatusGlyph status="unknown" />}</span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium text-foreground" dir="auto">{ruleShortLabel(rule, e.rule_id)}</span>
            <span className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">
              <span className="font-mono ltr-value">{e.rule_id}</span>
              <span>{status ? <StatusLabel status={status} className="text-xs" /> : t("trace.status_raw", { status: e.evaluation_status })}</span>
              {item.gaps.map((g) => (
                <span key={g.care_gap_id}>
                  {gapTypeMeta(g.gap_type, t).label} · {gapStatusMeta(g.status, t).label}
                </span>
              ))}
            </span>
          </span>
          <ChevronDown size={16} aria-hidden="true" className={cn("mt-1 shrink-0 text-faint transition-transform", open && "rotate-180")} />
        </button>
      </h4>
      {open && (
        <div id={panelId} className="border-t border-border px-4 pb-4 pt-3">
          <TraceDetail item={item} data={data} rule={rule} />
        </div>
      )}
    </article>
  );
}

function Step({ n, title, question, children }: { n: number; title: string; question: string; children: React.ReactNode }) {
  return (
    <li className="group relative grid grid-cols-[1.75rem_minmax(0,1fr)] gap-3 pb-5 last:pb-0">
      <span aria-hidden="true" className="absolute bottom-0 start-[0.8rem] top-7 w-px bg-border group-last:hidden" />
      <span className="flex size-7 items-center justify-center rounded-full border border-border-strong bg-surface-sunken font-mono text-xs text-muted">
        {n}
      </span>
      <div className="min-w-0">
        <h5 className="text-sm font-semibold text-foreground">
          {title} <span className="font-normal text-faint">— {question}</span>
        </h5>
        <div className="mt-1.5 text-sm text-muted">{children}</div>
      </div>
    </li>
  );
}

function KV({ rows }: { rows: { label: string; value: React.ReactNode; note?: string }[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-[minmax(9rem,max-content)_minmax(0,1fr)]">
      {rows.map((r, i) => (
        <div key={i} className="contents">
          <dt className="text-xs text-faint sm:pt-0.5">{r.label}</dt>
          <dd className="text-sm text-foreground" dir="auto">
            {r.value}
            {r.note && <span className="block text-xs text-status-insufficient">{r.note}</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function TraceDetail({ item, data, rule }: { item: TraceItem; data: PersonProfileData; rule: RuleSummaryOut | undefined }) {
  const e = item.evaluation;
  const { patient, evaluations } = data;
  const detail = useRuleDetail(e.rule_id, true);
  const explanation = useExplanation(patient.patient_id, e.rule_id);
  const status = asEvaluationStatus(e.evaluation_status);
  const { t, rich } = useLocale();
  const refs = item.gaps.flatMap((g) => gapEvidenceRefs(g, t));

  return (
    <ol className="flex flex-col">
      <Step n={1} title={t("trace.s1")} question={t("trace.s1_q")}>
        {rule ? (
          <>
            <p className="text-foreground" dir="auto">{rule.description}</p>
            <div className="mt-2">
              <KV
                rows={[
                  { label: t("prog.rule.eyebrow"), value: <span className="font-mono text-xs ltr-value">{e.rule_id} v{e.rule_version}</span> },
                  { label: t("pop.filter.programme"), value: pathwayLabel(e.pathway, t) },
                  { label: t("trace.source"), value: `${rule.source_name} (${rule.source_version})` },
                  { label: t("trace.reference"), value: rule.source_reference },
                  {
                    label: t("trace.verification"),
                    value: [
                      rule.verification_status,
                      t(rule.is_authoritative ? "prog.rule.authoritative" : "prog.rule.non_authoritative"),
                      ...(rule.requires_clinical_review ? [t("prog.rule.flagged")] : []),
                    ].join(" · "),
                    note: t("trace.verified_note"),
                  },
                  ...(rule.effective_date_text ? [{ label: t("trace.effective"), value: rule.effective_date_text }] : []),
                  ...(rule.open_question_ids.length > 0 ? [{ label: t("prog.sec.oq_eyebrow"), value: rule.open_question_ids.join(", ") }] : []),
                ]}
              />
            </div>
          </>
        ) : (
          <p>{rich("trace.no_rule", { id: <span className="font-mono">{e.rule_id}</span> })}</p>
        )}
        <div className="mt-3 rounded-md bg-surface-sunken px-3 py-2">
          <p className="mb-1.5 text-xs font-medium text-faint">{t("trace.criteria")}</p>
          {detail.state?.status === "loading" && (
            <p className="flex items-center gap-2 text-xs">
              <LoaderCircle size={12} aria-hidden="true" className="animate-spin" /> {t("pathway.loading_rule")}
            </p>
          )}
          {detail.state?.status === "error" && (
            <p className="text-xs">
              {t("trace.rule_unavailable", { message: detail.state.message })}{" "}
              <button type="button" onClick={detail.retry} className="font-medium text-accent hover:text-foreground">
                {t("access.retry")}
              </button>
            </p>
          )}
          {detail.state?.status === "ready" &&
            (() => {
              const rows = ruleCriteria(detail.state.data.spec, t);
              return rows.length > 0 ? (
                <KV rows={rows} />
              ) : (
                <p className="text-xs">{t("trace.no_criteria")}</p>
              );
            })()}
        </div>
      </Step>

      <Step n={2} title={t("trace.s2")} question={t("trace.s2_q")}>
        <KV
          rows={[
            { label: t("profile.f_age"), value: ageLabel(patient.date_of_birth, evaluations.reference_date, t) },
            { label: t("pop.filter.sex"), value: sexLabel(patient.sex, t) },
            { label: t("trace.history", { programme: pathwayLabel(e.pathway, t, true) }), value: historyMeta(patient.history_by_pathway[e.pathway], t).label },
            ...refs.map((r) => ({ label: r.label, value: <span className="font-mono text-xs ltr-value">{r.id}</span> })),
          ]}
        />
        <p className="mt-2 rounded-md border border-dashed border-border-strong px-3 py-2 text-xs">
          {rich("trace.not_available", { label: <span className="font-medium text-foreground">{t("trace.not_available_label")}</span> })}
        </p>
      </Step>

      <Step n={3} title={t("trace.s3")} question={t("trace.s3_q")}>
        <KV
          rows={[
            { label: t("trace.result"), value: status ? <StatusLabel status={status} /> : t("assess.unrecognised_status", { status: e.evaluation_status }) },
            ...(e.reason_code ? [{ label: t("trace.reason_code"), value: `${reasonCodeLabel(e.reason_code, t)} (${e.reason_code})` }] : []),
            ...(e.next_due_date ? [{ label: t("trace.next_date"), value: e.next_due_date }] : []),
            { label: t("trace.evaluated_at"), value: <span className="ltr-value">{e.evaluated_at.replace("T", " ").replace("Z", " UTC")}</span> },
            ...item.gaps.map((g) => ({
              label: t("trace.care_gap"),
              value: [
                gapTypeMeta(g.gap_type, t).label,
                gapStatusMeta(g.status, t).label,
                t("prog.rule.identified", { date: g.identified_date }),
                ...(g.closed_date ? [t("prog.rule.closed", { date: g.closed_date })] : []),
              ].join(" · "),
            })),
          ]}
        />
      </Step>

      <Step n={4} title={t("trace.s4")} question={t("trace.s4_q")}>
        <ul className="flex list-disc flex-col gap-1 ps-4">
          {traceReasons(item, t).map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
        {e.reasons.length === 0 && item.gaps.length === 0 && (
          <p className="mt-2 text-xs">{t("trace.no_codes")}</p>
        )}
        <div className="mt-3">
          {explanation.state === null && (
            <button
              type="button"
              onClick={explanation.request}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-accent"
            >
              <FileText size={13} aria-hidden="true" /> {t("trace.show_explanation")}
            </button>
          )}
          {explanation.state?.status === "loading" && (
            <p className="flex items-center gap-2 text-xs">
              <LoaderCircle size={12} aria-hidden="true" className="animate-spin" /> {t("trace.requesting")}
            </p>
          )}
          {explanation.state?.status === "error" && (
            <p className="text-xs">
              {t("trace.explanation_unavailable", { message: explanation.state.message })}{" "}
              <button type="button" onClick={explanation.request} className="font-medium text-accent hover:text-foreground">
                {t("access.retry")}
              </button>
            </p>
          )}
          {explanation.state?.status === "ready" && (
            <div className="rounded-md border border-border bg-surface-sunken px-3 py-2.5 text-xs">
              <p className="mb-1.5 font-semibold uppercase tracking-[0.08em] text-faint">
                {t("trace.explanation")} ·{" "}
                {explanation.state.data.generation_mode === "deterministic_fallback"
                  ? t("trace.deterministic")
                  : t("trace.validated", { mode: explanation.state.data.generation_mode })}
              </p>
              <KV
                rows={[
                  { label: t("trace.summary"), value: explanation.state.data.summary_text },
                  { label: t("trace.why"), value: explanation.state.data.why_text },
                  { label: t("trace.missing"), value: explanation.state.data.missing_or_uncertain_text },
                  { label: t("trace.citation"), value: explanation.state.data.rule_citation_text },
                ]}
              />
              {explanation.state.data.warnings.length > 0 && (
                <ul className="mt-2 flex flex-col gap-0.5 text-status-insufficient">
                  {explanation.state.data.warnings.map((w, i) => (
                    <li key={i} className="flex gap-1.5">
                      <AlertTriangle size={12} aria-hidden="true" className="mt-px shrink-0" />
                      {w}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </Step>
    </ol>
  );
}
