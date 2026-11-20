import { cn } from "@/lib/cn";

interface PlateProps {
  /** Folio number shown in the margin, e.g. "03". */
  index?: string;
  eyebrow?: string;
  title: string;
  description?: React.ReactNode;
  /** Accessible name; defaults to the title. */
  label?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  /** Lay the header in a left column beside the content on large screens. */
  aside?: boolean;
  id?: string;
}

/**
 * Editorial section ("plate") — a numbered folio opened by a hairline rule rather
 * than a boxed card. Different kinds of information keep their own layout inside.
 */
export function Plate({ index, eyebrow, title, description, label, actions, children, className, aside, id }: PlateProps) {
  return (
    <section
      id={id}
      aria-label={label ?? title}
      className={cn(
        "reveal scroll-mt-24 border-t border-border-strong pt-5",
        aside && "lg:grid lg:grid-cols-[260px_minmax(0,1fr)] lg:gap-10",
        className
      )}
    >
      <header className={cn("mb-5 flex flex-wrap items-start justify-between gap-3", aside && "lg:mb-0 lg:block")}>
        <div className="min-w-0">
          <p className="mb-2 flex items-center gap-2.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-faint">
            {index && <span className="font-mono tracking-normal text-action-text">{index}</span>}
            {eyebrow}
          </p>
          <h2 className="font-display text-2xl font-medium leading-tight tracking-[-0.015em] text-foreground">{title}</h2>
          {description && <div className="mt-2 max-w-prose text-sm leading-relaxed text-muted">{description}</div>}
        </div>
        {actions && <div className={cn("flex shrink-0 items-center gap-2", aside && "lg:mt-4")}>{actions}</div>}
      </header>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

/** Small-print source line closing a plate: definitions, provenance, caveats. */
export function Footnote({ children, className }: { children: React.ReactNode; className?: string }) {
  return <p className={cn("mt-4 text-[11px] leading-relaxed text-faint", className)}>{children}</p>;
}
