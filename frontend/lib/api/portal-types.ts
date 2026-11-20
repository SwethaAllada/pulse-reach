/* Patient portal (`/api/v1/portal/*`) — mirrors backend `app/schemas/portal.py`. Patient-facing
   responses carry localized `*_label` / `*_display` fields; the UI renders those, never raw codes. */

export interface Localized {
  locale: "en" | "ar";
  direction: "ltr" | "rtl";
}

export interface PortalProfileOut extends Localized {
  patient_id: string;
  given_name: string;
  family_name: string;
  date_of_birth: string | null;
  date_of_birth_display: string | null;
  sex: string | null;
  preferred_language: string;
  preferred_channel: string;
  region_id: number;
  is_synthetic: boolean;
  open_recommendations: number;
  upcoming_appointments: number;
  open_follow_ups: number;
  awaiting_your_reply: number;
  open_requests: number;
}

export interface ScreeningItemOut {
  kind: "screening" | "well_child_visit";
  programme: string;
  programme_label: string;
  performed_date: string | null;
  performed_date_display: string | null;
  status: string;
  status_label: string;
  results_communicated_date?: string | null;
}

export interface HealthSummaryOut extends Localized {
  patient_id: string;
  history: { programme: string; programme_label: string; status: string; status_label: string }[];
  events: ScreeningItemOut[];
  is_synthetic: boolean;
  disclaimer: string;
}

export interface RecommendationOut {
  recommendation_id: string;
  rule_id: string;
  programme: string;
  programme_label: string;
  gap_type: string;
  title: string;
  description: string;
  status: string;
  status_label: string;
  identified_date: string;
  identified_date_display: string;
  closed_date?: string | null;
  next_step: string | null;
  next_step_text: string;
}

export interface RecommendationsOut extends Localized {
  total: number;
  items: RecommendationOut[];
}

export interface RecommendationDetailOut extends Localized, RecommendationOut {
  evidence: string[];
  history: { occurred_on: string; occurred_on_display: string; event: string; label: string }[];
  related_follow_up_ids: string[];
  disclaimer: string;
}

export interface PortalAppointmentOut {
  appointment_id: string;
  appointment_type: string;
  appointment_type_label: string;
  scheduled_datetime: string;
  scheduled_display: string;
  status: string;
  status_label: string;
  recommendation_id: string | null;
  can_request_change: boolean;
}

export interface PortalAppointmentsOut extends Localized {
  total: number;
  items: PortalAppointmentOut[];
}

export interface PortalReferralOut {
  referral_id: string;
  referral_target: string;
  status: string;
  status_label: string;
  trigger_date: string;
  initiated_date: string | null;
  completed_date: string | null;
}

export interface PortalReferralsOut extends Localized {
  total: number;
  items: PortalReferralOut[];
}

export type TimeOfDay = "morning" | "afternoon" | "evening";
export type PatientResponse = "will_book" | "already_done" | "need_help" | "not_interested" | "question";

export interface AppointmentRequestIn {
  recommendation_id?: string | null;
  follow_up_id?: string | null;
  preferred_dates?: string[];
  preferred_time_of_day?: TimeOfDay | null;
  message?: string | null;
}

export interface AppointmentChangeIn {
  action: "cancel" | "reschedule";
  preferred_dates?: string[];
  preferred_time_of_day?: TimeOfDay | null;
  message?: string | null;
}

export interface PatientRequestOut {
  request_id: string;
  request_type: string;
  request_type_label: string;
  status: string;
  status_label: string;
  follow_up_id: string | null;
  recommendation_id: string | null;
  appointment_id: string | null;
  change_action: string | null;
  preferred_dates: string[];
  preferred_time_of_day: string | null;
  message: string | null;
  staff_response: string | null;
  created_at: string;
  updated_at: string;
}

export interface PatientRequestDetailOut extends Localized, PatientRequestOut {
  confirmation?: string | null;
}

export interface PatientRequestsOut extends Localized {
  total: number;
  items: PatientRequestOut[];
}

export interface TaskEventPatientOut {
  event_id: string;
  event_type: string;
  label: string;
  created_at: string;
  created_display: string;
  from_status?: string | null;
  to_status?: string | null;
  response?: string | null;
  response_label?: string | null;
  message?: string | null;
  from_care_team: boolean;
}

export interface PortalFollowUpOut {
  follow_up_id: string;
  recommendation_id: string | null;
  status: string;
  status_label: string;
  message: string;
  due_date: string | null;
  due_date_display: string | null;
  is_overdue: boolean;
  reported_completion_pending_verification: boolean;
  created_at: string;
  updated_at: string;
}

export interface PortalFollowUpsOut extends Localized {
  total: number;
  items: PortalFollowUpOut[];
}

export interface PortalFollowUpDetailOut extends Localized, PortalFollowUpOut {
  history: TaskEventPatientOut[];
  confirmation?: string | null;
}
