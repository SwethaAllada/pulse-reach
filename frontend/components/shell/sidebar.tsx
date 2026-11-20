"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PanelLeftClose, PanelLeft, X } from "lucide-react";
import { Suspense, useEffect, useSyncExternalStore } from "react";
import { cn } from "@/lib/cn";
import { useAuth } from "@/lib/auth/auth-context";
import { useLocale } from "@/lib/i18n/use-locale";
import { NAV_GROUPS, isNavItemActive, navItemsFor, navLabel } from "./nav-items";
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

/** Reads the pathname inside a Suspense boundary so dynamic routes can prerender their shell. */
function RoutedNav({ collapsed, onClose }: { collapsed: boolean; onClose: () => void }) {
  const pathname = usePathname();

  // Close the mobile drawer whenever navigation completes.
  useEffect(() => {
    onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  return <NavLinks pathname={pathname} collapsed={collapsed} />;
}

export function Sidebar({ mobileOpen, onClose }: SidebarProps) {
  const { t } = useLocale();
  const collapsed = useSyncExternalStore(subscribeCollapsed, getCollapsed, () => false);

  const toggleCollapsed = () => {
    try {
      localStorage.setItem(COLLAPSED_KEY, String(!getCollapsed()));
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new Event(COLLAPSED_EVENT));
  };

  const nav = (
    <Suspense fallback={<NavLinks pathname={null} collapsed={collapsed} />}>
      <RoutedNav collapsed={collapsed} onClose={onClose} />
    </Suspense>
  );

  return (
    <>
      {/* Mobile overlay */}
      <div
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-40 bg-[color-mix(in_srgb,var(--ink)_55%,transparent)] backdrop-blur-[2px] transition-opacity duration-300 lg:hidden",
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0"
        )}
      />
      <aside
        className={cn(
          "fixed inset-y-0 start-0 z-50 flex w-72 flex-col border-e border-border bg-background-elevated transition-[width,transform] duration-300 ease-[var(--ease-out)]",
          // Mobile drawer
          mobileOpen ? "translate-x-0 shadow-[var(--shadow-popover)]" : "-translate-x-full rtl:translate-x-full",
          // Desktop: sticky in-flow column, collapsible width
          "lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 lg:shadow-none rtl:lg:translate-x-0",
          collapsed ? "lg:w-[76px]" : "lg:w-64"
        )}
      >
        <div className="flex h-16 items-center gap-3 px-4">
          <Link href="/" aria-label={t("app.home_link")} className="flex items-center gap-3 rounded-md">
            <LogoMark />
          </Link>
          <div className={cn("min-w-0 flex-1 transition-opacity duration-200", collapsed && "lg:sr-only lg:opacity-0")}>
            <LogoWordmark />
            <p className="truncate text-[11px] text-faint">{t("app.tagline")}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("shell.close_navigation")}
            className="flex size-9 items-center justify-center rounded-full text-muted hover:bg-surface-sunken hover:text-foreground lg:hidden"
          >
            <X size={18} />
          </button>
        </div>

        {nav}

        <div className="p-3">
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-label={t(collapsed ? "shell.expand_sidebar" : "shell.collapse_sidebar")}
            aria-pressed={collapsed}
            className="hidden w-full items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-faint transition-colors hover:bg-surface-sunken hover:text-foreground lg:flex"
          >
            {collapsed ? (
              <PanelLeft size={17} className="mx-auto rtl:-scale-x-100" />
            ) : (
              <PanelLeftClose size={17} className="rtl:-scale-x-100" />
            )}
            <span className={cn(collapsed && "lg:sr-only")}>{t(collapsed ? "shell.expand" : "shell.collapse")}</span>
          </button>
        </div>
      </aside>
    </>
  );
}

function NavLinks({ pathname, collapsed }: { pathname: string | null; collapsed: boolean }) {
  const { can, role } = useAuth();
  const { t } = useLocale();
  const items = navItemsFor(role, can);
  return (
    <nav aria-label={t("shell.primary_navigation")} className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-4">
      {NAV_GROUPS.map((group) => {
        const groupItems = items.filter((i) => i.group === group.id);
        if (groupItems.length === 0) return null;
        return (
          <div key={group.id}>
            <p
              className={cn(
                "mb-2 px-3 text-xs font-medium text-faint",
                collapsed && "lg:sr-only"
              )}
            >
              {t(group.label)}
            </p>
            <ul className="flex flex-col gap-0.5">
              {groupItems.map((item) => {
                const active = pathname !== null && isNavItemActive(item, pathname);
                const Icon = item.icon;
                return (
                  <li key={`${item.group}|${item.href}`}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "group relative flex h-9 items-center gap-3 rounded-lg px-3 text-sm transition-[background-color,color] duration-200",
                        active
                          ? "bg-nav-active-bg font-semibold text-foreground"
                          : "font-medium text-muted hover:bg-surface-sunken hover:text-foreground"
                      )}
                    >
                      <span
                        aria-hidden="true"
                        className={cn(
                          "absolute start-0 top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-full bg-accent transition-transform duration-300 ease-[var(--ease-out)]",
                          active ? "scale-y-100" : "scale-y-0"
                        )}
                      />
                      <Icon
                        size={18}
                        strokeWidth={active ? 2 : 1.6}
                        className={cn("shrink-0", active && "text-accent")}
                        aria-hidden="true"
                      />
                      <span className={cn("min-w-0 flex-1 truncate", collapsed && "lg:sr-only")}>{navLabel(item, role, t)}</span>
                      {/* Tooltip — collapsed desktop only */}
                      {collapsed && (
                        <span
                          role="tooltip"
                          className="pointer-events-none absolute start-full top-1/2 z-50 ms-3 hidden -translate-y-1/2 whitespace-nowrap rounded-md border border-border bg-surface-raised px-2.5 py-1.5 text-xs font-medium text-foreground opacity-0 shadow-[var(--shadow-popover)] transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100 lg:block"
                        >
                          {navLabel(item, role, t)}
                        </span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}
