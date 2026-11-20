"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, CalendarClock, Inbox } from "lucide-react";
import { api } from "@/lib/api/client";
import { useResource, type Resource } from "@/lib/api/resource";
import { useAuth, scopeLabel } from "@/lib/auth/auth-context";
import {
  APPOINTMENT_STATUS_META,
  APPOINTMENT_TYPE_LABELS,
  REQUEST_STATUS_META,
  REQUEST_TYPE_LABELS,
  formatDateTime,
  isoDate,
} from "@/lib/coordination/model";
import {
  useAppointmentPage,
  useCareTeam,
  useCoordinationVersion,
  useRequestPage,
  useRulesIndex,
  useTaskPage,
  useTaskSummary,
} from "@/lib/coordination/use-coordination";
import { ageLabel, sexLabel } from "@/lib/people/person";
import { regionLabel } from "@/lib/population/filters";
import { PopulationWorkspace } from "@/components/population/population-workspace";
import { RequirePermission } from "@/components/auth/require-permission";
import { AdminOverview } from "@/components/admin/admin-overview";
import { TaskList } from "@/components/coordination/follow-up-workspace";
import { QuietEmpty, StatusPill } from "@/components/coordination/primitives";
import { ResourceView } from "@/components/programmes/resource-state";
import { PageHeader } from "@/components/ui/page-header";
import { Plate } from "@/components/ui/plate";
import { KpiCard } from "@/components/ui/figure";
import { buttonClass } from "@/components/ui/button-styles";
import { LoadingState } from "@/components/ui/loading-state";

/** "/" is each role's home; navigation and the backend decide what else each role reaches. */
export function RoleHome() {
  const { role } = useAuth();
  if (role === "SYSTEM_ADMIN") return <AdminOverview />;
  if (role === "CARE_COORDINATOR") return <CoordinatorHome />;
  if (role === "CLINICIAN") return <ClinicianHome />;
  return (
    <RequirePermission anyOf={["insights.read"]} workspace="The Population workspace">
      <PopulationWorkspace />
    </RequirePermission>
  );
}

function useMe() {
  const { state, scope } = useAuth();
  const me = state.status === "signed_in" ? state.me : null;
  return { userId: me?.user.user_id ?? "", scope };
}

function ViewAll({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className={buttonClass("quiet", "h-7 px-0 text-[13px]")}>
      {children} <ArrowRight size={13} aria-hidden="true" />
    </Link>
  );
}

function num<T>(r: Resource<T>, pick: (d: T) => number): number | string {
  return r.status === "ready" ? pick(r.data) : r.status === "loading" ? "…" : "—";
}

function CoordinatorHome() {
  const { userId, scope } = useMe();
  const today = useMemo(() => isoDate(new Date()), []);
  const now = useMemo(() => new Date().toISOString(), []);
  const [attempt, setAttempt] = useState(0);
  const retry = () => setAttempt((n) => n + 1);
  const mine = { assigned_to: userId || undefined };
  const summary = useTaskSummary(mine, attempt);
  const tasks = useTaskPage({ ...mine, active: true }, 1, attempt);
  const requests = useRequestPage({ status: "submitted" }, 1, attempt, 6);
  const appts = useAppointmentPage({ status_group: "active", scheduled_from: now, order: "asc" }, 1, attempt, 6);
  const team = useCareTeam();
  const rules = useRulesIndex();

  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="Care coordination"
        title="My worklist"
        subtitle="Follow-ups assigned to you, new patient requests and upcoming appointments for your patients."
        meta={<span>{scopeLabel(scope)} · as of {today}</span>}
        actions={
          <Link href="/follow-up" className={buttonClass("primary")}>
            Open follow-up queue <ArrowRight size={15} aria-hidden="true" />
          </Link>
        }
      />
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        <KpiCard label="Assigned to me" value={num(summary, (d) => d.active)} note="active follow-ups" i={0} />
        <KpiCard label="Overdue" value={num(summary, (d) => d.overdue)} note="past due, still open" i={1} />
        <KpiCard label="Due this week" value={num(summary, (d) => d.due_soon)} note="today included" i={2} />
        <KpiCard
          label="Patient replied"
          value={num(summary, (d) => d.by_status.patient_responded ?? 0)}
          note="waiting for you"
          i={3}
        />
        <KpiCard label="New requests" value={num(requests, (d) => d.total)} note="submitted by patients" i={4} />
      </dl>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Plate title="My active follow-ups" description="Ordered by due date." actions={<ViewAll href="/follow-up">All follow-ups</ViewAll>}>
          <ResourceView resource={tasks} what="Follow-ups" onRetry={retry} loading={<LoadingState rows={5} />}>
            {(p) =>
              p.items.length === 0 ? (
                <QuietEmpty title="Nothing assigned to you">New follow-ups assigned to you appear here.</QuietEmpty>
              ) : (
                <TaskList
                  tasks={p.items.slice(0, 8)}
                  team={team.status === "ready" ? team.data : null}
                  rules={rules.status === "ready" ? rules.data : null}
                  today={today}
                />
              )
            }
          </ResourceView>
        </Plate>
        <div className="flex flex-col gap-4">
          <Plate title="New patient requests" actions={<ViewAll href="/appointments">Handle</ViewAll>} flush>
            <ResourceView resource={requests} what="Patient requests" onRetry={retry}>
              {(p) =>
                p.items.length === 0 ? (
                  <p className="flex items-center gap-2 px-5 py-4 text-sm text-muted">
                    <Inbox size={15} aria-hidden="true" /> No new requests.
                  </p>
                ) : (
                  <ul className="divide-y divide-border">
                    {p.items.map((r) => (
                      <li key={r.request_id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                        <span className="min-w-0">
                          <span className="block text-foreground">{REQUEST_TYPE_LABELS[r.request_type]}</span>
                          <span className="font-mono text-xs text-faint">{r.patient_id}</span>
                        </span>
                        <StatusPill tone={REQUEST_STATUS_META[r.status].tone} label={REQUEST_STATUS_META[r.status].label} />
                      </li>
                    ))}
                  </ul>
                )
              }
            </ResourceView>
          </Plate>
          <UpcomingAppointments resource={appts} onRetry={retry} />
        </div>
      </div>
    </div>
  );
}

function UpcomingAppointments({ resource, onRetry }: { resource: ReturnType<typeof useAppointmentPage>; onRetry: () => void }) {
  return (
    <Plate title="Upcoming appointments" actions={<ViewAll href="/appointments">Calendar</ViewAll>} flush>
      <ResourceView resource={resource} what="Appointments" onRetry={onRetry}>
        {(p) =>
          p.items.length === 0 ? (
            <p className="flex items-center gap-2 px-5 py-4 text-sm text-muted">
              <CalendarClock size={15} aria-hidden="true" /> No upcoming appointments.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {p.items.map((a) => (
                <li key={a.appointment_id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                  <span className="min-w-0">
                    <span className="block text-foreground">{formatDateTime(a.scheduled_datetime)}</span>
                    <span className="text-xs text-faint">
                      <span className="font-mono">{a.patient_id}</span> · {APPOINTMENT_TYPE_LABELS[a.appointment_type] ?? a.appointment_type}
                    </span>
                  </span>
                  <StatusPill tone={APPOINTMENT_STATUS_META[a.status].tone} label={APPOINTMENT_STATUS_META[a.status].label} />
                </li>
              ))}
            </ul>
          )
        }
      </ResourceView>
    </Plate>
  );
}

function ClinicianHome() {
  const { userId, scope } = useMe();
  const now = useMemo(() => new Date().toISOString(), []);
  const today = useMemo(() => isoDate(new Date()), []);
  const [attempt, setAttempt] = useState(0);
  const retry = () => setAttempt((n) => n + 1);
  const version = useCoordinationVersion();
  const key = `${userId}|${attempt}|${version}`;
  const total = useResource(`clin-total|${key}`, "patients.read_assigned", (s) => api.patientsTotal({}, s), attempt);
  const withGaps = useResource(
    `clin-gaps|${key}`,
    "patients.read_assigned",
    (s) => api.patientsPage({ has_open_care_gaps: true, sort_by: "open_gaps", sort_dir: "desc", limit: 10, offset: 0 }, s),
    attempt
  );
  const summary = useTaskSummary({}, attempt);
  const appts = useAppointmentPage({ status_group: "active", scheduled_from: now, order: "asc" }, 1, attempt, 6);

  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="Clinical care"
        title="My patients"
        subtitle="Your assigned patients with open preventive-care gaps, their follow-ups and upcoming visits."
        meta={<span>{scopeLabel(scope)}</span>}
        actions={
          <Link href="/people" className={buttonClass("primary")}>
            Patient list <ArrowRight size={15} aria-hidden="true" />
          </Link>
        }
      />
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KpiCard label="Assigned patients" value={num(total, (d) => d)} note="in your care scope" i={0} />
        <KpiCard label="With an open care gap" value={num(withGaps, (d) => d.total)} note="documented, evidence-backed" i={1} />
        <KpiCard label="Active follow-ups" value={num(summary, (d) => d.active)} note="for your patients" i={2} />
        <KpiCard label="Overdue follow-ups" value={num(summary, (d) => d.overdue)} note="past due, still open" i={3} />
      </dl>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Plate
          title="Patients with open care gaps"
          description="Most open gaps first. Open a profile to see the evidence and document completion."
          actions={<ViewAll href="/people?has_open_care_gaps=true&sort=open_gaps">All</ViewAll>}
          flush
        >
          <ResourceView resource={withGaps} what="Patients" onRetry={retry} loading={<div className="p-5"><LoadingState rows={5} /></div>}>
            {(p) =>
              p.items.length === 0 ? (
                <div className="p-5">
                  <QuietEmpty title="No open care gaps">None of your assigned patients has an open documented gap.</QuietEmpty>
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted">
                    <tr className="border-b border-border">
                      <th className="px-5 py-2.5 font-medium">Patient</th>
                      <th className="px-3 py-2.5 font-medium">Age · sex</th>
                      <th className="hidden px-3 py-2.5 font-medium sm:table-cell">Region</th>
                      <th className="px-5 py-2.5 text-right font-medium">Open gaps</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {p.items.map((pt) => (
                      <tr key={pt.patient_id} className="transition-colors hover:bg-hover">
                        <td className="px-5 py-2.5">
                          <Link href={`/people/${encodeURIComponent(pt.patient_id)}`} className="font-mono text-accent hover:underline">
                            {pt.patient_id}
                          </Link>
                        </td>
                        <td className="px-3 py-2.5 text-muted">
                          {ageLabel(pt.date_of_birth, today)} · {sexLabel(pt.sex)}
                        </td>
                        <td className="hidden px-3 py-2.5 text-muted sm:table-cell">{regionLabel(pt.region_id)}</td>
                        <td className="px-5 py-2.5 text-right font-semibold tabular-nums text-foreground">{pt.open_care_gaps_count ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            }
          </ResourceView>
        </Plate>
        <UpcomingAppointments resource={appts} onRetry={retry} />
      </div>
    </div>
  );
}
