"use client";

import { useCallback, useState, useSyncExternalStore } from "react";
import { api, apiErrorMessage, ApiError } from "@/lib/api/client";
import { cached, evict, onCacheReset } from "@/lib/api/cache";
import { useResource, type Resource } from "@/lib/api/resource";
import type {
  AppointmentOut,
  AppointmentQuery,
  CareGapDetailOut,
  CareTeamMemberOut,
  Paginated,
  PatientActivityOut,
  ReferralOut,
  RequestQuery,
  RuleSummaryOut,
  ServiceProfilesOut,
  StaffPatientRequestOut,
  TaskDetailOut,
  TaskOut,
  TaskQuery,
  TaskSummaryOut,
  WorkflowHistoryOut,
} from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";

export type { Resource };

/*
 * Coordination data changes with every write, so it is never cached across views. Each read
 * carries the coordination version in its key; any successful write bumps it, refetching every
 * mounted coordination view (task lists, counts, timelines) instead of showing stale state.
 * A documented completion closes a care gap, so the session-cached care-gap records and dashboard
 * counts (programme views) are evicted too.
 */
let version = 0;
const listeners = new Set<() => void>();

export function invalidateCoordination(): void {
  evict("care-gaps", "dashboard-summary");
  version += 1;
  listeners.forEach((l) => l());
}
onCacheReset(invalidateCoordination);

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useCoordinationVersion(): number {
  return useSyncExternalStore(subscribe, () => version, () => version);
}

/**
 * `useResource` keyed by `base` plus the coordination version. While a write-triggered refetch of the
 * same `base` is in flight the last loaded data stays on screen (forms, confirmations and expanded
 * rows survive); a different `base` (another task, other filters) shows loading as usual.
 */
function useLive<T>(base: string | null, permission: string, load: (signal: AbortSignal) => Promise<T>, attempt: number): Resource<T> {
  const v = useCoordinationVersion();
  const r = useResource(base === null ? null : `${base}|v${v}`, permission, load, attempt);
  const [last, setLast] = useState<{ base: string | null; r: Resource<T> } | null>(null);
  if (r.status === "ready" && last?.r !== r) setLast({ base, r });
  return r.status === "loading" && last && last.base === base ? last.r : r;
}

function qs(query: object): string {
  return new URLSearchParams(
    Object.entries(query).flatMap(([k, v]) => (v === undefined || v === null || v === "" ? [] : [[k, String(v)]]))
  ).toString();
}

/** Shared reference data (session cache): rules for programme names, care team for names. */
export function useRulesIndex(): Resource<Map<string, RuleSummaryOut>> {
  const { can } = useAuth();
  return useLive(can("rules.read") ? "rules-index" : null, "rules.read", () =>
    cached("rules", () => api.rules().then((r) => r.items)).then((items) => new Map(items.map((r) => [r.rule_id, r]))), 0
  );
}

export function useCareTeam(patientId?: string): Resource<Map<string, CareTeamMemberOut>> {
  const { can } = useAuth();
  return useLive(
    can("followups.read") ? `care-team|${patientId ?? ""}` : null,
    "followups.read",
    (signal) =>
      (patientId ? api.careTeam(patientId, signal) : cached("care-team", () => api.careTeam())).then(
        (items) => new Map(items.map((m) => [m.user_id, m]))
      ),
    0
  );
}

export function useServiceProfiles(enabled = true): Resource<ServiceProfilesOut> {
  const { can } = useAuth();
  return useLive(enabled && can("facilities.read") ? "service-profiles" : null, "facilities.read", () =>
    cached("service-profiles", () => api.serviceProfiles()), 0
  );
}

export function useTaskSummary(query: TaskQuery, attempt: number): Resource<TaskSummaryOut> {
  const { can } = useAuth();
  return useLive(can("followups.read") ? `task-summary|${qs(query)}` : null, "followups.read", (signal) =>
    api.taskSummary(query, signal), attempt
  );
}

export const TASK_PAGE_SIZE = 25;

export function useTaskPage(query: TaskQuery, page: number, attempt: number): Resource<Paginated<TaskOut>> {
  const { can } = useAuth();
  return useLive(can("followups.read") ? `tasks|${qs(query)}|${page}` : null, "followups.read", (signal) =>
    api.tasks({ ...query, limit: TASK_PAGE_SIZE, offset: (page - 1) * TASK_PAGE_SIZE }, signal), attempt
  );
}

export type TaskState = Resource<TaskDetailOut> | { status: "not_found" };

export function useTask(taskId: string, attempt: number): TaskState {
  const { can } = useAuth();
  const r = useLive<TaskDetailOut | null>(can("followups.read") ? `task|${taskId}` : null, "followups.read", (signal) =>
    api.task(taskId, signal).catch((err) => {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }), attempt
  );
  if (r.status === "ready" && r.data === null) return { status: "not_found" };
  return r as Resource<TaskDetailOut>;
}

export function useCareGap(gapId: string | null, attempt: number): Resource<CareGapDetailOut> | null {
  const { can } = useAuth();
  const r = useLive(gapId && can("care_gaps.read") ? `gap|${gapId}` : null, "care_gaps.read", (signal) =>
    api.careGap(gapId!, signal), attempt
  );
  return gapId ? r : null;
}

export function useRequestPage(query: RequestQuery, page: number, attempt: number, size = TASK_PAGE_SIZE) {
  const { can } = useAuth();
  return useLive<Paginated<StaffPatientRequestOut>>(
    can("patient_requests.manage") ? `requests|${qs(query)}|${page}|${size}` : null,
    "patient_requests.manage",
    (signal) => api.patientRequests({ ...query, limit: size, offset: (page - 1) * size }, signal),
    attempt
  );
}

export function useAppointmentPage(query: AppointmentQuery, page: number, attempt: number, size = TASK_PAGE_SIZE) {
  const { can } = useAuth();
  return useLive<Paginated<AppointmentOut>>(
    can("appointments.read") ? `appointments|${qs(query)}|${page}|${size}` : null,
    "appointments.read",
    (signal) => api.appointments({ ...query, limit: size, offset: (page - 1) * size }, signal),
    attempt
  );
}

export interface AppointmentCounts {
  upcoming: number;
  pastUnresolved: number;
  attended: number;
  noShow: number;
  cancelled: number;
  byStatus: Record<string, number>;
  pendingRequests: number | null;
}

const COUNTED_STATUSES = ["scheduled", "rescheduled", "attended", "no_show", "cancelled_by_patient", "cancelled_by_facility"] as const;

/** Exact backend totals (one-row pages) — never derived from a partial list. */
export function useAppointmentCounts(query: AppointmentQuery, now: string, attempt: number): Resource<AppointmentCounts> {
  const { can } = useAuth();
  const requests = can("patient_requests.manage");
  return useLive(
    can("appointments.read") ? `appointment-counts|${qs(query)}|${now}|${requests}` : null,
    "appointments.read",
    async (signal) => {
      const base = { ...query, status: undefined, status_group: undefined };
      const [upcoming, pastUnresolved, cancelled, pending, ...byStatus] = await Promise.all([
        api.appointmentsTotal({ ...base, status_group: "active", scheduled_from: now }, signal),
        api.appointmentsTotal({ ...base, status_group: "active", scheduled_to: now }, signal),
        api.appointmentsTotal({ ...base, status_group: "cancelled" }, signal),
        requests
          ? Promise.all(
              (["submitted", "acknowledged"] as const).map((status) =>
                api.patientRequests({ status, request_type: undefined, limit: 1, offset: 0 }, signal).then((p) => p.total)
              )
            ).then(([a, b]) => a + b)
          : Promise.resolve(null),
        ...COUNTED_STATUSES.map((status) => api.appointmentsTotal({ ...base, status }, signal)),
      ]);
      const map = Object.fromEntries(COUNTED_STATUSES.map((s, i) => [s, byStatus[i]]));
      return { upcoming, pastUnresolved, cancelled, attended: map.attended, noShow: map.no_show, byStatus: map, pendingRequests: pending };
    },
    attempt
  );
}

export function useReferralPage(query: { patient_id?: string; status?: string }, page: number, attempt: number, size = TASK_PAGE_SIZE) {
  const { can } = useAuth();
  return useLive<Paginated<ReferralOut>>(
    can("referrals.read") ? `referrals|${qs(query)}|${page}|${size}` : null,
    "referrals.read",
    (signal) => api.referrals({ ...query, limit: size, offset: (page - 1) * size }, signal),
    attempt
  );
}

export function useWorkflowHistory(entity: "appointment" | "referral", id: string | null): Resource<WorkflowHistoryOut> | null {
  const r = useLive(id ? `${entity}-history|${id}` : null, `${entity}s.read`, (signal) =>
    entity === "appointment" ? api.appointmentHistory(id!, signal) : api.referralHistory(id!, signal), 0
  );
  return id ? r : null;
}

export interface PatientCoordination {
  tasks: Resource<TaskDetailOut[]>;
  activity: Resource<PatientActivityOut>;
  requests: Resource<StaffPatientRequestOut[]>;
  appointments: Resource<AppointmentOut[]>;
  referrals: Resource<ReferralOut[]>;
}

const PROFILE_LIMIT = 200;

/** Everything coordinated for one person, each part under its own permission. */
export function usePatientCoordination(patientId: string, attempt: number): PatientCoordination {
  const { can } = useAuth();
  const key = (perm: string, what: string) => (can(perm) ? `${what}|${patientId}` : null);
  const tasks = useLive(key("followups.read", "p-tasks"), "followups.read", async (signal) => {
    const page = await api.tasks({ patient_id: patientId, limit: PROFILE_LIMIT, offset: 0 }, signal);
    return Promise.all(page.items.map((t) => api.task(t.task_id, signal)));
  }, attempt);
  const activity = useLive(key("followups.read", "p-activity"), "followups.read", (signal) =>
    api.patientActivity(patientId, signal), attempt
  );
  const requests = useLive(key("patient_requests.manage", "p-requests"), "patient_requests.manage", (signal) =>
    api.patientRequests({ patient_id: patientId, limit: PROFILE_LIMIT, offset: 0 }, signal).then((p) => p.items), attempt
  );
  const appointments = useLive(key("appointments.read", "p-appointments"), "appointments.read", (signal) =>
    api.appointments({ patient_id: patientId, limit: PROFILE_LIMIT, offset: 0 }, signal).then((p) => p.items), attempt
  );
  const referrals = useLive(key("referrals.read", "p-referrals"), "referrals.read", (signal) =>
    api.referrals({ patient_id: patientId, limit: PROFILE_LIMIT, offset: 0 }, signal).then((p) => p.items), attempt
  );
  return { tasks, activity, requests, appointments, referrals };
}

/**
 * Runs one write at a time. Success invalidates coordination reads; failure keeps the backend's
 * own reason (e.g. invalid transition, consent refusal) for the form to show.
 */
export function useMutation() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setPending(true);
    setError(null);
    try {
      const out = await fn();
      invalidateCoordination();
      return out;
    } catch (err) {
      setError(apiErrorMessage(err));
      return null;
    } finally {
      setPending(false);
    }
  }, []);
  const reset = useCallback(() => setError(null), []);
  return { run, pending, error, reset };
}
