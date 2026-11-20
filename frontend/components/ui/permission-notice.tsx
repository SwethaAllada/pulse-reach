import { LockKeyhole } from "lucide-react";
import { cn } from "@/lib/cn";

/**
 * Shown when the backend refused a request for this role (403) or the signed-in
 * role lacks the permission a view depends on. It explains; it does not enforce —
 * the backend is the only authority.
 */
export function PermissionNotice({
  title,
  children,
  permission,
  className,
  tone = "paper",
}: {
  title: string;
  children?: React.ReactNode;
  permission?: string;
  className?: string;
  tone?: "paper" | "plate";
}) {
  const plate = tone === "plate";
  return (
    <div
      role="status"
      className={cn(
        "reveal flex items-start gap-3 rounded-xl border px-4 py-3.5 text-sm",
        plate ? "border-ink-line text-ink-muted" : "border-border bg-surface-sunken/60 text-muted",
        className
      )}
    >
      <LockKeyhole size={16} aria-hidden="true" className={cn("mt-0.5 shrink-0", plate ? "text-ink-faint" : "text-faint")} />
      <div>
        <p className={cn("font-medium", plate ? "text-ink-text" : "text-foreground")}>{title}</p>
        {children && <div className="mt-0.5 leading-relaxed">{children}</div>}
        {permission && (
          <p className="mt-1 text-xs">
            Requires <code className="font-mono">{permission}</code>, enforced by the PulseReach API.
          </p>
        )}
      </div>
    </div>
  );
}
