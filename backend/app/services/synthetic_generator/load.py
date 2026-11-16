"""Idempotent PostgreSQL loader for `SyntheticDataset` (`app.services.synthetic_generator.load`)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import insert, text
from sqlalchemy.engine import Connection, Engine

import app.models.synthetic  # noqa: F401
from app.models.base import Base
from app.services.synthetic_generator.generator import (
    SyntheticDataset,
    generate_synthetic_dataset,
)

CHUNK_SIZE = 2000

DELETE_ORDER = (
    "outreach_event",
    "care_gap_review",
    "care_gap",
    "referral",
    "assessment",
    "component_result",
    "well_child_visit",
    "ifhas_screening",
    "appointment",
    "evaluation_reason",
    "eligibility_evaluation",
    "history_availability",
    "consent",
    "guardian",
    "patient",
    "facility_service_profile",
    "evaluation_run",
    "generation_run",
)


def _synth_tables() -> dict[str, Any]:
    return {t.name: t for t in Base.metadata.tables.values() if t.schema == "synthetic"}


def _load_with_sa_conn(
    conn: Any,
    ds: SyntheticDataset,
    *,
    reset_existing_run: bool = True,
) -> dict[str, Any]:
    run_id = ds.generation_run["run_id"]
    tables = _synth_tables()

    # Align rule_bundle_load_id with latest clinical.rule_load row when available
    latest_load_id = conn.execute(
        text("SELECT load_id FROM clinical.rule_load ORDER BY load_id DESC LIMIT 1")
    ).scalar_one_or_none()
    gen_run = dict(ds.generation_run)
    eval_run = dict(ds.evaluation_run)
    if latest_load_id is not None:
        gen_run["rule_bundle_load_id"] = int(latest_load_id)
        eval_run["rule_bundle_load_id"] = int(latest_load_id)

    # Align simulated facility_service_profile.facility_id values with official.facility rows when available
    fac_ids = list(
        conn.execute(
            text("SELECT facility_id FROM official.facility ORDER BY facility_id ASC LIMIT 3")
        ).scalars()
    )
    fsp_rows = [dict(r) for r in ds.facility_service_profiles]
    if len(fac_ids) >= len(fsp_rows):
        for idx, row in enumerate(fsp_rows):
            row["facility_id"] = int(fac_ids[idx])

    if reset_existing_run:
        conn.execute(text("SET LOCAL pulsereach.allow_synthetic_reset = 'on'"))
        try:
            conn.execute(
                text(
                    "UPDATE synthetic.ifhas_screening SET appointment_id = NULL WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            )
            conn.execute(
                text(
                    "UPDATE synthetic.well_child_visit SET appointment_id = NULL WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            )
            conn.execute(
                text(
                    "UPDATE synthetic.outreach_event SET appointment_id = NULL WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            )
            conn.execute(
                text(
                    "UPDATE synthetic.appointment SET care_gap_id = NULL WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            )
            for tbl_name in DELETE_ORDER:
                conn.execute(
                    text(f"DELETE FROM synthetic.{tbl_name} WHERE run_id = :run_id"),
                    {"run_id": run_id},
                )
        finally:
            conn.execute(text("SET LOCAL pulsereach.allow_synthetic_reset = 'off'"))

    def _insert_table(table_name: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        tbl = tables[table_name]
        for i in range(0, len(rows), CHUNK_SIZE):
            conn.execute(insert(tbl), rows[i : i + CHUNK_SIZE])

    _insert_table("generation_run", [gen_run])
    _insert_table("evaluation_run", [eval_run])
    _insert_table("facility_service_profile", fsp_rows)
    _insert_table("patient", ds.patients)
    _insert_table("guardian", ds.guardians)
    _insert_table("consent", ds.consents)
    _insert_table("history_availability", ds.history_availabilities)
    _insert_table("eligibility_evaluation", ds.eligibility_evaluations)
    _insert_table("evaluation_reason", ds.evaluation_reasons)

    # Break circular FK between appointment.care_gap_id and care_gap on insert
    apts_without_gap = [{**a, "care_gap_id": None} for a in ds.appointments]
    _insert_table("appointment", apts_without_gap)
    _insert_table("ifhas_screening", ds.ifhas_screenings)
    _insert_table("well_child_visit", ds.well_child_visits)
    _insert_table("component_result", ds.component_results)
    _insert_table("assessment", ds.assessments)
    _insert_table("referral", ds.referrals)
    _insert_table("care_gap", ds.care_gaps)

    for a in ds.appointments:
        if a.get("care_gap_id") is not None:
            conn.execute(
                text(
                    "UPDATE synthetic.appointment SET care_gap_id = :care_gap_id "
                    "WHERE run_id = :run_id AND appointment_id = :appointment_id"
                ),
                {
                    "care_gap_id": a["care_gap_id"],
                    "run_id": run_id,
                    "appointment_id": a["appointment_id"],
                },
            )

    _insert_table("care_gap_review", ds.care_gap_reviews)
    _insert_table("outreach_event", ds.outreach_events)

    return {
        "run_id": run_id,
        "patients": len(ds.patients),
        "eligibility_evaluations": len(ds.eligibility_evaluations),
        "care_gaps": len(ds.care_gaps),
    }


def load_synthetic_dataset(
    conn: Engine | Connection | Any,
    dataset: SyntheticDataset | None = None,
    *,
    reset_existing_run: bool = True,
) -> dict[str, Any]:
    """Load `SyntheticDataset` into the 18 `synthetic.*` PostgreSQL tables inside a transaction."""
    ds = dataset if dataset is not None else generate_synthetic_dataset()
    if isinstance(conn, Engine):
        with conn.begin() as sa_conn:
            return _load_with_sa_conn(sa_conn, ds, reset_existing_run=reset_existing_run)
    return _load_with_sa_conn(conn, ds, reset_existing_run=reset_existing_run)
