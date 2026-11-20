"use client";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-locale";
import type { MessageKey } from "@/lib/i18n/translate";

interface LoadingStateProps {
  rows?: number;
  className?: string;
  label?: string;
  /** For server components, which cannot translate: a message key instead of `label`. */
  labelKey?: MessageKey;
}

/** Skeleton rows — same shape as final content, no spinners. */
export function LoadingState({ rows = 3, className, label, labelKey }: LoadingStateProps) {
  const t = useT();
  return (
    <div aria-busy="true" aria-label={label ?? t(labelKey ?? "state.loading")} className={cn("flex flex-col gap-3", className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="skeleton h-9 rounded-md"
          style={{ animationDelay: `${i * 120}ms`, width: `${100 - ((i * 13) % 30)}%` }}
        />
      ))}
    </div>
  );
}
