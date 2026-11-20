import { cn } from "@/lib/cn";

interface PlateProps {
  /** @deprecated Folio numbers are no longer displayed; kept for call-site compatibility. */
  index?: string;
  /** Short context label shown before the title (e.g. the data source or scope). */
  eyebrow?: string;
  title: string;
  description?: React.ReactNode;
  /** Accessible name; defaults to the title. */
  label?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  /** Lay the header in a narrow column beside the content on large screens. */
  aside?: boolean;
  id?: string;
  /** Remove body padding (tables and lists that run edge to edge). */
  flush?: boolean;
}

/**
 * Dashboard card: a titled panel on the elevated surface. Header = title, one-line
 * description and actions; the body keeps each kind of information's own layout.
 */
export function Plate({ eyebrow, title, description, label, actions, children, className, aside, id, flush }: PlateProps) {
  return (
    <section
      id={id}
      aria-label={label ?? title}
      className={cn(
        "reveal min-w-0 scroll-mt-24 rounded-xl border border-border bg-surface-raised",
        aside && "lg:grid lg:grid-cols-[240px_minmax(0,1fr)]",
        className
      )}
    >
      <header
        className={cn(
          "flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4",
          aside && "lg:block lg:border-b-0 lg:border-e"
        )}
      >
        <div className="min-w-0">
          {eyebrow && <p className="mb-1 text-xs font-medium text-faint">{eyebrow}</p>}
          <h2 className="text-[15px] font-semibold leading-snug text-foreground">{title}</h2>
          {description && <div className="mt-1 max-w-prose text-[13px] leading-relaxed text-muted">{description}</div>}
        </div>
        {actions && <div className={cn("flex shrink-0 items-center gap-2", aside && "lg:mt-4")}>{actions}</div>}
      </header>
      <div className={cn("min-w-0", !flush && "p-5")}>{children}</div>
    </section>
  );
}

/** Small-print source line closing a card: definitions, provenance, caveats. */
export function Footnote({ children, className }: { children: React.ReactNode; className?: string }) {
  return <p className={cn("mt-4 text-[11px] leading-relaxed text-faint", className)}>{children}</p>;
}
