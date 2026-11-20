import { cn } from "@/lib/cn";

interface SurfaceProps extends React.HTMLAttributes<HTMLDivElement> {
  raised?: boolean;
}

/**
 * Paper panel — used sparingly for grouped records (tables, record lists, forms).
 * Tone and a hairline carry the edge; there are no drop shadows on paper.
 */
export function Surface({ raised, className, ...props }: SurfaceProps) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border",
        raised ? "bg-surface-raised" : "bg-surface",
        className
      )}
      {...props}
    />
  );
}
