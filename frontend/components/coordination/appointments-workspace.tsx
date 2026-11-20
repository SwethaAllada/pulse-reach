"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { CalendarClock, ChevronDown, EyeOff, Info, MonitorSmartphone, Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import type {
  AppointmentOut,
  AppointmentQuery,
  AppointmentStatus,
  ReferralOut,
  ReferralStatus,
  RequestQuery,
  RequestStatus,
  RequestType,
  ServiceProfileOut,
  StaffPatientRequestOut,
} from "@/lib/api/types";
import { scopeLabel, useAuth } from "@/lib/auth/auth-context";
import {
  APPOINTMENT_STATUS_META,
  APPOINTMENT_STATUS_ORDER,
  APPOINTMENT_TRANSITIONS,
  APPOINTMENT_TYPE_LABELS,
  REFERRAL_STATUS_META,
  REFERRAL_TRANSITIONS,
  REQUEST_STATUS_META,
  REQUEST_TRANSITIONS,
  REQUEST_TYPE_LABELS,
  formatDate,
  formatDateTime,
  isoDate,
  memberName,
} from "@/lib/coordination/model";
import {
  TASK_PAGE_SIZE,
  useAppointmentCounts,
  useAppointmentPage,
  useCareTeam,
  useMutation,
  useReferralPage,
  useRequestPage,
  useServiceProfiles,
  useWorkflowHistory,
} from "@/lib/coordination/use-coordination";
import { PageHeader } from "@/components/ui/page-header";
import { Plate, Footnote } from "@/components/ui/plate";
import { Figure } from "@/components/ui/figure";
import { Segmented } from "@/components/ui/segmented";
import { buttonClass } from "@/components/ui/button-styles";
import { LoadingState } from "@/components/ui/loading-state";
import { PermissionNotice } from "@/components/ui/permission-notice";
import { ResourceView } from "@/components/programmes/resource-state";
import { ScheduleForm, profileLabel } from "./schedule-form";
import { Confirmation, DistributionBand, FormError, Pager, QuietEmpty, StatusPill, inputClass, labelClass, textareaClass } from "./primitives";
import { cn } from "@/lib/cn";

type Tab = "requests" | "appointments" | "referrals";

export function AppointmentsWorkspace() {
  const { can, scope, state: auth } = useAuth();
  const tabs = useMemo(
    () =>
      [
        can("patient_requests.manage") && { value: "requests" as const, label: "Patient requests" },
        can("appointments.read") && { value: "appointments" as const, label: "Appointments" },
        can("referrals.read") && { value: "referrals" as const, label: "Referrals" },
      ].filter(Boolean) as { value: Tab; label: string }[],
    [can]
  );
  // Permissions may arrive after the first render: fall back to the first tab the role can use.
  const [picked, setTab] = useState<Tab | null>(null);
  const tab = picked && tabs.some((t) => t.value === picked) ? picked : (tabs[0]?.value ?? "appointments");
  const [attempt, setAttempt] = useState(0);
  // Fixed for the view's lifetime (whole minute) so count and list queries share one cut-off.
  const [now] = useState(() => {
    const d = new Date();
    d.setUTCSeconds(0, 0);
    return d.toISOString();
  });
  const counts = useAppointmentCounts({}, now, attempt);
  const retry = () => setAttempt((n) => n + 1);

  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="Coordinate"
        title="Appointments & Referrals"
        subtitle="Patient requests, recorded appointments and referrals for people identified by the population rules."
        breadcrumbs={[{ label: "Appointments & Referrals" }]}
        meta={auth.status === "signed_in" ? <span>Scope: {scopeLabel(scope)}</span> : undefined}
        className="mb-6"
      />

      <p className="reveal mb-8 flex items-start gap-2 rounded-xl border border-dashed border-border-strong px-4 py-3 text-sm text-muted">
        <Info size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-status-info" />
        PulseReach has no facility availability or booking integration. Appointments here are recorded for coordination against simulated service profiles —
        they are not confirmed with a provider, and attendance alone never closes a care gap.
      </p>

      {can("appointments.read") && (
        <ResourceView
          resource={counts}
          what="Appointment counts"
          onRetry={retry}
          loading={<div aria-busy="true" aria-label="Loading appointment counts" className="skeleton h-52 rounded-xl" />}
        >
          {(c) => (
            <section aria-label="Appointments overview" className="reveal relative overflow-hidden rounded-xl border border-border bg-surface-raised p-6 text-ink-text sm:p-8">
              <div className="relative grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <dl className="grid grid-cols-2 gap-6 sm:grid-cols-3">
                  <Figure tone="plate" size="xl" className="col-span-2 sm:col-span-3" label="Upcoming appointments" value={c.upcoming} note="recorded or rescheduled, from now on" />
                  <Figure tone="plate" size="md" label="Pending requests" value={c.pendingRequests ?? "—"} note={c.pendingRequests === null ? "needs patient_requests.manage" : "new or acknowledged"} />
                  <Figure tone="plate" size="md" label="Attended" value={c.attended} note="attendance recorded" />
                  <Figure tone="plate" size="md" label="Awaiting outcome" value={<span className={c.pastUnresolved > 0 ? "text-ink-due" : undefined}>{c.pastUnresolved}</span>} note="time passed, status not updated" />
                </dl>
                <div>
                  <p className="mb-3 text-xs font-medium text-ink-faint">All appointments by status</p>
                  <DistributionBand
                    surface="ink"
                    label="Appointments by status"
                    parts={APPOINTMENT_STATUS_ORDER.map((s) => ({ key: s, label: APPOINTMENT_STATUS_META[s].label, count: c.byStatus[s] ?? 0, tone: APPOINTMENT_STATUS_META[s].tone }))}
                  />
                  <p className="mt-4 text-xs text-ink-muted">{c.cancelled} cancelled by the patient or the facility · {c.noShow} not attended.</p>
                </div>
              </div>
              <Footnote className="relative text-ink-faint">Exact totals from the appointments API for your scope.</Footnote>
            </section>
          )}
        </ResourceView>
      )}

      <div className="mt-12">
        {tabs.length === 0 ? (
          <PermissionNotice title="Appointments and referrals are not available for your role" permission="appointments.read or referrals.read" />
        ) : (
          <>
            {tabs.length > 1 && (
              <div className="mb-8 overflow-x-auto">
                <Segmented label="Coordination view" options={tabs} value={tab} onChange={setTab} className="min-w-max" />
              </div>
            )}
            <div key={tab}>
              {tab === "requests" && <RequestsPanel now={now} />}
              {tab === "appointments" && <AppointmentsPanel now={now} />}
              {tab === "referrals" && <ReferralsPanel />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ── Patient requests ────────────────────────────────────────────────────────── */

function RequestsPanel({ now }: { now: string }) {
  const [status, setStatus] = useState<RequestStatus | "">("submitted");
  const [type, setType] = useState<RequestType | "">("");
  const [patient, setPatient] = useState("");
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const query: RequestQuery = { status: status || undefined, request_type: type || undefined, patient_id: patient.trim() || undefined };
  const requests = useRequestPage(query, page, attempt);
  const team = useCareTeam();
  const teamMap = team.status === "ready" ? team.data : null;
  return (
    <Plate eyebrow="Requests" title="Patient requests" description="Appointment, help and change requests patients submitted in the portal. Replies you mark as visible appear in their portal; internal notes never do.">
      <div role="search" aria-label="Request filters" className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className={labelClass}>
          Status
          <select className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value as RequestStatus | ""); setPage(1); }}>
            <option value="">All statuses</option>
            {(Object.keys(REQUEST_STATUS_META) as RequestStatus[]).map((s) => (
              <option key={s} value={s}>
                {REQUEST_STATUS_META[s].label}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          Type
          <select className={inputClass} value={type} onChange={(e) => { setType(e.target.value as RequestType | ""); setPage(1); }}>
            <option value="">All types</option>
            {(Object.keys(REQUEST_TYPE_LABELS) as RequestType[]).map((t) => (
              <option key={t} value={t}>
                {REQUEST_TYPE_LABELS[t]}
              </option>
            ))}
          </select>
        </label>
        <PatientFilter value={patient} onChange={(v) => { setPatient(v); setPage(1); }} />
      </div>
      <ResourceView resource={requests} what="Patient requests" onRetry={() => setAttempt((n) => n + 1)} loading={<LoadingState rows={4} label="Loading patient requests" />}>
        {(p) =>
          p.items.length === 0 ? (
            <QuietEmpty title="No requests match">{status === "submitted" ? "No new requests are waiting." : "Try another status."}</QuietEmpty>
          ) : (
            <>
              <ul aria-label="Patient requests" className="flex flex-col divide-y divide-border border-y border-border">
                {p.items.map((r) => (
                  <RequestRow key={r.request_id} request={r} handledBy={memberName(teamMap, r.handled_by_user_id)} now={now} />
                ))}
              </ul>
              <Pager page={page} total={p.total} size={TASK_PAGE_SIZE} onPage={setPage} label="Request" />
            </>
          )
        }
      </ResourceView>
    </Plate>
  );
}

function RequestRow({ request: r, handledBy, now }: { request: StaffPatientRequestOut; handledBy: string; now: string }) {
  const [open, setOpen] = useState(false);
  const meta = REQUEST_STATUS_META[r.status];
  return (
    <li>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 px-1 py-3.5 text-left hover:bg-surface-raised">
        <span className="min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono text-sm text-foreground">{r.patient_id}</span>
            <span className="text-sm text-foreground">{REQUEST_TYPE_LABELS[r.request_type] ?? r.request_type}</span>
            {r.change_action && <span className="text-xs text-muted">({r.change_action})</span>}
          </span>
          <span className="mt-1 block text-xs text-muted">
            Submitted {formatDateTime(r.created_at)}
            {r.preferred_dates.length > 0 && ` · prefers ${r.preferred_dates.map((d) => formatDate(d)).join(", ")}`}
            {r.preferred_time_of_day && ` · ${r.preferred_time_of_day}`}
          </span>
        </span>
        <StatusPill tone={meta.tone} label={meta.label} />
        <ChevronDown size={16} aria-hidden="true" className={cn("text-faint transition-transform duration-200", open && "rotate-180")} />
      </button>
      {open && <RequestDetail request={r} handledBy={handledBy} now={now} />}
    </li>
  );
}

function RequestDetail({ request: r, handledBy, now }: { request: StaffPatientRequestOut; handledBy: string; now: string }) {
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");
  const [scheduling, setScheduling] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const { can } = useAuth();
  const { run, pending, error } = useMutation();
  const next = REQUEST_TRANSITIONS[r.status];
  const act = async (status: (typeof next)[number] | undefined, appointmentId?: string) => {
    setDone(null);
    const out = await run(() =>
      api.updatePatientRequest(r.request_id, {
        ...(status ? { status } : {}),
        ...(reply.trim() ? { staff_response: reply.trim() } : {}),
        ...(note.trim() ? { internal_note: note.trim() } : {}),
        ...(appointmentId ? { appointment_id: appointmentId } : {}),
      })
    );
    if (out) {
      setDone(status ? `Request marked “${REQUEST_STATUS_META[status].label}”.` : "Reply saved.");
      setReply("");
      setNote("");
      setScheduling(false);
    }
  };
  const canSchedule = can("appointments.create") && r.request_type === "appointment" && next.includes("scheduled");
  return (
    <div className="reveal grid grid-cols-1 gap-6 px-1 pb-6 pt-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-4 text-sm">
        <div>
          <p className="text-[11px] uppercase tracking-[0.08em] text-faint">Patient’s message</p>
          <p className="mt-1 whitespace-pre-wrap text-foreground" dir={r.language === "ar" ? "rtl" : "ltr"} lang={r.language}>
            {r.message ?? <span className="text-muted">No message.</span>}
          </p>
        </div>
        {r.staff_response && (
          <div>
            <p className="flex items-center gap-1 text-[11px] uppercase tracking-[0.08em] text-faint">
              <MonitorSmartphone size={11} aria-hidden="true" /> Reply visible to patient
            </p>
            <p className="mt-1 text-foreground">{r.staff_response}</p>
          </div>
        )}
        {r.internal_note && (
          <div className="rounded-xl bg-surface-sunken p-3">
            <p className="flex items-center gap-1 text-[11px] uppercase tracking-[0.08em] text-faint">
              <EyeOff size={11} aria-hidden="true" /> Internal note
            </p>
            <p className="mt-1 text-foreground">{r.internal_note}</p>
          </div>
        )}
        <dl className="grid grid-cols-2 gap-3 text-xs">
          <div>
            <dt className="text-faint">Linked follow-up</dt>
            <dd className="mt-0.5">
              {r.task_id ? (
                <Link className="text-accent underline-offset-4 hover:underline" href={`/follow-up/${encodeURIComponent(r.task_id)}`}>
                  Open follow-up
                </Link>
              ) : (
                "—"
              )}
            </dd>
          </div>
          <div>
            <dt className="text-faint">Appointment</dt>
            <dd className="mt-0.5 font-mono">{r.appointment_id ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-faint">Care gap</dt>
            <dd className="mt-0.5 font-mono">{r.care_gap_id ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-faint">Last handled by</dt>
            <dd className="mt-0.5">{r.handled_by_user_id ? handledBy : "—"}</dd>
          </div>
        </dl>
      </div>

      {next.length === 0 ? (
        <p className="text-sm text-muted">This request is closed; its history is kept.</p>
      ) : scheduling ? (
        <div className="flex flex-col gap-3">
          <ScheduleForm
            patientId={r.patient_id}
            careGapId={r.care_gap_id}
            suggestedDate={r.preferred_dates[0] ?? isoDate(new Date(now))}
            submitLabel="Record appointment and update request"
            onCancel={() => setScheduling(false)}
            onCreated={(a) => act("scheduled", a.appointment_id)}
          />
          {error && <FormError message={`The appointment was recorded, but the request was not updated: ${error}`} />}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <label className={labelClass}>
            <span className="flex items-center gap-1.5"><MonitorSmartphone size={12} aria-hidden="true" /> Reply to the patient (shown in the portal)</span>
            <textarea className={textareaClass} value={reply} maxLength={2000} onChange={(e) => setReply(e.target.value)} placeholder="e.g. We need your preferred clinic — please reply in the portal." />
          </label>
          <label className={labelClass}>
            <span className="flex items-center gap-1.5"><EyeOff size={12} aria-hidden="true" /> Internal note (staff only)</span>
            <input className={inputClass} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="flex flex-wrap gap-2">
            {canSchedule && (
              <button type="button" className={buttonClass("primary")} onClick={() => setScheduling(true)}>
                <CalendarClock size={15} aria-hidden="true" /> Record appointment
              </button>
            )}
            {next.includes("acknowledged") && (
              <button type="button" className={buttonClass("secondary")} disabled={pending} onClick={() => act("acknowledged")}>
                Acknowledge{reply.trim() ? " & reply" : ""}
              </button>
            )}
            {!next.includes("acknowledged") && (reply.trim() || note.trim()) && (
              <button type="button" className={buttonClass("secondary")} disabled={pending} onClick={() => act(undefined)}>
                Save reply
              </button>
            )}
            {next.includes("declined") && (
              <button type="button" className={buttonClass("secondary")} disabled={pending} onClick={() => act("declined")}>
                Decline
              </button>
            )}
            {next.includes("closed") && (
              <button type="button" className={buttonClass("quiet")} disabled={pending} onClick={() => act("closed")}>
                Close
              </button>
            )}
          </div>
          <p className="text-xs text-faint">To ask the patient for more information, acknowledge the request with a reply; it appears in their portal.</p>
          <FormError message={error} />
          {done && <Confirmation>{done}</Confirmation>}
        </div>
      )}
    </div>
  );
}

function PatientFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [draft, setDraft] = useState(value);
  return (
    <label className={labelClass}>
      Person ID
      <input
        className={`${inputClass} font-mono`}
        value={draft}
        placeholder="Exact synthetic ID"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => onChange(draft)}
        onKeyDown={(e) => e.key === "Enter" && onChange(draft)}
        autoComplete="off"
      />
    </label>
  );
}

/* ── Appointments ────────────────────────────────────────────────────────────── */

type When = "upcoming" | "past" | "all";

function AppointmentsPanel({ now }: { now: string }) {
  const { can } = useAuth();
  const [when, setWhen] = useState<When>("upcoming");
  const [status, setStatus] = useState<AppointmentStatus | "">("");
  const [profile, setProfile] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [patient, setPatient] = useState("");
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const profiles = useServiceProfiles();
  const profileMap = useMemo(() => new Map((profiles.status === "ready" ? profiles.data.items : []).map((p) => [p.profile_id, p])), [profiles]);
  const query: AppointmentQuery = {
    status: status || undefined,
    status_group: when === "upcoming" && !status ? "active" : undefined,
    profile_id: profile || undefined,
    patient_id: patient.trim() || undefined,
    scheduled_from: from ? `${from}T00:00:00Z` : when === "upcoming" ? now : undefined,
    scheduled_to: to ? `${to}T23:59:59Z` : when === "past" ? now : undefined,
    order: when === "upcoming" ? "asc" : "desc",
  };
  const appointments = useAppointmentPage(query, page, attempt);
  const reset = (fn: () => void) => {
    fn();
    setPage(1);
  };

  return (
    <Plate
      eyebrow="Appointments"
      title={when === "upcoming" ? "Upcoming appointments" : when === "past" ? "Past appointments" : "All appointments"}
      description="Record attendance, reschedule or cancel. Every change is kept in the appointment history."
      actions={
        can("appointments.create") && !creating ? (
          <button type="button" className={buttonClass("primary")} onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden="true" /> Record appointment
          </button>
        ) : undefined
      }
    >
      {creating && (
        <div className="mb-8">
          <ScheduleForm onCancel={() => setCreating(false)} onCreated={() => setCreating(false)} suggestedDate={isoDate(new Date(now))} />
        </div>
      )}
      <div role="search" aria-label="Appointment filters" className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <div className={`${labelClass} col-span-2 md:col-span-3 lg:col-span-2`}>
          When
          <Segmented label="When" options={[{ value: "upcoming", label: "Upcoming" }, { value: "past", label: "Past" }, { value: "all", label: "All" }]} value={when} onChange={(v) => reset(() => setWhen(v))} className="w-full" />
        </div>
        <label className={labelClass}>
          Status
          <select className={inputClass} value={status} onChange={(e) => reset(() => setStatus(e.target.value as AppointmentStatus | ""))}>
            <option value="">{when === "upcoming" ? "Recorded or rescheduled" : "Any status"}</option>
            {APPOINTMENT_STATUS_ORDER.map((s) => (
              <option key={s} value={s}>
                {APPOINTMENT_STATUS_META[s].label}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          Facility
          <select className={inputClass} value={profile} onChange={(e) => reset(() => setProfile(e.target.value))}>
            <option value="">All facilities</option>
            {[...profileMap.values()].map((p) => (
              <option key={p.profile_id} value={p.profile_id}>
                {profileLabel(p, p.profile_id)}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          From
          <input type="date" className={inputClass} value={from} onChange={(e) => reset(() => setFrom(e.target.value))} />
        </label>
        <label className={labelClass}>
          To
          <input type="date" className={inputClass} value={to} onChange={(e) => reset(() => setTo(e.target.value))} />
        </label>
        <div className="col-span-2 md:col-span-1">
          <PatientFilter value={patient} onChange={(v) => reset(() => setPatient(v))} />
        </div>
      </div>
      <p className="mb-4 text-xs text-faint">Programme and assigned-staff filters are not available: appointments carry neither in the API.</p>
      <ResourceView resource={appointments} what="Appointments" onRetry={() => setAttempt((n) => n + 1)} loading={<LoadingState rows={4} label="Loading appointments" />}>
        {(p) =>
          p.items.length === 0 ? (
            <QuietEmpty title="No appointments match">{when === "upcoming" ? "No upcoming appointment is recorded in your scope." : "Try other filters."}</QuietEmpty>
          ) : (
            <>
              <ul aria-label="Appointments" className="flex flex-col divide-y divide-border border-y border-border">
                {p.items.map((a) => (
                  <AppointmentRow key={a.appointment_id} appointment={a} profile={profileMap.get(a.profile_id)} now={now} />
                ))}
              </ul>
              <Pager page={page} total={p.total} size={TASK_PAGE_SIZE} onPage={setPage} label="Appointment" />
            </>
          )
        }
      </ResourceView>
    </Plate>
  );
}

function AppointmentRow({ appointment: a, profile, now }: { appointment: AppointmentOut; profile: ServiceProfileOut | undefined; now: string }) {
  const [open, setOpen] = useState(false);
  const meta = APPOINTMENT_STATUS_META[a.status] ?? { label: a.status, tone: "eligible" as const };
  const overdue = (a.status === "scheduled" || a.status === "rescheduled") && a.scheduled_datetime < now;
  return (
    <li>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 px-1 py-3.5 text-left hover:bg-surface-raised sm:grid-cols-[170px_minmax(0,1fr)_auto_auto]">
        <span className="text-sm tabular-nums text-foreground">{formatDateTime(a.scheduled_datetime)}</span>
        <span className="min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono text-sm text-foreground">{a.patient_id}</span>
            <span className="text-sm text-foreground">{APPOINTMENT_TYPE_LABELS[a.appointment_type] ?? a.appointment_type}</span>
          </span>
          <span className="mt-1 block truncate text-xs text-muted">
            {profileLabel(profile, a.profile_id)} · {a.slot_type}
            {overdue && <span className="text-status-due"> · outcome not recorded</span>}
          </span>
        </span>
        <StatusPill tone={meta.tone} label={meta.label} />
        <ChevronDown size={16} aria-hidden="true" className={cn("text-faint transition-transform duration-200", open && "rotate-180")} />
      </button>
      {open && <AppointmentDetail appointment={a} />}
    </li>
  );
}

function AppointmentDetail({ appointment: a }: { appointment: AppointmentOut }) {
  const { can } = useAuth();
  const history = useWorkflowHistory("appointment", a.appointment_id);
  const [status, setStatus] = useState<AppointmentStatus | "">("");
  const [when, setWhen] = useState("");
  const [note, setNote] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const { run, pending, error } = useMutation();
  const next = APPOINTMENT_TRANSITIONS[a.status] ?? [];
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!status) return;
    setDone(null);
    const out = await run(() =>
      api.updateAppointment(a.appointment_id, {
        status,
        ...(status === "rescheduled" ? { scheduled_datetime: new Date(`${when}:00Z`).toISOString() } : {}),
        note: note.trim() || null,
      })
    );
    if (out) {
      setDone(`Appointment marked “${APPOINTMENT_STATUS_META[status].label}”.`);
      setStatus("");
      setNote("");
    }
  };
  return (
    <div className="reveal grid grid-cols-1 gap-6 px-1 pb-6 pt-1 lg:grid-cols-2">
      <div>
        <p className="mb-2 text-[11px] uppercase tracking-[0.08em] text-faint">History</p>
        {history && <WorkflowTimeline history={history} />}
        <p className="mt-3 text-xs text-faint">
          Booked via {a.booked_via.replace(/_/g, " ")}
          {a.care_gap_id && (
            <>
              {" "}· care gap <span className="font-mono">{a.care_gap_id}</span>
            </>
          )}
          {" "}·{" "}
          <Link className="text-accent underline-offset-4 hover:underline" href={`/people/${encodeURIComponent(a.patient_id)}#coordination`}>
            Patient profile
          </Link>
        </p>
      </div>
      {!can("appointments.update") ? (
        <PermissionNotice title="Updating appointments is not available for your role" permission="appointments.update" />
      ) : next.length === 0 ? (
        <p className="text-sm text-muted">This appointment is final ({APPOINTMENT_STATUS_META[a.status]?.label.toLowerCase()}). Its history is kept.</p>
      ) : (
        <form onSubmit={submit} aria-label="Update appointment" className="flex flex-col gap-3">
          <label className={labelClass}>
            New status
            <select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value as AppointmentStatus)}>
              <option value="">Choose…</option>
              {next.map((s) => (
                <option key={s} value={s}>
                  {s === "rescheduled" ? "Reschedule" : APPOINTMENT_STATUS_META[s].label}
                </option>
              ))}
            </select>
          </label>
          {status === "rescheduled" && (
            <label className={labelClass}>
              New date and time (UTC)
              <input type="datetime-local" className={inputClass} required value={when} onChange={(e) => setWhen(e.target.value)} />
            </label>
          )}
          <label className={labelClass}>
            Note (staff history)
            <input className={inputClass} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </label>
          {status === "attended" && <p className="text-xs text-faint">Attendance does not close the care gap; document the completed record on the follow-up.</p>}
          <FormError message={error} />
          {done && <Confirmation>{done}</Confirmation>}
          <div>
            <button type="submit" className={buttonClass("primary")} disabled={pending || !status || (status === "rescheduled" && !when)}>
              {pending ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function WorkflowTimeline({ history }: { history: NonNullable<ReturnType<typeof useWorkflowHistory>> }) {
  return (
    <ResourceView resource={history} what="History">
      {(h) =>
        h.items.length === 0 ? (
          <p className="text-sm text-muted">No status changes recorded through PulseReach (seeded record).</p>
        ) : (
          <ol className="flex flex-col gap-2 border-l border-border pl-4">
            {h.items.map((e) => {
              const label =
                e.entity_type === "appointment"
                  ? APPOINTMENT_STATUS_META[e.to_status as AppointmentStatus]?.label ?? e.to_status
                  : REFERRAL_STATUS_META[e.to_status as ReferralStatus]?.label ?? e.to_status;
              return (
                <li key={e.status_event_id} className="text-sm">
                  <span className="text-foreground">{e.from_status ? `→ ${label}` : `Created · ${label}`}</span>
                  {e.scheduled_datetime && e.entity_type === "appointment" && <span className="text-muted"> · {formatDateTime(e.scheduled_datetime)}</span>}
                  {e.note && <span className="block text-xs text-muted">{e.note}</span>}
                  <span className="block text-[11px] text-faint">{formatDateTime(e.recorded_at)}</span>
                </li>
              );
            })}
          </ol>
        )
      }
    </ResourceView>
  );
}

/* ── Referrals ───────────────────────────────────────────────────────────────── */

function ReferralsPanel() {
  const [status, setStatus] = useState<ReferralStatus | "">("");
  const [patient, setPatient] = useState("");
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const referrals = useReferralPage({ status: status || undefined, patient_id: patient.trim() || undefined }, page, attempt);
  return (
    <Plate eyebrow="Referrals" title="Referrals" description="Referral destination and status. A completed referral is evidence only when it is documented as completion on the care gap.">
      <div role="search" aria-label="Referral filters" className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className={labelClass}>
          Status
          <select className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value as ReferralStatus | ""); setPage(1); }}>
            <option value="">All statuses</option>
            {(Object.keys(REFERRAL_STATUS_META) as ReferralStatus[]).map((s) => (
              <option key={s} value={s}>
                {REFERRAL_STATUS_META[s].label}
              </option>
            ))}
          </select>
        </label>
        <PatientFilter value={patient} onChange={(v) => { setPatient(v); setPage(1); }} />
      </div>
      <ResourceView resource={referrals} what="Referrals" onRetry={() => setAttempt((n) => n + 1)} loading={<LoadingState rows={4} label="Loading referrals" />}>
        {(p) =>
          p.items.length === 0 ? (
            <QuietEmpty title="No referrals match" />
          ) : (
            <>
              <ul aria-label="Referrals" className="flex flex-col divide-y divide-border border-y border-border">
                {p.items.map((r) => (
                  <ReferralRow key={r.referral_id} referral={r} />
                ))}
              </ul>
              <Pager page={page} total={p.total} size={TASK_PAGE_SIZE} onPage={setPage} label="Referral" />
            </>
          )
        }
      </ResourceView>
    </Plate>
  );
}

export function ReferralRow({ referral: r }: { referral: ReferralOut }) {
  const [open, setOpen] = useState(false);
  const meta = REFERRAL_STATUS_META[r.status];
  return (
    <li>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 px-1 py-3.5 text-left hover:bg-surface-raised">
        <span className="min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono text-sm text-foreground">{r.patient_id}</span>
            <span className="text-sm text-foreground">to {r.referral_target}</span>
          </span>
          <span className="mt-1 block text-xs text-muted">
            <span className="font-mono">{r.referral_id}</span> · triggered by {r.trigger_rule_id} on {formatDate(r.trigger_date)}
            {r.initiated_date && ` · initiated ${formatDate(r.initiated_date)}`}
            {r.completed_date && ` · completed ${formatDate(r.completed_date)}`}
          </span>
        </span>
        <StatusPill tone={meta.tone} label={meta.label} />
        <ChevronDown size={16} aria-hidden="true" className={cn("text-faint transition-transform duration-200", open && "rotate-180")} />
      </button>
      {open && <ReferralDetail referral={r} />}
    </li>
  );
}

function ReferralDetail({ referral: r }: { referral: ReferralOut }) {
  const { can } = useAuth();
  const history = useWorkflowHistory("referral", r.referral_id);
  const [status, setStatus] = useState<ReferralStatus | "">("");
  const [initiated, setInitiated] = useState(r.initiated_date ?? isoDate(new Date()));
  const [completed, setCompleted] = useState(isoDate(new Date()));
  const [note, setNote] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const { run, pending, error } = useMutation();
  const next = REFERRAL_TRANSITIONS[r.status];
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!status) return;
    setDone(null);
    const out = await run(() =>
      api.updateReferral(r.referral_id, {
        status,
        ...(status === "initiated" || status === "completed" ? { initiated_date: initiated } : {}),
        ...(status === "completed" ? { completed_date: completed } : {}),
        note: note.trim() || null,
      })
    );
    if (out) {
      setDone(`Referral marked “${REFERRAL_STATUS_META[status].label}”.`);
      setStatus("");
    }
  };
  return (
    <div className="reveal grid grid-cols-1 gap-6 px-1 pb-6 pt-1 lg:grid-cols-2">
      <div>
        <p className="mb-2 text-[11px] uppercase tracking-[0.08em] text-faint">History</p>
        {history && <WorkflowTimeline history={history} />}
        <p className="mt-3 text-xs text-faint">
          <Link className="text-accent underline-offset-4 hover:underline" href={`/people/${encodeURIComponent(r.patient_id)}#coordination`}>
            Patient profile and linked follow-ups
          </Link>
        </p>
      </div>
      {!can("referrals.update") ? (
        <PermissionNotice title="Updating referrals is not available for your role" permission="referrals.update" />
      ) : next.length === 0 ? (
        <p className="text-sm text-muted">This referral is final. Its history is kept.</p>
      ) : (
        <form onSubmit={submit} aria-label="Update referral" className="flex flex-col gap-3">
          <label className={labelClass}>
            New status
            <select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value as ReferralStatus)}>
              <option value="">Choose…</option>
              {next.map((s) => (
                <option key={s} value={s}>
                  {REFERRAL_STATUS_META[s].label}
                </option>
              ))}
            </select>
          </label>
          {(status === "initiated" || status === "completed") && (
            <label className={labelClass}>
              Initiated on
              <input type="date" className={inputClass} required value={initiated} min={r.trigger_date} onChange={(e) => setInitiated(e.target.value)} />
            </label>
          )}
          {status === "completed" && (
            <label className={labelClass}>
              Completed on
              <input type="date" className={inputClass} required value={completed} min={initiated} onChange={(e) => setCompleted(e.target.value)} />
            </label>
          )}
          <label className={labelClass}>
            Note (staff history)
            <input className={inputClass} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </label>
          <FormError message={error} />
          {done && <Confirmation>{done}</Confirmation>}
          <div>
            <button type="submit" className={buttonClass("primary")} disabled={pending || !status}>
              {pending ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
