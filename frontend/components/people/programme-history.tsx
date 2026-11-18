import type { HistoryStatus, Pathway } from "@/lib/api/types";
import { pathwayLabel } from "@/lib/population/filters";
import { historyMeta } from "@/lib/people/person";
import { PROGRAMME_COLOR, SegmentGlyph } from "@/components/population/segment-glyph";
import { cn } from "@/lib/cn";

const HISTORY_STATUSES: HistoryStatus[] = ["available", "partial", "not_available"];

/** Programme membership plus its history availability — shape, colour and text together. */
export function ProgrammeHistory({
  pathway,
  history,
  compact,
  className,
}: {
  pathway: Pathway;
  history: string | undefined;
  compact?: boolean;
  className?: string;
}) {
  const known = HISTORY_STATUSES.find((h) => h === history);
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm", className)}>
      <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
        <span
          aria-hidden="true"
          className="size-2 shrink-0 rounded-full"
          style={{ backgroundColor: PROGRAMME_COLOR[pathway].paper }}
        />
        {pathwayLabel(pathway, compact)}
      </span>
      <span className="inline-flex items-center gap-1 text-xs text-muted">
        {known && <SegmentGlyph segment={known} size={10} />}
        {historyMeta(history).label}
      </span>
    </span>
  );
}
