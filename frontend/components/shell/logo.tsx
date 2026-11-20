import { cn } from "@/lib/cn";

/** Atlas mark: a survey ring with marked points — a population read as a map. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-8", className)} fill="none">
      <rect x="1" y="1" width="30" height="30" rx="9" className="fill-ink stroke-ink-line" strokeWidth="1" />
      <circle cx="16" cy="16" r="9.5" stroke="var(--ink-line)" strokeWidth="1" />
      <path d="M6.5 16h19M16 6.5v19" stroke="var(--ink-line)" strokeWidth="0.8" />
      <circle cx="16" cy="16" r="9.5" stroke="var(--ink-accent-2)" strokeWidth="1.4" strokeDasharray="16 44" strokeLinecap="round" />
      <circle cx="12" cy="13" r="2.1" fill="var(--ink-accent)" />
      <circle cx="19.5" cy="18.5" r="1.6" fill="var(--ink-accent-2)" />
      <circle cx="18" cy="11.5" r="1" fill="var(--ink-muted)" />
      <circle cx="12.5" cy="20" r="1" fill="var(--ink-muted)" />
    </svg>
  );
}

export function LogoWordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-baseline font-display", className)}>
      <span className="text-[19px] font-medium tracking-[-0.02em] text-foreground">
        Pulse<span className="italic text-action-text">Reach</span>
      </span>
    </span>
  );
}
