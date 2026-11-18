import { ChevronDown } from "lucide-react";

/** Honest list of population capabilities the backend does not expose yet. */
const MISSING: { capability: string; needs: string }[] = [
  {
    capability: "People filter by open care gap or history status",
    needs: "GET /api/v1/patients has no has_open_gap / history_status / evaluation_status parameters (audit T-06).",
  },
  {
    capability: "Age-group filter and breakdown",
    needs: "No age-band parameter on /patients and no age roll-up in /dashboard/summary (T-06, T-08).",
  },
  {
    capability: "Programme coverage / completion rates",
    needs: "No per-person outcome roll-up; summary counts are rule evaluations, not people (T-08).",
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
    <details className="group mt-10 rounded-lg border border-border bg-surface px-5 py-4">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-foreground">
        Not yet available from the API
        <ChevronDown size={16} aria-hidden="true" className="text-faint transition-transform group-open:rotate-180" />
      </summary>
      <ul className="mt-3 flex flex-col gap-2.5">
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
