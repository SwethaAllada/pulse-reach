"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, BookOpen, EyeOff, Flag, MonitorSmartphone, SearchX, UserRound } from "lucide-react";
import { api } from "@/lib/api/client";
import { useResource } from "@/lib/api/resource";
import type {
  CareGapDetailOut,
  CareTeamMemberOut,
  ContactChannel,
  ContactOutcome,
  RuleSummaryOut,
  TaskDetailOut,
  TaskPriority,
} from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";
import {
  APPOINTMENT_STATUS_META,
  APPOINTMENT_TYPE_LABELS,
  CONTACT_CHANNEL_LABELS,
  CONTACT_OUTCOME_META,
  MESSAGE_KEY_LABELS,
  PRIORITY_META,
  PRIORITY_ORDER,
  REFERRAL_STATUS_META,
  ROLE_LABELS,
  TASK_STATUS_META,
  TASK_TRANSITIONS,
  TERMINAL_TASK_STATUSES,
  actorLabel,
  dueText,
  eventTone,
  formatDate,
  formatDateTime,
  humanize,
  isoDate,
  memberName,
  taskEventText,
} from "@/lib/coordination/model";
import { useCareGap, useCareTeam, useMutation, useRulesIndex, useTask } from "@/lib/coordination/use-coordination";
import { ruleHref } from "@/lib/programmes/model";
import { PATHWAY_OPTIONS } from "@/lib/population/filters";
import { PageHeader } from "@/components/ui/page-header";
import { Plate, Footnote } from "@/components/ui/plate";
import { buttonClass } from "@/components/ui/button-styles";
import { Segmented } from "@/components/ui/segmented";
import { LoadingState } from "@/components/ui/loading-state";
import { BACK } from "@/components/ui/page-transition";
import { PermissionNotice } from "@/components/ui/permission-notice";
import { InlineError, ResourceView } from "@/components/programmes/resource-state";
import { OutreachPanel } from "./outreach-panel";
import { Confirmation, FormError, PriorityMark, StatusPill, ToneGlyph, VisibilityBadge, inputClass, labelClass, textareaClass } from "./primitives";
import { cn } from "@/lib/cn";

export function TaskDetailPage() {
  const params = useParams<{ taskId: string }>();
  return <TaskDetail taskId={decodeURIComponent(params.taskId ?? "")} />;
}

export function TaskDetail({ taskId }: { taskId: string }) {
  const [attempt, setAttempt] = useState(0);
  const task = useTask(taskId, attempt);
  const crumbs = [{ label: "Follow-up", href: "/follow-up" }, { label: taskId.slice(0, 8) }];
  const back = (
    <Link href="/follow-up" transitionTypes={BACK} className={buttonClass("secondary")}>
      <ArrowLeft size={14} aria-hidden="true" /> Back to Follow-up
    </Link>
  );
  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-24 pt-8 sm:px-6 lg:px-8">
      {task.status === "ready" ? (
        <TaskBody task={task.data} crumbs={crumbs} back={back} onRetry={() => setAttempt((n) => n + 1)} />
      ) : (
        <>
          <PageHeader eyebrow="Follow-up" title="Follow-up" breadcrumbs={crumbs} actions={back} className="mb-8" />
          {task.status === "loading" && <LoadingState rows={6} label="Loading follow-up" />}
          {task.status === "not_found" && (
            <div className="flex flex-col items-start gap-3 rounded-xl border border-border bg-surface p-8">
              <SearchX size={22} aria-hidden="true" className="text-faint" />
              <h2 className="text-lg font-semibold text-foreground">Follow-up not found</h2>
              <p className="text-sm text-muted">It does not exist or is outside your organization and patient scope.</p>
            </div>
          )}
          {task.status === "forbidden" && (
            <PermissionNotice title="Follow-ups are not available for your role" permission={task.permission} />
          )}
          {task.status === "error" && <InlineError message={`This follow-up is unavailable. ${task.message}`} onRetry={() => setAttempt((n) => n + 1)} />}
        </>
      )}
    </div>
  );
}

function TaskBody({ task, crumbs, back, onRetry }: { task: TaskDetailOut; crumbs: { label: string; href?: string }[]; back: React.ReactNode; onRetry: () => void }) {
  const { can } = useAuth();
  const team = useCareTeam(task.patient_id);
  const rules = useRulesIndex();
  const gap = useCareGap(task.care_gap_id, 0);
  const patient = useResource(can("patients.read", "patients.read_assigned") ? `patient|${task.patient_id}` : null, "patients.read_assigned", (s) =>
    api.patient(task.patient_id, s), 0
  );
  const teamMap = team.status === "ready" ? team.data : null;
  const rule = task.rule_id && rules.status === "ready" ? rules.data.get(task.rule_id) ?? null : null;
  const today = useMemo(() => isoDate(new Date()), []);
  const terminal = TERMINAL_TASK_STATUSES.includes(task.status);
  const meta = TASK_STATUS_META[task.status];
  const template = MESSAGE_KEY_LABELS[task.message_key as keyof typeof MESSAGE_KEY_LABELS] ?? humanize(task.message_key);
  const gapData = gap?.status === "ready" ? gap.data : null;
  const p = patient.status === "ready" ? patient.data : null;

  return (
    <>
      <PageHeader
        eyebrow={`Follow-up · ${rule ? PATHWAY_OPTIONS.find((o) => o.value === rule.pathway)!.short : "General"}`}
        title={template}
        subtitle={`For synthetic person ${task.patient_id}. ${meta.description}`}
        breadcrumbs={crumbs}
        actions={
          <>
            {back}
            {can("patients.read", "patients.read_assigned") && (
              <Link href={`/people/${encodeURIComponent(task.patient_id)}#coordination`} className={buttonClass("secondary")}>
                <UserRound size={14} aria-hidden="true" /> Patient profile
              </Link>
            )}
            {rule && (
              <Link href={ruleHref(rule.pathway, rule.rule_id)} className={buttonClass("secondary")}>
                <BookOpen size={14} aria-hidden="true" /> Rule {rule.rule_id}
              </Link>
            )}
          </>
        }
        className="mb-6"
      />

      <section aria-label="Follow-up status" className="reveal mb-10 grid grid-cols-2 gap-x-6 gap-y-5 rounded-2xl bg-ink p-6 text-ink-text sm:grid-cols-3 lg:grid-cols-6">
        <Fact label="Status">
          <StatusPill surface="ink" tone={meta.tone} label={meta.label} />
        </Fact>
        <Fact label="Priority">
          <PriorityMark surface="ink" priority={task.priority} />
        </Fact>
        <Fact label="Due">
          <span className={cn(task.is_overdue && "text-ink-due")}>{dueText(task.due_date, today, terminal)}</span>
          {task.due_date && <span className="block text-xs text-ink-faint">{formatDate(task.due_date)}</span>}
        </Fact>
        <Fact label="Assigned">{memberName(teamMap, task.assigned_to_user_id)}</Fact>
        <Fact label="Portal">
          {task.patient_visible ? (
            <span className="inline-flex items-center gap-1.5"><MonitorSmartphone size={13} aria-hidden="true" /> Visible to patient</span>
          ) : (
            <span className="inline-flex items-center gap-1.5"><EyeOff size={13} aria-hidden="true" /> Internal only</span>
          )}
        </Fact>
        <Fact label="Created">
          {formatDate(task.created_at)}
          <span className="block text-xs text-ink-faint">by {memberName(teamMap, task.created_by_user_id)}</span>
        </Fact>
      </section>

      {task.patient_reported_completion && !terminal && (
        <p role="status" className="reveal mb-8 flex items-start gap-2 rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted">
          <Flag size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-status-insufficient" />
          <span>
            <span className="font-medium text-foreground">The patient reports this is already done.</span> A report is not evidence. Verify it, then document
            the completion with its record to close the care gap.
          </span>
        </p>
      )}

      <div className="grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex flex-col gap-12">
          <Plate index="01" eyebrow="Next actions" title={terminal ? "This follow-up is closed" : "What can be done now"}>
            {terminal ? (
              <p className="text-sm text-muted">
                {task.status === "completed"
                  ? `Completed ${task.completed_at ? formatDateTime(task.completed_at) : ""}${task.completion_follow_up_id ? ` with documented completion ${task.completion_follow_up_id}` : ""}.`
                  : "Cancelled. The history below is kept."}
              </p>
            ) : (
              <NextActions task={task} team={teamMap} gap={gapData} today={today} />
            )}
          </Plate>

          {task.care_gap_id && gap && (
            <Plate index="02" eyebrow="Outreach" title="Draft and review outreach">
              <ResourceView resource={gap} what="Care-gap details" onRetry={onRetry}>
                {(g) => (
                  <OutreachPanel
                    patientId={task.patient_id}
                    gap={g}
                    team={teamMap}
                    preferredChannel={p?.preferred_channel ?? null}
                    preferredLanguage={p?.preferred_language ?? task.language}
                    open={!terminal && g.status === "open"}
                  />
                )}
              </ResourceView>
            </Plate>
          )}

          <Plate index={task.care_gap_id ? "03" : "02"} eyebrow="History" title="Activity timeline" description="Every change, oldest first. Internal entries are never shown in the patient portal.">
            <TaskTimeline task={task} team={teamMap} />
          </Plate>
        </div>

        <aside className="flex flex-col gap-10">
          <section aria-label="What the patient sees">
            <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-faint">What the patient sees</h3>
            {task.patient_visible ? (
              <div className="rounded-xl border border-border bg-surface p-4">
                <VisibilityBadge visibility="patient" />
                <p className="mt-3 text-sm leading-relaxed text-foreground" dir={task.language === "ar" ? "rtl" : "ltr"} lang={task.language}>
                  {task.patient_message}
                </p>
                <p className="mt-3 text-xs text-faint">
                  Approved template “{template}” in {task.language === "ar" ? "Arabic" : "English"}, shown in the portal only — never sent by SMS or e-mail.
                </p>
              </div>
            ) : (
              <p className="rounded-xl border border-dashed border-border-strong p-4 text-sm text-muted">Internal follow-up — nothing appears in the patient portal.</p>
            )}
            {task.staff_note && (
              <div className="mt-4 rounded-xl bg-surface-sunken p-4">
                <VisibilityBadge visibility="internal" />
                <p className="mt-2 whitespace-pre-wrap text-sm text-foreground">{task.staff_note}</p>
              </div>
            )}
          </section>

          <section aria-label="Care-gap evidence">
            <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-faint">Care-gap evidence</h3>
            {!task.care_gap_id ? (
              <p className="text-sm text-muted">Not linked to a care gap.</p>
            ) : (
              gap && (
                <ResourceView resource={gap} what="Care-gap details" onRetry={onRetry}>
                  {(g) => <GapEvidence gap={g} rule={rule} />}
                </ResourceView>
              )
            )}
          </section>
        </aside>
      </div>
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-ink-faint">{label}</p>
      <div className="mt-1.5 text-sm text-ink-text">{children}</div>
    </div>
  );
}

function GapEvidence({ gap, rule }: { gap: CareGapDetailOut; rule: RuleSummaryOut | null }) {
  const open = gap.status === "open";
  return (
    <div className="flex flex-col gap-4 text-sm">
      <dl className="grid grid-cols-2 gap-3">
        <div>
          <dt className="text-[11px] uppercase tracking-[0.08em] text-faint">Status</dt>
          <dd className="mt-1">
            <StatusPill tone={open ? "due" : gap.status === "closed_completed" ? "completed" : "not_eligible"} label={open ? "Open" : humanize(gap.status)} />
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-[0.08em] text-faint">Identified</dt>
          <dd className="mt-1 text-foreground">{formatDate(gap.identified_date)}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-[11px] uppercase tracking-[0.08em] text-faint">Rule</dt>
          <dd className="mt-1 text-foreground">
            <span className="font-mono text-xs">{gap.rule_id}</span> · {humanize(gap.gap_type)}
            <span className="mt-0.5 block text-xs text-muted">{rule?.description ?? gap.rule?.description}</span>
          </dd>
        </div>
        {gap.priority_score != null && (
          <div className="col-span-2">
            <dt className="text-[11px] uppercase tracking-[0.08em] text-faint">Engine priority score</dt>
            <dd className="mt-1 text-foreground">
              {gap.priority_score.toFixed(2)}
              {gap.priority_explanation && <span className="block text-xs text-muted">{gap.priority_explanation}</span>}
            </dd>
          </div>
        )}
      </dl>
      {gap.recommended_pathway && (
        <div className="rounded-xl border border-border p-3">
          <p className="text-[11px] uppercase tracking-[0.08em] text-faint">Documented next step</p>
          <p className="mt-1 text-foreground">{gap.recommended_pathway.description}</p>
          <p className="mt-1 text-xs text-faint">{gap.recommended_pathway.notice}</p>
        </div>
      )}
      <div>
        <p className="text-[11px] uppercase tracking-[0.08em] text-faint">Linked appointments</p>
        {gap.linked_appointments.length === 0 ? (
          <p className="mt-1 text-muted">None recorded.</p>
        ) : (
          <ul className="mt-1 flex flex-col gap-1">
            {gap.linked_appointments.map((a) => (
              <li key={a.appointment_id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-foreground">
                  {APPOINTMENT_TYPE_LABELS[a.appointment_type] ?? a.appointment_type} · {formatDateTime(a.scheduled_datetime)}
                </span>
                <StatusPill tone={APPOINTMENT_STATUS_META[a.status]?.tone ?? "eligible"} label={APPOINTMENT_STATUS_META[a.status]?.label ?? a.status} />
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <p className="text-[11px] uppercase tracking-[0.08em] text-faint">Linked referrals</p>
        {gap.linked_referrals.length === 0 ? (
          <p className="mt-1 text-muted">None recorded.</p>
        ) : (
          <ul className="mt-1 flex flex-col gap-1">
            {gap.linked_referrals.map((r) => (
              <li key={r.referral_id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-foreground">
                  {r.referral_target} <span className="font-mono text-xs text-muted">{r.referral_id}</span>
                </span>
                <StatusPill tone={REFERRAL_STATUS_META[r.status]?.tone ?? "eligible"} label={REFERRAL_STATUS_META[r.status]?.label ?? r.status} />
              </li>
            ))}
          </ul>
        )}
      </div>
      <Footnote className="mt-0">Appointments, referrals, patient replies and outreach approvals are not evidence of completion. Only a documented completion with its record closes the gap.</Footnote>
      {rule && (
        <Link href={`/people/${encodeURIComponent(gap.patient_id)}#care-gaps`} className={buttonClass("quiet", "self-start px-0")}>
          View the evidence trace in the profile
        </Link>
      )}
    </div>
  );
}

type ActionTab = "contact" | "update" | "note" | "message" | "escalate" | "complete";

function NextActions({ task, team, gap, today }: { task: TaskDetailOut; team: Map<string, CareTeamMemberOut> | null; gap: CareGapDetailOut | null; today: string }) {
  const { can } = useAuth();
  const canUpdate = can("followups.update");
  const tabs: { value: ActionTab; label: string }[] = canUpdate
    ? [
        { value: "contact", label: "Contact attempt" },
        { value: "update", label: "Status & assignment" },
        { value: "note", label: "Internal note" },
        ...(task.patient_visible ? [{ value: "message" as const, label: "Message patient" }] : []),
        { value: "escalate", label: "Escalate" },
        { value: "complete", label: "Complete" },
      ]
    : [];
  const [tab, setTab] = useState<ActionTab>("contact");
  if (!canUpdate)
    return (
      <PermissionNotice title="Updating follow-ups is not available for your role" permission="followups.update">
        You can read this follow-up and its history.
      </PermissionNotice>
    );
  return (
    <div className="flex flex-col gap-5">
      <div className="-mx-1 overflow-x-auto px-1 pb-1">
        <Segmented label="Follow-up action" options={tabs} value={tab} onChange={setTab} className="min-w-max" />
      </div>
      <div key={tab} className="reveal">
        {tab === "contact" && <ContactAttemptForm task={task} />}
        {tab === "update" && <UpdateForm task={task} team={team} today={today} />}
        {tab === "note" && <NoteForm task={task} visible={false} />}
        {tab === "message" && <NoteForm task={task} visible />}
        {tab === "escalate" && <EscalateForm task={task} />}
        {tab === "complete" && <CompleteForm task={task} gap={gap} />}
      </div>
    </div>
  );
}

function ContactAttemptForm({ task }: { task: TaskDetailOut }) {
  const [channel, setChannel] = useState<ContactChannel>("phone");
  const [outcome, setOutcome] = useState<ContactOutcome>("reached");
  const [note, setNote] = useState("");
  const [done, setDone] = useState(false);
  const { run, pending, error } = useMutation();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setDone(false);
    if (await run(() => api.recordContactAttempt(task.task_id, { channel, outcome, note: note.trim() || null }))) {
      setNote("");
      setDone(true);
    }
  };
  return (
    <form onSubmit={submit} aria-label="Record contact attempt" className="flex flex-col gap-4">
      <p className="text-sm text-muted">Document a contact you made outside PulseReach. It is internal, does not change the status and nothing is sent.</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className={labelClass}>
          Channel
          <select className={inputClass} value={channel} onChange={(e) => setChannel(e.target.value as ContactChannel)}>
            {(Object.keys(CONTACT_CHANNEL_LABELS) as ContactChannel[]).map((c) => (
              <option key={c} value={c}>
                {CONTACT_CHANNEL_LABELS[c]}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          Outcome
          <select className={inputClass} value={outcome} onChange={(e) => setOutcome(e.target.value as ContactOutcome)}>
            {(Object.keys(CONTACT_OUTCOME_META) as ContactOutcome[]).map((o) => (
              <option key={o} value={o}>
                {CONTACT_OUTCOME_META[o].label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className={labelClass}>
        <span className="flex items-center gap-1.5"><EyeOff size={12} aria-hidden="true" /> Note (internal)</span>
        <textarea className={textareaClass} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
      </label>
      <FormError message={error} />
      {done && <Confirmation>Contact attempt recorded in the history.</Confirmation>}
      <div>
        <button type="submit" className={buttonClass("primary")} disabled={pending}>
          {pending ? "Recording…" : "Record contact attempt"}
        </button>
      </div>
    </form>
  );
}

const TRANSITION_LABELS = { awaiting_patient: "Awaiting patient", in_progress: "Start working (in progress)", cancelled: "Cancel follow-up" } as const;

function UpdateForm({ task, team, today }: { task: TaskDetailOut; team: Map<string, CareTeamMemberOut> | null; today: string }) {
  const [assignee, setAssignee] = useState(task.assigned_to_user_id ?? "");
  const [due, setDue] = useState(task.due_date ?? "");
  const [priority, setPriority] = useState<TaskPriority>(task.priority);
  const [done, setDone] = useState<string | null>(null);
  const status = useMutation();
  const save = useMutation();
  const transitions = TASK_TRANSITIONS[task.status].filter((s) => s !== "awaiting_patient" || task.patient_visible);
  const assignable = [...(team?.values() ?? [])].filter((m) => m.can_be_assigned);
  const dirty = assignee !== (task.assigned_to_user_id ?? "") || due !== (task.due_date ?? "") || priority !== task.priority;

  const move = async (to: (typeof transitions)[number]) => {
    setDone(null);
    if (await status.run(() => api.updateTask(task.task_id, { status: to }))) setDone(`Status changed to ${TASK_STATUS_META[to].label}.`);
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setDone(null);
    const body = {
      ...(assignee && assignee !== task.assigned_to_user_id ? { assigned_to_user_id: assignee } : {}),
      ...(due !== (task.due_date ?? "") ? (due ? { due_date: due } : { clear_due_date: true }) : {}),
      ...(priority !== task.priority ? { priority } : {}),
    };
    if (await save.run(() => api.updateTask(task.task_id, body))) setDone("Changes saved.");
  };
  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.12em] text-faint">Move to</p>
        <div className="flex flex-wrap gap-2">
          {transitions.map((s) => (
            <button key={s} type="button" className={buttonClass(s === "cancelled" ? "quiet" : "secondary")} disabled={status.pending} onClick={() => move(s)}>
              {TRANSITION_LABELS[s]}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-faint">Completion has its own evidence-checked step.</p>
        <FormError message={status.error} />
      </div>
      <form onSubmit={submit} aria-label="Assignment, due date and priority" className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className={labelClass}>
            Assigned coordinator
            <select className={inputClass} value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              {!task.assigned_to_user_id && <option value="">Unassigned</option>}
              {task.assigned_to_user_id && !assignable.some((m) => m.user_id === task.assigned_to_user_id) && (
                <option value={task.assigned_to_user_id}>{memberName(team, task.assigned_to_user_id)}</option>
              )}
              {assignable.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.full_name}
                  {m.is_self ? " (you)" : ""} · {ROLE_LABELS[m.role] ?? m.role}
                </option>
              ))}
            </select>
          </label>
          <label className={labelClass}>
            Due date
            <input type="date" className={inputClass} value={due} min={today} onChange={(e) => setDue(e.target.value)} />
          </label>
          <label className={labelClass}>
            Priority
            <select className={inputClass} value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)}>
              {PRIORITY_ORDER.map((p) => (
                <option key={p} value={p}>
                  {PRIORITY_META[p].label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <FormError message={save.error} />
        <div>
          <button type="submit" className={buttonClass("primary")} disabled={save.pending || !dirty}>
            {save.pending ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
      {done && <Confirmation>{done}</Confirmation>}
    </div>
  );
}

function NoteForm({ task, visible }: { task: TaskDetailOut; visible: boolean }) {
  const [text, setText] = useState("");
  const [done, setDone] = useState(false);
  const { run, pending, error } = useMutation();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setDone(false);
    if (await run(() => api.addTaskNote(task.task_id, text.trim(), visible))) {
      setText("");
      setDone(true);
    }
  };
  return (
    <form onSubmit={submit} aria-label={visible ? "Message the patient" : "Add internal note"} className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        {visible
          ? "Shown to the patient in the portal history under this follow-up. It is not sent by SMS or e-mail."
          : "Staff only. Internal notes are never shown in the patient portal."}
      </p>
      <label className={labelClass}>
        <span className="flex items-center gap-1.5">
          {visible ? <MonitorSmartphone size={12} aria-hidden="true" /> : <EyeOff size={12} aria-hidden="true" />}
          {visible ? "Message (visible to the patient)" : "Internal note"}
        </span>
        <textarea className={textareaClass} value={text} maxLength={2000} required onChange={(e) => setText(e.target.value)} />
      </label>
      <FormError message={error} />
      {done && <Confirmation>{visible ? "Message added to the patient's portal history." : "Internal note added."}</Confirmation>}
      <div>
        <button type="submit" className={buttonClass("primary")} disabled={pending || !text.trim()}>
          {pending ? "Saving…" : visible ? "Post to patient portal" : "Add internal note"}
        </button>
      </div>
    </form>
  );
}

function EscalateForm({ task }: { task: TaskDetailOut }) {
  const [reason, setReason] = useState("");
  const { run, pending, error } = useMutation();
  const [done, setDone] = useState(false);
  return (
    <form
      aria-label="Escalate follow-up"
      className="flex flex-col gap-4"
      onSubmit={async (e) => {
        e.preventDefault();
        if (await run(() => api.escalateTask(task.task_id, reason.trim() || null))) setDone(true);
      }}
    >
      <p className="text-sm text-muted">
        {task.escalated_at ? `Escalated ${formatDateTime(task.escalated_at)}. ` : ""}Escalation is internal and flags the follow-up for attention.
      </p>
      <label className={labelClass}>
        Reason (internal)
        <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <FormError message={error} />
      {done && <Confirmation>Escalation recorded.</Confirmation>}
      <div>
        <button type="submit" className={buttonClass("primary")} disabled={pending}>
          Escalate
        </button>
      </div>
    </form>
  );
}

/**
 * Completion = documented evidence. With a care gap, a `completion_documented` follow-up citing the
 * completed record (screening / well-child visit / referral id) is recorded first — the backend
 * re-runs the rule and refuses mismatched evidence — and the task then cites it.
 */
function CompleteForm({ task, gap }: { task: TaskDetailOut; gap: CareGapDetailOut | null }) {
  const { can } = useAuth();
  const [evidence, setEvidence] = useState("");
  const [note, setNote] = useState("");
  const { run, pending, error } = useMutation();
  const documented = gap?.follow_up_events.filter((f) => f.event_type === "completion_documented") ?? [];

  if (!task.care_gap_id)
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted">This follow-up has no care gap, so completing it closes only the task.</p>
        <FormError message={error} />
        <div>
          <button type="button" className={buttonClass("primary")} disabled={pending} onClick={() => run(() => api.completeTask(task.task_id, null))}>
            Complete follow-up
          </button>
        </div>
      </div>
    );

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-muted">
        A follow-up with a care gap completes only with documented evidence: the completed screening, well-child visit or referral record. Appointments,
        referrals in progress, patient replies and outreach are not evidence.
      </p>
      {documented.length > 0 && (
        <div className="flex flex-col gap-2">
          {documented.map((f) => (
            <div key={f.follow_up_id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border p-3 text-sm">
              <span>
                Completion documented {formatDateTime(f.recorded_at)} · evidence <span className="font-mono">{f.evidence_reference}</span>
              </span>
              <button type="button" className={buttonClass("primary")} disabled={pending} onClick={() => run(() => api.completeTask(task.task_id, f.follow_up_id))}>
                Complete with this evidence
              </button>
            </div>
          ))}
        </div>
      )}
      {gap?.status === "open" &&
        (can("care_gaps.complete") ? (
          <form
            aria-label="Document completion"
            className="flex flex-col gap-4"
            onSubmit={async (e) => {
              e.preventDefault();
              // One write: if completing the task fails after the evidence is recorded, the error stays visible
              // and the documented completion is offered above for a retry.
              await run(async () => {
                const fu = await api.createCareGapFollowUp(task.care_gap_id!, {
                  event_type: "completion_documented",
                  close_gap: true,
                  documented_evidence: true,
                  evidence_reference: evidence.trim(),
                  note: note.trim() || null,
                });
                return api.completeTask(task.task_id, fu.follow_up_id);
              });
            }}
          >
            <label className={labelClass}>
              Evidence record ID
              <input className={`${inputClass} font-mono`} required value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="SYNTH-SCR-… / SYNTH-WCV-… / SYNTH-REF-…" />
              <span className="normal-case tracking-normal text-faint">The record must be completed, belong to this person and satisfy the gap’s rule.</span>
            </label>
            <label className={labelClass}>
              Note (internal)
              <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
            <div>
              <button type="submit" className={buttonClass("primary")} disabled={pending || !evidence.trim()}>
                {pending ? "Checking evidence…" : "Document completion and close"}
              </button>
            </div>
          </form>
        ) : (
          <PermissionNotice title="Documenting completion needs clinical completion rights" permission="care_gaps.complete">
            A clinician or care coordinator documents completion with its evidence; you can then complete this follow-up.
          </PermissionNotice>
        ))}
      {gap && gap.status !== "open" && documented.length === 0 && (
        <p className="text-sm text-muted">The care gap is {humanize(gap.status).toLowerCase()} without a documented completion; cancel the follow-up instead.</p>
      )}
      <FormError message={error} />
    </div>
  );
}

function TaskTimeline({ task, team }: { task: TaskDetailOut; team: Map<string, CareTeamMemberOut> | null }) {
  return (
    <ol className="relative flex flex-col gap-5 border-l border-border pl-5">
      {task.events.map((e, i) => (
        <li key={e.event_id} className="reveal relative" style={{ "--i": Math.min(i, 10) } as React.CSSProperties}>
          <span className="absolute -left-[27px] top-1 rounded-full bg-background p-0.5">
            <ToneGlyph tone={eventTone(e)} />
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-foreground">{taskEventText(e)}</span>
            <VisibilityBadge visibility={e.visibility} />
          </div>
          {e.message && (
            <p className={cn("mt-1 whitespace-pre-wrap text-sm", e.visibility === "internal" ? "text-muted" : "text-foreground")}>{e.message}</p>
          )}
          <p className="mt-1 text-xs text-faint">
            {actorLabel(team, e.actor_user_id, e.actor_role)} · {formatDateTime(e.created_at)}
          </p>
        </li>
      ))}
    </ol>
  );
}
