"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, EyeOff, Search } from "lucide-react";
import { api, apiErrorMessage } from "@/lib/api/client";
import type { CareGapOut, CareTeamMemberOut, MessageKey, TaskDetailOut, TaskPriority } from "@/lib/api/types";
import { MESSAGE_KEY_LABELS, PRIORITY_META, PRIORITY_ORDER, addDays, gapTypeText, roleText } from "@/lib/coordination/model";
import { useMutation } from "@/lib/coordination/use-coordination";
import { useAuth } from "@/lib/auth/auth-context";
import { Segmented } from "@/components/ui/segmented";
import { buttonClass } from "@/components/ui/button-styles";
import { FormError, inputClass, labelClass, textareaClass } from "./primitives";
import { ageLabel, sexLabel } from "@/lib/people/person";
import { regionLabel } from "@/lib/population/filters";
import { cn } from "@/lib/cn";
import { t as activeT } from "@/lib/i18n/translate";
import { useLocale } from "@/lib/i18n/use-locale";

interface PatientContext {
  patientId: string;
  summary: string;
  gaps: CareGapOut[];
  team: CareTeamMemberOut[];
  preferredLanguage: string | null;
}

function suggestedTemplate(gap: CareGapOut | undefined): MessageKey {
  if (!gap) return "general_check_in";
  if (gap.rule_id.startsWith("WCV")) return "well_child_visit";
  if (gap.gap_type === "partial_completion") return "complete_outstanding";
  if (gap.gap_type === "referral_not_initiated") return "referral_follow_up";
  return "screening_invitation";
}

/**
 * Creates a follow-up task (`POST /follow-up-tasks`). Care gaps and assignees come from the API for
 * the chosen person: only open gaps, and only colleagues the backend says may be assigned.
 */
export function CreateTaskForm({
  patientId: fixedPatient,
  gaps: knownGaps,
  defaultGapId,
  today,
  onCreated,
  onCancel,
}: {
  patientId?: string;
  /** The person's care gaps when already loaded (profile); otherwise fetched. */
  gaps?: CareGapOut[];
  defaultGapId?: string;
  today: string;
  onCreated: (task: TaskDetailOut) => void;
  onCancel: () => void;
}) {
  const { can } = useAuth();
  const { t, rich } = useLocale();
  const [query, setQuery] = useState(fixedPatient ?? "");
  const [ctx, setCtx] = useState<PatientContext | null>(null);
  const [lookup, setLookup] = useState<{ pending: boolean; error: string | null }>({ pending: false, error: null });
  const [gapId, setGapId] = useState(defaultGapId ?? "");
  const [assignee, setAssignee] = useState("");
  const [due, setDue] = useState(addDays(today, 14));
  const [priority, setPriority] = useState<TaskPriority>("routine");
  const [template, setTemplate] = useState<MessageKey | null>(null);
  const [visible, setVisible] = useState(true);
  const [language, setLanguage] = useState<"" | "en" | "ar">("");
  const [note, setNote] = useState("");
  const { run, pending, error } = useMutation();

  const load = async (pid: string) => {
    const id = pid.trim();
    if (!id) return;
    setLookup({ pending: true, error: null });
    try {
      const [patient, gaps, team] = await Promise.all([
        api.patient(id),
        knownGaps ? Promise.resolve(knownGaps) : api.patientEvaluations(id).then((e) => e.care_gaps),
        api.careTeam(id),
      ]);
      setCtx({
        patientId: patient.patient_id,
        // Built in an async callback: the active-locale translator applies (not the render hook).
        summary: [ageLabel(patient.date_of_birth, today, activeT), sexLabel(patient.sex, activeT), regionLabel(patient.region_id, activeT)].join(" · "),
        gaps: gaps.filter((g) => g.status === "open"), team, preferredLanguage: patient.preferred_language ?? null });
      const self = team.find((m) => m.is_self && m.can_be_assigned);
      setAssignee((a) => a || (self ? self.user_id : ""));
      setLookup({ pending: false, error: null });
    } catch (err) {
      setCtx(null);
      setLookup({ pending: false, error: apiErrorMessage(err, activeT("coord.person_not_loaded")) });
    }
  };

  useEffect(() => {
    // Deferred: the lookup updates state once the requests settle, not during the effect.
    if (fixedPatient) void Promise.resolve(fixedPatient).then(load);
    // Load once for a fixed person; manual lookups go through the button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixedPatient]);

  const gap = ctx?.gaps.find((g) => g.care_gap_id === gapId);
  const messageKey = template ?? suggestedTemplate(gap);
  const assignable = useMemo(() => ctx?.team.filter((m) => m.can_be_assigned) ?? [], [ctx]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ctx || (due && due < today)) return;
    const task = await run(() =>
      api.createTask({
        patient_id: ctx.patientId,
        care_gap_id: gapId || null,
        assigned_to_user_id: assignee || null,
        due_date: due || null,
        message_key: messageKey,
        priority,
        patient_visible: visible,
        staff_note: note.trim() || null,
        language: language || null,
      })
    );
    if (task) onCreated(task);
  };

  const dueError = due && due < today ? t("coord.form.past_due") : null;
  const assigneeName = assignable.find((m) => m.user_id === assignee)?.full_name ?? null;
  const canSubmit = !!ctx && !dueError && !pending && can("followups.create");

  return (
    <form onSubmit={submit} aria-label={t("coord.new_follow_up")} noValidate className="reveal flex flex-col rounded-xl border border-border bg-surface-raised">
      <header className="border-b border-border px-5 py-4">
        <h2 className="text-[15px] font-semibold text-foreground">{t("coord.new_follow_up")}</h2>
        <p className="mt-0.5 text-[13px] text-muted">{t("coord.form.subtitle")}</p>
      </header>

      <Section n={1} title={t("coord.form.section_context")} done={!!ctx}>
        <div className="flex flex-wrap items-end gap-3">
          <label className={`${labelClass} w-full sm:w-72`}>
            {t("coord.person_id_synthetic")}
            <input
              className={`${inputClass} font-mono`}
              value={query}
              readOnly={!!fixedPatient}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void load(query);
                }
              }}
              placeholder="SYNTH-PAT-000001"
              autoComplete="off"
              aria-invalid={!!lookup.error}
            />
          </label>
          {!fixedPatient && (
            <button type="button" className={buttonClass("secondary")} onClick={() => void load(query)} disabled={lookup.pending || !query.trim()}>
              <Search size={14} aria-hidden="true" /> {lookup.pending ? t("coord.form.looking_up") : t("coord.form.look_up")}
            </button>
          )}
        </div>
        <FormError message={lookup.error} />
        {ctx && (
          <div className="reveal-fade mt-1 grid gap-4 md:grid-cols-2">
            <div className="rounded-lg bg-surface-sunken px-3.5 py-3 text-sm">
              <p className="ltr-value font-mono text-foreground">{ctx.patientId}</p>
              <p className="text-xs text-muted">{ctx.summary}</p>
              <p className="mt-1 text-xs text-faint">
                {t(ctx.gaps.length === 1 ? "coord.form.ctx_counts_one" : "coord.form.ctx_counts_n", { gaps: String(ctx.gaps.length), members: String(ctx.team.length) })}
              </p>
            </div>
            <label className={labelClass}>
              {t("coord.form.gap_label")}
              <select className={inputClass} value={gapId} onChange={(e) => setGapId(e.target.value)}>
                <option value="">{t("coord.form.no_gap")}</option>
                {ctx.gaps.map((g) => (
                  <option key={g.care_gap_id} value={g.care_gap_id}>
                    {g.rule_id} · {gapTypeText(g.gap_type, t)}
                  </option>
                ))}
              </select>
              <span className="normal-case tracking-normal text-faint">
                {gap
                  ? t("coord.form.gap_hint", { type: gapTypeText(gap.gap_type, t), rule: gap.rule_id, date: gap.identified_date })
                  : ctx.gaps.length === 0
                    ? t("coord.form.no_open_gap")
                    : t("coord.form.only_open")}
              </span>
            </label>
          </div>
        )}
      </Section>

      {ctx && (
        <>
          <Section n={2} title={t("coord.form.section_assignment")} done={!!assignee}>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <label className={labelClass}>
                {t("coord.form.assigned_coordinator")}
                <select className={inputClass} value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                  <option value="">{t("coord.member.unassigned")}</option>
                  {assignable.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.is_self ? t("coord.member.you", { name: m.full_name }) : m.full_name} · {roleText(m.role, t)}
                    </option>
                  ))}
                </select>
                <span className="normal-case tracking-normal text-faint">{t("coord.form.assignee_hint")}</span>
              </label>
              <div className={labelClass}>
                <span>{t("coord.form.coordination_priority")}</span>
                <Segmented
                  label={t("coord.form.coordination_priority")}
                  options={[...PRIORITY_ORDER].reverse().map((p) => ({ value: p, label: t(PRIORITY_META[p].label) }))}
                  value={priority}
                  onChange={setPriority}
                  className="w-full"
                />
                <span className="normal-case tracking-normal text-faint">{t("coord.form.priority_hint")}</span>
              </div>
            </div>
          </Section>

          <Section n={3} title={t("coord.due_date")} done={!!due && !dueError}>
            <div className="flex flex-wrap items-end gap-3">
              <label className={`${labelClass} w-48`}>
                {t("coord.due_date")}
                <input type="date" className={inputClass} value={due} min={today} onChange={(e) => setDue(e.target.value)} aria-invalid={!!dueError} aria-describedby={dueError ? "due-error" : undefined} />
              </label>
              <div className="flex gap-1.5" role="group" aria-label={t("coord.form.due_shortcuts")}>
                {[7, 14, 30].map((d) => (
                  <button
                    key={d}
                    type="button"
                    aria-pressed={due === addDays(today, d)}
                    onClick={() => setDue(addDays(today, d))}
                    className={cn(
                      "h-9 rounded-full border px-3 text-xs transition-colors",
                      due === addDays(today, d) ? "border-accent bg-accent-soft font-medium text-foreground" : "border-border-strong text-muted hover:border-accent"
                    )}
                  >
                    {t("coord.form.in_days", { count: String(d) })}
                  </button>
                ))}
              </div>
            </div>
            {dueError && (
              <p id="due-error" role="alert" className="text-xs text-status-error">
                {dueError}
              </p>
            )}
          </Section>

          <Section n={4} title={t("coord.form.section_outreach")} done>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>
                  {t("coord.form.template")}
                  <select className={inputClass} value={messageKey} onChange={(e) => setTemplate(e.target.value as MessageKey)}>
                    {(Object.keys(MESSAGE_KEY_LABELS) as MessageKey[]).map((k) => (
                      <option key={k} value={k}>
                        {t(MESSAGE_KEY_LABELS[k])}
                      </option>
                    ))}
                  </select>
                </label>
                {!template && gap && <span className="text-xs text-faint">{t("coord.form.suggested")}</span>}
              </div>
              <label className={labelClass}>
                {t("coord.form.language")}
                <select className={inputClass} value={language} onChange={(e) => setLanguage(e.target.value as "" | "en" | "ar")}>
                  <option value="">
                    {t(!ctx.preferredLanguage ? "coord.form.lang_pref" : ctx.preferredLanguage === "ar" ? "coord.form.lang_pref_ar" : "coord.form.lang_pref_en")}
                  </option>
                  <option value="en">{t("coord.lang.en")}</option>
                  <option value="ar">{t("coord.lang.ar")}</option>
                </select>
              </label>
            </div>
            <label className="flex items-start gap-3 text-sm text-foreground">
              <input type="checkbox" className="mt-1 size-4 accent-[var(--accent)]" checked={visible} onChange={(e) => setVisible(e.target.checked)} />
              <span>
                {t("coord.form.show_portal")}
                <span className="block text-xs text-muted">{t("coord.form.show_portal_hint")}</span>
              </span>
            </label>
            <label className={labelClass}>
              <span className="flex items-center gap-1.5">
                <EyeOff size={12} aria-hidden="true" /> {t("coord.internal_note_staff")}
              </span>
              <textarea className={textareaClass} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} placeholder={t("coord.form.note_placeholder")} />
            </label>
          </Section>

          <div className="flex flex-col gap-3 border-t border-border bg-surface px-5 py-4">
            <p className="text-sm text-muted" aria-live="polite">
              <span className="font-medium text-foreground">{t("coord.form.review_label")}</span>{" "}
              {rich("coord.form.review", {
                template: t(MESSAGE_KEY_LABELS[messageKey]),
                patient: <span className="ltr-value font-mono text-foreground">{ctx.patientId}</span>,
                about: gap ? t("coord.form.review_about", { rule: gap.rule_id }) : "",
                assignment: assigneeName ? t("coord.form.review_assigned", { name: assigneeName }) : t("coord.form.review_unassigned"),
                priority: t("coord.form.review_priority", { priority: t(PRIORITY_META[priority].label).toLowerCase() }),
                due: due ? t("coord.form.review_due", { date: due }) : t("coord.form.review_no_due"),
                visibility: t(visible ? "coord.form.review_visible" : "coord.form.review_internal"),
              })}
            </p>
            <FormError message={error} />
            <div className="flex flex-wrap gap-2">
              <button type="submit" className={buttonClass("primary")} disabled={!canSubmit}>
                {pending ? t("coord.form.creating") : t("coord.form.create")}
              </button>
              <button type="button" className={buttonClass("secondary")} onClick={onCancel}>
                {t("coord.cancel")}
              </button>
            </div>
          </div>
        </>
      )}
      {!ctx && !lookup.pending && (
        <div className="flex px-5 pb-4">
          <button type="button" className={buttonClass("quiet")} onClick={onCancel}>
            {t("coord.cancel")}
          </button>
        </div>
      )}
    </form>
  );
}

function Section({ n, title, done, children }: { n: number; title: string; done: boolean; children: React.ReactNode }) {
  return (
    <fieldset className="reveal-fade flex flex-col gap-3 border-b border-border px-5 py-4 last:border-b-0">
      <legend className="sr-only">{title}</legend>
      <p aria-hidden="true" className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <span
          className={cn(
            "flex size-5 items-center justify-center rounded-full text-[11px] transition-colors duration-300",
            done ? "bg-accent text-on-accent" : "border border-border-strong text-muted"
          )}
        >
          {done ? <Check size={12} /> : n}
        </span>
        {title}
      </p>
      {children}
    </fieldset>
  );
}
