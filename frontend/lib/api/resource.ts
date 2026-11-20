"use client";

import { useEffect, useState } from "react";
import { ApiError, isForbidden } from "./client";
import { useLocale } from "@/lib/i18n/use-locale";

/** A loaded resource; `forbidden` = the backend (or the role's permissions) refuse it. */
export type Resource<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "forbidden"; permission: string }
  | { status: "ready"; data: T };

function message(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/**
 * Runs `load` whenever `key` changes (null = disabled, reported as forbidden).
 * Stale responses are ignored; 403 becomes `forbidden`, never an error banner.
 *
 * A language switch reloads too (responses carry backend-localized labels), but keeps showing the
 * loaded data meanwhile, so forms, selections and expanded rows below survive the switch.
 */
export function useResource<T>(
  key: string | null,
  permission: string,
  load: (signal: AbortSignal) => Promise<T>,
  attempt: number,
  /** False for responses without backend-localized text (raw records localized at render). */
  localized = true
): Resource<T> {
  const { locale, t } = useLocale();
  const baseId = `${attempt}|${key}`;
  const requestId = localized ? `${baseId}|${locale}` : baseId;
  const [settled, setSettled] = useState<{ id: string; baseId: string; state: Resource<T> } | null>(null);
  useEffect(() => {
    if (key === null) return;
    const ctrl = new AbortController();
    load(ctrl.signal).then(
      (data) => !ctrl.signal.aborted && setSettled({ id: requestId, baseId, state: { status: "ready", data } }),
      (err) => {
        if (ctrl.signal.aborted) return;
        setSettled({
          id: requestId,
          baseId,
          state: isForbidden(err) ? { status: "forbidden", permission } : { status: "error", message: message(err, t("state.unexpected_error")) },
        });
      }
    );
    return () => ctrl.abort();
    // `load` is derived from `key`; re-running on identity changes would refetch every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestId]);
  if (key === null) return { status: "forbidden", permission };
  if (settled?.id === requestId) return settled.state;
  return settled?.baseId === baseId && settled.state.status === "ready" ? settled.state : { status: "loading" };
}

/**
 * Keeps showing the last ready value while a new key loads (filter changes), so a view does not
 * collapse to a skeleton on every refinement. Errors and 403s still replace it.
 */
export function useKeepPrevious<T>(resource: Resource<T>): Resource<T> {
  const [last, setLast] = useState<Resource<T> | null>(null);
  if (resource.status === "ready" && last !== resource) setLast(resource);
  return resource.status === "loading" && last ? last : resource;
}
