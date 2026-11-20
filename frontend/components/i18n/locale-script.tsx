import { LOCALE_STORAGE_KEY } from "@/lib/i18n/config";

/**
 * Runs before paint so `<html lang dir>` match the persisted language on first render (no
 * left-to-right flash for Arabic). Without a stored choice the default (English) applies.
 */
const localeInitScript = `(function(){try{var l=localStorage.getItem("${LOCALE_STORAGE_KEY}");if(l==="ar"||l==="en"){document.documentElement.lang=l;document.documentElement.dir=l==="ar"?"rtl":"ltr";}}catch(e){}})();`;

export function LocaleScript() {
  return <script dangerouslySetInnerHTML={{ __html: localeInitScript }} />;
}
