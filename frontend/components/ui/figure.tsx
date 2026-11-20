import { cn } from "@/lib/cn";

interface FigureProps {
  label: string;
  value: React.ReactNode;
  /** Definition / denominator — what the number counts. */
  note?: React.ReactNode;
  tone?: "paper" | "plate";
  size?: "md" | "lg" | "xl";
  className?: string;
  i?: number;
}

const SIZES = { md: "text-2xl", lg: "text-[34px]", xl: "text-5xl sm:text-6xl" } as const;

/** A measured quantity set in the display serif: label, figure, then what it counts. */
export function Figure({ label, value, note, tone = "paper", size = "lg", className, i }: FigureProps) {
  const plate = tone === "plate";
  return (
    <div className={cn("reveal min-w-0", className)} style={i !== undefined ? ({ "--i": i } as React.CSSProperties) : undefined}>
      <dt className={cn("text-[11px] font-medium uppercase tracking-[0.12em]", plate ? "text-ink-faint" : "text-faint")}>
        {label}
      </dt>
      <dd className={cn("figure mt-1.5 font-normal leading-none", SIZES[size], plate ? "text-ink-text" : "text-foreground")}>
        {value}
      </dd>
      {note && (
        <dd className={cn("mt-2 text-xs leading-snug", plate ? "text-ink-muted" : "text-muted")}>{note}</dd>
      )}
    </div>
  );
}

/** `n / d` as a whole percentage, or null when the denominator is empty. */
export function percent(n: number, d: number): number | null {
  return d > 0 ? Math.round((n / d) * 100) : null;
}
