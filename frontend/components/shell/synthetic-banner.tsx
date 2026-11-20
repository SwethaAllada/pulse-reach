"use client";

import { FlaskConical } from "lucide-react";
import { useLocale } from "@/lib/i18n/use-locale";

/** Persistent honesty ribbon: every screen states the data is synthetic. */
export function SyntheticBanner() {
  const { t, rich } = useLocale();
  return (
    <div className="flex items-center justify-center gap-2 border-b border-border bg-surface-sunken px-4 py-1 text-center">
      <FlaskConical size={12} aria-hidden="true" className="shrink-0 text-warm-text" />
      <p className="text-[11px] font-medium text-muted">
        {rich("shell.synthetic_banner", {
          strong: <span className="text-foreground">{t("shell.synthetic_banner_strong")}</span>,
        })}
      </p>
    </div>
  );
}
