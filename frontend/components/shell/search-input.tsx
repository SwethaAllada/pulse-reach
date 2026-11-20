"use client";

import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/**
 * Global search entry point. Backend search isn't wired up yet, so submitting
 * shows an honest placeholder message instead of pretending to search.
 */
export function SearchInput() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [notice, setNotice] = useState(false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(false), 3200);
    return () => clearTimeout(timer);
  }, [notice]);

  return (
    <div className="relative min-w-0 flex-1 sm:max-w-md">
      <Search
        size={16}
        aria-hidden="true"
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
      />
      <input
        ref={inputRef}
        type="search"
        aria-label="Search people, rules and programmes"
        placeholder="Search people, rules, programmes…"
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            setNotice(true);
          }
        }}
        className="h-9 w-full rounded-full border border-transparent bg-surface-sunken pl-9 pr-14 text-sm text-foreground placeholder:text-faint transition-colors hover:border-border focus:border-accent focus:bg-surface-raised focus:outline-none"
      />
      <kbd
        aria-hidden="true"
        className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-faint sm:block"
      >
        ⌘K
      </kbd>
      {notice && (
        <p
          role="status"
          className="reveal absolute left-0 top-full z-50 mt-2 w-72 rounded-xl border border-border bg-surface-raised px-3 py-2 text-xs text-muted shadow-[var(--shadow-popover)]"
        >
          Search isn&apos;t connected yet — it will query people, rules and programmes once the
          search API lands.
        </p>
      )}
    </div>
  );
}
