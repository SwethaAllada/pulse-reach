"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertOctagon, ArrowUpRight, EyeOff, Flag, Plus, X } from "lucide-react";
import type { CareTeamMemberOut, Pathway, RegionId, RuleSummaryOut, TaskOut, TaskPriority, TaskQuery, TaskStatus, TaskSummaryOut } from "@/lib/api/types";
import { scopeLabel, useAuth } from "@/lib/auth/auth-context";
import {
  PRIORITY_META,
  PRIORITY_ORDER,
  TASK_STATUS_META,
  TASK_STATUS_ORDER,
  TERMINAL_TASK_STATUSES,
  actorLabel,
  addDays,
  dueText,
  formatDateTime,
  memberName,
  taskEventText,
  eventTone,
  isoDate,
  roleText,
  templateText,
} from "@/lib/coordination/model";
import {
  TASK_PAGE_SIZE,
  useCareTeam,
  useRulesIndex,
  useTaskPage,
  useTaskSummary,
} from "@/lib/coordination/use-coordination";
import { PATHWAY_OPTIONS, REGION_OPTIONS } from "@/lib/population/filters";
import { useKeepPrevious } from "@/lib/api/resource";
import { PageHeader } from "@/components/ui/page-header";
import { Plate, Footnote } from "@/components/ui/plate";
import { Figure } from "@/components/ui/figure";
import { buttonClass } from "@/components/ui/button-styles";
import { FORWARD } from "@/components/ui/page-transition";
import { ResourceView } from "@/components/programmes/resource-state";
import { LoadingState } from "@/components/ui/loading-state";
import { CreateTaskForm } from "./create-task-form";
import { DistributionBand, Pager, PriorityMark, QuietEmpty, StatusPill, ToneGlyph, inputClass, labelClass } from "./primitives";
import { cn } from "@/lib/cn";
import { useLocale } from "@/lib/i18n/use-locale";
import type { Translate } from "@/lib/i18n/translate";

type DueFilter = "" | "overdue" | "soon" | "month";
type StatusFilter = "" | "active" | "closed" | TaskStatus;

export interface QueueFilters {
  status: StatusFilter;
  priority: TaskPriority | "";
  assigned: string;
  pathway: Pathway | "";
  region: RegionId | 0;
  due: DueFilter;
}

const EMPTY: QueueFilters = { status: "active", priority: "", assigned: "", pathway: "", region: 0, due: "" };

/** Scope filters shared by the overview counts and the queue. */
function scopeQuery(f: QueueFilters): TaskQuery {
  return {
    priority: f.priority || undefined,
    assigned_to: f.assigned || undefined,
    pathway: f.pathway || undefined,
    region_id: f.region || undefined,
  };
}

export function queueQuery(f: QueueFilters, today: string): TaskQuery {
  const q: TaskQuery = scopeQuery(f);
  if (f.status === "active") q.active = true;
  else if (f.status === "closed") q.active = false;
  else if (f.status) q.status = f.status;
  if (f.due === "overdue") q.overdue = true;
  if (f.due === "soon" || f.due === "month") {
    q.due_after = today;
    q.due_before = addDays(today, f.due === "soon" ? 7 : 30);
  }
  return q;
}

export function FollowUpWorkspace() {
  const { can, scope, state: auth } = useAuth();
  const { t } = useLocale();
  const router = useRouter();
  const [filters, setFilters] = useState<QueueFilters>(EMPTY);
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const today = useMemo(() => isoDate(new Date()), []);
  const retry = () => setAttempt((n) => n + 1);

  const summary = useKeepPrevious(useTaskSummary(scopeQuery(filters), attempt));
  const tasks = useTaskPage(queueQuery(filters, today), page, attempt);
  const team = useCareTeam();
  const rules = useRulesIndex();
  const teamMap = team.status === "ready" ? team.data : null;
  const ruleMap = rules.status === "ready" ? rules.data : null;
  const asOf = summary.status === "ready" ? summary.data.as_of : today;

  const update = (patch: Partial<QueueFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(1);
  };

  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow={t("coord.fu.eyebrow")}
        title={t("nav.follow_up")}
        subtitle={t("coord.fu.subtitle")}
        breadcrumbs={[{ label: t("nav.follow_up") }]}
        meta={
          <span className="flex flex-wrap gap-x-4 gap-y-1">
            <span>{t("coord.fu.counts_as_of", { date: asOf })}</span>
            {auth.status === "signed_in" && <span>{t("coord.scope", { scope: scopeLabel(scope, t) })}</span>}
          </span>
        }
        actions={
          can("followups.create") && !creating ? (
            <button type="button" className={buttonClass("primary")} onClick={() => setCreating(true)}>
              <Plus size={15} aria-hidden="true" /> {t("coord.new_follow_up")}
            </button>
          ) : undefined
        }
        className="mb-6"
      />

      {creating && (
        <div className="mb-10">
          <CreateTaskForm
            today={today}
            onCancel={() => setCreating(false)}
            onCreated={(task) => router.push(`/follow-up/${encodeURIComponent(task.task_id)}`)}
          />
        </div>
      )}

      <ResourceView
        resource={summary}
        what={t("coord.fu.what_counts")}
        onRetry={retry}
        loading={<div aria-busy="true" aria-label={t("coord.fu.loading_counts")} className="skeleton h-64 rounded-xl" />}
      >
        {(s) => <WorkloadPlate summary={s} filters={filters} onFilter={update} />}
      </ResourceView>

      <div className="mt-12 grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Plate
          index="01"
          eyebrow={t("coord.fu.queue_eyebrow")}
          title={t("coord.fu.queue_title")}
          description={t("coord.fu.queue_desc")}
        >
          <QueueFilterBar filters={filters} team={teamMap} onChange={update} onReset={() => update(EMPTY)} />
          <div className="mt-5">
            <ResourceView resource={tasks} what={t("coord.fu.what_tasks")} onRetry={retry} loading={<LoadingState rows={6} label={t("coord.fu.loading_tasks")} />}>
              {(p) =>
                p.items.length === 0 ? (
                  <QuietEmpty title={t("coord.fu.empty_title")}>
                    {JSON.stringify(filters) === JSON.stringify(EMPTY) ? t("coord.fu.empty_scope") : t("coord.fu.empty_filters")}
                  </QuietEmpty>
                ) : (
                  <>
                    <TaskList tasks={p.items} team={teamMap} rules={ruleMap} today={asOf} />
                    <Pager page={page} total={p.total} size={TASK_PAGE_SIZE} onPage={setPage} label={t("coord.fu.pager")} />
                  </>
                )
              }
            </ResourceView>
          </div>
        </Plate>

        <aside className="flex flex-col gap-12">
          <Plate index="02" eyebrow={t("coord.fu.workload_eyebrow")} title={t("coord.fu.workload_title")} description={t("coord.fu.workload_desc")}>
            <ResourceView resource={summary} what={t("coord.fu.what_workload")} onRetry={retry}>
              {(s) => <Workload summary={s} team={teamMap} selected={filters.assigned} onSelect={(id) => update({ assigned: filters.assigned === id ? "" : id })} />}
            </ResourceView>
          </Plate>
          <Plate index="03" eyebrow={t("coord.fu.recent_eyebrow")} title={t("coord.fu.recent_title")}>
            <ResourceView resource={summary} what={t("coord.fu.recent_eyebrow")} onRetry={retry}>
              {(s) => <RecentActivity summary={s} team={teamMap} />}
            </ResourceView>
          </Plate>
        </aside>
      </div>
    </div>
  );
}

function WorkloadPlate({ summary: s, filters, onFilter }: { summary: TaskSummaryOut; filters: QueueFilters; onFilter: (p: Partial<QueueFilters>) => void }) {
  const { t } = useLocale();
  const toggleDue = (due: DueFilter) => onFilter({ due: filters.due === due ? "" : due, status: "active" });
  return (
    <section aria-label={t("coord.fu.overview")} className="reveal relative overflow-hidden rounded-xl border border-border bg-surface-raised p-6 text-ink-text sm:p-8">
      <div className="relative grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-3">
          <Figure tone="plate" size="xl" className="col-span-2 sm:col-span-3" label={t("coord.fu.active")} value={s.active} note={t("coord.fu.active_note", { total: String(s.total), completed: String(s.completed), cancelled: String(s.cancelled) })} />
          <FigureButton label={t("coord.fu.overdue")} value={s.overdue} note={t("coord.fu.overdue_note")} active={filters.due === "overdue"} onClick={() => toggleDue("overdue")} accent />
          <FigureButton label={t("coord.fu.due_soon", { count: String(s.due_soon_days) })} value={s.due_soon} note={t("coord.fu.due_soon_note")} active={filters.due === "soon"} onClick={() => toggleDue("soon")} />
          <FigureButton
            label={t("coord.member.unassigned")}
            value={s.unassigned_active}
            note={t("coord.fu.unassigned_note")}
            active={filters.assigned === "unassigned"}
            onClick={() => onFilter({ assigned: filters.assigned === "unassigned" ? "" : "unassigned", status: "active" })}
          />
        </dl>
        <div className="flex flex-col gap-6">
          <div>
            <p className="mb-3 text-xs font-medium text-ink-faint">{t("coord.fu.by_status_heading")}</p>
            <DistributionBand
              surface="ink"
              label={t("coord.fu.by_status")}
              selected={TASK_STATUS_ORDER.includes(filters.status as TaskStatus) ? filters.status : null}
              onSelect={(k) => onFilter({ status: filters.status === k ? "active" : (k as TaskStatus), due: "" })}
              parts={TASK_STATUS_ORDER.map((st) => ({ key: st, label: t(TASK_STATUS_META[st].label), count: s.by_status[st] ?? 0, tone: TASK_STATUS_META[st].tone }))}
            />
          </div>
          <div>
            <p className="mb-3 text-xs font-medium text-ink-faint">{t("coord.fu.by_priority")}</p>
            <ul className="flex flex-col gap-2">
              {PRIORITY_ORDER.map((p) => {
                const n = s.active_by_priority[p] ?? 0;
                return (
                  <li key={p}>
                    <button
                      type="button"
                      aria-pressed={filters.priority === p}
                      onClick={() => onFilter({ priority: filters.priority === p ? "" : p })}
                      className={cn("group grid w-full grid-cols-[88px_minmax(0,1fr)_40px] items-center gap-3 rounded-lg py-0.5 text-start text-xs", filters.priority === p && "text-ink-accent")}
                    >
                      <PriorityMark priority={p} surface="ink" />
                      <span className="h-1.5 overflow-hidden rounded-full bg-ink-raised">
                        <span
                          className="grow-x block h-full rounded-full"
                          style={{ width: s.active ? `${(n / s.active) * 100}%` : "0%", backgroundColor: `var(--ink-${p === "urgent" ? "due" : p === "high" ? "insufficient" : "muted"})` }}
                        />
                      </span>
                      <span className="text-end font-mono tabular-nums text-ink-text">{n}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
          {s.patient_reported_completion > 0 && (
            <p className="flex items-start gap-2 rounded-xl border border-ink-line px-3 py-2 text-xs text-ink-muted">
              <Flag size={14} aria-hidden="true" className="mt-px shrink-0 text-ink-insufficient" />
              {t(s.patient_reported_completion === 1 ? "coord.fu.reported_one" : "coord.fu.reported_n", { count: String(s.patient_reported_completion) })}
            </p>
          )}
        </div>
      </div>
      <Footnote className="relative text-ink-faint">
        {t(filters.pathway || filters.region || filters.priority || filters.assigned ? "coord.fu.footnote_filtered" : "coord.fu.footnote", { date: s.as_of })}
      </Footnote>
    </section>
  );
}

function FigureButton({ label, value, note, active, onClick, accent }: { label: string; value: number; note: string; active: boolean; onClick: () => void; accent?: boolean }) {
  return (
    <div className="min-w-0">
      <button
        type="button"
        aria-pressed={active}
        onClick={onClick}
        className={cn(
          "w-full rounded-xl border px-3 py-2 text-start transition-colors duration-200",
          active ? "border-ink-accent bg-ink-raised" : "border-transparent hover:border-ink-line"
        )}
      >
        <dl>
          <Figure tone="plate" size="md" label={label} value={<span className={accent && value > 0 ? "text-ink-due" : undefined}>{value}</span>} note={note} />
        </dl>
      </button>
    </div>
  );
}

function QueueFilterBar({ filters, team, onChange, onReset }: { filters: QueueFilters; team: Map<string, CareTeamMemberOut> | null; onChange: (p: Partial<QueueFilters>) => void; onReset: () => void }) {
  const { t } = useLocale();
  const changed = JSON.stringify(filters) !== JSON.stringify(EMPTY);
  return (
    <div role="search" aria-label={t("coord.fu.filters")} className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <label className={labelClass}>
        {t("coord.status")}
        <select className={inputClass} value={filters.status} onChange={(e) => onChange({ status: e.target.value as StatusFilter })}>
          <option value="active">{t("coord.fu.status_active")}</option>
          <option value="">{t("coord.all_statuses")}</option>
          {TASK_STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {t(TASK_STATUS_META[s].label)}
            </option>
          ))}
          <option value="closed">{t("coord.fu.status_closed")}</option>
        </select>
      </label>
      <label className={labelClass}>
        {t("coord.priority")}
        <select className={inputClass} value={filters.priority} onChange={(e) => onChange({ priority: e.target.value as TaskPriority | "" })}>
          <option value="">{t("coord.fu.any_priority")}</option>
          {PRIORITY_ORDER.map((p) => (
            <option key={p} value={p}>
              {t(PRIORITY_META[p].label)}
            </option>
          ))}
        </select>
      </label>
      <label className={labelClass}>
        {t("coord.fu.assigned_to")}
        <select className={inputClass} value={filters.assigned} onChange={(e) => onChange({ assigned: e.target.value })}>
          <option value="">{t("coord.fu.anyone")}</option>
          <option value="me">{t("coord.fu.me")}</option>
          <option value="unassigned">{t("coord.member.unassigned")}</option>
          {[...(team?.values() ?? [])]
            .filter((m) => !m.is_self)
            .map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.full_name}
              </option>
            ))}
        </select>
      </label>
      <label className={labelClass}>
        {t("coord.fu.programme")}
        <select className={inputClass} value={filters.pathway} onChange={(e) => onChange({ pathway: e.target.value as Pathway | "" })}>
          <option value="">{t("coord.fu.all_programmes")}</option>
          {PATHWAY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {t(o.short)}
            </option>
          ))}
        </select>
      </label>
      <label className={labelClass}>
        {t("coord.fu.region")}
        <select className={inputClass} value={filters.region} onChange={(e) => onChange({ region: Number(e.target.value) as RegionId | 0 })}>
          <option value={0}>{t("coord.fu.all_regions")}</option>
          {REGION_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {t(o.label)}
            </option>
          ))}
        </select>
      </label>
      <label className={labelClass}>
        {t("coord.fu.due")}
        <select className={inputClass} value={filters.due} onChange={(e) => onChange({ due: e.target.value as DueFilter })}>
          <option value="">{t("coord.fu.any_due")}</option>
          <option value="overdue">{t("coord.fu.overdue")}</option>
          <option value="soon">{t("coord.fu.within_7")}</option>
          <option value="month">{t("coord.fu.within_30")}</option>
        </select>
      </label>
      {changed && (
        <button type="button" onClick={onReset} className={cn(buttonClass("quiet"), "col-span-2 justify-self-start sm:col-span-3 lg:col-span-6")}>
          <X size={14} aria-hidden="true" /> {t("coord.fu.reset")}
        </button>
      )}
    </div>
  );
}

function programmeOf(rules: Map<string, RuleSummaryOut> | null, ruleId: string | null, t: Translate): string | null {
  if (!ruleId) return null;
  const p = rules?.get(ruleId)?.pathway;
  return p ? t(PATHWAY_OPTIONS.find((o) => o.value === p)!.short) : null;
}

export function TaskList({
  tasks,
  team,
  rules,
  today,
  hidePatient,
}: {
  tasks: TaskOut[];
  team: Map<string, CareTeamMemberOut> | null;
  rules: Map<string, RuleSummaryOut> | null;
  today: string;
  hidePatient?: boolean;
}) {
  const { t, locale } = useLocale();
  return (
    <ul aria-label={t("coord.fu.what_tasks")} className="flex flex-col divide-y divide-border border-y border-border">
      {tasks.map((task, i) => {
        const meta = TASK_STATUS_META[task.status];
        const terminal = TERMINAL_TASK_STATUSES.includes(task.status);
        const programme = programmeOf(rules, task.rule_id, t);
        return (
          <li key={task.task_id} className="reveal" style={{ "--i": Math.min(i, 8) } as React.CSSProperties}>
            <Link
              href={`/follow-up/${encodeURIComponent(task.task_id)}`}
              transitionTypes={FORWARD}
              className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-1 py-3.5 transition-colors hover:bg-surface-raised sm:grid-cols-[96px_minmax(0,1fr)_auto_auto]"
            >
              <span className="order-3 sm:order-none">
                <PriorityMark priority={task.priority} />
              </span>
              <span className="min-w-0">
                <span className="flex flex-wrap items-baseline gap-x-2">
                  {!hidePatient && <span className="ltr-value font-mono text-sm text-foreground">{task.patient_id}</span>}
                  <span className="text-sm text-foreground">{templateText(task.message_key, t)}</span>
                  {programme && <span className="text-xs text-faint">{programme}</span>}
                </span>
                <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                  <span>{memberName(team, task.assigned_to_user_id, t)}</span>
                  <span className={cn(task.is_overdue && "font-medium text-status-due")}>{dueText(task.due_date, today, terminal, t, locale)}</span>
                  {task.escalated_at && !terminal && (
                    <span className="inline-flex items-center gap-1 text-status-due">
                      <AlertOctagon size={12} aria-hidden="true" /> {t("coord.event.escalated")}
                    </span>
                  )}
                  {task.patient_reported_completion && !terminal && (
                    <span className="inline-flex items-center gap-1 text-status-insufficient">
                      <Flag size={12} aria-hidden="true" /> {t("coord.fu.reported_done")}
                    </span>
                  )}
                  {!task.patient_visible && (
                    <span className="inline-flex items-center gap-1">
                      <EyeOff size={12} aria-hidden="true" /> {t("coord.internal_only")}
                    </span>
                  )}
                </span>
              </span>
              <StatusPill tone={meta.tone} label={t(meta.label)} />
              <ArrowUpRight size={15} aria-hidden="true" className="hidden text-faint transition-transform duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-foreground rtl:-scale-x-100 sm:block" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function Workload({ summary, team, selected, onSelect }: { summary: TaskSummaryOut; team: Map<string, CareTeamMemberOut> | null; selected: string; onSelect: (id: string) => void }) {
  const { t } = useLocale();
  if (summary.workload.length === 0) return <p className="text-sm text-muted">{t("coord.fu.no_active")}</p>;
  const max = Math.max(...summary.workload.map((w) => w.active));
  return (
    <ul className="flex flex-col gap-4">
      {summary.workload.map((w) => {
        const id = w.assigned_to_user_id ?? "unassigned";
        const member = w.assigned_to_user_id ? team?.get(w.assigned_to_user_id) : null;
        const rest = Math.max(0, w.active - w.overdue - w.due_soon);
        return (
          <li key={id}>
            <button type="button" aria-pressed={selected === id} onClick={() => onSelect(id)} className="w-full text-start">
              <span className="flex items-baseline justify-between gap-2">
                <span className={cn("truncate text-sm", selected === id ? "font-semibold text-accent" : "text-foreground")}>
                  {memberName(team, w.assigned_to_user_id, t)}
                </span>
                <span className="font-mono text-sm tabular-nums text-foreground">{w.active}</span>
              </span>
              {member && <span className="block text-[11px] text-faint">{roleText(member.role, t)}</span>}
              <span className="mt-1.5 flex h-1.5 gap-px overflow-hidden rounded-full bg-surface-sunken" style={{ width: `${(w.active / max) * 100}%` }}>
                <span className="grow-x h-full bg-status-due" style={{ width: `${(w.overdue / w.active) * 100}%` }} />
                <span className="grow-x h-full bg-status-upcoming" style={{ width: `${(w.due_soon / w.active) * 100}%` }} />
                <span className="grow-x h-full bg-status-eligible" style={{ width: `${(rest / w.active) * 100}%` }} />
              </span>
              <span className="mt-1 block text-[11px] text-muted">
                {w.urgent
                  ? t("coord.fu.workload_line_urgent", { overdue: String(w.overdue), soon: String(w.due_soon), urgent: String(w.urgent) })
                  : t("coord.fu.workload_line", { overdue: String(w.overdue), soon: String(w.due_soon) })}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function RecentActivity({ summary, team }: { summary: TaskSummaryOut; team: Map<string, CareTeamMemberOut> | null }) {
  const { t, locale } = useLocale();
  if (summary.recent_events.length === 0) return <p className="text-sm text-muted">{t("coord.fu.no_activity")}</p>;
  return (
    <ol className="relative flex flex-col gap-4 border-s border-border ps-4">
      {summary.recent_events.map((e) => (
        <li key={e.event_id} className="relative">
          <span className="absolute -start-[22.5px] top-1 bg-background">
            <ToneGlyph tone={eventTone(e)} />
          </span>
          <Link href={`/follow-up/${encodeURIComponent(e.task_id)}`} className="text-sm text-foreground hover:underline">
            {taskEventText({ ...e, from_status: null }, t)}
          </Link>
          <p className="text-[11px] text-faint">
            <span className="ltr-value font-mono">{e.patient_id}</span> · {actorLabel(team, e.actor_user_id, e.actor_role, t)} · {formatDateTime(e.created_at, locale)}
          </p>
        </li>
      ))}
    </ol>
  );
}
