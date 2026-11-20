import Link from "next/link";
import { cn } from "@/lib/cn";

export interface Breadcrumb {
  label: string;
  href?: string;
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  /** Position in the atlas journey, e.g. "02". */
  index?: string;
  breadcrumbs?: Breadcrumb[];
  actions?: React.ReactNode;
  /** Context line under the subtitle (run, reference date, scope). */
  meta?: React.ReactNode;
  className?: string;
}

/** Editorial page masthead: path, serif title, standfirst and a closing rule. */
export function PageHeader({
  title,
  subtitle,
  eyebrow,
  index,
  breadcrumbs,
  actions,
  meta,
  className,
}: PageHeaderProps) {
  return (
    <header className={cn("reveal border-b border-border pb-6", className)}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-5">
          <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-faint">
            {breadcrumbs.map((crumb, i) => (
              <li key={i} className="flex items-center gap-2">
                {i > 0 && <span aria-hidden="true" className="h-px w-3 bg-border-strong" />}
                {crumb.href ? (
                  <Link href={crumb.href} className="transition-colors hover:text-foreground">
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current="page" className="text-muted">
                    {crumb.label}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="min-w-0 max-w-3xl">
          {(eyebrow || index) && (
            <p className="mb-3 flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-action-text">
              {index && <span className="font-mono tracking-normal text-faint">{index}</span>}
              {index && eyebrow && <span aria-hidden="true" className="h-px w-6 bg-border-strong" />}
              {eyebrow}
            </p>
          )}
          <h1 className="font-display text-4xl font-medium leading-[1.05] tracking-[-0.02em] text-foreground sm:text-5xl">
            {title}
          </h1>
          {subtitle && <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-muted">{subtitle}</p>}
          {meta && <div className="mt-3 text-xs text-faint">{meta}</div>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}
