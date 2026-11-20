import { cn } from "@/lib/cn";

/** Atlas mark: a survey ring with marked points — a population read as a map. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-8", className)} fill="none">
      <rect x="0.5" y="0.5" width="31" height="31" rx="8" fill="var(--surface-brand)" />
      <circle cx="16" cy="16" r="9.5" stroke="var(--brand-highlight)" strokeOpacity="0.4" strokeWidth="1" />
      <path d="M6.5 16h19M16 6.5v19" stroke="var(--brand-line)" strokeWidth="0.8" />
      <circle cx="16" cy="16" r="9.5" stroke="var(--brand-highlight)" strokeWidth="1.4" strokeDasharray="16 44" strokeLinecap="round" />
      <circle cx="12" cy="13" r="2.1" fill="var(--accent-warm)" />
      <circle cx="19.5" cy="18.5" r="1.6" fill="var(--brand-highlight)" />
      <circle cx="18" cy="11.5" r="1" fill="var(--on-brand)" />
      <circle cx="12.5" cy="20" r="1" fill="var(--on-brand)" />
    </svg>
  );
}

export function LogoWordmark({ className }: { className?: string }) {
  return (
    <span lang="en" dir="ltr" className={cn("flex items-baseline font-display", className)}>
      <span className="text-[19px] font-medium tracking-[-0.02em] text-foreground">
        Pulse<span className="italic text-warm-text">Reach</span>
      </span>
    </span>
  );
}
