"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiErrorMessage } from "@/lib/api/client";
import type { Locale } from "@/lib/i18n/config";
import { copilotApi, copilotPath, type CopilotOut, type CopilotTarget } from "./api";

export type CopilotState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: CopilotOut }
  | { status: "error"; message: string; httpStatus: number | null };

/**
 * One copilot request at a time, started only by the user ("Generate summary"). Nothing is cached:
 * every generation is a fresh, audited backend call. A different target (another patient) starts idle.
 */
export function useCopilot(target: CopilotTarget) {
  const key = copilotPath(target);
  const [entry, setEntry] = useState<{ key: string; state: CopilotState }>({ key, state: { status: "idle" } });
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), [key]);

  const generate = useCallback(
    async (language: Locale) => {
      controller.current?.abort();
      const ac = new AbortController();
      controller.current = ac;
      setEntry({ key, state: { status: "loading" } });
      try {
        const data = await copilotApi.generateAt(key, language, ac.signal);
        if (!ac.signal.aborted) setEntry({ key, state: { status: "ready", data } });
      } catch (err) {
        if (ac.signal.aborted || (err as Error).name === "AbortError") return;
        setEntry({
          key,
          state: { status: "error", message: apiErrorMessage(err), httpStatus: err instanceof ApiError ? err.status : null },
        });
      }
    },
    [key]
  );

  const discard = useCallback(() => {
    controller.current?.abort();
    setEntry({ key, state: { status: "idle" } });
  }, [key]);

  const state: CopilotState = entry.key === key ? entry.state : { status: "idle" };
  return { state, generate, discard };
}
