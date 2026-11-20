"use client";

import { SEGMENT_META, SEGMENT_ORDER } from "@/lib/population/model";
import { useT } from "@/lib/i18n/use-locale";
import { SegmentGlyph } from "@/components/population/segment-glyph";

/** Shape + colour key for the constellation marks (ink surface). */
export function CohortLegend() {
  const t = useT();
  return (
    <figure>
      <ul className="flex flex-wrap gap-x-5 gap-y-2" aria-label={t("pop.legend.label")}>
        {SEGMENT_ORDER.map((seg) => (
          <li key={seg} className="flex items-center gap-2 text-xs text-ink-muted">
            <SegmentGlyph segment={seg} surface="ink" size={12} />
            {t(SEGMENT_META[seg].label)}
          </li>
        ))}
      </ul>
      <figcaption className="mt-2 text-[11px] leading-relaxed text-ink-faint">
        {t("pop.legend.caption")}
      </figcaption>
    </figure>
  );
}
