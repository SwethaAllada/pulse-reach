import { intlLocale, type Locale } from "./config";
import { getLocale } from "./store";

/*
 * Locale-aware display formatting. Stored values are never changed: dates stay ISO strings in
 * state and API calls, numbers stay numbers; only their rendering differs per locale.
 * Clinical units and identifiers are formatted by their callers, never translated.
 */

export function formatNumber(value: number, options?: Intl.NumberFormatOptions, locale: Locale = getLocale()): string {
  return new Intl.NumberFormat(intlLocale(locale), options).format(value);
}

export function formatPercent(fraction: number, locale: Locale = getLocale()): string {
  return formatNumber(fraction, { style: "percent", maximumFractionDigits: 0 }, locale);
}

function toDate(value: string | Date): Date | null {
  // A bare ISO date (YYYY-MM-DD) is a calendar date: format it in UTC so it never shifts a day.
  const d = typeof value === "string" ? new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00Z` : value) : value;
  return Number.isNaN(d.getTime()) ? null : d;
}

/** `16 Nov 2026` / `16 نوفمبر 2026`. Invalid input is returned unchanged. */
export function formatDate(
  value: string | Date,
  options: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" },
  locale: Locale = getLocale()
): string {
  const d = toDate(value);
  if (!d) return String(value);
  // Arabic has no abbreviated month names; `short` already yields the full name.
  return new Intl.DateTimeFormat(intlLocale(locale), options).format(d);
}

export function formatDateTime(value: string | Date, locale: Locale = getLocale()): string {
  return formatDate(value, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }, locale);
}
