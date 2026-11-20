"use client";

import { ChevronDown } from "lucide-react";
import type { MessageKey } from "@/lib/i18n/translate";
import { useT } from "@/lib/i18n/use-locale";

/** Honest list of population capabilities the backend does not expose yet. */
const MISSING: { capability: MessageKey; needs: MessageKey }[] = [
  { capability: "pop.limits.trends", needs: "pop.limits.trends_needs" },
  { capability: "pop.limits.aggregates", needs: "pop.limits.aggregates_needs" },
  { capability: "pop.limits.filtered", needs: "pop.limits.filtered_needs" },
];

export function UnavailableCapabilities() {
  const t = useT();
  return (
    <details className="group mt-16 border-y border-border py-4">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-foreground">
        <span>
          <span className="me-3 font-mono text-[11px] font-normal text-faint">{t("pop.limits.tag")}</span>
          {t("pop.limits.title")}
        </span>
        <ChevronDown size={16} aria-hidden="true" className="text-faint transition-transform duration-300 group-open:rotate-180" />
      </summary>
      <ul className="mt-4 grid grid-cols-1 gap-x-10 gap-y-3 md:grid-cols-2">
        {MISSING.map((m) => (
          <li key={m.capability} className="text-sm">
            <span className="font-medium text-foreground">{t(m.capability)}.</span>{" "}
            <span className="text-muted">{t(m.needs)}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
