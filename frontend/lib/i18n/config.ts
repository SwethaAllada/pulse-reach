/**
 * English / Arabic UI localization (mirrors `backend/app/core/i18n.py`).
 *
 * - `en` (default, left-to-right) and `ar` (right-to-left) are the only locales; the two-letter
 *   codes are what the API exchanges (`preferred_language`, `Accept-Language`).
 * - Identifiers, enum values, clinical codes and rule ids are never translated; only their
 *   user-facing representation is.
 * - Arabic uses Western digits (0-9) and Gregorian month names, as the backend does.
 */
export const LOCALES = ["en", "ar"] as const;
export type Locale = (typeof LOCALES)[number];
export type Direction = "ltr" | "rtl";

export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_STORAGE_KEY = "pulsereach-locale";
/** Set when the browser's choice still has to be saved to the account (see `preference.ts`). */
export const LOCALE_UNSYNCED_KEY = "pulsereach-locale-unsynced";

export function isLocale(value: unknown): value is Locale {
  return value === "en" || value === "ar";
}

export function directionOf(locale: Locale): Direction {
  return locale === "ar" ? "rtl" : "ltr";
}

/** BCP 47 tag for `Intl`: Gulf Arabic conventions with Latin digits; British English (day month year). */
export function intlLocale(locale: Locale): string {
  return locale === "ar" ? "ar-AE-u-nu-latn" : "en-GB";
}
