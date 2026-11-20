"use client";

import type { CohortId, PopulationModel, Programme } from "@/lib/population/model";
import { SEGMENT_META, SEGMENT_ORDER } from "@/lib/population/model";
import { pathwayLabel } from "@/lib/population/filters";
import { PROGRAMME_COLOR, SEGMENT_COLOR, SegmentGlyph } from "./segment-glyph";
import { cn } from "@/lib/cn";
import { useLocale } from "@/lib/i18n/use-locale";

const pct = (n: number, d: number) => (d > 0 ? Math.round((n / d) * 100) : null);

/**
 * Side-by-side comparison of the programme cohorts: evidence segments as 100% bars (each
 * segment selectable), then rates per programme. Every number is computed from the loaded
 * API records for the current filter set; rates divide by each programme's own members.
 */
export function CohortComparison({
  model,
  selectedId,
  onSelect,
}: {
  model: PopulationModel;
  selectedId: CohortId | null;
  onSelect: (id: CohortId | null) => void;
}) {
  const { t, number, percent } = useLocale();
  const pctText = (v: number | null) => (v === null ? "—" : percent(v / 100));
  const rows: { id: string; label: string; hint: string; value: (p: Programme) => string; share?: (p: Programme) => number | null }[] = [
    { id: "members", label: t("pop.compare.members"), hint: t("pop.compare.members_hint"), value: (p) => number(p.people) },
    {
      id: "with_gap",
      label: t("pop.compare.with_gap"),
      hint: t("pop.compare.with_gap_hint"),
      value: (p) => pctText(pct(p.peopleWithOpenGap, p.people)),
      share: (p) => pct(p.peopleWithOpenGap, p.people),
    },
    {
      id: "per_member",
      label: t("pop.compare.per_member"),
      hint: t("pop.compare.per_member_hint"),
      value: (p) => (p.people ? number(p.openGaps / p.people, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : "—"),
    },
    {
      id: "history",
      label: t("pop.compare.history"),
      hint: t("pop.compare.history_hint"),
      value: (p) => pctText(pct(p.history.available, p.people)),
      share: (p) => pct(p.history.available, p.people),
    },
    {
      id: "no_history",
      label: t("pop.compare.no_history"),
      hint: t("pop.compare.no_history_hint"),
      value: (p) => pctText(pct(p.history.not_available, p.people)),
      share: (p) => pct(p.history.not_available, p.people),
    },
    {
      id: "top_gap",
      label: t("pop.compare.top_gap"),
      hint: t("pop.compare.top_gap_hint"),
      value: (p) => p.gapsByRule[0]?.label ?? t("pop.compare.none"),
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4">
        {model.programmes.map((prog) => (
          <div key={prog.id}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
              <button
                type="button"
                onClick={() => onSelect(selectedId === prog.id ? null : prog.id)}
                aria-pressed={selectedId === prog.id}
                className={cn("flex items-center gap-2 text-sm font-semibold transition-colors", selectedId === prog.id ? "text-accent" : "text-foreground hover:text-accent")}
              >
                <span aria-hidden="true" className="size-2.5 rounded-full" style={{ background: PROGRAMME_COLOR[prog.pathway].paper }} />
                {pathwayLabel(prog.pathway, t)}
              </button>
              <span className="text-xs tabular-nums text-muted">{t("pop.people_n", { count: prog.people })}</span>
            </div>
            <div
              role="group"
              aria-label={t("pop.compare.segments_aria", { programme: pathwayLabel(prog.pathway, t) })}
              className="flex h-9 w-full gap-0.5 overflow-hidden rounded-lg bg-surface-sunken"
            >
              {prog.people > 0 &&
                prog.segments.map((seg, i) =>
                  seg.people > 0 ? (
                    <button
                      key={seg.id}
                      type="button"
                      onClick={() => onSelect(selectedId === seg.id ? null : seg.id)}
                      aria-pressed={selectedId === seg.id}
                      aria-label={t("pop.cohort.aria", { programme: pathwayLabel(prog.pathway, t), cohort: seg.label, people: t("pop.people_n", { count: seg.people }) })}
                      title={`${seg.label}: ${number(seg.people)} (${pctText(pct(seg.people, prog.people))})`}
                      className={cn(
                        "grow-x relative flex min-w-0 items-center justify-center text-[11px] font-semibold transition-[opacity,filter] duration-200 hover:brightness-110",
                        selectedId && selectedId !== seg.id && selectedId !== prog.id && "opacity-35"
                      )}
                      style={{ width: `${(seg.people / prog.people) * 100}%`, background: SEGMENT_COLOR[seg.segment!].paper, color: "var(--surface-elevated)", "--i": i } as React.CSSProperties}
                    >
                      <span className="truncate px-1">{(seg.people / prog.people) * 100 >= 9 ? pctText(pct(seg.people, prog.people)) : ""}</span>
                      {selectedId === seg.id && <span aria-hidden="true" className="absolute inset-0 rounded-sm ring-2 ring-inset ring-foreground" />}
                    </button>
                  ) : null
                )}
            </div>
          </div>
        ))}
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {SEGMENT_ORDER.map((s) => (
            <li key={s} className="flex items-center gap-1.5">
              <SegmentGlyph segment={s} /> {t(SEGMENT_META[s].short)}
            </li>
          ))}
        </ul>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t("pop.compare.caption")}</caption>
          <thead>
            <tr className="border-b border-border text-start text-xs text-muted">
              <th className="py-2 pe-3 text-start font-medium">{t("pop.compare.measure")}</th>
              {model.programmes.map((p) => (
                <th key={p.id} className="px-3 py-2 text-end font-medium">
                  {pathwayLabel(p.pathway, t, true)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((r) => (
              <tr key={r.id}>
                <th scope="row" className="py-2.5 pe-3 text-start font-normal">
                  <span className="block text-foreground">{r.label}</span>
                  <span className="text-[11px] text-faint">{r.hint}</span>
                </th>
                {model.programmes.map((p) => {
                  const share = r.share?.(p) ?? null;
                  return (
                    <td key={p.id} className="px-3 py-2.5 text-end align-middle">
                      <span className={cn("tabular-nums text-foreground", r.share ? "font-semibold" : "", r.id === "top_gap" && "text-xs")} dir="auto">{r.value(p)}</span>
                      {share !== null && (
                        <span aria-hidden="true" className="ms-auto mt-1 block h-1 w-24 overflow-hidden rounded-full bg-surface-sunken">
                          <span className="grow-x block h-full rounded-full" style={{ width: `${share}%`, background: PROGRAMME_COLOR[p.pathway].paper }} />
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] leading-relaxed text-faint">
        {t("pop.compare.footnote")}
      </p>
    </div>
  );
}
