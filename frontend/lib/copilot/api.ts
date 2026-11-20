import { apiPost } from "@/lib/api/client";
import type { Direction, Locale } from "@/lib/i18n/config";

/*
 * Staff AI copilot (`POST /api/v1/ai/copilot/...`). Read-only: the copilot summarises existing
 * records and never sends, books, completes or changes anything.
 */

export type CopilotTask = "coordination_summary" | "clinical_review" | "population_briefing";
export type CopilotGenerationMode = "llm_grounded" | "deterministic_fallback";

export interface CopilotNextStep {
  code: string;
  label: string;
}

export interface CopilotAiMeta {
  generation_mode: string;
  prompt_version: string;
  provider: string | null;
  model: string | null;
  fallback_reason: string | null;
  violations: string[];
  audit_id: string;
}

export interface CopilotOut {
  task: CopilotTask;
  locale: Locale;
  direction: Direction;
  summary: string;
  points: string[];
  questions: string[];
  /** Deterministic, from existing workflows; shown as labels, never as actions. */
  suggested_next_steps: CopilotNextStep[];
  generation_mode: CopilotGenerationMode;
  /** False when AI is disabled, misconfigured or failed: the standard summary is shown. */
  ai_available: boolean;
  draft_notice: string;
  disclaimer: string;
  sources: string[];
  ai: CopilotAiMeta;
}

export interface CopilotIn {
  language?: Locale;
}

/** What to summarise: one patient's coordination or clinical review, or the caller's population. */
export type CopilotTarget =
  | { kind: "coordination"; patientId: string }
  | { kind: "clinical_review"; patientId: string }
  | { kind: "population" };

export function copilotPath(target: CopilotTarget): string {
  if (target.kind === "population") return "/ai/copilot/population";
  const segment = target.kind === "coordination" ? "coordination" : "clinical-review";
  return `/ai/copilot/patients/${encodeURIComponent(target.patientId)}/${segment}`;
}

/** True when the response is the deterministic standard summary rather than an AI-grounded draft. */
export function isFallback(out: CopilotOut): boolean {
  return !out.ai_available || out.generation_mode === "deterministic_fallback";
}

export const copilotApi = {
  generate: (target: CopilotTarget, language: Locale, signal?: AbortSignal) =>
    copilotApi.generateAt(copilotPath(target), language, signal),
  /** `path` from `copilotPath`. */
  generateAt: (path: string, language: Locale, signal?: AbortSignal) =>
    apiPost<CopilotOut>(path, { language } satisfies CopilotIn, signal),
};
