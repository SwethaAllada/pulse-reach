"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "./use-theme";
import { useT } from "@/lib/i18n/use-locale";

export function ThemeToggle() {
  const { theme, mounted, toggleTheme } = useTheme();
  const t = useT();
  const label = mounted ? t(theme === "dark" ? "theme.to_light" : "theme.to_dark") : t("theme.toggle");

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={label}
      title={label}
      className="group flex size-9 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-sunken hover:text-foreground"
    >
      {/* Render the sun glyph until mounted to avoid a hydration-dependent icon flip. */}
      <span key={mounted ? theme : "ssr"} className="reveal-fade transition-transform duration-500 group-hover:rotate-[20deg]">
        {mounted && theme === "dark" ? <Moon size={18} /> : <Sun size={18} />}
      </span>
    </button>
  );
}
