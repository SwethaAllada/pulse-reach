"""Database loader for the 12 `clinical` tables (`docs/mappings/clinical-yaml-to-database-mapping.md`).

Implements:
- Idempotent loading of standards, vocabularies, open questions, rules, conditions, items, and associations
- Append-only version and `content_sha256` hash guard (`check_version_and_hash_guards`)
- Post-load authority recomputation verification against `clinical.v_rule_authority`
  and `clinical.v_rule_item_effective_authority` (LV-2)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from app.db.session import get_engine
from app.models import clinical as m

from .parse import (
    PROJECTION_COLUMNS,
    FatalError,
    ParsedClinicalBundle,
    parse_clinical_bundle,
    parse_semver,
)


@dataclass(frozen=True)
class ClinicalLoadSummary:
    load_id: int
    bundle_sha256: str
    rules_loaded: int
    rules_added: int
    authoritative_rules: int
    non_authoritative_rules: int
    conditions_loaded: int
    items_loaded: int
    open_questions_loaded: int
    rule_open_questions_loaded: int
    rule_item_open_questions_loaded: int


def check_version_and_hash_guards(
    existing_rules: Mapping[tuple[str, str], str],
    bundle: ParsedClinicalBundle,
) -> list[dict[str, Any]]:
    """Validate version/hash invariants against existing `(rule_id, rule_version) -> content_sha256`.

    - Same `(rule_id, rule_version)`, different `content_sha256` -> raises `FatalError` ("without a version bump")
    - Same `(rule_id, rule_version)`, same `content_sha256` -> no-op (idempotent)
    - Rule ID present in `existing_rules` but absent from `bundle.rules` -> raises `FatalError` ("vanished")
    - `rule_version` lower than the highest existing version for that `rule_id` -> raises `FatalError` ("downgrade")

    Returns the list of newly added rule dicts from `bundle.rules`.
    """
    yaml_by_id: dict[str, dict[str, Any]] = {r["rule_id"]: r for r in bundle.rules}
    existing_by_id: dict[str, list[tuple[tuple[int, int, int], str, str]]] = {}
    for (rid, rver), sha in existing_rules.items():
        existing_by_id.setdefault(rid, []).append((parse_semver(rver), rver, sha))

    # 1. Check no rule vanished from YAML (CU-12)
    vanished = sorted(set(existing_by_id) - set(yaml_by_id))
    if vanished:
        raise FatalError(
            f"rule(s) present in database but absent from YAML (vanished): {', '.join(vanished)}"
        )

    new_rules: list[dict[str, Any]] = []
    for r in bundle.rules:
        rid = r["rule_id"]
        rver = r["rule_version"]
        sha = r["content_sha256"]
        key = (rid, rver)
        if key in existing_rules:
            if existing_rules[key] != sha:
                raise FatalError(
                    f"rule '{rid}' version '{rver}' content_sha256 changed without a version bump"
                )
            continue

        # Not in existing_rules: check version ordering against highest existing version for rid
        if rid in existing_by_id:
            highest_sem, highest_str, _ = max(existing_by_id[rid], key=lambda x: x[0])
            cur_sem = (r["ver_major"], r["ver_minor"], r["ver_patch"])
            if cur_sem < highest_sem:
                raise FatalError(
                    f"rule '{rid}' YAML version {rver} is lower than highest loaded version {highest_str} (downgrade)"
                )
        new_rules.append(r)

    return new_rules


def _load_standards(conn: Connection, bundle: ParsedClinicalBundle) -> dict[tuple[str, str], int]:
    std_map: dict[tuple[str, str], int] = {}
    for s in bundle.standards:
        stmt = (
            pg_insert(m.Standard)
            .values(**s)
            .on_conflict_do_update(
                constraint="uq_standard_document_ref",
                set_={k: s[k] for k in s if k != "document_ref"},
            )
            .returning(m.Standard.standard_id)
        )
        sid = conn.execute(stmt).scalar_one()
        std_map[(s["source_name"], s["source_version"])] = int(sid)
    return std_map


def _load_vocabularies(conn: Connection, bundle: ParsedClinicalBundle) -> None:
    for vs in bundle.verification_statuses:
        stmt = (
            pg_insert(m.VerificationStatus)
            .values(**vs)
            .on_conflict_do_update(
                index_elements=[m.VerificationStatus.code],
                set_={
                    "definition": vs["definition"],
                    "may_drive_decisions": vs["may_drive_decisions"],
                },
            )
        )
        conn.execute(stmt)

    for es in bundle.evaluation_statuses:
        stmt = (
            pg_insert(m.EvaluationStatus)
            .values(**es)
            .on_conflict_do_update(
                index_elements=[m.EvaluationStatus.code],
                set_={
                    "definition": es["definition"],
                    "requires_text": es["requires_text"],
                    "never_inferred_from": es["never_inferred_from"],
                    "sort_order": es["sort_order"],
                },
            )
        )
        conn.execute(stmt)

    for rc in bundle.reason_codes:
        stmt = (
            pg_insert(m.ReasonCode)
            .values(**rc)
            .on_conflict_do_update(
                index_elements=[m.ReasonCode.code],
                set_={"description": rc["description"]},
            )
        )
        conn.execute(stmt)

    for g in bundle.guards:
        stmt = (
            pg_insert(m.Guard)
            .values(**g)
            .on_conflict_do_update(
                index_elements=[m.Guard.guard_id],
                set_={
                    "when_text": g["when_text"],
                    "result_status": g["result_status"],
                    "reason_code": g["reason_code"],
                    "note": g["note"],
                },
            )
        )
        conn.execute(stmt)


def _load_open_questions(conn: Connection, bundle: ParsedClinicalBundle, load_id: int) -> None:
    existing = {
        row.oq_id: row
        for row in conn.execute(select(m.OpenQuestion)).all()
    }
    for oq in bundle.open_questions:
        qid = oq["oq_id"]
        if qid not in existing:
            conn.execute(
                insert(m.OpenQuestion).values(
                    **oq, first_load_id=load_id, last_changed_load_id=load_id
                )
            )
        else:
            prev = existing[qid]
            changed = any(
                getattr(prev, col) != oq[col]
                for col in (
                    "category",
                    "status",
                    "title",
                    "detail",
                    "affects_raw",
                    "resolve_via",
                    "resolution",
                    "resolved_on",
                )
            )
            if changed:
                conn.execute(
                    update(m.OpenQuestion)
                    .where(m.OpenQuestion.oq_id == qid)
                    .values(**oq, last_changed_load_id=load_id)
                )


def run(
    engine: Engine | None = None,
    rules_dir: Path | None = None,
    manifest_path: Path | None = None,
) -> ClinicalLoadSummary:
    """Validate and load the clinical YAML bundle into `clinical.*` in a single transaction."""
    bundle = parse_clinical_bundle(rules_dir=rules_dir, manifest_path=manifest_path)
    eng = engine or get_engine()

    with eng.begin() as conn:
        existing_rows = conn.execute(
            select(m.Rule.rule_id, m.Rule.rule_version, m.Rule.content_sha256)
        ).all()
        existing_map = {(r.rule_id, r.rule_version): r.content_sha256 for r in existing_rows}

        new_rules = check_version_and_hash_guards(existing_map, bundle)
        new_keys = {(r["rule_id"], r["rule_version"]) for r in new_rules}

        # Insert rule_load row
        load_id = int(
            conn.execute(
                insert(m.RuleLoad)
                .values(
                    loader_version=bundle.loader_version,
                    bundle_sha256=bundle.bundle_sha256,
                    file_hashes=bundle.file_hashes,
                    config_versions=bundle.config_versions,
                    git_commit=bundle.git_commit,
                    clinical_review_status=bundle.clinical_review_status,
                    rules_loaded=len(bundle.rules),
                    rules_added=len(new_rules),
                )
                .returning(m.RuleLoad.load_id)
            ).scalar_one()
        )

        std_map = _load_standards(conn, bundle)
        _load_vocabularies(conn, bundle)
        _load_open_questions(conn, bundle, load_id)

        if new_rules:
            for r in new_rules:
                std_id = std_map[(r["source_name"], r["source_version"])]
                rule_values = {
                    "rule_id": r["rule_id"],
                    "rule_version": r["rule_version"],
                    "pathway": r["pathway"],
                    "rule_type": r["rule_type"],
                    "standard_id": std_id,
                    "source_reference": r["source_reference"],
                    "verification_status": r["verification_status"],
                    "requires_clinical_review": r["requires_clinical_review"],
                    "effective_date_text": r["effective_date_text"],
                    "effective_date_precision": r["effective_date_precision"],
                    "effective_date_from": r["effective_date_from"],
                    "effective_date_note": r["effective_date_note"],
                    "last_reviewed": r["last_reviewed"],
                    "description": r["description"],
                    "notes": r["notes"],
                    "spec": r["spec"],
                    "history": r["history"],
                    "content_sha256": r["content_sha256"],
                    "yaml_path": r["yaml_path"],
                    "load_id": load_id,
                    **{col: r[col] for col in PROJECTION_COLUMNS},
                }
                conn.execute(insert(m.Rule).values(**rule_values))

            new_conds = [
                c
                for c in bundle.conditions
                if (c["rule_id"], c["rule_version"]) in new_keys
            ]
            if new_conds:
                conn.execute(insert(m.RuleCondition), new_conds)

            new_items = [
                {
                    k: v
                    for k, v in i.items()
                    if k not in ("status_is_verified", "effective_authority")
                }
                for i in bundle.items
                if (i["rule_id"], i["rule_version"]) in new_keys
            ]
            if new_items:
                conn.execute(insert(m.RuleItem), new_items)

            new_roqs = [
                roq
                for roq in bundle.rule_open_questions
                if (roq["rule_id"], roq["rule_version"]) in new_keys
            ]
            if new_roqs:
                conn.execute(insert(m.RuleOpenQuestion), new_roqs)

            new_ioqs = [
                ioq
                for ioq in bundle.rule_item_open_questions
                if (ioq["rule_id"], ioq["rule_version"]) in new_keys
            ]
            if new_ioqs:
                conn.execute(insert(m.RuleItemOpenQuestion), new_ioqs)

        # Post-load LV-2 verification against database views
        db_rule_auth = {
            (row.rule_id, row.rule_version): row.is_authoritative
            for row in conn.execute(
                text(
                    "SELECT rule_id, rule_version, is_authoritative FROM clinical.v_rule_authority"
                )
            ).all()
        }
        for r in bundle.rules:
            key = (r["rule_id"], r["rule_version"])
            if db_rule_auth.get(key) != r["is_authoritative"]:
                raise FatalError(f"LV-2 rule authority mismatch in DB for {key}")

        db_item_auth = {
            (row.rule_id, row.rule_version, row.category, row.code): (
                row.effective_authority,
                row.parent_is_authoritative,
            )
            for row in conn.execute(
                text(
                    "SELECT rule_id, rule_version, category, code, effective_authority, parent_is_authoritative "
                    "FROM clinical.v_rule_item_effective_authority"
                )
            ).all()
        }
        for i in bundle.items:
            ikey = (i["rule_id"], i["rule_version"], i["category"], i["code"])
            eff, parent_auth = db_item_auth[ikey]
            if eff != i["effective_authority"]:
                raise FatalError(f"LV-2 item effective_authority mismatch in DB for {ikey}")
            if eff and not parent_auth:
                raise FatalError(f"LV-2 item {ikey} has effective_authority=true under non-authoritative parent")

    auth_count = sum(1 for r in bundle.rules if r["is_authoritative"])
    return ClinicalLoadSummary(
        load_id=load_id,
        bundle_sha256=bundle.bundle_sha256,
        rules_loaded=len(bundle.rules),
        rules_added=len(new_rules),
        authoritative_rules=auth_count,
        non_authoritative_rules=len(bundle.rules) - auth_count,
        conditions_loaded=len(bundle.conditions),
        items_loaded=len(bundle.items),
        open_questions_loaded=len(bundle.open_questions),
        rule_open_questions_loaded=len(bundle.rule_open_questions),
        rule_item_open_questions_loaded=len(bundle.rule_item_open_questions),
    )
