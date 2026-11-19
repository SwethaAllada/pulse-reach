"""Pydantic v2 request and response schemas for `/api/v1/*` (`app.schemas.v1`)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class RulesSummaryOut(BaseModel):
    total_rules: int
    authoritative_rules: int
    review_flagged_rules: int
    unresolved_rules: int
    total_rule_items: int
    clinical_review_status: str


class PathwayBreakdownOut(BaseModel):
    patients_with_history: int = 0
    eligible_or_due_patients: int = 0
    unknown_history_patients: int = 0
    review_flagged_patients: int = 0
    open_care_gaps_count: int = 0


class RegionBreakdownOut(BaseModel):
    region_id: int
    total_patients: int = 0
    open_care_gaps_count: int = 0


class DashboardSummaryOut(BaseModel):
    is_synthetic: bool = True
    run_id: str
    evaluation_run_id: str
    reference_date: date
    total_patients: int
    n_adults: int
    n_children: int
    open_care_gaps_count: int
    closed_refused_care_gaps_count: int
    unknown_history_patients_count: int = 0
    review_flagged_patients_count: int = 0
    evaluation_status_counts: dict[str, int]
    patient_status_counts: dict[str, int] = Field(default_factory=dict)
    pathway_breakdown: dict[str, PathwayBreakdownOut] = Field(default_factory=dict)
    gaps_by_type: dict[str, int] = Field(default_factory=dict)
    gaps_by_pathway: dict[str, int] = Field(default_factory=dict)
    region_breakdown: list[RegionBreakdownOut] = Field(default_factory=list)
    rules_summary: RulesSummaryOut
    governance_disclaimer: str


class PatientSummaryOut(BaseModel):
    patient_id: str
    run_id: str
    is_synthetic: bool = True
    emirates_id_synthetic: str
    given_name: str
    family_name: str
    date_of_birth: date | None
    sex: str | None
    nationality_group: str | None
    region_id: int
    district_label: str | None
    thiqa_member: bool | None
    ever_smoked: bool | None
    preferred_language: str
    preferred_channel: str
    contact_status: str
    date_of_death: date | None
    history_by_pathway: dict[str, str]
    open_care_gaps_count: int = 0
    evaluation_summary: dict[str, int] = Field(default_factory=dict)


class PaginatedPatientsOut(BaseModel):
    is_synthetic: bool = True
    total: int
    limit: int
    offset: int
    items: list[PatientSummaryOut]


class EvaluationReasonOut(BaseModel):
    reason_ordinal: int
    reason_code: str
    reason_detail: str | None = None
    guard_id: str | None = None
    item_category: str | None = None
    item_code: str | None = None


class EvaluationItemOut(BaseModel):
    evaluation_id: str
    patient_id: str
    rule_id: str
    rule_version: str
    pathway: str
    rule_type: str | None = None
    source_name: str | None = None
    source_version: str | None = None
    source_reference: str | None = None
    is_authoritative: bool = False
    requires_clinical_review: bool = False
    engine_version: str | None = None
    look_ahead_days: int | None = None
    evaluation_status: str
    reason_code: str | None = None
    reason_detail: str | None = None
    next_due_date: date | None = None
    evaluated_at: datetime
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    reasons: list[EvaluationReasonOut] = Field(default_factory=list)


class CareGapOut(BaseModel):
    care_gap_id: str
    patient_id: str
    evaluation_id: str
    rule_id: str
    rule_version: str
    gap_type: str
    status: str
    identified_date: date
    closed_date: date | None = None
    closed_by_consent_id: str | None = None
    closed_by_component_result_id: str | None = None
    subject_ifhas_screening_id: str | None = None
    subject_well_child_visit_id: str | None = None
    subject_referral_id: str | None = None
    priority_score: float | None = None
    priority_explanation: str | None = None
    scoring_suppressed_reason: str | None = None
    is_synthetic: bool = True


class PatientEvaluationsOut(BaseModel):
    is_synthetic: bool = True
    patient_id: str
    evaluation_run_id: str
    reference_date: date
    evaluations: list[EvaluationItemOut]
    care_gaps: list[CareGapOut]


class EvaluateRequestIn(BaseModel):
    patient_id: str
    look_ahead_days: int | None = Field(default=30, ge=0, le=365)


class RuleItemOut(BaseModel):
    category: str
    code: str
    code_origin: str
    ordinal: int
    description: str
    source_reference: str
    verification_status: str
    status_is_verified: bool
    effective_authority: bool
    open_question_ids: list[str] = Field(default_factory=list)


class RuleSummaryOut(BaseModel):
    rule_id: str
    rule_version: str
    pathway: str
    rule_type: str | None
    source_name: str
    source_version: str
    source_reference: str
    verification_status: str
    requires_clinical_review: bool
    is_authoritative: bool
    effective_date_text: str | None
    effective_date_precision: str
    effective_date_from: date | None
    description: str
    open_question_ids: list[str] = Field(default_factory=list)


class RuleDetailOut(RuleSummaryOut):
    effective_date_note: str | None = None
    notes: str | None = None
    spec: dict[str, Any]
    items: list[RuleItemOut] = Field(default_factory=list)


class PaginatedRulesOut(BaseModel):
    total: int
    items: list[RuleSummaryOut]


class PaginatedCareGapsOut(BaseModel):
    is_synthetic: bool = True
    total: int
    limit: int
    offset: int
    items: list[CareGapOut]


class FacilityItemOut(BaseModel):
    facility_id: int | None = None
    ch_fid: str | None = None
    source_object_id: int | None = None
    source_layer: str | None = None
    facility_name: str | None = None
    region_id: int | None = None
    facility_type: str | None = None
    license_status: str | None = None
    simulated_ifhas_service: bool | None = None
    simulated_wcv_service: bool | None = None
    capability_basis: str = "unverified_sdi_facts_only"


class PaginatedFacilitiesOut(BaseModel):
    governance_notice: str
    total: int
    limit: int
    offset: int
    items: list[FacilityItemOut]


class ExplanationRequestIn(BaseModel):
    patient_id: str
    rule_id: str


class ExplanationOut(BaseModel):
    synthetic_patient_id: str
    rule_id: str
    rule_version: str
    evaluation_status: str
    is_authoritative: bool
    is_synthetic: bool = True
    generation_mode: str
    summary_text: str
    why_text: str
    missing_or_uncertain_text: str
    rule_citation_text: str
    warnings: list[str]


class OutreachPreviewRequestIn(BaseModel):
    patient_id: str
    rule_id: str
    channel: Literal["sms", "phone", "email", "app"] = "sms"
    language: Literal["ar", "en"] = "en"


class OutreachPreviewOut(BaseModel):
    synthetic_patient_id: str
    care_gap_id: str | None
    rule_id: str
    rule_version: str
    allowed: bool
    simulated_only: bool = True
    blocked_reason: str | None
    preview_message: str | None
    disclaimer: str


class GuardianOut(BaseModel):
    guardian_id: str
    patient_id: str
    relationship: str
    given_name: str
    family_name: str
    preferred_language: str
    preferred_channel: str
    contact_status: str
    is_synthetic: bool = True


class HistoryAvailabilityOut(BaseModel):
    history_id: str
    pathway: str
    history_status: str
    as_of_date: date
    note: str | None = None
    is_synthetic: bool = True


class IfhasScreeningOut(BaseModel):
    screening_id: str
    rule_id: str
    rule_version: str
    profile_id: str
    appointment_id: str | None = None
    performed_date: date | None = None
    completion_status: str
    results_communicated_date: date | None = None
    journey_reported_date: date | None = None
    has_abnormal_finding: bool | None = None
    is_synthetic: bool = True


class WellChildVisitOut(BaseModel):
    visit_id: str
    rule_id: str
    rule_version: str
    guardian_id: str
    profile_id: str
    appointment_id: str | None = None
    performed_date: date | None = None
    attendance_status: str
    is_catch_up_visit: bool
    is_synthetic: bool = True


class ComponentResultOut(BaseModel):
    component_result_id: str
    rule_id: str
    rule_version: str
    ifhas_screening_id: str | None = None
    well_child_visit_id: str | None = None
    item_category: str
    item_code: str
    result_status: str
    performed_date: date | None = None
    documented_in_record: bool | None = None
    signature_on_file: bool | None = None
    refused_by_guardian_id: str | None = None
    refusal_reason: str | None = None
    is_synthetic: bool = True


class AssessmentOut(BaseModel):
    assessment_id: str
    ifhas_screening_id: str | None = None
    well_child_visit_id: str | None = None
    instrument: str
    instrument_version: str | None = None
    administered_date: date
    raw_score: float | None = None
    item_responses: dict[str, Any] | None = None
    rule_id: str | None = None
    rule_version: str | None = None
    is_synthetic: bool = True


class PatientHistoryOut(BaseModel):
    is_synthetic: bool = True
    patient_id: str
    guardians: list[GuardianOut] = Field(default_factory=list)
    history_availability: list[HistoryAvailabilityOut] = Field(default_factory=list)
    ifhas_screenings: list[IfhasScreeningOut] = Field(default_factory=list)
    well_child_visits: list[WellChildVisitOut] = Field(default_factory=list)
    component_results: list[ComponentResultOut] = Field(default_factory=list)
    assessments: list[AssessmentOut] = Field(default_factory=list)


class ConsentRecordOut(BaseModel):
    consent_id: str
    patient_id: str
    guardian_id: str | None = None
    consent_type: str
    state: str
    applies_to: str
    scope_pathway: str | None = None
    scope_rule_id: str | None = None
    scope_rule_version: str | None = None
    recorded_at: datetime
    recorded_by: str
    documented_in_record: bool | None = None
    signature_on_file: bool | None = None
    refusal_reason: str | None = None
    is_synthetic: bool = True


class PatientConsentsOut(BaseModel):
    is_synthetic: bool = True
    patient_id: str
    current_states: list[ConsentRecordOut] = Field(default_factory=list)
    history: list[ConsentRecordOut] = Field(default_factory=list)


class AppointmentOut(BaseModel):
    appointment_id: str
    patient_id: str
    profile_id: str
    care_gap_id: str | None = None
    appointment_type: str
    scheduled_datetime: datetime
    slot_type: str
    status: str
    booked_via: str
    is_synthetic: bool = True


class ReferralOut(BaseModel):
    referral_id: str
    patient_id: str
    trigger_rule_id: str
    trigger_rule_version: str
    referral_target: str
    target_profile_id: str | None = None
    trigger_date: date
    initiated_date: date | None = None
    completed_date: date | None = None
    status: str
    is_synthetic: bool = True


class OutreachEventOut(BaseModel):
    outreach_id: str
    patient_id: str
    care_gap_id: str
    guardian_id: str | None = None
    recipient: str
    event_type: str
    channel: str
    sent_datetime: datetime | None = None
    delivery_status: str
    suppression_reason: str | None = None
    contact_consent_id: str | None = None
    response: str | None = None
    appointment_id: str | None = None
    is_synthetic: bool = True


class FollowUpEventOut(BaseModel):
    follow_up_id: str
    patient_id: str
    care_gap_id: str
    event_type: str
    outcome_status: str | None = None
    documented_evidence: bool = False
    evidence_reference: str | None = None
    contact_consent_id: str | None = None
    suppression_reason: str | None = None
    recorded_by: str
    recorded_at: datetime
    note: str | None = None
    is_synthetic: bool = True


class FollowUpCreateIn(BaseModel):
    event_type: Literal[
        "outreach_attempted",
        "completion_documented",
        "note_recorded",
    ]
    close_gap: bool = False
    documented_evidence: bool = False
    evidence_reference: str | None = None
    recorded_by: str = Field(min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def _validate_close_gap_event_type(self) -> "FollowUpCreateIn":
        if self.close_gap and self.event_type != "completion_documented":
            raise ValueError("close_gap=True is only allowed with event_type='completion_documented'.")
        return self


class AppointmentCreateIn(BaseModel):
    patient_id: str
    profile_id: str
    care_gap_id: str | None = None
    appointment_type: Literal["ifhas_screening", "well_child_visit", "referral_visit", "other"]
    scheduled_datetime: datetime
    slot_type: Literal["weekday", "evening", "weekend"] = "weekday"
    booked_via: str = Field(default="clinician_portal", min_length=1)


class AppointmentPatchIn(BaseModel):
    status: Literal[
        "scheduled",
        "attended",
        "no_show",
        "cancelled_by_patient",
        "cancelled_by_facility",
        "rescheduled",
    ]
    scheduled_datetime: datetime | None = None


class PaginatedAppointmentsOut(BaseModel):
    is_synthetic: bool = True
    total: int
    limit: int
    offset: int
    items: list[AppointmentOut]


class ReferralCreateIn(BaseModel):
    patient_id: str
    ifhas_screening_id: str | None = None
    well_child_visit_id: str | None = None
    assessment_id: str | None = None
    trigger_rule_id: str
    trigger_rule_version: str
    referral_target: str = Field(min_length=1)
    target_profile_id: str | None = None
    trigger_date: date
    initiated_date: date | None = None
    status: Literal["pending", "initiated"] = "pending"


class ReferralPatchIn(BaseModel):
    status: Literal["pending", "initiated", "completed", "declined", "cancelled"]
    initiated_date: date | None = None
    completed_date: date | None = None


class PaginatedReferralsOut(BaseModel):
    is_synthetic: bool = True
    total: int
    limit: int
    offset: int
    items: list[ReferralOut]


class CareGapDetailOut(CareGapOut):
    patient: PatientSummaryOut
    rule: RuleSummaryOut
    reasons: list[EvaluationReasonOut] = Field(default_factory=list)
    linked_appointments: list[AppointmentOut] = Field(default_factory=list)
    linked_referrals: list[ReferralOut] = Field(default_factory=list)
    linked_outreach_events: list[OutreachEventOut] = Field(default_factory=list)
    follow_up_events: list[FollowUpEventOut] = Field(default_factory=list)
    facility_capability_notice: str = (
        "Facility capability and service profile references are simulated overlays only; "
        "real facility IFHAS/WCV capabilities remain unknown unless backed by an approved source."
    )
