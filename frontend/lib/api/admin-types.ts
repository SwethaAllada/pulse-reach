/* Administration (`/api/v1/admin/*`, `/audit-events`) — mirrors backend `app/schemas/identity.py`. */

export type AssignableRole = "SYSTEM_ADMIN" | "POPULATION_HEALTH_MANAGER" | "CARE_COORDINATOR" | "CLINICIAN";
export type PatientAccess = "assigned" | "organization";

export interface Page<T> {
  total: number;
  limit: number;
  offset: number;
  items: T[];
}

export interface MemberOut {
  user_id: string;
  email: string;
  full_name: string;
  preferred_language: "en" | "ar";
  account_active: boolean;
  role: string;
  patient_access: PatientAccess;
  membership_active: boolean;
  password_set: boolean;
}

/** `GET /admin/assignments/staff` (assignments.manage): only what choosing an assignee needs. */
export interface AssignableStaffOut {
  user_id: string;
  full_name: string;
  role: string;
}

export interface StaffCreateIn {
  email: string;
  full_name: string;
  role: AssignableRole;
  patient_access?: PatientAccess | null;
  preferred_language?: "en" | "ar";
}

export interface OneTimeTokenOut {
  purpose: "activation" | "password_reset";
  token: string;
  expires_at: string;
  delivery: string;
}

export interface StaffCreateOut {
  member: MemberOut;
  activation: OneTimeTokenOut;
}

export interface MemberUpdateIn {
  full_name?: string;
  role?: AssignableRole;
  patient_access?: PatientAccess;
  membership_active?: boolean;
}

export interface AccountStatusOut {
  user_id: string;
  scope: "account" | "membership";
  active: boolean;
}

export interface AssignmentOut {
  assignment_id: string;
  organization_id: string;
  staff_user_id: string;
  patient_id: string;
  is_active: boolean;
  created_at: string;
  created_by: string | null;
  ended_at?: string | null;
}

export interface PatientLinkOut {
  link_id: string;
  user_id: string;
  patient_id: string;
  organization_id: string;
  status: "active" | "revoked";
  verification_method: string;
  verified_at: string;
  revoked_at?: string | null;
}

export interface AuditEventOut {
  event_id: string;
  occurred_at: string;
  request_id: string | null;
  actor_user_id: string | null;
  actor_role: string | null;
  organization_id: string | null;
  permission: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  patient_id: string | null;
  outcome: "success" | "denied" | "failed";
  status_code: number | null;
  details: Record<string, unknown>;
}

export interface AuditQuery {
  action?: string;
  resource_type?: string;
  outcome?: "success" | "denied" | "failed";
  limit: number;
  offset: number;
}

/* Population aggregation operations (`/population/updates`, `/population/config`, `/population/refresh`). */
export interface AggregationRunOut {
  run_id: string;
  status: string;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  engine_version: string;
  data_version: string | null;
  config_version: number | null;
  source_run_id: string | null;
  as_of: string | null;
  complete_through: string | null;
  latest_data_at: string | null;
  error_code: string | null;
  summary: Record<string, unknown>;
}

export interface PopulationUpdatesOut {
  aggregation_status: string;
  last_aggregation_at: string | null;
  latest_aggregated_data_at: string | null;
  data_changed_since_aggregation: boolean | null;
  staleness_seconds: number | null;
  stale: boolean | null;
  latest_run: AggregationRunOut | null;
  dataset_version: Record<string, unknown>;
  recommended_poll_seconds: Record<string, number>;
}

export interface PopulationConfigOut {
  organization_scope: string;
  version: number;
  is_default: boolean;
  updated_at: string | null;
  updated_by: string | null;
  thresholds: Record<string, unknown>;
  min_cell_size: number;
}
