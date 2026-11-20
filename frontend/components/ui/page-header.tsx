"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-locale";

export interface Breadcrumb {
  label: string;
  href?: string;
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  /** Workspace name shown above the title when there are no breadcrumbs. */
  eyebrow?: string;
  /** @deprecated Folio numbers are no longer displayed. */
  index?: string;
  breadcrumbs?: Breadcrumb[];
  actions?: React.ReactNode;
  /** Context line under the subtitle (run, reference date, scope). */
  meta?: React.ReactNode;
  className?: string;
}

/** Workspace header: breadcrumb trail, title, one-line purpose, context and actions. */
export function PageHeader({ title, subtitle, eyebrow, breadcrumbs, actions, meta, className }: PageHeaderProps) {
  const t = useT();
  return (
    <header className={cn("reveal", className)}>
      {breadcrumbs && breadcrumbs.length > 0 ? (
        <nav aria-label={t("shell.breadcrumb")} className="mb-3">
          <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-faint">
            {breadcrumbs.map((crumb, i) => (
              <li key={i} className="flex items-center gap-1.5">
                {i > 0 && <ChevronRight size={12} aria-hidden="true" className="rtl:-scale-x-100" />}
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
      ) : (
        eyebrow && <p className="mb-2 text-xs font-medium text-faint">{eyebrow}</p>
      )}
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="min-w-0 max-w-3xl">
          <h1 className="font-display text-[28px] font-medium leading-tight tracking-[-0.015em] text-foreground">{title}</h1>
          {subtitle && <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">{subtitle}</p>}
          {meta && <div className="mt-2 text-xs text-faint">{meta}</div>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}
