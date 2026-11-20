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
  REFERRAL_STATUS_META,
  REFERRAL_TRANSITIONS,
  REQUEST_STATUS_META,
  REQUEST_TRANSITIONS,
  REQUEST_TYPE_LABELS,
  appointmentTypeText,
  formatDate,
  formatDateTime,
  isoDate,
  memberName,
  slotText,
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
import { useLocale } from "@/lib/i18n/use-locale";

type Tab = "requests" | "appointments" | "referrals";

export function AppointmentsWorkspace() {
  const { can, scope, state: auth } = useAuth();
  const { t } = useLocale();
  const tabs = useMemo(
    () =>
      [
        can("patient_requests.manage") && { value: "requests" as const, label: t("coord.appt.tab_requests") },
        can("appointments.read") && { value: "appointments" as const, label: t("coord.appt.tab_appointments") },
        can("referrals.read") && { value: "referrals" as const, label: t("coord.appt.tab_referrals") },
      ].filter(Boolean) as { value: Tab; label: string }[],
    [can, t]
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
        eyebrow={t("coord.appt.eyebrow")}
        title={t("coord.appt.title")}
        subtitle={t("coord.appt.subtitle")}
        breadcrumbs={[{ label: t("coord.appt.title") }]}
        meta={auth.status === "signed_in" ? <span>{t("coord.scope", { scope: scopeLabel(scope, t) })}</span> : undefined}
        className="mb-6"
      />

      <p className="reveal mb-8 flex items-start gap-2 rounded-xl border border-dashed border-border-strong px-4 py-3 text-sm text-muted">
        <Info size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-status-info" />
        {t("coord.appt.notice")}
      </p>

      {can("appointments.read") && (
        <ResourceView
          resource={counts}
          what={t("coord.appt.what_counts")}
          onRetry={retry}
          loading={<div aria-busy="true" aria-label={t("coord.appt.loading_counts")} className="skeleton h-52 rounded-xl" />}
        >
          {(c) => (
            <section aria-label={t("coord.appt.overview")} className="reveal relative overflow-hidden rounded-xl border border-border bg-surface-raised p-6 text-ink-text sm:p-8">
              <div className="relative grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <dl className="grid grid-cols-2 gap-6 sm:grid-cols-3">
                  <Figure tone="plate" size="xl" className="col-span-2 sm:col-span-3" label={t("coord.appt.upcoming")} value={c.upcoming} note={t("coord.appt.upcoming_note")} />
                  <Figure tone="plate" size="md" label={t("coord.appt.pending")} value={c.pendingRequests ?? "—"} note={c.pendingRequests === null ? t("coord.appt.pending_forbidden") : t("coord.appt.pending_note")} />
                  <Figure tone="plate" size="md" label={t("coord.appt.attended")} value={c.attended} note={t("coord.appt.attended_note")} />
                  <Figure tone="plate" size="md" label={t("coord.appt.awaiting")} value={<span className={c.pastUnresolved > 0 ? "text-ink-due" : undefined}>{c.pastUnresolved}</span>} note={t("coord.appt.awaiting_note")} />
                </dl>
                <div>
                  <p className="mb-3 text-xs font-medium text-ink-faint">{t("coord.appt.by_status_heading")}</p>
                  <DistributionBand
                    surface="ink"
                    label={t("coord.appt.by_status")}
                    parts={APPOINTMENT_STATUS_ORDER.map((s) => ({ key: s, label: t(APPOINTMENT_STATUS_META[s].label), count: c.byStatus[s] ?? 0, tone: APPOINTMENT_STATUS_META[s].tone }))}
                  />
                  <p className="mt-4 text-xs text-ink-muted">{t("coord.appt.cancel_line", { cancelled: String(c.cancelled), noShow: String(c.noShow) })}</p>
                </div>
              </div>
              <Footnote className="relative text-ink-faint">{t("coord.appt.footnote")}</Footnote>
            </section>
          )}
        </ResourceView>
      )}

      <div className="mt-12">
        {tabs.length === 0 ? (
          <PermissionNotice title={t("coord.appt.forbidden")} permission="appointments.read or referrals.read" />
        ) : (
          <>
            {tabs.length > 1 && (
              <div className="mb-8 overflow-x-auto">
                <Segmented label={t("coord.appt.view")} options={tabs} value={tab} onChange={setTab} className="min-w-max" />
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
  const { t } = useLocale();
  const query: RequestQuery = { status: status || undefined, request_type: type || undefined, patient_id: patient.trim() || undefined };
  const requests = useRequestPage(query, page, attempt);
  const team = useCareTeam();
  const teamMap = team.status === "ready" ? team.data : null;
  return (
    <Plate eyebrow={t("coord.req.eyebrow")} title={t("coord.appt.tab_requests")} description={t("coord.req.desc")}>
      <div role="search" aria-label={t("coord.req.filters")} className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className={labelClass}>
          {t("coord.status")}
          <select className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value as RequestStatus | ""); setPage(1); }}>
            <option value="">{t("coord.all_statuses")}</option>
            {(Object.keys(REQUEST_STATUS_META) as RequestStatus[]).map((s) => (
              <option key={s} value={s}>
                {t(REQUEST_STATUS_META[s].label)}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          {t("coord.req.type")}
          <select className={inputClass} value={type} onChange={(e) => { setType(e.target.value as RequestType | ""); setPage(1); }}>
            <option value="">{t("coord.req.all_types")}</option>
            {(Object.keys(REQUEST_TYPE_LABELS) as RequestType[]).map((k) => (
              <option key={k} value={k}>
                {t(REQUEST_TYPE_LABELS[k])}
              </option>
            ))}
          </select>
        </label>
        <PatientFilter value={patient} onChange={(v) => { setPatient(v); setPage(1); }} />
      </div>
      <ResourceView resource={requests} what={t("coord.appt.tab_requests")} onRetry={() => setAttempt((n) => n + 1)} loading={<LoadingState rows={4} label={t("coord.req.loading")} />}>
        {(p) =>
          p.items.length === 0 ? (
            <QuietEmpty title={t("coord.req.empty")}>{status === "submitted" ? t("coord.req.empty_new") : t("coord.req.empty_other")}</QuietEmpty>
          ) : (
            <>
              <ul aria-label={t("coord.appt.tab_requests")} className="flex flex-col divide-y divide-border border-y border-border">
                {p.items.map((r) => (
                  <RequestRow key={r.request_id} request={r} handledBy={memberName(teamMap, r.handled_by_user_id, t)} now={now} />
                ))}
              </ul>
              <Pager page={page} total={p.total} size={TASK_PAGE_SIZE} onPage={setPage} label={t("coord.req.pager")} />
            </>
          )
        }
      </ResourceView>
    </Plate>
  );
}

function RequestRow({ request: r, handledBy, now }: { request: StaffPatientRequestOut; handledBy: string; now: string }) {
  const { t, locale } = useLocale();
  const [open, setOpen] = useState(false);
  const meta = REQUEST_STATUS_META[r.status];
  return (
    <li>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 px-1 py-3.5 text-start hover:bg-surface-raised">
        <span className="min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="ltr-value font-mono text-sm text-foreground">{r.patient_id}</span>
            <span className="text-sm text-foreground">{REQUEST_TYPE_LABELS[r.request_type] ? t(REQUEST_TYPE_LABELS[r.request_type]) : r.request_type}</span>
            {r.change_action && <span className="text-xs text-muted">({r.change_action})</span>}
          </span>
          <span className="mt-1 block text-xs text-muted">
            {t("coord.req.submitted", { date: formatDateTime(r.created_at, locale) })}
            {r.preferred_dates.length > 0 && ` · ${t("coord.req.prefers", { dates: r.preferred_dates.map((d) => formatDate(d, locale)).join(t("list.sep")) })}`}
            {r.preferred_time_of_day && ` · ${r.preferred_time_of_day}`}
          </span>
        </span>
        <StatusPill tone={meta.tone} label={t(meta.label)} />
        <ChevronDown size={16} aria-hidden="true" className={cn("text-faint transition-transform duration-200", open && "rotate-180")} />
      </button>
      {open && <RequestDetail request={r} handledBy={handledBy} now={now} />}
    </li>
  );
}

function RequestDetail({ request: r, handledBy, now }: { request: StaffPatientRequestOut; handledBy: string; now: string }) {
  const { t } = useLocale();
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
      setDone(status ? t("coord.req.marked", { status: t(REQUEST_STATUS_META[status].label) }) : t("coord.req.reply_saved"));
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
          <p className="text-[11px] uppercase tracking-[0.08em] text-faint">{t("coord.req.message")}</p>
          <p className="mt-1 whitespace-pre-wrap text-foreground" dir={r.language === "ar" ? "rtl" : "ltr"} lang={r.language}>
            {r.message ?? <span className="text-muted">{t("coord.req.no_message")}</span>}
          </p>
        </div>
        {r.staff_response && (
          <div>
            <p className="flex items-center gap-1 text-[11px] uppercase tracking-[0.08em] text-faint">
              <MonitorSmartphone size={11} aria-hidden="true" /> {t("coord.req.reply_visible")}
            </p>
            <p className="mt-1 text-foreground">{r.staff_response}</p>
          </div>
        )}
        {r.internal_note && (
          <div className="rounded-xl bg-surface-sunken p-3">
            <p className="flex items-center gap-1 text-[11px] uppercase tracking-[0.08em] text-faint">
              <EyeOff size={11} aria-hidden="true" /> {t("coord.internal_note")}
            </p>
            <p className="mt-1 text-foreground">{r.internal_note}</p>
          </div>
        )}
        <dl className="grid grid-cols-2 gap-3 text-xs">
          <div>
            <dt className="text-faint">{t("coord.req.linked_follow_up")}</dt>
            <dd className="mt-0.5">
              {r.task_id ? (
                <Link className="text-accent underline-offset-4 hover:underline" href={`/follow-up/${encodeURIComponent(r.task_id)}`}>
                  {t("coord.req.open_follow_up")}
                </Link>
              ) : (
                "—"
              )}
            </dd>
          </div>
          <div>
            <dt className="text-faint">{t("coord.appointment")}</dt>
            <dd className="ltr-value mt-0.5 font-mono">{r.appointment_id ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-faint">{t("coord.care_gap")}</dt>
            <dd className="ltr-value mt-0.5 font-mono">{r.care_gap_id ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-faint">{t("coord.req.handled_by")}</dt>
            <dd className="mt-0.5">{r.handled_by_user_id ? handledBy : "—"}</dd>
          </div>
        </dl>
      </div>

      {next.length === 0 ? (
        <p className="text-sm text-muted">{t("coord.req.closed")}</p>
      ) : scheduling ? (
        <div className="flex flex-col gap-3">
          <ScheduleForm
            patientId={r.patient_id}
            careGapId={r.care_gap_id}
            suggestedDate={r.preferred_dates[0] ?? isoDate(new Date(now))}
            submitLabel={t("coord.req.record_and_update")}
            onCancel={() => setScheduling(false)}
            onCreated={(a) => act("scheduled", a.appointment_id)}
          />
          {error && <FormError message={t("coord.req.update_failed", { error })} />}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <label className={labelClass}>
            <span className="flex items-center gap-1.5"><MonitorSmartphone size={12} aria-hidden="true" /> {t("coord.req.reply_label")}</span>
            <textarea className={textareaClass} value={reply} maxLength={2000} onChange={(e) => setReply(e.target.value)} placeholder={t("coord.req.reply_placeholder")} />
          </label>
          <label className={labelClass}>
            <span className="flex items-center gap-1.5"><EyeOff size={12} aria-hidden="true" /> {t("coord.internal_note_staff")}</span>
            <input className={inputClass} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="flex flex-wrap gap-2">
            {canSchedule && (
              <button type="button" className={buttonClass("primary")} onClick={() => setScheduling(true)}>
                <CalendarClock size={15} aria-hidden="true" /> {t("coord.record_appointment")}
              </button>
            )}
            {next.includes("acknowledged") && (
              <button type="button" className={buttonClass("secondary")} disabled={pending} onClick={() => act("acknowledged")}>
                {reply.trim() ? t("coord.req.acknowledge_reply") : t("coord.req.acknowledge")}
              </button>
            )}
            {!next.includes("acknowledged") && (reply.trim() || note.trim()) && (
              <button type="button" className={buttonClass("secondary")} disabled={pending} onClick={() => act(undefined)}>
                {t("coord.req.save_reply")}
              </button>
            )}
            {next.includes("declined") && (
              <button type="button" className={buttonClass("secondary")} disabled={pending} onClick={() => act("declined")}>
                {t("coord.req.decline")}
              </button>
            )}
            {next.includes("closed") && (
              <button type="button" className={buttonClass("quiet")} disabled={pending} onClick={() => act("closed")}>
                {t("coord.req.close")}
              </button>
            )}
          </div>
          <p className="text-xs text-faint">{t("coord.req.hint")}</p>
          <FormError message={error} />
          {done && <Confirmation>{done}</Confirmation>}
        </div>
      )}
    </div>
  );
}

function PatientFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { t } = useLocale();
  const [draft, setDraft] = useState(value);
  return (
    <label className={labelClass}>
      {t("coord.req.person_id")}
      <input
        className={`${inputClass} font-mono`}
        value={draft}
        placeholder={t("coord.req.person_placeholder")}
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
  const { t } = useLocale();
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
      eyebrow={t("coord.appt.tab_appointments")}
      title={when === "upcoming" ? t("coord.appt.upcoming") : when === "past" ? t("coord.appts.past") : t("coord.appts.all")}
      description={t("coord.appts.desc")}
      actions={
        can("appointments.create") && !creating ? (
          <button type="button" className={buttonClass("primary")} onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden="true" /> {t("coord.record_appointment")}
          </button>
        ) : undefined
      }
    >
      {creating && (
        <div className="mb-8">
          <ScheduleForm onCancel={() => setCreating(false)} onCreated={() => setCreating(false)} suggestedDate={isoDate(new Date(now))} />
        </div>
      )}
      <div role="search" aria-label={t("coord.appts.filters")} className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <div className={`${labelClass} col-span-2 md:col-span-3 lg:col-span-2`}>
          {t("coord.appts.when")}
          <Segmented
            label={t("coord.appts.when")}
            options={[{ value: "upcoming", label: t("coord.appts.when_upcoming") }, { value: "past", label: t("coord.appts.when_past") }, { value: "all", label: t("coord.appts.when_all") }]} value={when} onChange={(v) => reset(() => setWhen(v))} className="w-full" />
        </div>
        <label className={labelClass}>
          {t("coord.status")}
          <select className={inputClass} value={status} onChange={(e) => reset(() => setStatus(e.target.value as AppointmentStatus | ""))}>
            <option value="">{when === "upcoming" ? t("coord.appts.active_statuses") : t("coord.appts.any_status")}</option>
            {APPOINTMENT_STATUS_ORDER.map((s) => (
              <option key={s} value={s}>
                {t(APPOINTMENT_STATUS_META[s].label)}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          {t("coord.appts.facility")}
          <select className={inputClass} value={profile} onChange={(e) => reset(() => setProfile(e.target.value))}>
            <option value="">{t("coord.appts.all_facilities")}</option>
            {[...profileMap.values()].map((p) => (
              <option key={p.profile_id} value={p.profile_id}>
                {profileLabel(p, p.profile_id, t)}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          {t("coord.appts.from")}
          <input type="date" className={inputClass} value={from} onChange={(e) => reset(() => setFrom(e.target.value))} />
        </label>
        <label className={labelClass}>
          {t("coord.appts.to")}
          <input type="date" className={inputClass} value={to} onChange={(e) => reset(() => setTo(e.target.value))} />
        </label>
        <div className="col-span-2 md:col-span-1">
          <PatientFilter value={patient} onChange={(v) => reset(() => setPatient(v))} />
        </div>
      </div>
      <p className="mb-4 text-xs text-faint">{t("coord.appts.filters_note")}</p>
      <ResourceView resource={appointments} what={t("coord.appt.tab_appointments")} onRetry={() => setAttempt((n) => n + 1)} loading={<LoadingState rows={4} label={t("coord.appts.loading")} />}>
        {(p) =>
          p.items.length === 0 ? (
            <QuietEmpty title={t("coord.appts.empty")}>{when === "upcoming" ? t("coord.appts.empty_upcoming") : t("coord.appts.empty_other")}</QuietEmpty>
          ) : (
            <>
              <ul aria-label={t("coord.appt.tab_appointments")} className="flex flex-col divide-y divide-border border-y border-border">
                {p.items.map((a) => (
                  <AppointmentRow key={a.appointment_id} appointment={a} profile={profileMap.get(a.profile_id)} now={now} />
                ))}
              </ul>
              <Pager page={page} total={p.total} size={TASK_PAGE_SIZE} onPage={setPage} label={t("coord.appts.pager")} />
            </>
          )
        }
      </ResourceView>
    </Plate>
  );
}

function AppointmentRow({ appointment: a, profile, now }: { appointment: AppointmentOut; profile: ServiceProfileOut | undefined; now: string }) {
  const [open, setOpen] = useState(false);
  const { t, locale } = useLocale();
  const known = APPOINTMENT_STATUS_META[a.status];
  const meta = { label: known ? t(known.label) : a.status, tone: known?.tone ?? ("eligible" as const) };
  const overdue = (a.status === "scheduled" || a.status === "rescheduled") && a.scheduled_datetime < now;
  return (
    <li>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 px-1 py-3.5 text-start hover:bg-surface-raised sm:grid-cols-[170px_minmax(0,1fr)_auto_auto]">
        <span className="text-sm tabular-nums text-foreground">{formatDateTime(a.scheduled_datetime, locale)}</span>
        <span className="min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono text-sm text-foreground">{a.patient_id}</span>
            <span className="text-sm text-foreground">{appointmentTypeText(a.appointment_type, t)}</span>
          </span>
          <span className="mt-1 block truncate text-xs text-muted">
            {profileLabel(profile, a.profile_id, t)} · {slotText(a.slot_type, t)}
            {overdue && <span className="text-status-due"> · {t("coord.appts.outcome_missing")}</span>}
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
  const { t, rich } = useLocale();
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
      setDone(t("coord.appts.marked", { status: t(APPOINTMENT_STATUS_META[status].label) }));
      setStatus("");
      setNote("");
    }
  };
  return (
    <div className="reveal grid grid-cols-1 gap-6 px-1 pb-6 pt-1 lg:grid-cols-2">
      <div>
        <p className="mb-2 text-[11px] uppercase tracking-[0.08em] text-faint">{t("coord.history")}</p>
        {history && <WorkflowTimeline history={history} />}
        <p className="mt-3 text-xs text-faint">
          {t("coord.appts.booked_via", { via: a.booked_via.replace(/_/g, " ") })}
          {a.care_gap_id && (
            <>
              {" "}·{" "}
              {rich("coord.appts.care_gap_ref", { id: <span className="ltr-value font-mono">{a.care_gap_id}</span> })}
            </>
          )}
          {" "}·{" "}
          <Link className="text-accent underline-offset-4 hover:underline" href={`/people/${encodeURIComponent(a.patient_id)}#coordination`}>
            {t("coord.patient_profile")}
          </Link>
        </p>
      </div>
      {!can("appointments.update") ? (
        <PermissionNotice title={t("coord.appts.no_update_permission")} permission="appointments.update" />
      ) : next.length === 0 ? (
        <p className="text-sm text-muted">
          {t("coord.appts.final", { status: APPOINTMENT_STATUS_META[a.status] ? t(APPOINTMENT_STATUS_META[a.status].label).toLowerCase() : a.status })}
        </p>
      ) : (
        <form onSubmit={submit} aria-label={t("coord.appts.update_aria")} className="flex flex-col gap-3">
          <label className={labelClass}>
            {t("coord.new_status")}
            <select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value as AppointmentStatus)}>
              <option value="">{t("coord.choose")}</option>
              {next.map((s) => (
                <option key={s} value={s}>
                  {s === "rescheduled" ? t("coord.appts.reschedule") : t(APPOINTMENT_STATUS_META[s].label)}
                </option>
              ))}
            </select>
          </label>
          {status === "rescheduled" && (
            <label className={labelClass}>
              {t("coord.appts.new_when")}
              <input type="datetime-local" className={inputClass} required value={when} onChange={(e) => setWhen(e.target.value)} />
            </label>
          )}
          <label className={labelClass}>
            {t("coord.note_staff_history")}
            <input className={inputClass} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </label>
          {status === "attended" && <p className="text-xs text-faint">{t("coord.appts.attended_hint")}</p>}
          <FormError message={error} />
          {done && <Confirmation>{done}</Confirmation>}
          <div>
            <button type="submit" className={buttonClass("primary")} disabled={pending || !status || (status === "rescheduled" && !when)}>
              {pending ? t("coord.saving") : t("coord.save")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function WorkflowTimeline({ history }: { history: NonNullable<ReturnType<typeof useWorkflowHistory>> }) {
  const { t, locale } = useLocale();
  return (
    <ResourceView resource={history} what={t("coord.history")}>
      {(h) =>
        h.items.length === 0 ? (
          <p className="text-sm text-muted">{t("coord.wf.none")}</p>
        ) : (
          <ol className="flex flex-col gap-2 border-s border-border ps-4">
            {h.items.map((e) => {
              const key =
                e.entity_type === "appointment"
                  ? APPOINTMENT_STATUS_META[e.to_status as AppointmentStatus]?.label
                  : REFERRAL_STATUS_META[e.to_status as ReferralStatus]?.label;
              const label = key ? t(key) : e.to_status;
              return (
                <li key={e.status_event_id} className="text-sm">
                  <span className="text-foreground">{t(e.from_status ? "coord.wf.changed" : "coord.wf.created", { status: label })}</span>
                  {e.scheduled_datetime && e.entity_type === "appointment" && <span className="text-muted"> · {formatDateTime(e.scheduled_datetime, locale)}</span>}
                  {e.note && <span className="block text-xs text-muted">{e.note}</span>}
                  <span className="block text-[11px] text-faint">{formatDateTime(e.recorded_at, locale)}</span>
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
  const { t } = useLocale();
  const referrals = useReferralPage({ status: status || undefined, patient_id: patient.trim() || undefined }, page, attempt);
  return (
    <Plate eyebrow={t("coord.appt.tab_referrals")} title={t("coord.appt.tab_referrals")} description={t("coord.ref.desc")}>
      <div role="search" aria-label={t("coord.ref.filters")} className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className={labelClass}>
          {t("coord.status")}
          <select className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value as ReferralStatus | ""); setPage(1); }}>
            <option value="">{t("coord.all_statuses")}</option>
            {(Object.keys(REFERRAL_STATUS_META) as ReferralStatus[]).map((s) => (
              <option key={s} value={s}>
                {t(REFERRAL_STATUS_META[s].label)}
              </option>
            ))}
          </select>
        </label>
        <PatientFilter value={patient} onChange={(v) => { setPatient(v); setPage(1); }} />
      </div>
      <ResourceView resource={referrals} what={t("coord.appt.tab_referrals")} onRetry={() => setAttempt((n) => n + 1)} loading={<LoadingState rows={4} label={t("coord.ref.loading")} />}>
        {(p) =>
          p.items.length === 0 ? (
            <QuietEmpty title={t("coord.ref.empty")} />
          ) : (
            <>
              <ul aria-label={t("coord.appt.tab_referrals")} className="flex flex-col divide-y divide-border border-y border-border">
                {p.items.map((r) => (
                  <ReferralRow key={r.referral_id} referral={r} />
                ))}
              </ul>
              <Pager page={page} total={p.total} size={TASK_PAGE_SIZE} onPage={setPage} label={t("coord.ref.pager")} />
            </>
          )
        }
      </ResourceView>
    </Plate>
  );
}

export function ReferralRow({ referral: r }: { referral: ReferralOut }) {
  const { t, locale } = useLocale();
  const [open, setOpen] = useState(false);
  const meta = REFERRAL_STATUS_META[r.status];
  return (
    <li>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 px-1 py-3.5 text-start hover:bg-surface-raised">
        <span className="min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="ltr-value font-mono text-sm text-foreground">{r.patient_id}</span>
            <span className="text-sm text-foreground">{t("coord.ref.to", { target: r.referral_target })}</span>
          </span>
          <span className="mt-1 block text-xs text-muted">
            <span className="ltr-value font-mono">{r.referral_id}</span> · {t("coord.ref.triggered", { rule: r.trigger_rule_id, date: formatDate(r.trigger_date, locale) })}
            {r.initiated_date && ` · ${t("coord.ref.initiated", { date: formatDate(r.initiated_date, locale) })}`}
            {r.completed_date && ` · ${t("coord.ref.completed", { date: formatDate(r.completed_date, locale) })}`}
          </span>
        </span>
        <StatusPill tone={meta.tone} label={t(meta.label)} />
        <ChevronDown size={16} aria-hidden="true" className={cn("text-faint transition-transform duration-200", open && "rotate-180")} />
      </button>
      {open && <ReferralDetail referral={r} />}
    </li>
  );
}

function ReferralDetail({ referral: r }: { referral: ReferralOut }) {
  const { can } = useAuth();
  const { t } = useLocale();
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
      setDone(t("coord.ref.marked", { status: t(REFERRAL_STATUS_META[status].label) }));
      setStatus("");
    }
  };
  return (
    <div className="reveal grid grid-cols-1 gap-6 px-1 pb-6 pt-1 lg:grid-cols-2">
      <div>
        <p className="mb-2 text-[11px] uppercase tracking-[0.08em] text-faint">{t("coord.history")}</p>
        {history && <WorkflowTimeline history={history} />}
        <p className="mt-3 text-xs text-faint">
          <Link className="text-accent underline-offset-4 hover:underline" href={`/people/${encodeURIComponent(r.patient_id)}#coordination`}>
            {t("coord.ref.profile_link")}
          </Link>
        </p>
      </div>
      {!can("referrals.update") ? (
        <PermissionNotice title={t("coord.ref.no_update_permission")} permission="referrals.update" />
      ) : next.length === 0 ? (
        <p className="text-sm text-muted">{t("coord.ref.final")}</p>
      ) : (
        <form onSubmit={submit} aria-label={t("coord.ref.update_aria")} className="flex flex-col gap-3">
          <label className={labelClass}>
            {t("coord.new_status")}
            <select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value as ReferralStatus)}>
              <option value="">{t("coord.choose")}</option>
              {next.map((s) => (
                <option key={s} value={s}>
                  {t(REFERRAL_STATUS_META[s].label)}
                </option>
              ))}
            </select>
          </label>
          {(status === "initiated" || status === "completed") && (
            <label className={labelClass}>
              {t("coord.ref.initiated_on")}
              <input type="date" className={inputClass} required value={initiated} min={r.trigger_date} onChange={(e) => setInitiated(e.target.value)} />
            </label>
          )}
          {status === "completed" && (
            <label className={labelClass}>
              {t("coord.ref.completed_on")}
              <input type="date" className={inputClass} required value={completed} min={initiated} onChange={(e) => setCompleted(e.target.value)} />
            </label>
          )}
          <label className={labelClass}>
            {t("coord.note_staff_history")}
            <input className={inputClass} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </label>
          <FormError message={error} />
          {done && <Confirmation>{done}</Confirmation>}
          <div>
            <button type="submit" className={buttonClass("primary")} disabled={pending || !status}>
              {pending ? t("coord.saving") : t("coord.save")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
