"use client";

import { cn } from "@/lib/cn";

/** Single-choice toggle group; the selected option is an inked pill that slides between options. */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  className,
}: {
  label: string;
  options: { value: T; label: React.ReactNode }[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  const index = Math.max(0, options.findIndex((o) => o.value === value));
  return (
    <div
      role="group"
      aria-label={label}
      className={cn("relative inline-grid rounded-full border border-border bg-surface-sunken p-0.5 text-xs", className)}
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      <span
        aria-hidden="true"
        className="absolute inset-y-0.5 left-0.5 rounded-full bg-surface-raised shadow-[var(--shadow-thumb)] ring-1 ring-border-strong transition-transform duration-300 ease-[var(--ease-out)]"
        style={{ width: `calc((100% - 4px) / ${options.length})`, transform: `translateX(${index * 100}%)` }}
      />
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "relative z-10 inline-flex h-8 items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-3 font-medium transition-colors duration-200",
            o.value === value ? "text-foreground" : "text-muted hover:text-foreground"
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
