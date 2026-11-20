/**
 * Session-scoped request cache for reference data that does not change within an
 * evaluation run (rules, open questions, care-gap records). Failed requests are
 * evicted so a retry goes back to the API. Cleared on sign-in / sign-out so one
 * user's scoped data is never shown to another.
 */
const store = new Map<string, Promise<unknown>>();
const resetHooks = new Set<() => void>();

export function cached<T>(key: string, load: () => Promise<T>): Promise<T> {
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

/** Registers extra caches (e.g. per-hook module caches) to clear with this one. */
export function onCacheReset(hook: () => void): void {
  resetHooks.add(hook);
}

export function clearApiCache(): void {
  store.clear();
  resetHooks.forEach((h) => h());
}
