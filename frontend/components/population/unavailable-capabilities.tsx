import { ChevronDown } from "lucide-react";

/** Honest list of population capabilities the backend does not expose yet. */
const MISSING: { capability: string; needs: string }[] = [
  {
    capability: "Per-programme historical trends",
    needs:
      "GET /programmes/{pathway}/summary compares periods only where persisted evaluation runs cover them. The synthetic data has a single evaluation run, so earlier periods are unobserved.",
  },
  {
    capability: "Server-side cohort aggregates",
    needs:
      "This workspace still rolls segments up in the browser from every page of /patients and /care-gaps. The programme views use GET /programmes/{pathway}/summary instead.",
  },
  {
    capability: "Filtered care-gap and evaluation summaries",
    needs: "/care-gaps cannot filter by region, sex or programme; /dashboard/summary accepts no filters.",
  },
];

export function UnavailableCapabilities() {
  return (
    <details className="group mt-16 border-y border-border py-4">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-foreground">
        <span>
          <span className="mr-3 font-mono text-[11px] font-normal text-faint">Limits</span>
          Not yet available from the API
        </span>
        <ChevronDown size={16} aria-hidden="true" className="text-faint transition-transform duration-300 group-open:rotate-180" />
      </summary>
      <ul className="mt-4 grid grid-cols-1 gap-x-10 gap-y-3 md:grid-cols-2">
        {MISSING.map((m) => (
          <li key={m.capability} className="text-sm">
            <span className="font-medium text-foreground">{m.capability}.</span>{" "}
            <span className="text-muted">{m.needs}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
