import type {
  AppointmentCreateIn,
  AppointmentOut,
  AppointmentPatchIn,
  AppointmentQuery,
  CareGapDetailOut,
  CareTeamMemberOut,
  ContactChannel,
  ContactOutcome,
  FollowUpCreateIn,
  FollowUpEventOut,
  OutreachDraftIn,
  OutreachDraftOut,
  OutreachReviewIn,
  OutreachReviewOut,
  PatientActivityOut,
  ReferralOut,
  ReferralPatchIn,
  RequestQuery,
  RequestUpdateIn,
  ServiceProfilesOut,
  StaffPatientRequestOut,
  TaskCreateIn,
  TaskDetailOut,
  TaskOut,
  TaskQuery,
  TaskSummaryOut,
  TaskUpdateIn,
  WorkflowHistoryOut,
  CareGapOut,
  CareGapQuery,
  DashboardSummaryOut,
  ExplanationOut,
  MeOut,
  Paginated,
  PaginatedOpenQuestionsOut,
  PaginatedRulesOut,
  Pathway,
  PatientEvaluationsOut,
  PatientQuery,
  PatientSummaryOut,
  PopulationSummaryOut,
  ProgrammeSummaryOut,
  ProgrammeSummaryQuery,
  RuleDetailOut,
  TokenOut,
} from "./types";
import type * as P from "./portal-types";
import type * as A from "./admin-types";
import type * as G from "./geo-types";
import type { AggregationRunOut, PopulationConfigOut, PopulationUpdatesOut } from "./admin-types";
import { clearSession, getSession, isAccessExpired, setSession } from "@/lib/auth/session";

/** Backend base URL; `.env.example` documents the local default. Never holds credentials. */
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  ""
);

/** Largest page the backend accepts for `/patients` and `/care-gaps` (`le=200`). */
const MAX_PAGE = 200;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly path: string,
    /** `error.code` from the backend error body (`unauthorized`, `forbidden`, …), when present. */
    readonly code: string | null = null,
    /** Localized `error.message` from the backend, when present. */
    readonly serverMessage: string | null = null
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** True when the backend refused the call for this role (403) — the UI shows a permission state, not an error. */
export function isForbidden(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403;
}

type QueryValue = string | number | boolean | undefined;

async function apiGet<T>(path: string, query: object = {}, signal?: AbortSignal): Promise<T> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query as Record<string, QueryValue>))
    if (v !== undefined) params.set(k, String(v));
  const qs = params.toString();
  return apiRequest<T>(path, `${path}${qs ? `?${qs}` : ""}`, { signal });
}

async function apiPost<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return apiRequest<T>(path, path, {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>(path, path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** The backend's localized reason for a refused write (e.g. an invalid transition), else the generic message. */
export function apiErrorMessage(err: unknown, fallback = "The request failed."): string {
  if (!(err instanceof ApiError)) return fallback;
  if (err.status === 401 || err.status === 403 || err.status === null) return err.message;
  return err.serverMessage ?? err.message;
}

async function toApiError(res: Response, path: string): Promise<ApiError> {
  let code: string | null = null;
  let serverMessage: string | null = null;
  try {
    const body = (await res.json()) as { error?: { code?: string; message?: string } };
    code = body.error?.code ?? null;
    serverMessage = body.error?.message ?? null;
  } catch {
    /* Non-JSON body. */
  }
  const message =
    res.status === 401
      ? `Your session is not valid (401 for ${path}). Sign in again to continue.`
      : res.status === 403
        ? `Your role does not have access to ${path} (403).`
        : res.status === 429
          ? `Too many requests (429 for ${path}). Wait a moment and try again.`
          : `The API responded ${res.status} for ${path}.`;
  return new ApiError(message, res.status, path, code, serverMessage);
}

/*
 * Request gate. While the session is being resolved (or nobody is signed in) data
 * requests wait here instead of going out unauthenticated. Identity endpoints
 * bypass it. With no AuthProvider (tests) the gate stays open, but the token rule
 * below still applies.
 */
let gate: { promise: Promise<void>; open: () => void } | null = null;

/*
 * Token rule: a data request without an access token is refused locally (never sent),
 * unless the AuthProvider resolved an explicitly allowed legacy backend
 * (`legacyBackendAllowed`, local development only).
 */
let unauthenticatedAllowed = false;

export function allowUnauthenticatedRequests(allowed: boolean): void {
  unauthenticatedAllowed = allowed;
}

/** Identity endpoint the backend answered 404 for (no identity layer) — set before the session is cleared. */
let missingIdentityEndpoint: string | null = null;

export function identityEndpointMissing(): string | null {
  return missingIdentityEndpoint;
}

export function resetIdentityProbe(): void {
  missingIdentityEndpoint = null;
}

export function holdRequests(): void {
  if (gate) return;
  let open!: () => void;
  const promise = new Promise<void>((resolve) => (open = resolve));
  gate = { promise, open };
}

/*
 * Patient sessions never release the staff gate: only `/portal/*` requests (the patient's own,
 * link-derived record) bypass it, so a staff view mounted underneath can never fire a request
 * with a patient token.
 */
let portalAllowed = false;

export function allowPortalRequests(allowed: boolean): void {
  portalAllowed = allowed;
}

export function releaseRequests(): void {
  gate?.open();
  gate = null;
}

function waitForGate(signal?: AbortSignal | null): Promise<void> {
  if (!gate) return Promise.resolve();
  const pending = gate.promise;
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
    signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    pending.then(resolve);
  });
}

/* One refresh at a time: concurrent 401s wait for the same rotation (reuse would revoke the session). */
let refreshing: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  const session = getSession();
  if (!session) return false;
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: session.refreshToken }),
      });
      if (!res.ok) {
        if (res.status === 404) missingIdentityEndpoint = "/auth/refresh";
        clearSession();
        return false;
      }
      setSession((await res.json()) as TokenOut);
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

/** Identity endpoints: not held by the gate and allowed without a token (they establish the session). */
const UNGATED = new Set(["/me", "/auth/login", "/auth/logout"]);

function notSignedIn(path: string): ApiError {
  return new ApiError(`Sign in to load ${path}. No request was sent without a session.`, 401, path, "not_authenticated");
}

async function apiRequest<T>(path: string, pathWithQuery: string, init: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}/api/v1${pathWithQuery}`;
  const identity = UNGATED.has(path);
  if (!identity && !(portalAllowed && path.startsWith("/portal/"))) await waitForGate(init.signal);
  const send = () => {
    const session = getSession();
    if (!session && !identity && !unauthenticatedAllowed) throw notSignedIn(path);
    const auth: Record<string, string> = session ? { Authorization: `Bearer ${session.accessToken}` } : {};
    return fetch(url, { ...init, headers: { Accept: "application/json", ...auth, ...init.headers } });
  };
  let res: Response;
  try {
    const session = getSession();
    if (session && isAccessExpired(session)) await refreshSession();
    res = await send();
    if (res.status === 401 && getSession() && (await refreshSession())) res = await send();
  } catch (err) {
    if ((err as Error).name === "AbortError" || err instanceof ApiError) throw err;
    throw new ApiError(`Could not reach the PulseReach API at ${API_BASE_URL}.`, null, path);
  }
  if (res.status === 404 && path !== "/auth/logout" && identity) missingIdentityEndpoint = path;
  if (!res.ok) throw await toApiError(res, path);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Reads every page of a paginated endpoint so aggregates cover the full result set. */
async function getAllPages<T>(
  path: string,
  query: object,
  signal?: AbortSignal
): Promise<{ total: number; items: T[] }> {
  const first = await apiGet<Paginated<T>>(path, { ...query, limit: MAX_PAGE, offset: 0 }, signal);
  const offsets: number[] = [];
  for (let o = MAX_PAGE; o < first.total; o += MAX_PAGE) offsets.push(o);
  const rest = await Promise.all(
    offsets.map((offset) => apiGet<Paginated<T>>(path, { ...query, limit: MAX_PAGE, offset }, signal))
  );
  return { total: first.total, items: [first, ...rest].flatMap((p) => p.items) };
}

export const api = {
  dashboardSummary: (signal?: AbortSignal) =>
    apiGet<DashboardSummaryOut>("/dashboard/summary", {}, signal),
  rules: (signal?: AbortSignal, pathway?: Pathway) => apiGet<PaginatedRulesOut>("/rules", { pathway }, signal),
  /** Backend-filtered (`pathway`, `region_id`, `sex`, `age_band`, …), all pages. */
  allPatients: (query: PatientQuery, signal?: AbortSignal) =>
    getAllPages<PatientSummaryOut>("/patients", { ...query }, signal),
  /** Only the backend `total` for a patient query (one-row page). */
  patientsTotal: (query: PatientQuery, signal?: AbortSignal) =>
    apiGet<Paginated<PatientSummaryOut>>("/patients", { ...query, limit: 1, offset: 0 }, signal).then((p) => p.total),
  allCareGaps: (signal?: AbortSignal, query: CareGapQuery = {}) =>
    getAllPages<CareGapOut>("/care-gaps", query, signal),
  /** One backend page of `/patients` (filters + `limit`/`offset`). */
  patientsPage: (query: PatientQuery & { limit: number; offset: number }, signal?: AbortSignal) =>
    apiGet<Paginated<PatientSummaryOut>>("/patients", { ...query }, signal),
  patient: (id: string, signal?: AbortSignal) =>
    apiGet<PatientSummaryOut>(`/patients/${encodeURIComponent(id)}`, {}, signal),
  patientEvaluations: (id: string, signal?: AbortSignal) =>
    apiGet<PatientEvaluationsOut>(`/patients/${encodeURIComponent(id)}/evaluations`, {}, signal),
  ruleDetail: (id: string, signal?: AbortSignal) =>
    apiGet<RuleDetailOut>(`/rules/${encodeURIComponent(id)}`, {}, signal),
  openQuestions: (signal?: AbortSignal) => apiGet<PaginatedOpenQuestionsOut>("/open-questions", {}, signal),
  /** Organization-level surveillance aggregates (`population.read`; small cells suppressed). */
  populationSummary: (signal?: AbortSignal) => apiGet<PopulationSummaryOut>("/population/summary", {}, signal),
  /** Programme aggregates computed server-side for the caller's scope (`insights.read` + `care_gaps.read`). */
  programmeSummary: (pathway: Pathway, query: ProgrammeSummaryQuery, signal?: AbortSignal) =>
    apiGet<ProgrammeSummaryOut>(`/programmes/${pathway}/summary`, { ...query }, signal),
  explanation: (patientId: string, ruleId: string, signal?: AbortSignal) =>
    apiPost<ExplanationOut>("/explanations", { patient_id: patientId, rule_id: ruleId }, signal),

  /* Coordination: follow-up tasks (`followups.*`), patient requests, appointments, referrals, outreach. */
  taskSummary: (query: TaskQuery, signal?: AbortSignal) =>
    apiGet<TaskSummaryOut>("/follow-up-tasks/summary", { ...query }, signal),
  tasks: (query: TaskQuery & { limit: number; offset: number }, signal?: AbortSignal) =>
    apiGet<Paginated<TaskOut>>("/follow-up-tasks", { ...query }, signal),
  task: (id: string, signal?: AbortSignal) =>
    apiGet<TaskDetailOut>(`/follow-up-tasks/${encodeURIComponent(id)}`, {}, signal),
  createTask: (body: TaskCreateIn) => apiPost<TaskDetailOut>("/follow-up-tasks", body),
  updateTask: (id: string, body: TaskUpdateIn) => apiPatch<TaskDetailOut>(`/follow-up-tasks/${encodeURIComponent(id)}`, body),
  addTaskNote: (id: string, text: string, patientVisible: boolean) =>
    apiPost<TaskDetailOut>(`/follow-up-tasks/${encodeURIComponent(id)}/notes`, { text, patient_visible: patientVisible }),
  escalateTask: (id: string, reason: string | null) =>
    apiPost<TaskDetailOut>(`/follow-up-tasks/${encodeURIComponent(id)}/escalate`, { reason }),
  recordContactAttempt: (id: string, body: { channel: ContactChannel; outcome: ContactOutcome; note?: string | null }) =>
    apiPost<TaskDetailOut>(`/follow-up-tasks/${encodeURIComponent(id)}/contact-attempts`, body),
  completeTask: (id: string, completionFollowUpId: string | null) =>
    apiPost<TaskDetailOut>(`/follow-up-tasks/${encodeURIComponent(id)}/complete`, { completion_follow_up_id: completionFollowUpId }),
  careTeam: (patientId?: string, signal?: AbortSignal) =>
    apiGet<{ items: CareTeamMemberOut[] }>("/care-team", { patient_id: patientId }, signal).then((r) => r.items),
  careGap: (id: string, signal?: AbortSignal) => apiGet<CareGapDetailOut>(`/care-gaps/${encodeURIComponent(id)}`, {}, signal),
  createCareGapFollowUp: (gapId: string, body: FollowUpCreateIn) =>
    apiPost<FollowUpEventOut>(`/care-gaps/${encodeURIComponent(gapId)}/follow-ups`, body),
  patientActivity: (id: string, signal?: AbortSignal) =>
    apiGet<PatientActivityOut>(`/patients/${encodeURIComponent(id)}/activity`, {}, signal),
  patientRequests: (query: RequestQuery & { limit: number; offset: number }, signal?: AbortSignal) =>
    apiGet<Paginated<StaffPatientRequestOut>>("/patient-requests", { ...query }, signal),
  updatePatientRequest: (id: string, body: RequestUpdateIn) =>
    apiPatch<StaffPatientRequestOut>(`/patient-requests/${encodeURIComponent(id)}`, body),
  appointments: (query: AppointmentQuery & { limit: number; offset: number }, signal?: AbortSignal) =>
    apiGet<Paginated<AppointmentOut>>("/appointments", { ...query }, signal),
  appointmentsTotal: (query: AppointmentQuery, signal?: AbortSignal) =>
    apiGet<Paginated<AppointmentOut>>("/appointments", { ...query, limit: 1, offset: 0 }, signal).then((p) => p.total),
  createAppointment: (body: AppointmentCreateIn) => apiPost<AppointmentOut>("/appointments", body),
  updateAppointment: (id: string, body: AppointmentPatchIn) =>
    apiPatch<AppointmentOut>(`/appointments/${encodeURIComponent(id)}`, body),
  appointmentHistory: (id: string, signal?: AbortSignal) =>
    apiGet<WorkflowHistoryOut>(`/appointments/${encodeURIComponent(id)}/history`, {}, signal),
  serviceProfiles: (signal?: AbortSignal) => apiGet<ServiceProfilesOut>("/facility-service-profiles", {}, signal),
  referrals: (query: { patient_id?: string; status?: string; limit: number; offset: number }, signal?: AbortSignal) =>
    apiGet<Paginated<ReferralOut>>("/referrals", { ...query }, signal),
  updateReferral: (id: string, body: ReferralPatchIn) => apiPatch<ReferralOut>(`/referrals/${encodeURIComponent(id)}`, body),
  referralHistory: (id: string, signal?: AbortSignal) =>
    apiGet<WorkflowHistoryOut>(`/referrals/${encodeURIComponent(id)}/history`, {}, signal),
  outreachDraft: (body: OutreachDraftIn) => apiPost<OutreachDraftOut>("/outreach/draft", body),
  outreachReview: (body: OutreachReviewIn) => apiPost<OutreachReviewOut>("/outreach/draft/review", body),

  /* Identity (`AUTH_MODE=users`; 404 in legacy mode). */
  login: (email: string, password: string) => apiPost<TokenOut>("/auth/login", { email, password }),
  logout: () => apiPost<void>("/auth/logout", undefined),
  me: (signal?: AbortSignal) => apiGet<MeOut>("/me", {}, signal),

  /* Population aggregation operations (SYSTEM_ADMIN / PHM). */
  populationUpdates: (signal?: AbortSignal) => apiGet<PopulationUpdatesOut>("/population/updates", {}, signal),
  populationConfig: (signal?: AbortSignal) => apiGet<PopulationConfigOut>("/population/config", {}, signal),
  refreshPopulation: () => apiPost<AggregationRunOut>("/population/refresh", undefined),

  /* Map (BE-33): area aggregates are suppressed server-side; facilities are verified points only. */
  populationMap: (query: { geography: "district" | "local_area"; metric: G.MapMetric; condition?: G.ConditionCode; period?: string; limit?: number }, signal?: AbortSignal) =>
    apiGet<G.MapOut>("/population/map", { period: "90d", limit: 500, ...query }, signal),
  populationAlerts: (signal?: AbortSignal) => apiGet<G.AlertsOut>("/population/alerts", { active_only: true, limit: 200 }, signal),
  facilityPoints: (signal?: AbortSignal) => apiGet<G.FacilityPointsOut>("/facilities/points", {}, signal),
};

const enc = encodeURIComponent;

/** Patient portal: the backend derives the patient from the verified account link, never from the request. */
export const portalApi = {
  link: (invitationCode: string, dateOfBirth: string) =>
    apiPost<{ linked: boolean; patient_id: string; message: string }>("/portal/link", { invitation_code: invitationCode, date_of_birth: dateOfBirth }),
  summary: (signal?: AbortSignal) => apiGet<P.PortalProfileOut>("/portal/summary", {}, signal),
  healthSummary: (signal?: AbortSignal) => apiGet<P.HealthSummaryOut>("/portal/health-summary", {}, signal),
  recommendations: (status: "active" | "all", signal?: AbortSignal) =>
    apiGet<P.RecommendationsOut>("/portal/recommendations", { status }, signal),
  recommendation: (id: string, signal?: AbortSignal) =>
    apiGet<P.RecommendationDetailOut>(`/portal/recommendations/${enc(id)}`, {}, signal),
  appointments: (signal?: AbortSignal) => apiGet<P.PortalAppointmentsOut>("/portal/appointments", {}, signal),
  referrals: (signal?: AbortSignal) => apiGet<P.PortalReferralsOut>("/portal/referrals", {}, signal),
  followUps: (signal?: AbortSignal) => apiGet<P.PortalFollowUpsOut>("/portal/follow-ups", {}, signal),
  followUp: (id: string, signal?: AbortSignal) => apiGet<P.PortalFollowUpDetailOut>(`/portal/follow-ups/${enc(id)}`, {}, signal),
  respond: (id: string, response: P.PatientResponse, message: string | null) =>
    apiPost<P.PortalFollowUpDetailOut>(`/portal/follow-ups/${enc(id)}/responses`, { response, message }),
  requests: (signal?: AbortSignal) => apiGet<P.PatientRequestsOut>("/portal/requests", {}, signal),
  cancelRequest: (id: string) => apiPost<P.PatientRequestDetailOut>(`/portal/requests/${enc(id)}/cancel`, undefined),
  requestAppointment: (body: P.AppointmentRequestIn) => apiPost<P.PatientRequestDetailOut>("/portal/appointment-requests", body),
  requestAppointmentChange: (appointmentId: string, body: P.AppointmentChangeIn) =>
    apiPost<P.PatientRequestDetailOut>(`/portal/appointments/${enc(appointmentId)}/change-requests`, body),
  requestAssistance: (message: string, preferredTime: P.TimeOfDay | null) =>
    apiPost<P.PatientRequestDetailOut>("/portal/assistance", { message, preferred_time_of_day: preferredTime }),
};

/** Organization administration — every call is scoped by the backend to the caller's organization. */
export const adminApi = {
  users: (query: { role?: string; limit: number; offset: number }, signal?: AbortSignal) =>
    apiGet<A.Page<A.MemberOut>>("/admin/users", query, signal),
  createUser: (body: A.StaffCreateIn) => apiPost<A.StaffCreateOut>("/admin/users", body),
  updateUser: (id: string, body: A.MemberUpdateIn) => apiPatch<A.MemberOut>(`/admin/users/${enc(id)}`, body),
  setUserActive: (id: string, active: boolean) =>
    apiPost<A.AccountStatusOut>(`/admin/users/${enc(id)}/${active ? "activate" : "deactivate"}`, undefined),
  issuePasswordReset: (id: string) => apiPost<A.OneTimeTokenOut>(`/admin/users/${enc(id)}/password-reset`, undefined),
  assignableStaff: (signal?: AbortSignal) =>
    apiGet<{ items: A.AssignableStaffOut[] }>("/admin/assignments/staff", {}, signal).then((r) => r.items),
  assignments: (query: { staff_user_id?: string; patient_id?: string; active_only?: boolean; limit: number; offset: number }, signal?: AbortSignal) =>
    apiGet<A.Page<A.AssignmentOut>>("/admin/assignments", query, signal),
  createAssignment: (staffUserId: string, patientId: string) =>
    apiPost<A.AssignmentOut>("/admin/assignments", { staff_user_id: staffUserId, patient_id: patientId }),
  endAssignment: (id: string) => apiPost<A.AssignmentOut>(`/admin/assignments/${enc(id)}/end`, undefined),
  patientLinks: (query: { status?: "active" | "revoked"; limit: number; offset: number }, signal?: AbortSignal) =>
    apiGet<A.Page<A.PatientLinkOut>>("/admin/patient-links", query, signal),
  revokePatientLink: (id: string) => apiPost<A.PatientLinkOut>(`/admin/patient-links/${enc(id)}/revoke`, undefined),
  auditEvents: (query: A.AuditQuery, signal?: AbortSignal) => apiGet<A.Page<A.AuditEventOut>>("/audit-events", query, signal),
};
