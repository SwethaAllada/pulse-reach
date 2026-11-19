"""Pydantic v2 request and response schemas for `/api/v1/*` (`app.schemas.v1`)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Accountable actor for every write (audit trail); blank values are rejected.
Actor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


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
    superseded_by_completion: bool = Field(
        default=False,
        description=(
            "True when a care gap produced by this evaluation was later closed as "
            "'closed_completed'. The evaluation remains the unchanged historical result of its "
            "evaluation run and reference date; the care gap holds the current state."
        ),
    )
    superseded_by_care_gap_id: str | None = None
    applicability: Literal["in_band", "out_of_band", "not_determined"] = Field(
        default="not_determined",
        description=(
            "Whether the person is inside the rule's printed age/sex band (or, for rules without "
            "one, the pathway's programme scope). Never assumed: missing attributes or bands give "
            "'not_determined'."
        ),
    )
    applicability_basis: Literal["rule_band", "programme_scope"] | None = None
    review_origin: Literal["rule", "record"] | None = Field(
        default=None,
        description=(
            "For requires_clinical_review only: 'rule' when the rule itself is unresolved or "
            "review-flagged, 'record' when the person's records need review."
        ),
    )


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
    closed_by_ifhas_screening_id: str | None = None
    closed_by_well_child_visit_id: str | None = None
    closed_by_referral_id: str | None = None
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
    city: str | None = None
    facility_type: str | None = None
    category: str | None = None
    license_status: str | None = None
    is_public: bool | None = None
    latitude: float | None = None
    longitude: float | None = None
    geo_quality: str | None = None
    simulated_ifhas_service: bool | None = None
    simulated_wcv_service: bool | None = None
    capability_basis: str = "unverified_sdi_facts_only"


class FacilityDetailOut(FacilityItemOut):
    """All published SDI facts for one facility. Programme capability is not published."""

    governance_notice: str
    facility_name_ar: str | None = None
    subtype: str | None = None
    license_no: str | None = None
    has_insurance: bool | None = None
    inpatient_bed_capacity: int | None = None
    specialities_raw: str | None = None
    professionals_raw: str | None = None
    emergency_department: bool | None = None
    pediatric_emergency_department: bool | None = None
    maternity_emergency_care: bool | None = None
    home_care_services: bool | None = None
    source_effective_date: date | None = None


class PaginatedFacilitiesOut(BaseModel):
    governance_notice: str
    total: int
    limit: int
    offset: int
    items: list[FacilityItemOut]


class ExplanationRequestIn(BaseModel):
    patient_id: str
    rule_id: str


class AIGenerationOut(BaseModel):
    """Provenance of an AI-assisted text: prompt/model version and why a fallback was used."""

    generation_mode: Literal["llm_grounded", "deterministic_fallback"]
    prompt_version: str
    provider: str | None = None
    model: str | None = None
    fallback_reason: str | None = None
    violations: list[str] = Field(default_factory=list)
    audit_id: str


class OutreachDraftOut(BaseModel):
    synthetic_patient_id: str
    care_gap_id: str | None
    rule_id: str
    rule_version: str
    allowed: bool
    simulated_only: bool = True
    sendable: bool = Field(default=False, description="Always false: PulseReach never sends messages.")
    blocked_reason: str | None
    draft_message: str | None
    disclaimer: str
    ai: AIGenerationOut | None = None


class PopulationInsightOut(BaseModel):
    is_synthetic: bool = True
    facts: dict[str, Any]
    summary_text: str
    disclaimer: str
    ai: AIGenerationOut


class AIStatusOut(BaseModel):
    llm_enabled: bool
    status: str
    provider: str | None = None
    model: str | None = None
    prompt_versions: dict[str, str]


class AIAuditRecordOut(BaseModel):
    audit_id: str
    recorded_at: datetime
    request_id: str | None = None
    feature: str
    subject: dict[str, Any]
    prompt_version: str
    provider: str | None = None
    model: str | None = None
    generation_mode: str
    fallback_reason: str | None = None
    violations: list[str] = Field(default_factory=list)
    input_sha256: str | None = None
    output_sha256: str | None = None
    latency_ms: float | None = None


class AIAuditOut(BaseModel):
    items: list[AIAuditRecordOut]


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
    ai: AIGenerationOut | None = None


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
    appointment_id: str | None = None
    referral_id: str | None = None
    is_synthetic: bool = True


class WorkflowStatusEventOut(BaseModel):
    """One append-only appointment/referral status change (`from_status` is null on creation)."""

    status_event_id: str
    patient_id: str
    entity_type: Literal["appointment", "referral"]
    appointment_id: str | None = None
    referral_id: str | None = None
    care_gap_id: str | None = None
    from_status: str | None = None
    to_status: str
    scheduled_datetime: datetime | None = None
    initiated_date: date | None = None
    completed_date: date | None = None
    recorded_by: str
    recorded_at: datetime
    note: str | None = None
    is_synthetic: bool = True


class WorkflowHistoryOut(BaseModel):
    is_synthetic: bool = True
    entity_type: Literal["appointment", "referral"]
    entity_id: str
    items: list[WorkflowStatusEventOut]


class PaginatedFollowUpEventsOut(BaseModel):
    is_synthetic: bool = True
    total: int
    limit: int
    offset: int
    items: list[FollowUpEventOut]


class PatientActivityOut(BaseModel):
    """Audit trail of every follow-up and workflow write recorded for one patient."""

    is_synthetic: bool = True
    patient_id: str
    follow_up_events: list[FollowUpEventOut] = Field(default_factory=list)
    workflow_events: list[WorkflowStatusEventOut] = Field(default_factory=list)


class FollowUpCreateIn(BaseModel):
    event_type: Literal[
        "outreach_attempted",
        "completion_documented",
        "note_recorded",
    ]
    close_gap: bool = False
    documented_evidence: bool = False
    evidence_reference: str | None = None
    recorded_by: Actor
    note: str | None = None

    @model_validator(mode="after")
    def _validate_close_gap_event_type(self) -> "FollowUpCreateIn":
        if self.close_gap != (self.event_type == "completion_documented"):
            raise ValueError(
                "close_gap=True is required for, and only allowed with, "
                "event_type='completion_documented'."
            )
        return self


class AppointmentCreateIn(BaseModel):
    patient_id: str
    profile_id: str
    care_gap_id: str | None = None
    appointment_type: Literal["ifhas_screening", "well_child_visit", "referral_visit", "other"]
    scheduled_datetime: datetime
    slot_type: Literal["weekday", "evening", "weekend"] = "weekday"
    booked_via: str = Field(default="clinician_portal", min_length=1)
    recorded_by: Actor
    note: str | None = None


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
    recorded_by: Actor
    note: str | None = None

    @model_validator(mode="after")
    def _validate_reschedule(self) -> "AppointmentPatchIn":
        if (self.status == "rescheduled") != (self.scheduled_datetime is not None):
            raise ValueError(
                "scheduled_datetime is required for, and only allowed with, status='rescheduled'."
            )
        return self


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
    care_gap_id: str | None = None
    recorded_by: Actor
    note: str | None = None


class ReferralPatchIn(BaseModel):
    status: Literal["pending", "initiated", "completed", "declined", "cancelled"]
    initiated_date: date | None = None
    completed_date: date | None = None
    recorded_by: Actor
    note: str | None = None


class PaginatedReferralsOut(BaseModel):
    is_synthetic: bool = True
    total: int
    limit: int
    offset: int
    items: list[ReferralOut]


class RecommendedPathwayOut(BaseModel):
    """Next step documented by the rule's source standard (verbatim, never inferred)."""

    status: Literal["documented_next_step", "requires_clinical_review", "no_documented_pathway"]
    next_step: str | None = None
    description: str
    rule_id: str
    rule_version: str
    source_reference: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    related_rule_ids: list[str] = Field(default_factory=list)
    notice: str


class CareGapReviewIn(BaseModel):
    reviewer: Actor
    action: Literal["confirmed", "dismissed", "priority_overridden"]
    reason: Actor
    new_priority: float | None = None


class CareGapReviewOut(BaseModel):
    review_id: str
    care_gap_id: str
    reviewer: str
    action: str
    previous_priority: float | None = None
    new_priority: float | None = None
    reason: str
    reviewed_at: datetime
    is_synthetic: bool = True


class CareGapReviewsOut(BaseModel):
    is_synthetic: bool = True
    care_gap_id: str
    items: list[CareGapReviewOut]


class OpenQuestionOut(BaseModel):
    oq_id: str
    category: str
    status: str
    title: str
    detail: str
    affects: list[str] = Field(default_factory=list)
    resolve_via: str | None = None
    resolution: str | None = None
    resolved_on: date | None = None
    rule_ids: list[str] = Field(default_factory=list)


class PaginatedOpenQuestionsOut(BaseModel):
    total: int
    items: list[OpenQuestionOut]


class CareGapDetailOut(CareGapOut):
    patient: PatientSummaryOut
    rule: RuleSummaryOut
    reasons: list[EvaluationReasonOut] = Field(default_factory=list)
    linked_appointments: list[AppointmentOut] = Field(default_factory=list)
    linked_referrals: list[ReferralOut] = Field(default_factory=list)
    linked_outreach_events: list[OutreachEventOut] = Field(default_factory=list)
    follow_up_events: list[FollowUpEventOut] = Field(default_factory=list)
    workflow_events: list[WorkflowStatusEventOut] = Field(default_factory=list)
    reviews: list[CareGapReviewOut] = Field(default_factory=list)
    recommended_pathway: RecommendedPathwayOut | None = None
    facility_capability_notice: str = (
        "Facility service profiles are simulated (synthetic); real facility IFHAS/WCV capabilities "
        "are not published by the SDI register and remain unknown."
    )
