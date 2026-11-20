"use client";

import { Menu } from "lucide-react";
import { SearchInput } from "./search-input";
import { NotificationMenu } from "./notification-menu";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { UserMenu } from "./user-menu";
import { useT } from "@/lib/i18n/use-locale";

interface TopNavigationProps {
  onMenuClick: () => void;
}

export function TopNavigation({ onMenuClick }: TopNavigationProps) {
  const t = useT();
  return (
    <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center gap-3 border-b border-border bg-[color-mix(in_srgb,var(--bg)_82%,transparent)] px-4 backdrop-blur-md sm:px-6">
      <button
        type="button"
        onClick={onMenuClick}
        aria-label={t("shell.open_navigation")}
        className="flex size-9 items-center justify-center rounded-full text-muted hover:bg-surface-sunken hover:text-foreground lg:hidden"
      >
        <Menu size={20} />
      </button>
      <SearchInput />
      <div className="ms-auto flex items-center gap-1">
        <NotificationMenu />
        <ThemeToggle />
        <UserMenu />
      </div>
    </header>
  );
}
