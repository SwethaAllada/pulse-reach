import { FlaskConical } from "lucide-react";

/** Persistent honesty ribbon: every screen states the data is synthetic. */
export function SyntheticBanner() {
  return (
    <div className="flex items-center justify-center gap-2 bg-ink px-4 py-1 text-center">
      <FlaskConical size={12} aria-hidden="true" className="shrink-0 text-ink-accent" />
      <p className="text-[11px] font-medium tracking-wide text-ink-muted">
        <span className="text-ink-text">Synthetic demonstration data</span> — no real people. Not clinically validated.
      </p>
    </div>
  );
}
