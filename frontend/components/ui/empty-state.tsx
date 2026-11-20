import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  children?: React.ReactNode;
}

/** Absence, stated plainly: a dashed outline means "nothing recorded here", never "negative". */
export function EmptyState({ icon: Icon, title, description, children }: EmptyStateProps) {
  return (
    <div className="reveal flex flex-col items-center gap-3 rounded-xl border border-dashed border-border-strong px-6 py-10 text-center">
      <span className="flex size-10 items-center justify-center rounded-full bg-surface-sunken text-faint">
        <Icon size={18} strokeWidth={1.5} aria-hidden="true" />
      </span>
      <p className="font-display text-lg font-medium text-foreground">{title}</p>
      <p className="max-w-sm text-sm text-muted">{description}</p>
      {children}
    </div>
  );
}
