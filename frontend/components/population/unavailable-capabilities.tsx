import { ChevronDown } from "lucide-react";

/** Honest list of population capabilities the backend does not expose yet. */
const MISSING: { capability: string; needs: string }[] = [
  {
    capability: "Programme-scoped open-gap and history filters",
    needs:
      "GET /patients has has_open_care_gaps and history_status, but they match any programme. The programme views compare totals and disclose differences.",
  },
  {
    capability: "Per-programme coverage, completion rates and trends",
    needs:
      "No per-person outcome roll-up per programme. /population/summary gives organization-wide preventive coverage and 90-day comparisons only.",
  },
  {
    capability: "Server-side cohort aggregates",
    needs:
      "Segments are rolled up in the browser from every page of /patients and /care-gaps. A person-level roll-up endpoint (T-08) should replace this.",
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
