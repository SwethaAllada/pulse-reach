import { FlaskConical } from "lucide-react";

/** Persistent honesty stripe: every screen states the data is synthetic. */
export function SyntheticBanner() {
  return (
    <div className="flex items-center justify-center gap-2 border-b border-border bg-surface-sunken px-4 py-1.5 text-center">
      <FlaskConical size={13} aria-hidden="true" className="shrink-0 text-faint" />
      <p className="text-[11px] font-medium text-faint">
        Synthetic demonstration data — no real people. Illustrative values only.
      </p>
    </div>
  );
}
