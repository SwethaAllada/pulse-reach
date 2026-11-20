"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertOctagon, ArrowUpRight, EyeOff, Flag, Plus, X } from "lucide-react";
import type { CareTeamMemberOut, Pathway, RegionId, RuleSummaryOut, TaskOut, TaskPriority, TaskQuery, TaskStatus, TaskSummaryOut } from "@/lib/api/types";
import { scopeLabel, useAuth } from "@/lib/auth/auth-context";
import {
  MESSAGE_KEY_LABELS,
  PRIORITY_META,
  PRIORITY_ORDER,
  ROLE_LABELS,
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
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-24 pt-8 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="Connect"
        title="Follow-up"
        subtitle="Coordinate care-gap follow-ups from identification through outreach to documented, evidence-backed completion."
        breadcrumbs={[{ label: "Follow-up" }]}
        meta={
          <span className="flex flex-wrap gap-x-4 gap-y-1">
            <span>Counts as of {asOf}</span>
            {auth.status === "signed_in" && <span>Scope: {scopeLabel(scope)}</span>}
          </span>
        }
        actions={
          can("followups.create") && !creating ? (
            <button type="button" className={buttonClass("primary")} onClick={() => setCreating(true)}>
              <Plus size={15} aria-hidden="true" /> New follow-up
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
            onCreated={(t) => router.push(`/follow-up/${encodeURIComponent(t.task_id)}`)}
          />
        </div>
      )}

      <ResourceView
        resource={summary}
        what="Follow-up counts"
        onRetry={retry}
        loading={<div aria-busy="true" aria-label="Loading follow-up counts" className="skeleton-ink h-64 rounded-2xl" />}
      >
        {(s) => <WorkloadPlate summary={s} filters={filters} onFilter={update} />}
      </ResourceView>

      <div className="mt-12 grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Plate
          index="01"
          eyebrow="Work queue"
          title="Follow-ups to coordinate"
          description="Ordered by due date. Open a follow-up to record contact, message the patient, review outreach or document completion."
        >
          <QueueFilterBar filters={filters} team={teamMap} onChange={update} onReset={() => update(EMPTY)} />
          <div className="mt-5">
            <ResourceView resource={tasks} what="Follow-up tasks" onRetry={retry} loading={<LoadingState rows={6} label="Loading follow-up tasks" />}>
              {(p) =>
                p.items.length === 0 ? (
                  <QuietEmpty title="No follow-ups match">
                    {JSON.stringify(filters) === JSON.stringify(EMPTY) ? "Nothing is waiting in your scope." : "Try widening the filters."}
                  </QuietEmpty>
                ) : (
                  <>
                    <TaskList tasks={p.items} team={teamMap} rules={ruleMap} today={asOf} />
                    <Pager page={page} total={p.total} size={TASK_PAGE_SIZE} onPage={setPage} label="Follow-up" />
                  </>
                )
              }
            </ResourceView>
          </div>
        </Plate>

        <aside className="flex flex-col gap-12">
          <Plate index="02" eyebrow="Workload" title="By coordinator" description="Active follow-ups per assignee.">
            <ResourceView resource={summary} what="Workload figures" onRetry={retry}>
              {(s) => <Workload summary={s} team={teamMap} selected={filters.assigned} onSelect={(id) => update({ assigned: filters.assigned === id ? "" : id })} />}
            </ResourceView>
          </Plate>
          <Plate index="03" eyebrow="Recent activity" title="Latest changes">
            <ResourceView resource={summary} what="Recent activity" onRetry={retry}>
              {(s) => <RecentActivity summary={s} team={teamMap} />}
            </ResourceView>
          </Plate>
        </aside>
      </div>
    </div>
  );
}

function WorkloadPlate({ summary: s, filters, onFilter }: { summary: TaskSummaryOut; filters: QueueFilters; onFilter: (p: Partial<QueueFilters>) => void }) {
  const toggleDue = (due: DueFilter) => onFilter({ due: filters.due === due ? "" : due, status: "active" });
  return (
    <section aria-label="Follow-up overview" className="reveal relative overflow-hidden rounded-2xl bg-ink p-6 text-ink-text sm:p-8">
      <span aria-hidden="true" className="pointer-events-none absolute -right-20 -top-24 size-72 rounded-full border border-ink-line" />
      <span aria-hidden="true" className="pointer-events-none absolute -right-6 -top-10 size-40 rounded-full border border-ink-line opacity-60" />
      <div className="relative grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-3">
          <Figure tone="plate" size="xl" className="col-span-2 sm:col-span-3" label="Active follow-ups" value={s.active} note={`of ${s.total} in scope · ${s.completed} completed · ${s.cancelled} cancelled`} />
          <FigureButton label="Overdue" value={s.overdue} note="past due, still open" active={filters.due === "overdue"} onClick={() => toggleDue("overdue")} accent />
          <FigureButton label={`Due in ${s.due_soon_days} days`} value={s.due_soon} note="today included" active={filters.due === "soon"} onClick={() => toggleDue("soon")} />
          <FigureButton
            label="Unassigned"
            value={s.unassigned_active}
            note="active, no coordinator"
            active={filters.assigned === "unassigned"}
            onClick={() => onFilter({ assigned: filters.assigned === "unassigned" ? "" : "unassigned", status: "active" })}
          />
        </dl>
        <div className="flex flex-col gap-6">
          <div>
            <p className="mb-3 text-[11px] font-medium uppercase tracking-[0.12em] text-ink-faint">All follow-ups by status</p>
            <DistributionBand
              surface="ink"
              label="Follow-ups by status"
              selected={TASK_STATUS_ORDER.includes(filters.status as TaskStatus) ? filters.status : null}
              onSelect={(k) => onFilter({ status: filters.status === k ? "active" : (k as TaskStatus), due: "" })}
              parts={TASK_STATUS_ORDER.map((st) => ({ key: st, label: TASK_STATUS_META[st].label, count: s.by_status[st] ?? 0, tone: TASK_STATUS_META[st].tone }))}
            />
          </div>
          <div>
            <p className="mb-3 text-[11px] font-medium uppercase tracking-[0.12em] text-ink-faint">Active by coordination priority</p>
            <ul className="flex flex-col gap-2">
              {PRIORITY_ORDER.map((p) => {
                const n = s.active_by_priority[p] ?? 0;
                return (
                  <li key={p}>
                    <button
                      type="button"
                      aria-pressed={filters.priority === p}
                      onClick={() => onFilter({ priority: filters.priority === p ? "" : p })}
                      className={cn("group grid w-full grid-cols-[88px_minmax(0,1fr)_40px] items-center gap-3 rounded-lg py-0.5 text-left text-xs", filters.priority === p && "text-ink-accent")}
                    >
                      <PriorityMark priority={p} surface="ink" />
                      <span className="h-1.5 overflow-hidden rounded-full bg-ink-raised">
                        <span
                          className="grow-x block h-full rounded-full"
                          style={{ width: s.active ? `${(n / s.active) * 100}%` : "0%", backgroundColor: `var(--ink-${p === "urgent" ? "due" : p === "high" ? "insufficient" : "muted"})` }}
                        />
                      </span>
                      <span className="text-right font-mono tabular-nums text-ink-text">{n}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
          {s.patient_reported_completion > 0 && (
            <p className="flex items-start gap-2 rounded-xl border border-ink-line px-3 py-2 text-xs text-ink-muted">
              <Flag size={14} aria-hidden="true" className="mt-px shrink-0 text-ink-insufficient" />
              {s.patient_reported_completion} active {s.patient_reported_completion === 1 ? "follow-up has" : "follow-ups have"} a patient report of
              completion awaiting verification. A report is not evidence; only documented completion closes a care gap.
            </p>
          )}
        </div>
      </div>
      <Footnote className="relative text-ink-faint">
        Exact server-side counts for your scope{filters.pathway || filters.region || filters.priority || filters.assigned ? " and the programme, region, priority and assignee filters" : ""}. Due windows use the
        server date ({s.as_of}).
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
          "w-full rounded-xl border px-3 py-2 text-left transition-colors duration-200",
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
  const changed = JSON.stringify(filters) !== JSON.stringify(EMPTY);
  return (
    <div role="search" aria-label="Follow-up filters" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <label className={labelClass}>
        Status
        <select className={inputClass} value={filters.status} onChange={(e) => onChange({ status: e.target.value as StatusFilter })}>
          <option value="active">Active (not closed)</option>
          <option value="">All statuses</option>
          {TASK_STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {TASK_STATUS_META[s].label}
            </option>
          ))}
          <option value="closed">Closed (completed or cancelled)</option>
        </select>
      </label>
      <label className={labelClass}>
        Priority
        <select className={inputClass} value={filters.priority} onChange={(e) => onChange({ priority: e.target.value as TaskPriority | "" })}>
          <option value="">Any priority</option>
          {PRIORITY_ORDER.map((p) => (
            <option key={p} value={p}>
              {PRIORITY_META[p].label}
            </option>
          ))}
        </select>
      </label>
      <label className={labelClass}>
        Assigned to
        <select className={inputClass} value={filters.assigned} onChange={(e) => onChange({ assigned: e.target.value })}>
          <option value="">Anyone</option>
          <option value="me">Me</option>
          <option value="unassigned">Unassigned</option>
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
        Programme
        <select className={inputClass} value={filters.pathway} onChange={(e) => onChange({ pathway: e.target.value as Pathway | "" })}>
          <option value="">All programmes</option>
          {PATHWAY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.short}
            </option>
          ))}
        </select>
      </label>
      <label className={labelClass}>
        Region
        <select className={inputClass} value={filters.region} onChange={(e) => onChange({ region: Number(e.target.value) as RegionId | 0 })}>
          <option value={0}>All regions</option>
          {REGION_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label className={labelClass}>
        Due
        <select className={inputClass} value={filters.due} onChange={(e) => onChange({ due: e.target.value as DueFilter })}>
          <option value="">Any due date</option>
          <option value="overdue">Overdue</option>
          <option value="soon">Within 7 days</option>
          <option value="month">Within 30 days</option>
        </select>
      </label>
      {changed && (
        <button type="button" onClick={onReset} className={cn(buttonClass("quiet"), "col-span-2 justify-self-start sm:col-span-3 lg:col-span-6")}>
          <X size={14} aria-hidden="true" /> Reset filters
        </button>
      )}
    </div>
  );
}

function programmeOf(rules: Map<string, RuleSummaryOut> | null, ruleId: string | null): string | null {
  if (!ruleId) return null;
  const p = rules?.get(ruleId)?.pathway;
  return p ? PATHWAY_OPTIONS.find((o) => o.value === p)!.short : null;
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
  return (
    <ul aria-label="Follow-up tasks" className="flex flex-col divide-y divide-border border-y border-border">
      {tasks.map((t, i) => {
        const meta = TASK_STATUS_META[t.status];
        const terminal = TERMINAL_TASK_STATUSES.includes(t.status);
        const programme = programmeOf(rules, t.rule_id);
        return (
          <li key={t.task_id} className="reveal" style={{ "--i": Math.min(i, 8) } as React.CSSProperties}>
            <Link
              href={`/follow-up/${encodeURIComponent(t.task_id)}`}
              transitionTypes={FORWARD}
              className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-1 py-3.5 transition-colors hover:bg-surface-raised sm:grid-cols-[96px_minmax(0,1fr)_auto_auto]"
            >
              <span className="order-3 sm:order-none">
                <PriorityMark priority={t.priority} />
              </span>
              <span className="min-w-0">
                <span className="flex flex-wrap items-baseline gap-x-2">
                  {!hidePatient && <span className="font-mono text-sm text-foreground">{t.patient_id}</span>}
                  <span className="text-sm text-foreground">{MESSAGE_KEY_LABELS[t.message_key as keyof typeof MESSAGE_KEY_LABELS] ?? t.message_key}</span>
                  {programme && <span className="text-xs text-faint">{programme}</span>}
                </span>
                <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                  <span>{memberName(team, t.assigned_to_user_id)}</span>
                  <span className={cn(t.is_overdue && "font-medium text-status-due")}>{dueText(t.due_date, today, terminal)}</span>
                  {t.escalated_at && !terminal && (
                    <span className="inline-flex items-center gap-1 text-status-due">
                      <AlertOctagon size={12} aria-hidden="true" /> Escalated
                    </span>
                  )}
                  {t.patient_reported_completion && !terminal && (
                    <span className="inline-flex items-center gap-1 text-status-insufficient">
                      <Flag size={12} aria-hidden="true" /> Patient reports done · unverified
                    </span>
                  )}
                  {!t.patient_visible && (
                    <span className="inline-flex items-center gap-1">
                      <EyeOff size={12} aria-hidden="true" /> Internal only
                    </span>
                  )}
                </span>
              </span>
              <StatusPill tone={meta.tone} label={meta.label} />
              <ArrowUpRight size={15} aria-hidden="true" className="hidden text-faint transition-transform duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-foreground sm:block" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function Workload({ summary, team, selected, onSelect }: { summary: TaskSummaryOut; team: Map<string, CareTeamMemberOut> | null; selected: string; onSelect: (id: string) => void }) {
  if (summary.workload.length === 0) return <p className="text-sm text-muted">No active follow-ups.</p>;
  const max = Math.max(...summary.workload.map((w) => w.active));
  return (
    <ul className="flex flex-col gap-4">
      {summary.workload.map((w) => {
        const id = w.assigned_to_user_id ?? "unassigned";
        const member = w.assigned_to_user_id ? team?.get(w.assigned_to_user_id) : null;
        const rest = Math.max(0, w.active - w.overdue - w.due_soon);
        return (
          <li key={id}>
            <button type="button" aria-pressed={selected === id} onClick={() => onSelect(id)} className="w-full text-left">
              <span className="flex items-baseline justify-between gap-2">
                <span className={cn("truncate text-sm", selected === id ? "font-semibold text-accent" : "text-foreground")}>
                  {memberName(team, w.assigned_to_user_id)}
                </span>
                <span className="font-mono text-sm tabular-nums text-foreground">{w.active}</span>
              </span>
              {member && <span className="block text-[11px] text-faint">{ROLE_LABELS[member.role] ?? member.role}</span>}
              <span className="mt-1.5 flex h-1.5 gap-px overflow-hidden rounded-full bg-surface-sunken" style={{ width: `${(w.active / max) * 100}%` }}>
                <span className="grow-x h-full bg-status-due" style={{ width: `${(w.overdue / w.active) * 100}%` }} />
                <span className="grow-x h-full bg-status-upcoming" style={{ width: `${(w.due_soon / w.active) * 100}%` }} />
                <span className="grow-x h-full bg-status-eligible" style={{ width: `${(rest / w.active) * 100}%` }} />
              </span>
              <span className="mt-1 block text-[11px] text-muted">
                {w.overdue} overdue · {w.due_soon} due soon{w.urgent ? ` · ${w.urgent} urgent` : ""}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function RecentActivity({ summary, team }: { summary: TaskSummaryOut; team: Map<string, CareTeamMemberOut> | null }) {
  if (summary.recent_events.length === 0) return <p className="text-sm text-muted">No follow-up activity recorded yet.</p>;
  return (
    <ol className="relative flex flex-col gap-4 border-l border-border pl-4">
      {summary.recent_events.map((e) => (
        <li key={e.event_id} className="relative">
          <span className="absolute -left-[22.5px] top-1 bg-background">
            <ToneGlyph tone={eventTone(e)} />
          </span>
          <Link href={`/follow-up/${encodeURIComponent(e.task_id)}`} className="text-sm text-foreground hover:underline">
            {taskEventText({ ...e, from_status: null })}
          </Link>
          <p className="text-[11px] text-faint">
            <span className="font-mono">{e.patient_id}</span> · {actorLabel(team, e.actor_user_id, e.actor_role)} · {formatDateTime(e.created_at)}
          </p>
        </li>
      ))}
    </ol>
  );
}
