import { DEFAULT_LOCALE, directionOf, isLocale, LOCALE_STORAGE_KEY, LOCALE_UNSYNCED_KEY, type Locale } from "./config";

/*
 * The active locale lives on `<html lang dir>` (set before first paint by `LocaleScript`) and in
 * localStorage. Changing it only re-renders subscribers: no navigation, no remount, so the current
 * workspace and any unsaved form input survive a language switch.
 */
const CHANGE_EVENT = "pulsereach-locale-change";

function readDocumentLocale(): Locale {
  if (typeof document === "undefined") return DEFAULT_LOCALE;
  const lang = document.documentElement.lang;
  return isLocale(lang) ? lang : DEFAULT_LOCALE;
}

/*
 * The rendering locale starts at the default on the client too, so hydration matches the server
 * render for hooks and helpers alike; `bootLocale()` (after mount) switches to the stored choice.
 */
let current: Locale = DEFAULT_LOCALE;

/** The active rendering locale, also for non-React helpers called during render. */
export function getLocale(): Locale {
  return current;
}

/** The locale requested from the API: the document's, which is right from the first paint. */
export function documentLocale(): Locale {
  return readDocumentLocale();
}

/** After hydration: adopt the language `LocaleScript` already put on `<html>`. */
export function bootLocale(): void {
  applyLocale(readDocumentLocale(), { persist: false });
}

export function getServerLocale(): Locale {
  return DEFAULT_LOCALE;
}

export function subscribeLocale(callback: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, callback);
  return () => window.removeEventListener(CHANGE_EVENT, callback);
}

/** The persisted browser choice, or null when the user never picked a language here. */
export function storedLocale(): Locale | null {
  try {
    const v = localStorage.getItem(LOCALE_STORAGE_KEY);
    return isLocale(v) ? v : null;
  } catch {
    return null;
  }
}

/** Applies `locale` to the document, persists it for this browser and notifies subscribers. */
export function applyLocale(locale: Locale, { persist = true }: { persist?: boolean } = {}): void {
  const root = document.documentElement;
  root.lang = locale;
  root.dir = directionOf(locale);
  if (persist) {
    try {
      localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    } catch {
      /* Private browsing etc. — the language still applies for this page. */
    }
  }
  if (current === locale) return;
  current = locale;
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Test helper: forget the module state and return the document to the default locale. */
export function resetLocaleForTests(): void {
  current = DEFAULT_LOCALE;
  try {
    localStorage.removeItem(LOCALE_STORAGE_KEY);
    localStorage.removeItem(LOCALE_UNSYNCED_KEY);
  } catch {
    /* ignore */
  }
  if (typeof document !== "undefined") {
    document.documentElement.lang = DEFAULT_LOCALE;
    document.documentElement.dir = "ltr";
  }
}
