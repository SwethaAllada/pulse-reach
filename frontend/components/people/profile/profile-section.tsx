import { cn } from "@/lib/cn";

export const PROFILE_SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "history", label: "Screening & History" },
  { id: "assessment", label: "Prevention Assessment" },
  { id: "evidence", label: "Evidence Trace" },
  { id: "care-gaps", label: "Care Gaps" },
  { id: "pathway", label: "Recommended Pathway" },
  { id: "coordination", label: "Care Coordination" },
] as const;

export type ProfileSectionId = (typeof PROFILE_SECTIONS)[number]["id"];

export function ProfileSection({
  id,
  title,
  description,
  children,
  className,
}: {
  id: ProfileSectionId;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-heading`} className={cn("scroll-mt-36", className)}>
      <h2 id={`${id}-heading`} className="font-display text-xl font-semibold tracking-tight text-foreground">
        {title}
      </h2>
      {description && <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Explicit "the API does not provide this" notice — dashed, never styled as a negative result. */
export function UnavailableNote({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-border-strong px-4 py-3 text-sm">
      <p className="font-medium text-foreground">{title}</p>
      <p className="mt-0.5 text-muted">{children}</p>
    </div>
  );
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-faint">{label}</dt>
      <dd className="mt-1 text-sm text-foreground">{children}</dd>
    </div>
  );
}
