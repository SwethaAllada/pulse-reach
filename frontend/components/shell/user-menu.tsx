"use client";

import { CircleUser, LogOut, Settings, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/** Synthetic operator identity — auth isn't part of this milestone. */
export function UserMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="User menu"
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex size-9 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-sunken hover:text-foreground"
      >
        <CircleUser size={22} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-60 rounded-md border border-border bg-surface-raised py-1.5 shadow-[var(--shadow-popover)]"
        >
          <div className="border-b border-border px-4 py-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <UserRound size={15} aria-hidden="true" /> Demo Operator
            </p>
            <p className="mt-0.5 text-xs text-faint">synthetic session — no sign-in required</p>
          </div>
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm text-muted hover:bg-surface-sunken hover:text-foreground"
            onClick={() => setOpen(false)}
          >
            <Settings size={15} aria-hidden="true" /> Preferences
            <span className="ml-auto text-[10px] uppercase tracking-wide text-faint">soon</span>
          </button>
          <button
            type="button"
            role="menuitem"
            disabled
            className="flex w-full cursor-not-allowed items-center gap-2.5 px-4 py-2 text-left text-sm text-faint"
          >
            <LogOut size={15} aria-hidden="true" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
