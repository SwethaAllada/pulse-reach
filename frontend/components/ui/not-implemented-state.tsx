import type { LucideIcon } from "lucide-react";
import { Surface } from "./surface";
import { SectionHeader } from "./section-header";

interface NotImplementedStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  /** What this area will do once its backend capability lands. */
  roadmap?: string;
}

/**
 * Honest placeholder for routes that exist in the navigation but whose
 * feature work is scheduled for a later phase.
 */
export function NotImplementedState({ icon: Icon, title, description, roadmap }: NotImplementedStateProps) {
  return (
    <Surface className="flex flex-col items-start gap-4 p-8">
      <span className="flex size-11 items-center justify-center rounded-full bg-accent-soft text-accent">
        <Icon size={22} strokeWidth={1.75} aria-hidden="true" />
      </span>
      <SectionHeader title={title} description={description} />
      {roadmap && (
        <p className="rounded-md bg-surface-sunken px-3 py-2 text-xs text-muted">
          Planned: {roadmap}
        </p>
      )}
    </Surface>
  );
}
