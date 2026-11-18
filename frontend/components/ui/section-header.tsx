interface SectionHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
}

export function SectionHeader({ eyebrow, title, description }: SectionHeaderProps) {
  return (
    <div className="mb-4">
      {eyebrow && (
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
          {eyebrow}
        </p>
      )}
      <h2 className="text-lg font-semibold text-foreground">{title}</h2>
      {description && <p className="mt-1 text-sm text-muted">{description}</p>}
    </div>
  );
}
