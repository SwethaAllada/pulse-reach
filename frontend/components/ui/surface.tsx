import { cn } from "@/lib/cn";

interface SurfaceProps extends React.HTMLAttributes<HTMLDivElement> {
  raised?: boolean;
}

/** Layered card/panel — borders carry elevation, not heavy shadows. */
export function Surface({ raised, className, ...props }: SurfaceProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border shadow-[var(--shadow-card)]",
        raised ? "bg-surface-raised" : "bg-surface",
        className
      )}
      {...props}
    />
  );
}
