"use client";

import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Search, X } from "lucide-react";
import { normalizeIdQuery } from "@/lib/people/params";
import { useT } from "@/lib/i18n/use-locale";

const DEBOUNCE_MS = 400;

interface Props {
  /** Normalised ID currently in the URL. */
  value: string | null;
  onSearch: (id: string | null) => void;
  busy: boolean;
}

/**
 * Exact synthetic-ID lookup (`GET /patients/{id}`). The API has no name or
 * partial-match search, so that is stated rather than simulated.
 */
export function PeopleIdSearch({ value, onSearch, busy }: Props) {
  const t = useT();
  const [text, setText] = useState(value ?? "");
  const [syncedValue, setSyncedValue] = useState(value);
  if (value !== syncedValue) {
    setSyncedValue(value);
    if (normalizeIdQuery(text) !== value) setText(value ?? "");
  }

  const normalized = normalizeIdQuery(text);
  const invalid = text.trim() !== "" && normalized === null;
  const onSearchRef = useRef(onSearch);
  useEffect(() => {
    onSearchRef.current = onSearch;
  });

  useEffect(() => {
    if (invalid || normalized === value) return;
    const timer = setTimeout(() => onSearchRef.current(normalized), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [normalized, invalid, value]);

  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor="people-id-search" className="text-xs font-medium text-faint">
        {t("people.search.label")}
      </label>
      <div className="relative w-full sm:max-w-sm">
        <Search size={16} aria-hidden="true" className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-faint" />
        <input
          id="people-id-search"
          type="search"
          dir="ltr"
          inputMode="text"
          autoComplete="off"
          spellCheck={false}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !invalid) onSearch(normalized);
          }}
          placeholder={t("people.search.placeholder")}
          aria-describedby="people-id-search-hint"
          aria-invalid={invalid || undefined}
          className="h-9 w-full rounded-md border border-border-strong bg-surface ps-9 pe-16 font-mono text-sm text-foreground placeholder:font-sans placeholder:text-faint transition-colors hover:border-faint focus:border-accent focus:outline-none [&::-webkit-search-cancel-button]:hidden"
        />
        <span className="absolute end-2 top-1/2 flex -translate-y-1/2 items-center gap-1">
          {busy && value && <LoaderCircle size={14} aria-hidden="true" className="animate-spin text-faint" />}
          {text && (
            <button
              type="button"
              onClick={() => {
                setText("");
                onSearch(null);
              }}
              aria-label={t("people.search.clear")}
              className="rounded p-1 text-faint transition-colors hover:text-foreground"
            >
              <X size={14} aria-hidden="true" />
            </button>
          )}
        </span>
      </div>
      <p id="people-id-search-hint" className={invalid ? "text-xs text-status-error" : "text-xs text-faint"} aria-live="polite">
        {t(invalid ? "people.search.invalid" : "people.search.hint")}
      </p>
    </div>
  );
}
