"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Filter } from "lucide-react";
import { filterChips, filtersToSearchParams, parseFilters } from "@/lib/population/filters";

/** Shows the population filters handed over from the Population workspace. */
export function ReceivedFilters() {
  const filters = parseFilters(useSearchParams());
  const chips = filterChips(filters);
  if (chips.length === 0) return null;
  const back = `/?${filtersToSearchParams(filters).toString()}`;
  return (
    <section
      aria-label="Filters from the Population workspace"
      className="mb-6 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-4 py-3"
    >
      <Filter size={14} aria-hidden="true" className="text-faint" />
      <span className="text-xs font-medium text-muted">Filters carried from Population:</span>
      {chips.map((c) => (
        <span key={c.key} className="rounded-full bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent">
          {c.label}
        </span>
      ))}
      <span className="text-xs text-faint">— will be applied to the people list when it arrives.</span>
      <Link href={back} className="ml-auto text-xs font-medium text-accent hover:text-foreground">
        Back to Population
      </Link>
    </section>
  );
}
