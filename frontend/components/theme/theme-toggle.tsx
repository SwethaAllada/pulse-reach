"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "./use-theme";

export function ThemeToggle() {
  const { theme, mounted, toggleTheme } = useTheme();

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={
        mounted ? `Switch to ${theme === "dark" ? "light" : "dark"} theme` : "Toggle theme"
      }
      title={mounted ? `Switch to ${theme === "dark" ? "light" : "dark"} theme` : "Toggle theme"}
      className="flex size-9 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-sunken hover:text-foreground"
    >
      {/* Render the sun glyph until mounted to avoid a hydration-dependent icon flip. */}
      {mounted && theme === "dark" ? <Moon size={18} /> : <Sun size={18} />}
    </button>
  );
}
