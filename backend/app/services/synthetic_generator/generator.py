"""Deterministic, seed-based synthetic patient dataset generator (`app.services.synthetic_generator.generator`).

Implements Workstream B2–B4 of `pulse-reach-backend-execution-plan.md` and the 27 edge-case scenarios
in `data/metadata/synthetic_data_spec.md`.
- Uses `random.Random(seed)` for 100% deterministic, repeatable output.
- Evaluates every synthetic patient through the real `EvaluationEngine` (`app.services.evaluation`)
  so all `eligibility_evaluation`, `evaluation_reason`, and `care_gap` rows are guaranteed to obey
  the clinical YAML rules and guards.
- Enforces all safety invariants (`is_synthetic=True`, `SYNTH-<CODE>-` IDs, `SYNTH-EID-` Emirates IDs,
  ` (synthetic)` family names, `@example.invalid` emails, `+971-50-000-XXXX` phone numbers).
"""

from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.clinical_loader.parse import (
    ParsedClinicalBundle,
    git_commit_if_clean,
    parse_clinical_bundle,
    repo_root,
)
from app.services.evaluation import (
    ENGINE_VERSION,
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
    evaluation_reason_detail,
    evaluation_snapshot,
    fired_reason_detail,
)
from app.services.synthetic_generator.conditions import generate_condition_records
from app.services.followup.completion import (
    CompletionEvidence,
    evaluate_current_rule,
    validate_completion_evidence,
)

GENERATOR_VERSION = "0.1.0"
SPEC_VERSION = "2.6.0"
DEFAULT_RUN_ID = "SYNTH-RUN-0001"
DEFAULT_EVAL_RUN_ID = "SYNTH-EVR-000001"
DEFAULT_REFERENCE_DATE = date(2026, 11, 16)

_GIVEN_NAMES_FEMALE = (
    "Fatima",
    "Mariam",
    "Aisha",
    "Noora",
    "Salama",
    "Hessa",
    "Meera",
    "Shamma",
    "Latifa",
    "Sara",
    "Layla",
    "Amna",
)
_GIVEN_NAMES_MALE = (
    "Mohammed",
    "Ahmed",
    "Saeed",
    "Rashid",
    "Zayed",
    "Hamdan",
    "Sultan",
    "Khalid",
    "Omar",
    "Abdullah",
    "Mansoor",
    "Tariq",
)
_FAMILY_SURNAMES = (
    "Al-Mansoori",
    "Al-Nuaimi",
    "Al-Mazrouei",
    "Al-Dhaheri",
    "Al-Kaabi",
    "Al-Shamsi",
    "Al-Ketbi",
    "Al-Zaabi",
    "Al-Suwaidi",
    "Al-Muhairi",
)
_DISTRICTS_BY_REGION = {
    1: ("Khalifa City", "Al Bateen", "Mussafah", "Al Reem Island", "Baniyas"),
    2: ("Al Jimi", "Al Muwaiji", "Zakhir", "Al Towayya"),
    3: ("Madinat Zayed", "Ruwais", "Ghayathi", "Liwa"),
}


@dataclass(frozen=True)
class SyntheticDataset:
    generation_run: dict[str, Any]
    evaluation_run: dict[str, Any]
    facility_service_profiles: list[dict[str, Any]]
    patients: list[dict[str, Any]]
    guardians: list[dict[str, Any]]
    consents: list[dict[str, Any]]
    history_availabilities: list[dict[str, Any]]
    eligibility_evaluations: list[dict[str, Any]]
    evaluation_reasons: list[dict[str, Any]]
    appointments: list[dict[str, Any]]
    ifhas_screenings: list[dict[str, Any]]
    well_child_visits: list[dict[str, Any]]
    component_results: list[dict[str, Any]]
    assessments: list[dict[str, Any]]
    referrals: list[dict[str, Any]]
    care_gaps: list[dict[str, Any]]
    care_gap_reviews: list[dict[str, Any]]
    outreach_events: list[dict[str, Any]]
    condition_records: list[dict[str, Any]] = dataclasses.field(default_factory=list)  # BE-33


def generate_synthetic_dataset(
    *,
    seed: int = 20261116,
    total_patients: int = 550,
    run_id: str = DEFAULT_RUN_ID,
    eval_run_id: str = DEFAULT_EVAL_RUN_ID,
    reference_date: date = DEFAULT_REFERENCE_DATE,
    rule_bundle_load_id: int = 1,
    bundle: ParsedClinicalBundle | None = None,
) -> SyntheticDataset:
    """Generate a deterministic, seed-based synthetic dataset across all 18 `synthetic.*` tables."""
    if total_patients < 30:
        raise ValueError("total_patients must be at least 30 to include all mandatory scenarios")

    rng = random.Random(seed)
    clinical_bundle = bundle if bundle is not None else parse_clinical_bundle()
    engine = EvaluationEngine(clinical_bundle)

    started_ts = datetime(
        reference_date.year, reference_date.month, reference_date.day, 8, 0, tzinfo=timezone.utc
    )
    eval_ts = datetime(
        reference_date.year, reference_date.month, reference_date.day, 9, 0, tzinfo=timezone.utc
    )

    # Simulated facility profiles (explicitly labelled capability_basis='simulated')
    facility_service_profiles: list[dict[str, Any]] = [
        {
            "profile_id": "SYNTH-FSP-000001",
            "run_id": run_id,
            "is_synthetic": True,
            "facility_id": 1,
            "offers_ifhas": True,
            "offers_wcv": True,
            "evening_hours": True,
            "weekend_hours": True,
            "capability_basis": "simulated",
        },
        {
            "profile_id": "SYNTH-FSP-000002",
            "run_id": run_id,
            "is_synthetic": True,
            "facility_id": 2,
            "offers_ifhas": True,
            "offers_wcv": True,
            "evening_hours": False,
            "weekend_hours": False,
            "capability_basis": "simulated",
        },
        {
            "profile_id": "SYNTH-FSP-000003",
            "run_id": run_id,
            "is_synthetic": True,
            "facility_id": 3,
            "offers_ifhas": False,
            "offers_wcv": True,
            "evening_hours": False,
            "weekend_hours": False,
            "capability_basis": "simulated",
        },
    ]

    patients: list[dict[str, Any]] = []
    guardians: list[dict[str, Any]] = []
    consents: list[dict[str, Any]] = []
    history_availabilities: list[dict[str, Any]] = []
    appointments: list[dict[str, Any]] = []
    ifhas_screenings: list[dict[str, Any]] = []
    well_child_visits: list[dict[str, Any]] = []
    component_results: list[dict[str, Any]] = []
    assessments: list[dict[str, Any]] = []
    referrals: list[dict[str, Any]] = []
    eligibility_evaluations: list[dict[str, Any]] = []
    evaluation_reasons: list[dict[str, Any]] = []
    care_gaps: list[dict[str, Any]] = []
    care_gap_reviews: list[dict[str, Any]] = []
    outreach_events: list[dict[str, Any]] = []

    grd_seq = 0
    cns_seq = 0
    hst_seq = 0
    apt_seq = 0
    scr_seq = 0
    vis_seq = 0
    cmp_seq = 0
    asm_seq = 0
    ref_seq = 0
    evl_seq = 0
    ers_seq = 0
    gap_seq = 0
    rev_seq = 0
    out_seq = 0
    ctx_by_patient: dict[str, PatientContext] = {}

    def _next_id(prefix: str, seq: int) -> str:
        return f"SYNTH-{prefix}-{seq:06d}"

    def _make_patient_base(
        idx: int,
        *,
        sex: str | None,
        dob: date | None,
        thiqa: bool | None = True,
        smoked: bool | None = False,
        region_id: int = 1,
        profile_id: str = "SYNTH-FSP-000001",
        contact_status: str = "valid",
        date_of_death: date | None = None,
    ) -> dict[str, Any]:
        pid = _next_id("PAT", idx)
        gname = (
            rng.choice(_GIVEN_NAMES_FEMALE)
            if sex == "female"
            else rng.choice(_GIVEN_NAMES_MALE)
        )
        fname = f"{rng.choice(_FAMILY_SURNAMES)} (synthetic)"
        district = rng.choice(_DISTRICTS_BY_REGION.get(region_id, ("Khalifa City",)))
        return {
            "patient_id": pid,
            "run_id": run_id,
            "is_synthetic": True,
            "emirates_id_synthetic": f"SYNTH-EID-{idx:08d}",
            "given_name": gname,
            "family_name": fname,
            "date_of_birth": dob,
            "sex": sex,
            "nationality_group": "emirati" if thiqa is not False else "non_emirati",
            "region_id": region_id,
            "district_label": district,
            "thiqa_member": thiqa,
            "ever_smoked": smoked,
            "preferred_language": rng.choice(("ar", "en")),
            "preferred_channel": rng.choice(("sms", "app", "phone", "email")),
            "phone_synthetic": f"+971-50-000-{idx % 10000:04d}",
            "email_synthetic": f"patient.{idx:06d}@example.invalid",
            "contact_status": contact_status,
            "registered_profile_id": profile_id,
            "date_of_death": date_of_death,
        }

    def _add_guardian(patient_row: dict[str, Any], idx: int) -> str:
        nonlocal grd_seq
        grd_seq += 1
        gid = _next_id("GDN", grd_seq)
        guardians.append(
            {
                "guardian_id": gid,
                "run_id": run_id,
                "patient_id": patient_row["patient_id"],
                "is_synthetic": True,
                "relationship": "mother" if idx % 2 == 0 else "father",
                "given_name": rng.choice(_GIVEN_NAMES_FEMALE if idx % 2 == 0 else _GIVEN_NAMES_MALE),
                "family_name": patient_row["family_name"],
                "phone_synthetic": patient_row["phone_synthetic"],
                "email_synthetic": f"guardian.{grd_seq:06d}@example.invalid",
                "preferred_language": patient_row["preferred_language"],
                "preferred_channel": patient_row["preferred_channel"],
                "contact_status": patient_row["contact_status"],
            }
        )
        return gid

    def _add_history(pid: str, pathway: str, status: str, note: str | None = None) -> None:
        nonlocal hst_seq
        hst_seq += 1
        history_availabilities.append(
            {
                "history_id": _next_id("HST", hst_seq),
                "run_id": run_id,
                "patient_id": pid,
                "is_synthetic": True,
                "pathway": pathway,
                "history_status": status,
                "as_of_date": reference_date,
                "note": note,
            }
        )

    def _add_consent(
        pid: str,
        *,
        consent_type: str,
        state: str,
        guardian_id: str | None = None,
        scope_pathway: str = "ifhas",
        scope_rule_id: str | None = None,
        scope_rule_version: str | None = None,
        documented: bool | None = None,
        signed: bool | None = None,
        refusal_reason: str | None = None,
    ) -> dict[str, Any]:
        nonlocal cns_seq
        cns_seq += 1
        cid = _next_id("CNS", cns_seq)
        row = {
            "consent_id": cid,
            "run_id": run_id,
            "patient_id": pid,
            "is_synthetic": True,
            "guardian_id": guardian_id,
            "consent_type": consent_type,
            "state": state,
            "applies_to": "child_by_guardian" if guardian_id is not None else "self",
            "scope_pathway": scope_pathway,
            "scope_rule_id": scope_rule_id,
            "scope_rule_version": scope_rule_version,
            "recorded_at": started_ts - timedelta(days=15),
            "recorded_by": "synthetic_intake_portal",
            "documented_in_record": documented,
            "signature_on_file": signed,
            "refusal_reason": refusal_reason if state == "refused" else None,
        }
        consents.append(row)
        return row

    # Build 30 deterministic edge-case patients (SYNTH-PAT-000001 .. SYNTH-PAT-000030)
    # plus seeded cohort up to total_patients
    n_adults = 0
    n_children = 0

    for idx in range(1, total_patients + 1):
        pid = _next_id("PAT", idx)
        patient_screenings: list[ScreeningEventFact] = []
        patient_visits: list[VisitEventFact] = []
        patient_crs: list[ComponentResultFact] = []
        patient_assessments: list[AssessmentFact] = []
        patient_referrals: list[ReferralFact] = []
        patient_consents: list[ConsentFact] = []
        history_map: dict[str, str] = {}
        guardian_id: str | None = None
        contact_consent_id: str | None = None
        ai_consent_id: str | None = None

        if idx == 1:
            # Scenario 1: 45yo Thiqa female, due for Mammography & other packages, AI + contact consent granted
            p = _make_patient_base(idx, sex="female", dob=date(1981, 5, 10), thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
            c_contact = _add_consent(pid, consent_type="contact", state="granted", scope_pathway="ifhas")
            c_ai = _add_consent(
                pid, consent_type="ai_assisted_prioritisation", state="granted", scope_pathway="ifhas"
            )
            contact_consent_id = c_contact["consent_id"]
            ai_consent_id = c_ai["consent_id"]
        elif idx == 2:
            # Scenario 2: 52yo Thiqa male, Major Package completed 14m ago
            p = _make_patient_base(idx, sex="male", dob=date(1974, 8, 20), thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
            scr_seq += 1
            sid = _next_id("SCR", scr_seq)
            perf = date(2025, 9, 16)
            ifhas_screenings.append(
                {
                    "screening_id": sid,
                    "run_id": run_id,
                    "patient_id": pid,
                    "is_synthetic": True,
                    "profile_id": p["registered_profile_id"],
                    "rule_id": "IFHAS-PKG-MAJOR-40-64",
                    "rule_version": "1.0.0",
                    "appointment_id": None,
                    "performed_date": perf,
                    "completion_status": "complete",
                    "results_communicated_date": perf + timedelta(days=5),
                    "journey_reported_date": perf + timedelta(days=10),
                    "has_abnormal_finding": False,
                }
            )
            patient_screenings.append(
                ScreeningEventFact(
                    sid,
                    "IFHAS-PKG-MAJOR-40-64",
                    "1.0.0",
                    "complete",
                    perf,
                    perf + timedelta(days=5),
                    perf + timedelta(days=10),
                )
            )
        elif idx == 3:
            # Scenario 3: 31yo female hitting Cervical HPV (requires_clinical_review)
            p = _make_patient_base(idx, sex="female", dob=date(1995, 4, 12), thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
        elif idx == 4:
            # Scenario 4: Aged 78 hitting IFHAS-PROG-AGE-CEILING
            p = _make_patient_base(idx, sex="male", dob=date(1948, 2, 10), thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
        elif idx == 5:
            # Scenario 5: thiqa_member = None -> insufficient_information
            p = _make_patient_base(idx, sex="female", dob=date(1980, 6, 1), thiqa=None, smoked=False)
            history_map["ifhas"] = "available"
        elif idx == 6:
            # Scenario 6: date_of_birth = None -> insufficient_information
            p = _make_patient_base(idx, sex="female", dob=None, thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
        elif idx == 7:
            # Scenario 7: history_availability = 'not_available' -> unknown, zero care gaps
            p = _make_patient_base(idx, sex="female", dob=date(1979, 11, 3), thiqa=True, smoked=False)
            history_map["ifhas"] = "not_available"
        elif idx == 8:
            # Scenario 8: Major package partial completion
            p = _make_patient_base(idx, sex="male", dob=date(1978, 3, 19), thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
            scr_seq += 1
            sid = _next_id("SCR", scr_seq)
            perf = date(2026, 10, 10)
            ifhas_screenings.append(
                {
                    "screening_id": sid,
                    "run_id": run_id,
                    "patient_id": pid,
                    "is_synthetic": True,
                    "profile_id": p["registered_profile_id"],
                    "rule_id": "IFHAS-PKG-MAJOR-40-64",
                    "rule_version": "1.0.0",
                    "appointment_id": None,
                    "performed_date": perf,
                    "completion_status": "partial",
                    "results_communicated_date": None,
                    "journey_reported_date": None,
                    "has_abnormal_finding": False,
                }
            )
            patient_screenings.append(
                ScreeningEventFact(sid, "IFHAS-PKG-MAJOR-40-64", "1.0.0", "partial", perf)
            )
        elif idx == 9:
            # Scenario 9: Abnormal FIT with uninitiated referral after 15 working days
            p = _make_patient_base(idx, sex="male", dob=date(1972, 7, 14), thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
            scr_seq += 1
            sid = _next_id("SCR", scr_seq)
            trig_date = date(2026, 9, 15)
            ifhas_screenings.append(
                {
                    "screening_id": sid,
                    "run_id": run_id,
                    "patient_id": pid,
                    "is_synthetic": True,
                    "profile_id": p["registered_profile_id"],
                    "rule_id": "IFHAS-PKG-FIT-40-75",
                    "rule_version": "1.0.0",
                    "appointment_id": None,
                    "performed_date": trig_date,
                    "completion_status": "complete",
                    "results_communicated_date": trig_date + timedelta(days=3),
                    "journey_reported_date": trig_date + timedelta(days=5),
                    "has_abnormal_finding": True,
                }
            )
            patient_screenings.append(
                ScreeningEventFact(
                    sid,
                    "IFHAS-PKG-FIT-40-75",
                    "1.0.0",
                    "complete",
                    trig_date,
                    trig_date + timedelta(days=3),
                    trig_date + timedelta(days=5),
                )
            )
            ref_seq += 1
            rid_ref = _next_id("REF", ref_seq)
            referrals.append(
                {
                    "referral_id": rid_ref,
                    "run_id": run_id,
                    "patient_id": pid,
                    "is_synthetic": True,
                    "ifhas_screening_id": sid,
                    "well_child_visit_id": None,
                    "assessment_id": None,
                    "trigger_rule_id": "IFHAS-WF-REFERRAL-15WD",
                    "trigger_rule_version": "1.0.0",
                    "rule_action_ordinal": 1,
                    "referral_target": "gastroenterology clinic",
                    "target_profile_id": "SYNTH-FSP-000001",
                    "trigger_date": trig_date,
                    "initiated_date": None,
                    "completed_date": None,
                    "status": "pending",
                }
            )
            patient_referrals.append(
                ReferralFact(rid_ref, "IFHAS-WF-REFERRAL-15WD", "1.0.0", trig_date, None, None, "pending")
            )
        elif idx == 10:
            # Scenario 10: Results not communicated within 10 days (§4.9.2.1 breach)
            p = _make_patient_base(idx, sex="female", dob=date(1983, 1, 25), thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
            scr_seq += 1
            sid = _next_id("SCR", scr_seq)
            perf = date(2026, 10, 25)
            ifhas_screenings.append(
                {
                    "screening_id": sid,
                    "run_id": run_id,
                    "patient_id": pid,
                    "is_synthetic": True,
                    "profile_id": p["registered_profile_id"],
                    "rule_id": "IFHAS-PKG-MAJOR-40-64",
                    "rule_version": "1.0.0",
                    "appointment_id": None,
                    "performed_date": perf,
                    "completion_status": "complete",
                    "results_communicated_date": None,
                    "journey_reported_date": perf + timedelta(days=8),
                    "has_abnormal_finding": False,
                }
            )
            patient_screenings.append(
                ScreeningEventFact(
                    sid,
                    "IFHAS-PKG-MAJOR-40-64",
                    "1.0.0",
                    "complete",
                    perf,
                    None,
                    perf + timedelta(days=8),
                )
            )
        elif idx == 11:
            # Scenario 11: 60yo smoker hitting IFHAS-PKG-LUNG-LDCT-55-75 (requires_clinical_review)
            p = _make_patient_base(idx, sex="male", dob=date(1966, 5, 5), thiqa=True, smoked=True)
            history_map["ifhas"] = "available"
        elif idx == 12:
            # Scenario 12: 67yo male ever-smoked, AAA ultrasound due (once_per_lifetime)
            p = _make_patient_base(idx, sex="male", dob=date(1959, 4, 18), thiqa=True, smoked=True)
            history_map["ifhas"] = "available"
        elif idx in (13, 14, 15, 16):
            # Scenarios 13–16: Children aged 18 months with M-CHAT-R High (9), Moderate (4), Low (1), and IDAQ referral
            p = _make_patient_base(idx, sex="male" if idx % 2 else "female", dob=date(2025, 5, 16), thiqa=True, smoked=None)
            guardian_id = _add_guardian(p, idx)
            history_map["well_child"] = "available"
            vis_seq += 1
            vid = _next_id("VIS", vis_seq)
            vdate = date(2026, 11, 1)
            well_child_visits.append(
                {
                    "visit_id": vid,
                    "run_id": run_id,
                    "patient_id": pid,
                    "is_synthetic": True,
                    "guardian_id": guardian_id,
                    "profile_id": p["registered_profile_id"],
                    "rule_id": "WCV-VISIT-18M",
                    "rule_version": "1.0.0",
                    "appointment_id": None,
                    "performed_date": vdate,
                    "attendance_status": "attended",
                    "is_catch_up_visit": False,
                }
            )
            patient_visits.append(VisitEventFact(vid, "WCV-VISIT-18M", "1.0.0", "attended", vdate))
            asm_seq += 1
            aid = _next_id("ASM", asm_seq)
            if idx == 13:
                tier_rule, inst, score, resp = "WCV-MCHATR-HIGH", "M-CHAT-R", Decimal("9"), None
            elif idx == 14:
                tier_rule, inst, score, resp = "WCV-MCHATR-MODERATE", "M-CHAT-R", Decimal("4"), None
            elif idx == 15:
                tier_rule, inst, score, resp = "WCV-MCHATR-LOW", "M-CHAT-R", Decimal("1"), None
            else:
                tier_rule, inst, score, resp = (
                    "WCV-IDAQ-REFERRAL",
                    "IDAQ",
                    None,
                    {"q1": "YES", "q2": "YES", "q3": "YES", "q4": "YES", "q5": "YES", "q6": "YES"},
                )
            assessments.append(
                {
                    "assessment_id": aid,
                    "run_id": run_id,
                    "patient_id": pid,
                    "is_synthetic": True,
                    "ifhas_screening_id": None,
                    "well_child_visit_id": vid,
                    "instrument": inst,
                    "instrument_version": "1.0",
                    "administered_date": vdate,
                    "raw_score": score,
                    "item_responses": resp,
                    "rule_id": tier_rule,
                    "rule_version": "1.0.0",
                }
            )
            patient_assessments.append(
                AssessmentFact(
                    aid,
                    vid,
                    inst,
                    tier_rule,
                    "1.0.0",
                    datetime(vdate.year, vdate.month, vdate.day, tzinfo=timezone.utc),
                    int(score) if score is not None else None,
                )
            )
        elif idx == 17:
            # Scenario 17: Child 14 months, 12-month visit not attended (visit_not_attended gap, never overdue)
            p = _make_patient_base(idx, sex="female", dob=date(2025, 9, 16), thiqa=True, smoked=None)
            guardian_id = _add_guardian(p, idx)
            history_map["well_child"] = "available"
            vis_seq += 1
            vid = _next_id("VIS", vis_seq)
            well_child_visits.append(
                {
                    "visit_id": vid,
                    "run_id": run_id,
                    "patient_id": pid,
                    "is_synthetic": True,
                    "guardian_id": guardian_id,
                    "profile_id": p["registered_profile_id"],
                    "rule_id": "WCV-VISIT-12M",
                    "rule_version": "1.0.0",
                    "appointment_id": None,
                    "performed_date": None,
                    "attendance_status": "not_attended",
                    "is_catch_up_visit": False,
                }
            )
            patient_visits.append(VisitEventFact(vid, "WCV-VISIT-12M", "1.0.0", "not_attended", None))
        elif idx == 18:
            # Scenario 18: Child 15 months catch-up visit
            p = _make_patient_base(idx, sex="male", dob=date(2025, 8, 16), thiqa=True, smoked=None)
            guardian_id = _add_guardian(p, idx)
            history_map["well_child"] = "available"
        elif idx == 19:
            # Scenario 19: Child 18 months whose guardian refuses WCV-VISIT-18M, signed and documented
            p = _make_patient_base(idx, sex="female", dob=date(2025, 5, 16), thiqa=True, smoked=None)
            guardian_id = _add_guardian(p, idx)
            history_map["well_child"] = "available"
            c_ref = _add_consent(
                pid,
                consent_type="screening_participation",
                state="refused",
                guardian_id=guardian_id,
                scope_pathway="well_child",
                scope_rule_id="WCV-VISIT-18M",
                scope_rule_version="1.0.0",
                documented=True,
                signed=True,
                refusal_reason="Guardian declined 18-month screening visit after counselling.",
            )
            patient_consents.append(
                ConsentFact(
                    consent_id=c_ref["consent_id"],
                    consent_type="screening_participation",
                    state="refused",
                    applies_to="child_by_guardian",
                    scope_pathway="well_child",
                    scope_rule_id="WCV-VISIT-18M",
                    scope_rule_version="1.0.0",
                    recorded_at=c_ref["recorded_at"],
                    documented_in_record=True,
                    signature_on_file=True,
                )
            )
        elif idx == 20:
            # Scenario 20: Adult opted out of AI prioritisation (refused), accepts contact
            p = _make_patient_base(idx, sex="female", dob=date(1982, 6, 15), thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
            c_contact = _add_consent(pid, consent_type="contact", state="granted", scope_pathway="ifhas")
            _add_consent(
                pid, consent_type="ai_assisted_prioritisation", state="refused", scope_pathway="ifhas",
                refusal_reason="Prefers non-AI scheduling priority."
            )
            contact_consent_id = c_contact["consent_id"]
        elif idx == 21:
            # Scenario 21: Adult withdrew contact consent
            p = _make_patient_base(idx, sex="male", dob=date(1975, 9, 10), thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
            _add_consent(pid, consent_type="contact", state="withdrawn", scope_pathway="ifhas")
        elif idx == 22:
            # Scenario 22: Deceased patient with an open care gap -> outreach suppressed
            p = _make_patient_base(
                idx,
                sex="male",
                dob=date(1962, 1, 10),
                thiqa=True,
                smoked=False,
                date_of_death=date(2026, 10, 15),
            )
            history_map["ifhas"] = "available"
        elif idx == 23:
            # Scenario 23: Wrong contact details, failed invitation delivery
            p = _make_patient_base(
                idx, sex="female", dob=date(1980, 12, 1), thiqa=True, smoked=False, contact_status="wrong"
            )
            history_map["ifhas"] = "available"
            c_contact = _add_consent(pid, consent_type="contact", state="granted", scope_pathway="ifhas")
            contact_consent_id = c_contact["consent_id"]
        elif idx == 24:
            # Scenario 24: Al Dhafra patient (region_id=3), nearest facility lacks IFHAS
            p = _make_patient_base(
                idx,
                sex="female",
                dob=date(1977, 8, 8),
                thiqa=True,
                smoked=False,
                region_id=3,
                profile_id="SYNTH-FSP-000003",
            )
            history_map["ifhas"] = "available"
        elif idx == 25:
            # Scenario 25: Child 15 months, oral exam ambiguity (OQ-WCV-ORAL-15M -> GUARD-ITEM-UNRESOLVED)
            p = _make_patient_base(idx, sex="female", dob=date(2025, 8, 16), thiqa=True, smoked=None)
            guardian_id = _add_guardian(p, idx)
            history_map["well_child"] = "available"
        elif idx == 26:
            # Scenario 26: Two conflicting screening records for one patient -> requires_clinical_review
            p = _make_patient_base(idx, sex="female", dob=date(1979, 2, 20), thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
            perf = date(2026, 6, 10)
            for c_status, comm_d, jrn_d in (
                ("complete", perf + timedelta(days=4), perf + timedelta(days=8)),
                ("partial", None, None),
            ):
                scr_seq += 1
                sid = _next_id("SCR", scr_seq)
                ifhas_screenings.append(
                    {
                        "screening_id": sid,
                        "run_id": run_id,
                        "patient_id": pid,
                        "is_synthetic": True,
                        "profile_id": p["registered_profile_id"],
                        "rule_id": "IFHAS-PKG-MAMMOGRAPHY-40-75",
                        "rule_version": "1.0.0",
                        "appointment_id": None,
                        "performed_date": perf,
                        "completion_status": c_status,
                        "results_communicated_date": comm_d,
                        "journey_reported_date": jrn_d,
                        "has_abnormal_finding": False,
                    }
                )
                patient_screenings.append(
                    ScreeningEventFact(
                        sid,
                        "IFHAS-PKG-MAMMOGRAPHY-40-75",
                        "1.0.0",
                        c_status,
                        perf,
                        comm_d,
                        jrn_d,
                    )
                )
        elif idx == 27:
            # Scenario 27: Care gap scored by model, clinician overrides priority in care_gap_review
            p = _make_patient_base(idx, sex="female", dob=date(1973, 4, 4), thiqa=True, smoked=False)
            history_map["ifhas"] = "available"
            c_contact = _add_consent(pid, consent_type="contact", state="granted", scope_pathway="ifhas")
            c_ai = _add_consent(
                pid, consent_type="ai_assisted_prioritisation", state="granted", scope_pathway="ifhas"
            )
            contact_consent_id = c_contact["consent_id"]
            ai_consent_id = c_ai["consent_id"]
        else:
            # Seeded general population: ~72% adults, ~28% children
            is_child = (idx % 4 == 0)
            sex = "female" if rng.random() < 0.48 else "male"
            region_id = rng.choices((1, 2, 3), weights=(0.65, 0.25, 0.10))[0]
            if is_child:
                age_m = rng.choice((1, 2, 4, 6, 9, 12, 15, 18, 24, 30, 36, 48, 60, 72))
                dob = date(
                    reference_date.year - (age_m // 12),
                    max(1, min(12, reference_date.month - (age_m % 12) or 1)),
                    10,
                )
                p = _make_patient_base(idx, sex=sex, dob=dob, thiqa=True, smoked=None, region_id=region_id)
                guardian_id = _add_guardian(p, idx)
                h_state = rng.choices(
                    ("available", "not_available", "partial"), weights=(0.78, 0.15, 0.07)
                )[0]
                history_map["well_child"] = h_state
            else:
                age_y = rng.randint(19, 74)
                dob = date(reference_date.year - age_y, rng.randint(1, 12), rng.randint(1, 28))
                thiqa = rng.choices((True, False), weights=(0.85, 0.15))[0]
                smoked = rng.choices((False, True), weights=(0.75, 0.25))[0]
                p = _make_patient_base(idx, sex=sex, dob=dob, thiqa=thiqa, smoked=smoked, region_id=region_id)
                h_state = rng.choices(
                    ("available", "not_available", "partial"), weights=(0.78, 0.15, 0.07)
                )[0]
                history_map["ifhas"] = h_state
                if h_state == "available" and thiqa and rng.random() < 0.35:
                    scr_seq += 1
                    sid = _next_id("SCR", scr_seq)
                    perf = reference_date - timedelta(days=rng.randint(60, 600))
                    pkg_rule = (
                        "IFHAS-PKG-MAJOR-18-39"
                        if age_y < 40
                        else ("IFHAS-PKG-MAJOR-40-64" if age_y < 65 else "IFHAS-PKG-MAJOR-65-75")
                    )
                    ifhas_screenings.append(
                        {
                            "screening_id": sid,
                            "run_id": run_id,
                            "patient_id": pid,
                            "is_synthetic": True,
                            "profile_id": p["registered_profile_id"],
                            "rule_id": pkg_rule,
                            "rule_version": "1.0.0",
                            "appointment_id": None,
                            "performed_date": perf,
                            "completion_status": "complete",
                            "results_communicated_date": perf + timedelta(days=4),
                            "journey_reported_date": perf + timedelta(days=8),
                            "has_abnormal_finding": False,
                        }
                    )
                    patient_screenings.append(
                        ScreeningEventFact(
                            sid,
                            pkg_rule,
                            "1.0.0",
                            "complete",
                            perf,
                            perf + timedelta(days=4),
                            perf + timedelta(days=8),
                        )
                    )

        patients.append(p)
        if guardian_id is not None:
            n_children += 1
        else:
            n_adults += 1

        for pw, st in history_map.items():
            _add_history(pid, pw, st)

        ctx = PatientContext(
            patient_id=pid,
            date_of_birth=p["date_of_birth"],
            sex=p["sex"],
            thiqa_member=p["thiqa_member"],
            ever_smoked=p["ever_smoked"],
            history_by_pathway=history_map,
            ifhas_screenings=tuple(patient_screenings),
            well_child_visits=tuple(patient_visits),
            component_results=tuple(patient_crs),
            developmental_assessments=tuple(patient_assessments),
            referrals=tuple(patient_referrals),
            consents=tuple(patient_consents),
        )
        ctx_by_patient[pid] = ctx
        summary = engine.evaluate_patient(
            ctx, reference_date=reference_date, look_ahead_days=30, evaluated_at=eval_ts
        )

        eval_id_by_rule: dict[str, str] = {}
        for ev in summary.evaluations:
            evl_seq += 1
            eid = _next_id("EVL", evl_seq)
            eval_id_by_rule[ev.rule_id] = eid
            eligibility_evaluations.append(
                {
                    "evaluation_id": eid,
                    "run_id": run_id,
                    "patient_id": pid,
                    "is_synthetic": True,
                    "evaluation_run_id": eval_run_id,
                    "rule_id": ev.rule_id,
                    "rule_version": ev.rule_version,
                    "evaluated_at": ev.evaluated_at,
                    "evaluation_status": ev.evaluation_status,
                    "reason_code": ev.reason_code,
                    "next_due_date": ev.next_due_date,
                    "reason_detail": evaluation_reason_detail(ev),
                    "input_snapshot": evaluation_snapshot(ctx, ev, reference_date),
                }
            )
            for ord_idx, reason in enumerate(ev.reasons, 1):
                ers_seq += 1
                evaluation_reasons.append(
                    {
                        "reason_id": _next_id("ERS", ers_seq),
                        "run_id": run_id,
                        "patient_id": pid,
                        "is_synthetic": True,
                        "evaluation_id": eid,
                        "rule_id": ev.rule_id,
                        "rule_version": ev.rule_version,
                        "reason_ordinal": ord_idx,
                        "guard_id": reason.guard_id,
                        "reason_code": reason.reason_code,
                        "item_category": reason.item_category,
                        "item_code": reason.item_code,
                        "reason_detail": fired_reason_detail(reason),
                    }
                )

        for gf in summary.care_gaps:
            gap_seq += 1
            gid = _next_id("GAP", gap_seq)
            eid = eval_id_by_rule[gf.rule_id]

            p_score: Decimal | None = None
            p_expl: str | None = None
            p_model: str | None = None
            p_scored_at: datetime | None = None
            p_consent_id: str | None = None
            p_supp_reason: str | None = None

            if idx == 20 and gf.status == "open":
                p_supp_reason = "ai_consent_refused"
            elif gf.status == "open":
                p_supp_reason = "model_not_implemented"

            gap_row = {
                "care_gap_id": gid,
                "run_id": run_id,
                "patient_id": pid,
                "is_synthetic": True,
                "evaluation_id": eid,
                "rule_id": gf.rule_id,
                "rule_version": gf.rule_version,
                "gap_type": gf.gap_type,
                "subject_ifhas_screening_id": gf.subject_ifhas_screening_id,
                "subject_well_child_visit_id": gf.subject_well_child_visit_id,
                "subject_referral_id": gf.subject_referral_id,
                "identified_date": gf.opened_date,
                "status": gf.status,
                "closed_date": gf.closed_date,
                "suppression_reason": None,
                "closed_by_ifhas_screening_id": gf.closed_by_ifhas_screening_id,
                "closed_by_well_child_visit_id": gf.closed_by_well_child_visit_id,
                "closed_by_referral_id": None,
                "closed_by_component_result_id": gf.closed_by_component_result_id,
                "closed_by_consent_id": gf.closed_by_consent_id,
                "priority_score": p_score,
                "priority_explanation": p_expl,
                "scored_by_model_version": p_model,
                "scored_at": p_scored_at,
                "scoring_consent_id": p_consent_id,
                "scoring_suppressed_reason": p_supp_reason,
            }
            care_gaps.append(gap_row)

            if idx == 27 and gf.rule_id == "IFHAS-PKG-MAMMOGRAPHY-40-75":
                rev_seq += 1
                care_gap_reviews.append(
                    {
                        "review_id": _next_id("REV", rev_seq),
                        "run_id": run_id,
                        "care_gap_id": gid,
                        "is_synthetic": True,
                        "reviewer": "dr.almansoori.synthetic",
                        "action": "priority_overridden",
                        "previous_priority": p_score,
                        "new_priority": Decimal("0.95"),
                        "reason": "Coordinator requested earlier slot to combine with annual vision check.",
                        "reviewed_at": eval_ts + timedelta(minutes=30),
                    }
                )

            if idx == 1 and gf.rule_id == "IFHAS-PKG-MAMMOGRAPHY-40-75":
                apt_seq += 1
                aid = _next_id("APT", apt_seq)
                appointments.append(
                    {
                        "appointment_id": aid,
                        "run_id": run_id,
                        "patient_id": pid,
                        "is_synthetic": True,
                        "profile_id": p["registered_profile_id"],
                        "care_gap_id": gid,
                        "appointment_type": "ifhas_screening",
                        "scheduled_datetime": eval_ts + timedelta(days=7),
                        "slot_type": "weekday",
                        "status": "scheduled",
                        "booked_via": "outreach_link",
                    }
                )
                out_seq += 1
                outreach_events.append(
                    {
                        "outreach_id": _next_id("OUT", out_seq),
                        "run_id": run_id,
                        "patient_id": pid,
                        "is_synthetic": True,
                        "care_gap_id": gid,
                        "guardian_id": None,
                        "recipient": "patient",
                        "event_type": "invitation",
                        "channel": "sms",
                        "sent_datetime": eval_ts + timedelta(hours=1),
                        "delivery_status": "delivered",
                        "suppression_reason": None,
                        "contact_consent_id": contact_consent_id,
                        "response": "booked",
                        "appointment_id": aid,
                        "triggered_by_ai_score": True,
                        "clinician_approved_by": "coord.salama.synthetic",
                        "message_template_id": "TPL-IFHAS-INVITE-EN",
                    }
                )
            elif idx == 21 and gf.rule_id == "IFHAS-PKG-MAJOR-40-64":
                out_seq += 1
                outreach_events.append(
                    {
                        "outreach_id": _next_id("OUT", out_seq),
                        "run_id": run_id,
                        "patient_id": pid,
                        "is_synthetic": True,
                        "care_gap_id": gid,
                        "guardian_id": None,
                        "recipient": "patient",
                        "event_type": "invitation",
                        "channel": "sms",
                        "sent_datetime": None,
                        "delivery_status": "suppressed",
                        "suppression_reason": "contact_consent_withdrawn",
                        "contact_consent_id": None,
                        "response": None,
                        "appointment_id": None,
                        "triggered_by_ai_score": False,
                        "clinician_approved_by": None,
                        "message_template_id": "TPL-IFHAS-INVITE-AR",
                    }
                )
            elif idx == 22 and gf.rule_id == "IFHAS-PKG-MAJOR-40-64":
                out_seq += 1
                outreach_events.append(
                    {
                        "outreach_id": _next_id("OUT", out_seq),
                        "run_id": run_id,
                        "patient_id": pid,
                        "is_synthetic": True,
                        "care_gap_id": gid,
                        "guardian_id": None,
                        "recipient": "patient",
                        "event_type": "invitation",
                        "channel": "sms",
                        "sent_datetime": None,
                        "delivery_status": "suppressed",
                        "suppression_reason": "patient_deceased",
                        "contact_consent_id": None,
                        "response": None,
                        "appointment_id": None,
                        "triggered_by_ai_score": False,
                        "clinician_approved_by": None,
                        "message_template_id": None,
                    }
                )
            elif idx == 23 and gf.rule_id == "IFHAS-PKG-MAMMOGRAPHY-40-75":
                out_seq += 1
                outreach_events.append(
                    {
                        "outreach_id": _next_id("OUT", out_seq),
                        "run_id": run_id,
                        "patient_id": pid,
                        "is_synthetic": True,
                        "care_gap_id": gid,
                        "guardian_id": None,
                        "recipient": "patient",
                        "event_type": "invitation",
                        "channel": "sms",
                        "sent_datetime": eval_ts + timedelta(hours=2),
                        "delivery_status": "failed",
                        "suppression_reason": None,
                        "contact_consent_id": contact_consent_id,
                        "response": None,
                        "appointment_id": None,
                        "triggered_by_ai_score": False,
                        "clinician_approved_by": None,
                        "message_template_id": "TPL-IFHAS-INVITE-EN",
                    }
                )

    # T-10: Enrich background patients (idx >= 28) with deterministic operational journeys
    # without altering any Scenario 1-27 IDs or statuses.
    latest_contact_consent: dict[str, dict[str, Any]] = {}
    for c in consents:
        if c["consent_type"] == "contact":
            prev = latest_contact_consent.get(c["patient_id"])
            if prev is None or (c["recorded_at"], c["consent_id"]) > (
                prev["recorded_at"],
                prev["consent_id"],
            ):
                latest_contact_consent[c["patient_id"]] = c
    consent_by_patient_contact: dict[str, str] = {
        pid: c["consent_id"]
        for pid, c in latest_contact_consent.items()
        if c["state"] == "granted"
    }

    # Ensure >= 40 background patients with open care gaps have granted contact consent
    # (so >= 30 contactable people with open gaps exist even after 5 are closed below).
    patients_by_id_map = {p["patient_id"]: p for p in patients}
    for g in care_gaps:
        pid = g["patient_id"]
        if int(pid.split("-")[-1]) < 28 or g["status"] != "open":
            continue
        if pid in latest_contact_consent:
            continue
        if patients_by_id_map[pid]["contact_status"] != "valid":
            continue
        cns_seq += 1
        cid = _next_id("CNS", cns_seq)
        consents.append(
            {
                "consent_id": cid,
                "run_id": run_id,
                "patient_id": pid,
                "is_synthetic": True,
                "guardian_id": None,
                "consent_type": "contact",
                "state": "granted",
                "applies_to": "self",
                "scope_pathway": "ifhas",
                "scope_rule_id": None,
                "scope_rule_version": None,
                "recorded_at": started_ts - timedelta(days=5),
                "recorded_by": "synthetic_intake_portal",
                "documented_in_record": True,
                "signature_on_file": True,
                "refusal_reason": None,
            }
        )
        consent_by_patient_contact[pid] = cid
        if len(consent_by_patient_contact) >= 45:
            break

    items_by_rule: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for it in clinical_bundle.items:
        items_by_rule.setdefault((it["rule_id"], it["rule_version"]), []).append(
            (it["category"], it["code"])
        )

    open_gaps_bg = [
        g
        for g in care_gaps
        if int(g["patient_id"].split("-")[-1]) >= 28
        and g["status"] == "open"
        and g["rule_id"].startswith("IFHAS-")
        and (g["rule_id"], g["rule_version"]) in items_by_rule
        and g["patient_id"] in consent_by_patient_contact
    ]
    seen_in_progress: set[str] = set()
    for g in open_gaps_bg:
        pid = g["patient_id"]
        if pid in seen_in_progress:
            continue
        seen_in_progress.add(pid)
        apt_seq += 1
        apt_id = _next_id("APT", apt_seq)
        appointments.append(
            {
                "appointment_id": apt_id,
                "run_id": run_id,
                "patient_id": pid,
                "is_synthetic": True,
                "profile_id": "SYNTH-FSP-000001",
                "care_gap_id": g["care_gap_id"],
                "appointment_type": "ifhas_screening",
                "scheduled_datetime": eval_ts + timedelta(days=5),
                "slot_type": "weekday",
                "status": "scheduled",
                "booked_via": "coordinator_portal",
            }
        )
        out_seq += 1
        outreach_events.append(
            {
                "outreach_id": _next_id("OUT", out_seq),
                "run_id": run_id,
                "patient_id": pid,
                "is_synthetic": True,
                "care_gap_id": g["care_gap_id"],
                "guardian_id": None,
                "recipient": "patient",
                "event_type": "invitation",
                "channel": "sms",
                "sent_datetime": eval_ts + timedelta(hours=3),
                "delivery_status": "delivered",
                "suppression_reason": None,
                "contact_consent_id": consent_by_patient_contact[pid],
                "response": "booked",
                "appointment_id": apt_id,
                "triggered_by_ai_score": False,
                "clinician_approved_by": None,
                "message_template_id": "TPL-IFHAS-INVITE-EN",
            }
        )
        if len(seen_in_progress) >= 5:
            break

    # 5 background patients with documented completion + component_result + closed_completed gap
    rules_by_key = {(r["rule_id"], r["rule_version"]): r for r in clinical_bundle.rules}
    seen_completed: set[str] = set()
    for g in open_gaps_bg:
        pid = g["patient_id"]
        if pid in seen_in_progress or pid in seen_completed:
            continue
        seen_completed.add(pid)
        scr_seq += 1
        scr_id = _next_id("SCR", scr_seq)
        ifhas_screenings.append(
            {
                "screening_id": scr_id,
                "run_id": run_id,
                "patient_id": pid,
                "is_synthetic": True,
                "profile_id": "SYNTH-FSP-000001",
                "rule_id": g["rule_id"],
                "rule_version": g["rule_version"],
                "appointment_id": None,
                "performed_date": reference_date - timedelta(days=2),
                "completion_status": "complete",
                "results_communicated_date": reference_date - timedelta(days=1),
                "journey_reported_date": reference_date - timedelta(days=1),
                "has_abnormal_finding": False,
            }
        )
        cmp_seq += 1
        cr_id = _next_id("CMP", cmp_seq)
        item_cat, item_code = items_by_rule[(g["rule_id"], g["rule_version"])][0]
        component_results.append(
            {
                "component_result_id": cr_id,
                "run_id": run_id,
                "patient_id": pid,
                "is_synthetic": True,
                "ifhas_screening_id": scr_id,
                "well_child_visit_id": None,
                "rule_id": g["rule_id"],
                "rule_version": g["rule_version"],
                "item_category": item_cat,
                "item_code": item_code,
                "result_status": "completed",
                "performed_date": reference_date - timedelta(days=2),
                "documented_in_record": None,
                "signature_on_file": None,
                "refused_by_guardian_id": None,
                "refusal_reason": None,
            }
        )
        new_scr = ifhas_screenings[-1]
        completed_ctx = dataclasses.replace(
            ctx_by_patient[pid],
            ifhas_screenings=ctx_by_patient[pid].ifhas_screenings
            + (
                ScreeningEventFact(
                    scr_id,
                    g["rule_id"],
                    g["rule_version"],
                    "complete",
                    new_scr["performed_date"],
                    new_scr["results_communicated_date"],
                    new_scr["journey_reported_date"],
                ),
            ),
            component_results=ctx_by_patient[pid].component_results
            + (
                ComponentResultFact(
                    cr_id,
                    g["rule_id"],
                    g["rule_version"],
                    item_cat,
                    item_code,
                    "completed",
                    datetime.combine(new_scr["performed_date"], datetime.min.time(), timezone.utc),
                ),
            ),
        )
        completion = validate_completion_evidence(
            gap=g,
            rule=rules_by_key.get((g["rule_id"], g["rule_version"])),
            evidence=CompletionEvidence.from_screening(new_scr),
            documented_evidence=True,
            evidence_reference=scr_id,
            as_of=reference_date,
            current_evaluation=evaluate_current_rule(
                engine,
                completed_ctx,
                rule_id=g["rule_id"],
                rule_version=g["rule_version"],
                as_of=reference_date,
                look_ahead_days=30,
            ),
        )
        if not completion.accepted:
            raise ValueError(f"Synthetic completion scenario is invalid: {completion.message}")
        g["status"] = "closed_completed"
        g["closed_date"] = reference_date
        g["closed_by_ifhas_screening_id"] = scr_id
        if len(seen_completed) >= 5:
            break

    # 2 declined/cancelled referral scenarios on background patients with screenings
    bg_screenings = [
        s
        for s in ifhas_screenings
        if int(s["patient_id"].split("-")[-1]) >= 28 and s["completion_status"] != "not_attended"
    ]
    for status_val, scr_item in zip(("declined", "cancelled"), bg_screenings[:2]):
        ref_seq += 1
        referrals.append(
            {
                "referral_id": _next_id("REF", ref_seq),
                "run_id": run_id,
                "patient_id": scr_item["patient_id"],
                "is_synthetic": True,
                "ifhas_screening_id": scr_item["screening_id"],
                "well_child_visit_id": None,
                "assessment_id": None,
                "trigger_rule_id": scr_item["rule_id"],
                "trigger_rule_version": scr_item["rule_version"],
                "rule_action_ordinal": None,
                "referral_target": "specialist_follow_up",
                "target_profile_id": "SYNTH-FSP-000001",
                "trigger_date": reference_date - timedelta(days=10),
                "initiated_date": reference_date - timedelta(days=8),
                "completed_date": None,
                "status": status_val,
            }
        )

    condition_records = generate_condition_records(
        patients, reference_date=reference_date, run_id=run_id, seed=seed
    )

    generation_run = {
        "run_id": run_id,
        "is_synthetic": True,
        "generator_version": GENERATOR_VERSION,
        "generator_commit": git_commit_if_clean(repo_root()),
        "spec_version": SPEC_VERSION,
        "generation_seed": seed,
        "started_at": started_ts,
        "finished_at": started_ts + timedelta(seconds=2),
        "rule_bundle_load_id": rule_bundle_load_id,
        "parameters": {
            "total_patients": total_patients,
            "reference_date": reference_date.isoformat(),
            "look_ahead_days": 30,
        },
        "calibration_inputs": [
            {
                "note": "Labelled demo cohort covering all 27 edge cases in synthetic_data_spec.md; does not claim Abu Dhabi prevalence or programme coverage."
            }
        ],
        "population_profile": "labelled_alternative",
        "n_adults": n_adults,
        "n_children": n_children,
        "clinically_validated": False,
        "data_card_path": f"data/synthetic/{run_id}/data_card.md",
    }

    evaluation_run = {
        "evaluation_run_id": eval_run_id,
        "run_id": run_id,
        "is_synthetic": True,
        "rule_bundle_load_id": rule_bundle_load_id,
        "reference_date": reference_date,
        "age_convention": "unspecified",
        "look_ahead_days": 30,
        "applicability_policy": "evaluate_all_54_rules_with_guards",
        "engine_version": ENGINE_VERSION,
        "started_at": eval_ts,
    }

    return SyntheticDataset(
        generation_run=generation_run,
        evaluation_run=evaluation_run,
        facility_service_profiles=facility_service_profiles,
        patients=patients,
        guardians=guardians,
        consents=consents,
        history_availabilities=history_availabilities,
        eligibility_evaluations=eligibility_evaluations,
        evaluation_reasons=evaluation_reasons,
        appointments=appointments,
        ifhas_screenings=ifhas_screenings,
        well_child_visits=well_child_visits,
        component_results=component_results,
        assessments=assessments,
        referrals=referrals,
        care_gaps=care_gaps,
        care_gap_reviews=care_gap_reviews,
        outreach_events=outreach_events,
        condition_records=condition_records,
    )


def write_data_card(dataset: SyntheticDataset, output_path: Path) -> Path:
    """Write the Responsible AI Standard §3.2.5 synthetic data card Markdown file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gr = dataset.generation_run
    er = dataset.evaluation_run
    content = f"""# PulseReach Synthetic Dataset Data Card — `{gr['run_id']}`

> **SYNTHETIC DATA NOTICE:** Every record in this dataset is 100% fabricated (`is_synthetic = true`).
> No real personal identifiers, Emirates IDs, phone numbers, emails, or patient histories are used.
> This dataset is **not clinically validated** (`clinically_validated = false`) and does not claim
> Abu Dhabi disease prevalence or real screening programme coverage.

## 1. Provenance & Reproducibility
- **Generation Run ID:** `{gr['run_id']}`
- **Evaluation Run ID:** `{er['evaluation_run_id']}`
- **Generator Version:** `{gr['generator_version']}`
- **Specification Version:** `{gr['spec_version']}`
- **Random Seed:** `{gr['generation_seed']}`
- **Reference Date:** `{er['reference_date']}`
- **Population Profile:** `{gr['population_profile']}`

## 2. Row Counts Across the 18 `synthetic.*` Tables
| Table | Rows |
|---|---|
| `synthetic.generation_run` | 1 |
| `synthetic.evaluation_run` | 1 |
| `synthetic.facility_service_profile` | {len(dataset.facility_service_profiles)} |
| `synthetic.patient` | {len(dataset.patients)} ({gr['n_adults']} adults, {gr['n_children']} children) |
| `synthetic.guardian` | {len(dataset.guardians)} |
| `synthetic.consent` | {len(dataset.consents)} |
| `synthetic.history_availability` | {len(dataset.history_availabilities)} |
| `synthetic.eligibility_evaluation` | {len(dataset.eligibility_evaluations)} |
| `synthetic.evaluation_reason` | {len(dataset.evaluation_reasons)} |
| `synthetic.appointment` | {len(dataset.appointments)} |
| `synthetic.ifhas_screening` | {len(dataset.ifhas_screenings)} |
| `synthetic.well_child_visit` | {len(dataset.well_child_visits)} |
| `synthetic.component_result` | {len(dataset.component_results)} |
| `synthetic.assessment` | {len(dataset.assessments)} |
| `synthetic.referral` | {len(dataset.referrals)} |
| `synthetic.care_gap` | {len(dataset.care_gaps)} |
| `synthetic.care_gap_review` | {len(dataset.care_gap_reviews)} |
| `synthetic.outreach_event` | {len(dataset.outreach_events)} |
| `synthetic.condition_record` | {len(dataset.condition_records)} (BE-33 problem-list entries; illustrative rates, labelled scenarios) |

## 3. Safety & Governance Guarantees
- Every primary key begins with `SYNTH-<CODE>-`.
- Every `emirates_id_synthetic` begins with `SYNTH-EID-` and never matches `784-...`.
- Every `family_name` ends with ` (synthetic)`.
- Missing screening history (`not_available`) evaluates to `unknown`, never `due` or `overdue`.
- Unresolved or review-flagged clinical rules evaluate to `requires_clinical_review`.
- Well-Child rules never produce `overdue` while `OQ-WCV-DUE-WINDOW` is unresolved.
"""
    output_path.write_text(content, encoding="utf-8")
    return output_path


def write_demo_fixture(
    dataset: SyntheticDataset,
    output_path: Path,
    *,
    patient_limit: int = 50,
) -> Path:
    """Write the committed 50-patient synthetic demo fixture (`data/synthetic/fixtures/demo_patients_50.json`)."""
    import json

    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected_patients = dataset.patients[:patient_limit]
    selected_pids = {p["patient_id"] for p in selected_patients}

    def _default_json(obj: Any) -> Any:
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        raise TypeError(f"Unsupported type: {type(obj)!r}")

    payload = {
        "is_synthetic": True,
        "run_id": dataset.generation_run["run_id"],
        "evaluation_run_id": dataset.evaluation_run["evaluation_run_id"],
        "generation_seed": dataset.generation_run["generation_seed"],
        "reference_date": dataset.evaluation_run["reference_date"].isoformat(),
        "patients": selected_patients,
        "guardians": [g for g in dataset.guardians if g["patient_id"] in selected_pids],
        "consents": [c for c in dataset.consents if c["patient_id"] in selected_pids],
        "history_availabilities": [
            h for h in dataset.history_availabilities if h["patient_id"] in selected_pids
        ],
        "ifhas_screenings": [
            s for s in dataset.ifhas_screenings if s["patient_id"] in selected_pids
        ],
        "well_child_visits": [
            v for v in dataset.well_child_visits if v["patient_id"] in selected_pids
        ],
        "care_gaps": [g for g in dataset.care_gaps if g["patient_id"] in selected_pids],
    }
    output_path.write_text(
        json.dumps(payload, indent=2, default=_default_json, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path

