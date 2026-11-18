import type { Pathway } from "@/lib/api/types";
import type { SegmentId } from "@/lib/population/model";
import { cn } from "@/lib/cn";

/** Each segment has a distinct shape as well as colour, so it reads without colour. */
export const SEGMENT_COLOR: Record<SegmentId, { ink: string; paper: string }> = {
  open_gap: { ink: "var(--ink-segment-gap)", paper: "var(--segment-gap)" },
  available: { ink: "var(--ink-segment-available)", paper: "var(--segment-available)" },
  partial: { ink: "var(--ink-segment-partial)", paper: "var(--segment-partial)" },
  not_available: { ink: "var(--ink-segment-unavailable)", paper: "var(--segment-unavailable)" },
};

export const PROGRAMME_COLOR: Record<Pathway, { ink: string; paper: string }> = {
  ifhas: { ink: "var(--ink-programme-ifhas)", paper: "var(--programme-ifhas)" },
  well_child: { ink: "var(--ink-programme-well-child)", paper: "var(--programme-well-child)" },
};

/** SVG mark for one person / one legend entry, centred on (x, y). */
export function SegmentMark({
  segment,
  x,
  y,
  r,
  color,
  opacity,
}: {
  segment: SegmentId;
  x: number;
  y: number;
  r: number;
  color: string;
  opacity?: number;
}) {
  switch (segment) {
    case "open_gap":
      return <circle cx={x} cy={y} r={r} fill={color} opacity={opacity} />;
    case "available":
      return (
        <circle cx={x} cy={y} r={r * 0.85} fill="none" stroke={color} strokeWidth={r * 0.45} opacity={opacity} />
      );
    case "partial":
      return (
        <path
          d={`M${x} ${y - r * 1.15}L${x + r * 1.15} ${y}L${x} ${y + r * 1.15}L${x - r * 1.15} ${y}Z`}
          fill={color}
          opacity={opacity}
        />
      );
    case "not_available":
      return (
        <rect
          x={x - r * 0.8}
          y={y - r * 0.8}
          width={r * 1.6}
          height={r * 1.6}
          fill="none"
          stroke={color}
          strokeWidth={r * 0.4}
          opacity={opacity}
        />
      );
  }
}

export function SegmentGlyph({
  segment,
  surface = "paper",
  size = 12,
  className,
}: {
  segment: SegmentId;
  surface?: "ink" | "paper";
  size?: number;
  className?: string;
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true" className={cn("shrink-0", className)}>
      <SegmentMark segment={segment} x={6} y={6} r={4} color={SEGMENT_COLOR[segment][surface]} />
    </svg>
  );
}
