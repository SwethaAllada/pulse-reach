"""SQLAlchemy 2.x models for the `clinical` schema (12 tables).

Matches `docs/phase-3-database-design.md` §4 and `docs/erd/clinical-schema-erd.md`.
All foreign keys use `ON DELETE RESTRICT` and `ON UPDATE RESTRICT` and stay strictly
within the `clinical` schema (§2.1 dependency rule).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    TIMESTAMP,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SCHEMA = "clinical"

SHA256_REGEX = r"^[0-9a-f]{64}$"
SEMVER_REGEX = r"^[0-9]+\.[0-9]+\.[0-9]+$"
DATE_PRECISIONS = ("day", "month", "year", "unknown")


def _restrict_fk(
    cols: list[str], ref_cols: list[str], name: str
) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        cols,
        [f"{SCHEMA}.{rc}" for rc in ref_cols],
        name=name,
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )


def _partial_date_checks(prefix: str) -> tuple[CheckConstraint, CheckConstraint]:
    in_list = ", ".join(f"'{p}'" for p in DATE_PRECISIONS)
    return (
        CheckConstraint(
            f"{prefix}_precision IN ({in_list})",
            name=f"{prefix}_precision",
        ),
        CheckConstraint(
            f"(({prefix}_precision = 'unknown') = ({prefix}_text IS NULL)) "
            f"AND (({prefix}_precision = 'day') = ({prefix}_from IS NOT NULL))",
            name=f"{prefix}_triple",
        ),
    )


# ---------------------------------------------------------------------------
# §4.1 Standards & load provenance
# ---------------------------------------------------------------------------
class Standard(Base):
    __tablename__ = "standard"

    standard_id: Mapped[int] = mapped_column(
        SmallInteger, Identity(always=True), primary_key=True
    )
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_version: Mapped[str] = mapped_column(Text, nullable=False)
    document_ref: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str] = mapped_column(Text, nullable=False)
    publication_date_text: Mapped[str | None] = mapped_column(Text)
    publication_date_precision: Mapped[str] = mapped_column(Text, nullable=False)
    publication_date_from: Mapped[date | None] = mapped_column(Date)
    effective_date_text: Mapped[str | None] = mapped_column(Text)
    effective_date_precision: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date_from: Mapped[date | None] = mapped_column(Date)
    effective_date_note: Mapped[str | None] = mapped_column(Text)
    revision_date_text: Mapped[str | None] = mapped_column(Text)
    pdf_pages: Mapped[int | None] = mapped_column(SmallInteger)
    url: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[str | None] = mapped_column(Text)
    status_note: Mapped[str | None] = mapped_column(Text)
    manifest_source_id: Mapped[str | None] = mapped_column(Text)
    acquisition_state: Mapped[str] = mapped_column(Text, nullable=False)
    local_copy_sha256: Mapped[str | None] = mapped_column(CHAR(64))

    __table_args__ = (
        UniqueConstraint(
            "source_name", "source_version", name="uq_standard_source_name_source_version"
        ),
        UniqueConstraint("document_ref", name="uq_standard_document_ref"),
        *_partial_date_checks("publication_date"),
        *_partial_date_checks("effective_date"),
        CheckConstraint(
            "effective_date_precision <> 'unknown' OR effective_date_note IS NOT NULL",
            name="effective_date_note",
        ),
        CheckConstraint("pdf_pages IS NULL OR pdf_pages > 0", name="pdf_pages"),
        CheckConstraint(
            "acquisition_state IN ('blocked', 'document_obtained')",
            name="acquisition_state",
        ),
        CheckConstraint(
            f"local_copy_sha256 IS NULL OR (acquisition_state = 'document_obtained' AND local_copy_sha256 ~ '{SHA256_REGEX}')",
            name="local_copy_sha256",
        ),
        {"schema": SCHEMA},
    )


class RuleLoad(Base):
    __tablename__ = "rule_load"

    load_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    loaded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    loader_version: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    file_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    git_commit: Mapped[str | None] = mapped_column(Text)
    clinical_review_status: Mapped[str] = mapped_column(Text, nullable=False)
    rules_loaded: Mapped[int] = mapped_column(Integer, nullable=False)
    rules_added: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint(f"bundle_sha256 ~ '{SHA256_REGEX}'", name="bundle_sha256"),
        CheckConstraint("rules_loaded >= 0", name="rules_loaded"),
        CheckConstraint(
            "rules_added >= 0 AND rules_added <= rules_loaded", name="rules_added"
        ),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# §4.2 Vocabularies & open questions
# ---------------------------------------------------------------------------
class VerificationStatus(Base):
    __tablename__ = "verification_status"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    may_drive_decisions: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "code IN ('verified', 'reported', 'unresolved')", name="code"
        ),
        CheckConstraint(
            "may_drive_decisions = (code = 'verified')", name="may_drive_decisions"
        ),
        {"schema": SCHEMA},
    )


class EvaluationStatus(Base):
    __tablename__ = "evaluation_status"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    requires_text: Mapped[str | None] = mapped_column(Text)
    never_inferred_from: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("sort_order", name="uq_evaluation_status_sort_order"),
        CheckConstraint(
            "code IN ('eligible', 'not_eligible', 'due', 'upcoming', 'overdue', "
            "'completed', 'unknown', 'insufficient_information', 'requires_clinical_review')",
            name="code",
        ),
        CheckConstraint("sort_order >= 1", name="sort_order"),
        {"schema": SCHEMA},
    )


class ReasonCode(Base):
    __tablename__ = "reason_code"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("length(btrim(code)) > 0", name="code_nonempty"),
        {"schema": SCHEMA},
    )


class Guard(Base):
    __tablename__ = "guard"

    guard_id: Mapped[str] = mapped_column(Text, primary_key=True)
    when_text: Mapped[str] = mapped_column(Text, nullable=False)
    result_status: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _restrict_fk(
            ["result_status"],
            ["evaluation_status.code"],
            "fk_guard_result_status_evaluation_status",
        ),
        _restrict_fk(
            ["reason_code"], ["reason_code.code"], "fk_guard_reason_code_reason_code"
        ),
        {"schema": SCHEMA},
    )


class OpenQuestion(Base):
    __tablename__ = "open_question"

    oq_id: Mapped[str] = mapped_column(Text, primary_key=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    affects_raw: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    resolve_via: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_on: Mapped[date | None] = mapped_column(Date)
    first_load_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_changed_load_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        _restrict_fk(
            ["first_load_id"],
            ["rule_load.load_id"],
            "fk_open_question_first_load_id_rule_load",
        ),
        _restrict_fk(
            ["last_changed_load_id"],
            ["rule_load.load_id"],
            "fk_open_question_last_changed_load_id_rule_load",
        ),
        CheckConstraint("status IN ('open', 'resolved')", name="status"),
        CheckConstraint(
            "resolved_on IS NULL OR resolution IS NOT NULL",
            name="resolved_on_requires_resolution",
        ),
        CheckConstraint(
            "(status = 'resolved') = (resolution IS NOT NULL AND resolved_on IS NOT NULL)",
            name="status_resolution_consistency",
        ),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# §4.3 Versioned rules, conditions, items & open-question links
# ---------------------------------------------------------------------------
class Rule(Base):
    __tablename__ = "rule"

    rule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_version: Mapped[str] = mapped_column(Text, primary_key=True)
    ver_major: Mapped[int] = mapped_column(
        Integer,
        Computed("split_part(rule_version, '.', 1)::integer", persisted=True),
        nullable=False,
    )
    ver_minor: Mapped[int] = mapped_column(
        Integer,
        Computed("split_part(rule_version, '.', 2)::integer", persisted=True),
        nullable=False,
    )
    ver_patch: Mapped[int] = mapped_column(
        Integer,
        Computed("split_part(rule_version, '.', 3)::integer", persisted=True),
        nullable=False,
    )
    pathway: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str | None] = mapped_column(Text)
    standard_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(Text, nullable=False)
    requires_clinical_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_authoritative: Mapped[bool] = mapped_column(
        Boolean,
        Computed(
            "verification_status = 'verified' AND NOT requires_clinical_review",
            persisted=True,
        ),
        nullable=False,
    )
    effective_date_text: Mapped[str | None] = mapped_column(Text)
    effective_date_precision: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date_from: Mapped[date | None] = mapped_column(Date)
    effective_date_note: Mapped[str | None] = mapped_column(Text)
    last_reviewed: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    history: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    yaml_path: Mapped[str] = mapped_column(Text, nullable=False)
    load_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Typed projections (all 20 nullable)
    package_name: Mapped[str | None] = mapped_column(Text)
    package_group: Mapped[str | None] = mapped_column(Text)
    age_min_years: Mapped[int | None] = mapped_column(SmallInteger)
    age_max_years: Mapped[int | None] = mapped_column(SmallInteger)
    age_as_printed: Mapped[str | None] = mapped_column(Text)
    sexes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    frequency_type: Mapped[str | None] = mapped_column(Text)
    interval_value: Mapped[int | None] = mapped_column(SmallInteger)
    interval_unit: Mapped[str | None] = mapped_column(Text)
    visit_number: Mapped[int | None] = mapped_column(SmallInteger)
    visit_id: Mapped[str | None] = mapped_column(Text)
    recommended_age_months: Mapped[int | None] = mapped_column(SmallInteger)
    age_band: Mapped[str | None] = mapped_column(Text)
    instrument: Mapped[str | None] = mapped_column(Text)
    score_min: Mapped[Decimal | None] = mapped_column(Numeric)
    score_max: Mapped[Decimal | None] = mapped_column(Numeric)
    timing_value: Mapped[int | None] = mapped_column(SmallInteger)
    timing_unit: Mapped[str | None] = mapped_column(Text)
    timing_reference_event: Mapped[str | None] = mapped_column(Text)
    gate_attribute: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _restrict_fk(
            ["standard_id"], ["standard.standard_id"], "fk_rule_standard_id_standard"
        ),
        _restrict_fk(
            ["verification_status"],
            ["verification_status.code"],
            "fk_rule_verification_status_verification_status",
        ),
        _restrict_fk(["load_id"], ["rule_load.load_id"], "fk_rule_load_id_rule_load"),
        CheckConstraint(f"rule_version ~ '{SEMVER_REGEX}'", name="rule_version_semver"),
        CheckConstraint("pathway IN ('ifhas', 'well_child')", name="pathway"),
        CheckConstraint(
            "verification_status <> 'unresolved' OR requires_clinical_review",
            name="unresolved_requires_review",
        ),
        CheckConstraint(
            "length(btrim(source_reference)) > 0", name="source_reference_nonempty"
        ),
        CheckConstraint("length(btrim(description)) > 0", name="description_nonempty"),
        *_partial_date_checks("effective_date"),
        CheckConstraint(
            "effective_date_precision <> 'unknown' OR effective_date_note IS NOT NULL",
            name="effective_date_note",
        ),
        CheckConstraint(f"content_sha256 ~ '{SHA256_REGEX}'", name="content_sha256"),
        CheckConstraint(
            "age_min_years IS NULL OR age_max_years IS NULL OR age_min_years <= age_max_years",
            name="age_years_bounds",
        ),
        CheckConstraint(
            "sexes IS NULL OR (cardinality(sexes) > 0 AND sexes <@ ARRAY['female','male']::text[])",
            name="sexes_values",
        ),
        CheckConstraint(
            "frequency_type IN ('recurring', 'once_per_lifetime')",
            name="frequency_type",
        ),
        CheckConstraint(
            "interval_value IS NULL OR interval_value > 0", name="interval_value"
        ),
        CheckConstraint(
            "(frequency_type = 'recurring' AND interval_value IS NOT NULL AND interval_unit IS NOT NULL) "
            "OR (frequency_type = 'once_per_lifetime' AND interval_value IS NULL AND interval_unit IS NULL) "
            "OR (frequency_type IS NULL AND interval_value IS NULL AND interval_unit IS NULL)",
            name="frequency_interval_consistency",
        ),
        CheckConstraint(
            "visit_number IS NULL OR visit_number BETWEEN 1 AND 14", name="visit_number"
        ),
        CheckConstraint(
            "recommended_age_months IS NULL OR recommended_age_months > 0",
            name="recommended_age_months",
        ),
        CheckConstraint(
            "score_min IS NULL OR score_max IS NULL OR score_min <= score_max",
            name="score_bounds",
        ),
        CheckConstraint("timing_value IS NULL OR timing_value > 0", name="timing_value"),
        CheckConstraint(
            "timing_unit IN ('days', 'working_days', 'weeks', 'months', 'years')",
            name="timing_unit",
        ),
        Index("ix_rule_pathway_rule_type", "pathway", "rule_type"),
        Index("ix_rule_verification_status", "verification_status"),
        Index("ix_rule_is_authoritative", "is_authoritative"),
        Index("ix_rule_package_group", "package_group"),
        Index("ix_rule_visit_number", "visit_number"),
        Index("ix_rule_instrument", "instrument"),
        Index("ix_rule_standard_id", "standard_id"),
        Index("ix_rule_load_id", "load_id"),
        {"schema": SCHEMA},
    )


class RuleCondition(Base):
    __tablename__ = "rule_condition"

    rule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_version: Mapped[str] = mapped_column(Text, primary_key=True)
    condition_ordinal: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    as_printed: Mapped[str] = mapped_column(Text, nullable=False)
    machine_evaluable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attribute: Mapped[str | None] = mapped_column(Text)
    required_value: Mapped[Any | None] = mapped_column(JSONB)

    __table_args__ = (
        _restrict_fk(
            ["rule_id", "rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_rule_condition_rule_id_rule",
        ),
        CheckConstraint("condition_ordinal >= 1", name="condition_ordinal"),
        CheckConstraint("kind IN ('inclusion', 'exclusion')", name="kind"),
        CheckConstraint("length(btrim(as_printed)) > 0", name="as_printed_nonempty"),
        CheckConstraint(
            "NOT machine_evaluable OR (attribute IS NOT NULL AND required_value IS NOT NULL)",
            name="machine_evaluable_fields",
        ),
        CheckConstraint(
            "kind <> 'exclusion' OR NOT machine_evaluable",
            name="exclusion_not_machine_evaluable",
        ),
        {"schema": SCHEMA},
    )


class RuleItem(Base):
    __tablename__ = "rule_item"

    rule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_version: Mapped[str] = mapped_column(Text, primary_key=True)
    category: Mapped[str] = mapped_column(Text, primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    code_origin: Mapped[str] = mapped_column(Text, nullable=False)
    text_verbatim: Mapped[str | None] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    inherited_from_rule: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verification_status: Mapped[str] = mapped_column(Text, nullable=False)
    status_is_verified: Mapped[bool] = mapped_column(
        Boolean,
        Computed("verification_status = 'verified'", persisted=True),
        nullable=False,
    )
    condition_text: Mapped[str | None] = mapped_column(Text)
    components_text: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    rule_refs: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _restrict_fk(
            ["rule_id", "rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_rule_item_rule_id_rule",
        ),
        _restrict_fk(
            ["verification_status"],
            ["verification_status.code"],
            "fk_rule_item_verification_status_verification_status",
        ),
        UniqueConstraint(
            "rule_id",
            "rule_version",
            "category",
            "ordinal",
            name="uq_rule_item_rule_category_ordinal",
        ),
        CheckConstraint(
            "category IN ('preventive_assessments', 'developmental_assessments', "
            "'follow_up_requirements', 'package_component')",
            name="category",
        ),
        CheckConstraint("length(btrim(code)) > 0", name="code_nonempty"),
        CheckConstraint("code_origin IN ('yaml', 'derived_slug')", name="code_origin"),
        CheckConstraint(
            "code_origin = 'yaml' OR text_verbatim IS NOT NULL",
            name="text_verbatim_required_for_slug",
        ),
        CheckConstraint("ordinal >= 1", name="ordinal"),
        CheckConstraint("length(btrim(description)) > 0", name="description_nonempty"),
        CheckConstraint(
            "length(btrim(source_reference)) > 0", name="source_reference_nonempty"
        ),
        Index("ix_rule_item_verification_status", "verification_status"),
        Index("ix_rule_item_code", "code"),
        {"schema": SCHEMA},
    )


class RuleOpenQuestion(Base):
    __tablename__ = "rule_open_question"

    rule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_version: Mapped[str] = mapped_column(Text, primary_key=True)
    oq_id: Mapped[str] = mapped_column(Text, primary_key=True)

    __table_args__ = (
        _restrict_fk(
            ["rule_id", "rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_rule_open_question_rule_id_rule",
        ),
        _restrict_fk(
            ["oq_id"],
            ["open_question.oq_id"],
            "fk_rule_open_question_oq_id_open_question",
        ),
        Index("ix_rule_open_question_oq_id", "oq_id"),
        {"schema": SCHEMA},
    )


class RuleItemOpenQuestion(Base):
    __tablename__ = "rule_item_open_question"

    rule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_version: Mapped[str] = mapped_column(Text, primary_key=True)
    category: Mapped[str] = mapped_column(Text, primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    oq_id: Mapped[str] = mapped_column(Text, primary_key=True)

    __table_args__ = (
        _restrict_fk(
            ["rule_id", "rule_version", "category", "code"],
            [
                "rule_item.rule_id",
                "rule_item.rule_version",
                "rule_item.category",
                "rule_item.code",
            ],
            "fk_rule_item_open_question_rule_id_rule_item",
        ),
        _restrict_fk(
            ["oq_id"],
            ["open_question.oq_id"],
            "fk_rule_item_open_question_oq_id_open_question",
        ),
        Index("ix_rule_item_open_question_oq_id", "oq_id"),
        {"schema": SCHEMA},
    )
