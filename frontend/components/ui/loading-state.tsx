import { cn } from "@/lib/cn";

interface LoadingStateProps {
  rows?: number;
  className?: string;
}

/** Skeleton rows — same shape as final content, no spinners. */
export function LoadingState({ rows = 3, className }: LoadingStateProps) {
  return (
    <div aria-busy="true" aria-label="Loading" className={cn("flex flex-col gap-3", className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-9 animate-pulse rounded-md bg-surface-sunken"
          style={{ animationDelay: `${i * 120}ms` }}
        />
      ))}
    </div>
  );
}
