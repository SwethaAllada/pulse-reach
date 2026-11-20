"use client";

import { useEffect, useState } from "react";
import { ApiError, isForbidden } from "./client";

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
 */
export function useResource<T>(
  key: string | null,
  permission: string,
  load: (signal: AbortSignal) => Promise<T>,
  attempt: number
): Resource<T> {
  const requestId = `${attempt}|${key}`;
  const [settled, setSettled] = useState<{ id: string; state: Resource<T> } | null>(null);
  useEffect(() => {
    if (key === null) return;
    const ctrl = new AbortController();
    load(ctrl.signal).then(
      (data) => !ctrl.signal.aborted && setSettled({ id: requestId, state: { status: "ready", data } }),
      (err) => {
        if (ctrl.signal.aborted) return;
        setSettled({
          id: requestId,
          state: isForbidden(err) ? { status: "forbidden", permission } : { status: "error", message: message(err, "Unexpected error.") },
        });
      }
    );
    return () => ctrl.abort();
    // `load` is derived from `key`; re-running on identity changes would refetch every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestId]);
  if (key === null) return { status: "forbidden", permission };
  return settled?.id === requestId ? settled.state : { status: "loading" };
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
