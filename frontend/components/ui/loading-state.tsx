import { cn } from "@/lib/cn";

interface LoadingStateProps {
  rows?: number;
  className?: string;
  label?: string;
}

/** Skeleton rows — same shape as final content, no spinners. */
export function LoadingState({ rows = 3, className, label = "Loading" }: LoadingStateProps) {
  return (
    <div aria-busy="true" aria-label={label} className={cn("flex flex-col gap-3", className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="skeleton h-9 rounded-md"
          style={{ animationDelay: `${i * 120}ms`, width: `${100 - ((i * 13) % 30)}%` }}
        />
      ))}
    </div>
  );
}
