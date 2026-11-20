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
  CONTACT_CHANNEL_LABELS,
  CONTACT_OUTCOME_META,
  PRIORITY_META,
  PRIORITY_ORDER,
  REFERRAL_STATUS_META,
  TASK_STATUS_META,
  TASK_TRANSITIONS,
  TERMINAL_TASK_STATUSES,
  actorLabel,
  appointmentTypeText,
  dueText,
  eventTone,
  formatDate,
  formatDateTime,
  gapStatusText,
  gapTypeText,
  isoDate,
  memberName,
  roleText,
  taskEventText,
  templateText,
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
import { useLocale } from "@/lib/i18n/use-locale";
import type { MessageKey } from "@/lib/i18n/translate";

export function TaskDetailPage() {
  const params = useParams<{ taskId: string }>();
  return <TaskDetail taskId={decodeURIComponent(params.taskId ?? "")} />;
}

export function TaskDetail({ taskId }: { taskId: string }) {
  const [attempt, setAttempt] = useState(0);
  const { t } = useLocale();
  const task = useTask(taskId, attempt);
  const crumbs = [{ label: t("nav.follow_up"), href: "/follow-up" }, { label: taskId.slice(0, 8) }];
  const back = (
    <Link href="/follow-up" transitionTypes={BACK} className={buttonClass("secondary")}>
      <ArrowLeft size={14} aria-hidden="true" className="rtl:-scale-x-100" /> {t("coord.task.back")}
    </Link>
  );
  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      {task.status === "ready" ? (
        <TaskBody task={task.data} crumbs={crumbs} back={back} onRetry={() => setAttempt((n) => n + 1)} />
      ) : (
        <>
          <PageHeader eyebrow={t("nav.follow_up")} title={t("nav.follow_up")} breadcrumbs={crumbs} actions={back} className="mb-8" />
          {task.status === "loading" && <LoadingState rows={6} label={t("coord.task.loading")} />}
          {task.status === "not_found" && (
            <div className="flex flex-col items-start gap-3 rounded-xl border border-border bg-surface p-8">
              <SearchX size={22} aria-hidden="true" className="text-faint" />
              <h2 className="text-lg font-semibold text-foreground">{t("coord.task.not_found")}</h2>
              <p className="text-sm text-muted">{t("coord.task.not_found_desc")}</p>
            </div>
          )}
          {task.status === "forbidden" && (
            <PermissionNotice title={t("coord.task.forbidden")} permission={task.permission} />
          )}
          {task.status === "error" && <InlineError message={t("coord.task.unavailable", { message: task.message })} onRetry={() => setAttempt((n) => n + 1)} />}
        </>
      )}
    </div>
  );
}

function TaskBody({ task, crumbs, back, onRetry }: { task: TaskDetailOut; crumbs: { label: string; href?: string }[]; back: React.ReactNode; onRetry: () => void }) {
  const { can } = useAuth();
  const { t, rich, locale } = useLocale();
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
  const template = templateText(task.message_key, t);
  const gapData = gap?.status === "ready" ? gap.data : null;
  const p = patient.status === "ready" ? patient.data : null;

  return (
    <>
      <PageHeader
        eyebrow={t("coord.task.eyebrow", { programme: rule ? t(PATHWAY_OPTIONS.find((o) => o.value === rule.pathway)!.short) : t("coord.task.general") })}
        title={template}
        subtitle={t("coord.task.subtitle", { id: task.patient_id, description: t(meta.description) })}
        breadcrumbs={crumbs}
        actions={
          <>
            {back}
            {can("patients.read", "patients.read_assigned") && (
              <Link href={`/people/${encodeURIComponent(task.patient_id)}#coordination`} className={buttonClass("secondary")}>
                <UserRound size={14} aria-hidden="true" /> {t("coord.patient_profile")}
              </Link>
            )}
            {rule && (
              <Link href={ruleHref(rule.pathway, rule.rule_id)} className={buttonClass("secondary")}>
                <BookOpen size={14} aria-hidden="true" /> {t("coord.task.rule", { id: rule.rule_id })}
              </Link>
            )}
          </>
        }
        className="mb-6"
      />

      <section aria-label={t("coord.task.status_aria")} className="reveal mb-10 grid grid-cols-2 gap-x-6 gap-y-5 rounded-xl border border-border bg-surface-raised p-6 text-ink-text sm:grid-cols-3 lg:grid-cols-6">
        <Fact label={t("coord.status")}>
          <StatusPill surface="ink" tone={meta.tone} label={t(meta.label)} />
        </Fact>
        <Fact label={t("coord.priority")}>
          <PriorityMark surface="ink" priority={task.priority} />
        </Fact>
        <Fact label={t("coord.task.fact_due")}>
          <span className={cn(task.is_overdue && "text-ink-due")}>{dueText(task.due_date, today, terminal, t, locale)}</span>
          {task.due_date && <span className="block text-xs text-ink-faint">{formatDate(task.due_date, locale)}</span>}
        </Fact>
        <Fact label={t("coord.task.fact_assigned")}>{memberName(teamMap, task.assigned_to_user_id, t)}</Fact>
        <Fact label={t("coord.task.fact_portal")}>
          {task.patient_visible ? (
            <span className="inline-flex items-center gap-1.5"><MonitorSmartphone size={13} aria-hidden="true" /> {t("coord.visibility.patient")}</span>
          ) : (
            <span className="inline-flex items-center gap-1.5"><EyeOff size={13} aria-hidden="true" /> {t("coord.internal_only")}</span>
          )}
        </Fact>
        <Fact label={t("coord.task.fact_created")}>
          {formatDate(task.created_at, locale)}
          <span className="block text-xs text-ink-faint">{t("coord.task.created_by", { name: memberName(teamMap, task.created_by_user_id, t) })}</span>
        </Fact>
      </section>

      {task.patient_reported_completion && !terminal && (
        <p role="status" className="reveal mb-8 flex items-start gap-2 rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted">
          <Flag size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-status-insufficient" />
          <span>
            {rich("coord.task.reported", { claim: <span className="font-medium text-foreground">{t("coord.task.reported_claim")}</span> })}
          </span>
        </p>
      )}

      <div className="grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex flex-col gap-12">
          <Plate index="01" eyebrow={t("coord.task.next_eyebrow")} title={terminal ? t("coord.task.closed_title") : t("coord.task.open_title")}>
            {terminal ? (
              <p className="text-sm text-muted">
                {task.status === "completed"
                  ? t(task.completion_follow_up_id ? "coord.task.completed_with" : "coord.task.completed_on", {
                      date: task.completed_at ? formatDateTime(task.completed_at, locale) : "",
                      id: task.completion_follow_up_id ?? "",
                    })
                  : t("coord.task.cancelled")}
              </p>
            ) : (
              <NextActions task={task} team={teamMap} gap={gapData} today={today} />
            )}
          </Plate>

          {task.care_gap_id && gap && (
            <Plate index="02" eyebrow={t("coord.task.outreach_eyebrow")} title={t("coord.task.outreach_title")}>
              <ResourceView resource={gap} what={t("coord.task.what_gap")} onRetry={onRetry}>
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

          <Plate index={task.care_gap_id ? "03" : "02"} eyebrow={t("coord.history")} title={t("coord.task.timeline_title")} description={t("coord.task.timeline_desc")}>
            <TaskTimeline task={task} team={teamMap} />
          </Plate>
        </div>

        <aside className="flex flex-col gap-10">
          <section aria-label={t("coord.task.patient_sees")}>
            <h3 className="mb-3 text-xs font-medium text-faint">{t("coord.task.patient_sees")}</h3>
            {task.patient_visible ? (
              <div className="rounded-xl border border-border bg-surface p-4">
                <VisibilityBadge visibility="patient" />
                <p className="mt-3 text-sm leading-relaxed text-foreground" dir={task.language === "ar" ? "rtl" : "ltr"} lang={task.language}>
                  {task.patient_message}
                </p>
                <p className="mt-3 text-xs text-faint">
                  {t("coord.task.template_note", { template, language: t(task.language === "ar" ? "coord.lang.ar" : "coord.lang.en") })}
                </p>
              </div>
            ) : (
              <p className="rounded-xl border border-dashed border-border-strong p-4 text-sm text-muted">{t("coord.task.internal_follow_up")}</p>
            )}
            {task.staff_note && (
              <div className="mt-4 rounded-xl bg-surface-sunken p-4">
                <VisibilityBadge visibility="internal" />
                <p className="mt-2 whitespace-pre-wrap text-sm text-foreground">{task.staff_note}</p>
              </div>
            )}
          </section>

          <section aria-label={t("coord.task.gap_evidence")}>
            <h3 className="mb-3 text-xs font-medium text-faint">{t("coord.task.gap_evidence")}</h3>
            {!task.care_gap_id ? (
              <p className="text-sm text-muted">{t("coord.task.no_gap")}</p>
            ) : (
              gap && (
                <ResourceView resource={gap} what={t("coord.task.what_gap")} onRetry={onRetry}>
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
      <p className="text-xs font-medium text-ink-faint">{label}</p>
      <div className="mt-1.5 text-sm text-ink-text">{children}</div>
    </div>
  );
}

function GapEvidence({ gap, rule }: { gap: CareGapDetailOut; rule: RuleSummaryOut | null }) {
  const { t, locale } = useLocale();
  const open = gap.status === "open";
  return (
    <div className="flex flex-col gap-4 text-sm">
      <dl className="grid grid-cols-2 gap-3">
        <div>
          <dt className="text-[11px] uppercase tracking-[0.08em] text-faint">{t("coord.status")}</dt>
          <dd className="mt-1">
            <StatusPill tone={open ? "due" : gap.status === "closed_completed" ? "completed" : "not_eligible"} label={gapStatusText(gap.status, t)} />
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-[0.08em] text-faint">{t("coord.task.identified")}</dt>
          <dd className="mt-1 text-foreground">{formatDate(gap.identified_date, locale)}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-[11px] uppercase tracking-[0.08em] text-faint">{t("coord.task.rule_label")}</dt>
          <dd className="mt-1 text-foreground">
            <span className="ltr-value font-mono text-xs">{gap.rule_id}</span> · {gapTypeText(gap.gap_type, t)}
            <span className="mt-0.5 block text-xs text-muted">{rule?.description ?? gap.rule?.description}</span>
          </dd>
        </div>
        {gap.priority_score != null && (
          <div className="col-span-2">
            <dt className="text-[11px] uppercase tracking-[0.08em] text-faint">{t("coord.task.engine_score")}</dt>
            <dd className="mt-1 text-foreground">
              {gap.priority_score.toFixed(2)}
              {gap.priority_explanation && <span className="block text-xs text-muted">{gap.priority_explanation}</span>}
            </dd>
          </div>
        )}
      </dl>
      {gap.recommended_pathway && (
        <div className="rounded-xl border border-border p-3">
          <p className="text-[11px] uppercase tracking-[0.08em] text-faint">{t("coord.task.next_step")}</p>
          <p className="mt-1 text-foreground">{gap.recommended_pathway.description}</p>
          <p className="mt-1 text-xs text-faint">{gap.recommended_pathway.notice}</p>
        </div>
      )}
      <div>
        <p className="text-[11px] uppercase tracking-[0.08em] text-faint">{t("coord.task.linked_appointments")}</p>
        {gap.linked_appointments.length === 0 ? (
          <p className="mt-1 text-muted">{t("coord.task.none_recorded")}</p>
        ) : (
          <ul className="mt-1 flex flex-col gap-1">
            {gap.linked_appointments.map((a) => (
              <li key={a.appointment_id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-foreground">
                  {appointmentTypeText(a.appointment_type, t)} · {formatDateTime(a.scheduled_datetime, locale)}
                </span>
                <StatusPill tone={APPOINTMENT_STATUS_META[a.status]?.tone ?? "eligible"} label={APPOINTMENT_STATUS_META[a.status] ? t(APPOINTMENT_STATUS_META[a.status].label) : a.status} />
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <p className="text-[11px] uppercase tracking-[0.08em] text-faint">{t("coord.task.linked_referrals")}</p>
        {gap.linked_referrals.length === 0 ? (
          <p className="mt-1 text-muted">{t("coord.task.none_recorded")}</p>
        ) : (
          <ul className="mt-1 flex flex-col gap-1">
            {gap.linked_referrals.map((r) => (
              <li key={r.referral_id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-foreground">
                  {r.referral_target} <span className="ltr-value font-mono text-xs text-muted">{r.referral_id}</span>
                </span>
                <StatusPill tone={REFERRAL_STATUS_META[r.status]?.tone ?? "eligible"} label={REFERRAL_STATUS_META[r.status] ? t(REFERRAL_STATUS_META[r.status].label) : r.status} />
              </li>
            ))}
          </ul>
        )}
      </div>
      <Footnote className="mt-0">{t("coord.task.gap_footnote")}</Footnote>
      {rule && (
        <Link href={`/people/${encodeURIComponent(gap.patient_id)}#care-gaps`} className={buttonClass("quiet", "self-start px-0")}>
          {t("coord.task.view_trace")}
        </Link>
      )}
    </div>
  );
}

type ActionTab = "contact" | "update" | "note" | "message" | "escalate" | "complete";

function NextActions({ task, team, gap, today }: { task: TaskDetailOut; team: Map<string, CareTeamMemberOut> | null; gap: CareGapDetailOut | null; today: string }) {
  const { can } = useAuth();
  const { t } = useLocale();
  const canUpdate = can("followups.update");
  const tabs: { value: ActionTab; label: string }[] = canUpdate
    ? [
        { value: "contact", label: t("coord.task.tab_contact") },
        { value: "update", label: t("coord.task.tab_update") },
        { value: "note", label: t("coord.internal_note") },
        ...(task.patient_visible ? [{ value: "message" as const, label: t("coord.task.tab_message") }] : []),
        { value: "escalate", label: t("coord.task.tab_escalate") },
        { value: "complete", label: t("coord.task.tab_complete") },
      ]
    : [];
  const [tab, setTab] = useState<ActionTab>("contact");
  if (!canUpdate)
    return (
      <PermissionNotice title={t("coord.task.no_update_permission")} permission="followups.update">
        {t("coord.task.read_only")}
      </PermissionNotice>
    );
  return (
    <div className="flex flex-col gap-5">
      <div className="-mx-1 overflow-x-auto px-1 pb-1">
        <Segmented label={t("coord.task.action")} options={tabs} value={tab} onChange={setTab} className="min-w-max" />
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
  const { t } = useLocale();
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
    <form onSubmit={submit} aria-label={t("coord.task.record_contact")} className="flex flex-col gap-4">
      <p className="text-sm text-muted">{t("coord.task.contact_desc")}</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className={labelClass}>
          {t("coord.channel")}
          <select className={inputClass} value={channel} onChange={(e) => setChannel(e.target.value as ContactChannel)}>
            {(Object.keys(CONTACT_CHANNEL_LABELS) as ContactChannel[]).map((c) => (
              <option key={c} value={c}>
                {t(CONTACT_CHANNEL_LABELS[c])}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          {t("coord.task.outcome")}
          <select className={inputClass} value={outcome} onChange={(e) => setOutcome(e.target.value as ContactOutcome)}>
            {(Object.keys(CONTACT_OUTCOME_META) as ContactOutcome[]).map((o) => (
              <option key={o} value={o}>
                {t(CONTACT_OUTCOME_META[o].label)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className={labelClass}>
        <span className="flex items-center gap-1.5"><EyeOff size={12} aria-hidden="true" /> {t("coord.note_internal")}</span>
        <textarea className={textareaClass} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
      </label>
      <FormError message={error} />
      {done && <Confirmation>{t("coord.task.contact_recorded")}</Confirmation>}
      <div>
        <button type="submit" className={buttonClass("primary")} disabled={pending}>
          {pending ? t("coord.recording") : t("coord.task.record_contact")}
        </button>
      </div>
    </form>
  );
}

const TRANSITION_LABELS: Record<"awaiting_patient" | "in_progress" | "cancelled", MessageKey> = {
  awaiting_patient: "coord.transition.awaiting_patient",
  in_progress: "coord.transition.in_progress",
  cancelled: "coord.transition.cancelled",
};

function UpdateForm({ task, team, today }: { task: TaskDetailOut; team: Map<string, CareTeamMemberOut> | null; today: string }) {
  const { t } = useLocale();
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
    if (await status.run(() => api.updateTask(task.task_id, { status: to }))) setDone(t("coord.task.status_changed", { status: t(TASK_STATUS_META[to].label) }));
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setDone(null);
    const body = {
      ...(assignee && assignee !== task.assigned_to_user_id ? { assigned_to_user_id: assignee } : {}),
      ...(due !== (task.due_date ?? "") ? (due ? { due_date: due } : { clear_due_date: true }) : {}),
      ...(priority !== task.priority ? { priority } : {}),
    };
    if (await save.run(() => api.updateTask(task.task_id, body))) setDone(t("coord.task.changes_saved"));
  };
  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="mb-2 text-xs font-medium text-faint">{t("coord.task.move_to")}</p>
        <div className="flex flex-wrap gap-2">
          {transitions.map((s) => (
            <button key={s} type="button" className={buttonClass(s === "cancelled" ? "quiet" : "secondary")} disabled={status.pending} onClick={() => move(s)}>
              {t(TRANSITION_LABELS[s])}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-faint">{t("coord.task.completion_step")}</p>
        <FormError message={status.error} />
      </div>
      <form onSubmit={submit} aria-label={t("coord.task.update_aria")} className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className={labelClass}>
            {t("coord.form.assigned_coordinator")}
            <select className={inputClass} value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              {!task.assigned_to_user_id && <option value="">{t("coord.member.unassigned")}</option>}
              {task.assigned_to_user_id && !assignable.some((m) => m.user_id === task.assigned_to_user_id) && (
                <option value={task.assigned_to_user_id}>{memberName(team, task.assigned_to_user_id, t)}</option>
              )}
              {assignable.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.is_self ? t("coord.member.you", { name: m.full_name }) : m.full_name} · {roleText(m.role, t)}
                </option>
              ))}
            </select>
          </label>
          <label className={labelClass}>
            {t("coord.due_date")}
            <input type="date" className={inputClass} value={due} min={today} onChange={(e) => setDue(e.target.value)} />
          </label>
          <label className={labelClass}>
            {t("coord.priority")}
            <select className={inputClass} value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)}>
              {PRIORITY_ORDER.map((p) => (
                <option key={p} value={p}>
                  {t(PRIORITY_META[p].label)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <FormError message={save.error} />
        <div>
          <button type="submit" className={buttonClass("primary")} disabled={save.pending || !dirty}>
            {save.pending ? t("coord.saving") : t("coord.task.save_changes")}
          </button>
        </div>
      </form>
      {done && <Confirmation>{done}</Confirmation>}
    </div>
  );
}

function NoteForm({ task, visible }: { task: TaskDetailOut; visible: boolean }) {
  const { t } = useLocale();
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
    <form onSubmit={submit} aria-label={visible ? t("coord.task.message_aria") : t("coord.task.note_aria")} className="flex flex-col gap-4">
      <p className="text-sm text-muted">{visible ? t("coord.task.message_desc") : t("coord.task.note_desc")}</p>
      <label className={labelClass}>
        <span className="flex items-center gap-1.5">
          {visible ? <MonitorSmartphone size={12} aria-hidden="true" /> : <EyeOff size={12} aria-hidden="true" />}
          {visible ? t("coord.task.message_label") : t("coord.internal_note")}
        </span>
        <textarea className={textareaClass} value={text} maxLength={2000} required onChange={(e) => setText(e.target.value)} />
      </label>
      <FormError message={error} />
      {done && <Confirmation>{visible ? t("coord.task.message_added") : t("coord.task.note_added")}</Confirmation>}
      <div>
        <button type="submit" className={buttonClass("primary")} disabled={pending || !text.trim()}>
          {pending ? t("coord.saving") : visible ? t("coord.task.post_portal") : t("coord.task.note_aria")}
        </button>
      </div>
    </form>
  );
}

function EscalateForm({ task }: { task: TaskDetailOut }) {
  const { t, locale } = useLocale();
  const [reason, setReason] = useState("");
  const { run, pending, error } = useMutation();
  const [done, setDone] = useState(false);
  return (
    <form
      aria-label={t("coord.task.escalate_aria")}
      className="flex flex-col gap-4"
      onSubmit={async (e) => {
        e.preventDefault();
        if (await run(() => api.escalateTask(task.task_id, reason.trim() || null))) setDone(true);
      }}
    >
      <p className="text-sm text-muted">
        {task.escalated_at ? t("coord.task.escalated_desc", { date: formatDateTime(task.escalated_at, locale) }) : t("coord.task.escalate_desc")}
      </p>
      <label className={labelClass}>
        {t("coord.task.reason_internal")}
        <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <FormError message={error} />
      {done && <Confirmation>{t("coord.task.escalation_recorded")}</Confirmation>}
      <div>
        <button type="submit" className={buttonClass("primary")} disabled={pending}>
          {t("coord.task.tab_escalate")}
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
  const { t, rich, locale } = useLocale();
  const [evidence, setEvidence] = useState("");
  const [note, setNote] = useState("");
  const { run, pending, error } = useMutation();
  const documented = gap?.follow_up_events.filter((f) => f.event_type === "completion_documented") ?? [];

  if (!task.care_gap_id)
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted">{t("coord.task.no_gap_complete")}</p>
        <FormError message={error} />
        <div>
          <button type="button" className={buttonClass("primary")} disabled={pending} onClick={() => run(() => api.completeTask(task.task_id, null))}>
            {t("coord.task.complete_follow_up")}
          </button>
        </div>
      </div>
    );

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-muted">
        {t("coord.task.evidence_desc")}
      </p>
      {documented.length > 0 && (
        <div className="flex flex-col gap-2">
          {documented.map((f) => (
            <div key={f.follow_up_id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border p-3 text-sm">
              <span>
                {rich("coord.task.documented", {
                  date: formatDateTime(f.recorded_at, locale),
                  reference: <span className="ltr-value font-mono">{f.evidence_reference}</span>,
                })}
              </span>
              <button type="button" className={buttonClass("primary")} disabled={pending} onClick={() => run(() => api.completeTask(task.task_id, f.follow_up_id))}>
                {t("coord.task.complete_with")}
              </button>
            </div>
          ))}
        </div>
      )}
      {gap?.status === "open" &&
        (can("care_gaps.complete") ? (
          <form
            aria-label={t("coord.task.document_aria")}
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
              {t("coord.task.evidence_id")}
              <input className={`${inputClass} font-mono`} required value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="SYNTH-SCR-… / SYNTH-WCV-… / SYNTH-REF-…" />
              <span className="normal-case tracking-normal text-faint">{t("coord.task.evidence_hint")}</span>
            </label>
            <label className={labelClass}>
              {t("coord.note_internal")}
              <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
            <div>
              <button type="submit" className={buttonClass("primary")} disabled={pending || !evidence.trim()}>
                {pending ? t("coord.task.checking") : t("coord.task.document_close")}
              </button>
            </div>
          </form>
        ) : (
          <PermissionNotice title={t("coord.task.no_complete_permission")} permission="care_gaps.complete">
            {t("coord.task.complete_permission_desc")}
          </PermissionNotice>
        ))}
      {gap && gap.status !== "open" && documented.length === 0 && (
        <p className="text-sm text-muted">{t("coord.task.gap_not_open", { status: gapStatusText(gap.status, t).toLowerCase() })}</p>
      )}
      <FormError message={error} />
    </div>
  );
}

function TaskTimeline({ task, team }: { task: TaskDetailOut; team: Map<string, CareTeamMemberOut> | null }) {
  const { t, locale } = useLocale();
  return (
    <ol className="relative flex flex-col gap-5 border-s border-border ps-5">
      {task.events.map((e, i) => (
        <li key={e.event_id} className="reveal relative" style={{ "--i": Math.min(i, 10) } as React.CSSProperties}>
          <span className="absolute -start-[27px] top-1 rounded-full bg-background p-0.5">
            <ToneGlyph tone={eventTone(e)} />
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-foreground">{taskEventText(e, t)}</span>
            <VisibilityBadge visibility={e.visibility} />
          </div>
          {e.message && (
            <p className={cn("mt-1 whitespace-pre-wrap text-sm", e.visibility === "internal" ? "text-muted" : "text-foreground")}>{e.message}</p>
          )}
          <p className="mt-1 text-xs text-faint">
            {actorLabel(team, e.actor_user_id, e.actor_role, t)} · {formatDateTime(e.created_at, locale)}
          </p>
        </li>
      ))}
    </ol>
  );
}
