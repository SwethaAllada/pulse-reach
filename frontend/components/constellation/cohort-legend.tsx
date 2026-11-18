import { COHORTS } from "./constellation-visualization";

export function CohortLegend() {
  return (
    <figure>
      <ul className="flex flex-col gap-2.5">
        {COHORTS.map((c) => (
          <li key={c.id} className="flex items-center gap-2.5 text-sm">
            <span
              aria-hidden="true"
              className="size-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: c.colorVar }}
            />
            <span className="text-ink-text">{c.label}</span>
            <span className="ml-auto font-mono text-xs tabular-nums text-ink-muted">
              {c.count}
            </span>
          </li>
        ))}
      </ul>
      <figcaption className="mt-4 border-t border-ink-line pt-3 text-[11px] leading-relaxed text-ink-faint">
        Each point is one synthetic person. Clusters are labelled cohort territories; positions and
        counts are illustrative demo values, not statistics or clinical relationships.
      </figcaption>
    </figure>
  );
}
