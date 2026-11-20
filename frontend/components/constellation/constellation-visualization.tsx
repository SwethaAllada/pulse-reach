"use client";

/**
 * Population Constellation — a deterministic, hand-built SVG field.
 *
 * Each mark is one synthetic person, placed in the territory of their
 * programme and the cluster of their evidence segment (open documented gap,
 * history available, partial, unavailable). There are deliberately NO lines
 * between people and no force layout: position within a cluster is a fixed
 * sunflower pattern and carries no clinical meaning. Cluster size is
 * proportional to the real head-count returned by the API.
 */

import { useMemo, useRef, useState } from "react";
import type { Pathway } from "@/lib/api/types";
import {
  SEGMENT_META,
  type Cohort,
  type CohortId,
  type PopulationModel,
  type SegmentId,
} from "@/lib/population/model";
import { pathwayLabel } from "@/lib/population/filters";
import { PROGRAMME_COLOR, SEGMENT_COLOR, SegmentMark } from "@/components/population/segment-glyph";
import { cn } from "@/lib/cn";

const W = 800;
const H = 440;
/** Spacing constant of the sunflower pattern (viewBox units). */
const SPACING = 4.6;
const MARK_R = 2.3;

interface Territory {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
  labelX: number;
  labelY: number;
  anchor: "start" | "end";
  slots: Record<SegmentId, { cx: number; cy: number; maxR: number }>;
}

const TERRITORIES: Record<Pathway, Territory> = {
  ifhas: {
    cx: 290,
    cy: 240,
    rx: 260,
    ry: 182,
    labelX: 44,
    labelY: 26,
    anchor: "start",
    slots: {
      open_gap: { cx: 205, cy: 232, maxR: 112 },
      available: { cx: 405, cy: 128, maxR: 52 },
      partial: { cx: 440, cy: 246, maxR: 46 },
      not_available: { cx: 395, cy: 348, maxR: 46 },
    },
  },
  well_child: {
    cx: 672,
    cy: 240,
    rx: 112,
    ry: 182,
    labelX: 772,
    labelY: 26,
    anchor: "end",
    slots: {
      open_gap: { cx: 672, cy: 160, maxR: 62 },
      available: { cx: 622, cy: 290, maxR: 30 },
      partial: { cx: 724, cy: 290, maxR: 26 },
      not_available: { cx: 672, cy: 362, maxR: 28 },
    },
  },
};

/** Deterministic PRNG so the field never reshuffles between renders. */
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

function clusterRadius(count: number, maxR: number): number {
  return Math.min(maxR, SPACING * Math.sqrt(Math.max(count, 1)));
}

function layoutCluster(id: string, count: number, cx: number, cy: number, maxR: number) {
  const rand = mulberry32(hash(id));
  const R = clusterRadius(count, maxR);
  const step = count > 0 ? R / Math.sqrt(count) : 0;
  return Array.from({ length: count }, (_, i) => {
    const angle = i * 2.399963 + rand() * 0.35;
    const radius = step * Math.sqrt(i + 0.5);
    return { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius, o: 0.7 + rand() * 0.3 };
  });
}

const DUST = (() => {
  const rand = mulberry32(0x50524);
  return Array.from({ length: 46 }, () => ({
    x: rand() * W,
    y: rand() * H,
    r: 0.5 + rand() * 0.9,
    o: 0.12 + rand() * 0.25,
  }));
})();

interface Props {
  model: PopulationModel;
  selectedId: CohortId | null;
  onSelect: (id: CohortId | null) => void;
}

export function ConstellationVisualization({ model, selectedId, onSelect }: Props) {
  const [hoverId, setHoverId] = useState<CohortId | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const clusters = useMemo(
    () =>
      model.programmes.flatMap((prog) =>
        prog.segments.map((seg) => {
          const slot = TERRITORIES[prog.pathway].slots[seg.segment!];
          return {
            cohort: seg,
            slot,
            R: clusterRadius(seg.people, slot.maxR),
            marks: layoutCluster(seg.id, seg.people, slot.cx, slot.cy, slot.maxR),
          };
        })
      ),
    [model]
  );

  const selectedPathway = selectedId?.split(":")[0] as Pathway | undefined;
  const isDimmed = (cohort: Cohort) =>
    selectedId !== null && selectedId !== cohort.id && selectedId !== cohort.pathway;

  /** Arrow keys move focus between interactive marks in document order. */
  const onKeyDown = (e: React.KeyboardEvent<SVGGElement>, id: CohortId) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(selectedId === id ? null : id);
      return;
    }
    if (e.key === "Escape") {
      onSelect(null);
      return;
    }
    const dir = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    const items = Array.from(svgRef.current?.querySelectorAll<SVGGElement>("[data-cohort]") ?? []);
    const idx = items.indexOf(e.currentTarget);
    items[(idx + dir + items.length) % items.length]?.focus();
  };

  const interactive = (id: CohortId, label: string) => ({
    role: "button",
    tabIndex: 0,
    "data-cohort": id,
    "aria-pressed": selectedId === id,
    "aria-label": label,
    onClick: (e: React.MouseEvent) => {
      e.stopPropagation();
      onSelect(selectedId === id ? null : id);
    },
    onKeyDown: (e: React.KeyboardEvent<SVGGElement>) => onKeyDown(e, id),
    onMouseEnter: () => setHoverId(id),
    onMouseLeave: () => setHoverId((h) => (h === id ? null : h)),
    onFocus: () => setHoverId(id),
    onBlur: () => setHoverId((h) => (h === id ? null : h)),
    className: "cursor-pointer outline-none [&:focus-visible>.focus-ring]:opacity-100",
  });

  const hovered = clusters.find((c) => c.cohort.id === hoverId);
  const hoveredProgramme = model.programmes.find((p) => p.id === hoverId);

  return (
    <div className="relative h-full w-full">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        role="group"
        aria-label={`Population constellation: ${model.totalPeople} synthetic people in programme territories, grouped by documented evidence segment. Each mark is one person; position inside a cluster carries no clinical meaning.`}
        className="h-full w-full select-none"
        preserveAspectRatio="xMidYMid meet"
        onClick={() => onSelect(null)}
      >
        {DUST.map((s, i) => (
          <circle key={`d${i}`} cx={s.x} cy={s.y} r={s.r} fill="var(--ink-muted)" opacity={s.o} />
        ))}

        {model.programmes.map((prog) => {
          const t = TERRITORIES[prog.pathway];
          const color = PROGRAMME_COLOR[prog.pathway].ink;
          const selected = selectedId === prog.id;
          const dim = selectedId !== null && selectedPathway !== prog.pathway;
          return (
            <g key={prog.id} opacity={dim ? 0.45 : 1} className="transition-opacity duration-150">
              <ellipse
                cx={t.cx}
                cy={t.cy}
                rx={t.rx}
                ry={t.ry}
                fill={color}
                opacity={selected ? 0.1 : 0.04}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(selected ? null : prog.id);
                }}
                className="cursor-pointer"
              />
              <ellipse
                cx={t.cx}
                cy={t.cy}
                rx={t.rx}
                ry={t.ry}
                fill="none"
                stroke={color}
                strokeWidth={selected ? 1.6 : 1}
                strokeDasharray={selected ? undefined : "3 6"}
                opacity={selected ? 0.9 : 0.45}
                pointerEvents="none"
              />
              <g
                {...interactive(
                  prog.id,
                  `${pathwayLabel(prog.pathway)} programme: ${prog.people} people. ${selected ? "Selected." : "Select to view programme details."}`
                )}
              >
                <rect
                  className="focus-ring opacity-0"
                  x={t.anchor === "start" ? t.labelX - 8 : t.labelX - 236}
                  y={t.labelY - 22}
                  width={244}
                  height={50}
                  rx={6}
                  fill="none"
                  stroke="var(--ink-accent)"
                  strokeWidth={2}
                />
                <text
                  x={t.labelX}
                  y={t.labelY}
                  textAnchor={t.anchor}
                  fill={color}
                  fontSize={15}
                  fontWeight={600}
                  className="font-display"
                >
                  {pathwayLabel(prog.pathway)}
                </text>
                <text x={t.labelX} y={t.labelY + 18} textAnchor={t.anchor} fill="var(--ink-muted)" fontSize={12}>
                  {prog.people} {prog.people === 1 ? "person" : "people"}
                </text>
              </g>
              {prog.people === 0 && (
                <text x={t.cx} y={t.cy} textAnchor="middle" fill="var(--ink-faint)" fontSize={13}>
                  No people match the current filters
                </text>
              )}
            </g>
          );
        })}

        {clusters.map(({ cohort, slot, R, marks }) => {
          const seg = cohort.segment!;
          const color = SEGMENT_COLOR[seg].ink;
          const selected = selectedId === cohort.id;
          const dim = isDimmed(cohort);
          if (cohort.people === 0) return null;
          return (
            <g
              key={cohort.id}
              {...interactive(
                cohort.id,
                `${pathwayLabel(cohort.pathway)} — ${cohort.label}: ${cohort.people} ${cohort.people === 1 ? "person" : "people"}. ${selected ? "Selected." : "Select to view cohort details."}`
              )}
              opacity={dim ? 0.3 : 1}
              style={{ transition: "opacity 160ms" }}
            >
              <circle cx={slot.cx} cy={slot.cy} r={R + 9} fill="transparent" />
              <circle
                cx={slot.cx}
                cy={slot.cy}
                r={R + 6}
                fill={color}
                opacity={selected ? 0.12 : 0}
                stroke={color}
                strokeWidth={selected ? 1.4 : 0}
              />
              <circle
                className="focus-ring opacity-0"
                cx={slot.cx}
                cy={slot.cy}
                r={R + 10}
                fill="none"
                stroke="var(--ink-accent)"
                strokeWidth={2}
              />
              {marks.map((m, i) => (
                <SegmentMark key={i} segment={seg} x={m.x} y={m.y} r={MARK_R} color={color} opacity={m.o} />
              ))}
              <text
                x={slot.cx}
                y={slot.cy + R + 22}
                textAnchor="middle"
                fontSize={12}
                fill="var(--ink-text)"
                className="hidden sm:inline"
              >
                <tspan fontWeight={600} className="font-mono">
                  {cohort.people}
                </tspan>
                <tspan fill="var(--ink-muted)"> {SEGMENT_META[seg].short}</tspan>
              </text>
            </g>
          );
        })}
      </svg>

      {(hovered || hoveredProgramme) && (
        <Tooltip
          cohort={hovered?.cohort ?? hoveredProgramme!}
          x={hovered ? hovered.slot.cx : TERRITORIES[hoveredProgramme!.pathway].cx}
          y={hovered ? hovered.slot.cy - hovered.R - 10 : TERRITORIES[hoveredProgramme!.pathway].cy - 120}
        />
      )}
    </div>
  );
}

function Tooltip({ cohort, x, y }: { cohort: Cohort; x: number; y: number }) {
  return (
    <div
      role="tooltip"
      className={cn(
        "pointer-events-none absolute z-10 w-56 -translate-x-1/2 -translate-y-full rounded-md border border-ink-line bg-ink-raised px-3 py-2 shadow-[var(--shadow-popover)]"
      )}
      style={{ left: `${(Math.min(Math.max(x, 120), W - 120) / W) * 100}%`, top: `${(Math.max(y, 70) / H) * 100}%` }}
    >
      <p className="text-xs font-medium text-ink-faint">
        {pathwayLabel(cohort.pathway)}
      </p>
      <p className="text-sm font-semibold text-ink-text">{cohort.label}</p>
      <p className="mt-1 text-xs text-ink-muted">
        <span className="font-mono text-ink-text">{cohort.people}</span> people ·{" "}
        <span className="font-mono text-ink-text">{cohort.openGaps}</span> open documented gaps
      </p>
    </div>
  );
}
