"use client";

import { useMemo, useSyncExternalStore } from "react";
import { directionOf, type Locale } from "./config";
import { formatDate, formatDateTime, formatNumber, formatPercent } from "./format";
import { getLocale, getServerLocale, subscribeLocale } from "./store";
import { translate, translatePlural, translateRich, type MessageKey, type Params, type PluralKey } from "./translate";

/**
 * The active locale plus bound translate/format helpers. Server render and hydration use the
 * default locale; the stored choice applies right after (the `<html dir>` is already correct).
 */
export function useLocale() {
  const locale = useSyncExternalStore<Locale>(subscribeLocale, getLocale, getServerLocale);
  return useMemo(
    () => ({
      locale,
      dir: directionOf(locale),
      t: (key: MessageKey, params?: Params) => translate(locale, key, params),
      tp: (key: PluralKey, count: number, params?: Params) => translatePlural(locale, key, count, params),
      rich: (key: MessageKey, nodes: Record<string, React.ReactNode>) => translateRich(locale, key, nodes),
      number: (value: number, options?: Intl.NumberFormatOptions) => formatNumber(value, options, locale),
      percent: (fraction: number) => formatPercent(fraction, locale),
      date: (value: string | Date, options?: Intl.DateTimeFormatOptions) => formatDate(value, options, locale),
      dateTime: (value: string | Date) => formatDateTime(value, locale),
    }),
    [locale]
  );
}

/** Shorthand when only `t` is needed. */
export function useT() {
  return useLocale().t;
}
