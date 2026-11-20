"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Filter } from "lucide-react";
import { filterChips, filtersToSearchParams, parseFilters } from "@/lib/population/filters";
import { useT } from "@/lib/i18n/use-locale";

/** Shows the population filters handed over from the Population workspace. */
export function ReceivedFilters() {
  const t = useT();
  const filters = parseFilters(useSearchParams());
  const chips = filterChips(filters, t);
  if (chips.length === 0) return null;
  const back = `/?${filtersToSearchParams(filters).toString()}`;
  return (
    <section
      aria-label={t("pop.received.label")}
      className="mb-6 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-4 py-3"
    >
      <Filter size={14} aria-hidden="true" className="text-faint" />
      <span className="text-xs font-medium text-muted">{t("pop.received.carried")}</span>
      {chips.map((c) => (
        <span key={c.key} className="rounded-full bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent">
          {c.label}
        </span>
      ))}
      <span className="text-xs text-faint">{t("pop.received.pending")}</span>
      <Link href={back} className="ms-auto text-xs font-medium text-accent hover:text-foreground">
        {t("pop.received.back")}
      </Link>
    </section>
  );
}
