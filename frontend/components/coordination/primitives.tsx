"use client";

import { AlertTriangle, ChevronLeft, ChevronRight, EyeOff, MonitorSmartphone } from "lucide-react";
import type { TaskPriority } from "@/lib/api/types";
import { PRIORITY_META, TONE_COLOR, type Tone } from "@/lib/coordination/model";
import { buttonClass } from "@/components/ui/button-styles";
import { cn } from "@/lib/cn";
import { useLocale } from "@/lib/i18n/use-locale";

type Surface = "paper" | "ink";

/** Shape + colour per tone, mirroring the status glyph language (never colour alone). */
export function ToneGlyph({ tone, surface = "paper", size = 12 }: { tone: Tone; surface?: Surface; size?: number }) {
  const c = TONE_COLOR[tone][surface];
  const shape =
    tone === "completed" ? (
      <>
        <circle cx="12" cy="12" r="8" fill="none" stroke={c} strokeWidth="2" />
        <path d="m8.5 12.2 2.4 2.4 4.6-4.9" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </>
    ) : tone === "due" ? (
      <circle cx="12" cy="12" r="7" fill={c} />
    ) : tone === "upcoming" ? (
      <>
        <circle cx="12" cy="12" r="7" fill="none" stroke={c} strokeWidth="2" />
        <path d="M12 5a7 7 0 0 1 7 7h-7z" fill={c} />
      </>
    ) : tone === "review" ? (
      <path d="M12 4.5 19.5 12 12 19.5 4.5 12z" fill={c} />
    ) : tone === "insufficient" ? (
      <path d="M12 5.5 20 19H4z" fill="none" stroke={c} strokeWidth="2" strokeLinejoin="round" />
    ) : tone === "not_eligible" ? (
      <path d="M6 12h12" stroke={c} strokeWidth="2" strokeLinecap="round" />
    ) : (
      <circle cx="12" cy="12" r="7" fill="none" stroke={c} strokeWidth="2" />
    );
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="shrink-0">
      {shape}
    </svg>
  );
}

export function StatusPill({ tone, label, surface = "paper", className }: { tone: Tone; label: string; surface?: Surface; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium",
        surface === "ink" ? "border-ink-line text-ink-text" : "border-border bg-surface-raised text-foreground",
        className
      )}
    >
      <ToneGlyph tone={tone} surface={surface} size={11} />
      {label}
    </span>
  );
}

/** Priority as rising bars plus its word, so urgency is never colour alone. */
export function PriorityMark({ priority, surface = "paper", showLabel = true }: { priority: TaskPriority; surface?: Surface; showLabel?: boolean }) {
  const { t } = useLocale();
  const meta = PRIORITY_META[priority];
  const label = t(meta.label);
  const c = TONE_COLOR[meta.tone][surface];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs" title={t("coord.priority.title", { priority: label })}>
      <svg width="14" height="12" viewBox="0 0 14 12" aria-hidden="true" className="shrink-0">
        {[0, 1, 2].map((i) => (
          <rect
            key={i}
            x={i * 5}
            y={8 - i * 4}
            width="3.5"
            height={4 + i * 4}
            rx="1"
            fill={i < meta.bars ? c : "none"}
            stroke={c}
            strokeWidth="1"
            opacity={i < meta.bars ? 1 : 0.45}
          />
        ))}
      </svg>
      {showLabel ? (
        <span className={surface === "ink" ? "text-ink-muted" : "text-muted"}>{label}</span>
      ) : (
        <span className="sr-only">{t("coord.priority.title", { priority: label })}</span>
      )}
    </span>
  );
}

/** Who can see an entry: internal (staff only) or the patient portal. */
export function VisibilityBadge({ visibility }: { visibility: "internal" | "patient" | "record" }) {
  const { t } = useLocale();
  if (visibility === "record") return null;
  return visibility === "internal" ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-surface-sunken px-2 py-0.5 text-[11px] font-medium text-muted">
      <EyeOff size={11} aria-hidden="true" /> {t("coord.visibility.internal")}
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent">
      <MonitorSmartphone size={11} aria-hidden="true" /> {t("coord.visibility.patient")}
    </span>
  );
}

/** Proportional band of exact counts; segments with 0 are omitted, the legend keeps them. */
export function DistributionBand({
  label,
  parts,
  surface = "paper",
  onSelect,
  selected,
}: {
  label: string;
  parts: { key: string; label: string; count: number; tone: Tone }[];
  surface?: Surface;
  onSelect?: (key: string) => void;
  selected?: string | null;
}) {
  const { t } = useLocale();
  const total = parts.reduce((n, p) => n + p.count, 0);
  const ink = surface === "ink";
  return (
    <div>
      <div
        role="img"
        aria-label={`${label}: ${parts.map((p) => t("coord.band.part", { label: p.label, count: String(p.count) })).join(t("list.sep"))}`}
        className={cn("flex h-2.5 w-full gap-[3px] overflow-hidden rounded-full", ink ? "bg-ink-raised" : "bg-surface-sunken")}
      >
        {total > 0 &&
          parts
            .filter((p) => p.count > 0)
            .map((p, i) => (
              <span
                key={p.key}
                className={cn("grow-x h-full", selected && selected !== p.key && "opacity-30")}
                style={{ width: `${(p.count / total) * 100}%`, backgroundColor: TONE_COLOR[p.tone][surface], "--i": i } as React.CSSProperties}
              />
            ))}
      </div>
      <ul className={cn("mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs", ink ? "text-ink-muted" : "text-muted")}>
        {parts.map((p) => {
          const body = (
            <>
              <ToneGlyph tone={p.tone} surface={surface} size={11} />
              {p.label}
              <span className={cn("font-mono tabular-nums", ink ? "text-ink-text" : "text-foreground")}>{p.count}</span>
            </>
          );
          return (
            <li key={p.key}>
              {onSelect ? (
                <button
                  type="button"
                  aria-pressed={selected === p.key}
                  onClick={() => onSelect(p.key)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full underline-offset-4 hover:underline",
                    selected === p.key && (ink ? "text-ink-text underline" : "text-foreground underline")
                  )}
                >
                  {body}
                </button>
              ) : (
                <span className="inline-flex items-center gap-1.5">{body}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export const inputClass =
  "h-9 w-full min-w-0 rounded-lg border border-border-strong bg-surface-raised px-3 text-sm text-foreground transition-colors duration-200 placeholder:text-faint hover:border-faint focus-visible:border-accent";
/** Compact control for toolbars and table rows: no width, so callers size it. */
export const compactInputClass =
  "h-8 min-w-0 rounded-lg border border-border-strong bg-surface-raised px-2.5 text-sm text-foreground transition-colors duration-200 placeholder:text-faint hover:border-faint focus-visible:border-accent";
export const textareaClass =
  "min-h-20 w-full rounded-lg border border-border-strong bg-surface-raised px-3 py-2 text-sm text-foreground transition-colors duration-200 placeholder:text-faint hover:border-faint focus-visible:border-accent";
export const labelClass = "flex min-w-0 flex-col gap-1.5 text-xs font-medium text-muted";

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="reveal flex items-start gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-sm text-muted">
      <AlertTriangle size={15} aria-hidden="true" className="mt-0.5 shrink-0 text-status-error" />
      <span>{message}</span>
    </p>
  );
}

/** Inline confirmation after a write, announced politely. */
export function Confirmation({ children }: { children: React.ReactNode }) {
  return (
    <p role="status" className="reveal rounded-xl bg-accent-soft px-3 py-2 text-sm text-foreground">
      {children}
    </p>
  );
}

/** `label` names what is paged (already translated by the caller), e.g. "Follow-up". */
export function Pager({ page, total, size, onPage, label }: { page: number; total: number; size: number; onPage: (p: number) => void; label: string }) {
  const { t } = useLocale();
  const pages = Math.max(1, Math.ceil(total / size));
  if (total <= size) return null;
  return (
    <nav aria-label={t("coord.pager.aria", { label })} className="mt-4 flex items-center justify-between gap-3 text-sm text-muted">
      <span>{t("coord.pager.range", { from: String((page - 1) * size + 1), to: String(Math.min(page * size, total)), total: String(total) })}</span>
      <span className="flex gap-2">
        <button type="button" className={buttonClass("secondary")} disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft size={14} aria-hidden="true" className="rtl:-scale-x-100" /> {t("coord.pager.previous")}
        </button>
        <button type="button" className={buttonClass("secondary")} disabled={page >= pages} onClick={() => onPage(page + 1)}>
          {t("coord.pager.next")} <ChevronRight size={14} aria-hidden="true" className="rtl:-scale-x-100" />
        </button>
      </span>
    </nav>
  );
}

/** A queue that is genuinely empty (not loading, not refused). */
export function QuietEmpty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="reveal rounded-xl border border-dashed border-border-strong px-5 py-8 text-center">
      <p className="text-[15px] font-semibold text-foreground">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</p>}
    </div>
  );
}
