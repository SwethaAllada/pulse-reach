import type {
  CareGapOut,
  DashboardSummaryOut,
  ExplanationOut,
  Paginated,
  PaginatedRulesOut,
  PatientEvaluationsOut,
  PatientQuery,
  PatientSummaryOut,
  RuleDetailOut,
} from "./types";

/** Backend base URL; `.env.example` documents the local default. */
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
    readonly path: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type QueryValue = string | number | undefined;

async function apiGet<T>(path: string, query: Record<string, QueryValue> = {}, signal?: AbortSignal): Promise<T> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined) params.set(k, String(v));
  const qs = params.toString();
  return apiRequest<T>(path, `${path}${qs ? `?${qs}` : ""}`, { signal });
}

async function apiRequest<T>(path: string, pathWithQuery: string, init: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}/api/v1${pathWithQuery}`;
  let res: Response;
  try {
    res = await fetch(url, { ...init, headers: { Accept: "application/json", ...init.headers } });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(`Could not reach the PulseReach API at ${API_BASE_URL}.`, null, path);
  }
  if (!res.ok) throw new ApiError(`The API responded ${res.status} for ${path}.`, res.status, path);
  return (await res.json()) as T;
}

/** Reads every page of a paginated endpoint so aggregates cover the full result set. */
async function getAllPages<T>(
  path: string,
  query: Record<string, QueryValue>,
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
  rules: (signal?: AbortSignal) => apiGet<PaginatedRulesOut>("/rules", {}, signal),
  /** Backend-filtered (`pathway`, `region_id`, `sex`), all pages. */
  allPatients: (query: PatientQuery, signal?: AbortSignal) =>
    getAllPages<PatientSummaryOut>("/patients", { ...query }, signal),
  allCareGaps: (signal?: AbortSignal) => getAllPages<CareGapOut>("/care-gaps", {}, signal),
  /** One backend page of `/patients` (filters + `limit`/`offset`). */
  patientsPage: (query: PatientQuery & { limit: number; offset: number }, signal?: AbortSignal) =>
    apiGet<Paginated<PatientSummaryOut>>("/patients", { ...query }, signal),
  patient: (id: string, signal?: AbortSignal) =>
    apiGet<PatientSummaryOut>(`/patients/${encodeURIComponent(id)}`, {}, signal),
  patientEvaluations: (id: string, signal?: AbortSignal) =>
    apiGet<PatientEvaluationsOut>(`/patients/${encodeURIComponent(id)}/evaluations`, {}, signal),
  ruleDetail: (id: string, signal?: AbortSignal) =>
    apiGet<RuleDetailOut>(`/rules/${encodeURIComponent(id)}`, {}, signal),
  explanation: (patientId: string, ruleId: string, signal?: AbortSignal) =>
    apiRequest<ExplanationOut>("/explanations", "/explanations", {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patient_id: patientId, rule_id: ruleId }),
    }),
};
