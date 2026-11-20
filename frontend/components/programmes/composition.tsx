"use client";

import { useState } from "react";
import { SEGMENT_META, SEGMENT_ORDER, type Cohort, type Programme, type SegmentId } from "@/lib/population/model";
import { SEGMENT_COLOR, SegmentGlyph, SegmentMark } from "@/components/population/segment-glyph";
import { cn } from "@/lib/cn";

type Tone = "ink" | "paper";

/**
 * Composition band: a programme's members split into mutually exclusive evidence
 * segments (open documented gap → otherwise history availability). Widths are
 * head-counts from the API; segments are selectable when `onSelect` is given.
 */
export function CompositionBand({
  programme,
  tone = "paper",
  selected,
  onSelect,
  showLegend = true,
  className,
}: {
  /** A loaded programme cohort, or the server-side programme summary (`summaryBand`). */
  programme: Pick<Programme, "label" | "people"> & { segments: Pick<Cohort, "id" | "segment" | "people">[] };
  tone?: Tone;
  selected?: SegmentId | null;
  onSelect?: (segment: SegmentId | null) => void;
  showLegend?: boolean;
  className?: string;
}) {
  const total = programme.people;
  const segs = programme.segments.filter((s) => s.people > 0);
  const plate = tone === "ink";
  return (
    <div className={className}>
      <div
        role={onSelect ? "group" : "img"}
        aria-label={`${programme.label} members by evidence: ${programme.segments
          .map((s) => `${SEGMENT_META[s.segment!].short} ${s.people}`)
          .join(", ")}`}
        className={cn("flex h-3 w-full gap-[3px] overflow-hidden rounded-full", plate ? "bg-ink-raised" : "bg-surface-sunken")}
      >
        {segs.map((s, i) => {
          const seg = s.segment!;
          const dim = selected && selected !== seg;
          const style = {
            width: `${(s.people / total) * 100}%`,
            backgroundColor: SEGMENT_COLOR[seg][plate ? "ink" : "paper"],
            "--i": i,
          } as React.CSSProperties;
          return onSelect ? (
            <button
              key={seg}
              type="button"
              aria-pressed={selected === seg}
              aria-label={`${SEGMENT_META[seg].label}: ${s.people} people`}
              onClick={() => onSelect(selected === seg ? null : seg)}
              className={cn("grow-x h-full transition-opacity duration-300", dim && "opacity-30")}
              style={style}
            />
          ) : (
            <span key={seg} className={cn("grow-x h-full", dim && "opacity-30")} style={style} />
          );
        })}
      </div>
      {showLegend && (
        <ul className={cn("mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs", plate ? "text-ink-muted" : "text-muted")}>
          {programme.segments.map((s) => (
            <li key={s.id} className="flex items-center gap-1.5">
              <SegmentGlyph segment={s.segment!} surface={plate ? "ink" : "paper"} />
              {SEGMENT_META[s.segment!].short}
              <span className={cn("font-mono tabular-nums", plate ? "text-ink-text" : "text-foreground")}>{s.people}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const CELL = 14;
/** Columns grow with head-count so the lattice keeps a calm ~1.7:1 shape. */
function latticeColumns(n: number): number {
  return Math.min(36, Math.max(16, Math.round(Math.sqrt(n * 1.7))));
}

/**
 * Member lattice: one mark per programme member, laid out in segment order on a
 * fixed grid (a waffle, not a scatter) — position carries no meaning beyond the
 * segment block a person belongs to. Selecting a block focuses that segment.
 */
export function MemberLattice({
  programme,
  selected,
  onSelect,
}: {
  programme: Programme;
  selected: SegmentId | null;
  onSelect: (segment: SegmentId | null) => void;
}) {
  const [hover, setHover] = useState<SegmentId | null>(null);
  const focus = hover ?? selected;
  const cohorts = SEGMENT_ORDER.map((seg) => programme.segments.find((s) => s.segment === seg)!);
  const blocks = cohorts.map((cohort, i) => ({
    seg: SEGMENT_ORDER[i],
    cohort,
    start: cohorts.slice(0, i).reduce((sum, c) => sum + c.people, 0),
  }));
  const n = cohorts.reduce((sum, c) => sum + c.people, 0);
  const COLS = latticeColumns(n);
  const rows = Math.max(1, Math.ceil(n / COLS));
  const W = COLS * CELL;
  const H = rows * CELL;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="group"
      aria-label={`${programme.people} ${programme.label} members, one mark each, grouped by evidence segment.`}
      className="h-auto w-full select-none"
    >
      {blocks.map(({ seg, cohort, start }, bi) => {
        if (cohort.people === 0) return null;
        const color = SEGMENT_COLOR[seg].ink;
        const active = selected === seg;
        const dim = focus !== null && focus !== seg;
        return (
          <g
            key={seg}
            role="button"
            tabIndex={0}
            aria-pressed={active}
            aria-label={`${SEGMENT_META[seg].label}: ${cohort.people} people. ${active ? "Selected." : "Select to focus."}`}
            onClick={() => onSelect(active ? null : seg)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(active ? null : seg);
              } else if (e.key === "Escape") onSelect(null);
            }}
            onMouseEnter={() => setHover(seg)}
            onMouseLeave={() => setHover(null)}
            onFocus={() => setHover(seg)}
            onBlur={() => setHover(null)}
            className="cursor-pointer outline-none [&:focus-visible>.ring]:opacity-100"
            style={{ opacity: dim ? 0.22 : 1, transition: "opacity 260ms var(--ease-out)" }}
          >
            <rect
              className="ring opacity-0"
              x={1}
              y={Math.floor(start / COLS) * CELL + 1}
              width={W - 2}
              height={(Math.floor((start + cohort.people - 1) / COLS) - Math.floor(start / COLS) + 1) * CELL - 2}
              rx={4}
              fill="none"
              stroke="var(--ink-accent)"
              strokeWidth={2}
            />
            {Array.from({ length: cohort.people }, (_, k) => {
              const idx = start + k;
              const x = (idx % COLS) * CELL + CELL / 2;
              const y = Math.floor(idx / COLS) * CELL + CELL / 2;
              return (
                <g key={k} className="reveal-fade" style={{ "--i": bi * 2 + Math.floor(k / 60) } as React.CSSProperties}>
                  <rect x={x - CELL / 2} y={y - CELL / 2} width={CELL} height={CELL} fill="transparent" />
                  <SegmentMark segment={seg} x={x} y={y} r={active ? 4.1 : 3.6} color={color} />
                </g>
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}
