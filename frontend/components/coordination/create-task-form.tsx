"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, EyeOff, Search } from "lucide-react";
import { api, apiErrorMessage } from "@/lib/api/client";
import type { CareGapOut, CareTeamMemberOut, MessageKey, TaskDetailOut, TaskPriority } from "@/lib/api/types";
import { MESSAGE_KEY_LABELS, PRIORITY_META, PRIORITY_ORDER, ROLE_LABELS, addDays, humanize } from "@/lib/coordination/model";
import { useMutation } from "@/lib/coordination/use-coordination";
import { useAuth } from "@/lib/auth/auth-context";
import { Segmented } from "@/components/ui/segmented";
import { buttonClass } from "@/components/ui/button-styles";
import { FormError, inputClass, labelClass, textareaClass } from "./primitives";
import { ageLabel, sexLabel } from "@/lib/people/person";
import { regionLabel } from "@/lib/population/filters";
import { cn } from "@/lib/cn";

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
        summary: [ageLabel(patient.date_of_birth, today), sexLabel(patient.sex), regionLabel(patient.region_id)].join(" · "),
        gaps: gaps.filter((g) => g.status === "open"), team, preferredLanguage: patient.preferred_language ?? null });
      const self = team.find((m) => m.is_self && m.can_be_assigned);
      setAssignee((a) => a || (self ? self.user_id : ""));
      setLookup({ pending: false, error: null });
    } catch (err) {
      setCtx(null);
      setLookup({ pending: false, error: apiErrorMessage(err, "This person could not be loaded.") });
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

  const dueError = due && due < today ? "The due date cannot be in the past." : null;
  const assigneeName = assignable.find((m) => m.user_id === assignee)?.full_name ?? "unassigned";
  const canSubmit = !!ctx && !dueError && !pending && can("followups.create");

  return (
    <form onSubmit={submit} aria-label="New follow-up" noValidate className="reveal flex flex-col rounded-xl border border-border bg-surface-raised">
      <header className="border-b border-border px-5 py-4">
        <h2 className="text-[15px] font-semibold text-foreground">New follow-up</h2>
        <p className="mt-0.5 text-[13px] text-muted">Who it is for, why it exists, who handles it and when it is due.</p>
      </header>

      <Section n={1} title="Patient and care context" done={!!ctx}>
        <div className="flex flex-wrap items-end gap-3">
          <label className={`${labelClass} w-full sm:w-72`}>
            Synthetic person ID
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
              <Search size={14} aria-hidden="true" /> {lookup.pending ? "Looking up…" : "Look up"}
            </button>
          )}
        </div>
        <FormError message={lookup.error} />
        {ctx && (
          <div className="reveal-fade mt-1 grid gap-4 md:grid-cols-2">
            <div className="rounded-lg bg-surface-sunken px-3.5 py-3 text-sm">
              <p className="font-mono text-foreground">{ctx.patientId}</p>
              <p className="text-xs text-muted">{ctx.summary}</p>
              <p className="mt-1 text-xs text-faint">
                {ctx.gaps.length} open documented {ctx.gaps.length === 1 ? "gap" : "gaps"} · {ctx.team.length} care-team members
              </p>
            </div>
            <label className={labelClass}>
              Care gap this follow-up is about
              <select className={inputClass} value={gapId} onChange={(e) => setGapId(e.target.value)}>
                <option value="">No care gap (general follow-up)</option>
                {ctx.gaps.map((g) => (
                  <option key={g.care_gap_id} value={g.care_gap_id}>
                    {g.rule_id} · {humanize(g.gap_type)}
                  </option>
                ))}
              </select>
              <span className="normal-case tracking-normal text-faint">
                {gap
                  ? `${humanize(gap.gap_type)} under ${gap.rule_id}, identified ${gap.identified_date}.`
                  : ctx.gaps.length === 0
                    ? "No open care gap is recorded for this person."
                    : "Only open, evidence-backed gaps are listed."}
              </span>
            </label>
          </div>
        )}
      </Section>

      {ctx && (
        <>
          <Section n={2} title="Assignment and priority" done={!!assignee}>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <label className={labelClass}>
                Assigned coordinator
                <select className={inputClass} value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                  <option value="">Unassigned</option>
                  {assignable.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.full_name}
                      {m.is_self ? " (you)" : ""} · {ROLE_LABELS[m.role] ?? m.role}
                    </option>
                  ))}
                </select>
                <span className="normal-case tracking-normal text-faint">Only care-team members with access to this person can be assigned.</span>
              </label>
              <div className={labelClass}>
                <span>Coordination priority</span>
                <Segmented
                  label="Coordination priority"
                  options={[...PRIORITY_ORDER].reverse().map((p) => ({ value: p, label: PRIORITY_META[p].label }))}
                  value={priority}
                  onChange={setPriority}
                  className="w-full"
                />
                <span className="normal-case tracking-normal text-faint">Operational urgency only — not a clinical risk score.</span>
              </div>
            </div>
          </Section>

          <Section n={3} title="Due date" done={!!due && !dueError}>
            <div className="flex flex-wrap items-end gap-3">
              <label className={`${labelClass} w-48`}>
                Due date
                <input type="date" className={inputClass} value={due} min={today} onChange={(e) => setDue(e.target.value)} aria-invalid={!!dueError} aria-describedby={dueError ? "due-error" : undefined} />
              </label>
              <div className="flex gap-1.5" role="group" aria-label="Due date shortcuts">
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
                    In {d} days
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

          <Section n={4} title="Patient outreach" done>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>
                  Approved message template
                  <select className={inputClass} value={messageKey} onChange={(e) => setTemplate(e.target.value as MessageKey)}>
                    {(Object.keys(MESSAGE_KEY_LABELS) as MessageKey[]).map((k) => (
                      <option key={k} value={k}>
                        {MESSAGE_KEY_LABELS[k]}
                      </option>
                    ))}
                  </select>
                </label>
                {!template && gap && <span className="text-xs text-faint">Suggested for this care gap.</span>}
              </div>
              <label className={labelClass}>
                Message language
                <select className={inputClass} value={language} onChange={(e) => setLanguage(e.target.value as "" | "en" | "ar")}>
                  <option value="">Patient preference{ctx.preferredLanguage ? ` (${ctx.preferredLanguage === "ar" ? "Arabic" : "English"})` : ""}</option>
                  <option value="en">English</option>
                  <option value="ar">Arabic</option>
                </select>
              </label>
            </div>
            <label className="flex items-start gap-3 text-sm text-foreground">
              <input type="checkbox" className="mt-1 size-4 accent-[var(--accent)]" checked={visible} onChange={(e) => setVisible(e.target.checked)} />
              <span>
                Show in the patient portal
                <span className="block text-xs text-muted">
                  The patient sees the approved template in their language and can reply. Nothing is sent by e-mail or SMS.
                </span>
              </span>
            </label>
            <label className={labelClass}>
              <span className="flex items-center gap-1.5">
                <EyeOff size={12} aria-hidden="true" /> Internal note (staff only)
              </span>
              <textarea className={textareaClass} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} placeholder="Never shown to the patient" />
            </label>
          </Section>

          <div className="flex flex-col gap-3 border-t border-border bg-surface px-5 py-4">
            <p className="text-sm text-muted" aria-live="polite">
              <span className="font-medium text-foreground">Review:</span> {MESSAGE_KEY_LABELS[messageKey]} for{" "}
              <span className="font-mono text-foreground">{ctx.patientId}</span>
              {gap ? ` about ${gap.rule_id}` : ""}, {assigneeName === "unassigned" ? "unassigned" : `assigned to ${assigneeName}`}, {PRIORITY_META[priority].label.toLowerCase()} priority
              {due ? `, due ${due}` : ", no due date"}
              {visible ? ", visible in the portal" : ", internal only"}.
            </p>
            <FormError message={error} />
            <div className="flex flex-wrap gap-2">
              <button type="submit" className={buttonClass("primary")} disabled={!canSubmit}>
                {pending ? "Creating…" : "Create follow-up"}
              </button>
              <button type="button" className={buttonClass("secondary")} onClick={onCancel}>
                Cancel
              </button>
            </div>
          </div>
        </>
      )}
      {!ctx && !lookup.pending && (
        <div className="flex px-5 pb-4">
          <button type="button" className={buttonClass("quiet")} onClick={onCancel}>
            Cancel
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
