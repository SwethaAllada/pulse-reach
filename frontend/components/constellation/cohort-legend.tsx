import { SEGMENT_META, SEGMENT_ORDER } from "@/lib/population/model";
import { SegmentGlyph } from "@/components/population/segment-glyph";

/** Shape + colour key for the constellation marks (ink surface). */
export function CohortLegend() {
  return (
    <figure>
      <ul className="flex flex-wrap gap-x-5 gap-y-2" aria-label="Constellation legend">
        {SEGMENT_ORDER.map((seg) => (
          <li key={seg} className="flex items-center gap-2 text-xs text-ink-muted">
            <SegmentGlyph segment={seg} surface="ink" size={12} />
            {SEGMENT_META[seg].label}
          </li>
        ))}
      </ul>
      <figcaption className="mt-2 text-[11px] leading-relaxed text-ink-faint">
        Each mark is one synthetic person. Dashed territories are programmes; clusters are evidence
        segments sized by real head-count. Position within a cluster is a fixed pattern and implies
        no clinical similarity or risk.
      </figcaption>
    </figure>
  );
}
