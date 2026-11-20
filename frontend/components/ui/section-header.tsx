interface SectionHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
}

export function SectionHeader({ eyebrow, title, description }: SectionHeaderProps) {
  return (
    <div className="mb-5">
      {eyebrow && (
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-faint">{eyebrow}</p>
      )}
      <h2 className="font-display text-xl font-medium tracking-[-0.01em] text-foreground">{title}</h2>
      {description && <p className="mt-1 max-w-prose text-sm leading-relaxed text-muted">{description}</p>}
    </div>
  );
}
