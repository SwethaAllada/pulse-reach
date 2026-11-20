"use client";

import { useT } from "@/lib/i18n/use-locale";

export function SkipLink() {
  const t = useT();
  return (
    <a
      href="#main-content"
      className="sr-only rounded-md bg-accent px-3 py-2 text-sm font-medium text-on-accent focus:not-sr-only focus:absolute focus:start-3 focus:top-3 focus:z-[60]"
    >
      {t("app.skip_to_content")}
    </a>
  );
}
