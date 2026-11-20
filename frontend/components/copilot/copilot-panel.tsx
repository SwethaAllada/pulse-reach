"use client";

import { useId, useState } from "react";
import { AlertTriangle, Bot, ClipboardCopy, FileText, PencilLine, RotateCcw, ShieldCheck, Sparkles, Trash2 } from "lucide-react";
import { isFallback, type CopilotOut, type CopilotTarget } from "@/lib/copilot/api";
import { useCopilot, type CopilotState } from "@/lib/copilot/use-copilot";
import { buttonClass } from "@/components/ui/button-styles";
import { LoadingState } from "@/components/ui/loading-state";
import { textareaClass } from "@/components/coordination/primitives";
import { cn } from "@/lib/cn";
import { useLocale } from "@/lib/i18n/use-locale";
import { translate, type MessageKey } from "@/lib/i18n/translate";

const META: Record<CopilotTarget["kind"], { title: MessageKey; desc: MessageKey }> = {
  coordination: { title: "copilot.coordination.title", desc: "copilot.coordination.desc" },
  clinical_review: { title: "copilot.clinical.title", desc: "copilot.clinical.desc" },
  population: { title: "copilot.population.title", desc: "copilot.population.desc" },
};

function errorTitle(status: number | null): MessageKey {
  if (status === 403) return "copilot.error.forbidden";
  if (status === 404) return "copilot.error.not_found";
  if (status === 429) return "copilot.error.rate_limited";
  return "copilot.error.other";
}

/** Plain-text draft in the draft's own language (what Copy copies and Edit starts from). */
export function draftText(d: CopilotOut): string {
  const h = (key: MessageKey) => translate(d.locale, key);
  const list = (items: string[]) => items.map((i) => `- ${i}`).join("\n");
  return [
    `${h("copilot.summary")}\n${d.summary}`,
    d.points.length > 0 && `${h("copilot.points")}\n${list(d.points)}`,
    d.questions.length > 0 && `${h("copilot.questions")}\n${list(d.questions)}`,
    d.suggested_next_steps.length > 0 && `${h("copilot.next_steps")}\n${list(d.suggested_next_steps.map((s) => s.label))}`,
    d.sources.length > 0 && `${h("copilot.sources")}\n${list(d.sources)}`,
  ]
    .filter(Boolean)
    .join("\n\n");
}

/**
 * Context panel for the staff AI copilot: the user asks for a summary, reviews the draft, and may
 * copy, edit (locally) or discard it. Read-only by design — no control here sends, books,
 * completes or changes anything; suggested next steps are labels, not actions.
 */
export function CopilotPanel({ target, level = 3, className }: { target: CopilotTarget; level?: 2 | 3; className?: string }) {
  const { t, locale } = useLocale();
  const { state, generate, discard } = useCopilot(target);
  const headingId = useId();
  const meta = META[target.kind];
  const Heading = level === 2 ? "h2" : "h3";
  const loading = state.status === "loading";

  return (
    <section
      aria-labelledby={headingId}
      data-copilot={target.kind}
      className={cn("reveal min-w-0 rounded-xl border border-border bg-surface-raised p-4 sm:p-5", className)}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-2xl">
          <p className="inline-flex items-center gap-1.5 text-xs font-medium text-warm-text">
            <Sparkles size={12} aria-hidden="true" /> {t("copilot.eyebrow")}
          </p>
          <Heading id={headingId} className="mt-1 text-base font-semibold text-foreground">
            {t(meta.title)}
          </Heading>
          <p className="mt-0.5 text-sm text-muted">{t(meta.desc)}</p>
        </div>
        <button type="button" className={buttonClass("secondary")} onClick={() => generate(locale)} disabled={loading}>
          <Bot size={15} aria-hidden="true" />
          {loading ? t("copilot.generating") : state.status === "ready" ? t("copilot.regenerate") : t("copilot.generate")}
        </button>
      </div>

      <div className="mt-4">
        <Body state={state} onRetry={() => generate(locale)} onDiscard={discard} />
      </div>

      <p className="mt-4 flex gap-2 border-t border-border pt-3 text-xs text-faint">
        <ShieldCheck size={14} aria-hidden="true" className="mt-px shrink-0" />
        {t("copilot.read_only")}
      </p>
    </section>
  );
}

function Body({ state, onRetry, onDiscard }: { state: CopilotState; onRetry: () => void; onDiscard: () => void }) {
  const { t } = useLocale();
  if (state.status === "idle") return <p className="text-sm text-muted">{t("copilot.idle")}</p>;
  if (state.status === "loading")
    return (
      <div className="flex flex-col gap-3">
        <LoadingState rows={4} label={t("copilot.loading_aria")} />
        <p role="status" className="text-xs text-faint">
          {t("copilot.generating")}
        </p>
      </div>
    );
  if (state.status === "error") {
    const retryable = state.httpStatus !== 403 && state.httpStatus !== 404;
    return (
      <div role="alert" className="reveal flex flex-col items-start gap-2 rounded-xl border border-border bg-surface px-4 py-3">
        <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <AlertTriangle size={15} aria-hidden="true" className="shrink-0 text-status-error" />
          {t(errorTitle(state.httpStatus))}
        </p>
        <p className="text-sm text-muted">{state.message}</p>
        {retryable && (
          <button type="button" className={buttonClass("secondary")} onClick={onRetry}>
            <RotateCcw size={14} aria-hidden="true" /> {t("access.retry")}
          </button>
        )}
      </div>
    );
  }
  return <Draft key={state.data.ai.audit_id} draft={state.data} onDiscard={onDiscard} />;
}

function Draft({ draft, onDiscard }: { draft: CopilotOut; onDiscard: () => void }) {
  const { t } = useLocale();
  const fallback = isFallback(draft);
  const [editing, setEditing] = useState(false);
  const [edited, setEdited] = useState<string | null>(null);
  const [copy, setCopy] = useState<"copied" | "failed" | null>(null);
  const text = edited ?? draftText(draft);
  const textDir = { dir: draft.direction, lang: draft.locale };

  const onCopy = async () => {
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(text);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  };

  return (
    <div className="reveal flex flex-col gap-4">
      {fallback ? (
        <div role="status" className="flex items-start gap-2 rounded-xl border border-dashed border-border-strong bg-surface-sunken px-3 py-2.5 text-sm">
          <FileText size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-faint" />
          <span>
            <span className="block font-medium text-foreground">{t("copilot.unavailable.title")}</span>
            <span className="text-muted">{t("copilot.unavailable.body")}</span>
          </span>
        </div>
      ) : (
        <p className="inline-flex w-fit max-w-full items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent">
          <Bot size={12} aria-hidden="true" className="shrink-0" />
          <span {...textDir}>{draft.draft_notice || t("copilot.draft_notice")}</span>
        </p>
      )}

      <article aria-label={t("copilot.draft_aria")} {...textDir} className="flex min-w-0 flex-col gap-4 break-words text-start">
        {editing ? (
          <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
            {t("copilot.edit_label")}
            <textarea {...textDir} className={cn(textareaClass, "min-h-56")} value={text} onChange={(e) => setEdited(e.target.value)} />
            <span className="font-normal text-faint">{t("copilot.edit_note")}</span>
          </label>
        ) : edited !== null ? (
          <div>
            <p className="mb-2 inline-flex rounded-full bg-surface-sunken px-2 py-0.5 text-[11px] font-medium text-muted">{t("copilot.edited")}</p>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{edited}</p>
          </div>
        ) : (
          <>
            <Block title={t("copilot.summary")}>
              <p className="text-sm leading-relaxed text-foreground">{draft.summary}</p>
            </Block>
            <Items title={t("copilot.points")} items={draft.points} />
            <Items title={t("copilot.questions")} items={draft.questions} />
            {draft.suggested_next_steps.length > 0 && (
              <Block title={t("copilot.next_steps")}>
                <ul className="flex flex-wrap gap-2">
                  {draft.suggested_next_steps.map((s) => (
                    <li key={s.code} data-step={s.code} className="rounded-full border border-border px-2.5 py-0.5 text-xs text-foreground">
                      {s.label}
                    </li>
                  ))}
                </ul>
                <p className="mt-1.5 text-xs text-faint">{t("copilot.next_steps_note")}</p>
              </Block>
            )}
            {draft.sources.length > 0 && (
              <Block title={t("copilot.sources")}>
                <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                  {draft.sources.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </Block>
            )}
          </>
        )}
        {draft.disclaimer && <p className="text-xs text-faint">{draft.disclaimer}</p>}
      </article>

      <div role="group" aria-label={t("copilot.actions_aria")} className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass("secondary")} onClick={onCopy}>
          <ClipboardCopy size={14} aria-hidden="true" /> {t("copilot.copy")}
        </button>
        <button type="button" className={buttonClass("secondary")} aria-pressed={editing} onClick={() => setEditing((e) => !e)}>
          <PencilLine size={14} aria-hidden="true" /> {editing ? t("copilot.done") : t("copilot.edit")}
        </button>
        <button type="button" className={buttonClass("quiet")} onClick={onDiscard}>
          <Trash2 size={14} aria-hidden="true" /> {t("copilot.discard")}
        </button>
      </div>
      {copy && (
        <p role="status" className="text-xs text-muted">
          {t(copy === "copied" ? "copilot.copied" : "copilot.copy_failed")}
        </p>
      )}

      <details className="text-xs text-muted">
        <summary className="cursor-pointer select-none text-faint">{t("copilot.technical")}</summary>
        <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
          <Tech label={t("copilot.tech.prompt")} value={draft.ai.prompt_version} />
          <Tech label={t("copilot.tech.provider")} value={draft.ai.provider} />
          <Tech label={t("copilot.tech.model")} value={draft.ai.model} />
          <Tech label={t("copilot.tech.audit")} value={draft.ai.audit_id} />
          {draft.ai.fallback_reason && <Tech label={t("copilot.tech.fallback")} value={draft.ai.fallback_reason} />}
          <Tech label={t("copilot.tech.violations")} value={draft.ai.violations.length > 0 ? draft.ai.violations.join(", ") : null} />
        </dl>
      </details>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="mb-1 text-xs font-medium text-faint">{title}</h4>
      {children}
    </div>
  );
}

function Items({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <Block title={title}>
      <ul className="flex list-disc flex-col gap-1 ps-5 text-sm leading-relaxed text-foreground">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </Block>
  );
}

function Tech({ label, value }: { label: string; value: string | null }) {
  const { t } = useLocale();
  return (
    <div className="flex min-w-0 flex-wrap gap-x-2">
      <dt className="text-faint">{label}</dt>
      <dd className="min-w-0 break-all">
        {value ? (
          <span dir="ltr" className="font-mono ltr-value">
            {value}
          </span>
        ) : (
          t("copilot.tech.none")
        )}
      </dd>
    </div>
  );
}
