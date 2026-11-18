import { cn } from "@/lib/cn";

/** Constellation mark: nodes joined like a star chart — "see the signals". */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      aria-hidden="true"
      className={cn("size-8", className)}
      fill="none"
    >
      <rect
        x="1"
        y="1"
        width="30"
        height="30"
        rx="7"
        className="fill-ink stroke-ink-line"
      />
      <path
        d="M9.5 21.5 15 12.5l6.5 4"
        stroke="var(--ink-accent-2)"
        strokeWidth="1.25"
        strokeLinecap="round"
        opacity="0.75"
      />
      <circle cx="9.5" cy="21.5" r="2.6" fill="var(--ink-accent)" />
      <circle cx="15" cy="12.5" r="2" fill="var(--ink-accent-2)" />
      <circle cx="21.5" cy="16.5" r="3.4" fill="none" stroke="var(--ink-accent)" strokeWidth="1.4" />
      <circle cx="21.5" cy="16.5" r="1.3" fill="var(--ink-accent)" />
      <circle cx="24" cy="9" r="1.1" fill="var(--ink-muted)" />
      <circle cx="8" cy="9.5" r="0.9" fill="var(--ink-muted)" />
    </svg>
  );
}

export function LogoWordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-baseline gap-1 font-display", className)}>
      <span className="text-[17px] font-semibold tracking-tight text-foreground">
        Pulse<span className="text-accent">Reach</span>
      </span>
    </span>
  );
}
