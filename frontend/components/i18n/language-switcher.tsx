"use client";

import { useEffect } from "react";
import { Languages } from "lucide-react";
import { useAuth } from "@/lib/auth/auth-context";
import { LOCALES } from "@/lib/i18n/config";
import { reconcileSignedInLocale, useChangeLanguage } from "@/lib/i18n/preference";
import { bootLocale } from "@/lib/i18n/store";
import { useLocale } from "@/lib/i18n/use-locale";
import { cn } from "@/lib/cn";

/**
 * Mounted once at the root: adopts the stored language after hydration, then applies the
 * account's saved language once per signed-in identity (see `lib/i18n/preference`).
 */
export function LocaleSync() {
  useEffect(() => bootLocale(), []);
  const { state } = useAuth();
  const userId = state.status === "signed_in" ? state.me.user.user_id : null;
  const preference = state.status === "signed_in" ? state.me.user.preferred_language : null;
  useEffect(() => {
    if (userId) reconcileSignedInLocale(preference);
    // Once per identity: later preference changes come from this browser.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);
  return null;
}

/**
 * English / العربية toggle. Each option is labelled in its own language (and `lang`) so it is
 * recognisable whichever language is active.
 */
export function LanguageSwitcher({ className }: { className?: string }) {
  const { locale, t } = useLocale();
  const change = useChangeLanguage();
  return (
    <div role="group" aria-label={t("language.label")} className={cn("flex items-center gap-1", className)}>
      <Languages size={15} aria-hidden="true" className="shrink-0 text-faint" />
      {LOCALES.map((l) => (
        <button
          key={l}
          type="button"
          lang={l}
          aria-pressed={locale === l}
          onClick={() => change(l)}
          className={cn(
            "h-7 rounded-full px-2.5 text-xs font-medium transition-colors",
            locale === l ? "bg-nav-active-bg text-foreground" : "text-muted hover:bg-surface-sunken hover:text-foreground"
          )}
        >
          {t(`language.${l}`)}
        </button>
      ))}
    </div>
  );
}
