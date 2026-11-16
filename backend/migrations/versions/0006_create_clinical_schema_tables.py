"""create clinical schema tables, views, and append-only triggers

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-16

Creates the 12 tables of the `clinical` schema (`docs/phase-3-database-design.md` §4,
`docs/erd/clinical-schema-erd.md`), the 3 clinical authority/current views
(`v_rule_current`, `v_rule_authority`, `v_rule_item_effective_authority`), and
append-only enforcement triggers on `rule_load`, `rule`, `rule_condition`,
`rule_item`, `rule_open_question`, and `rule_item_open_question`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "clinical"
SHA256 = r"^[0-9a-f]{64}$"
SEMVER = r"^[0-9]+\.[0-9]+\.[0-9]+$"

APPEND_ONLY_TABLES = (
    "rule_load",
    "rule",
    "rule_condition",
    "rule_item",
    "rule_open_question",
    "rule_item_open_question",
)


def _fk(
    cols: list[str], ref: list[str], name: str
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        cols,
        [f"{SCHEMA}.{r}" for r in ref],
        name=name,
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )


def _pdate_checks(table: str, prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(
            f"{prefix}_precision IN ('day', 'month', 'year', 'unknown')",
            name=f"ck_{table}_{prefix}_precision",
        ),
        sa.CheckConstraint(
            f"(({prefix}_precision = 'unknown') = ({prefix}_text IS NULL)) "
            f"AND (({prefix}_precision = 'day') = ({prefix}_from IS NOT NULL))",
            name=f"ck_{table}_{prefix}_triple",
        ),
    ]


def upgrade() -> None:
    # 1. standard
    op.create_table(
        "standard",
        sa.Column(
            "standard_id",
            sa.SmallInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("document_ref", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("publication_date_text", sa.Text(), nullable=True),
        sa.Column("publication_date_precision", sa.Text(), nullable=False),
        sa.Column("publication_date_from", sa.Date(), nullable=True),
        sa.Column("effective_date_text", sa.Text(), nullable=True),
        sa.Column("effective_date_precision", sa.Text(), nullable=False),
        sa.Column("effective_date_from", sa.Date(), nullable=True),
        sa.Column("effective_date_note", sa.Text(), nullable=True),
        sa.Column("revision_date_text", sa.Text(), nullable=True),
        sa.Column("pdf_pages", sa.SmallInteger(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("contact", sa.Text(), nullable=True),
        sa.Column("status_note", sa.Text(), nullable=True),
        sa.Column("manifest_source_id", sa.Text(), nullable=True),
        sa.Column("acquisition_state", sa.Text(), nullable=False),
        sa.Column("local_copy_sha256", sa.CHAR(64), nullable=True),
        sa.PrimaryKeyConstraint("standard_id", name="pk_standard"),
        sa.UniqueConstraint(
            "source_name",
            "source_version",
            name="uq_standard_source_name_source_version",
        ),
        sa.UniqueConstraint("document_ref", name="uq_standard_document_ref"),
        *_pdate_checks("standard", "publication_date"),
        *_pdate_checks("standard", "effective_date"),
        sa.CheckConstraint(
            "effective_date_precision <> 'unknown' OR effective_date_note IS NOT NULL",
            name="ck_standard_effective_date_note",
        ),
        sa.CheckConstraint(
            "pdf_pages IS NULL OR pdf_pages > 0", name="ck_standard_pdf_pages"
        ),
        sa.CheckConstraint(
            "acquisition_state IN ('blocked', 'document_obtained')",
            name="ck_standard_acquisition_state",
        ),
        sa.CheckConstraint(
            f"local_copy_sha256 IS NULL OR (acquisition_state = 'document_obtained' AND local_copy_sha256 ~ '{SHA256}')",
            name="ck_standard_local_copy_sha256",
        ),
        schema=SCHEMA,
    )

    # 2. rule_load
    op.create_table(
        "rule_load",
        sa.Column(
            "load_id", sa.BigInteger(), sa.Identity(always=True), nullable=False
        ),
        sa.Column(
            "loaded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("loader_version", sa.Text(), nullable=False),
        sa.Column("bundle_sha256", sa.CHAR(64), nullable=False),
        sa.Column("file_hashes", postgresql.JSONB(), nullable=False),
        sa.Column("config_versions", postgresql.JSONB(), nullable=False),
        sa.Column("git_commit", sa.Text(), nullable=True),
        sa.Column("clinical_review_status", sa.Text(), nullable=False),
        sa.Column("rules_loaded", sa.Integer(), nullable=False),
        sa.Column("rules_added", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("load_id", name="pk_rule_load"),
        sa.CheckConstraint(
            f"bundle_sha256 ~ '{SHA256}'", name="ck_rule_load_bundle_sha256"
        ),
        sa.CheckConstraint("rules_loaded >= 0", name="ck_rule_load_rules_loaded"),
        sa.CheckConstraint(
            "rules_added >= 0 AND rules_added <= rules_loaded",
            name="ck_rule_load_rules_added",
        ),
        schema=SCHEMA,
    )

    # 3. verification_status
    op.create_table(
        "verification_status",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("may_drive_decisions", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("code", name="pk_verification_status"),
        sa.CheckConstraint(
            "code IN ('verified', 'reported', 'unresolved')",
            name="ck_verification_status_code",
        ),
        sa.CheckConstraint(
            "may_drive_decisions = (code = 'verified')",
            name="ck_verification_status_may_drive_decisions",
        ),
        schema=SCHEMA,
    )

    # 4. evaluation_status
    op.create_table(
        "evaluation_status",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("requires_text", sa.Text(), nullable=True),
        sa.Column(
            "never_inferred_from", postgresql.ARRAY(sa.Text()), nullable=True
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("code", name="pk_evaluation_status"),
        sa.UniqueConstraint("sort_order", name="uq_evaluation_status_sort_order"),
        sa.CheckConstraint(
            "code IN ('eligible', 'not_eligible', 'due', 'upcoming', 'overdue', "
            "'completed', 'unknown', 'insufficient_information', 'requires_clinical_review')",
            name="ck_evaluation_status_code",
        ),
        sa.CheckConstraint("sort_order >= 1", name="ck_evaluation_status_sort_order"),
        schema=SCHEMA,
    )

    # 5. reason_code
    op.create_table(
        "reason_code",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("code", name="pk_reason_code"),
        sa.CheckConstraint(
            "length(btrim(code)) > 0", name="ck_reason_code_code_nonempty"
        ),
        schema=SCHEMA,
    )

    # 6. guard
    op.create_table(
        "guard",
        sa.Column("guard_id", sa.Text(), nullable=False),
        sa.Column("when_text", sa.Text(), nullable=False),
        sa.Column("result_status", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("guard_id", name="pk_guard"),
        _fk(
            ["result_status"],
            ["evaluation_status.code"],
            "fk_guard_result_status_evaluation_status",
        ),
        _fk(
            ["reason_code"],
            ["reason_code.code"],
            "fk_guard_reason_code_reason_code",
        ),
        schema=SCHEMA,
    )

    # 7. open_question
    op.create_table(
        "open_question",
        sa.Column("oq_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("affects_raw", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("resolve_via", sa.Text(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_on", sa.Date(), nullable=True),
        sa.Column("first_load_id", sa.BigInteger(), nullable=False),
        sa.Column("last_changed_load_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("oq_id", name="pk_open_question"),
        _fk(
            ["first_load_id"],
            ["rule_load.load_id"],
            "fk_open_question_first_load_id_rule_load",
        ),
        _fk(
            ["last_changed_load_id"],
            ["rule_load.load_id"],
            "fk_open_question_last_changed_load_id_rule_load",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved')", name="ck_open_question_status"
        ),
        sa.CheckConstraint(
            "resolved_on IS NULL OR resolution IS NOT NULL",
            name="ck_open_question_resolved_on_requires_resolution",
        ),
        sa.CheckConstraint(
            "(status = 'resolved') = (resolution IS NOT NULL AND resolved_on IS NOT NULL)",
            name="ck_open_question_status_resolution_consistency",
        ),
        schema=SCHEMA,
    )

    # 8. rule
    op.create_table(
        "rule",
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column(
            "ver_major",
            sa.Integer(),
            sa.Computed("split_part(rule_version, '.', 1)::integer", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "ver_minor",
            sa.Integer(),
            sa.Computed("split_part(rule_version, '.', 2)::integer", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "ver_patch",
            sa.Integer(),
            sa.Computed("split_part(rule_version, '.', 3)::integer", persisted=True),
            nullable=False,
        ),
        sa.Column("pathway", sa.Text(), nullable=False),
        sa.Column("rule_type", sa.Text(), nullable=True),
        sa.Column("standard_id", sa.SmallInteger(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.Text(), nullable=False),
        sa.Column(
            "requires_clinical_review",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_authoritative",
            sa.Boolean(),
            sa.Computed(
                "verification_status = 'verified' AND NOT requires_clinical_review",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("effective_date_text", sa.Text(), nullable=True),
        sa.Column("effective_date_precision", sa.Text(), nullable=False),
        sa.Column("effective_date_from", sa.Date(), nullable=True),
        sa.Column("effective_date_note", sa.Text(), nullable=True),
        sa.Column("last_reviewed", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("history", postgresql.JSONB(), nullable=True),
        sa.Column("content_sha256", sa.CHAR(64), nullable=False),
        sa.Column("yaml_path", sa.Text(), nullable=False),
        sa.Column("load_id", sa.BigInteger(), nullable=False),
        sa.Column("package_name", sa.Text(), nullable=True),
        sa.Column("package_group", sa.Text(), nullable=True),
        sa.Column("age_min_years", sa.SmallInteger(), nullable=True),
        sa.Column("age_max_years", sa.SmallInteger(), nullable=True),
        sa.Column("age_as_printed", sa.Text(), nullable=True),
        sa.Column("sexes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("frequency_type", sa.Text(), nullable=True),
        sa.Column("interval_value", sa.SmallInteger(), nullable=True),
        sa.Column("interval_unit", sa.Text(), nullable=True),
        sa.Column("visit_number", sa.SmallInteger(), nullable=True),
        sa.Column("visit_id", sa.Text(), nullable=True),
        sa.Column("recommended_age_months", sa.SmallInteger(), nullable=True),
        sa.Column("age_band", sa.Text(), nullable=True),
        sa.Column("instrument", sa.Text(), nullable=True),
        sa.Column("score_min", sa.Numeric(), nullable=True),
        sa.Column("score_max", sa.Numeric(), nullable=True),
        sa.Column("timing_value", sa.SmallInteger(), nullable=True),
        sa.Column("timing_unit", sa.Text(), nullable=True),
        sa.Column("timing_reference_event", sa.Text(), nullable=True),
        sa.Column("gate_attribute", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("rule_id", "rule_version", name="pk_rule"),
        _fk(["standard_id"], ["standard.standard_id"], "fk_rule_standard_id_standard"),
        _fk(
            ["verification_status"],
            ["verification_status.code"],
            "fk_rule_verification_status_verification_status",
        ),
        _fk(["load_id"], ["rule_load.load_id"], "fk_rule_load_id_rule_load"),
        sa.CheckConstraint(
            f"rule_version ~ '{SEMVER}'", name="ck_rule_rule_version_semver"
        ),
        sa.CheckConstraint(
            "pathway IN ('ifhas', 'well_child')", name="ck_rule_pathway"
        ),
        sa.CheckConstraint(
            "verification_status <> 'unresolved' OR requires_clinical_review",
            name="ck_rule_unresolved_requires_review",
        ),
        sa.CheckConstraint(
            "length(btrim(source_reference)) > 0",
            name="ck_rule_source_reference_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(description)) > 0", name="ck_rule_description_nonempty"
        ),
        *_pdate_checks("rule", "effective_date"),
        sa.CheckConstraint(
            "effective_date_precision <> 'unknown' OR effective_date_note IS NOT NULL",
            name="ck_rule_effective_date_note",
        ),
        sa.CheckConstraint(
            f"content_sha256 ~ '{SHA256}'", name="ck_rule_content_sha256"
        ),
        sa.CheckConstraint(
            "age_min_years IS NULL OR age_max_years IS NULL OR age_min_years <= age_max_years",
            name="ck_rule_age_years_bounds",
        ),
        sa.CheckConstraint(
            "sexes IS NULL OR (cardinality(sexes) > 0 AND sexes <@ ARRAY['female','male']::text[])",
            name="ck_rule_sexes_values",
        ),
        sa.CheckConstraint(
            "frequency_type IN ('recurring', 'once_per_lifetime')",
            name="ck_rule_frequency_type",
        ),
        sa.CheckConstraint(
            "interval_value IS NULL OR interval_value > 0",
            name="ck_rule_interval_value",
        ),
        sa.CheckConstraint(
            "(frequency_type = 'recurring' AND interval_value IS NOT NULL AND interval_unit IS NOT NULL) "
            "OR (frequency_type = 'once_per_lifetime' AND interval_value IS NULL AND interval_unit IS NULL) "
            "OR (frequency_type IS NULL AND interval_value IS NULL AND interval_unit IS NULL)",
            name="ck_rule_frequency_interval_consistency",
        ),
        sa.CheckConstraint(
            "visit_number IS NULL OR visit_number BETWEEN 1 AND 14",
            name="ck_rule_visit_number",
        ),
        sa.CheckConstraint(
            "recommended_age_months IS NULL OR recommended_age_months > 0",
            name="ck_rule_recommended_age_months",
        ),
        sa.CheckConstraint(
            "score_min IS NULL OR score_max IS NULL OR score_min <= score_max",
            name="ck_rule_score_bounds",
        ),
        sa.CheckConstraint(
            "timing_value IS NULL OR timing_value > 0", name="ck_rule_timing_value"
        ),
        sa.CheckConstraint(
            "timing_unit IN ('days', 'working_days', 'weeks', 'months', 'years')",
            name="ck_rule_timing_unit",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_rule_pathway_rule_type", "rule", ["pathway", "rule_type"], schema=SCHEMA
    )
    op.create_index(
        "ix_rule_verification_status", "rule", ["verification_status"], schema=SCHEMA
    )
    op.create_index(
        "ix_rule_is_authoritative", "rule", ["is_authoritative"], schema=SCHEMA
    )
    op.create_index("ix_rule_package_group", "rule", ["package_group"], schema=SCHEMA)
    op.create_index("ix_rule_visit_number", "rule", ["visit_number"], schema=SCHEMA)
    op.create_index("ix_rule_instrument", "rule", ["instrument"], schema=SCHEMA)
    op.create_index("ix_rule_standard_id", "rule", ["standard_id"], schema=SCHEMA)
    op.create_index("ix_rule_load_id", "rule", ["load_id"], schema=SCHEMA)

    # 9. rule_condition
    op.create_table(
        "rule_condition",
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("condition_ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("as_printed", sa.Text(), nullable=False),
        sa.Column("machine_evaluable", sa.Boolean(), nullable=False),
        sa.Column("attribute", sa.Text(), nullable=True),
        sa.Column("required_value", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint(
            "rule_id", "rule_version", "condition_ordinal", name="pk_rule_condition"
        ),
        _fk(
            ["rule_id", "rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_rule_condition_rule_id_rule",
        ),
        sa.CheckConstraint(
            "condition_ordinal >= 1", name="ck_rule_condition_condition_ordinal"
        ),
        sa.CheckConstraint(
            "kind IN ('inclusion', 'exclusion')", name="ck_rule_condition_kind"
        ),
        sa.CheckConstraint(
            "length(btrim(as_printed)) > 0",
            name="ck_rule_condition_as_printed_nonempty",
        ),
        sa.CheckConstraint(
            "NOT machine_evaluable OR (attribute IS NOT NULL AND required_value IS NOT NULL)",
            name="ck_rule_condition_machine_evaluable_fields",
        ),
        sa.CheckConstraint(
            "kind <> 'exclusion' OR NOT machine_evaluable",
            name="ck_rule_condition_exclusion_not_machine_evaluable",
        ),
        schema=SCHEMA,
    )

    # 10. rule_item
    op.create_table(
        "rule_item",
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("code_origin", sa.Text(), nullable=False),
        sa.Column("text_verbatim", sa.Text(), nullable=True),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("inherited_from_rule", sa.Boolean(), nullable=False),
        sa.Column("verification_status", sa.Text(), nullable=False),
        sa.Column(
            "status_is_verified",
            sa.Boolean(),
            sa.Computed("verification_status = 'verified'", persisted=True),
            nullable=False,
        ),
        sa.Column("condition_text", sa.Text(), nullable=True),
        sa.Column("components_text", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("rule_refs", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint(
            "rule_id", "rule_version", "category", "code", name="pk_rule_item"
        ),
        _fk(
            ["rule_id", "rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_rule_item_rule_id_rule",
        ),
        _fk(
            ["verification_status"],
            ["verification_status.code"],
            "fk_rule_item_verification_status_verification_status",
        ),
        sa.UniqueConstraint(
            "rule_id",
            "rule_version",
            "category",
            "ordinal",
            name="uq_rule_item_rule_category_ordinal",
        ),
        sa.CheckConstraint(
            "category IN ('preventive_assessments', 'developmental_assessments', "
            "'follow_up_requirements', 'package_component')",
            name="ck_rule_item_category",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0", name="ck_rule_item_code_nonempty"
        ),
        sa.CheckConstraint(
            "code_origin IN ('yaml', 'derived_slug')", name="ck_rule_item_code_origin"
        ),
        sa.CheckConstraint(
            "code_origin = 'yaml' OR text_verbatim IS NOT NULL",
            name="ck_rule_item_text_verbatim_required_for_slug",
        ),
        sa.CheckConstraint("ordinal >= 1", name="ck_rule_item_ordinal"),
        sa.CheckConstraint(
            "length(btrim(description)) > 0",
            name="ck_rule_item_description_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(source_reference)) > 0",
            name="ck_rule_item_source_reference_nonempty",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_rule_item_verification_status",
        "rule_item",
        ["verification_status"],
        schema=SCHEMA,
    )
    op.create_index("ix_rule_item_code", "rule_item", ["code"], schema=SCHEMA)

    # 11. rule_open_question
    op.create_table(
        "rule_open_question",
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("oq_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "rule_id", "rule_version", "oq_id", name="pk_rule_open_question"
        ),
        _fk(
            ["rule_id", "rule_version"],
            ["rule.rule_id", "rule.rule_version"],
            "fk_rule_open_question_rule_id_rule",
        ),
        _fk(
            ["oq_id"],
            ["open_question.oq_id"],
            "fk_rule_open_question_oq_id_open_question",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_rule_open_question_oq_id", "rule_open_question", ["oq_id"], schema=SCHEMA
    )

    # 12. rule_item_open_question
    op.create_table(
        "rule_item_open_question",
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("oq_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "rule_id",
            "rule_version",
            "category",
            "code",
            "oq_id",
            name="pk_rule_item_open_question",
        ),
        _fk(
            ["rule_id", "rule_version", "category", "code"],
            [
                "rule_item.rule_id",
                "rule_item.rule_version",
                "rule_item.category",
                "rule_item.code",
            ],
            "fk_rule_item_open_question_rule_id_rule_item",
        ),
        _fk(
            ["oq_id"],
            ["open_question.oq_id"],
            "fk_rule_item_open_question_oq_id_open_question",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_rule_item_open_question_oq_id",
        "rule_item_open_question",
        ["oq_id"],
        schema=SCHEMA,
    )

    # Views (docs/erd/clinical-schema-erd.md §3 & docs/mappings/clinical-yaml-to-database-mapping.md §4)
    op.execute(
        """
        CREATE VIEW clinical.v_rule_current AS
        SELECT DISTINCT ON (rule_id)
            r.*
        FROM clinical.rule r
        ORDER BY r.rule_id, r.ver_major DESC, r.ver_minor DESC, r.ver_patch DESC;
        """
    )

    op.execute(
        """
        CREATE VIEW clinical.v_rule_authority AS
        SELECT
            r.rule_id,
            r.rule_version,
            r.pathway,
            r.rule_type,
            r.verification_status,
            r.requires_clinical_review,
            r.is_authoritative,
            array_remove(ARRAY[
                CASE WHEN r.verification_status <> 'verified'
                     THEN format('verification_status is %L (only ''verified'' may drive decisions)', r.verification_status)
                END,
                CASE WHEN r.requires_clinical_review
                     THEN 'it is flagged requires_clinical_review'
                END
            ], NULL) AS non_authoritative_reasons
        FROM clinical.rule r;
        """
    )

    op.execute(
        """
        CREATE VIEW clinical.v_rule_item_effective_authority AS
        SELECT
            i.*,
            r.is_authoritative AS parent_is_authoritative,
            (i.status_is_verified AND r.is_authoritative) AS effective_authority
        FROM clinical.rule_item i
        JOIN clinical.rule r USING (rule_id, rule_version);
        """
    )

    # Append-only trigger function and triggers
    op.execute(
        """
        CREATE FUNCTION clinical.reject_append_only_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'clinical.% is append-only; % is not permitted', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'integrity_constraint_violation';
        END $$;
        """
    )

    for tbl in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{tbl}_append_only
            BEFORE UPDATE OR DELETE ON clinical.{tbl}
            FOR EACH ROW EXECUTE FUNCTION clinical.reject_append_only_mutation();
            """
        )


def downgrade() -> None:
    for tbl in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_append_only ON clinical.{tbl};")
    op.execute("DROP FUNCTION IF EXISTS clinical.reject_append_only_mutation();")

    op.execute("DROP VIEW IF EXISTS clinical.v_rule_item_effective_authority;")
    op.execute("DROP VIEW IF EXISTS clinical.v_rule_authority;")
    op.execute("DROP VIEW IF EXISTS clinical.v_rule_current;")

    for tbl in (
        "rule_item_open_question",
        "rule_open_question",
        "rule_item",
        "rule_condition",
        "rule",
        "open_question",
        "guard",
        "reason_code",
        "evaluation_status",
        "verification_status",
        "rule_load",
        "standard",
    ):
        op.drop_table(tbl, schema=SCHEMA)
