/**
 * Session-scoped request cache for reference data that does not change within an
 * evaluation run (rules, open questions, care-gap records). Failed requests are
 * evicted so a retry goes back to the API. Cleared on sign-in / sign-out so one
 * user's scoped data is never shown to another.
 */
import { documentLocale } from "@/lib/i18n/store";

/* Entries are per UI language: responses carry backend-localized labels and messages. */
const store = new Map<string, Promise<unknown>>();
const scoped = (key: string) => `${documentLocale()}|${key}`;
const resetHooks = new Set<() => void>();

export function cached<T>(name: string, load: () => Promise<T>): Promise<T> {
  const key = scoped(name);
  let p = store.get(key) as Promise<T> | undefined;
  if (!p) {
    p = load();
    store.set(key, p);
    p.catch(() => {
      if (store.get(key) === p) store.delete(key);
    });
  }
  return p;
}

/** Drops cached entries a write may have changed; the next read goes back to the API. */
export function evict(...keys: string[]): void {
  for (const k of [...store.keys()]) if (keys.includes(k.slice(k.indexOf("|") + 1))) store.delete(k);
}

/** Registers extra caches (e.g. per-hook module caches) to clear with this one. */
export function onCacheReset(hook: () => void): void {
  resetHooks.add(hook);
}

export function clearApiCache(): void {
  store.clear();
  resetHooks.forEach((h) => h());
}
