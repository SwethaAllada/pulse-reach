import { cn } from "@/lib/cn";
import { AnimatedNumber } from "./animated-number";

interface FigureProps {
  label: string;
  value: React.ReactNode;
  /** Definition / denominator — what the number counts. */
  note?: React.ReactNode;
  /** @deprecated Both tones render identically on the card surface. */
  tone?: "paper" | "plate";
  size?: "md" | "lg" | "xl";
  className?: string;
  i?: number;
}

const SIZES = { md: "text-xl", lg: "text-[26px]", xl: "text-[32px]" } as const;

/** A KPI: label, tabular figure, then what it counts. */
export function Figure({ label, value, note, size = "lg", className, i }: FigureProps) {
  return (
    <div className={cn("reveal min-w-0", className)} style={i !== undefined ? ({ "--i": i } as React.CSSProperties) : undefined}>
      <dt className="text-xs font-medium text-muted">{label}</dt>
      <dd className={cn("figure mt-1.5 leading-none text-foreground", SIZES[size])}>
        {typeof value === "number" && Number.isInteger(value) ? <AnimatedNumber value={value} /> : value}
      </dd>
      {note && <dd className="mt-1.5 text-xs leading-snug text-faint">{note}</dd>}
    </div>
  );
}

/** A KPI on its own card — the standard tile of every dashboard KPI row. */
export function KpiCard({ className, ...props }: FigureProps) {
  return <Figure {...props} className={cn("rounded-xl border border-border bg-surface-raised px-4 py-3.5", className)} />;
}

/** `n / d` as a whole percentage, or null when the denominator is empty. */
export function percent(n: number, d: number): number | null {
  return d > 0 ? Math.round((n / d) * 100) : null;
}
