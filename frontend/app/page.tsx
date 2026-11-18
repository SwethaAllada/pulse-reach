import Link from "next/link";
import { ArrowRight, Layers, Telescope, Users } from "lucide-react";
import { ConstellationVisualization } from "@/components/constellation/constellation-visualization";
import { CohortLegend } from "@/components/constellation/cohort-legend";
import { StatusGlyph, statusColor, type EvaluationStatus } from "@/components/ui/status-glyph";
import { Surface } from "@/components/ui/surface";
import { SectionHeader } from "@/components/ui/section-header";

/* ── Illustrative demo values — clearly synthetic, replaced by the API later ── */

const SUMMARY = [
  { label: "Synthetic people", value: "160", note: "demo set" },
  { label: "Programmes", value: "2", note: "IFHAS · Well-Child" },
  { label: "Rule evaluations", value: "4,320", note: "illustrative" },
  { label: "Open documented gaps", value: "58", note: "illustrative" },
];

const GAP_STRIP = [
  { id: "IFHAS-PKG-ORAL-18-75", label: "Oral health package · 18–75", count: 21 },
  { id: "IFHAS-PKG-MAJOR-40-64", label: "Major screening · 40–64", count: 17 },
  { id: "WCV-VISIT-24M", label: "Well-Child visit · 24 months", count: 11 },
  { id: "IFHAS-PKG-CARDIO-40-75", label: "Cardiovascular package · 40–75", count: 9 },
];

const SPECTRUM: { status: EvaluationStatus; count: number }[] = [
  { status: "completed", count: 1980 },
  { status: "due", count: 940 },
  { status: "eligible", count: 760 },
  { status: "not_eligible", count: 320 },
  { status: "unknown", count: 180 },
  { status: "insufficient_information", count: 86 },
  { status: "requires_clinical_review", count: 54 },
];

/* ── Page ── */

export default function PopulationPage() {
  const spectrumTotal = SPECTRUM.reduce((n, s) => n + s.count, 0);

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 sm:px-6 lg:px-8">
      {/* ── Ink hero band: one observatory surface per screen ── */}
      <section className="-mx-4 sm:-mx-6 lg:-mx-8 mb-10 border-b border-ink-line bg-ink px-4 pb-8 pt-8 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-[1200px]">
          <div className="flex items-center gap-2 text-ink-accent">
            <Telescope size={15} aria-hidden="true" />
            <p className="text-xs font-semibold uppercase tracking-[0.1em]">
              Population · Overview
            </p>
          </div>
          <h1 className="mt-3 font-display text-4xl font-semibold tracking-tight text-ink-text sm:text-5xl">
            See the signals. Prevent the gaps.
            <br className="hidden sm:block" /> Change the outcome.
          </h1>
          <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-ink-muted">
            PulseReach watches a whole synthetic population at once — every point below is one
            person, gathered into labelled cohort territories so the shape of unmet need is visible
            before anyone falls through it.
          </p>

          <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_260px]">
            <div className="rounded-lg border border-ink-line bg-ink-raised/60 p-3">
              <div className="h-[300px] sm:h-[380px]">
                <ConstellationVisualization />
              </div>
            </div>
            <div className="rounded-lg border border-ink-line bg-ink-raised/60 p-5">
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-faint">
                Cohorts · illustrative
              </p>
              <CohortLegend />
            </div>
          </div>
        </div>
      </section>

      {/* ── Illustrative summary ── */}
      <section aria-labelledby="summary-heading">
        <SectionHeader
          eyebrow="Synthetic demo values"
          title="Population at a glance"
          description="Illustrative placeholders showing where live population measures will appear once the summary API is connected."
        />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {SUMMARY.map((s) => (
            <Surface key={s.label} className="px-4 py-3.5">
              <p className="font-display text-3xl font-semibold tabular-nums text-foreground">
                {s.value}
              </p>
              <p className="mt-1 text-xs font-medium text-muted">
                {s.label} <span className="text-faint">· {s.note}</span>
              </p>
            </Surface>
          ))}
        </div>
      </section>

      {/* ── Preview sections ── */}
      <div className="mt-10 grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="gaps-heading">
          <Surface className="h-full p-5">
            <SectionHeader
              eyebrow="Preview"
              title="Where documented gaps sit"
              description="Ranked illustration — real rules and counts arrive with the dashboard API."
            />
            <ul className="flex flex-col gap-3">
              {GAP_STRIP.map((row) => {
                const max = GAP_STRIP[0].count;
                return (
                  <li key={row.id}>
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="truncate font-mono text-xs text-muted">{row.id}</span>
                      <span className="font-mono text-xs tabular-nums text-foreground">
                        {row.count}
                      </span>
                    </div>
                    <div
                      aria-hidden="true"
                      className="mt-1 flex gap-1"
                      title={`${row.label} — ${row.count} (illustrative)`}
                    >
                      {Array.from({ length: Math.ceil((row.count / max) * 24) }).map((_, i) => (
                        <span key={i} className="size-1.5 rounded-full bg-status-due opacity-80" />
                      ))}
                    </div>
                  </li>
                );
              })}
            </ul>
            <p className="mt-4 border-t border-border pt-3 text-[11px] text-faint">
              Demo rows — counts are illustrative, not real gap volumes.
            </p>
          </Surface>
        </section>

        <section aria-labelledby="evidence-heading">
          <Surface className="h-full p-5">
            <SectionHeader
              eyebrow="Preview"
              title="How complete is the evidence"
              description="Illustrative distribution of rule evaluations across statuses."
            />
            <div
              className="flex h-6 w-full overflow-hidden rounded-sm"
              role="img"
              aria-label="Illustrative status distribution of rule evaluations."
            >
              {SPECTRUM.map((s) => (
                <div
                  key={s.status}
                  style={{
                    width: `${(s.count / spectrumTotal) * 100}%`,
                    backgroundColor: statusColor(s.status),
                  }}
                />
              ))}
            </div>
            <ul className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {SPECTRUM.map((s) => (
                <li key={s.status} className="flex items-center gap-2 text-xs">
                  <StatusGlyph status={s.status} size={12} />
                  <span className="flex-1 text-muted">
                    {s.status === "requires_clinical_review"
                      ? "Clinical review"
                      : s.status === "insufficient_information"
                        ? "Missing attribute"
                        : s.status === "due"
                          ? "Documented gap"
                          : s.status === "not_eligible"
                            ? "Outside scope"
                            : s.status === "unknown"
                              ? "History unavailable"
                              : s.status === "completed"
                                ? "Completed"
                                : "In scope"}
                  </span>
                  <span className="font-mono tabular-nums text-foreground">{s.count}</span>
                </li>
              ))}
            </ul>
            <p className="mt-4 border-t border-border pt-3 text-[11px] text-faint">
              Counts rule evaluations (people × rules), not people. Illustrative values.
            </p>
          </Surface>
        </section>
      </div>

      {/* ── Entry points ── */}
      <section aria-labelledby="entry-heading" className="mt-10">
        <SectionHeader eyebrow="Workspaces" title="Where the work happens" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Link href="/people" className="group">
            <Surface className="flex h-full items-start gap-4 p-5 transition-colors group-hover:border-accent">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                <Users size={19} strokeWidth={1.75} aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  People workspace
                  <ArrowRight
                    size={14}
                    aria-hidden="true"
                    className="text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent"
                  />
                </span>
                <span className="mt-1 block text-sm text-muted">
                  Find and queue the synthetic people who need attention — filter by programme,
                  region and evidence state.
                </span>
              </span>
            </Surface>
          </Link>
          <Link href="/programmes" className="group">
            <Surface className="flex h-full items-start gap-4 p-5 transition-colors group-hover:border-accent">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                <Layers size={19} strokeWidth={1.75} aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  Programmes &amp; rules
                  <ArrowRight
                    size={14}
                    aria-hidden="true"
                    className="text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent"
                  />
                </span>
                <span className="mt-1 block text-sm text-muted">
                  Browse the screening packages and well-child visit rules that decide who should
                  have been seen — and how each rule was verified.
                </span>
              </span>
            </Surface>
          </Link>
        </div>
      </section>
    </div>
  );
}
