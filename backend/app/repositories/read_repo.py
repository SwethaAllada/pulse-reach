"""Read repositories supporting `DATA_SOURCE=memory` and `DATA_SOURCE=db` (`T-03`)."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any, Protocol

from fastapi import HTTPException
from sqlalchemy import func, or_, select, true
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.clinical import (
    OpenQuestion,
    Rule,
    RuleItem,
    RuleItemOpenQuestion,
    RuleLoad,
    RuleOpenQuestion,
    Standard,
)
from app.models.official import Facility
from app.models.synthetic import (
    Appointment,
    Assessment,
    CareGap,
    CareGapFollowUpEvent,
    CareGapReview,
    WorkflowStatusEvent,
    ComponentResult,
    Consent,
    EligibilityEvaluation,
    EvaluationReason,
    EvaluationRun,
    GenerationRun,
    Guardian,
    HistoryAvailability,
    IfhasScreening,
    OutreachEvent,
    Patient,
    Referral,
    WellChildVisit,
)
from app.schemas.v1 import (
    CareGapReviewOut,
    FacilityDetailOut,
    OpenQuestionOut,
    PaginatedOpenQuestionsOut,
    RecommendedPathwayOut,
    AppointmentOut,
    AssessmentOut,
    CareGapDetailOut,
    CareGapOut,
    ComponentResultOut,
    ConsentRecordOut,
    DashboardSummaryOut,
    EvaluationItemOut,
    EvaluationReasonOut,
    FacilityItemOut,
    FollowUpEventOut,
    GuardianOut,
    HistoryAvailabilityOut,
    IfhasScreeningOut,
    OutreachEventOut,
    PaginatedCareGapsOut,
    PaginatedFacilitiesOut,
    PaginatedPatientsOut,
    PaginatedRulesOut,
    PathwayBreakdownOut,
    PatientConsentsOut,
    PatientEvaluationsOut,
    PatientHistoryOut,
    PatientSummaryOut,
    ReferralOut,
    RegionBreakdownOut,
    RuleDetailOut,
    RuleItemOut,
    RulesSummaryOut,
    RuleSummaryOut,
    WellChildVisitOut,
)
from app.services.clinical_loader.parse import (
    ParsedClinicalBundle,
    parse_clinical_bundle,
    repo_root,
)
from app.services.evaluation import (
    AssessmentFact,
    ComponentResultFact,
    ConsentFact,
    EvaluationEngine,
    PatientContext,
    ReferralFact,
    ScreeningEventFact,
    VisitEventFact,
)
from app.services.evaluation.recorded import (
    SNAPSHOT_RECONSTRUCTED,
    SNAPSHOT_RECORDED,
    build_safe_input_snapshot_from_context,
    compute_age_parts as _compute_age_parts,
    describe_reason,
)
from app.services.official_loader import parse as official_parse
from app.services.care_pathway import (
    recommended_pathway,
    review_origin,
    rule_applicability,
    rules_index,
)
from app.services.synthetic_generator import (
    SyntheticDataset,
    generate_synthetic_dataset,
)

logger = logging.getLogger(__name__)


def _db_query_failed(exc: Exception) -> HTTPException:
    """Generic 503 for a failed read; the database error is logged, never returned (F-19)."""
    logger.error("PostgreSQL read failed: %s", type(exc).__name__, exc_info=exc)
    return HTTPException(status_code=503, detail="PostgreSQL query failed.")


_GOVERNANCE_DISCLAIMER = (
    "All patient records shown are 100% synthetic (`is_synthetic=true`). Clinical rules are "
    "transcribed from published DoH standards for engineering use (`clinical_review_status=not_reviewed`) "
    "and require healthcare-professional review."
)
_FACILITY_NOTICE = (
    "Official SDI facility register: names, types, regions, licence status and point locations "
    "as published (usable coordinates only where geo_quality is 'ok'). Preventive-programme "
    "service capability (IFHAS / Well-Child) is not published by this source and is unknown "
    "(Decision D13 pending)."
)


# `patient_ids` (when not None) restricts results to the caller's authorized patients; it is
# applied before counting and pagination so totals never include other organizations' records.
class ReadRepository(Protocol):
    def get_dashboard_summary(self, patient_ids: frozenset[str] | None = None) -> DashboardSummaryOut: ...
    def list_patients(
        self,
        limit: int,
        offset: int,
        sex: str | None,
        region_id: int | None,
        pathway: str | None,
        q: str | None = None,
        sort_by: str = "patient_id",
        sort_dir: str = "asc",
        evaluation_status: str | None = None,
        has_open_care_gaps: bool | None = None,
        history_status: str | None = None,
        age_band: str | None = None,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedPatientsOut: ...
    # Programme summary inputs (`app.services.programmes`): members = people with a history record
    # for the pathway (as `list_patients(pathway=…)`), their gaps under the pathway's rules, and the
    # reference dates of the persisted evaluation runs.
    def list_programme_members(
        self,
        pathway: str,
        sex: str | None = None,
        region_id: int | None = None,
        age_band: str | None = None,
        patient_ids: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]: ...
    def list_programme_gaps(
        self, pathway: str, patient_ids: frozenset[str]
    ) -> list[tuple[str, str, str, date, date | None]]: ...
    def evaluation_reference_dates(self) -> list[date]: ...
    def get_patient(self, patient_id: str) -> PatientSummaryOut | None: ...
    def get_patient_evaluations(self, patient_id: str) -> PatientEvaluationsOut | None: ...
    def get_evaluation_run_info(self) -> tuple[str, date, int]: ...
    def get_patient_context(self, patient_id: str) -> PatientContext | None: ...
    def list_rules(
        self,
        pathway: str | None,
        verification_status: str | None,
        is_authoritative: bool | None,
    ) -> PaginatedRulesOut: ...
    def get_rule_detail(self, rule_id: str) -> RuleDetailOut | None: ...
    def get_rule_meta(self, rule_id: str) -> dict[str, Any] | None: ...
    def list_care_gaps(
        self,
        status: str | None,
        gap_type: str | None,
        rule_id: str | None,
        limit: int,
        offset: int,
        patient_id: str | None = None,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedCareGapsOut: ...
    def get_care_gap_detail(self, gap_id: str) -> CareGapDetailOut | None: ...
    def get_care_gap_patient_id(self, gap_id: str) -> str | None: ...
    def list_facilities(
        self,
        limit: int,
        offset: int,
        region_id: int | None = None,
        facility_type: str | None = None,
        source_layer: str | None = None,
        q: str | None = None,
    ) -> PaginatedFacilitiesOut: ...
    def get_facility(self, ch_fid: str) -> FacilityDetailOut | None: ...
    def list_open_questions(
        self, status: str | None = None, category: str | None = None
    ) -> PaginatedOpenQuestionsOut: ...
    def get_open_question(self, oq_id: str) -> OpenQuestionOut | None: ...
    def get_patient_outreach_inputs(
        self, patient_id: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]: ...
    def get_explanation_inputs(
        self, patient_id: str, rule_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str, list[dict[str, Any]], list[str]]: ...
    def get_patient_history(self, patient_id: str) -> PatientHistoryOut | None: ...
    def get_patient_consents(self, patient_id: str) -> PatientConsentsOut | None: ...


@dataclass(frozen=True)
class _DatasetIndex:
    dataset: SyntheticDataset
    patients_by_id: dict[str, dict[str, Any]]
    guardians_by_patient: dict[str, list[dict[str, Any]]]
    history_by_patient: dict[str, dict[str, str]]
    history_availabilities_by_patient: dict[str, list[dict[str, Any]]]
    evaluations_by_patient: dict[str, list[dict[str, Any]]]
    reasons_by_eval: dict[str, list[dict[str, Any]]]
    care_gaps_by_patient: dict[str, list[dict[str, Any]]]
    consents_by_patient: dict[str, list[dict[str, Any]]]
    ifhas_by_patient: dict[str, list[dict[str, Any]]]
    wcv_by_patient: dict[str, list[dict[str, Any]]]
    crs_by_patient: dict[str, list[dict[str, Any]]]
    assessments_by_patient: dict[str, list[dict[str, Any]]]
    referrals_by_patient: dict[str, list[dict[str, Any]]]


@lru_cache(maxsize=1)
def get_cached_bundle() -> ParsedClinicalBundle:
    return parse_clinical_bundle()


@lru_cache(maxsize=1)
def get_cached_engine() -> EvaluationEngine:
    return EvaluationEngine(get_cached_bundle())


@lru_cache(maxsize=1)
def get_cached_dataset() -> SyntheticDataset:
    return generate_synthetic_dataset(seed=20261116, total_patients=550, bundle=get_cached_bundle())


@lru_cache(maxsize=1)
def get_cached_index() -> _DatasetIndex:
    ds = get_cached_dataset()
    patients_by_id = {p["patient_id"]: p for p in ds.patients}
    guardians_by_patient: dict[str, list[dict[str, Any]]] = {}
    for g in ds.guardians:
        guardians_by_patient.setdefault(g["patient_id"], []).append(g)

    history_by_patient: dict[str, dict[str, str]] = {}
    history_availabilities_by_patient: dict[str, list[dict[str, Any]]] = {}
    for h in ds.history_availabilities:
        history_by_patient.setdefault(h["patient_id"], {})[h["pathway"]] = h["history_status"]
        history_availabilities_by_patient.setdefault(h["patient_id"], []).append(h)

    evaluations_by_patient: dict[str, list[dict[str, Any]]] = {}
    for ev in ds.eligibility_evaluations:
        evaluations_by_patient.setdefault(ev["patient_id"], []).append(ev)

    reasons_by_eval: dict[str, list[dict[str, Any]]] = {}
    for r in ds.evaluation_reasons:
        reasons_by_eval.setdefault(r["evaluation_id"], []).append(r)

    care_gaps_by_patient: dict[str, list[dict[str, Any]]] = {}
    for g in ds.care_gaps:
        care_gaps_by_patient.setdefault(g["patient_id"], []).append(g)

    consents_by_patient: dict[str, list[dict[str, Any]]] = {}
    for c in ds.consents:
        consents_by_patient.setdefault(c["patient_id"], []).append(c)

    ifhas_by_patient: dict[str, list[dict[str, Any]]] = {}
    for s in ds.ifhas_screenings:
        ifhas_by_patient.setdefault(s["patient_id"], []).append(s)

    wcv_by_patient: dict[str, list[dict[str, Any]]] = {}
    for v in ds.well_child_visits:
        wcv_by_patient.setdefault(v["patient_id"], []).append(v)

    crs_by_patient: dict[str, list[dict[str, Any]]] = {}
    for cr in ds.component_results:
        crs_by_patient.setdefault(cr["patient_id"], []).append(cr)

    assessments_by_patient: dict[str, list[dict[str, Any]]] = {}
    for a in ds.assessments:
        assessments_by_patient.setdefault(a["patient_id"], []).append(a)

    referrals_by_patient: dict[str, list[dict[str, Any]]] = {}
    for ref in ds.referrals:
        referrals_by_patient.setdefault(ref["patient_id"], []).append(ref)

    return _DatasetIndex(
        dataset=ds,
        patients_by_id=patients_by_id,
        guardians_by_patient=guardians_by_patient,
        history_by_patient=history_by_patient,
        history_availabilities_by_patient=history_availabilities_by_patient,
        evaluations_by_patient=evaluations_by_patient,
        reasons_by_eval=reasons_by_eval,
        care_gaps_by_patient=care_gaps_by_patient,
        consents_by_patient=consents_by_patient,
        ifhas_by_patient=ifhas_by_patient,
        wcv_by_patient=wcv_by_patient,
        crs_by_patient=crs_by_patient,
        assessments_by_patient=assessments_by_patient,
        referrals_by_patient=referrals_by_patient,
    )


_USABLE_LICENSE_STATUSES = ("Active", "Temporary Closure")


@lru_cache(maxsize=1)
def get_cached_facilities() -> list[dict[str, Any]]:
    """Usable SDI facility rows as published (no invented facilities if the files are absent)."""
    root = repo_root()
    sdi_dir = root / "data" / "raw" / "abudhabi_sdi"
    if not (sdi_dir / "acquisition_log.json").exists():
        return []
    sdi_to_region = {r[3]: r[0] for r in official_parse.REGIONS}
    file_rels = {
        layer: f"data/raw/abudhabi_sdi/{layer}.geojson" for layer in official_parse.SDI_LAYERS
    }
    fac_unit = official_parse.parse_facilities(root, sdi_to_region, file_rels)
    return [
        {"facility_id": None, **r}
        for r in fac_unit.rows
        if r["identity_status"] == "identified"
        and r["geo_quality"] == "ok"
        and r["license_status_raw"] in _USABLE_LICENSE_STATUSES
    ]


_FACILITY_DETAIL_FIELDS = (
    "facility_name_ar",
    "subtype",
    "license_no",
    "has_insurance",
    "inpatient_bed_capacity",
    "specialities_raw",
    "professionals_raw",
    "emergency_department",
    "pediatric_emergency_department",
    "maternity_emergency_care",
    "home_care_services",
    "source_effective_date",
)


def _facility_item(r: dict[str, Any]) -> FacilityItemOut:
    return FacilityItemOut(
        facility_id=r.get("facility_id"),
        ch_fid=r["ch_fid"],
        source_object_id=r["source_object_id"],
        source_layer=r["source_layer"],
        facility_name=r["facility_name_en"],
        region_id=r["region_id"],
        city=r.get("city"),
        facility_type=r["type"] or r["source_layer"],
        category=r.get("category"),
        license_status=r["license_status_raw"],
        is_public=r.get("is_public"),
        latitude=r.get("latitude"),
        longitude=r.get("longitude"),
        geo_quality=r.get("geo_quality"),
        simulated_ifhas_service=None,
        simulated_wcv_service=None,
        capability_basis="unverified_sdi_facts_only",
    )


def _facility_detail(r: dict[str, Any]) -> FacilityDetailOut:
    return FacilityDetailOut(
        **_facility_item(r).model_dump(),
        governance_notice=_FACILITY_NOTICE,
        **{k: r.get(k) for k in _FACILITY_DETAIL_FIELDS},
    )


def _facility_matches(
    r: dict[str, Any],
    region_id: int | None,
    facility_type: str | None,
    source_layer: str | None,
    q: str | None,
) -> bool:
    if region_id is not None and r["region_id"] != region_id:
        return False
    if facility_type is not None and (r["type"] or r["source_layer"]).lower() != facility_type.lower():
        return False
    if source_layer is not None and r["source_layer"] != source_layer:
        return False
    if q and q.strip():
        hay = " ".join(str(r.get(k) or "") for k in ("facility_name_en", "facility_name_ar", "city"))
        if q.strip().lower() not in hay.lower():
            return False
    return True


def _open_question_out(oq: dict[str, Any], rule_ids: list[str]) -> OpenQuestionOut:
    return OpenQuestionOut(
        oq_id=oq["oq_id"],
        category=oq["category"],
        status=oq["status"],
        title=oq["title"],
        detail=oq["detail"],
        affects=list(oq.get("affects_raw") or []),
        resolve_via=oq.get("resolve_via"),
        resolution=oq.get("resolution"),
        resolved_on=oq.get("resolved_on"),
        rule_ids=sorted(set(rule_ids)),
    )


def _review_out(r: dict[str, Any]) -> CareGapReviewOut:
    return CareGapReviewOut(
        review_id=r["review_id"],
        care_gap_id=r["care_gap_id"],
        reviewer=r["reviewer"],
        action=r["action"],
        previous_priority=float(r["previous_priority"]) if r.get("previous_priority") is not None else None,
        new_priority=float(r["new_priority"]) if r.get("new_priority") is not None else None,
        reason=r["reason"],
        reviewed_at=r["reviewed_at"],
        is_synthetic=True,
    )


@lru_cache(maxsize=1)
def _bundle_rules_by_id() -> dict[str, Any]:
    return rules_index(get_cached_bundle().rules)


def evaluation_markers(
    rule_id: str,
    evaluation_status: str,
    reason_code: str | None,
    *,
    date_of_birth: date | None,
    sex: str | None,
    reference_date: date,
) -> dict[str, Any]:
    """Applicability (BE-21) and review-origin (H-7) markers for one evaluation."""
    rules = _bundle_rules_by_id()
    applicability, basis = rule_applicability(
        rules.get(rule_id), rules, date_of_birth=date_of_birth, sex=sex, reference_date=reference_date
    )
    return {
        "applicability": applicability,
        "applicability_basis": basis,
        "review_origin": review_origin(evaluation_status, reason_code),
    }


def build_safe_input_snapshot(
    *,
    patient: dict[str, Any],
    pathway: str,
    history_status: str,
    consents: list[dict[str, Any]],
    has_prior_activity: bool,
    has_referral: bool,
    reference_date: date,
) -> dict[str, Any]:
    age_years, age_months = _compute_age_parts(patient.get("date_of_birth"), reference_date)
    relevant_consents = [
        c
        for c in consents
        if c.get("consent_type") == "screening_participation"
        and c.get("scope_pathway") in (None, pathway)
    ]
    latest_consent = (
        max(relevant_consents, key=lambda c: (c["recorded_at"], c["consent_id"]))["state"]
        if relevant_consents
        else "absent"
    )
    return {
        "pathway": pathway,
        "age_years": age_years,
        "age_months": age_months,
        "sex": patient.get("sex"),
        "thiqa_member": patient.get("thiqa_member"),
        "ever_smoked": patient.get("ever_smoked"),
        "history_status": history_status,
        "screening_consent_state": latest_consent,
        "has_prior_screening_or_visit": has_prior_activity,
        "has_referral": has_referral,
    }


def _snapshot_fields(recorded: dict[str, Any] | None, reconstruct) -> dict[str, Any]:
    """Prefer the snapshot recorded at evaluation time; rows written before migration 0010 have
    none, so their snapshot is rebuilt from current records and labelled as such."""
    if recorded is not None:
        return {"input_snapshot": recorded, "input_snapshot_basis": SNAPSHOT_RECORDED}
    return {"input_snapshot": reconstruct(), "input_snapshot_basis": SNAPSHOT_RECONSTRUCTED}


def _age_band_bounds(age_band: str, ref_date: date) -> tuple[date | None, date | None]:
    """Return `(dob_gt, dob_lte)` bounds for an age band relative to `ref_date`."""
    from app.services.evaluation.engine import _add_years

    if age_band == "child":
        return _add_years(ref_date, -18), None
    if age_band == "adult_18_39":
        return _add_years(ref_date, -40), _add_years(ref_date, -18)
    if age_band == "adult_40_59":
        return _add_years(ref_date, -60), _add_years(ref_date, -40)
    if age_band == "adult_60_plus":
        return None, _add_years(ref_date, -60)
    return None, None


def _build_patient_summary(
    p: dict[str, Any],
    history_map: dict[str, str],
    open_care_gaps_count: int = 0,
    evaluation_summary: dict[str, int] | None = None,
) -> PatientSummaryOut:
    return PatientSummaryOut(
        patient_id=p["patient_id"],
        run_id=p["run_id"],
        is_synthetic=True,
        emirates_id_synthetic=p["emirates_id_synthetic"],
        given_name=p["given_name"],
        family_name=p["family_name"],
        date_of_birth=p["date_of_birth"],
        sex=p["sex"],
        nationality_group=p["nationality_group"],
        region_id=p["region_id"],
        district_label=p["district_label"],
        thiqa_member=p["thiqa_member"],
        ever_smoked=p["ever_smoked"],
        preferred_language=p["preferred_language"],
        preferred_channel=p["preferred_channel"],
        contact_status=p["contact_status"],
        date_of_death=p["date_of_death"],
        history_by_pathway=history_map,
        open_care_gaps_count=open_care_gaps_count,
        evaluation_summary=evaluation_summary or {},
    )


def _build_care_gap_out(g: dict[str, Any]) -> CareGapOut:
    return CareGapOut(
        care_gap_id=g["care_gap_id"],
        patient_id=g["patient_id"],
        evaluation_id=g["evaluation_id"],
        rule_id=g["rule_id"],
        rule_version=g["rule_version"],
        gap_type=g["gap_type"],
        status=g["status"],
        identified_date=g["identified_date"],
        closed_date=g["closed_date"],
        closed_by_consent_id=g["closed_by_consent_id"],
        closed_by_component_result_id=g["closed_by_component_result_id"],
        closed_by_ifhas_screening_id=g.get("closed_by_ifhas_screening_id"),
        closed_by_well_child_visit_id=g.get("closed_by_well_child_visit_id"),
        closed_by_referral_id=g.get("closed_by_referral_id"),
        subject_ifhas_screening_id=g["subject_ifhas_screening_id"],
        subject_well_child_visit_id=g["subject_well_child_visit_id"],
        subject_referral_id=g["subject_referral_id"],
        priority_score=float(g["priority_score"]) if g["priority_score"] is not None else None,
        priority_explanation=g["priority_explanation"],
        scoring_suppressed_reason=g["scoring_suppressed_reason"],
        is_synthetic=True,
    )


def _completed_gap_by_evaluation(gaps: list[dict[str, Any]]) -> dict[str, str]:
    """Map evaluation_id -> care_gap_id for gaps later closed as completed."""
    return {
        g["evaluation_id"]: g["care_gap_id"] for g in gaps if g["status"] == "closed_completed"
    }


def _build_patient_context_from_dicts(
    p: dict[str, Any],
    history_map: dict[str, str],
    ifhas_rows: list[dict[str, Any]],
    wcv_rows: list[dict[str, Any]],
    cr_rows: list[dict[str, Any]],
    assessment_rows: list[dict[str, Any]],
    referral_rows: list[dict[str, Any]],
    consent_rows: list[dict[str, Any]],
    reference_date: date,
) -> PatientContext:
    screenings = tuple(
        ScreeningEventFact(
            screening_id=s["screening_id"],
            rule_id=s["rule_id"],
            rule_version=s["rule_version"],
            completion_status=s["completion_status"],
            performed_date=s["performed_date"],
            results_communicated_date=s.get("results_communicated_date"),
            journey_reported_date=s.get("journey_reported_date"),
        )
        for s in ifhas_rows
    )
    visits = tuple(
        VisitEventFact(
            visit_id=v["visit_id"],
            rule_id=v["rule_id"],
            rule_version=v["rule_version"],
            attendance_status=v["attendance_status"],
            performed_date=v["performed_date"],
        )
        for v in wcv_rows
    )
    crs = tuple(
        ComponentResultFact(
            component_result_id=cr["component_result_id"],
            rule_id=cr["rule_id"],
            rule_version=cr["rule_version"],
            item_category=cr["item_category"],
            item_code=cr["item_code"],
            status=cr["result_status"],
            recorded_at=datetime(
                (cr["performed_date"] or reference_date).year,
                (cr["performed_date"] or reference_date).month,
                (cr["performed_date"] or reference_date).day,
                tzinfo=timezone.utc,
            ),
            documented_in_record=bool(cr.get("documented_in_record")),
            signature_on_file=bool(cr.get("signature_on_file")),
            refused_by_guardian_id=cr.get("refused_by_guardian_id"),
        )
        for cr in cr_rows
    )
    assessments = tuple(
        AssessmentFact(
            assessment_id=a["assessment_id"],
            visit_id=a["well_child_visit_id"] or a["ifhas_screening_id"] or "",
            instrument=a["instrument"],
            tier_rule_id=a["rule_id"] or "",
            tier_rule_version=a["rule_version"] or "1.0.0",
            recorded_at=datetime(
                a["administered_date"].year,
                a["administered_date"].month,
                a["administered_date"].day,
                tzinfo=timezone.utc,
            ),
            mchatr_score=int(a["raw_score"]) if a.get("raw_score") is not None else None,
        )
        for a in assessment_rows
    )
    referrals = tuple(
        ReferralFact(
            referral_id=r["referral_id"],
            trigger_rule_id=r["trigger_rule_id"],
            trigger_rule_version=r["trigger_rule_version"],
            trigger_date=r["trigger_date"],
            initiated_date=r["initiated_date"],
            completed_date=r["completed_date"],
            status=r["status"],
        )
        for r in referral_rows
    )
    consents = tuple(
        ConsentFact(
            consent_id=c["consent_id"],
            consent_type=c["consent_type"],
            state=c["state"],
            applies_to=c["applies_to"],
            scope_pathway=c["scope_pathway"],
            scope_rule_id=c["scope_rule_id"],
            scope_rule_version=c["scope_rule_version"],
            recorded_at=c["recorded_at"],
            documented_in_record=bool(c.get("documented_in_record")),
            signature_on_file=bool(c.get("signature_on_file")),
        )
        for c in consent_rows
    )
    return PatientContext(
        patient_id=p["patient_id"],
        date_of_birth=p["date_of_birth"],
        sex=p["sex"],
        thiqa_member=p["thiqa_member"],
        ever_smoked=p["ever_smoked"],
        history_by_pathway=dict(history_map),
        ifhas_screenings=screenings,
        well_child_visits=visits,
        component_results=crs,
        developmental_assessments=assessments,
        referrals=referrals,
        consents=consents,
    )


# Person-level status (F-10): each person is counted once, under the first status in this order
# that any of their in-scope results has. Results for rules whose printed band excludes the person
# (`applicability = out_of_band`) and reviews caused by the rule itself (`review_origin = rule`,
# counted separately) do not classify a person.
PATIENT_STATUS_PRECEDENCE: tuple[str, ...] = (
    "requires_clinical_review",
    "overdue",
    "due",
    "upcoming",
    "unknown",
    "insufficient_information",
    "eligible",
    "completed",
    "not_eligible",
)
NO_APPLICABLE_RESULT = "no_applicable_result"


def _build_dashboard_summary_out(
    *,
    run_id: str,
    evaluation_run_id: str,
    reference_date: date,
    n_adults: int,
    n_children: int,
    patients: list[tuple[str, int, date | None, str | None]],
    evaluations: list[tuple[str, str, str, str | None]],
    care_gaps: list[tuple[str, str, str, str]],
    history_rows: list[tuple[str, str, str]],
    rule_pathway_map: dict[str, str],
    rules_summary: RulesSummaryOut,
) -> DashboardSummaryOut:
    status_counts = Counter(st for _, _, st, _ in evaluations)
    person = {pid: (dob, sex) for pid, _, dob, sex in patients}
    person_statuses: dict[str, set[str]] = {pid: set() for pid in person}
    unknown_patients: set[str] = set()
    record_review: set[str] = set()
    rule_review: set[str] = set()
    pathway_patients_with_history: dict[str, set[str]] = {"ifhas": set(), "well_child": set()}
    pathway_unknown_history: dict[str, set[str]] = {"ifhas": set(), "well_child": set()}
    pathway_eligible: dict[str, set[str]] = {"ifhas": set(), "well_child": set()}
    pathway_due: dict[str, set[str]] = {"ifhas": set(), "well_child": set()}
    pathway_record_review: dict[str, set[str]] = {"ifhas": set(), "well_child": set()}
    pathway_rule_review: dict[str, set[str]] = {"ifhas": set(), "well_child": set()}

    for pid, pw, hst in history_rows:
        if pw in pathway_patients_with_history:
            if hst in ("available", "partial"):
                pathway_patients_with_history[pw].add(pid)
            elif hst == "not_available":
                pathway_unknown_history[pw].add(pid)

    for pid, rid, st, rc in evaluations:
        dob, sex = person.get(pid, (None, None))
        markers = evaluation_markers(rid, st, rc, date_of_birth=dob, sex=sex, reference_date=reference_date)
        if markers["applicability"] == "out_of_band":
            continue
        pw = rule_pathway_map.get(rid)
        if markers["review_origin"] == "rule":
            rule_review.add(pid)
            if pw in pathway_rule_review:
                pathway_rule_review[pw].add(pid)
            continue
        person_statuses.setdefault(pid, set()).add(st)
        if st == "unknown":
            unknown_patients.add(pid)
        if pw not in pathway_eligible:
            continue
        if st == "eligible":
            pathway_eligible[pw].add(pid)
        elif st in ("due", "upcoming", "overdue"):
            pathway_due[pw].add(pid)
        elif st == "requires_clinical_review":
            record_review.add(pid)
            pathway_record_review[pw].add(pid)

    patient_status_counts: Counter[str] = Counter()
    for statuses in person_statuses.values():
        patient_status_counts[
            next((st for st in PATIENT_STATUS_PRECEDENCE if st in statuses), NO_APPLICABLE_RESULT)
        ] += 1

    patients = [(pid, reg) for pid, reg, _, _ in patients]
    patient_region = {pid: reg for pid, reg in patients}
    open_gaps_count = 0
    closed_refused_count = 0
    gaps_by_type: Counter[str] = Counter()
    gaps_by_pathway: Counter[str] = Counter({"ifhas": 0, "well_child": 0})
    region_open_gaps: Counter[int] = Counter()
    for pid, rid, gtype, gst in care_gaps:
        if gst == "open":
            open_gaps_count += 1
            gaps_by_type[gtype] += 1
            pw = rule_pathway_map.get(rid)
            if pw:
                gaps_by_pathway[pw] += 1
            reg = patient_region.get(pid)
            if reg is not None:
                region_open_gaps[reg] += 1
        elif gst == "closed_refused":
            closed_refused_count += 1

    region_patient_counts = Counter(reg for _, reg in patients)
    region_breakdown = [
        RegionBreakdownOut(
            region_id=reg_id,
            total_patients=region_patient_counts[reg_id],
            open_care_gaps_count=region_open_gaps[reg_id],
        )
        for reg_id in sorted(region_patient_counts.keys())
    ]

    pathway_breakdown = {
        pw: PathwayBreakdownOut(
            patients_with_history=len(pathway_patients_with_history[pw]),
            programme_eligible_patients=len(pathway_eligible[pw]),
            due_or_upcoming_patients=len(pathway_due[pw]),
            unknown_history_patients=len(pathway_unknown_history[pw]),
            review_flagged_patients=len(pathway_record_review[pw]),
            rule_review_patients=len(pathway_rule_review[pw]),
            open_care_gaps_count=gaps_by_pathway[pw],
        )
        for pw in ("ifhas", "well_child")
    }

    return DashboardSummaryOut(
        is_synthetic=True,
        run_id=run_id,
        evaluation_run_id=evaluation_run_id,
        reference_date=reference_date,
        total_patients=len(patients),
        n_adults=n_adults,
        n_children=n_children,
        open_care_gaps_count=open_gaps_count,
        closed_refused_care_gaps_count=closed_refused_count,
        unknown_history_patients_count=len(unknown_patients),
        review_flagged_patients_count=len(record_review),
        rule_review_patients_count=len(rule_review),
        evaluation_status_counts=dict(status_counts),
        patient_status_counts=dict(patient_status_counts),
        patient_status_precedence=list(PATIENT_STATUS_PRECEDENCE),
        pathway_breakdown=pathway_breakdown,
        gaps_by_type=dict(gaps_by_type),
        gaps_by_pathway=dict(gaps_by_pathway),
        region_breakdown=region_breakdown,
        rules_summary=rules_summary,
        governance_disclaimer=_GOVERNANCE_DISCLAIMER,
    )


class MemoryReadRepository:
    """In-memory repository preserving the existing deterministic demo mode."""

    def get_dashboard_summary(self, patient_ids: frozenset[str] | None = None) -> DashboardSummaryOut:
        bundle = get_cached_bundle()
        ds = get_cached_dataset()
        gr = ds.generation_run
        er = ds.evaluation_run
        keep = (lambda pid: True) if patient_ids is None else (lambda pid: pid in patient_ids)
        n_adults, n_children = gr["n_adults"], gr["n_children"]
        if patient_ids is not None:
            with_guardian = {g["patient_id"] for g in ds.guardians}
            scoped = [p["patient_id"] for p in ds.patients if keep(p["patient_id"])]
            n_children = sum(1 for pid in scoped if pid in with_guardian)
            n_adults = len(scoped) - n_children
        rule_pathway_map = {r["rule_id"]: r["pathway"] for r in bundle.rules}
        auth_rules = sum(1 for r in bundle.rules if r["is_authoritative"])
        flagged_rules = sum(1 for r in bundle.rules if r["requires_clinical_review"])
        unres_rules = sum(1 for r in bundle.rules if r["verification_status"] == "unresolved")

        return _build_dashboard_summary_out(
            run_id=gr["run_id"],
            evaluation_run_id=er["evaluation_run_id"],
            reference_date=er["reference_date"],
            n_adults=n_adults,
            n_children=n_children,
            patients=[
                (p["patient_id"], p["region_id"], p["date_of_birth"], p["sex"])
                for p in ds.patients
                if keep(p["patient_id"])
            ],
            evaluations=[
                (e["patient_id"], e["rule_id"], e["evaluation_status"], e["reason_code"])
                for e in ds.eligibility_evaluations
                if keep(e["patient_id"])
            ],
            care_gaps=[
                (g["patient_id"], g["rule_id"], g["gap_type"], g["status"])
                for g in ds.care_gaps
                if keep(g["patient_id"])
            ],
            history_rows=[
                (h["patient_id"], h["pathway"], h["history_status"])
                for h in ds.history_availabilities
                if keep(h["patient_id"])
            ],
            rule_pathway_map=rule_pathway_map,
            rules_summary=RulesSummaryOut(
                total_rules=len(bundle.rules),
                authoritative_rules=auth_rules,
                review_flagged_rules=flagged_rules,
                unresolved_rules=unres_rules,
                total_rule_items=len(bundle.items),
                clinical_review_status=bundle.clinical_review_status,
            ),
        )

    def list_patients(
        self,
        limit: int,
        offset: int,
        sex: str | None,
        region_id: int | None,
        pathway: str | None,
        q: str | None = None,
        sort_by: str = "patient_id",
        sort_dir: str = "asc",
        evaluation_status: str | None = None,
        has_open_care_gaps: bool | None = None,
        history_status: str | None = None,
        age_band: str | None = None,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedPatientsOut:
        idx = get_cached_index()
        ref_date = idx.dataset.evaluation_run["reference_date"]
        dob_gt, dob_lte = _age_band_bounds(age_band, ref_date) if age_band else (None, None)
        q_norm = q.strip().lower() if q else None

        open_gaps_map: dict[str, int] = {}
        eval_summary_map: dict[str, dict[str, int]] = {}
        for p in idx.dataset.patients:
            pid = p["patient_id"]
            open_gaps_map[pid] = sum(
                1 for g in idx.care_gaps_by_patient.get(pid, []) if g["status"] == "open"
            )
            eval_summary_map[pid] = dict(
                Counter(e["evaluation_status"] for e in idx.evaluations_by_patient.get(pid, []))
            )

        filtered = idx.dataset.patients
        if patient_ids is not None:
            filtered = [p for p in filtered if p["patient_id"] in patient_ids]
        if sex is not None:
            filtered = [p for p in filtered if p["sex"] == sex]
        if region_id is not None:
            filtered = [p for p in filtered if p["region_id"] == region_id]
        if pathway is not None:
            filtered = [
                p for p in filtered if pathway in idx.history_by_patient.get(p["patient_id"], {})
            ]
        if q_norm:
            filtered = [
                p
                for p in filtered
                if q_norm in p["patient_id"].lower()
                or q_norm in p["emirates_id_synthetic"].lower()
                or q_norm in p["given_name"].lower()
                or q_norm in p["family_name"].lower()
            ]
        if evaluation_status is not None:
            filtered = [
                p
                for p in filtered
                if eval_summary_map[p["patient_id"]].get(evaluation_status, 0) > 0
            ]
        if has_open_care_gaps is not None:
            # With `pathway`, only open gaps under that programme's rules count (programme views).
            rule_pathway = {r["rule_id"]: r["pathway"] for r in get_cached_bundle().rules}

            def has_open(pid: str) -> bool:
                return any(
                    g["status"] == "open" and (pathway is None or rule_pathway.get(g["rule_id"]) == pathway)
                    for g in idx.care_gaps_by_patient.get(pid, [])
                )

            filtered = [p for p in filtered if has_open(p["patient_id"]) is has_open_care_gaps]
        if history_status is not None:
            filtered = [
                p
                for p in filtered
                if (
                    idx.history_by_patient.get(p["patient_id"], {}).get(pathway) == history_status
                    if pathway is not None
                    else history_status in idx.history_by_patient.get(p["patient_id"], {}).values()
                )
            ]
        if age_band is not None:
            filtered = [
                p
                for p in filtered
                if p["date_of_birth"] is not None
                and (dob_gt is None or p["date_of_birth"] > dob_gt)
                and (dob_lte is None or p["date_of_birth"] <= dob_lte)
            ]

        reverse = sort_dir == "desc"
        if sort_by == "family_name":
            filtered = sorted(
                filtered,
                key=lambda p: (p["family_name"].lower(), p["given_name"].lower(), p["patient_id"]),
                reverse=reverse,
            )
        elif sort_by == "age":
            # Older patients have earlier date_of_birth; missing DOB goes last; tie-break patient_id ASC
            with_dob = [p for p in filtered if p["date_of_birth"] is not None]
            without_dob = sorted(
                [p for p in filtered if p["date_of_birth"] is None],
                key=lambda p: p["patient_id"],
            )
            if reverse:
                with_dob = sorted(
                    with_dob,
                    key=lambda p: (p["date_of_birth"].toordinal(), p["patient_id"]),
                )
            else:
                with_dob = sorted(
                    with_dob,
                    key=lambda p: (-p["date_of_birth"].toordinal(), p["patient_id"]),
                )
            filtered = with_dob + without_dob
        elif sort_by == "open_gaps":
            filtered = sorted(
                filtered,
                key=lambda p: (
                    open_gaps_map[p["patient_id"]] if not reverse else -open_gaps_map[p["patient_id"]],
                    p["patient_id"],
                ),
            )
        else:
            filtered = sorted(filtered, key=lambda p: p["patient_id"], reverse=reverse)

        page = filtered[offset : offset + limit]
        return PaginatedPatientsOut(
            is_synthetic=True,
            total=len(filtered),
            limit=limit,
            offset=offset,
            items=[
                _build_patient_summary(
                    p,
                    idx.history_by_patient.get(p["patient_id"], {}),
                    open_care_gaps_count=open_gaps_map[p["patient_id"]],
                    evaluation_summary=eval_summary_map[p["patient_id"]],
                )
                for p in page
            ],
        )

    def list_programme_members(
        self,
        pathway: str,
        sex: str | None = None,
        region_id: int | None = None,
        age_band: str | None = None,
        patient_ids: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        idx = get_cached_index()
        ref_date = idx.dataset.evaluation_run["reference_date"]
        dob_gt, dob_lte = _age_band_bounds(age_band, ref_date) if age_band else (None, None)
        out: list[tuple[str, str]] = []
        for p in idx.dataset.patients:
            pid, dob = p["patient_id"], p["date_of_birth"]
            hst = idx.history_by_patient.get(pid, {}).get(pathway)
            if (
                hst is None
                or (patient_ids is not None and pid not in patient_ids)
                or (sex is not None and p["sex"] != sex)
                or (region_id is not None and p["region_id"] != region_id)
                or (age_band is not None and (
                    dob is None or (dob_gt is not None and dob <= dob_gt) or (dob_lte is not None and dob > dob_lte)))
            ):
                continue
            out.append((pid, hst))
        return out

    def list_programme_gaps(
        self, pathway: str, patient_ids: frozenset[str]
    ) -> list[tuple[str, str, str, date, date | None]]:
        idx = get_cached_index()
        rule_pathway = {r["rule_id"]: r["pathway"] for r in get_cached_bundle().rules}
        return [
            (g["patient_id"], g["gap_type"], g["status"], g["identified_date"], g["closed_date"])
            for pid in sorted(patient_ids)
            for g in idx.care_gaps_by_patient.get(pid, [])
            if rule_pathway.get(g["rule_id"]) == pathway
        ]

    def evaluation_reference_dates(self) -> list[date]:
        return [get_cached_dataset().evaluation_run["reference_date"]]

    def get_patient(self, patient_id: str) -> PatientSummaryOut | None:
        idx = get_cached_index()
        p = idx.patients_by_id.get(patient_id)
        if p is None:
            return None
        open_gaps = sum(
            1 for g in idx.care_gaps_by_patient.get(patient_id, []) if g["status"] == "open"
        )
        eval_summary = dict(
            Counter(e["evaluation_status"] for e in idx.evaluations_by_patient.get(patient_id, []))
        )
        return _build_patient_summary(
            p,
            idx.history_by_patient.get(patient_id, {}),
            open_care_gaps_count=open_gaps,
            evaluation_summary=eval_summary,
        )

    def get_patient_evaluations(self, patient_id: str) -> PatientEvaluationsOut | None:
        bundle = get_cached_bundle()
        idx = get_cached_index()
        p = idx.patients_by_id.get(patient_id)
        if p is None:
            return None

        ds = idx.dataset
        er = ds.evaluation_run
        ref_date = er["reference_date"]
        rule_meta = {r["rule_id"]: r for r in bundle.rules}
        hmap = idx.history_by_patient.get(patient_id, {})
        consents = idx.consents_by_patient.get(patient_id, [])
        prior_by_rule = {
            s["rule_id"] for s in idx.ifhas_by_patient.get(patient_id, [])
        } | {v["rule_id"] for v in idx.wcv_by_patient.get(patient_id, [])}
        referral_by_rule = {
            r["trigger_rule_id"]
            for r in idx.referrals_by_patient.get(patient_id, [])
            if r.get("trigger_rule_id")
        }

        patient_gaps = idx.care_gaps_by_patient.get(patient_id, [])
        completed_gap_by_eval = _completed_gap_by_evaluation(patient_gaps)
        eval_items: list[EvaluationItemOut] = []
        for ev in idx.evaluations_by_patient.get(patient_id, []):
            rm = rule_meta[ev["rule_id"]]
            pathway = rm["pathway"]
            h_status = hmap.get(pathway, "not_available")
            reasons = [
                EvaluationReasonOut(
                    reason_ordinal=r["reason_ordinal"],
                    reason_code=r["reason_code"],
                    reason_detail=r.get("reason_detail")
                    or describe_reason(
                        r["reason_code"],
                        r["guard_id"],
                        r["item_category"],
                        r["item_code"],
                    ),
                    guard_id=r["guard_id"],
                    item_category=r["item_category"],
                    item_code=r["item_code"],
                )
                for r in idx.reasons_by_eval.get(ev["evaluation_id"], [])
            ]
            eval_items.append(
                EvaluationItemOut(
                    evaluation_id=ev["evaluation_id"],
                    patient_id=patient_id,
                    rule_id=ev["rule_id"],
                    rule_version=ev["rule_version"],
                    pathway=pathway,
                    rule_type=rm.get("rule_type"),
                    source_name=rm.get("source_name"),
                    source_version=rm.get("source_version"),
                    source_reference=rm.get("source_reference"),
                    is_authoritative=bool(rm.get("is_authoritative", False)),
                    requires_clinical_review=bool(rm.get("requires_clinical_review", False)),
                    engine_version=er.get("engine_version"),
                    look_ahead_days=er.get("look_ahead_days"),
                    evaluation_status=ev["evaluation_status"],
                    reason_code=ev["reason_code"],
                    reason_detail=ev.get("reason_detail")
                    or describe_reason(
                        ev.get("reason_code"),
                        evaluation_status=ev["evaluation_status"],
                    ),
                    next_due_date=ev["next_due_date"],
                    evaluated_at=ev["evaluated_at"],
                    **_snapshot_fields(
                        ev.get("input_snapshot"),
                        lambda: build_safe_input_snapshot(
                            patient=p,
                            pathway=pathway,
                            history_status=h_status,
                            consents=consents,
                            has_prior_activity=ev["rule_id"] in prior_by_rule,
                            has_referral=ev["rule_id"] in referral_by_rule,
                            reference_date=ref_date,
                        ),
                    ),
                    reasons=reasons,
                    superseded_by_completion=ev["evaluation_id"] in completed_gap_by_eval,
                    superseded_by_care_gap_id=completed_gap_by_eval.get(ev["evaluation_id"]),
                    **evaluation_markers(
                        ev["rule_id"],
                        ev["evaluation_status"],
                        ev["reason_code"],
                        date_of_birth=p["date_of_birth"],
                        sex=p["sex"],
                        reference_date=ref_date,
                    ),
                )
            )
        gap_items = [_build_care_gap_out(g) for g in patient_gaps]
        return PatientEvaluationsOut(
            is_synthetic=True,
            patient_id=patient_id,
            evaluation_run_id=idx.dataset.evaluation_run["evaluation_run_id"],
            reference_date=idx.dataset.evaluation_run["reference_date"],
            evaluations=eval_items,
            care_gaps=gap_items,
        )

    def get_evaluation_run_info(self) -> tuple[str, date, int]:
        er = get_cached_dataset().evaluation_run
        return er["evaluation_run_id"], er["reference_date"], er["look_ahead_days"]

    def get_patient_context(self, patient_id: str) -> PatientContext | None:
        idx = get_cached_index()
        p = idx.patients_by_id.get(patient_id)
        if p is None:
            return None
        return _build_patient_context_from_dicts(
            p,
            idx.history_by_patient.get(patient_id, {}),
            idx.ifhas_by_patient.get(patient_id, []),
            idx.wcv_by_patient.get(patient_id, []),
            idx.crs_by_patient.get(patient_id, []),
            idx.assessments_by_patient.get(patient_id, []),
            idx.referrals_by_patient.get(patient_id, []),
            idx.consents_by_patient.get(patient_id, []),
            idx.dataset.evaluation_run["reference_date"],
        )

    def list_rules(
        self,
        pathway: str | None,
        verification_status: str | None,
        is_authoritative: bool | None,
    ) -> PaginatedRulesOut:
        bundle = get_cached_bundle()
        oqs_by_rule: dict[tuple[str, str], list[str]] = {}
        for roq in bundle.rule_open_questions:
            oqs_by_rule.setdefault((roq["rule_id"], roq["rule_version"]), []).append(roq["oq_id"])

        rules = bundle.rules
        if pathway is not None:
            rules = [r for r in rules if r["pathway"] == pathway]
        if verification_status is not None:
            rules = [r for r in rules if r["verification_status"] == verification_status]
        if is_authoritative is not None:
            rules = [r for r in rules if r["is_authoritative"] == is_authoritative]

        items = [
            RuleSummaryOut(
                rule_id=r["rule_id"],
                rule_version=r["rule_version"],
                pathway=r["pathway"],
                rule_type=r["rule_type"],
                source_name=r["source_name"],
                source_version=r["source_version"],
                source_reference=r["source_reference"],
                verification_status=r["verification_status"],
                requires_clinical_review=r["requires_clinical_review"],
                is_authoritative=r["is_authoritative"],
                effective_date_text=r["effective_date_text"],
                effective_date_precision=r["effective_date_precision"],
                effective_date_from=r["effective_date_from"],
                description=r["description"],
                open_question_ids=sorted(oqs_by_rule.get((r["rule_id"], r["rule_version"]), [])),
            )
            for r in rules
        ]
        return PaginatedRulesOut(total=len(items), items=items)

    def get_rule_detail(self, rule_id: str) -> RuleDetailOut | None:
        bundle = get_cached_bundle()
        r = next((r for r in bundle.rules if r["rule_id"] == rule_id), None)
        if r is None:
            return None
        rver = r["rule_version"]
        rule_oqs = [
            roq["oq_id"]
            for roq in bundle.rule_open_questions
            if roq["rule_id"] == rule_id and roq["rule_version"] == rver
        ]
        item_oqs_map: dict[tuple[str, str], list[str]] = {}
        for ioq in bundle.rule_item_open_questions:
            if ioq["rule_id"] == rule_id and ioq["rule_version"] == rver:
                item_oqs_map.setdefault((ioq["category"], ioq["code"]), []).append(ioq["oq_id"])
        rule_items = [
            RuleItemOut(
                category=it["category"],
                code=it["code"],
                code_origin=it["code_origin"],
                ordinal=it["ordinal"],
                description=it["description"],
                source_reference=it["source_reference"],
                verification_status=it["verification_status"],
                status_is_verified=it["status_is_verified"],
                effective_authority=it["effective_authority"],
                open_question_ids=sorted(item_oqs_map.get((it["category"], it["code"]), [])),
            )
            for it in bundle.items
            if it["rule_id"] == rule_id and it["rule_version"] == rver
        ]
        return RuleDetailOut(
            rule_id=r["rule_id"],
            rule_version=rver,
            pathway=r["pathway"],
            rule_type=r["rule_type"],
            source_name=r["source_name"],
            source_version=r["source_version"],
            source_reference=r["source_reference"],
            verification_status=r["verification_status"],
            requires_clinical_review=r["requires_clinical_review"],
            is_authoritative=r["is_authoritative"],
            effective_date_text=r["effective_date_text"],
            effective_date_precision=r["effective_date_precision"],
            effective_date_from=r["effective_date_from"],
            effective_date_note=r["effective_date_note"],
            description=r["description"],
            notes=r["notes"],
            spec=r["spec"],
            open_question_ids=sorted(rule_oqs),
            items=rule_items,
        )

    def get_rule_meta(self, rule_id: str) -> dict[str, Any] | None:
        return next((r for r in get_cached_bundle().rules if r["rule_id"] == rule_id), None)

    def list_care_gaps(
        self,
        status: str | None,
        gap_type: str | None,
        rule_id: str | None,
        limit: int,
        offset: int,
        patient_id: str | None = None,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedCareGapsOut:
        gaps = get_cached_dataset().care_gaps
        if patient_ids is not None:
            gaps = [g for g in gaps if g["patient_id"] in patient_ids]
        if status is not None:
            gaps = [g for g in gaps if g["status"] == status]
        if gap_type is not None:
            gaps = [g for g in gaps if g["gap_type"] == gap_type]
        if rule_id is not None:
            gaps = [g for g in gaps if g["rule_id"] == rule_id]
        if patient_id is not None:
            gaps = [g for g in gaps if g["patient_id"] == patient_id]
        page = gaps[offset : offset + limit]
        return PaginatedCareGapsOut(
            is_synthetic=True,
            total=len(gaps),
            limit=limit,
            offset=offset,
            items=[_build_care_gap_out(g) for g in page],
        )

    def get_care_gap_patient_id(self, gap_id: str) -> str | None:
        return next(
            (g["patient_id"] for g in get_cached_dataset().care_gaps if g["care_gap_id"] == gap_id), None
        )

    def get_care_gap_detail(self, gap_id: str) -> CareGapDetailOut | None:
        idx = get_cached_index()
        ds = idx.dataset
        gap = next((g for g in ds.care_gaps if g["care_gap_id"] == gap_id), None)
        if gap is None:
            return None
        pid = gap["patient_id"]
        patient = self.get_patient(pid)
        if patient is None:
            return None
        rule = self.get_rule_detail(gap["rule_id"])
        if rule is None:
            return None
        reasons = [
            EvaluationReasonOut(
                reason_ordinal=r["reason_ordinal"],
                reason_code=r["reason_code"],
                reason_detail=r.get("reason_detail")
                or describe_reason(
                    r["reason_code"],
                    r["guard_id"],
                    r["item_category"],
                    r["item_code"],
                ),
                guard_id=r["guard_id"],
                item_category=r["item_category"],
                item_code=r["item_code"],
            )
            for r in idx.reasons_by_eval.get(gap["evaluation_id"], [])
        ]
        appointments = [
            a
            for a in ds.appointments
            if a["patient_id"] == pid and a.get("care_gap_id") == gap_id
        ]
        from app.repositories.followup_repo import (
            get_memory_follow_up_events,
            get_memory_workflow_events,
        )

        gap_linked_refs = {
            e["referral_id"]
            for e in get_memory_workflow_events(care_gap_id=gap_id, patient_id=pid)
            if e["referral_id"]
        }
        referrals = [
            r
            for r in idx.referrals_by_patient.get(pid, [])
            if (
                r["referral_id"] == gap.get("subject_referral_id")
                or r.get("trigger_rule_id") == gap["rule_id"]
                or r["referral_id"] in gap_linked_refs
            )
        ]
        outreach_events = [
            o
            for o in ds.outreach_events
            if o["patient_id"] == pid and o["care_gap_id"] == gap_id
        ]
        follow_up_events = get_memory_follow_up_events(
            gap_id, run_id=gap["run_id"], patient_id=pid
        )
        workflow_events = get_memory_workflow_events(
            appointment_ids={a["appointment_id"] for a in appointments},
            referral_ids={r["referral_id"] for r in referrals},
            care_gap_id=gap_id,
            patient_id=pid,
        )
        reviews = [r for r in ds.care_gap_reviews if r["care_gap_id"] == gap_id]
        return _build_care_gap_detail_out(
            gap=gap,
            patient=patient,
            rule=rule,
            reasons=reasons,
            appointments=appointments,
            referrals=referrals,
            outreach_events=outreach_events,
            follow_up_events=follow_up_events,
            workflow_events=workflow_events,
            reviews=reviews,
        )

    def list_facilities(
        self,
        limit: int,
        offset: int,
        region_id: int | None = None,
        facility_type: str | None = None,
        source_layer: str | None = None,
        q: str | None = None,
    ) -> PaginatedFacilitiesOut:
        rows = [
            r
            for r in get_cached_facilities()
            if _facility_matches(r, region_id, facility_type, source_layer, q)
        ]
        return PaginatedFacilitiesOut(
            governance_notice=_FACILITY_NOTICE,
            total=len(rows),
            limit=limit,
            offset=offset,
            items=[_facility_item(r) for r in rows[offset : offset + limit]],
        )

    def get_facility(self, ch_fid: str) -> FacilityDetailOut | None:
        row = next((r for r in get_cached_facilities() if r["ch_fid"] == ch_fid), None)
        return _facility_detail(row) if row is not None else None

    def list_open_questions(
        self, status: str | None = None, category: str | None = None
    ) -> PaginatedOpenQuestionsOut:
        bundle = get_cached_bundle()
        links: dict[str, list[str]] = {}
        for link in (*bundle.rule_open_questions, *bundle.rule_item_open_questions):
            links.setdefault(link["oq_id"], []).append(link["rule_id"])
        items = [
            _open_question_out(oq, links.get(oq["oq_id"], []))
            for oq in sorted(bundle.open_questions, key=lambda o: o["oq_id"])
            if (status is None or oq["status"] == status)
            and (category is None or oq["category"] == category)
        ]
        return PaginatedOpenQuestionsOut(total=len(items), items=items)

    def get_open_question(self, oq_id: str) -> OpenQuestionOut | None:
        return next((o for o in self.list_open_questions().items if o.oq_id == oq_id), None)

    def get_patient_outreach_inputs(
        self, patient_id: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        idx = get_cached_index()
        p = idx.patients_by_id.get(patient_id)
        if p is None:
            return None, [], [], []
        return (
            p,
            idx.evaluations_by_patient.get(patient_id, []),
            idx.care_gaps_by_patient.get(patient_id, []),
            idx.consents_by_patient.get(patient_id, []),
        )

    def get_explanation_inputs(
        self, patient_id: str, rule_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str, list[dict[str, Any]], list[str]]:
        bundle = get_cached_bundle()
        idx = get_cached_index()
        ev_match = next(
            (e for e in idx.evaluations_by_patient.get(patient_id, []) if e["rule_id"] == rule_id),
            None,
        )
        if ev_match is None:
            return None, None, "not_available", [], []
        r_meta = next(r for r in bundle.rules if r["rule_id"] == rule_id)
        h_status = idx.history_by_patient.get(patient_id, {}).get(
            r_meta["pathway"], "not_available"
        )
        eval_reasons = idx.reasons_by_eval.get(ev_match["evaluation_id"], [])
        rule_oqs = [
            roq["oq_id"]
            for roq in bundle.rule_open_questions
            if roq["rule_id"] == rule_id and roq["rule_version"] == r_meta["rule_version"]
        ]
        return ev_match, r_meta, h_status, eval_reasons, sorted(rule_oqs)

    def get_patient_history(self, patient_id: str) -> PatientHistoryOut | None:
        idx = get_cached_index()
        if patient_id not in idx.patients_by_id:
            return None
        return _build_patient_history_out(
            patient_id=patient_id,
            guardians=idx.guardians_by_patient.get(patient_id, []),
            history_availabilities=idx.history_availabilities_by_patient.get(patient_id, []),
            ifhas_screenings=idx.ifhas_by_patient.get(patient_id, []),
            well_child_visits=idx.wcv_by_patient.get(patient_id, []),
            component_results=idx.crs_by_patient.get(patient_id, []),
            assessments=idx.assessments_by_patient.get(patient_id, []),
        )

    def get_patient_consents(self, patient_id: str) -> PatientConsentsOut | None:
        idx = get_cached_index()
        if patient_id not in idx.patients_by_id:
            return None
        return _build_patient_consents_out(
            patient_id=patient_id,
            consents=idx.consents_by_patient.get(patient_id, []),
        )


def _build_patient_history_out(
    *,
    patient_id: str,
    guardians: list[dict[str, Any]],
    history_availabilities: list[dict[str, Any]],
    ifhas_screenings: list[dict[str, Any]],
    well_child_visits: list[dict[str, Any]],
    component_results: list[dict[str, Any]],
    assessments: list[dict[str, Any]],
) -> PatientHistoryOut:
    return PatientHistoryOut(
        is_synthetic=True,
        patient_id=patient_id,
        guardians=[
            GuardianOut(
                guardian_id=g["guardian_id"],
                patient_id=g["patient_id"],
                relationship=g["relationship"],
                given_name=g["given_name"],
                family_name=g["family_name"],
                preferred_language=g["preferred_language"],
                preferred_channel=g["preferred_channel"],
                contact_status=g["contact_status"],
                is_synthetic=bool(g.get("is_synthetic", True)),
            )
            for g in sorted(guardians, key=lambda x: x["guardian_id"])
        ],
        history_availability=[
            HistoryAvailabilityOut(
                history_id=h["history_id"],
                pathway=h["pathway"],
                history_status=h["history_status"],
                as_of_date=h["as_of_date"],
                note=h.get("note"),
                is_synthetic=bool(h.get("is_synthetic", True)),
            )
            for h in sorted(history_availabilities, key=lambda x: (x["pathway"], x["as_of_date"]))
        ],
        ifhas_screenings=[
            IfhasScreeningOut(
                screening_id=s["screening_id"],
                rule_id=s["rule_id"],
                rule_version=s["rule_version"],
                profile_id=s["profile_id"],
                appointment_id=s.get("appointment_id"),
                performed_date=s.get("performed_date"),
                completion_status=s["completion_status"],
                results_communicated_date=s.get("results_communicated_date"),
                journey_reported_date=s.get("journey_reported_date"),
                has_abnormal_finding=s.get("has_abnormal_finding"),
                is_synthetic=bool(s.get("is_synthetic", True)),
            )
            for s in sorted(
                ifhas_screenings,
                key=lambda x: (x.get("performed_date") or date.min, x["screening_id"]),
                reverse=True,
            )
        ],
        well_child_visits=[
            WellChildVisitOut(
                visit_id=v["visit_id"],
                rule_id=v["rule_id"],
                rule_version=v["rule_version"],
                guardian_id=v["guardian_id"],
                profile_id=v["profile_id"],
                appointment_id=v.get("appointment_id"),
                performed_date=v.get("performed_date"),
                attendance_status=v["attendance_status"],
                is_catch_up_visit=bool(v["is_catch_up_visit"]),
                is_synthetic=bool(v.get("is_synthetic", True)),
            )
            for v in sorted(
                well_child_visits,
                key=lambda x: (x.get("performed_date") or date.min, x["visit_id"]),
                reverse=True,
            )
        ],
        component_results=[
            ComponentResultOut(
                component_result_id=c["component_result_id"],
                rule_id=c["rule_id"],
                rule_version=c["rule_version"],
                ifhas_screening_id=c.get("ifhas_screening_id"),
                well_child_visit_id=c.get("well_child_visit_id"),
                item_category=c["item_category"],
                item_code=c["item_code"],
                result_status=c["result_status"],
                performed_date=c.get("performed_date"),
                documented_in_record=c.get("documented_in_record"),
                signature_on_file=c.get("signature_on_file"),
                refused_by_guardian_id=c.get("refused_by_guardian_id"),
                refusal_reason=c.get("refusal_reason"),
                is_synthetic=bool(c.get("is_synthetic", True)),
            )
            for c in sorted(component_results, key=lambda x: x["component_result_id"])
        ],
        assessments=[
            AssessmentOut(
                assessment_id=a["assessment_id"],
                ifhas_screening_id=a.get("ifhas_screening_id"),
                well_child_visit_id=a.get("well_child_visit_id"),
                instrument=a["instrument"],
                instrument_version=a.get("instrument_version"),
                administered_date=a["administered_date"],
                raw_score=float(a["raw_score"]) if a.get("raw_score") is not None else None,
                item_responses=a.get("item_responses"),
                rule_id=a.get("rule_id"),
                rule_version=a.get("rule_version"),
                is_synthetic=bool(a.get("is_synthetic", True)),
            )
            for a in sorted(
                assessments,
                key=lambda x: (x["administered_date"], x["assessment_id"]),
                reverse=True,
            )
        ],
    )


def _build_patient_consents_out(
    *, patient_id: str, consents: list[dict[str, Any]]
) -> PatientConsentsOut:
    ordered = sorted(
        consents,
        key=lambda c: (c["recorded_at"], c["consent_id"]),
        reverse=True,
    )
    latest_by_scope: dict[tuple[str, str, str | None, str | None], dict[str, Any]] = {}
    for c in ordered:
        key = (
            c["consent_type"],
            c["applies_to"],
            c.get("scope_pathway"),
            c.get("scope_rule_id"),
        )
        latest_by_scope.setdefault(key, c)

    def _to_out(c: dict[str, Any]) -> ConsentRecordOut:
        return ConsentRecordOut(
            consent_id=c["consent_id"],
            patient_id=c["patient_id"],
            guardian_id=c.get("guardian_id"),
            consent_type=c["consent_type"],
            state=c["state"],
            applies_to=c["applies_to"],
            scope_pathway=c.get("scope_pathway"),
            scope_rule_id=c.get("scope_rule_id"),
            scope_rule_version=c.get("scope_rule_version"),
            recorded_at=c["recorded_at"],
            recorded_by=c["recorded_by"],
            documented_in_record=c.get("documented_in_record"),
            signature_on_file=c.get("signature_on_file"),
            refusal_reason=c.get("refusal_reason"),
            is_synthetic=bool(c.get("is_synthetic", True)),
        )

    return PatientConsentsOut(
        is_synthetic=True,
        patient_id=patient_id,
        current_states=[_to_out(c) for c in latest_by_scope.values()],
        history=[_to_out(c) for c in ordered],
    )


def _build_care_gap_detail_out(
    *,
    gap: dict[str, Any],
    patient: PatientSummaryOut,
    rule: RuleSummaryOut,
    reasons: list[EvaluationReasonOut],
    appointments: list[dict[str, Any]],
    referrals: list[dict[str, Any]],
    outreach_events: list[dict[str, Any]],
    follow_up_events: list[dict[str, Any]] | None = None,
    workflow_events: list[dict[str, Any]] | None = None,
    reviews: list[dict[str, Any]] | None = None,
) -> CareGapDetailOut:
    from app.repositories.followup_repo import _sorted_follow_ups, _sorted_workflow

    base = _build_care_gap_out(gap)
    return CareGapDetailOut(
        **base.model_dump(),
        patient=patient,
        rule=RuleSummaryOut(**rule.model_dump(include=set(RuleSummaryOut.model_fields.keys()))),
        reasons=reasons,
        linked_appointments=[
            AppointmentOut(
                appointment_id=a["appointment_id"],
                patient_id=a["patient_id"],
                profile_id=a["profile_id"],
                care_gap_id=a.get("care_gap_id"),
                appointment_type=a["appointment_type"],
                scheduled_datetime=a["scheduled_datetime"],
                slot_type=a["slot_type"],
                status=a["status"],
                booked_via=a["booked_via"],
                is_synthetic=bool(a.get("is_synthetic", True)),
            )
            for a in sorted(appointments, key=lambda x: x["scheduled_datetime"], reverse=True)
        ],
        linked_referrals=[
            ReferralOut(
                referral_id=r["referral_id"],
                patient_id=r["patient_id"],
                trigger_rule_id=r["trigger_rule_id"],
                trigger_rule_version=r["trigger_rule_version"],
                referral_target=r["referral_target"],
                target_profile_id=r.get("target_profile_id"),
                trigger_date=r["trigger_date"],
                initiated_date=r.get("initiated_date"),
                completed_date=r.get("completed_date"),
                status=r["status"],
                is_synthetic=bool(r.get("is_synthetic", True)),
            )
            for r in sorted(referrals, key=lambda x: x["trigger_date"], reverse=True)
        ],
        linked_outreach_events=[
            OutreachEventOut(
                outreach_id=o["outreach_id"],
                patient_id=o["patient_id"],
                care_gap_id=o["care_gap_id"],
                guardian_id=o.get("guardian_id"),
                recipient=o["recipient"],
                event_type=o["event_type"],
                channel=o["channel"],
                sent_datetime=o.get("sent_datetime"),
                delivery_status=o["delivery_status"],
                suppression_reason=o.get("suppression_reason"),
                contact_consent_id=o.get("contact_consent_id"),
                response=o.get("response"),
                appointment_id=o.get("appointment_id"),
                is_synthetic=bool(o.get("is_synthetic", True)),
            )
            for o in sorted(outreach_events, key=lambda x: x["outreach_id"], reverse=True)
        ],
        follow_up_events=_sorted_follow_ups(follow_up_events or []),
        workflow_events=_sorted_workflow(workflow_events or []),
        reviews=[
            _review_out(r)
            for r in sorted(reviews or [], key=lambda x: (x["reviewed_at"], x["review_id"]))
        ],
        recommended_pathway=RecommendedPathwayOut(**recommended_pathway(gap, rule.model_dump())),
    )


def _row_to_dict(obj: Any) -> dict[str, Any]:
    return {col.name: getattr(obj, col.name) for col in obj.__table__.columns}


class PostgresReadRepository:
    """PostgreSQL-backed read repository for `DATA_SOURCE=db`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _latest_runs(self) -> tuple[GenerationRun, EvaluationRun]:
        gr = self._session.scalars(
            select(GenerationRun).order_by(
                GenerationRun.started_at.desc(), GenerationRun.run_id.desc()
            )
        ).first()
        if gr is None:
            raise HTTPException(
                status_code=503,
                detail="Database has no seeded synthetic generation/evaluation run.",
            )
        er = self._session.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.run_id == gr.run_id)
            .order_by(EvaluationRun.started_at.desc(), EvaluationRun.evaluation_run_id.desc())
        ).first()
        if er is None:
            raise HTTPException(
                status_code=503,
                detail="Database has no seeded synthetic generation/evaluation run.",
            )
        return gr, er

    def get_dashboard_summary(self, patient_ids: frozenset[str] | None = None) -> DashboardSummaryOut:
        scope = sorted(patient_ids) if patient_ids is not None else None
        try:
            gr, er = self._latest_runs()
            eval_rows = list(
                self._session.execute(
                    select(
                        EligibilityEvaluation.patient_id,
                        EligibilityEvaluation.rule_id,
                        EligibilityEvaluation.evaluation_status,
                        EligibilityEvaluation.reason_code,
                    ).where(
                        EligibilityEvaluation.evaluation_run_id == er.evaluation_run_id
                    ).where(
                        EligibilityEvaluation.patient_id.in_(scope) if scope is not None else true()
                    )
                ).all()
            )
            gap_rows = list(
                self._session.execute(
                    select(
                        CareGap.patient_id,
                        CareGap.rule_id,
                        CareGap.gap_type,
                        CareGap.status,
                    ).where(CareGap.run_id == gr.run_id)
                    .where(CareGap.patient_id.in_(scope) if scope is not None else true())
                ).all()
            )
            patient_rows = list(
                self._session.execute(
                    select(
                        Patient.patient_id, Patient.region_id, Patient.date_of_birth, Patient.sex
                    ).where(Patient.run_id == gr.run_id)
                    .where(Patient.patient_id.in_(scope) if scope is not None else true())
                ).all()
            )
            history_rows = list(
                self._session.execute(
                    select(
                        HistoryAvailability.patient_id,
                        HistoryAvailability.pathway,
                        HistoryAvailability.history_status,
                    ).where(HistoryAvailability.run_id == gr.run_id)
                    .where(HistoryAvailability.patient_id.in_(scope) if scope is not None else true())
                ).all()
            )
            n_adults, n_children = gr.n_adults, gr.n_children
            if scope is not None:
                with_guardian = set(self._session.scalars(
                    select(Guardian.patient_id).where(Guardian.run_id == gr.run_id, Guardian.patient_id.in_(scope))
                ))
                n_children = sum(1 for r in patient_rows if r[0] in with_guardian)
                n_adults = len(patient_rows) - n_children
            rules = self._session.scalars(select(Rule)).all()
            n_items = len(self._session.scalars(select(RuleItem.rule_id)).all())
            rl = self._session.scalars(
                select(RuleLoad).order_by(RuleLoad.load_id.desc())
            ).first()
            clin_status = rl.clinical_review_status if rl is not None else "not_reviewed"
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

        return _build_dashboard_summary_out(
            run_id=gr.run_id,
            evaluation_run_id=er.evaluation_run_id,
            reference_date=er.reference_date,
            n_adults=n_adults,
            n_children=n_children,
            patients=[tuple(r) for r in patient_rows],
            evaluations=[tuple(r) for r in eval_rows],
            care_gaps=[(pid, rid, gt, gst) for pid, rid, gt, gst in gap_rows],
            history_rows=[(pid, pw, hst) for pid, pw, hst in history_rows],
            rule_pathway_map={r.rule_id: r.pathway for r in rules},
            rules_summary=RulesSummaryOut(
                total_rules=len(rules),
                authoritative_rules=sum(1 for r in rules if r.is_authoritative),
                review_flagged_rules=sum(1 for r in rules if r.requires_clinical_review),
                unresolved_rules=sum(1 for r in rules if r.verification_status == "unresolved"),
                total_rule_items=n_items,
                clinical_review_status=clin_status,
            ),
        )

    def _patient_history_map(
        self, patient_ids: list[str], run_id: str | None = None
    ) -> dict[str, dict[str, str]]:
        if not patient_ids:
            return {}
        stmt = select(HistoryAvailability).where(HistoryAvailability.patient_id.in_(patient_ids))
        if run_id is not None:
            stmt = stmt.where(HistoryAvailability.run_id == run_id)
        rows = self._session.scalars(stmt).all()
        out: dict[str, dict[str, str]] = {}
        for h in rows:
            out.setdefault(h.patient_id, {})[h.pathway] = h.history_status
        return out

    def _patient_rollups(
        self, patient_ids: list[str], eval_run_id: str, run_id: str | None = None
    ) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
        if not patient_ids:
            return {}, {}
        open_gaps: dict[str, int] = {}
        gap_stmt = select(CareGap.patient_id, func.count(CareGap.care_gap_id)).where(
            CareGap.patient_id.in_(patient_ids),
            CareGap.status == "open",
        )
        if run_id is not None:
            gap_stmt = gap_stmt.where(CareGap.run_id == run_id)
        for pid, cnt in self._session.execute(gap_stmt.group_by(CareGap.patient_id)).all():
            open_gaps[pid] = int(cnt)

        eval_summaries: dict[str, dict[str, int]] = {}
        for pid, st, cnt in self._session.execute(
            select(
                EligibilityEvaluation.patient_id,
                EligibilityEvaluation.evaluation_status,
                func.count(EligibilityEvaluation.evaluation_id),
            )
            .where(
                EligibilityEvaluation.patient_id.in_(patient_ids),
                EligibilityEvaluation.evaluation_run_id == eval_run_id,
            )
            .group_by(
                EligibilityEvaluation.patient_id,
                EligibilityEvaluation.evaluation_status,
            )
        ).all():
            eval_summaries.setdefault(pid, {})[st] = int(cnt)
        return open_gaps, eval_summaries

    def list_programme_members(
        self,
        pathway: str,
        sex: str | None = None,
        region_id: int | None = None,
        age_band: str | None = None,
        patient_ids: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        try:
            gr, er = self._latest_runs()
            stmt = (
                select(Patient.patient_id, HistoryAvailability.history_status)
                .join(
                    HistoryAvailability,
                    (HistoryAvailability.patient_id == Patient.patient_id)
                    & (HistoryAvailability.run_id == gr.run_id)
                    & (HistoryAvailability.pathway == pathway),
                )
                .where(Patient.run_id == gr.run_id)
            )
            if patient_ids is not None:
                stmt = stmt.where(Patient.patient_id.in_(sorted(patient_ids)))
            if sex is not None:
                stmt = stmt.where(Patient.sex == sex)
            if region_id is not None:
                stmt = stmt.where(Patient.region_id == region_id)
            if age_band is not None:
                dob_gt, dob_lte = _age_band_bounds(age_band, er.reference_date)
                stmt = stmt.where(Patient.date_of_birth.is_not(None))
                if dob_gt is not None:
                    stmt = stmt.where(Patient.date_of_birth > dob_gt)
                if dob_lte is not None:
                    stmt = stmt.where(Patient.date_of_birth <= dob_lte)
            rows = self._session.execute(stmt.order_by(Patient.patient_id)).all()
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc
        return [(pid, hst) for pid, hst in rows]

    def list_programme_gaps(
        self, pathway: str, patient_ids: frozenset[str]
    ) -> list[tuple[str, str, str, date, date | None]]:
        if not patient_ids:
            return []
        try:
            gr, _ = self._latest_runs()
            rows = self._session.execute(
                select(CareGap.patient_id, CareGap.gap_type, CareGap.status, CareGap.identified_date,
                       CareGap.closed_date)
                .where(
                    CareGap.run_id == gr.run_id,
                    CareGap.patient_id.in_(sorted(patient_ids)),
                    CareGap.rule_id.in_(select(Rule.rule_id).where(Rule.pathway == pathway)),
                )
                .order_by(CareGap.care_gap_id)
            ).all()
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc
        return [tuple(r) for r in rows]

    def evaluation_reference_dates(self) -> list[date]:
        try:
            gr, _ = self._latest_runs()
            return sorted(set(self._session.scalars(
                select(EvaluationRun.reference_date).where(EvaluationRun.run_id == gr.run_id)
            )))
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

    def list_patients(
        self,
        limit: int,
        offset: int,
        sex: str | None,
        region_id: int | None,
        pathway: str | None,
        q: str | None = None,
        sort_by: str = "patient_id",
        sort_dir: str = "asc",
        evaluation_status: str | None = None,
        has_open_care_gaps: bool | None = None,
        history_status: str | None = None,
        age_band: str | None = None,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedPatientsOut:
        try:
            gr, er = self._latest_runs()
            stmt = select(Patient).where(Patient.run_id == gr.run_id)
            if patient_ids is not None:
                stmt = stmt.where(Patient.patient_id.in_(sorted(patient_ids)))
            if sex is not None:
                stmt = stmt.where(Patient.sex == sex)
            if region_id is not None:
                stmt = stmt.where(Patient.region_id == region_id)
            if pathway is not None:
                subq = select(HistoryAvailability.patient_id).where(
                    HistoryAvailability.run_id == gr.run_id,
                    HistoryAvailability.pathway == pathway,
                )
                stmt = stmt.where(Patient.patient_id.in_(subq))
            if q and q.strip():
                pat = f"%{q.strip()}%"
                stmt = stmt.where(
                    or_(
                        Patient.patient_id.ilike(pat),
                        Patient.emirates_id_synthetic.ilike(pat),
                        Patient.given_name.ilike(pat),
                        Patient.family_name.ilike(pat),
                    )
                )
            if evaluation_status is not None:
                ev_subq = select(EligibilityEvaluation.patient_id).where(
                    EligibilityEvaluation.evaluation_run_id == er.evaluation_run_id,
                    EligibilityEvaluation.evaluation_status == evaluation_status,
                )
                stmt = stmt.where(Patient.patient_id.in_(ev_subq))
            if has_open_care_gaps is not None:
                gap_subq = select(CareGap.patient_id).where(
                    CareGap.run_id == gr.run_id,
                    CareGap.status == "open",
                )
                if pathway is not None:
                    gap_subq = gap_subq.where(
                        CareGap.rule_id.in_(select(Rule.rule_id).where(Rule.pathway == pathway))
                    )
                if has_open_care_gaps:
                    stmt = stmt.where(Patient.patient_id.in_(gap_subq))
                else:
                    stmt = stmt.where(~Patient.patient_id.in_(gap_subq))
            if history_status is not None:
                hs_subq = select(HistoryAvailability.patient_id).where(
                    HistoryAvailability.run_id == gr.run_id,
                    HistoryAvailability.history_status == history_status,
                )
                if pathway is not None:
                    hs_subq = hs_subq.where(HistoryAvailability.pathway == pathway)
                stmt = stmt.where(Patient.patient_id.in_(hs_subq))
            if age_band is not None:
                dob_gt, dob_lte = _age_band_bounds(age_band, er.reference_date)
                stmt = stmt.where(Patient.date_of_birth.is_not(None))
                if dob_gt is not None:
                    stmt = stmt.where(Patient.date_of_birth > dob_gt)
                if dob_lte is not None:
                    stmt = stmt.where(Patient.date_of_birth <= dob_lte)

            total = int(
                self._session.scalar(
                    select(func.count()).select_from(stmt.subquery())
                )
                or 0
            )
            desc = sort_dir == "desc"
            if sort_by == "family_name":
                order_cols = [
                    func.lower(Patient.family_name).desc()
                    if desc
                    else func.lower(Patient.family_name).asc(),
                    func.lower(Patient.given_name).desc()
                    if desc
                    else func.lower(Patient.given_name).asc(),
                    Patient.patient_id.desc() if desc else Patient.patient_id.asc(),
                ]
            elif sort_by == "age":
                order_cols = [
                    Patient.date_of_birth.is_(None).asc(),
                    Patient.date_of_birth.asc() if desc else Patient.date_of_birth.desc(),
                    Patient.patient_id.asc(),
                ]
            elif sort_by == "open_gaps":
                gap_cnt = (
                    select(func.count(CareGap.care_gap_id))
                    .where(
                        CareGap.run_id == gr.run_id,
                        CareGap.patient_id == Patient.patient_id,
                        CareGap.status == "open",
                    )
                    .correlate(Patient)
                    .scalar_subquery()
                )
                order_cols = [
                    gap_cnt.desc() if desc else gap_cnt.asc(),
                    Patient.patient_id.asc(),
                ]
            else:
                order_cols = [
                    Patient.patient_id.desc() if desc else Patient.patient_id.asc()
                ]

            page = self._session.scalars(
                stmt.order_by(*order_cols).limit(limit).offset(offset)
            ).all()
            pids = [p.patient_id for p in page]
            hmap = self._patient_history_map(pids, run_id=gr.run_id)
            open_gaps_map, eval_summaries = self._patient_rollups(
                pids, er.evaluation_run_id, run_id=gr.run_id
            )
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

        return PaginatedPatientsOut(
            is_synthetic=True,
            total=total,
            limit=limit,
            offset=offset,
            items=[
                _build_patient_summary(
                    _row_to_dict(p),
                    hmap.get(p.patient_id, {}),
                    open_care_gaps_count=open_gaps_map.get(p.patient_id, 0),
                    evaluation_summary=eval_summaries.get(p.patient_id, {}),
                )
                for p in page
            ],
        )

    def get_patient(self, patient_id: str) -> PatientSummaryOut | None:
        try:
            gr, er = self._latest_runs()
            p = self._session.scalars(
                select(Patient).where(
                    Patient.run_id == gr.run_id,
                    Patient.patient_id == patient_id,
                )
            ).first()
            if p is None:
                return None
            hmap = self._patient_history_map([patient_id], run_id=gr.run_id)
            open_gaps_map, eval_summaries = self._patient_rollups(
                [patient_id], er.evaluation_run_id, run_id=gr.run_id
            )
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc
        return _build_patient_summary(
            _row_to_dict(p),
            hmap.get(patient_id, {}),
            open_care_gaps_count=open_gaps_map.get(patient_id, 0),
            evaluation_summary=eval_summaries.get(patient_id, {}),
        )

    def get_patient_evaluations(self, patient_id: str) -> PatientEvaluationsOut | None:
        try:
            gr, er = self._latest_runs()
            p = self._session.scalars(
                select(Patient).where(
                    Patient.run_id == gr.run_id,
                    Patient.patient_id == patient_id,
                )
            ).first()
            if p is None:
                return None
            rules = {r.rule_id: r for r in self._session.scalars(select(Rule)).all()}
            standards = {s.standard_id: s for s in self._session.scalars(select(Standard)).all()}
            evals = self._session.scalars(
                select(EligibilityEvaluation)
                .where(
                    EligibilityEvaluation.patient_id == patient_id,
                    EligibilityEvaluation.evaluation_run_id == er.evaluation_run_id,
                )
                .order_by(EligibilityEvaluation.evaluation_id)
            ).all()
            eval_ids = [ev.evaluation_id for ev in evals]
            reasons_by_eval: dict[str, list[EvaluationReason]] = {}
            if eval_ids:
                for er_row in self._session.scalars(
                    select(EvaluationReason).where(EvaluationReason.evaluation_id.in_(eval_ids))
                ).all():
                    reasons_by_eval.setdefault(er_row.evaluation_id, []).append(er_row)
            gaps = self._session.scalars(
                select(CareGap)
                .where(
                    CareGap.run_id == gr.run_id,
                    CareGap.patient_id == patient_id,
                )
                .order_by(CareGap.care_gap_id)
            ).all()
            hmap = self._patient_history_map([patient_id], run_id=gr.run_id).get(patient_id, {})
            consents = [
                _row_to_dict(c)
                for c in self._session.scalars(
                    select(Consent).where(
                        Consent.run_id == gr.run_id,
                        Consent.patient_id == patient_id,
                    )
                ).all()
            ]
            prior_by_rule = {
                s.rule_id
                for s in self._session.scalars(
                    select(IfhasScreening).where(
                        IfhasScreening.run_id == gr.run_id,
                        IfhasScreening.patient_id == patient_id,
                    )
                ).all()
            } | {
                v.rule_id
                for v in self._session.scalars(
                    select(WellChildVisit).where(
                        WellChildVisit.run_id == gr.run_id,
                        WellChildVisit.patient_id == patient_id,
                    )
                ).all()
            }
            referral_by_rule = {
                r.trigger_rule_id
                for r in self._session.scalars(
                    select(Referral).where(
                        Referral.run_id == gr.run_id,
                        Referral.patient_id == patient_id,
                    )
                ).all()
                if r.trigger_rule_id
            }
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

        p_dict = _row_to_dict(p)
        gap_dicts = [_row_to_dict(g) for g in gaps]
        completed_gap_by_eval = _completed_gap_by_evaluation(gap_dicts)
        eval_items = []
        for ev in evals:
            rm = rules[ev.rule_id]
            std = standards.get(rm.standard_id)
            h_status = hmap.get(rm.pathway, "not_available")
            eval_items.append(
                EvaluationItemOut(
                    evaluation_id=ev.evaluation_id,
                    patient_id=patient_id,
                    rule_id=ev.rule_id,
                    rule_version=ev.rule_version,
                    pathway=rm.pathway,
                    rule_type=rm.rule_type,
                    source_name=std.source_name if std else None,
                    source_version=std.source_version if std else None,
                    source_reference=rm.source_reference,
                    is_authoritative=bool(rm.is_authoritative),
                    requires_clinical_review=bool(rm.requires_clinical_review),
                    engine_version=er.engine_version,
                    look_ahead_days=er.look_ahead_days,
                    evaluation_status=ev.evaluation_status,
                    reason_code=ev.reason_code,
                    reason_detail=ev.reason_detail
                    or describe_reason(
                        ev.reason_code,
                        evaluation_status=ev.evaluation_status,
                    ),
                    next_due_date=ev.next_due_date,
                    evaluated_at=ev.evaluated_at,
                    **_snapshot_fields(
                        ev.input_snapshot,
                        lambda: build_safe_input_snapshot(
                            patient=p_dict,
                            pathway=rm.pathway,
                            history_status=h_status,
                            consents=consents,
                            has_prior_activity=ev.rule_id in prior_by_rule,
                            has_referral=ev.rule_id in referral_by_rule,
                            reference_date=er.reference_date,
                        ),
                    ),
                    reasons=[
                        EvaluationReasonOut(
                            reason_ordinal=r.reason_ordinal,
                            reason_code=r.reason_code,
                            reason_detail=r.reason_detail
                            or describe_reason(
                                r.reason_code,
                                r.guard_id,
                                r.item_category,
                                r.item_code,
                            ),
                            guard_id=r.guard_id,
                            item_category=r.item_category,
                            item_code=r.item_code,
                        )
                        for r in sorted(
                            reasons_by_eval.get(ev.evaluation_id, []),
                            key=lambda x: x.reason_ordinal,
                        )
                    ],
                    superseded_by_completion=ev.evaluation_id in completed_gap_by_eval,
                    superseded_by_care_gap_id=completed_gap_by_eval.get(ev.evaluation_id),
                    **evaluation_markers(
                        ev.rule_id,
                        ev.evaluation_status,
                        ev.reason_code,
                        date_of_birth=p_dict["date_of_birth"],
                        sex=p_dict["sex"],
                        reference_date=er.reference_date,
                    ),
                )
            )
        return PatientEvaluationsOut(
            is_synthetic=True,
            patient_id=patient_id,
            evaluation_run_id=er.evaluation_run_id,
            reference_date=er.reference_date,
            evaluations=eval_items,
            care_gaps=[_build_care_gap_out(g) for g in gap_dicts],
        )

    def get_evaluation_run_info(self) -> tuple[str, date, int]:
        try:
            _, er = self._latest_runs()
            return er.evaluation_run_id, er.reference_date, er.look_ahead_days
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

    def get_patient_context(self, patient_id: str) -> PatientContext | None:
        try:
            p = self._session.scalars(
                select(Patient).where(Patient.patient_id == patient_id)
            ).first()
            if p is None:
                return None
            _, er = self._latest_runs()
            hmap = self._patient_history_map([patient_id]).get(patient_id, {})
            ifhas_rows = [
                _row_to_dict(r)
                for r in self._session.scalars(
                    select(IfhasScreening).where(IfhasScreening.patient_id == patient_id)
                ).all()
            ]
            wcv_rows = [
                _row_to_dict(r)
                for r in self._session.scalars(
                    select(WellChildVisit).where(WellChildVisit.patient_id == patient_id)
                ).all()
            ]
            cr_rows = [
                _row_to_dict(r)
                for r in self._session.scalars(
                    select(ComponentResult).where(ComponentResult.patient_id == patient_id)
                ).all()
            ]
            assessment_rows = [
                _row_to_dict(r)
                for r in self._session.scalars(
                    select(Assessment).where(Assessment.patient_id == patient_id)
                ).all()
            ]
            referral_rows = [
                _row_to_dict(r)
                for r in self._session.scalars(
                    select(Referral)
                    .where(Referral.patient_id == patient_id)
                    .order_by(Referral.trigger_date, Referral.referral_id)
                ).all()
            ]
            consent_rows = [
                _row_to_dict(r)
                for r in self._session.scalars(
                    select(Consent).where(Consent.patient_id == patient_id)
                ).all()
            ]
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

        return _build_patient_context_from_dicts(
            _row_to_dict(p),
            hmap,
            ifhas_rows,
            wcv_rows,
            cr_rows,
            assessment_rows,
            referral_rows,
            consent_rows,
            er.reference_date,
        )

    def list_rules(
        self,
        pathway: str | None,
        verification_status: str | None,
        is_authoritative: bool | None,
    ) -> PaginatedRulesOut:
        try:
            stmt = select(Rule)
            if pathway is not None:
                stmt = stmt.where(Rule.pathway == pathway)
            if verification_status is not None:
                stmt = stmt.where(Rule.verification_status == verification_status)
            if is_authoritative is not None:
                stmt = stmt.where(Rule.is_authoritative == is_authoritative)
            rules = self._session.scalars(stmt.order_by(Rule.rule_id)).all()
            standards = {s.standard_id: s for s in self._session.scalars(select(Standard)).all()}
            roqs = self._session.scalars(select(RuleOpenQuestion)).all()
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

        oqs_by_rule: dict[tuple[str, str], list[str]] = {}
        for roq in roqs:
            oqs_by_rule.setdefault((roq.rule_id, roq.rule_version), []).append(roq.oq_id)

        items = [
            RuleSummaryOut(
                rule_id=r.rule_id,
                rule_version=r.rule_version,
                pathway=r.pathway,
                rule_type=r.rule_type,
                source_name=standards[r.standard_id].source_name,
                source_version=standards[r.standard_id].source_version,
                source_reference=r.source_reference,
                verification_status=r.verification_status,
                requires_clinical_review=r.requires_clinical_review,
                is_authoritative=r.is_authoritative,
                effective_date_text=r.effective_date_text,
                effective_date_precision=r.effective_date_precision,
                effective_date_from=r.effective_date_from,
                description=r.description,
                open_question_ids=sorted(oqs_by_rule.get((r.rule_id, r.rule_version), [])),
            )
            for r in rules
        ]
        return PaginatedRulesOut(total=len(items), items=items)

    def get_rule_detail(self, rule_id: str) -> RuleDetailOut | None:
        try:
            r = self._session.scalars(select(Rule).where(Rule.rule_id == rule_id)).first()
            if r is None:
                return None
            std = self._session.scalars(
                select(Standard).where(Standard.standard_id == r.standard_id)
            ).first()
            rver = r.rule_version
            rule_oqs = [
                roq.oq_id
                for roq in self._session.scalars(
                    select(RuleOpenQuestion).where(
                        RuleOpenQuestion.rule_id == rule_id,
                        RuleOpenQuestion.rule_version == rver,
                    )
                ).all()
            ]
            ioqs = self._session.scalars(
                select(RuleItemOpenQuestion).where(
                    RuleItemOpenQuestion.rule_id == rule_id,
                    RuleItemOpenQuestion.rule_version == rver,
                )
            ).all()
            items_rows = self._session.scalars(
                select(RuleItem)
                .where(RuleItem.rule_id == rule_id, RuleItem.rule_version == rver)
                .order_by(RuleItem.ordinal)
            ).all()
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

        item_oqs_map: dict[tuple[str, str], list[str]] = {}
        for ioq in ioqs:
            item_oqs_map.setdefault((ioq.category, ioq.code), []).append(ioq.oq_id)

        rule_items = [
            RuleItemOut(
                category=it.category,
                code=it.code,
                code_origin=it.code_origin,
                ordinal=it.ordinal,
                description=it.description,
                source_reference=it.source_reference,
                verification_status=it.verification_status,
                status_is_verified=it.status_is_verified,
                effective_authority=bool(it.status_is_verified and r.is_authoritative),
                open_question_ids=sorted(item_oqs_map.get((it.category, it.code), [])),
            )
            for it in items_rows
        ]
        return RuleDetailOut(
            rule_id=r.rule_id,
            rule_version=rver,
            pathway=r.pathway,
            rule_type=r.rule_type,
            source_name=std.source_name if std is not None else "",
            source_version=std.source_version if std is not None else "",
            source_reference=r.source_reference,
            verification_status=r.verification_status,
            requires_clinical_review=r.requires_clinical_review,
            is_authoritative=r.is_authoritative,
            effective_date_text=r.effective_date_text,
            effective_date_precision=r.effective_date_precision,
            effective_date_from=r.effective_date_from,
            effective_date_note=r.effective_date_note,
            description=r.description,
            notes=r.notes,
            spec=r.spec,
            open_question_ids=sorted(rule_oqs),
            items=rule_items,
        )

    def get_rule_meta(self, rule_id: str) -> dict[str, Any] | None:
        try:
            r = self._session.scalars(select(Rule).where(Rule.rule_id == rule_id)).first()
            if r is None:
                return None
            std = self._session.scalars(
                select(Standard).where(Standard.standard_id == r.standard_id)
            ).first()
            meta = _row_to_dict(r)
            if std is not None:
                meta["source_name"] = std.source_name
                meta["source_version"] = std.source_version
            return meta
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

    def list_care_gaps(
        self,
        status: str | None,
        gap_type: str | None,
        rule_id: str | None,
        limit: int,
        offset: int,
        patient_id: str | None = None,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedCareGapsOut:
        try:
            gr, _ = self._latest_runs()
            stmt = select(CareGap).where(CareGap.run_id == gr.run_id)
            if patient_ids is not None:
                stmt = stmt.where(CareGap.patient_id.in_(sorted(patient_ids)))
            if status is not None:
                stmt = stmt.where(CareGap.status == status)
            if gap_type is not None:
                stmt = stmt.where(CareGap.gap_type == gap_type)
            if rule_id is not None:
                stmt = stmt.where(CareGap.rule_id == rule_id)
            if patient_id is not None:
                stmt = stmt.where(CareGap.patient_id == patient_id)
            total = int(
                self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            )
            page = self._session.scalars(
                stmt.order_by(CareGap.care_gap_id).limit(limit).offset(offset)
            ).all()
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

        return PaginatedCareGapsOut(
            is_synthetic=True,
            total=total,
            limit=limit,
            offset=offset,
            items=[_build_care_gap_out(_row_to_dict(g)) for g in page],
        )

    def get_care_gap_patient_id(self, gap_id: str) -> str | None:
        try:
            gr, _ = self._latest_runs()
            return self._session.scalar(
                select(CareGap.patient_id).where(CareGap.run_id == gr.run_id, CareGap.care_gap_id == gap_id)
            )
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

    def get_care_gap_detail(self, gap_id: str) -> CareGapDetailOut | None:
        try:
            gr, _ = self._latest_runs()
            g = self._session.scalars(
                select(CareGap).where(
                    CareGap.run_id == gr.run_id,
                    CareGap.care_gap_id == gap_id,
                )
            ).first()
            if g is None:
                return None
            patient = self.get_patient(g.patient_id)
            rule = self.get_rule_detail(g.rule_id)
            if patient is None or rule is None:
                return None
            reasons = [
                EvaluationReasonOut(
                    reason_ordinal=r.reason_ordinal,
                    reason_code=r.reason_code,
                    reason_detail=r.reason_detail
                    or describe_reason(
                        r.reason_code,
                        r.guard_id,
                        r.item_category,
                        r.item_code,
                    ),
                    guard_id=r.guard_id,
                    item_category=r.item_category,
                    item_code=r.item_code,
                )
                for r in self._session.scalars(
                    select(EvaluationReason)
                    .where(EvaluationReason.evaluation_id == g.evaluation_id)
                    .order_by(EvaluationReason.reason_ordinal)
                ).all()
            ]
            appointments = [
                _row_to_dict(a)
                for a in self._session.scalars(
                    select(Appointment).where(
                        Appointment.run_id == gr.run_id,
                        Appointment.patient_id == g.patient_id,
                        Appointment.care_gap_id == gap_id,
                    )
                ).all()
            ]
            referrals = [
                _row_to_dict(r)
                for r in self._session.scalars(
                    select(Referral).where(
                        Referral.run_id == gr.run_id,
                        Referral.patient_id == g.patient_id,
                        or_(
                            Referral.referral_id == g.subject_referral_id,
                            Referral.trigger_rule_id == g.rule_id,
                            Referral.referral_id.in_(
                                select(WorkflowStatusEvent.referral_id).where(
                                    WorkflowStatusEvent.run_id == gr.run_id,
                                    WorkflowStatusEvent.care_gap_id == gap_id,
                                    WorkflowStatusEvent.referral_id.is_not(None),
                                )
                            ),
                        ),
                    )
                ).all()
            ]
            outreach_events = [
                _row_to_dict(o)
                for o in self._session.scalars(
                    select(OutreachEvent).where(
                        OutreachEvent.run_id == gr.run_id,
                        OutreachEvent.patient_id == g.patient_id,
                        OutreachEvent.care_gap_id == gap_id,
                    )
                ).all()
            ]
            follow_up_events = [
                _row_to_dict(f)
                for f in self._session.scalars(
                    select(CareGapFollowUpEvent).where(
                        CareGapFollowUpEvent.run_id == gr.run_id,
                        CareGapFollowUpEvent.patient_id == g.patient_id,
                        CareGapFollowUpEvent.care_gap_id == gap_id,
                    )
                ).all()
            ]
            from app.repositories.followup_repo import postgres_gap_workflow_events

            reviews = [
                _row_to_dict(r)
                for r in self._session.scalars(
                    select(CareGapReview).where(
                        CareGapReview.run_id == gr.run_id, CareGapReview.care_gap_id == gap_id
                    )
                ).all()
            ]
            workflow_events = postgres_gap_workflow_events(
                self._session,
                run_id=gr.run_id,
                care_gap_id=gap_id,
                appointment_ids={a["appointment_id"] for a in appointments},
                referral_ids={r["referral_id"] for r in referrals},
            )
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

        return _build_care_gap_detail_out(
            gap=_row_to_dict(g),
            patient=patient,
            rule=rule,
            reasons=reasons,
            appointments=appointments,
            referrals=referrals,
            outreach_events=outreach_events,
            follow_up_events=follow_up_events,
            workflow_events=workflow_events,
            reviews=reviews,
        )

    def _facility_stmt(self):
        return select(Facility).where(
            Facility.identity_status == "identified",
            Facility.geo_quality == "ok",
            Facility.license_status_raw.in_(_USABLE_LICENSE_STATUSES),
        )

    def list_facilities(
        self,
        limit: int,
        offset: int,
        region_id: int | None = None,
        facility_type: str | None = None,
        source_layer: str | None = None,
        q: str | None = None,
    ) -> PaginatedFacilitiesOut:
        try:
            stmt = self._facility_stmt()
            if region_id is not None:
                stmt = stmt.where(Facility.region_id == region_id)
            if facility_type is not None:
                stmt = stmt.where(
                    func.lower(func.coalesce(Facility.type, Facility.source_layer))
                    == facility_type.lower()
                )
            if source_layer is not None:
                stmt = stmt.where(Facility.source_layer == source_layer)
            if q and q.strip():
                pat = f"%{q.strip()}%"
                stmt = stmt.where(
                    or_(
                        Facility.facility_name_en.ilike(pat),
                        Facility.facility_name_ar.ilike(pat),
                        Facility.city.ilike(pat),
                    )
                )
            total = int(
                self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            )
            page = self._session.scalars(
                stmt.order_by(Facility.facility_id).limit(limit).offset(offset)
            ).all()
            items = [_facility_item(_row_to_dict(f)) for f in page]
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc
        return PaginatedFacilitiesOut(
            governance_notice=_FACILITY_NOTICE,
            total=total,
            limit=limit,
            offset=offset,
            items=items,
        )

    def get_facility(self, ch_fid: str) -> FacilityDetailOut | None:
        try:
            f = self._session.scalars(self._facility_stmt().where(Facility.ch_fid == ch_fid)).first()
            row = _row_to_dict(f) if f is not None else None
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc
        return _facility_detail(row) if row is not None else None

    def list_open_questions(
        self, status: str | None = None, category: str | None = None
    ) -> PaginatedOpenQuestionsOut:
        try:
            stmt = select(OpenQuestion).order_by(OpenQuestion.oq_id)
            if status is not None:
                stmt = stmt.where(OpenQuestion.status == status)
            if category is not None:
                stmt = stmt.where(OpenQuestion.category == category)
            oqs = [_row_to_dict(o) for o in self._session.scalars(stmt).all()]
            links: dict[str, list[str]] = {}
            for model in (RuleOpenQuestion, RuleItemOpenQuestion):
                for oq_id, rule_id in self._session.execute(select(model.oq_id, model.rule_id)).all():
                    links.setdefault(oq_id, []).append(rule_id)
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc
        items = [_open_question_out(o, links.get(o["oq_id"], [])) for o in oqs]
        return PaginatedOpenQuestionsOut(total=len(items), items=items)

    def get_open_question(self, oq_id: str) -> OpenQuestionOut | None:
        return next((o for o in self.list_open_questions().items if o.oq_id == oq_id), None)

    def get_patient_outreach_inputs(
        self, patient_id: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        try:
            gr, er = self._latest_runs()
            p = self._session.scalars(
                select(Patient).where(Patient.run_id == gr.run_id, Patient.patient_id == patient_id)
            ).first()
            if p is None:
                return None, [], [], []
            evals = [
                _row_to_dict(e)
                for e in self._session.scalars(
                    select(EligibilityEvaluation).where(
                        EligibilityEvaluation.patient_id == patient_id,
                        EligibilityEvaluation.evaluation_run_id == er.evaluation_run_id,
                    )
                ).all()
            ]
            gaps = [
                _row_to_dict(g)
                for g in self._session.scalars(
                    select(CareGap).where(CareGap.run_id == gr.run_id, CareGap.patient_id == patient_id)
                ).all()
            ]
            consents = [
                _row_to_dict(c)
                for c in self._session.scalars(
                    select(Consent).where(Consent.run_id == gr.run_id, Consent.patient_id == patient_id)
                ).all()
            ]
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc
        return _row_to_dict(p), evals, gaps, consents

    def get_explanation_inputs(
        self, patient_id: str, rule_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str, list[dict[str, Any]], list[str]]:
        try:
            gr, er = self._latest_runs()
            ev = self._session.scalars(
                select(EligibilityEvaluation).where(
                    EligibilityEvaluation.patient_id == patient_id,
                    EligibilityEvaluation.rule_id == rule_id,
                    EligibilityEvaluation.evaluation_run_id == er.evaluation_run_id,
                )
            ).first()
            if ev is None:
                return None, None, "not_available", [], []
            r_meta = self._session.scalars(select(Rule).where(Rule.rule_id == rule_id)).first()
            if r_meta is None:
                return None, None, "not_available", [], []
            h_status = self._patient_history_map([patient_id], run_id=gr.run_id).get(patient_id, {}).get(
                r_meta.pathway, "not_available"
            )
            eval_reasons = [
                _row_to_dict(r)
                for r in self._session.scalars(
                    select(EvaluationReason)
                    .where(EvaluationReason.evaluation_id == ev.evaluation_id)
                    .order_by(EvaluationReason.reason_ordinal)
                ).all()
            ]
            rule_oqs = [
                roq.oq_id
                for roq in self._session.scalars(
                    select(RuleOpenQuestion).where(
                        RuleOpenQuestion.rule_id == rule_id,
                        RuleOpenQuestion.rule_version == r_meta.rule_version,
                    )
                ).all()
            ]
            std = self._session.scalars(
                select(Standard).where(Standard.standard_id == r_meta.standard_id)
            ).first()
            meta = _row_to_dict(r_meta)
            if std is not None:
                meta["source_name"] = std.source_name
                meta["source_version"] = std.source_version
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc
        return _row_to_dict(ev), meta, h_status, eval_reasons, sorted(rule_oqs)

    def get_patient_history(self, patient_id: str) -> PatientHistoryOut | None:
        try:
            gr, _ = self._latest_runs()
            p = self._session.scalars(
                select(Patient).where(
                    Patient.run_id == gr.run_id,
                    Patient.patient_id == patient_id,
                )
            ).first()
            if p is None:
                return None
            guardians = [
                _row_to_dict(g)
                for g in self._session.scalars(
                    select(Guardian).where(
                        Guardian.run_id == gr.run_id,
                        Guardian.patient_id == patient_id,
                    )
                ).all()
            ]
            history_availabilities = [
                _row_to_dict(h)
                for h in self._session.scalars(
                    select(HistoryAvailability).where(
                        HistoryAvailability.run_id == gr.run_id,
                        HistoryAvailability.patient_id == patient_id,
                    )
                ).all()
            ]
            ifhas_screenings = [
                _row_to_dict(s)
                for s in self._session.scalars(
                    select(IfhasScreening).where(
                        IfhasScreening.run_id == gr.run_id,
                        IfhasScreening.patient_id == patient_id,
                    )
                ).all()
            ]
            well_child_visits = [
                _row_to_dict(v)
                for v in self._session.scalars(
                    select(WellChildVisit).where(
                        WellChildVisit.run_id == gr.run_id,
                        WellChildVisit.patient_id == patient_id,
                    )
                ).all()
            ]
            component_results = [
                _row_to_dict(c)
                for c in self._session.scalars(
                    select(ComponentResult).where(
                        ComponentResult.run_id == gr.run_id,
                        ComponentResult.patient_id == patient_id,
                    )
                ).all()
            ]
            assessments = [
                _row_to_dict(a)
                for a in self._session.scalars(
                    select(Assessment).where(
                        Assessment.run_id == gr.run_id,
                        Assessment.patient_id == patient_id,
                    )
                ).all()
            ]
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

        return _build_patient_history_out(
            patient_id=patient_id,
            guardians=guardians,
            history_availabilities=history_availabilities,
            ifhas_screenings=ifhas_screenings,
            well_child_visits=well_child_visits,
            component_results=component_results,
            assessments=assessments,
        )

    def get_patient_consents(self, patient_id: str) -> PatientConsentsOut | None:
        try:
            gr, _ = self._latest_runs()
            p = self._session.scalars(
                select(Patient).where(
                    Patient.run_id == gr.run_id,
                    Patient.patient_id == patient_id,
                )
            ).first()
            if p is None:
                return None
            consents = [
                _row_to_dict(c)
                for c in self._session.scalars(
                    select(Consent).where(
                        Consent.run_id == gr.run_id,
                        Consent.patient_id == patient_id,
                    )
                ).all()
            ]
        except SQLAlchemyError as exc:
            raise _db_query_failed(exc) from exc

        return _build_patient_consents_out(patient_id=patient_id, consents=consents)
