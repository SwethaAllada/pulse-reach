"""Pydantic v2 request and response schemas for `/api/v1/*` (`app.schemas.v1`)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RulesSummaryOut(BaseModel):
    total_rules: int
    authoritative_rules: int
    review_flagged_rules: int
    unresolved_rules: int
    total_rule_items: int
    clinical_review_status: str


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
    evaluation_status_counts: dict[str, int]
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


class PaginatedPatientsOut(BaseModel):
    is_synthetic: bool = True
    total: int
    limit: int
    offset: int
    items: list[PatientSummaryOut]


class EvaluationReasonOut(BaseModel):
    reason_ordinal: int
    reason_code: str
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
    evaluation_status: str
    reason_code: str | None = None
    next_due_date: date | None = None
    evaluated_at: datetime
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
    facility_id: int
    facility_name: str
    region_id: int
    facility_type: str
    license_status: str
    simulated_ifhas_service: bool | None = None
    simulated_wcv_service: bool | None = None
    capability_basis: str = "simulated_overlay_only"


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
