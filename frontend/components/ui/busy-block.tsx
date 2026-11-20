"use client";

import type { MessageKey } from "@/lib/i18n/translate";
import { useT } from "@/lib/i18n/use-locale";

/** Route-level skeleton for server-component Suspense fallbacks (labelled by message key). */
export function BusyBlock({ labelKey, className }: { labelKey: MessageKey; className?: string }) {
  const t = useT();
  return <div aria-busy="true" aria-label={t(labelKey)} className={className} />;
}
