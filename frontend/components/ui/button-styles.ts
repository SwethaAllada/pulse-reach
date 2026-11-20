import { cn } from "@/lib/cn";

/**
 * One button vocabulary for links and buttons.
 *  primary   — the single human action on a view (coral on paper, lime at night)
 *  secondary — outlined, for navigation and alternatives
 *  quiet     — inline text action
 * Disabled states keep their shape and drop to 45% so the layout never jumps.
 */
export type ButtonVariant = "primary" | "secondary" | "quiet" | "plate" | "plate-primary";

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-full text-sm font-medium transition-[background-color,border-color,color,transform] duration-200 ease-out active:translate-y-px disabled:pointer-events-none disabled:opacity-45 aria-disabled:pointer-events-none aria-disabled:opacity-45";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "h-10 bg-action px-4 font-semibold text-on-action hover:bg-action-strong",
  secondary: "h-9 border border-border-strong px-3.5 text-foreground hover:border-foreground hover:bg-surface-raised",
  quiet: "h-8 px-2 text-accent underline-offset-4 hover:underline",
  plate: "h-9 border border-ink-line px-3.5 text-ink-text hover:border-ink-text",
  "plate-primary": "h-10 bg-ink-accent px-4 font-semibold text-ink-on-accent hover:brightness-105",
};

export function buttonClass(variant: ButtonVariant = "secondary", className?: string): string {
  return cn(BASE, VARIANTS[variant], className);
}
