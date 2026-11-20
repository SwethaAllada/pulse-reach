import type {
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
  RuleDetailOut,
  TokenOut,
} from "./types";
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
 * bypass it. With no AuthProvider (tests, legacy embedding) the gate stays open.
 */
let gate: { promise: Promise<void>; open: () => void } | null = null;

export function holdRequests(): void {
  if (gate) return;
  let open!: () => void;
  const promise = new Promise<void>((resolve) => (open = resolve));
  gate = { promise, open };
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

const UNGATED = new Set(["/me", "/auth/login", "/auth/logout"]);

async function apiRequest<T>(path: string, pathWithQuery: string, init: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}/api/v1${pathWithQuery}`;
  if (!UNGATED.has(path)) await waitForGate(init.signal);
  const send = () => {
    const session = getSession();
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
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(`Could not reach the PulseReach API at ${API_BASE_URL}.`, null, path);
  }
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
  explanation: (patientId: string, ruleId: string, signal?: AbortSignal) =>
    apiPost<ExplanationOut>("/explanations", { patient_id: patientId, rule_id: ruleId }, signal),

  /* Identity (`AUTH_MODE=users`; 404 in legacy mode). */
  login: (email: string, password: string) => apiPost<TokenOut>("/auth/login", { email, password }),
  logout: () => apiPost<void>("/auth/logout", undefined),
  me: (signal?: AbortSignal) => apiGet<MeOut>("/me", {}, signal),
};
