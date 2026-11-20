interface SectionHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
}

export function SectionHeader({ eyebrow, title, description }: SectionHeaderProps) {
  return (
    <div className="mb-4">
      {eyebrow && <p className="mb-1 text-xs font-medium text-faint">{eyebrow}</p>}
      <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
      {description && <p className="mt-1 max-w-prose text-[13px] leading-relaxed text-muted">{description}</p>}
    </div>
  );
}
