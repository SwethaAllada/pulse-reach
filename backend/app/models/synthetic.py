"""SQLAlchemy 2.x models for the `synthetic` schema (18 tables + later additions).

Matches `docs/phase-3-database-design.md` §5; later migrations add `care_gap_follow_up_event`
(0008), `workflow_status_event` (0009), `ai_audit_record` (0010) and `condition_record` (0012).
All 18 tables carry `run_id` and `is_synthetic BOOLEAN NOT NULL DEFAULT true CHECK (is_synthetic)`,
PK prefix regex checks (`^SYNTH-<CODE>-[0-9]{N,}$`), and composite `ON DELETE RESTRICT` /
`ON UPDATE RESTRICT` foreign keys.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    Double,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SCHEMA = "synthetic"


def _fk(
    cols: list[str],
    ref_cols: list[str],
    name: str,
    ref_schema: str = SCHEMA,
) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        cols,
        [f"{ref_schema}.{rc}" for rc in ref_cols],
        name=name,
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )


def _synth_checks(pk_col: str, code: str, digits: int = 6) -> tuple[CheckConstraint, CheckConstraint]:
    return (
        CheckConstraint("is_synthetic", name="is_synthetic"),
        CheckConstraint(
            f"{pk_col} ~ '^SYNTH-{code}-[0-9]{{{digits},}}$'",
            name="pk_prefix",
        ),
    )


# ---------------------------------------------------------------------------
# §5.1 Provenance and runs
# ---------------------------------------------------------------------------
class GenerationRun(Base):
    __tablename__ = "generation_run"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    generator_version: Mapped[str] = mapped_column(Text, nullable=False)
    generator_commit: Mapped[str | None] = mapped_column(Text)
    spec_version: Mapped[str] = mapped_column(Text, nullable=False)
    generation_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    rule_bundle_load_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    calibration_inputs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False
    )
    population_profile: Mapped[str] = mapped_column(Text, nullable=False)
    n_adults: Mapped[int] = mapped_column(Integer, nullable=False)
    n_children: Mapped[int] = mapped_column(Integer, nullable=False)
    clinically_validated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    data_card_path: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        _fk(
            ["rule_bundle_load_id"],
            ["rule_load.load_id"],
            "fk_generation_run_rule_bundle_load_id_rule_load",
            ref_schema="clinical",
        ),
        *_synth_checks("run_id", "RUN", digits=4),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        CheckConstraint(
            "population_profile IN ('mirror_scad', 'labelled_alternative')",
            name="population_profile",
        ),
        CheckConstraint("n_adults >= 0 AND n_children >= 0", name="counts_nonnegative"),
        CheckConstraint("NOT clinically_validated", name="not_clinically_validated"),
        {"schema": SCHEMA},
    )


class EvaluationRun(Base):
    __tablename__ = "evaluation_run"

    evaluation_run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    rule_bundle_load_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    age_convention: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unspecified'")
    )
    look_ahead_days: Mapped[int | None] = mapped_column(Integer)
    applicability_policy: Mapped[str] = mapped_column(Text, nullable=False)
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )

    __table_args__ = (
        _fk(["run_id"], ["generation_run.run_id"], "fk_evaluation_run_run_id_generation_run"),
        _fk(
            ["rule_bundle_load_id"],
            ["rule_load.load_id"],
            "fk_evaluation_run_rule_bundle_load_id_rule_load",
            ref_schema="clinical",
        ),
        UniqueConstraint(
            "run_id", "evaluation_run_id", name="uq_evaluation_run_run_id_evaluation_run_id"
        ),
        *_synth_checks("evaluation_run_id", "EVR"),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# §5.2 People, consent, facilities
# ---------------------------------------------------------------------------
class FacilityServiceProfile(Base):
    __tablename__ = "facility_service_profile"

    profile_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    facility_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    offers_ifhas: Mapped[bool] = mapped_column(Boolean, nullable=False)
    offers_wcv: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evening_hours: Mapped[bool] = mapped_column(Boolean, nullable=False)
    weekend_hours: Mapped[bool] = mapped_column(Boolean, nullable=False)
    capability_basis: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'simulated'")
    )

    __table_args__ = (
        _fk(
            ["run_id"],
            ["generation_run.run_id"],
            "fk_facility_service_profile_run_id_generation_run",
        ),
        _fk(
            ["facility_id"],
            ["facility.facility_id"],
            "fk_facility_service_profile_facility_id_facility",
            ref_schema="official",
        ),
        UniqueConstraint(
            "run_id", "profile_id", name="uq_facility_service_profile_run_id_profile_id"
        ),
        UniqueConstraint(
            "run_id", "facility_id", name="uq_facility_service_profile_run_id_facility_id"
        ),
        *_synth_checks("profile_id", "FSP"),
        CheckConstraint("capability_basis = 'simulated'", name="capability_basis"),
        {"schema": SCHEMA},
    )


class Patient(Base):
    __tablename__ = "patient"

    patient_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    emirates_id_synthetic: Mapped[str] = mapped_column(Text, nullable=False)
    given_name: Mapped[str] = mapped_column(Text, nullable=False)
    family_name: Mapped[str] = mapped_column(Text, nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(Text)
    nationality_group: Mapped[str | None] = mapped_column(Text)
    region_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    district_label: Mapped[str | None] = mapped_column(Text)
    thiqa_member: Mapped[bool | None] = mapped_column(Boolean)
    ever_smoked: Mapped[bool | None] = mapped_column(Boolean)
    preferred_language: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_channel: Mapped[str] = mapped_column(Text, nullable=False)
    phone_synthetic: Mapped[str | None] = mapped_column(Text)
    email_synthetic: Mapped[str | None] = mapped_column(Text)
    contact_status: Mapped[str] = mapped_column(Text, nullable=False)
    registered_profile_id: Mapped[str | None] = mapped_column(Text)
    date_of_death: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        _fk(["run_id"], ["generation_run.run_id"], "fk_patient_run_id_generation_run"),
        _fk(
            ["region_id"],
            ["region.region_id"],
            "fk_patient_region_id_region",
            ref_schema="official",
        ),
        _fk(
            ["run_id", "registered_profile_id"],
            ["facility_service_profile.run_id", "facility_service_profile.profile_id"],
            "fk_patient_registered_profile_id_facility_service_profile",
        ),
        UniqueConstraint("run_id", "patient_id", name="uq_patient_run_id_patient_id"),
        UniqueConstraint("emirates_id_synthetic", name="uq_patient_emirates_id_synthetic"),
        *_synth_checks("patient_id", "PAT"),
        CheckConstraint(
            "emirates_id_synthetic ~ '^SYNTH-EID-' AND emirates_id_synthetic !~ '^784-?[0-9]{4}-?[0-9]{7}-?[0-9]$'",
            name="emirates_id_synthetic_format",
        ),
        CheckConstraint("family_name ~ '\\(synthetic\\)$'", name="family_name_synthetic"),
        CheckConstraint("sex IN ('male', 'female')", name="sex"),
        CheckConstraint(
            "nationality_group IN ('emirati', 'non_emirati', 'not_stated')",
            name="nationality_group",
        ),
        CheckConstraint("preferred_language IN ('ar', 'en')", name="preferred_language"),
        CheckConstraint(
            "preferred_channel IN ('sms', 'phone', 'email', 'app')",
            name="preferred_channel",
        ),
        CheckConstraint(
            "email_synthetic IS NULL OR email_synthetic ~ '@example\\.invalid$'",
            name="email_synthetic",
        ),
        CheckConstraint(
            "contact_status IN ('valid', 'wrong', 'unverified')", name="contact_status"
        ),
        CheckConstraint(
            "date_of_death IS NULL OR date_of_birth IS NULL OR date_of_death >= date_of_birth",
            name="death_after_birth",
        ),
        Index("ix_patient_run_id", "run_id"),
        Index("ix_patient_region_id", "region_id"),
        Index("ix_patient_registered_profile_id", "registered_profile_id"),
        Index("ix_patient_date_of_birth", "date_of_birth"),
        Index("ix_patient_run_region_district", "run_id", "region_id", "district_label"),  # 0012
        {"schema": SCHEMA},
    )


class Guardian(Base):
    __tablename__ = "guardian"

    guardian_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    relationship: Mapped[str] = mapped_column(Text, nullable=False)
    given_name: Mapped[str] = mapped_column(Text, nullable=False)
    family_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_synthetic: Mapped[str | None] = mapped_column(Text)
    email_synthetic: Mapped[str | None] = mapped_column(Text)
    preferred_language: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_channel: Mapped[str] = mapped_column(Text, nullable=False)
    contact_status: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        _fk(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.patient_id"],
            "fk_guardian_patient_id_patient",
        ),
        UniqueConstraint("run_id", "guardian_id", name="uq_guardian_run_id_guardian_id"),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "guardian_id",
            name="uq_guardian_run_id_patient_id_guardian_id",
        ),
        *_synth_checks("guardian_id", "GDN"),
        CheckConstraint(
            "relationship IN ('mother', 'father', 'legal_guardian')",
            name="relationship",
        ),
        CheckConstraint("family_name ~ '\\(synthetic\\)$'", name="family_name_synthetic"),
        CheckConstraint(
            "email_synthetic IS NULL OR email_synthetic ~ '@example\\.invalid$'",
            name="email_synthetic",
        ),
        CheckConstraint("preferred_language IN ('ar', 'en')", name="preferred_language"),
        CheckConstraint(
            "preferred_channel IN ('sms', 'phone', 'email', 'app')",
            name="preferred_channel",
        ),
        CheckConstraint(
            "contact_status IN ('valid', 'wrong', 'unverified')", name="contact_status"
        ),
        {"schema": SCHEMA},
    )


class Consent(Base):
    __tablename__ = "consent"

    consent_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    guardian_id: Mapped[str | None] = mapped_column(Text)
    consent_type: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    applies_to: Mapped[str] = mapped_column(Text, nullable=False)
    scope_pathway: Mapped[str | None] = mapped_column(Text)
    scope_rule_id: Mapped[str | None] = mapped_column(Text)
    scope_rule_version: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    recorded_by: Mapped[str] = mapped_column(Text, nullable=False)
    documented_in_record: Mapped[bool | None] = mapped_column(Boolean)
    signature_on_file: Mapped[bool | None] = mapped_column(Boolean)
    refusal_reason: Mapped[str | None] = mapped_column(Text)
    refusal_evidence_valid: Mapped[bool] = mapped_column(
        Boolean,
        Computed(
            "consent_type = 'screening_participation' AND state = 'refused' "
            "AND scope_pathway IS NOT NULL AND documented_in_record IS TRUE "
            "AND signature_on_file IS TRUE "
            "AND (scope_pathway <> 'well_child' OR applies_to = 'child_by_guardian')",
            persisted=True,
        ),
        nullable=False,
    )
    grants_contact: Mapped[bool] = mapped_column(
        Boolean,
        Computed("consent_type = 'contact' AND state = 'granted'", persisted=True),
        nullable=False,
    )
    grants_ai_scoring: Mapped[bool] = mapped_column(
        Boolean,
        Computed(
            "consent_type = 'ai_assisted_prioritisation' AND state = 'granted'",
            persisted=True,
        ),
        nullable=False,
    )

    __table_args__ = (
        _fk(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.patient_id"],
            "fk_consent_patient_id_patient",
        ),
        _fk(
            ["run_id", "patient_id", "guardian_id"],
            ["guardian.run_id", "guardian.patient_id", "guardian.guardian_id"],
            "fk_consent_guardian_id_guardian",
        ),
        _fk(
            ["scope_rule_id", "scope_rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_consent_scope_rule_id_rule",
            ref_schema="clinical",
        ),
        UniqueConstraint(
            "run_id", "patient_id", "consent_id", name="uq_consent_run_id_patient_id_consent_id"
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "consent_id",
            "refusal_evidence_valid",
            name="uq_consent_refusal_evidence_valid",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "consent_id",
            "grants_contact",
            name="uq_consent_grants_contact",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "consent_id",
            "grants_ai_scoring",
            name="uq_consent_grants_ai_scoring",
        ),
        *_synth_checks("consent_id", "CNS"),
        CheckConstraint(
            "(applies_to = 'child_by_guardian') = (guardian_id IS NOT NULL)",
            name="guardian_applies_to",
        ),
        CheckConstraint(
            "consent_type IN ('contact', 'data_processing', 'ai_assisted_prioritisation', 'screening_participation')",
            name="consent_type",
        ),
        CheckConstraint(
            "state IN ('granted', 'withdrawn', 'refused')", name="state"
        ),
        CheckConstraint(
            "applies_to IN ('self', 'child_by_guardian')", name="applies_to"
        ),
        CheckConstraint(
            "scope_pathway IN ('ifhas', 'well_child')", name="scope_pathway"
        ),
        CheckConstraint(
            "num_nonnulls(scope_rule_id, scope_rule_version) <> 1",
            name="scope_rule_pair",
        ),
        CheckConstraint(
            "scope_rule_id IS NULL OR scope_pathway IS NOT NULL",
            name="scope_rule_requires_pathway",
        ),
        CheckConstraint(
            "state = 'refused' OR refusal_reason IS NULL", name="refusal_reason"
        ),
        Index("ix_consent_patient_type_recorded", "patient_id", "consent_type", "recorded_at"),
        {"schema": SCHEMA},
    )


class HistoryAvailability(Base):
    __tablename__ = "history_availability"

    history_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    pathway: Mapped[str] = mapped_column(Text, nullable=False)
    history_status: Mapped[str] = mapped_column(Text, nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _fk(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.patient_id"],
            "fk_history_availability_patient_id_patient",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "pathway",
            "as_of_date",
            name="uq_history_availability_patient_pathway_date",
        ),
        *_synth_checks("history_id", "HST"),
        CheckConstraint("pathway IN ('ifhas', 'well_child')", name="pathway"),
        CheckConstraint(
            "history_status IN ('available', 'partial', 'not_available')",
            name="history_status",
        ),
        Index(
            "ix_history_availability_patient_pathway_date",
            "patient_id",
            "pathway",
            "as_of_date",
        ),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# §5.3 Evaluation
# ---------------------------------------------------------------------------
class EligibilityEvaluation(Base):
    __tablename__ = "eligibility_evaluation"

    evaluation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    evaluation_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    evaluation_status: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text)
    next_due_date: Mapped[date | None] = mapped_column(Date)
    # Recorded at evaluation time (migration 0010, F-12); NULL on rows written before 0010.
    reason_detail: Mapped[str | None] = mapped_column(Text)
    input_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        _fk(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.patient_id"],
            "fk_eligibility_evaluation_patient_id_patient",
        ),
        _fk(
            ["run_id", "evaluation_run_id"],
            ["evaluation_run.run_id", "evaluation_run.evaluation_run_id"],
            "fk_eligibility_evaluation_evaluation_run_id_evaluation_run",
        ),
        _fk(
            ["rule_id", "rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_eligibility_evaluation_rule_id_rule",
            ref_schema="clinical",
        ),
        _fk(
            ["evaluation_status"],
            ["evaluation_status.code"],
            "fk_eligibility_evaluation_evaluation_status_evaluation_status",
            ref_schema="clinical",
        ),
        _fk(
            ["reason_code"],
            ["reason_code.code"],
            "fk_eligibility_evaluation_reason_code_reason_code",
            ref_schema="clinical",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "evaluation_id",
            name="uq_eligibility_evaluation_run_patient_eval",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "evaluation_id",
            "rule_id",
            "rule_version",
            name="uq_eligibility_evaluation_run_patient_eval_rule",
        ),
        UniqueConstraint(
            "evaluation_run_id",
            "patient_id",
            "rule_id",
            "rule_version",
            name="uq_eligibility_evaluation_run_patient_rule_unique",
        ),
        *_synth_checks("evaluation_id", "EVL"),
        CheckConstraint(
            "evaluation_status NOT IN ('unknown', 'insufficient_information', 'requires_clinical_review') OR reason_code IS NOT NULL",
            name="reason_code_required_for_non_decisive",
        ),
        Index(
            "ix_eligibility_evaluation_patient_rule_evaluated",
            "patient_id",
            "rule_id",
            "evaluated_at",
        ),
        Index("ix_eligibility_evaluation_status", "evaluation_status"),
        Index("ix_eligibility_evaluation_rule", "rule_id", "rule_version"),
        {"schema": SCHEMA},
    )


class EvaluationReason(Base):
    __tablename__ = "evaluation_reason"

    reason_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    evaluation_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    reason_ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    guard_id: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    item_category: Mapped[str | None] = mapped_column(Text)
    item_code: Mapped[str | None] = mapped_column(Text)
    reason_detail: Mapped[str | None] = mapped_column(Text)  # migration 0010 (F-12)

    __table_args__ = (
        _fk(
            ["run_id", "patient_id", "evaluation_id", "rule_id", "rule_version"],
            [
                "eligibility_evaluation.run_id",
                "eligibility_evaluation.patient_id",
                "eligibility_evaluation.evaluation_id",
                "eligibility_evaluation.rule_id",
                "eligibility_evaluation.rule_version",
            ],
            "fk_evaluation_reason_evaluation_id_eligibility_evaluation",
        ),
        _fk(
            ["guard_id"],
            ["guard.guard_id"],
            "fk_evaluation_reason_guard_id_guard",
            ref_schema="clinical",
        ),
        _fk(
            ["reason_code"],
            ["reason_code.code"],
            "fk_evaluation_reason_reason_code_reason_code",
            ref_schema="clinical",
        ),
        _fk(
            ["rule_id", "rule_version", "item_category", "item_code"],
            [
                "rule_item.rule_id",
                "rule_item.rule_version",
                "rule_item.category",
                "rule_item.code",
            ],
            "fk_evaluation_reason_item_code_rule_item",
            ref_schema="clinical",
        ),
        UniqueConstraint(
            "evaluation_id",
            "reason_ordinal",
            name="uq_evaluation_reason_evaluation_id_ordinal",
        ),
        *_synth_checks("reason_id", "ERS"),
        CheckConstraint(
            "num_nonnulls(item_category, item_code) <> 1", name="item_pair"
        ),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# §5.4–5.5 Booking, care events, assessments, referrals, care gaps, outreach
# ---------------------------------------------------------------------------
class Appointment(Base):
    __tablename__ = "appointment"

    appointment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    profile_id: Mapped[str] = mapped_column(Text, nullable=False)
    care_gap_id: Mapped[str | None] = mapped_column(Text)
    appointment_type: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_datetime: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    slot_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    booked_via: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        _fk(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.patient_id"],
            "fk_appointment_patient_id_patient",
        ),
        _fk(
            ["run_id", "profile_id"],
            ["facility_service_profile.run_id", "facility_service_profile.profile_id"],
            "fk_appointment_profile_id_facility_service_profile",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "appointment_id",
            name="uq_appointment_run_patient_appointment",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "appointment_id",
            "profile_id",
            name="uq_appointment_run_patient_appointment_profile",
        ),
        *_synth_checks("appointment_id", "APT"),
        CheckConstraint(
            "appointment_type IN ('ifhas_screening', 'well_child_visit', 'referral_visit', 'other')",
            name="appointment_type",
        ),
        CheckConstraint(
            "slot_type IN ('weekday', 'evening', 'weekend')", name="slot_type"
        ),
        CheckConstraint(
            "status IN ('scheduled', 'attended', 'no_show', 'cancelled_by_patient', 'cancelled_by_facility', 'rescheduled')",
            name="status",
        ),
        Index("ix_appointment_patient_scheduled", "patient_id", "scheduled_datetime"),
        Index("ix_appointment_care_gap_id", "care_gap_id"),
        Index("ix_appointment_profile_scheduled", "profile_id", "scheduled_datetime"),
        {"schema": SCHEMA},
    )


class IfhasScreening(Base):
    __tablename__ = "ifhas_screening"

    screening_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    profile_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    appointment_id: Mapped[str | None] = mapped_column(Text)
    performed_date: Mapped[date | None] = mapped_column(Date)
    completion_status: Mapped[str] = mapped_column(Text, nullable=False)
    results_communicated_date: Mapped[date | None] = mapped_column(Date)
    journey_reported_date: Mapped[date | None] = mapped_column(Date)
    has_abnormal_finding: Mapped[bool | None] = mapped_column(Boolean)
    has_performed: Mapped[bool] = mapped_column(
        Boolean,
        Computed("performed_date IS NOT NULL", persisted=True),
        nullable=False,
    )

    __table_args__ = (
        _fk(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.patient_id"],
            "fk_ifhas_screening_patient_id_patient",
        ),
        _fk(
            ["run_id", "profile_id"],
            ["facility_service_profile.run_id", "facility_service_profile.profile_id"],
            "fk_ifhas_screening_profile_id_facility_service_profile",
        ),
        _fk(
            ["rule_id", "rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_ifhas_screening_rule_id_rule",
            ref_schema="clinical",
        ),
        _fk(
            ["run_id", "patient_id", "appointment_id", "profile_id"],
            [
                "appointment.run_id",
                "appointment.patient_id",
                "appointment.appointment_id",
                "appointment.profile_id",
            ],
            "fk_ifhas_screening_appointment_id_appointment",
        ),
        UniqueConstraint(
            "appointment_id", name="uq_ifhas_screening_appointment_id"
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "screening_id",
            name="uq_ifhas_screening_run_patient_screening",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "screening_id",
            "rule_id",
            "rule_version",
            name="uq_ifhas_screening_run_patient_screening_rule",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "screening_id",
            "has_performed",
            "rule_id",
            "rule_version",
            name="uq_ifhas_screening_performed_evidence",
        ),
        *_synth_checks("screening_id", "SCR"),
        CheckConstraint(
            "completion_status IN ('complete', 'partial', 'not_attended')",
            name="completion_status",
        ),
        CheckConstraint(
            "(completion_status = 'not_attended') = (performed_date IS NULL)",
            name="performed_date_matches_status",
        ),
        Index(
            "ix_ifhas_screening_patient_rule_performed",
            "patient_id",
            "rule_id",
            "performed_date",
        ),
        Index("ix_ifhas_screening_appointment_id", "appointment_id"),
        {"schema": SCHEMA},
    )


class WellChildVisit(Base):
    __tablename__ = "well_child_visit"

    visit_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    guardian_id: Mapped[str] = mapped_column(Text, nullable=False)
    profile_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    appointment_id: Mapped[str | None] = mapped_column(Text)
    performed_date: Mapped[date | None] = mapped_column(Date)
    attendance_status: Mapped[str] = mapped_column(Text, nullable=False)
    is_catch_up_visit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_performed: Mapped[bool] = mapped_column(
        Boolean,
        Computed("performed_date IS NOT NULL", persisted=True),
        nullable=False,
    )

    __table_args__ = (
        _fk(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.patient_id"],
            "fk_well_child_visit_patient_id_patient",
        ),
        _fk(
            ["run_id", "patient_id", "guardian_id"],
            ["guardian.run_id", "guardian.patient_id", "guardian.guardian_id"],
            "fk_well_child_visit_guardian_id_guardian",
        ),
        _fk(
            ["run_id", "profile_id"],
            ["facility_service_profile.run_id", "facility_service_profile.profile_id"],
            "fk_well_child_visit_profile_id_facility_service_profile",
        ),
        _fk(
            ["rule_id", "rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_well_child_visit_rule_id_rule",
            ref_schema="clinical",
        ),
        _fk(
            ["run_id", "patient_id", "appointment_id", "profile_id"],
            [
                "appointment.run_id",
                "appointment.patient_id",
                "appointment.appointment_id",
                "appointment.profile_id",
            ],
            "fk_well_child_visit_appointment_id_appointment",
        ),
        UniqueConstraint(
            "appointment_id", name="uq_well_child_visit_appointment_id"
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "visit_id",
            name="uq_well_child_visit_run_patient_visit",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "visit_id",
            "rule_id",
            "rule_version",
            name="uq_well_child_visit_run_patient_visit_rule",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "visit_id",
            "has_performed",
            "rule_id",
            "rule_version",
            name="uq_well_child_visit_performed_evidence",
        ),
        *_synth_checks("visit_id", "VIS"),
        CheckConstraint(
            "attendance_status IN ('attended', 'not_attended')",
            name="attendance_status",
        ),
        CheckConstraint(
            "(attendance_status = 'attended') = (performed_date IS NOT NULL)",
            name="performed_date_matches_attendance",
        ),
        {"schema": SCHEMA},
    )


class ComponentResult(Base):
    __tablename__ = "component_result"

    component_result_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    ifhas_screening_id: Mapped[str | None] = mapped_column(Text)
    well_child_visit_id: Mapped[str | None] = mapped_column(Text)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    item_category: Mapped[str] = mapped_column(Text, nullable=False)
    item_code: Mapped[str] = mapped_column(Text, nullable=False)
    result_status: Mapped[str] = mapped_column(Text, nullable=False)
    performed_date: Mapped[date | None] = mapped_column(Date)
    documented_in_record: Mapped[bool | None] = mapped_column(Boolean)
    signature_on_file: Mapped[bool | None] = mapped_column(Boolean)
    refused_by_guardian_id: Mapped[str | None] = mapped_column(Text)
    refusal_reason: Mapped[str | None] = mapped_column(Text)
    refusal_evidence_valid: Mapped[bool] = mapped_column(
        Boolean,
        Computed(
            "result_status = 'refused' AND documented_in_record IS TRUE "
            "AND signature_on_file IS TRUE "
            "AND (well_child_visit_id IS NULL OR refused_by_guardian_id IS NOT NULL)",
            persisted=True,
        ),
        nullable=False,
    )

    __table_args__ = (
        _fk(
            ["run_id", "patient_id", "ifhas_screening_id", "rule_id", "rule_version"],
            [
                "ifhas_screening.run_id",
                "ifhas_screening.patient_id",
                "ifhas_screening.screening_id",
                "ifhas_screening.rule_id",
                "ifhas_screening.rule_version",
            ],
            "fk_component_result_ifhas_screening_id_ifhas_screening",
        ),
        _fk(
            ["run_id", "patient_id", "well_child_visit_id", "rule_id", "rule_version"],
            [
                "well_child_visit.run_id",
                "well_child_visit.patient_id",
                "well_child_visit.visit_id",
                "well_child_visit.rule_id",
                "well_child_visit.rule_version",
            ],
            "fk_component_result_well_child_visit_id_well_child_visit",
        ),
        _fk(
            ["rule_id", "rule_version", "item_category", "item_code"],
            [
                "rule_item.rule_id",
                "rule_item.rule_version",
                "rule_item.category",
                "rule_item.code",
            ],
            "fk_component_result_item_code_rule_item",
            ref_schema="clinical",
        ),
        _fk(
            ["run_id", "patient_id", "refused_by_guardian_id"],
            ["guardian.run_id", "guardian.patient_id", "guardian.guardian_id"],
            "fk_component_result_refused_by_guardian_id_guardian",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "component_result_id",
            name="uq_component_result_run_patient_id",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "component_result_id",
            "rule_id",
            "rule_version",
            "refusal_evidence_valid",
            name="uq_component_result_refusal_evidence",
        ),
        UniqueConstraint(
            "ifhas_screening_id",
            "item_category",
            "item_code",
            name="uq_component_result_ifhas_item",
        ),
        UniqueConstraint(
            "well_child_visit_id",
            "item_category",
            "item_code",
            name="uq_component_result_wcv_item",
        ),
        *_synth_checks("component_result_id", "CMP"),
        CheckConstraint(
            "num_nonnulls(ifhas_screening_id, well_child_visit_id) = 1",
            name="single_parent_event",
        ),
        CheckConstraint(
            "result_status IN ('completed', 'refused', 'not_done', 'not_applicable')",
            name="result_status",
        ),
        CheckConstraint(
            "result_status <> 'completed' OR performed_date IS NOT NULL",
            name="completed_requires_date",
        ),
        CheckConstraint(
            "result_status <> 'refused' OR performed_date IS NULL",
            name="refused_has_no_performed_date",
        ),
        CheckConstraint(
            "result_status = 'refused' OR (documented_in_record IS NULL AND signature_on_file IS NULL AND refused_by_guardian_id IS NULL AND refusal_reason IS NULL)",
            name="refusal_fields_only_on_refused",
        ),
        CheckConstraint(
            "ifhas_screening_id IS NULL OR refused_by_guardian_id IS NULL",
            name="ifhas_has_no_guardian_refusal",
        ),
        {"schema": SCHEMA},
    )


class Assessment(Base):
    __tablename__ = "assessment"

    assessment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    ifhas_screening_id: Mapped[str | None] = mapped_column(Text)
    well_child_visit_id: Mapped[str | None] = mapped_column(Text)
    instrument: Mapped[str] = mapped_column(Text, nullable=False)
    instrument_version: Mapped[str | None] = mapped_column(Text)
    administered_date: Mapped[date] = mapped_column(Date, nullable=False)
    raw_score: Mapped[Decimal | None] = mapped_column(Numeric)
    item_responses: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    rule_id: Mapped[str | None] = mapped_column(Text)
    rule_version: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _fk(
            ["run_id", "patient_id", "ifhas_screening_id"],
            [
                "ifhas_screening.run_id",
                "ifhas_screening.patient_id",
                "ifhas_screening.screening_id",
            ],
            "fk_assessment_ifhas_screening_id_ifhas_screening",
        ),
        _fk(
            ["run_id", "patient_id", "well_child_visit_id"],
            [
                "well_child_visit.run_id",
                "well_child_visit.patient_id",
                "well_child_visit.visit_id",
            ],
            "fk_assessment_well_child_visit_id_well_child_visit",
        ),
        _fk(
            ["rule_id", "rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_assessment_rule_id_rule",
            ref_schema="clinical",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "assessment_id",
            name="uq_assessment_run_patient_assessment",
        ),
        *_synth_checks("assessment_id", "ASM"),
        CheckConstraint(
            "num_nonnulls(ifhas_screening_id, well_child_visit_id) = 1",
            name="single_parent_event",
        ),
        CheckConstraint(
            "instrument IN ('M-CHAT-R', 'IDAQ', 'PHQ-9', 'GAD-7')",
            name="instrument",
        ),
        CheckConstraint(
            "num_nonnulls(rule_id, rule_version) <> 1", name="rule_pair"
        ),
        CheckConstraint(
            "instrument NOT IN ('PHQ-9', 'GAD-7') OR rule_id IS NULL",
            name="no_tier_rule_for_phq9_gad7",
        ),
        {"schema": SCHEMA},
    )


class Referral(Base):
    __tablename__ = "referral"

    referral_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    ifhas_screening_id: Mapped[str | None] = mapped_column(Text)
    well_child_visit_id: Mapped[str | None] = mapped_column(Text)
    assessment_id: Mapped[str | None] = mapped_column(Text)
    trigger_rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    rule_action_ordinal: Mapped[int | None] = mapped_column(SmallInteger)
    referral_target: Mapped[str] = mapped_column(Text, nullable=False)
    target_profile_id: Mapped[str | None] = mapped_column(Text)
    trigger_date: Mapped[date] = mapped_column(Date, nullable=False)
    initiated_date: Mapped[date | None] = mapped_column(Date)
    completed_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    is_initiated: Mapped[bool] = mapped_column(
        Boolean,
        Computed("initiated_date IS NOT NULL", persisted=True),
        nullable=False,
    )

    __table_args__ = (
        _fk(
            ["run_id", "patient_id", "ifhas_screening_id"],
            [
                "ifhas_screening.run_id",
                "ifhas_screening.patient_id",
                "ifhas_screening.screening_id",
            ],
            "fk_referral_ifhas_screening_id_ifhas_screening",
        ),
        _fk(
            ["run_id", "patient_id", "well_child_visit_id"],
            [
                "well_child_visit.run_id",
                "well_child_visit.patient_id",
                "well_child_visit.visit_id",
            ],
            "fk_referral_well_child_visit_id_well_child_visit",
        ),
        _fk(
            ["run_id", "patient_id", "assessment_id"],
            ["assessment.run_id", "assessment.patient_id", "assessment.assessment_id"],
            "fk_referral_assessment_id_assessment",
        ),
        _fk(
            ["trigger_rule_id", "trigger_rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_referral_trigger_rule_id_rule",
            ref_schema="clinical",
        ),
        _fk(
            ["run_id", "target_profile_id"],
            ["facility_service_profile.run_id", "facility_service_profile.profile_id"],
            "fk_referral_target_profile_id_facility_service_profile",
        ),
        UniqueConstraint(
            "run_id", "patient_id", "referral_id", name="uq_referral_run_patient_referral"
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "referral_id",
            "is_initiated",
            name="uq_referral_initiated_evidence",
        ),
        *_synth_checks("referral_id", "REF"),
        CheckConstraint(
            "num_nonnulls(ifhas_screening_id, well_child_visit_id, assessment_id) = 1",
            name="single_source_event",
        ),
        CheckConstraint(
            "status IN ('pending', 'initiated', 'completed', 'declined', 'cancelled')",
            name="status",
        ),
        CheckConstraint(
            "initiated_date IS NULL OR initiated_date >= trigger_date",
            name="initiated_after_trigger",
        ),
        CheckConstraint(
            "completed_date IS NULL OR (initiated_date IS NOT NULL AND completed_date >= initiated_date)",
            name="completed_after_initiated",
        ),
        CheckConstraint(
            "status NOT IN ('initiated', 'completed') OR initiated_date IS NOT NULL",
            name="status_requires_initiated_date",
        ),
        CheckConstraint(
            "status <> 'completed' OR completed_date IS NOT NULL",
            name="completed_requires_completed_date",
        ),
        {"schema": SCHEMA},
    )


class CareGap(Base):
    __tablename__ = "care_gap"

    care_gap_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Group 1 — rule fact
    evaluation_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    gap_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_ifhas_screening_id: Mapped[str | None] = mapped_column(Text)
    subject_well_child_visit_id: Mapped[str | None] = mapped_column(Text)
    subject_referral_id: Mapped[str | None] = mapped_column(Text)
    identified_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Group 2 — lifecycle & closing evidence
    status: Mapped[str] = mapped_column(Text, nullable=False)
    closed_date: Mapped[date | None] = mapped_column(Date)
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    closed_by_ifhas_screening_id: Mapped[str | None] = mapped_column(Text)
    closed_by_well_child_visit_id: Mapped[str | None] = mapped_column(Text)
    closed_by_referral_id: Mapped[str | None] = mapped_column(Text)
    closed_by_component_result_id: Mapped[str | None] = mapped_column(Text)
    closed_by_consent_id: Mapped[str | None] = mapped_column(Text)
    completion_evidence_marker: Mapped[bool | None] = mapped_column(
        Boolean,
        Computed(
            "CASE WHEN num_nonnulls(closed_by_ifhas_screening_id, closed_by_well_child_visit_id, closed_by_referral_id) > 0 THEN TRUE END",
            persisted=True,
        ),
    )
    refusal_evidence_marker: Mapped[bool | None] = mapped_column(
        Boolean,
        Computed(
            "CASE WHEN num_nonnulls(closed_by_component_result_id, closed_by_consent_id) > 0 THEN TRUE END",
            persisted=True,
        ),
    )

    # Group 3 — AI scoring
    priority_score: Mapped[Decimal | None] = mapped_column(Numeric)
    priority_explanation: Mapped[str | None] = mapped_column(Text)
    scored_by_model_version: Mapped[str | None] = mapped_column(Text)
    scored_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    scoring_consent_id: Mapped[str | None] = mapped_column(Text)
    scoring_consent_marker: Mapped[bool | None] = mapped_column(
        Boolean,
        Computed(
            "CASE WHEN scoring_consent_id IS NOT NULL THEN TRUE END",
            persisted=True,
        ),
    )
    scoring_suppressed_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _fk(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.patient_id"],
            "fk_care_gap_patient_id_patient",
        ),
        _fk(
            ["run_id", "patient_id", "evaluation_id", "rule_id", "rule_version"],
            [
                "eligibility_evaluation.run_id",
                "eligibility_evaluation.patient_id",
                "eligibility_evaluation.evaluation_id",
                "eligibility_evaluation.rule_id",
                "eligibility_evaluation.rule_version",
            ],
            "fk_care_gap_evaluation_id_eligibility_evaluation",
        ),
        _fk(
            ["run_id", "patient_id", "subject_ifhas_screening_id"],
            [
                "ifhas_screening.run_id",
                "ifhas_screening.patient_id",
                "ifhas_screening.screening_id",
            ],
            "fk_care_gap_subject_ifhas_screening_id_ifhas_screening",
        ),
        _fk(
            ["run_id", "patient_id", "subject_well_child_visit_id"],
            [
                "well_child_visit.run_id",
                "well_child_visit.patient_id",
                "well_child_visit.visit_id",
            ],
            "fk_care_gap_subject_well_child_visit_id_well_child_visit",
        ),
        _fk(
            ["run_id", "patient_id", "subject_referral_id"],
            ["referral.run_id", "referral.patient_id", "referral.referral_id"],
            "fk_care_gap_subject_referral_id_referral",
        ),
        _fk(
            [
                "run_id",
                "patient_id",
                "closed_by_ifhas_screening_id",
                "completion_evidence_marker",
                "rule_id",
                "rule_version",
            ],
            [
                "ifhas_screening.run_id",
                "ifhas_screening.patient_id",
                "ifhas_screening.screening_id",
                "ifhas_screening.has_performed",
                "ifhas_screening.rule_id",
                "ifhas_screening.rule_version",
            ],
            "fk_care_gap_closed_by_ifhas_screening_id_ifhas_screening",
        ),
        _fk(
            [
                "run_id",
                "patient_id",
                "closed_by_well_child_visit_id",
                "completion_evidence_marker",
                "rule_id",
                "rule_version",
            ],
            [
                "well_child_visit.run_id",
                "well_child_visit.patient_id",
                "well_child_visit.visit_id",
                "well_child_visit.has_performed",
                "well_child_visit.rule_id",
                "well_child_visit.rule_version",
            ],
            "fk_care_gap_closed_by_well_child_visit_id_well_child_visit",
        ),
        _fk(
            [
                "run_id",
                "patient_id",
                "closed_by_referral_id",
                "completion_evidence_marker",
            ],
            [
                "referral.run_id",
                "referral.patient_id",
                "referral.referral_id",
                "referral.is_initiated",
            ],
            "fk_care_gap_closed_by_referral_id_referral",
        ),
        _fk(
            [
                "run_id",
                "patient_id",
                "closed_by_component_result_id",
                "rule_id",
                "rule_version",
                "refusal_evidence_marker",
            ],
            [
                "component_result.run_id",
                "component_result.patient_id",
                "component_result.component_result_id",
                "component_result.rule_id",
                "component_result.rule_version",
                "component_result.refusal_evidence_valid",
            ],
            "fk_care_gap_closed_by_component_result_id_component_result",
        ),
        _fk(
            [
                "run_id",
                "patient_id",
                "closed_by_consent_id",
                "refusal_evidence_marker",
            ],
            [
                "consent.run_id",
                "consent.patient_id",
                "consent.consent_id",
                "consent.refusal_evidence_valid",
            ],
            "fk_care_gap_closed_by_consent_id_consent",
        ),
        _fk(
            [
                "run_id",
                "patient_id",
                "scoring_consent_id",
                "scoring_consent_marker",
            ],
            [
                "consent.run_id",
                "consent.patient_id",
                "consent.consent_id",
                "consent.grants_ai_scoring",
            ],
            "fk_care_gap_scoring_consent_id_consent",
        ),
        UniqueConstraint("run_id", "care_gap_id", name="uq_care_gap_run_id_care_gap_id"),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "care_gap_id",
            name="uq_care_gap_run_patient_care_gap",
        ),
        UniqueConstraint(
            "closed_by_component_result_id",
            name="uq_care_gap_closed_by_component_result_id",
        ),
        *_synth_checks("care_gap_id", "GAP"),
        CheckConstraint(
            "gap_type IN ('no_documented_screening', 'interval_elapsed', 'partial_completion', 'referral_not_initiated', 'visit_not_attended')",
            name="gap_type",
        ),
        CheckConstraint(
            "num_nonnulls(subject_ifhas_screening_id, subject_well_child_visit_id, subject_referral_id) <= 1",
            name="single_subject",
        ),
        CheckConstraint(
            "status IN ('open', 'closed_completed', 'closed_refused', 'suppressed', 'superseded')",
            name="status",
        ),
        CheckConstraint(
            "(status IN ('closed_completed', 'closed_refused')) = (closed_date IS NOT NULL)",
            name="closed_date_consistency",
        ),
        CheckConstraint(
            "(status = 'suppressed') = (suppression_reason IS NOT NULL)",
            name="suppression_reason_consistency",
        ),
        CheckConstraint(
            "(status = 'closed_completed' AND num_nonnulls(closed_by_ifhas_screening_id, closed_by_well_child_visit_id, closed_by_referral_id) = 1) "
            "OR (status <> 'closed_completed' AND num_nonnulls(closed_by_ifhas_screening_id, closed_by_well_child_visit_id, closed_by_referral_id) = 0)",
            name="completion_evidence_consistency",
        ),
        CheckConstraint(
            "(status = 'closed_refused' AND num_nonnulls(closed_by_component_result_id, closed_by_consent_id) = 1) "
            "OR (status <> 'closed_refused' AND num_nonnulls(closed_by_component_result_id, closed_by_consent_id) = 0)",
            name="refusal_evidence_consistency",
        ),
        CheckConstraint(
            "status <> 'closed_refused' OR gap_type <> 'referral_not_initiated'",
            name="referral_gap_not_closed_refused",
        ),
        CheckConstraint(
            "priority_score IS NULL OR (priority_explanation IS NOT NULL AND scored_by_model_version IS NOT NULL AND scored_at IS NOT NULL AND scoring_consent_id IS NOT NULL)",
            name="ai_scoring_requires_explanation_and_consent",
        ),
        CheckConstraint(
            "scoring_suppressed_reason IS NULL OR priority_score IS NULL",
            name="scoring_suppressed_excludes_score",
        ),
        Index("ix_care_gap_patient_id", "patient_id"),
        Index("ix_care_gap_evaluation_id", "evaluation_id"),
        Index("ix_care_gap_status", "status"),
        {"schema": SCHEMA},
    )


# Deferred circular FK from Appointment -> CareGap
Appointment.__table__.append_constraint(
    _fk(
        ["run_id", "patient_id", "care_gap_id"],
        ["care_gap.run_id", "care_gap.patient_id", "care_gap.care_gap_id"],
        "fk_appointment_care_gap_id_care_gap",
    )
)


class CareGapReview(Base):
    __tablename__ = "care_gap_review"

    review_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    care_gap_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    reviewer: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    previous_priority: Mapped[Decimal | None] = mapped_column(Numeric)
    new_priority: Mapped[Decimal | None] = mapped_column(Numeric)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )

    __table_args__ = (
        _fk(
            ["run_id", "care_gap_id"],
            ["care_gap.run_id", "care_gap.care_gap_id"],
            "fk_care_gap_review_care_gap_id_care_gap",
        ),
        *_synth_checks("review_id", "REV"),
        CheckConstraint(
            "action IN ('confirmed', 'priority_overridden', 'dismissed')",
            name="action",
        ),
        CheckConstraint(
            "action <> 'priority_overridden' OR new_priority IS NOT NULL",
            name="override_requires_new_priority",
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_nonempty"),
        Index("ix_care_gap_review_gap_reviewed_at", "care_gap_id", "reviewed_at"),
        {"schema": SCHEMA},
    )


class OutreachEvent(Base):
    __tablename__ = "outreach_event"

    outreach_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    care_gap_id: Mapped[str] = mapped_column(Text, nullable=False)
    guardian_id: Mapped[str | None] = mapped_column(Text)
    recipient: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    sent_datetime: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    delivery_status: Mapped[str] = mapped_column(Text, nullable=False)
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    contact_consent_id: Mapped[str | None] = mapped_column(Text)
    contact_consent_marker: Mapped[bool | None] = mapped_column(
        Boolean,
        Computed(
            "CASE WHEN contact_consent_id IS NOT NULL THEN TRUE END",
            persisted=True,
        ),
    )
    response: Mapped[str | None] = mapped_column(Text)
    appointment_id: Mapped[str | None] = mapped_column(Text)
    triggered_by_ai_score: Mapped[bool] = mapped_column(Boolean, nullable=False)
    clinician_approved_by: Mapped[str | None] = mapped_column(Text)
    message_template_id: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _fk(
            ["run_id", "patient_id", "care_gap_id"],
            ["care_gap.run_id", "care_gap.patient_id", "care_gap.care_gap_id"],
            "fk_outreach_event_care_gap_id_care_gap",
        ),
        _fk(
            ["run_id", "patient_id", "guardian_id"],
            ["guardian.run_id", "guardian.patient_id", "guardian.guardian_id"],
            "fk_outreach_event_guardian_id_guardian",
        ),
        _fk(
            [
                "run_id",
                "patient_id",
                "contact_consent_id",
                "contact_consent_marker",
            ],
            [
                "consent.run_id",
                "consent.patient_id",
                "consent.consent_id",
                "consent.grants_contact",
            ],
            "fk_outreach_event_contact_consent_id_consent",
        ),
        _fk(
            ["run_id", "patient_id", "appointment_id"],
            [
                "appointment.run_id",
                "appointment.patient_id",
                "appointment.appointment_id",
            ],
            "fk_outreach_event_appointment_id_appointment",
        ),
        *_synth_checks("outreach_id", "OUT"),
        CheckConstraint(
            "(recipient = 'guardian') = (guardian_id IS NOT NULL)",
            name="guardian_recipient_consistency",
        ),
        CheckConstraint("recipient IN ('patient', 'guardian')", name="recipient"),
        CheckConstraint(
            "event_type IN ('invitation', 'reminder', 'recall_positive_result', 'recall_insufficient_result', 'referral_follow_up')",
            name="event_type",
        ),
        CheckConstraint(
            "channel IN ('sms', 'phone', 'email', 'app')", name="channel"
        ),
        CheckConstraint(
            "delivery_status IN ('queued', 'delivered', 'failed', 'suppressed')",
            name="delivery_status",
        ),
        CheckConstraint(
            "(delivery_status = 'suppressed') = (sent_datetime IS NULL)",
            name="suppressed_sent_datetime",
        ),
        CheckConstraint(
            "(delivery_status = 'suppressed') = (suppression_reason IS NOT NULL)",
            name="suppressed_reason_consistency",
        ),
        CheckConstraint(
            "delivery_status = 'suppressed' OR contact_consent_id IS NOT NULL",
            name="unsuppressed_requires_contact_consent",
        ),
        CheckConstraint(
            "response IN ('no_response', 'booked', 'declined', 'opted_out', 'wrong_contact')",
            name="response",
        ),
        CheckConstraint(
            "appointment_id IS NULL OR response = 'booked'",
            name="appointment_requires_booked_response",
        ),
        Index("ix_outreach_event_care_gap_id", "care_gap_id"),
        Index("ix_outreach_event_patient_sent", "patient_id", "sent_datetime"),
        Index("ix_outreach_event_appointment_id", "appointment_id"),
        Index("ix_outreach_event_contact_consent_id", "contact_consent_id"),
        {"schema": SCHEMA},
    )


class CareGapFollowUpEvent(Base):
    __tablename__ = "care_gap_follow_up_event"

    follow_up_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    care_gap_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_status: Mapped[str | None] = mapped_column(Text)
    documented_evidence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    evidence_reference: Mapped[str | None] = mapped_column(Text)
    contact_consent_id: Mapped[str | None] = mapped_column(Text)
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    appointment_id: Mapped[str | None] = mapped_column(Text)
    referral_id: Mapped[str | None] = mapped_column(Text)
    contact_consent_marker: Mapped[bool | None] = mapped_column(
        Boolean,
        Computed(
            "CASE WHEN contact_consent_id IS NOT NULL THEN TRUE END",
            persisted=True,
        ),
    )

    __table_args__ = (
        _fk(
            ["run_id", "patient_id", "care_gap_id"],
            ["care_gap.run_id", "care_gap.patient_id", "care_gap.care_gap_id"],
            "fk_care_gap_follow_up_event_care_gap",
        ),
        _fk(
            ["run_id", "patient_id", "contact_consent_id", "contact_consent_marker"],
            [
                "consent.run_id",
                "consent.patient_id",
                "consent.consent_id",
                "consent.grants_contact",
            ],
            "fk_care_gap_follow_up_event_contact_consent_id_consent",
        ),
        _fk(
            ["run_id", "patient_id", "appointment_id"],
            ["appointment.run_id", "appointment.patient_id", "appointment.appointment_id"],
            "fk_care_gap_follow_up_event_appointment_id_appointment",
        ),
        _fk(
            ["run_id", "patient_id", "referral_id"],
            ["referral.run_id", "referral.patient_id", "referral.referral_id"],
            "fk_care_gap_follow_up_event_referral_id_referral",
        ),
        *_synth_checks("follow_up_id", "FUP"),
        CheckConstraint(
            "outcome_status IS NULL OR outcome_status IN ('noted', 'completed', 'suppressed', "
            "'simulated_not_sent', 'status_recorded')",
            name="outcome_status",
        ),
        CheckConstraint(
            "event_type <> 'completion_documented' OR (documented_evidence AND "
            "evidence_reference IS NOT NULL AND outcome_status = 'completed')",
            name="completion_requires_evidence",
        ),
        CheckConstraint(
            "(event_type IN ('appointment_scheduled', 'appointment_updated')) = "
            "(appointment_id IS NOT NULL)",
            name="appointment_link",
        ),
        CheckConstraint(
            "(event_type IN ('referral_created', 'referral_updated')) = (referral_id IS NOT NULL)",
            name="referral_link",
        ),
        CheckConstraint(
            "event_type IN ('outreach_attempted', 'outreach_suppressed', 'appointment_scheduled', "
            "'appointment_updated', 'referral_created', 'referral_updated', "
            "'completion_documented', 'note_recorded')",
            name="event_type",
        ),
        CheckConstraint(
            "event_type <> 'outreach_attempted' OR contact_consent_id IS NOT NULL",
            name="outreach_requires_consent",
        ),
        CheckConstraint(
            "event_type <> 'outreach_suppressed' OR suppression_reason IS NOT NULL",
            name="suppressed_requires_reason",
        ),
        UniqueConstraint(
            "run_id",
            "patient_id",
            "follow_up_id",
            name="uq_care_gap_follow_up_event_run_patient_follow_up",
        ),
        Index("ix_care_gap_follow_up_event_gap_recorded", "care_gap_id", "recorded_at"),
        Index("ix_care_gap_follow_up_event_patient", "patient_id", "recorded_at"),
        {"schema": SCHEMA},
    )


class WorkflowStatusEvent(Base):
    """Append-only appointment/referral status history (migration 0009)."""

    __tablename__ = "workflow_status_event"

    status_event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    appointment_id: Mapped[str | None] = mapped_column(Text)
    referral_id: Mapped[str | None] = mapped_column(Text)
    care_gap_id: Mapped[str | None] = mapped_column(Text)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_datetime: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    initiated_date: Mapped[date | None] = mapped_column(Date)
    completed_date: Mapped[date | None] = mapped_column(Date)
    recorded_by: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _fk(
            ["run_id", "patient_id", "appointment_id"],
            ["appointment.run_id", "appointment.patient_id", "appointment.appointment_id"],
            "fk_workflow_status_event_appointment_id_appointment",
        ),
        _fk(
            ["run_id", "patient_id", "referral_id"],
            ["referral.run_id", "referral.patient_id", "referral.referral_id"],
            "fk_workflow_status_event_referral_id_referral",
        ),
        _fk(
            ["run_id", "patient_id", "care_gap_id"],
            ["care_gap.run_id", "care_gap.patient_id", "care_gap.care_gap_id"],
            "fk_workflow_status_event_care_gap_id_care_gap",
        ),
        *_synth_checks("status_event_id", "WSE"),
        CheckConstraint(
            "(entity_type = 'appointment' AND appointment_id IS NOT NULL AND referral_id IS NULL) "
            "OR (entity_type = 'referral' AND referral_id IS NOT NULL AND appointment_id IS NULL)",
            name="entity_link",
        ),
        CheckConstraint(
            "(entity_type = 'appointment' AND to_status IN ('scheduled', 'attended', 'no_show', "
            "'cancelled_by_patient', 'cancelled_by_facility', 'rescheduled') AND (from_status IS "
            "NULL OR from_status IN ('scheduled', 'rescheduled'))) OR (entity_type = 'referral' "
            "AND to_status IN ('pending', 'initiated', 'completed', 'declined', 'cancelled') AND "
            "(from_status IS NULL OR from_status IN ('pending', 'initiated')))",
            name="status_vocabulary",
        ),
        CheckConstraint(
            "from_status IS NOT NULL OR to_status IN ('scheduled', 'pending', 'initiated')",
            name="creation_status",
        ),
        CheckConstraint("length(btrim(recorded_by)) > 0", name="recorded_by_nonempty"),
        Index("ix_workflow_status_event_appointment", "appointment_id", "recorded_at"),
        Index("ix_workflow_status_event_referral", "referral_id", "recorded_at"),
        Index("ix_workflow_status_event_patient", "patient_id", "recorded_at"),
        {"schema": SCHEMA},
    )


class ConditionRecord(Base):
    """Synthetic problem-list entry (migration 0012, BE-33): one recorded condition of a patient.

    Distinct from care gaps (preventive-care facts). `diagnosis_date` may be unknown;
    `recorded_at` is when the entry reached the record (reporting delay); duplicates of the same
    patient/condition are allowed and collapsed by the aggregation engine.
    """

    __tablename__ = "condition_record"

    condition_record_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    condition_code: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis_date: Mapped[date | None] = mapped_column(Date)
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_date: Mapped[date | None] = mapped_column(Date)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    scenario_tag: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _fk(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.patient_id"],
            "fk_condition_record_patient_id_patient",
        ),
        *_synth_checks("condition_record_id", "CND"),
        CheckConstraint(
            "condition_code IN ('diabetes_type_2', 'hypertension', 'dyslipidaemia', 'asthma')",
            name="condition_code",
        ),
        CheckConstraint(
            "status IN ('active', 'resolved', 'entered_in_error')", name="status"
        ),
        CheckConstraint(
            "(status = 'resolved') = (resolved_date IS NOT NULL)", name="resolved_date_consistency"
        ),
        CheckConstraint(
            "resolved_date IS NULL OR diagnosis_date IS NULL OR resolved_date >= diagnosis_date",
            name="resolved_after_diagnosis",
        ),
        CheckConstraint(
            "diagnosis_date IS NULL OR diagnosis_date <= (recorded_at AT TIME ZONE 'UTC')::date",
            name="diagnosed_before_recorded",
        ),
        Index("ix_condition_record_run_condition_diagnosis", "run_id", "condition_code", "diagnosis_date"),
        Index("ix_condition_record_patient", "patient_id", "condition_code"),
        Index("ix_condition_record_recorded_at", "recorded_at"),
        {"schema": SCHEMA},
    )


class AIAuditRecord(Base):
    """Durable AI generation / human review audit (migration 0010).

    One append-only row per explanation, outreach draft (generated, fallback or blocked),
    population insight and human outreach review. Message texts are never stored: only SHA-256
    fingerprints, references and metadata. A draft accepts at most one terminal review
    (`approved` / `rejected`), so approval cannot be replayed and a rejected draft cannot be
    approved later.
    """

    __tablename__ = "ai_audit_record"

    audit_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    request_id: Mapped[str | None] = mapped_column(Text)
    feature: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str | None] = mapped_column(Text)
    rule_id: Mapped[str | None] = mapped_column(Text)
    care_gap_id: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    generation_mode: Mapped[str] = mapped_column(Text, nullable=False)
    fallback_reason: Mapped[str | None] = mapped_column(Text)
    violations: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    input_sha256: Mapped[str | None] = mapped_column(Text)
    output_sha256: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[float | None] = mapped_column(Double)
    extra: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    draft_audit_id: Mapped[str | None] = mapped_column(Text)
    draft_feature: Mapped[str | None] = mapped_column(
        Text,
        Computed(
            "CASE WHEN draft_audit_id IS NOT NULL THEN 'outreach_draft' END", persisted=True
        ),
    )
    review_decision: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    follow_up_id: Mapped[str | None] = mapped_column(Text)
    simulated_outreach_status: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _fk(["run_id"], ["generation_run.run_id"], "fk_ai_audit_record_run_id_generation_run"),
        _fk(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.patient_id"],
            "fk_ai_audit_record_patient_id_patient",
        ),
        _fk(
            ["run_id", "draft_audit_id", "draft_feature"],
            ["ai_audit_record.run_id", "ai_audit_record.audit_id", "ai_audit_record.feature"],
            "fk_ai_audit_record_draft_audit_id_ai_audit_record",
        ),
        _fk(
            ["run_id", "patient_id", "follow_up_id"],
            [
                "care_gap_follow_up_event.run_id",
                "care_gap_follow_up_event.patient_id",
                "care_gap_follow_up_event.follow_up_id",
            ],
            "fk_ai_audit_record_follow_up_id_care_gap_follow_up_event",
        ),
        UniqueConstraint("run_id", "audit_id", "feature", name="uq_ai_audit_record_run_audit_feature"),
        CheckConstraint("is_synthetic", name="is_synthetic"),
        CheckConstraint("audit_id ~ '^[0-9a-f]{32}$'", name="audit_id_format"),
        CheckConstraint(
            "feature IN ('explanation', 'outreach_draft', 'outreach_review', 'population_insight')",
            name="feature",
        ),
        CheckConstraint(
            "generation_mode IN ('llm_grounded', 'deterministic_fallback', 'not_generated', "
            "'human_approved', 'human_rejected', 'human_blocked', 'human_invalid')",
            name="generation_mode",
        ),
        CheckConstraint(
            "input_sha256 IS NULL OR input_sha256 ~ '^[0-9a-f]{64}$'", name="input_sha256_format"
        ),
        CheckConstraint(
            "output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$'", name="output_sha256_format"
        ),
        CheckConstraint(
            "(feature = 'outreach_review') = (draft_audit_id IS NOT NULL)", name="review_draft_link"
        ),
        CheckConstraint(
            "(feature = 'outreach_review') = (review_decision IS NOT NULL) AND (review_decision "
            "IS NULL OR (review_decision IN ('approved', 'rejected', 'blocked', 'invalid') AND "
            "generation_mode = 'human_' || review_decision))",
            name="review_decision",
        ),
        CheckConstraint(
            "feature <> 'outreach_review' OR length(btrim(coalesce(reviewed_by, ''))) > 0",
            name="review_actor",
        ),
        CheckConstraint(
            "follow_up_id IS NULL OR feature = 'outreach_review'", name="follow_up_only_on_review"
        ),
        CheckConstraint(
            "simulated_outreach_status IS NULL OR simulated_outreach_status IN "
            "('simulated_not_sent', 'suppressed')",
            name="simulated_outreach_status",
        ),
        CheckConstraint(
            "review_decision IS DISTINCT FROM 'approved' OR (follow_up_id IS NOT NULL AND "
            "simulated_outreach_status = 'simulated_not_sent')",
            name="approved_records_simulated_follow_up",
        ),
        Index(
            "uq_ai_audit_record_terminal_review",
            "draft_audit_id",
            unique=True,
            postgresql_where=text("review_decision IN ('approved', 'rejected')"),
        ),
        Index(
            "uq_ai_audit_record_follow_up_id",
            "follow_up_id",
            unique=True,
            postgresql_where=text("follow_up_id IS NOT NULL"),
        ),
        Index("ix_ai_audit_record_feature_recorded", "feature", "recorded_at"),
        Index("ix_ai_audit_record_recorded", "recorded_at"),
        Index("ix_ai_audit_record_patient", "patient_id", "recorded_at"),
        {"schema": SCHEMA},
    )
