"""FastAPI `/api/v1/*` router (`app.api.v1`).

Implements Workstream D1–D3 of `pulse-reach-backend-execution-plan.md`:
- Serves deterministic clinical rules, seeded synthetic patients, evaluations, care gaps,
  official facility reference points (with explicit governance notices), bounded explanations,
  and permission-checked simulated outreach previews.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from app.schemas.v1 import (
    CareGapOut,
    DashboardSummaryOut,
    EvaluateRequestIn,
    EvaluationItemOut,
    EvaluationReasonOut,
    ExplanationOut,
    ExplanationRequestIn,
    FacilityItemOut,
    OutreachPreviewOut,
    OutreachPreviewRequestIn,
    PaginatedCareGapsOut,
    PaginatedFacilitiesOut,
    PaginatedPatientsOut,
    PaginatedRulesOut,
    PatientEvaluationsOut,
    PatientSummaryOut,
    RuleDetailOut,
    RuleItemOut,
    RulesSummaryOut,
    RuleSummaryOut,
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
from app.services.explanation import (
    BoundedExplanationInput,
    ExplanationService,
    OutreachPreviewInput,
    PrivacyViolationError,
)
from app.services.official_loader import parse as official_parse
from app.services.synthetic_generator import (
    SyntheticDataset,
    generate_synthetic_dataset,
)

router = APIRouter(prefix="/api/v1", tags=["v1"])


@dataclass(frozen=True)
class _DatasetIndex:
    dataset: SyntheticDataset
    patients_by_id: dict[str, dict[str, Any]]
    history_by_patient: dict[str, dict[str, str]]
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
def _get_bundle() -> ParsedClinicalBundle:
    return parse_clinical_bundle()


@lru_cache(maxsize=1)
def _get_engine() -> EvaluationEngine:
    return EvaluationEngine(_get_bundle())


@lru_cache(maxsize=1)
def _get_dataset() -> SyntheticDataset:
    return generate_synthetic_dataset(seed=20261116, total_patients=550, bundle=_get_bundle())


@lru_cache(maxsize=1)
def _get_index() -> _DatasetIndex:
    ds = _get_dataset()
    patients_by_id = {p["patient_id"]: p for p in ds.patients}
    history_by_patient: dict[str, dict[str, str]] = {}
    for h in ds.history_availabilities:
        history_by_patient.setdefault(h["patient_id"], {})[h["pathway"]] = h["history_status"]

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
        history_by_patient=history_by_patient,
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


@lru_cache(maxsize=1)
def _get_facilities() -> list[FacilityItemOut]:
    root = repo_root()
    sdi_dir = root / "data" / "raw" / "abudhabi_sdi"
    if (sdi_dir / "acquisition_log.json").exists():
        sdi_to_region = {r[3]: r[0] for r in official_parse.REGIONS}
        file_rels = {
            layer: f"data/raw/abudhabi_sdi/{layer}.geojson"
            for layer in official_parse.SDI_LAYERS
        }
        fac_unit = official_parse.parse_facilities(root, sdi_to_region, file_rels)
        usable = [
            r
            for r in fac_unit.rows
            if r["identity_status"] == "identified"
            and r["geo_quality"] == "ok"
            and r["license_status_raw"] in ("Active", "Temporary Closure")
        ]
        items: list[FacilityItemOut] = []
        for idx, r in enumerate(usable, 1):
            is_primary = r["source_layer"] in ("center", "clinic", "hospital")
            items.append(
                FacilityItemOut(
                    facility_id=idx,
                    facility_name=r["facility_name_en"] or f"SDI Facility {idx}",
                    region_id=r["region_id"] or 1,
                    facility_type=r["type"] or r["source_layer"],
                    license_status=r["license_status_raw"] or "Active",
                    simulated_ifhas_service=is_primary and (r["region_id"] != 3 or idx % 2 == 1),
                    simulated_wcv_service=is_primary,
                    capability_basis="simulated_overlay_only",
                )
            )
        return items

    return [
        FacilityItemOut(
            facility_id=1,
            facility_name="Abu Dhabi Preventive Care Center (Simulated Overlay)",
            region_id=1,
            facility_type="Center",
            license_status="Active",
            simulated_ifhas_service=True,
            simulated_wcv_service=True,
        ),
        FacilityItemOut(
            facility_id=2,
            facility_name="Al Ain Family Screening Clinic (Simulated Overlay)",
            region_id=2,
            facility_type="Clinic",
            license_status="Active",
            simulated_ifhas_service=True,
            simulated_wcv_service=True,
        ),
        FacilityItemOut(
            facility_id=3,
            facility_name="Al Dhafra Community Maternal & Child Clinic (Simulated Overlay)",
            region_id=3,
            facility_type="Clinic",
            license_status="Active",
            simulated_ifhas_service=False,
            simulated_wcv_service=True,
        ),
    ]


_explanation_service = ExplanationService(llm_provider=None)


def _build_patient_summary(
    p: dict[str, Any], history_by_patient: dict[str, dict[str, str]]
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
        history_by_pathway=history_by_patient.get(p["patient_id"], {}),
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
        subject_ifhas_screening_id=g["subject_ifhas_screening_id"],
        subject_well_child_visit_id=g["subject_well_child_visit_id"],
        subject_referral_id=g["subject_referral_id"],
        priority_score=float(g["priority_score"]) if g["priority_score"] is not None else None,
        priority_explanation=g["priority_explanation"],
        scoring_suppressed_reason=g["scoring_suppressed_reason"],
        is_synthetic=True,
    )


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary() -> DashboardSummaryOut:
    bundle = _get_bundle()
    ds = _get_dataset()
    gr = ds.generation_run
    er = ds.evaluation_run

    status_counts = Counter(e["evaluation_status"] for e in ds.eligibility_evaluations)
    open_gaps = sum(1 for g in ds.care_gaps if g["status"] == "open")
    refused_gaps = sum(1 for g in ds.care_gaps if g["status"] == "closed_refused")

    auth_rules = sum(1 for r in bundle.rules if r["is_authoritative"])
    flagged_rules = sum(1 for r in bundle.rules if r["requires_clinical_review"])
    unres_rules = sum(1 for r in bundle.rules if r["verification_status"] == "unresolved")

    return DashboardSummaryOut(
        is_synthetic=True,
        run_id=gr["run_id"],
        evaluation_run_id=er["evaluation_run_id"],
        reference_date=er["reference_date"],
        total_patients=len(ds.patients),
        n_adults=gr["n_adults"],
        n_children=gr["n_children"],
        open_care_gaps_count=open_gaps,
        closed_refused_care_gaps_count=refused_gaps,
        evaluation_status_counts=dict(status_counts),
        rules_summary=RulesSummaryOut(
            total_rules=len(bundle.rules),
            authoritative_rules=auth_rules,
            review_flagged_rules=flagged_rules,
            unresolved_rules=unres_rules,
            total_rule_items=len(bundle.items),
            clinical_review_status=bundle.clinical_review_status,
        ),
        governance_disclaimer=(
            "All patient records shown are 100% synthetic (`is_synthetic=true`). Clinical rules are "
            "transcribed from published DoH standards for engineering use (`clinical_review_status=not_reviewed`) "
            "and require healthcare-professional review."
        ),
    )


@router.get("/patients", response_model=PaginatedPatientsOut)
def list_patients(
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sex: Literal["female", "male"] | None = Query(default=None),
    region_id: int | None = Query(default=None, ge=1, le=3),
    pathway: Literal["ifhas", "well_child"] | None = Query(default=None),
) -> PaginatedPatientsOut:
    idx = _get_index()
    filtered = idx.dataset.patients
    if sex is not None:
        filtered = [p for p in filtered if p["sex"] == sex]
    if region_id is not None:
        filtered = [p for p in filtered if p["region_id"] == region_id]
    if pathway is not None:
        filtered = [
            p for p in filtered if pathway in idx.history_by_patient.get(p["patient_id"], {})
        ]

    page = filtered[offset : offset + limit]
    return PaginatedPatientsOut(
        is_synthetic=True,
        total=len(filtered),
        limit=limit,
        offset=offset,
        items=[_build_patient_summary(p, idx.history_by_patient) for p in page],
    )


@router.get("/patients/{patient_id}", response_model=PatientSummaryOut)
def get_patient(patient_id: str) -> PatientSummaryOut:
    idx = _get_index()
    p = idx.patients_by_id.get(patient_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Synthetic patient '{patient_id}' not found")
    return _build_patient_summary(p, idx.history_by_patient)


def _get_patient_evaluations_payload(patient_id: str) -> PatientEvaluationsOut:
    bundle = _get_bundle()
    idx = _get_index()
    if patient_id not in idx.patients_by_id:
        raise HTTPException(status_code=404, detail=f"Synthetic patient '{patient_id}' not found")

    rule_meta = {r["rule_id"]: r for r in bundle.rules}
    eval_items: list[EvaluationItemOut] = []
    for ev in idx.evaluations_by_patient.get(patient_id, []):
        rm = rule_meta[ev["rule_id"]]
        reasons = [
            EvaluationReasonOut(
                reason_ordinal=r["reason_ordinal"],
                reason_code=r["reason_code"],
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
                pathway=rm["pathway"],
                rule_type=rm.get("rule_type"),
                evaluation_status=ev["evaluation_status"],
                reason_code=ev["reason_code"],
                next_due_date=ev["next_due_date"],
                evaluated_at=ev["evaluated_at"],
                reasons=reasons,
            )
        )

    gap_items = [_build_care_gap_out(g) for g in idx.care_gaps_by_patient.get(patient_id, [])]
    return PatientEvaluationsOut(
        is_synthetic=True,
        patient_id=patient_id,
        evaluation_run_id=idx.dataset.evaluation_run["evaluation_run_id"],
        reference_date=idx.dataset.evaluation_run["reference_date"],
        evaluations=eval_items,
        care_gaps=gap_items,
    )


def _build_patient_context(idx: _DatasetIndex, patient_id: str) -> PatientContext:
    p = idx.patients_by_id[patient_id]
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
        for s in idx.ifhas_by_patient.get(patient_id, [])
    )
    visits = tuple(
        VisitEventFact(
            visit_id=v["visit_id"],
            rule_id=v["rule_id"],
            rule_version=v["rule_version"],
            attendance_status=v["attendance_status"],
            performed_date=v["performed_date"],
        )
        for v in idx.wcv_by_patient.get(patient_id, [])
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
                (cr["performed_date"] or idx.dataset.evaluation_run["reference_date"]).year,
                (cr["performed_date"] or idx.dataset.evaluation_run["reference_date"]).month,
                (cr["performed_date"] or idx.dataset.evaluation_run["reference_date"]).day,
                tzinfo=timezone.utc,
            ),
            documented_in_record=bool(cr.get("documented_in_record")),
            signature_on_file=bool(cr.get("signature_on_file")),
            refused_by_guardian_id=cr.get("refused_by_guardian_id"),
        )
        for cr in idx.crs_by_patient.get(patient_id, [])
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
        for a in idx.assessments_by_patient.get(patient_id, [])
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
        for r in idx.referrals_by_patient.get(patient_id, [])
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
        for c in idx.consents_by_patient.get(patient_id, [])
    )
    return PatientContext(
        patient_id=patient_id,
        date_of_birth=p["date_of_birth"],
        sex=p["sex"],
        thiqa_member=p["thiqa_member"],
        ever_smoked=p["ever_smoked"],
        history_by_pathway=dict(idx.history_by_patient.get(patient_id, {})),
        ifhas_screenings=screenings,
        well_child_visits=visits,
        component_results=crs,
        developmental_assessments=assessments,
        referrals=referrals,
        consents=consents,
    )


@router.get("/patients/{patient_id}/evaluations", response_model=PatientEvaluationsOut)
def get_patient_evaluations(patient_id: str) -> PatientEvaluationsOut:
    return _get_patient_evaluations_payload(patient_id)


@router.post("/evaluations", response_model=PatientEvaluationsOut)
def run_evaluation(req: EvaluateRequestIn) -> PatientEvaluationsOut:
    idx = _get_index()
    if req.patient_id not in idx.patients_by_id:
        raise HTTPException(
            status_code=404, detail=f"Synthetic patient '{req.patient_id}' not found"
        )
    if req.look_ahead_days == idx.dataset.evaluation_run["look_ahead_days"]:
        return _get_patient_evaluations_payload(req.patient_id)

    ctx = _build_patient_context(idx, req.patient_id)
    summary = _get_engine().evaluate_patient(
        ctx,
        reference_date=idx.dataset.evaluation_run["reference_date"],
        look_ahead_days=req.look_ahead_days,
    )
    eval_items: list[EvaluationItemOut] = []
    eval_id_by_rule: dict[str, str] = {}
    for ord_ev, ev in enumerate(summary.evaluations, 1):
        eid = f"SYNTH-EVL-{ord_ev:06d}"
        eval_id_by_rule[ev.rule_id] = eid
        eval_items.append(
            EvaluationItemOut(
                evaluation_id=eid,
                patient_id=req.patient_id,
                rule_id=ev.rule_id,
                rule_version=ev.rule_version,
                pathway=ev.pathway,
                rule_type=ev.rule_type,
                evaluation_status=ev.evaluation_status,
                reason_code=ev.reason_code,
                next_due_date=ev.next_due_date,
                evaluated_at=ev.evaluated_at,
                reasons=[
                    EvaluationReasonOut(
                        reason_ordinal=i,
                        reason_code=r.reason_code,
                        guard_id=r.guard_id,
                        item_category=r.item_category,
                        item_code=r.item_code,
                    )
                    for i, r in enumerate(ev.reasons, 1)
                ],
            )
        )
    gap_items = [
        CareGapOut(
            care_gap_id=f"SYNTH-GAP-{i:06d}",
            patient_id=req.patient_id,
            evaluation_id=eval_id_by_rule[gf.rule_id],
            rule_id=gf.rule_id,
            rule_version=gf.rule_version,
            gap_type=gf.gap_type,
            status=gf.status,
            identified_date=gf.opened_date,
            closed_date=gf.closed_date,
            closed_by_consent_id=gf.closed_by_consent_id,
            closed_by_component_result_id=gf.closed_by_component_result_id,
            subject_ifhas_screening_id=gf.subject_ifhas_screening_id,
            subject_well_child_visit_id=gf.subject_well_child_visit_id,
            subject_referral_id=gf.subject_referral_id,
            is_synthetic=True,
        )
        for i, gf in enumerate(summary.care_gaps, 1)
    ]
    return PatientEvaluationsOut(
        is_synthetic=True,
        patient_id=req.patient_id,
        evaluation_run_id=idx.dataset.evaluation_run["evaluation_run_id"],
        reference_date=summary.reference_date,
        evaluations=eval_items,
        care_gaps=gap_items,
    )


@router.get("/rules", response_model=PaginatedRulesOut)
def list_rules(
    pathway: Literal["ifhas", "well_child"] | None = Query(default=None),
    verification_status: Literal["verified", "reported", "unresolved"] | None = Query(
        default=None
    ),
    is_authoritative: bool | None = Query(default=None),
) -> PaginatedRulesOut:
    bundle = _get_bundle()
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
            open_question_ids=oqs_by_rule.get((r["rule_id"], r["rule_version"]), []),
        )
        for r in rules
    ]
    return PaginatedRulesOut(total=len(items), items=items)


@router.get("/rules/{rule_id}", response_model=RuleDetailOut)
def get_rule_detail(rule_id: str) -> RuleDetailOut:
    bundle = _get_bundle()
    r_map = {r["rule_id"]: r for r in bundle.rules}
    if rule_id not in r_map:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    r = r_map[rule_id]
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
            open_question_ids=item_oqs_map.get((it["category"], it["code"]), []),
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
        open_question_ids=rule_oqs,
        items=rule_items,
    )


@router.get("/care-gaps", response_model=PaginatedCareGapsOut)
def list_care_gaps(
    status: Literal[
        "open", "closed_completed", "closed_refused", "suppressed", "superseded"
    ]
    | None = Query(default=None),
    gap_type: Literal[
        "no_documented_screening",
        "interval_elapsed",
        "partial_completion",
        "referral_not_initiated",
        "visit_not_attended",
    ]
    | None = Query(default=None),
    rule_id: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedCareGapsOut:
    ds = _get_dataset()
    gaps = ds.care_gaps
    if status is not None:
        gaps = [g for g in gaps if g["status"] == status]
    if gap_type is not None:
        gaps = [g for g in gaps if g["gap_type"] == gap_type]
    if rule_id is not None:
        gaps = [g for g in gaps if g["rule_id"] == rule_id]

    page = gaps[offset : offset + limit]
    return PaginatedCareGapsOut(
        is_synthetic=True,
        total=len(gaps),
        limit=limit,
        offset=offset,
        items=[_build_care_gap_out(g) for g in page],
    )


@router.get("/facilities", response_model=PaginatedFacilitiesOut)
def list_facilities(
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedFacilitiesOut:
    ref_facilities = _get_facilities()
    page = ref_facilities[offset : offset + limit]
    return PaginatedFacilitiesOut(
        governance_notice=(
            "Official SDI facility register contains point locations and licence status only; "
            "preventive-programme service capabilities (IFHAS / Well-Child) are a SIMULATED overlay "
            "(Decision D13 pending external licensing/governance confirmation)."
        ),
        total=len(ref_facilities),
        limit=limit,
        offset=offset,
        items=page,
    )


@router.post("/explanations", response_model=ExplanationOut)
def create_explanation(req: ExplanationRequestIn) -> ExplanationOut:
    bundle = _get_bundle()
    idx = _get_index()

    ev_match = next(
        (
            e
            for e in idx.evaluations_by_patient.get(req.patient_id, [])
            if e["rule_id"] == req.rule_id
        ),
        None,
    )
    if ev_match is None:
        raise HTTPException(
            status_code=404,
            detail=f"Evaluation for patient '{req.patient_id}' and rule '{req.rule_id}' not found",
        )

    r_meta = next(r for r in bundle.rules if r["rule_id"] == req.rule_id)
    h_status = idx.history_by_patient.get(req.patient_id, {}).get(
        r_meta["pathway"], "not_available"
    )
    eval_reasons = idx.reasons_by_eval.get(ev_match["evaluation_id"], [])
    rule_oqs = [
        roq["oq_id"]
        for roq in bundle.rule_open_questions
        if roq["rule_id"] == req.rule_id and roq["rule_version"] == r_meta["rule_version"]
    ]

    try:
        res = _explanation_service.explain_evaluation(
            BoundedExplanationInput(
                synthetic_patient_id=req.patient_id,
                pathway=r_meta["pathway"],
                standard_name=r_meta["source_name"],
                rule_id=req.rule_id,
                rule_version=r_meta["rule_version"],
                source_reference=r_meta["source_reference"],
                verification_status=r_meta["verification_status"],
                is_authoritative=r_meta["is_authoritative"],
                evaluation_status=ev_match["evaluation_status"],
                history_status=h_status,
                reason_codes=tuple(r["reason_code"] for r in eval_reasons),
                guard_ids=tuple(r["guard_id"] for r in eval_reasons if r["guard_id"]),
                open_question_ids=tuple(rule_oqs),
                next_due_date=(
                    ev_match["next_due_date"].isoformat()
                    if ev_match["next_due_date"] is not None
                    else None
                ),
            )
        )
    except PrivacyViolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ExplanationOut(
        synthetic_patient_id=res.synthetic_patient_id,
        rule_id=res.rule_id,
        rule_version=res.rule_version,
        evaluation_status=res.evaluation_status,
        is_authoritative=res.is_authoritative,
        is_synthetic=True,
        generation_mode=res.generation_mode,
        summary_text=res.summary_text,
        why_text=res.why_text,
        missing_or_uncertain_text=res.missing_or_uncertain_text,
        rule_citation_text=res.rule_citation_text,
        warnings=list(res.warnings),
    )


@router.post("/outreach/preview", response_model=OutreachPreviewOut)
def preview_outreach(req: OutreachPreviewRequestIn) -> OutreachPreviewOut:
    idx = _get_index()
    p = idx.patients_by_id.get(req.patient_id)
    if p is None:
        raise HTTPException(
            status_code=404, detail=f"Synthetic patient '{req.patient_id}' not found"
        )

    contact_consents = [
        c
        for c in idx.consents_by_patient.get(req.patient_id, [])
        if c["consent_type"] == "contact"
    ]
    c_state = contact_consents[-1]["state"] if contact_consents else None

    gap = next(
        (
            g
            for g in idx.care_gaps_by_patient.get(req.patient_id, [])
            if g["rule_id"] == req.rule_id
        ),
        None,
    )

    try:
        res = _explanation_service.preview_outreach(
            OutreachPreviewInput(
                synthetic_patient_id=req.patient_id,
                care_gap_id=gap["care_gap_id"] if gap else None,
                rule_id=req.rule_id,
                rule_version="1.0.0",
                channel=req.channel,
                language=req.language,
                contact_consent_state=c_state,
                contact_status=p["contact_status"],
                is_deceased=p["date_of_death"] is not None,
            )
        )
    except PrivacyViolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return OutreachPreviewOut(
        synthetic_patient_id=res.synthetic_patient_id,
        care_gap_id=res.care_gap_id,
        rule_id=res.rule_id,
        rule_version=res.rule_version,
        allowed=res.allowed,
        simulated_only=True,
        blocked_reason=res.blocked_reason,
        preview_message=res.preview_message,
        disclaimer=res.disclaimer,
    )
