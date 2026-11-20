"use client";

import { cn } from "@/lib/cn";
import type { MessageKey, Translate } from "@/lib/i18n/translate";
import { useT } from "@/lib/i18n/use-locale";

/**
 * Status glyph set — shape + colour + text label together, never colour alone.
 * Shapes follow the 24 px Lucide grid so they sit naturally beside app icons.
 */
export type EvaluationStatus =
  | "due"
  | "upcoming"
  | "eligible"
  | "completed"
  | "not_eligible"
  | "unknown"
  | "insufficient_information"
  | "requires_clinical_review";

const STATUS_META: Record<
  EvaluationStatus,
  { colorVar: string; label: MessageKey }
> = {
  due: { colorVar: "var(--status-due)", label: "status.due" },
  upcoming: { colorVar: "var(--status-upcoming)", label: "status.upcoming" },
  eligible: { colorVar: "var(--status-eligible)", label: "status.eligible" },
  completed: { colorVar: "var(--status-completed)", label: "status.completed" },
  not_eligible: { colorVar: "var(--status-not-eligible)", label: "status.not_eligible" },
  unknown: { colorVar: "var(--status-unknown)", label: "status.unknown" },
  insufficient_information: {
    colorVar: "var(--status-insufficient)",
    label: "status.insufficient_information",
  },
  requires_clinical_review: {
    colorVar: "var(--status-review)",
    label: "status.requires_clinical_review",
  },
};

interface StatusGlyphProps {
  status: EvaluationStatus;
  size?: number;
  className?: string;
}

export function StatusGlyph({ status, size = 14, className }: StatusGlyphProps) {
  const color = STATUS_META[status].colorVar;
  const props = { width: size, height: size, viewBox: "0 0 24 24", "aria-hidden": true as const };

  let shape: React.ReactNode;
  switch (status) {
    case "due":
      shape = <circle cx="12" cy="12" r="7" fill={color} />;
      break;
    case "upcoming":
      shape = (
        <>
          <circle cx="12" cy="12" r="7" fill="none" stroke={color} strokeWidth="1.75" />
          <path d="M12 5a7 7 0 0 1 7 7h-7z" fill={color} />
        </>
      );
      break;
    case "eligible":
      shape = <circle cx="12" cy="12" r="7" fill="none" stroke={color} strokeWidth="1.75" />;
      break;
    case "completed":
      shape = (
        <>
          <circle cx="12" cy="12" r="8" fill="none" stroke={color} strokeWidth="1.75" />
          <path
            d="m8.5 12.2 2.4 2.4 4.6-4.9"
            fill="none"
            stroke={color}
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      );
      break;
    case "not_eligible":
      shape = (
        <path d="M6 12h12" stroke={color} strokeWidth="1.75" strokeLinecap="round" />
      );
      break;
    case "unknown":
      shape = (
        <circle
          cx="12"
          cy="12"
          r="7"
          fill="none"
          stroke={color}
          strokeWidth="1.75"
          strokeDasharray="3 2.5"
        />
      );
      break;
    case "insufficient_information":
      shape = (
        <path
          d="M12 5.5 20 19H4z"
          fill="none"
          stroke={color}
          strokeWidth="1.75"
          strokeLinejoin="round"
        />
      );
      break;
    case "requires_clinical_review":
      shape = <path d="M12 4.5 19.5 12 12 19.5 4.5 12z" fill={color} />;
      break;
  }

  return (
    <svg {...props} className={cn("shrink-0", className)}>
      {shape}
    </svg>
  );
}

export function statusLabel(status: EvaluationStatus, t: Translate): string {
  return t(STATUS_META[status].label);
}

export function statusColor(status: EvaluationStatus): string {
  return STATUS_META[status].colorVar;
}

interface StatusLabelProps {
  status: EvaluationStatus;
  label?: string;
  className?: string;
}

/** Glyph + label — the only correct way to surface a status. */
export function StatusLabel({ status, label, className }: StatusLabelProps) {
  const t = useT();
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm", className)}>
      <StatusGlyph status={status} />
      <span className="text-muted">{label ?? statusLabel(status, t)}</span>
    </span>
  );
}
