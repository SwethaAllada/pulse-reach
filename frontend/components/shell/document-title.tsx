"use client";

import { Suspense, useEffect } from "react";
import { usePathname } from "next/navigation";
import type { MessageKey } from "@/lib/i18n/translate";
import { useLocale } from "@/lib/i18n/use-locale";

/* Route → title key. Next sets English `metadata` titles; in Arabic they are replaced here. */
const TITLES: [RegExp, MessageKey][] = [
  [/^\/$/, "app.title_default"],
  [/^\/people\/[^/]+$/, "page.person_profile"],
  [/^\/people$/, "nav.people"],
  [/^\/programmes\/[^/]+\/rules\//, "nav.programme_rules"],
  [/^\/programmes\/[^/]+$/, "page.programme"],
  [/^\/programmes$/, "nav.programmes"],
  [/^\/follow-up/, "nav.follow_up"],
  [/^\/appointments/, "nav.appointments_referrals"],
  [/^\/population/, "nav.panel_insights"],
  [/^\/facilities/, "nav.facilities"],
  [/^\/admin\/users/, "nav.users_roles"],
  [/^\/admin\/assignments/, "nav.care_team_assignments"],
  [/^\/admin\/patient-links/, "nav.patient_portal_links"],
  [/^\/admin\/audit/, "nav.audit_log"],
  [/^\/admin\/population/, "nav.population_aggregation"],
];

function TitleSync() {
  const pathname = usePathname();
  const { locale, t } = useLocale();
  useEffect(() => {
    if (locale === "en") return; // English titles come from route metadata.
    const key = TITLES.find(([re]) => re.test(pathname))?.[1];
    if (!key) return;
    const title = key === "app.title_default" ? t(key) : `${t(key)} · PulseReach`;
    const apply = () => {
      if (document.title !== title) document.title = title;
    };
    apply();
    // Next re-applies metadata titles after navigation; keep the localized one.
    const observer = new MutationObserver(apply);
    observer.observe(document.head, { subtree: true, childList: true, characterData: true });
    return () => observer.disconnect();
  }, [pathname, locale, t]);
  return null;
}

export function DocumentTitle() {
  return (
    <Suspense fallback={null}>
      <TitleSync />
    </Suspense>
  );
}
