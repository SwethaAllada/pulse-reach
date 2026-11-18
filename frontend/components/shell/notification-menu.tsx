"use client";

import { Bell, Inbox } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/** Notifications entry point — placeholder until a notifications API exists. */
export function NotificationMenu() {
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
        aria-label="Notifications"
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex size-9 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-sunken hover:text-foreground"
      >
        <Bell size={18} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-80 rounded-md border border-border bg-surface-raised p-4 shadow-[var(--shadow-popover)]"
        >
          <p className="text-sm font-semibold text-foreground">Notifications</p>
          <div className="mt-3 flex flex-col items-center gap-2 rounded-md border border-dashed border-border-strong px-4 py-6 text-center">
            <Inbox size={20} className="text-faint" aria-hidden="true" />
            <p className="text-xs text-muted">
              Nothing here yet. Alerts for care gaps, follow-up activity and review requests will
              appear once the notifications service is connected.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
