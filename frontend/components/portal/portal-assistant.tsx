"use client";

import { useState } from "react";
import { AlertTriangle, Bot, FileText, LifeBuoy, Send, Sparkles, Stethoscope } from "lucide-react";
import { apiErrorMessage } from "@/lib/api/client";
import type { PatientAssistantOut, PortalAssistantOut } from "@/lib/api/portal-types";
import { useT } from "@/lib/i18n/use-locale";
import type { MessageKey } from "@/lib/i18n/translate";
import { buttonClass } from "@/components/ui/button-styles";
import { FormError } from "@/components/coordination/primitives";
import { cn } from "@/lib/cn";

type Answer = PatientAssistantOut | PortalAssistantOut;
type Turn = { question: string | null; data: Answer };

/**
 * Care-navigation assistant used per recommendation and portal-wide. Answers come from the
 * patient's own portal facts (a guarded AI answer when enabled, otherwise the standard answer);
 * free-text questions are screened by the backend first. It never changes, books or sends
 * anything; "Ask your care team" opens the existing help request form.
 */
export function AssistantPanel<T extends string>({
  title,
  description,
  topics,
  ask,
  renderHelp,
}: {
  title: string;
  description?: string;
  topics: { id: T; label: MessageKey }[];
  ask: (topic: T | "question", question?: string) => Promise<Answer>;
  renderHelp?: (initial: string, close: () => void) => React.ReactNode;
}) {
  const t = useT();
  const [topic, setTopic] = useState<T | "question" | null>(null);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<{ message: string; retry: () => void } | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [helping, setHelping] = useState(false);

  const run = async (next: T | "question", question?: string) => {
    setTopic(next);
    setPending(true);
    setError(null);
    try {
      const data = await ask(next, question);
      setTurns((prev) => [...prev.slice(-4), { question: question ?? null, data }]);
      if (question) setDraft("");
    } catch (err) {
      setError({ message: apiErrorMessage(err), retry: () => void run(next, question) });
    } finally {
      setPending(false);
    }
  };
  const last = turns.at(-1)?.data;

  return (
    <section aria-label={title} className="mt-5 rounded-xl border border-border bg-surface p-4">
      <h3 className="flex items-center gap-2 text-sm font-medium text-foreground">
        <Sparkles size={15} aria-hidden="true" className="text-accent" /> {title}
      </h3>
      {description && <p className="mt-1 text-xs text-muted">{description}</p>}
      <div role="group" aria-label={t("portal.assistant.choose")} className="mt-3 flex flex-wrap gap-2">
        {topics.map((x) => (
          <button key={x.id} type="button" aria-pressed={topic === x.id} disabled={pending} onClick={() => void run(x.id)}
            className={cn(buttonClass("secondary"), topic === x.id && "border-accent bg-accent-soft")}>
            {t(x.label)}
          </button>
        ))}
      </div>
      <form
        className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          const q = draft.trim();
          if (q.length >= 2) void run("question", q);
        }}
      >
        <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs text-muted">
          {t("portal.assistant.question_label")}
          <input dir="auto" value={draft} maxLength={500} onChange={(e) => setDraft(e.target.value)}
            placeholder={t("portal.assistant.question_placeholder")}
            className="h-10 rounded-lg border border-border bg-surface-raised px-3 text-sm text-foreground" />
        </label>
        <button type="submit" disabled={pending || draft.trim().length < 2} className={buttonClass("primary")}>
          <Send size={14} aria-hidden="true" /> {t("portal.assistant.ask")}
        </button>
      </form>
      <p className="mt-1 text-xs text-faint">{t("portal.assistant.question_hint")}</p>

      <div aria-live="polite" className="mt-3 flex flex-col gap-3">
        {turns.map((turn, i) => <AnswerView key={i} turn={turn} />)}
        {pending && <p className="skeleton h-16 rounded-lg" aria-label={t("portal.assistant.preparing")} />}
        {error && (
          <div className="flex flex-wrap items-center gap-3">
            <FormError message={error.message} />
            <button type="button" className={buttonClass("secondary")} onClick={error.retry}>
              {t("portal.assistant.retry")}
            </button>
          </div>
        )}
      </div>
      {last && renderHelp &&
        (helping ? (
          renderHelp(`${last.topic_label}: `, () => setHelping(false))
        ) : (
          <button type="button" className={buttonClass("primary", "mt-3")} onClick={() => setHelping(true)}>
            <LifeBuoy size={15} aria-hidden="true" /> {t("portal.assistant.ask_team")}
          </button>
        ))}
    </section>
  );
}

function AnswerView({ turn: { question, data: d } }: { turn: Turn }) {
  const t = useT();
  const kind = d.answer_kind ?? "answer";
  const ai = d.ai_generated ?? d.generation_mode === "llm_grounded";
  const urgent = kind === "emergency";
  return (
    <div dir={d.direction} lang={d.locale}
      className={cn("reveal-fade flex flex-col gap-2 rounded-lg p-3 text-sm",
        urgent ? "border border-danger bg-surface-raised" : "bg-surface-raised")}>
      {question && (
        <p className="text-xs text-muted">
          <span className="font-medium">{t("portal.assistant.you_asked")}:</span> <span dir="auto">{question}</span>
        </p>
      )}
      <h4 className="flex items-center gap-2 font-medium text-foreground">
        {urgent ? <AlertTriangle size={15} aria-hidden="true" className="text-danger" />
          : kind === "clinical_question" ? <Stethoscope size={15} aria-hidden="true" className="text-accent" /> : null}
        {urgent ? t("portal.assistant.emergency_title") : kind === "clinical_question" ? t("portal.assistant.clinical_title") : d.topic_label}
      </h4>
      {d.topic === "prepare_questions" ? (
        <ul className="list-disc space-y-1 ps-5 text-foreground">{d.answer.map((a, i) => <li key={i}>{a}</li>)}</ul>
      ) : (
        d.answer.map((a, i) => <p key={i} className="text-foreground">{a}</p>)
      )}
      {!urgent && <p className="rounded-lg bg-surface-sunken px-3 py-2 text-foreground">{d.escalation}</p>}
      <p className="flex items-center gap-1.5 text-xs text-faint">
        {ai ? <Bot size={12} aria-hidden="true" /> : <FileText size={12} aria-hidden="true" />}
        <span className="font-medium">{t(ai ? "portal.assistant.ai_badge" : "portal.assistant.standard_badge")}</span>
        <span>· {d.source_note}</span>
      </p>
    </div>
  );
}
