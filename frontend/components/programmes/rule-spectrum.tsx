"use client";

import Link from "next/link";
import type { CareGapStatus, Pathway } from "@/lib/api/types";
import {
  GAP_STATUS_META,
  RULE_GROUP_META,
  RULE_GROUP_ORDER,
  ruleHref,
  STANDING_META,
  type RuleRow,
  type RuleStanding,
} from "@/lib/programmes/model";
import { FORWARD } from "@/components/ui/page-transition";
import { cn } from "@/lib/cn";
import { useLocale } from "@/lib/i18n/use-locale";

const STANDING_COLOR: Record<RuleStanding, string> = {
  authoritative: "var(--accent)",
  review: "var(--status-review)",
  unresolved: "var(--status-insufficient)",
};

/** Rule standing glyph: solid = verified & authoritative, diamond = review, dashed ring = unresolved. */
export function StandingGlyph({ standing, size = 12 }: { standing: RuleStanding; size?: number }) {
  const c = STANDING_COLOR[standing];
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true" className="shrink-0">
      {standing === "authoritative" && <circle cx="6" cy="6" r="4" fill={c} />}
      {standing === "review" && <path d="M6 1.5 10.5 6 6 10.5 1.5 6z" fill={c} />}
      {standing === "unresolved" && <circle cx="6" cy="6" r="4" fill="none" stroke={c} strokeWidth="1.5" strokeDasharray="2 1.6" />}
    </svg>
  );
}

export const SPECTRUM_METRICS: CareGapStatus[] = ["open", "closed_completed", "closed_refused"];

const BAR_COLOR: Partial<Record<CareGapStatus, string>> = {
  open: "var(--segment-gap)",
  closed_completed: "var(--status-completed)",
  closed_refused: "var(--status-not-eligible)",
};

/**
 * Rule spectrum: every rule of the programme as one column, grouped by role
 * (gates · services · timing). Column height = care-gap records with the chosen
 * status under that rule; the foot glyph = the rule's verification standing.
 */
export function RuleSpectrum({
  pathway,
  rows,
  metric,
  standing,
}: {
  pathway: Pathway;
  rows: RuleRow[];
  metric: CareGapStatus;
  standing: RuleStanding | null;
}) {
  const { t, rich } = useLocale();
  const max = Math.max(1, ...rows.map((r) => r.gaps[metric]));
  return (
    <div className="-mx-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0">
      <div className="flex min-w-[720px] gap-6">
        {RULE_GROUP_ORDER.map((group) => {
          const groupRows = rows.filter((r) => r.group === group);
          if (groupRows.length === 0) return null;
          return (
            <div key={group} className="flex min-w-0 flex-col" style={{ flexGrow: groupRows.length, flexBasis: 0 }}>
              <p className="mb-3 flex items-baseline justify-between gap-2 border-b border-border pb-2 text-xs font-medium text-faint">
                <span className="truncate">{t(RULE_GROUP_META[group].title)}</span>
                <span className="font-mono tracking-normal">{groupRows.length}</span>
              </p>
              <ol className="flex h-44 items-end gap-[3px]">
                {groupRows.map((r, i) => {
                  const value = r.gaps[metric];
                  const dim = standing !== null && r.standing !== standing;
                  return (
                    <li key={r.rule.rule_id} className="group relative flex h-full min-w-[9px] flex-1 flex-col justify-end">
                      <Link
                        href={ruleHref(pathway, r.rule.rule_id)}
                        transitionTypes={FORWARD}
                        aria-label={t("prog.spectrum.aria", {
                          rule: r.label,
                          id: r.rule.rule_id,
                          value,
                          status: t(GAP_STATUS_META[metric].short).toLowerCase(),
                          standing: t(STANDING_META[r.standing].label),
                        })}
                        className={cn(
                          "flex h-full flex-col justify-end rounded-sm outline-offset-1 transition-opacity duration-300",
                          dim && "opacity-25"
                        )}
                      >
                        <span
                          className="grow-y block w-full rounded-t-[3px] transition-[filter] duration-200 group-hover:brightness-110"
                          style={{
                            height: value > 0 ? `${Math.max(3, (value / max) * 100)}%` : "2px",
                            backgroundColor: value > 0 ? BAR_COLOR[metric] : "var(--border-strong)",
                            "--i": i,
                          } as React.CSSProperties}
                        />
                        <span className="mt-1.5 flex justify-center">
                          <StandingGlyph standing={r.standing} size={10} />
                        </span>
                      </Link>
                      <span
                        role="tooltip"
                        className="pointer-events-none absolute left-1/2 top-0 z-20 w-56 -translate-x-1/2 translate-y-1 rounded-lg border border-border bg-surface-raised px-3 py-2 text-start opacity-0 shadow-[var(--shadow-popover)] transition-[opacity,transform] duration-200 group-focus-within:translate-y-0 group-focus-within:opacity-100 group-hover:translate-y-0 group-hover:opacity-100"
                      >
                        <span className="block text-xs font-semibold text-foreground" dir="auto">{r.label}</span>
                        <span className="mt-0.5 block font-mono text-[10px] text-faint">{r.rule.rule_id}</span>
                        <span className="mt-1.5 block text-xs text-muted">
                          {rich("prog.spectrum.counts", {
                            open: <span className="font-mono text-foreground">{r.gaps.open}</span>,
                            completed: <span className="font-mono text-foreground">{r.gaps.closed_completed}</span>,
                            refused: <span className="font-mono text-foreground">{r.gaps.closed_refused}</span>,
                          })}
                        </span>
                        <span className="mt-1 flex items-center gap-1.5 text-xs text-muted">
                          <StandingGlyph standing={r.standing} size={10} /> {t(STANDING_META[r.standing].label)}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ol>
            </div>
          );
        })}
      </div>
    </div>
  );
}
