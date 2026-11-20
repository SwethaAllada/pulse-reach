"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, FileText, SearchX } from "lucide-react";
import type { CareGapOut, CareGapStatus, Pathway, RuleDetailOut } from "@/lib/api/types";
import { ruleCriteria, ruleGroup, gapTypeMeta } from "@/lib/people/person";
import { ruleShortLabel } from "@/lib/population/model";
import {
  GAP_STATUS_META,
  GAP_STATUS_ORDER,
  PROGRAMME_META,
  pathwayFromSlug,
  programmeHref,
  RULE_GROUP_META,
  ruleStanding,
  STANDING_META,
} from "@/lib/programmes/model";
import { useRuleView } from "@/lib/programmes/use-programmes-data";
import { PageHeader } from "@/components/ui/page-header";
import { Plate, Footnote } from "@/components/ui/plate";
import { Figure } from "@/components/ui/figure";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";
import { buttonClass } from "@/components/ui/button-styles";
import { BACK, FORWARD } from "@/components/ui/page-transition";
import { StatusGlyph } from "@/components/ui/status-glyph";
import { StandingGlyph } from "./rule-spectrum";
import { ResourceView } from "./resource-state";

export function RuleDetailView() {
  const params = useParams<{ programme: string; ruleId: string }>();
  const slugPathway = pathwayFromSlug(params.programme ?? "");
  const ruleId = decodeURIComponent(params.ruleId ?? "");
  const { detail, gaps, openQuestions, retry } = useRuleView(ruleId);
  const pathway: Pathway = (detail.status === "ready" ? (detail.data.pathway as Pathway) : slugPathway) ?? "ifhas";
  const back = programmeHref(pathway);

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-24 pt-8 sm:px-6 lg:px-8">
      {detail.status === "ready" ? (
        <RuleHeader rule={detail.data} pathway={pathway} back={back} />
      ) : (
        <PageHeader
          eyebrow="Rule"
          title={ruleId}
          breadcrumbs={[{ label: "Programmes", href: "/programmes" }, { label: PROGRAMME_META[pathway].name, href: back }, { label: ruleId }]}
          className="mb-8"
        />
      )}

      <ResourceView
        resource={detail}
        what="Rule definitions"
        onRetry={retry}
        loading={<LoadingState rows={6} label="Loading rule" />}
      >
        {(rule) => (
          <div className="flex flex-col gap-16">
            <div className="grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
              <Plate index="01" eyebrow="Definition" title="What the rule says, as printed">
                <Definition rule={rule} />
              </Plate>
              <Plate index="02" eyebrow="Care-gap records" title="Where this rule opened gaps">
                <ResourceView resource={gaps} what="Care-gap records" onRetry={retry}>
                  {(g) => <RuleGaps gaps={g} pathway={pathway} ruleId={rule.rule_id} />}
                </ResourceView>
              </Plate>
            </div>
            <Plate index="03" eyebrow="Open questions" title="Unresolved points affecting this rule">
              <ResourceView resource={openQuestions} what="Open questions" onRetry={retry}>
                {(oq) => {
                  const linked = oq.filter((q) => q.rule_ids.includes(rule.rule_id) || rule.open_question_ids.includes(q.oq_id));
                  return linked.length === 0 ? (
                    <p className="text-sm text-muted">No open questions are recorded against this rule.</p>
                  ) : (
                    <ul className="grid grid-cols-1 gap-x-10 gap-y-6 md:grid-cols-2">
                      {linked.map((q) => (
                        <li key={q.oq_id} className="reveal border-l-2 border-status-review pl-4">
                          <p className="font-mono text-[11px] text-faint">
                            {q.oq_id} · {q.category} · {q.status}
                          </p>
                          <p className="mt-1 font-display text-lg text-foreground">{q.title}</p>
                          <p className="mt-1 text-sm leading-relaxed text-muted">{q.detail}</p>
                        </li>
                      ))}
                    </ul>
                  );
                }}
              </ResourceView>
            </Plate>
          </div>
        )}
      </ResourceView>
    </div>
  );
}

function RuleHeader({ rule, pathway, back }: { rule: RuleDetailOut; pathway: Pathway; back: string }) {
  const standing = ruleStanding(rule);
  const group = RULE_GROUP_META[ruleGroup(rule.rule_type)];
  return (
    <>
      <PageHeader
        eyebrow={`${PROGRAMME_META[pathway].name} · ${group.title}`}
        title={ruleShortLabel(rule, rule.rule_id)}
        subtitle={rule.description}
        breadcrumbs={[
          { label: "Programmes", href: "/programmes" },
          { label: PROGRAMME_META[pathway].name, href: back },
          { label: rule.rule_id },
        ]}
        meta={
          <span className="font-mono">
            {rule.rule_id} · v{rule.rule_version}
            {rule.rule_type ? ` · ${rule.rule_type.replace(/_/g, " ")}` : ""}
          </span>
        }
        actions={
          <Link href={back} transitionTypes={BACK} className={buttonClass("secondary")}>
            <ArrowLeft size={14} aria-hidden="true" /> {PROGRAMME_META[pathway].name}
          </Link>
        }
        className="mb-8"
      />
      <div className="reveal mb-12 grid grid-cols-1 gap-4 rounded-2xl bg-surface-sunken p-5 sm:grid-cols-[auto_minmax(0,1fr)] sm:items-center sm:gap-6">
        <span className="flex size-12 items-center justify-center rounded-full bg-surface-raised">
          <StandingGlyph standing={standing} size={22} />
        </span>
        <div>
          <p className="font-display text-xl text-foreground">{STANDING_META[standing].label}</p>
          <p className="mt-0.5 text-sm text-muted">{STANDING_META[standing].description}</p>
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
            <span>verification: {rule.verification_status}</span>
            <span>{rule.is_authoritative ? "authoritative" : "non-authoritative"}</span>
            <span>{rule.requires_clinical_review ? "flagged for clinical review" : "not review-flagged"}</span>
            <span>effective: {rule.effective_date_text ?? "not stated"}</span>
          </p>
        </div>
      </div>
    </>
  );
}

function Definition({ rule }: { rule: RuleDetailOut }) {
  const criteria = ruleCriteria(rule.spec);
  return (
    <div>
      {criteria.length > 0 ? (
        <dl className="divide-y divide-border border-y border-border">
          {criteria.map((c, i) => (
            <div key={i} className="reveal-fade grid grid-cols-1 gap-1 py-3 sm:grid-cols-[180px_minmax(0,1fr)] sm:gap-4" style={{ "--i": i } as React.CSSProperties}>
              <dt className="text-xs font-medium uppercase tracking-[0.1em] text-faint">{c.label}</dt>
              <dd className="text-sm text-foreground">
                {c.value}
                {c.note && <span className="mt-0.5 block text-xs text-action-text">{c.note}</span>}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-sm text-muted">The rule specification contains no printed criteria.</p>
      )}

      {rule.items.length > 0 && (
        <div className="mt-8">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-faint">Items ({rule.items.length})</p>
          <ol className="flex flex-col gap-2">
            {rule.items.map((it) => (
              <li key={`${it.category}-${it.code}`} className="flex items-start gap-3 text-sm">
                <span className="mt-0.5 w-6 shrink-0 text-right font-mono text-[11px] text-faint">{it.ordinal}</span>
                <span className="min-w-0 flex-1">
                  <span className="text-foreground">{it.description}</span>
                  <span className="block text-xs text-faint">
                    {it.category.replace(/_/g, " ")} · {it.verification_status}
                    {it.effective_authority ? "" : " · not authoritative"}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {rule.notes && <p className="mt-8 border-l-2 border-border-strong pl-4 text-sm leading-relaxed text-muted">{rule.notes}</p>}

      <p className="mt-8 flex gap-2 text-xs leading-relaxed text-faint">
        <FileText size={14} aria-hidden="true" className="mt-px shrink-0" />
        <span>
          {rule.source_name} ({rule.source_version}) — {rule.source_reference}. Transcribed for engineering use; not clinically
          reviewed.
        </span>
      </p>
    </div>
  );
}

const PAGE = 15;

function RuleGaps({ gaps, pathway, ruleId }: { gaps: CareGapOut[]; pathway: Pathway; ruleId: string }) {
  const [status, setStatus] = useState<CareGapStatus>("open");
  const [shown, setShown] = useState(PAGE);
  const counts = useMemo(() => {
    const c = Object.fromEntries(GAP_STATUS_ORDER.map((s) => [s, 0])) as Record<CareGapStatus, number>;
    for (const g of gaps) if (g.status in c) c[g.status] += 1;
    return c;
  }, [gaps]);
  const list = gaps.filter((g) => g.status === status);
  const via = typeof window === "undefined" ? "" : window.location.pathname;
  const from = new URLSearchParams({ pathway }).toString();

  if (gaps.length === 0)
    return (
      <EmptyState
        icon={SearchX}
        title="No care-gap records"
        description="The engine opened no care gap under this rule for anyone in your scope. That is not evidence that everyone completed it."
      />
    );

  return (
    <div>
      <dl className="grid grid-cols-3 gap-4">
        <Figure label="Open" value={counts.open} note="records" i={0} />
        <Figure label="Completed" value={counts.closed_completed} note="documented" i={1} />
        <Figure label="Refused" value={counts.closed_refused} note="documented" i={2} />
      </dl>

      <div role="group" aria-label="Show care gaps by status" className="mt-6 flex flex-wrap gap-2 text-xs">
        {GAP_STATUS_ORDER.filter((s) => counts[s] > 0).map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={status === s}
            onClick={() => {
              setStatus(s);
              setShown(PAGE);
            }}
            className={
              status === s
                ? "rounded-full border border-foreground bg-surface-raised px-2.5 py-1 text-foreground"
                : "rounded-full border border-border px-2.5 py-1 text-muted transition-colors hover:border-border-strong hover:text-foreground"
            }
          >
            {GAP_STATUS_META[s].short} <span className="font-mono text-faint">{counts[s]}</span>
          </button>
        ))}
      </div>

      <ul key={status} className="mt-4 divide-y divide-border border-y border-border">
        {list.slice(0, shown).map((g, i) => (
          <li key={g.care_gap_id} className="reveal-fade" style={{ "--i": i } as React.CSSProperties}>
            <Link
              href={`/people/${encodeURIComponent(g.patient_id)}?${new URLSearchParams({ from, via }).toString()}#evidence`}
              transitionTypes={FORWARD}
              className="group flex items-center gap-3 py-2.5 transition-colors hover:bg-highlight/50 sm:px-2"
            >
              <StatusGlyph status={g.status === "open" ? "due" : g.status === "closed_completed" ? "completed" : "not_eligible"} size={12} />
              <span className="min-w-0 flex-1">
                <span className="block font-mono text-[13px] font-semibold text-foreground group-hover:text-accent">{g.patient_id}</span>
                <span className="block truncate text-xs text-muted">
                  {gapTypeMeta(g.gap_type).label} · identified {g.identified_date}
                  {g.closed_date ? ` · closed ${g.closed_date}` : ""}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {shown < list.length && (
        <button type="button" onClick={() => setShown((n) => n + PAGE * 2)} className={buttonClass("secondary", "mt-4")}>
          Show more ({list.length - shown} remaining)
        </button>
      )}
      <Footnote>
        Records from <code className="font-mono">GET /care-gaps?rule_id={ruleId}</code>, limited to your scope. Open a person to
        follow the evidence trace.
      </Footnote>
    </div>
  );
}
