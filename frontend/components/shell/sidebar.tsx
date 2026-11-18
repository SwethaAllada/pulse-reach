"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PanelLeftClose, PanelLeft, X } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";
import { cn } from "@/lib/cn";
import { NAV_ITEMS, isNavItemActive } from "./nav-items";
import { LogoMark, LogoWordmark } from "./logo";

const COLLAPSED_KEY = "pulereach-sidebar-collapsed";
const COLLAPSED_EVENT = "pulereach-sidebar-change";

function subscribeCollapsed(callback: () => void) {
  window.addEventListener(COLLAPSED_EVENT, callback);
  return () => window.removeEventListener(COLLAPSED_EVENT, callback);
}

function getCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "true";
  } catch {
    return false;
  }
}

interface SidebarProps {
  mobileOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ mobileOpen, onClose }: SidebarProps) {
  const pathname = usePathname();
  const collapsed = useSyncExternalStore(subscribeCollapsed, getCollapsed, () => false);

  // Close the mobile drawer whenever navigation completes.
  useEffect(() => {
    onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  const toggleCollapsed = () => {
    try {
      localStorage.setItem(COLLAPSED_KEY, String(!getCollapsed()));
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new Event(COLLAPSED_EVENT));
  };

  const nav = (
    <nav aria-label="Primary" className="flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-4">
      {NAV_ITEMS.map((item) => {
        const active = isNavItemActive(item, pathname);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors duration-150",
              active
                ? "bg-[var(--nav-active-bg)] text-accent"
                : "text-muted hover:bg-surface-sunken hover:text-foreground"
            )}
          >
            {active && (
              <span
                aria-hidden="true"
                className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-accent"
              />
            )}
            <Icon size={18} strokeWidth={1.75} className="shrink-0" aria-hidden="true" />
            <span
              className={cn(
                "flex min-w-0 flex-col transition-opacity duration-150",
                collapsed && "lg:sr-only lg:opacity-0"
              )}
            >
              <span className="truncate">{item.label}</span>
              {item.verb && (
                <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-faint">
                  {item.verb}
                </span>
              )}
            </span>
            {/* Tooltip — collapsed desktop only */}
            {collapsed && (
              <span
                role="tooltip"
                className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 hidden -translate-y-1/2 whitespace-nowrap rounded-md border border-border bg-surface-raised px-2.5 py-1.5 text-xs font-medium text-foreground opacity-0 shadow-[var(--shadow-popover)] transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100 lg:block"
              >
                {item.label}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <>
      {/* Mobile overlay */}
      <div
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-40 bg-black/50 transition-opacity duration-200 lg:hidden",
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0"
        )}
      />
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-border bg-surface transition-[width,transform] duration-200 ease-out",
          // Mobile drawer
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          // Desktop: sticky in-flow column, collapsible width
          "lg:sticky lg:top-0 lg:h-screen lg:translate-x-0",
          collapsed ? "lg:w-[72px]" : "lg:w-64"
        )}
      >
        <div className="flex h-16 items-center gap-3 border-b border-border px-4">
          <Link href="/" aria-label="PulseReach — Population overview" className="flex items-center gap-3">
            <LogoMark />
          </Link>
          <div className={cn("min-w-0 flex-1 transition-opacity", collapsed && "lg:sr-only lg:opacity-0")}>
            <LogoWordmark />
            <p className="truncate text-[10px] font-medium uppercase tracking-[0.08em] text-faint">
              Population observatory
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className="flex size-9 items-center justify-center rounded-md text-muted hover:bg-surface-sunken hover:text-foreground lg:hidden"
          >
            <X size={18} />
          </button>
        </div>

        {nav}

        <div className="border-t border-border p-3">
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-pressed={collapsed}
            className="hidden w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted transition-colors hover:bg-surface-sunken hover:text-foreground lg:flex"
          >
            {collapsed ? <PanelLeft size={18} /> : <PanelLeftClose size={18} />}
            <span className={cn(collapsed && "lg:sr-only")}>
              {collapsed ? "Expand" : "Collapse"}
            </span>
          </button>
        </div>
      </aside>
    </>
  );
}
