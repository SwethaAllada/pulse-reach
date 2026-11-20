"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";
import type { Resource } from "@/lib/programmes/use-programmes-data";
import { PermissionNotice } from "@/components/ui/permission-notice";
import { LoadingState } from "@/components/ui/loading-state";
import { buttonClass } from "@/components/ui/button-styles";

/**
 * Renders `children(data)` when ready; otherwise the matching state. Loading keeps
 * the layout (skeleton), errors say what failed and never substitute values, and
 * 403s are explained as role limits rather than failures.
 */
export function ResourceView<T>({
  resource,
  what,
  onRetry,
  loading,
  children,
}: {
  resource: Resource<T>;
  /** e.g. "Care-gap records" */
  what: string;
  onRetry?: () => void;
  loading?: React.ReactNode;
  children: (data: T) => React.ReactNode;
}) {
  switch (resource.status) {
    case "ready":
      return <>{children(resource.data)}</>;
    case "loading":
      return <>{loading ?? <LoadingState rows={3} label={`Loading ${what.toLowerCase()}`} />}</>;
    case "forbidden":
      return (
        <PermissionNotice title={`${what} are not available for your role`} permission={resource.permission}>
          Nothing is shown in their place.
        </PermissionNotice>
      );
    case "error":
      return <InlineError message={`${what} are unavailable. ${resource.message}`} onRetry={onRetry} />;
  }
}

export function InlineError({ message, onRetry, tone = "paper" }: { message: string; onRetry?: () => void; tone?: "paper" | "plate" }) {
  const plate = tone === "plate";
  return (
    <div
      role="alert"
      className={
        plate
          ? "reveal flex flex-wrap items-center gap-3 rounded-xl border border-ink-line px-4 py-3 text-sm text-ink-muted"
          : "reveal flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted"
      }
    >
      <AlertTriangle size={16} aria-hidden="true" className={plate ? "shrink-0 text-ink-due" : "shrink-0 text-status-error"} />
      <span className="min-w-0 flex-1">{message} No values are shown in place of API data.</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className={buttonClass(plate ? "plate" : "secondary")}>
          <RotateCcw size={14} aria-hidden="true" /> Retry
        </button>
      )}
    </div>
  );
}
